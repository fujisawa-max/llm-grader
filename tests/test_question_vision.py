from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from scoring.api import create_app
from scoring.adapters.pdf_region import PyMuPdfRegionRenderer
from scoring.adapters.question_vision import RuntimeVisionAdapter, normalize_output
from scoring.db import create_session_factory, init_database
from scoring.db.models import QuestionImportVisionResult, QuestionImportDraftNode
from scoring.domain import DomainService
from scoring.pdf_native import canonical_hash, sha256_file
from scoring.question_vision import VisionFallbackService, VisionError
from scoring.vision_policy import VisionRoutingPolicy, crop_geometry, DEFAULT_POLICY


def fixtures():
    spans = [
        {
            "element_id": "a",
            "type": "text",
            "bbox": [30, 50, 40, 65],
            "native_text": "x",
            "quality_signals": {"math_like_candidate": True},
        },
        {
            "element_id": "b",
            "type": "text",
            "bbox": [40, 45, 45, 53],
            "native_text": "3",
            "quality_signals": {"math_like_candidate": True},
        },
    ]
    page = {
        "page_index": 0,
        "width": 300,
        "height": 400,
        "rotation": 0,
        "cropbox": [0, 0, 300, 400],
        "mediabox": [0, 0, 300, 400],
        "elements": spans,
    }
    region = {
        "region_id": "formula-0001",
        "page_index": 0,
        "bbox": [30, 45, 45, 65],
        "source_element_ids": ["a", "b"],
        "assigned_question_key": "q1",
        "routing_evidence": {"math_font_span_count": 2, "superscript_geometry_count": 1},
    }
    draft = {
        "nodes": [
            {
                "stable_key": "q1",
                "ordered_content": [
                    {"type": "formula_region", "region_id": "formula-0001", "order": 1}
                ],
            }
        ],
        "formula_regions": [region],
        "figure_regions": [],
    }
    ir = {"source": {"sha256": "source"}, "pages": [page]}
    return draft, ir


class RoutingTests(unittest.TestCase):
    def test_fragmented_vertical_formula_and_determinism(self):
        d, ir = fixtures()
        original = deepcopy((d, ir))
        plan = VisionRoutingPolicy().build(d, ir)
        self.assertEqual(plan, VisionRoutingPolicy().build(d, ir))
        self.assertEqual((d, ir), original)
        self.assertEqual(plan["routes"][0]["decision"], "VISION_RECOMMENDED")
        self.assertIn("multiple_vertical_positions", plan["routes"][0]["reasons"])

    def test_single_span_with_geometry_only_is_native(self):
        d, ir = fixtures()
        d["formula_regions"][0]["source_element_ids"] = ["a"]
        d["formula_regions"][0]["routing_evidence"] = {"superscript_geometry_count": 1}
        self.assertEqual(
            VisionRoutingPolicy().build(d, ir)["routes"][0]["decision"], "NATIVE_SUFFICIENT"
        )

    def test_no_regions_means_no_requests(self):
        d, ir = fixtures()
        d["formula_regions"] = []
        self.assertEqual(VisionRoutingPolicy().build(d, ir)["vision_request_count"], 0)

    def test_figure_and_missing_anchor(self):
        d, ir = fixtures()
        region = d["formula_regions"].pop()
        region.update(region_id="figure-0001", bbox=[50, 150, 200, 250])
        d["figure_regions"] = [region]
        d["nodes"][0]["ordered_content"][0].update(type="figure_region", region_id="figure-0001")
        self.assertEqual(VisionRoutingPolicy().build(d, ir)["routes"][0]["model_role"], "ocr")
        d["nodes"][0]["ordered_content"] = []
        self.assertEqual(VisionRoutingPolicy().build(d, ir)["routes"][0]["decision"], "AMBIGUOUS")

    def test_pixel_limits_and_full_page_formula_rejected(self):
        d, ir = fixtures()
        d["formula_regions"][0]["bbox"] = [0, 0, 300, 400]
        with self.assertRaises(ValueError):
            VisionRoutingPolicy().build(d, ir)
        with self.assertRaises(ValueError):
            VisionRoutingPolicy({"formula_scale": float("nan")})

    def test_neighbor_margin_avoids_prose(self):
        d, ir = fixtures()
        ir["pages"][0]["elements"].append(
            {
                "element_id": "prose",
                "type": "text",
                "bbox": [45.3, 45, 100, 65],
                "native_text": "本文",
            }
        )
        crop = VisionRoutingPolicy().build(d, ir)["routes"][0]["crop"]
        self.assertLess(crop["margins"][2], 0.1)


class RendererTests(unittest.TestCase):
    def test_rotations_crop_offset_and_full_layers(self):
        with tempfile.TemporaryDirectory() as temp:
            for rotation in (0, 90, 180, 270):
                with self.subTest(rotation=rotation):
                    pdf = pymupdf.open()
                    page = pdf.new_page(width=300, height=400)
                    page.draw_rect((70, 100, 130, 130), fill=(1, 0, 0), color=None)
                    page.insert_text((75, 120), "A", color=(0, 0, 0))
                    page.set_cropbox(pymupdf.Rect(40, 50, 280, 380))
                    page.set_rotation(rotation)
                    path = Path(temp) / f"{rotation}.pdf"
                    pdf.save(path)
                    meta = {
                        "cropbox": list(page.cropbox),
                        "mediabox": list(page.mediabox),
                        "rotation": rotation,
                        "elements": [],
                    }
                    config = {**DEFAULT_POLICY, "figure_margin": 3.0}
                    # The real native extraction is crop-local, not media-local.
                    self.assertAlmostEqual(page.get_text("blocks")[0][0], 35, delta=1)
                    route = {
                        "page_index": 0,
                        "region_id": "figure-0001",
                        "region_type": "figure",
                        "crop": crop_geometry(meta, [30, 50, 90, 80], "figure", config),
                    }
                    target = Path(temp) / f"{rotation}.png"
                    result = PyMuPdfRegionRenderer().render(path, meta, route, config, target)
                    pix = pymupdf.Pixmap(target)
                    # Independent oracle: full-page render ONLY in the test.
                    full = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    x0, y0, x1, y1 = route["crop"]["pixel_bbox"]
                    self.assertEqual((pix.width, pix.height), (x1 - x0, y1 - y0))
                    expected = b"".join(
                        full.samples[y * full.stride + x0 * 3 : y * full.stride + x1 * 3]
                        for y in range(y0, y1)
                    )
                    self.assertEqual(pix.samples, expected)
                    red = sum(
                        pix.samples[i] > 200 and pix.samples[i + 1] < 50
                        for i in range(0, len(pix.samples), 3)
                    )
                    self.assertGreater(red, pix.width * pix.height / 2)
                    self.assertEqual(result["sha256"], sha256_file(target))
                    pdf.close()

    def test_boundary_clipped(self):
        _, ir = fixtures()
        crop = crop_geometry(ir["pages"][0], [0, 0, 10, 10], "formula", DEFAULT_POLICY)
        self.assertTrue(crop["clipped"])
        self.assertEqual(crop["expanded_bbox"][:2], [0, 0])


class FakeInference:
    def __init__(self):
        self.calls, self.events, self.fail = [], [], False
        self.runtime_observation = {"startup_seconds": 0, "owned": False}

    def metadata(self, roles):
        return {
            role: {"alias": "mock", "model_sha256": "mock", "generation": {"temperature": 0}}
            for role in roles
        }

    @contextmanager
    def acquire(self, role, metadata):
        self.events.append(("acquire", role))
        try:
            yield self
        finally:
            self.events.append(("release", role))

    def infer(self, role, crop):
        self.calls.append((role, str(crop)))
        if self.fail:
            self.fail = False
            raise TimeoutError("mock timeout")
        content = (
            "x^{3}"
            if role == "math_ocr"
            else json.dumps(
                {k: [] for k in ("visible_text", "labels", "visual_elements", "spatial_relations")}
            )
        )
        return {"choices": [{"message": {"content": content}}]}


class VisionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine, self.sf = create_session_factory("sqlite:///:memory:")
        init_database(self.engine)
        self.fake = FakeInference()
        self.client = TestClient(
            create_app(self.sf, question_import_root=self.root, vision_inference=self.fake)
        )
        with self.sf() as s:
            domain = DomainService(s)
            u = domain.user(display_name="Vision test")
            c = domain.course(u.id, name="Vision test")
            o = domain.offering(c.id, academic_year=2026, term="fall")
            t = domain.test(o.id, name="Vision test", total_points=10)
            s.commit()
            tid = t.id
            self.test_id = tid
        pdf = pymupdf.open()
        p = pdf.new_page(width=300, height=400)
        p.insert_text((20, 30), "問題1 body", fontname="japan", fontsize=12)
        # Math text evidence in two spans without requiring an installed math font.
        p.insert_text((50, 90), "x=1", fontsize=12)
        p.insert_text((69, 84), "x=2", fontsize=8)
        pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 20, 20), False)
        pix.clear_with(120)
        p.insert_image((50, 160, 180, 250), stream=pix.tobytes("png"))
        data = pdf.tobytes()
        pdf.close()
        r = self.client.post(
            f"/api/v1/tests/{tid}/question-materials",
            content=data,
            headers={"Content-Type": "application/pdf", "x-filename": "vision.pdf"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.extraction = r.json()["id"]
        r = self.client.post(f"/api/v1/question-imports/{self.extraction}/draft")
        self.assertEqual(r.status_code, 201, r.text)
        self.draft_id = r.json()["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_plan_no_models_execution_results_idempotency_native_immutable(self):
        path = f"/api/v1/question-import-drafts/{self.draft_id}"
        original = self.client.get(path).json()
        plan = self.client.post(path + "/vision-plan").json()
        self.assertEqual(plan["vision_request_count"], 2)
        self.assertEqual(self.fake.events, [])
        result = self.client.post(path + "/vision-runs", json={"execute": True})
        self.assertEqual(result.status_code, 201, result.text)
        run = result.json()
        self.assertEqual(run["state"], "completed")
        results = self.client.get(f"/api/v1/question-import-vision-runs/{run['id']}/results").json()
        self.assertEqual(len(results["results"]), 2)
        self.assertNotIn(str(self.root), json.dumps(results))
        self.assertEqual(self.client.get(path).json(), original)
        again = self.client.post(path + "/vision-runs", json={"execute": True}).json()
        self.assertEqual(again["id"], run["id"])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(
            self.fake.events,
            [
                ("acquire", "math_ocr"),
                ("release", "math_ocr"),
                ("acquire", "ocr"),
                ("release", "ocr"),
            ],
        )
        with self.sf() as s:
            node = s.scalar(
                select(QuestionImportDraftNode).where(
                    QuestionImportDraftNode.draft_id == self.draft_id
                )
            )
            self.assertIn("ordered_content", node.evidence)

    def test_resume_skips_completed_and_retries_failed_pending(self):
        path = f"/api/v1/question-import-drafts/{self.draft_id}"
        self.fake.fail = True
        run = self.client.post(path + "/vision-runs", json={"execute": True}).json()
        self.assertEqual(run["state"], "failed")
        self.assertEqual(len(self.fake.calls), 2)
        response = self.client.post(
            f"/api/v1/question-import-vision-runs/{run['id']}/resume", json={}
        )
        self.assertEqual(response.json()["state"], "completed", response.text)
        self.assertEqual(len(self.fake.calls), 3)
        with self.sf() as s:
            rows = s.scalars(
                select(QuestionImportVisionResult).where(
                    QuestionImportVisionResult.run_id == run["id"]
                )
            ).all()
            self.assertEqual(sorted(r.attempts for r in rows), [1, 2])

    def test_missing_pdf_hash_mismatch_and_no_path_leak(self):
        pdf = self.root / self.extraction / "source.pdf"
        pdf.write_bytes(b"changed")
        r = self.client.post(f"/api/v1/question-import-drafts/{self.draft_id}/vision-plan")
        self.assertEqual(r.status_code, 409)
        self.assertNotIn(str(self.root), r.text)
        pdf.unlink()
        self.assertEqual(
            self.client.post(
                f"/api/v1/question-import-drafts/{self.draft_id}/vision-plan"
            ).status_code,
            409,
        )

    def test_three_regions_completed_failed_pending_resume(self):
        with pymupdf.open(self.root / self.extraction / "source.pdf") as pdf:
            pdf[0].insert_text((50, 125), "x=3", fontsize=12)
            pdf[0].insert_text((69, 119), "x=4", fontsize=8)
            data = pdf.tobytes()
        upload = self.client.post(
            f"/api/v1/tests/{self.test_id}/question-materials",
            content=data,
            headers={"Content-Type": "application/pdf", "x-filename": "three.pdf"},
        ).json()
        draft = self.client.post(f"/api/v1/question-imports/{upload['id']}/draft").json()
        with self.sf() as s:
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(draft["id"])
            regions = svc.results(run["id"])
            self.assertEqual(len(regions), 3)
            formulas = sorted(r["region_id"] for r in regions if r["region_type"] == "formula")
            svc.execute(run["id"], region_ids=[formulas[0]])
            self.fake.fail = True
            svc.execute(run["id"], region_ids=[formulas[1]])
            self.assertEqual(
                sorted(r["state"] for r in svc.results(run["id"])),
                ["completed", "failed", "planned"],
            )
            self.assertEqual(svc.execute(run["id"])["state"], "completed")
            self.assertEqual(len(self.fake.calls), 4)

    def test_plan_artifact_tamper_rejected_without_inference(self):
        with self.sf() as s:
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(self.draft_id)
            (self.root / self.extraction / "vision" / run["id"] / "routing-plan.json").write_text(
                "{}"
            )
            with self.assertRaises(VisionError):
                svc.execute(run["id"])
            self.assertEqual(self.fake.calls, [])

    def test_render_failure_persists_failure(self):
        with self.sf() as s:
            renderer = Mock()
            renderer.render.side_effect = ValueError("bad crop")
            svc = VisionFallbackService(s, self.root, inference=self.fake, renderer=renderer)
            run = svc.create(self.draft_id)
            self.assertEqual(svc.execute(run["id"])["state"], "failed")
            self.assertTrue(
                all(r["error_code"] == "crop_render_failed" for r in svc.results(run["id"]))
            )
            self.assertEqual(self.fake.calls, [])

    def test_missing_model_and_startup_failure(self):
        with self.sf() as s:
            adapter = Mock()
            adapter.metadata.side_effect = ValueError("missing")
            with self.assertRaises(VisionError):
                VisionFallbackService(s, self.root, inference=adapter).create(self.draft_id)
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(self.draft_id)
            self.fake.acquire = Mock(side_effect=RuntimeError("startup"))
            self.assertEqual(svc.execute(run["id"])["state"], "failed")

    def test_completed_artifact_tamper_is_not_replayed(self):
        with self.sf() as s:
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(self.draft_id)
            svc.execute(run["id"])
            row = svc.results(run["id"])[0]
            (self.root / self.extraction / row["evidence"]["raw_ref"]).write_text("tampered")
            with self.assertRaises(VisionError):
                svc.execute(run["id"])
            self.assertEqual(len(self.fake.calls), 2)

    def test_parser_replay_without_inference_preserves_baseline(self):
        with self.sf() as s:
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(self.draft_id)
            svc.execute(run["id"])
            before = deepcopy(svc.results(run["id"]))
            diagnostics_path = (
                self.root / self.extraction / "vision" / run["id"] / "diagnostics.json"
            )
            duration = json.loads(diagnostics_path.read_text())["last_execution_seconds"]
            replay = VisionFallbackService(s, self.root, renderer=Mock())
            after = replay.reparse(run["id"])
            replay.renderer.render.assert_not_called()
            self.assertEqual(len(self.fake.calls), 2)
            for old, new in zip(before, after):
                for k in ("state", "attempts", "routing_decision"):
                    self.assertEqual(old[k], new[k])
                for k in old["evidence"]:
                    self.assertEqual(old["evidence"][k], new["evidence"][k])
                view = new["evidence"]["parsed_view"]["result"]
                self.assertEqual(view["source_raw_sha256"], old["evidence"]["raw_sha256"])
                self.assertEqual(view["region_id"], old["region_id"])
            self.assertEqual(after, replay.reparse(run["id"]))
            self.assertEqual(
                json.loads(diagnostics_path.read_text())["last_execution_seconds"], duration
            )
            self.assertEqual(svc.execute(run["id"])["state"], "completed")
            self.assertEqual(len(self.fake.calls), 2)
            response = self.client.get(f"/api/v1/question-import-vision-runs/{run['id']}/results")
            self.assertEqual(response.status_code, 200)
            self.assertIn("parsed_view", response.json()["results"][0]["evidence"])
            self.assertNotIn(str(self.root), response.text)

    def test_parser_replay_rejects_corrupt_raw_and_crop(self):
        with self.sf() as s:
            svc = VisionFallbackService(s, self.root, inference=self.fake)
            run = svc.create(self.draft_id)
            svc.execute(run["id"])
            row = svc.results(run["id"])[0]
            for kind in ("raw", "crop"):
                path = self.root / self.extraction / row["evidence"][f"{kind}_ref"]
                original = path.read_bytes()
                path.write_bytes(b"tampered")
                with self.assertRaises(VisionError):
                    svc.reparse(run["id"])
                path.write_bytes(original)
            self.assertEqual(len(self.fake.calls), 2)


class AdapterTests(unittest.TestCase):
    def test_external_and_preexisting_managed_are_not_stopped(self):
        for runtime_type in ("external", "managed"):
            manager = Mock()
            manager.status.return_value = {
                "state": "ready",
                "pid": 42,
                "profile": {"runtime_type": runtime_type},
            }
            manager.ensure_running.return_value = {
                "state": "ready",
                "profile": {"runtime_type": runtime_type, "endpoint": "http://127.0.0.1:18080/v1"},
            }
            adapter = RuntimeVisionAdapter(manager, {})
            with adapter.acquire("math_ocr", {"runtime_id": "math_ocr"}):
                pass
            manager.stop.assert_not_called()

    def test_owned_runtime_released_on_exception(self):
        manager = Mock()
        manager.status.return_value = {
            "state": "stopped",
            "pid": None,
            "profile": {"runtime_type": "managed"},
        }
        manager.ensure_running.return_value = {
            "state": "ready",
            "profile": {"runtime_type": "managed", "endpoint": "http://127.0.0.1:18080/v1"},
        }
        with self.assertRaises(TimeoutError):
            with RuntimeVisionAdapter(manager, {}).acquire("math_ocr", {"runtime_id": "math_ocr"}):
                raise TimeoutError()
        manager.stop.assert_called_once_with("math_ocr")

    def test_parse_failure_and_conservative_normalization(self):
        def raw(s):
            return {"choices": [{"message": {"content": s}}]}

        value = normalize_output(raw("not json"), "ocr", [])
        self.assertIn("vision_output_parse_failed", value["review_flags"])
        value = normalize_output(raw("```latex\nx^3\n```"), "math_ocr", ["x", "3"])
        self.assertEqual(value["output"]["recognized_expression"], "x^3")
        self.assertIn("native_vision_disagreement", value["review_flags"])
        self.assertIn(
            "possible_answer_inference",
            normalize_output(raw("答えは2です"), "math_ocr", [])["review_flags"],
        )


class RealRoutingTests(unittest.TestCase):
    def test_existing_real_draft_plans(self):
        base = Path("/tmp/h2b-real-draft-evaluation")
        if not base.exists():
            self.skipTest("local frozen evaluation not available")
        from scoring.question_structure import QuestionStructureParser

        for i, expected in ((1, 0), (2, 3), (3, 4)):
            ir = json.loads((base / f"sampleQ{i}" / "document-ir.json").read_text())
            _, draft = QuestionStructureParser().build(ir)
            before = canonical_hash(draft)
            plan = VisionRoutingPolicy().build(draft, ir)
            self.assertEqual(plan["vision_request_count"], expected)
            self.assertEqual(canonical_hash(draft), before)
