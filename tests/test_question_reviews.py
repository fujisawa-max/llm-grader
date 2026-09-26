from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import pymupdf
from sqlalchemy import select

from scoring.adapters.pdf_preview import PyMuPdfPagePreviewRenderer
from scoring.coordinate import pdf_bbox_to_pixel
from scoring.db.models import QuestionImportVisionResult, QuestionImportReviewRevision, TestQuestion
from scoring.adapters.artifacts import RunArtifactAdapter
from scoring.question_reviews import QuestionReviewService, ReviewError
from scoring.review_document import validate_snapshot, initial_snapshot, review_summary
from scoring.review_preview import page_preview
from scoring.pdf_native import canonical_hash, sha256_file
from scoring.vision_policy import page_space
from tests import test_question_vision as vision_fixture


class ReviewApiTests(unittest.TestCase):
    def setUp(self):
        vision_fixture.VisionApiTests.setUp(self)
        result = self.client.post(f"/api/v1/question-import-drafts/{self.draft_id}/vision-runs",
                                  json={"execute": True})
        self.assertEqual(result.status_code, 201, result.text)
        self.original_calls = list(self.fake.calls)
        self.source_files = {str(p): sha256_file(p) for p in self.root.rglob("*") if p.is_file()}
        r = self.client.post(f"/api/v1/question-import-drafts/{self.draft_id}/reviews")
        self.assertEqual(r.status_code, 201, r.text)
        self.data = r.json()
        self.url = f"/api/v1/question-import-reviews/{self.data['id']}"

    def tearDown(self):
        self.assertEqual(self.fake.calls, self.original_calls)
        vision_fixture.VisionApiTests.tearDown(self)

    def save(self, snapshot, expected=200, base=None):
        r = self.client.post(self.url + "/revisions", json={
            "snapshot": snapshot, "base_revision": base or self.data["current_revision"]})
        self.assertEqual(r.status_code, expected, r.text)
        if expected == 200:
            self.data = r.json()
            with self.sf() as s:
                rev = s.scalar(select(QuestionImportReviewRevision).where(
                    QuestionImportReviewRevision.review_id == self.data["id"],
                    QuestionImportReviewRevision.revision_number == self.data["current_revision"]))
                path = self.root / self.extraction / rev.artifact_ref
                self.assertEqual(sha256_file(path), rev.revision_sha256)
                self.assertEqual(canonical_hash(rev.snapshot), rev.revision_sha256)
                self.assertEqual(json.loads(path.read_text()), rev.snapshot)
        return r

    def ready(self):
        snap = deepcopy(self.data["snapshot"])
        for n in snap["nodes"]:
            for r in self.data["regions"]:
                if r["assigned_question_key"] == n["source_draft_stable_key"]:
                    n[f"{r['region_type']}_decisions"][r["region_id"]] = {
                        "decision": "use_native" if r["region_type"] == "formula" else "accepted_as_evidence"}
        snap["warning_states"] = {w["id"]: {"state": "acknowledged"} for w in self.data["warnings"]}
        return snap

    def test_preview_metadata_crop_raw_and_access_isolation(self):
        meta = self.client.get(self.url + "/pages/0/metadata").json()
        self.assertEqual(meta["preview_width"], 450)
        self.assertEqual(meta["preview_height"], 600)
        image = self.client.get(self.url + "/pages/0/preview")
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b"\x89PNG"))
        self.assertEqual(self.client.get(self.url + "/pages/0/preview").content, image.content)
        for index in (-1, 1, 999):
            self.assertEqual(self.client.get(self.url + f"/pages/{index}/preview").status_code, 422)
        for region in self.data["regions"]:
            prefix = self.url + f"/regions/{region['region_id']}"
            self.assertEqual(self.client.get(prefix + "/crop").status_code, 200)
            self.assertEqual(self.client.get(prefix + "/vision-raw").status_code, 200)
            evidence = self.client.get(prefix + "/evidence").json()
            self.assertEqual(evidence["region"], region)
        for path in ("/regions/other/crop", "/regions/other/vision-raw", "/regions/other/evidence"):
            self.assertEqual(self.client.get(self.url + path).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/question-import-reviews/{uuid4()}/pages/0/preview").status_code, 404)
        self.assertNotIn(str(self.root), json.dumps(self.data))
        self.assertNotIn(str(self.root), json.dumps(meta))

    def test_list_creation_noop_text_score_revisions_and_conflict(self):
        listed = self.client.get(f"/api/v1/tests/{self.test_id}/question-import-reviews")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], self.data["id"])
        self.assertEqual(self.client.post(f"/api/v1/question-import-drafts/{self.draft_id}/reviews").json()["id"], self.data["id"])
        self.save(deepcopy(self.data["snapshot"]))
        self.assertEqual(self.data["current_revision"], 1)
        snap = deepcopy(self.data["snapshot"])
        next(i for i in snap["nodes"][0]["ordered_content"] if i["type"] == "text")["text"] = "Teacher text <script>"
        self.save(snap)
        self.assertEqual(self.data["current_revision"], 2)
        self.save(snap, base=1)
        self.assertEqual(self.data["current_revision"], 2)
        snap = deepcopy(self.data["snapshot"])
        snap["nodes"][0].update(score_semantics="direct", score_points=12.5)
        self.save(snap, expected=409, base=1)
        self.save(snap)
        self.assertEqual(self.data["summary"]["total_points_candidate"], 12.5)
        history = self.client.get(self.url + "/revisions").json()["revisions"]
        self.assertEqual(len(history), 3)
        old = self.client.get(self.url + "/revisions/1").json()
        self.assertNotIn("Teacher text", old["snapshot"]["nodes"][0]["body_text"])

    def test_formula_figure_warning_decisions_and_source_immutability(self):
        for decision in ("use_native", "use_vision", "teacher_edit"):
            snap = self.ready()
            for n in snap["nodes"]:
                for rid in n["formula_decisions"]:
                    n["formula_decisions"][rid] = {"decision": decision, "teacher_transcription": "x^3", "note": "確認"}
            self.save(snap)
        reviewed = self.client.post(self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["state"], "reviewed")
        for path, digest in self.source_files.items():
            self.assertEqual(sha256_file(Path(path)), digest)
        with self.sf() as s:
            self.assertEqual(list(s.scalars(select(TestQuestion))), [])
        old = deepcopy(reviewed.json()["snapshot"])
        old.update(state="editing", reviewed=False)
        self.data = reviewed.json()
        self.save(old)
        self.assertEqual(self.data["state"], "editing")

    def test_teacher_transcription_preserves_one_or_two_literal_backslashes(self):
        # HTTP JSON encoding may display a backslash doubled on the wire, but the
        # decoded Python value must be stored byte-for-byte.  There is no global
        # unescape here: an intentional two-character ``\\\\`` remains two.
        snap = deepcopy(self.data["snapshot"])
        formula = next(r for r in self.data["regions"] if r["region_type"] == "formula")
        node = next(n for n in snap["nodes"] if n["source_draft_stable_key"] == formula["assigned_question_key"])
        node["formula_decisions"][formula["region_id"]] = {
            "decision": "teacher_edit", "teacher_transcription": r"\sin x"
        }
        self.save(snap)
        saved = next(n for n in self.data["snapshot"]["nodes"] if n["source_draft_stable_key"] == formula["assigned_question_key"])
        actual = saved["formula_decisions"][formula["region_id"]]["teacher_transcription"]
        self.assertEqual(actual, "\\sin x")
        self.assertEqual([ord(c) for c in actual][:3], [92, 115, 105])
        snap = deepcopy(self.data["snapshot"])
        node = next(n for n in snap["nodes"] if n["source_draft_stable_key"] == formula["assigned_question_key"])
        node["formula_decisions"][formula["region_id"]]["teacher_transcription"] = "a\\\\b"
        self.save(snap)
        saved = next(n for n in self.data["snapshot"]["nodes"] if n["source_draft_stable_key"] == formula["assigned_question_key"])
        actual = saved["formula_decisions"][formula["region_id"]]["teacher_transcription"]
        self.assertEqual(actual, "a\\\\b")
        self.assertEqual([ord(c) for c in actual], [97, 92, 92, 98])

    def test_invalid_decisions_warnings_anchors_pins_and_scores(self):
        snap = deepcopy(self.data["snapshot"])
        n = snap["nodes"][0]
        n["formula_decisions"]["foreign"] = {"decision": "teacher_edit", "teacher_transcription": "x"}
        self.save(snap, expected=422)
        for mutation in (lambda s: s["warning_states"].update({"invented": {"state": "resolved"}}),
                         lambda s: s["vision_pin"].update(run_id="other"),
                         lambda s: s["nodes"][0].update(score_semantics="direct", score_points=-1),
                         lambda s: s["nodes"][0]["ordered_content"].pop(),
                         lambda s: s["nodes"][0].update(source_draft_stable_key=None)):
            snap = deepcopy(self.data["snapshot"])
            mutation(snap)
            self.save(snap, expected=422)
        snap = self.ready()
        for n in snap["nodes"]:
            for rid in n["formula_decisions"]:
                n["formula_decisions"][rid] = {"decision": "teacher_edit", "teacher_transcription": " "}
        self.save(snap, expected=422)
        r = self.client.post(self.url + "/mark-reviewed", json={"base_revision": 1})
        self.assertEqual(r.status_code, 422)

    def test_pin_survives_new_parser_view_and_hash_tampering_fails(self):
        formula = next(r for r in self.data["regions"] if r["region_type"] == "formula")
        endpoint = self.url + f"/regions/{formula['region_id']}/evidence"
        original = self.client.get(endpoint).json()
        with self.sf() as s:
            row = s.scalar(select(QuestionImportVisionResult).where(QuestionImportVisionResult.region_id == formula["region_id"]))
            value = deepcopy(row.evidence)
            value["parsed_view"] = {"result": {"transcription_normalized": "later"}}
            row.evidence = value
            s.commit()
        self.assertEqual(self.client.get(endpoint).json(), original)
        path = self.root / self.extraction / original["pin"]["raw_ref"]
        path.write_text("{}")
        self.assertEqual(self.client.get(self.url + f"/regions/{formula['region_id']}/vision-raw").status_code, 409)

    def test_node_operations_artifacts_and_cycle_rejection(self):
        snap = deepcopy(self.data["snapshot"])
        new = {**deepcopy(snap["nodes"][0]), "review_node_id": "teacher-1", "stable_key": "teacher-1",
               "source_draft_stable_key": None, "parent_key": None, "sort_order": 10,
               "label": {"raw": "追加", "normalized": "追加"}, "review_flags": [],
               "ordered_content": [{"type": "text", "order": 0, "text": "追加問題"}]}
        snap["nodes"].append(new)
        self.save(snap)
        snap = deepcopy(self.data["snapshot"])
        snap["nodes"][0]["sort_order"], snap["nodes"][-1]["sort_order"] = 10, 0
        self.save(snap)
        snap = deepcopy(self.data["snapshot"])
        snap["nodes"][-1].update(parent_key=snap["nodes"][0]["stable_key"], node_type="subquestion")
        self.save(snap)
        snap = deepcopy(self.data["snapshot"])
        snap["nodes"][0].update(parent_key="teacher-1", node_type="subquestion")
        self.save(snap, expected=422)
        snap = deepcopy(self.data["snapshot"])
        snap["nodes"][-1]["included"] = False
        self.save(snap)
        self.assertEqual(self.data["summary"]["excluded_questions"], 1)

    def test_revision_tamper_prevents_read_and_save(self):
        with self.sf() as s:
            row = s.scalar(select(QuestionImportReviewRevision).where(QuestionImportReviewRevision.review_id == self.data["id"]))
            path = self.root / self.extraction / row.artifact_ref
        path.write_text("{}")
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.save(deepcopy(self.data["snapshot"]), expected=409)

    def test_readiness_requires_figure_and_warning_review(self):
        snap = self.ready()
        for n in snap["nodes"]:
            n["figure_decisions"] = {}
        self.save(snap)
        response = self.client.post(self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]})
        self.assertEqual(response.json()["error"]["code"], "figure_review_required")
        snap = self.ready()
        snap["warning_states"] = {}
        self.save(snap)
        response = self.client.post(self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]})
        if self.data["warnings"]:
            self.assertEqual(response.json()["error"]["code"], "warning_acknowledgement_required")

    def test_source_pdf_and_preview_cache_tamper_rejected(self):
        metadata = self.client.get(self.url + "/pages/0/metadata")
        self.assertEqual(metadata.status_code, 200)
        cache = next((self.root / self.extraction / "review/previews").glob("*.png"))
        cache.write_bytes(b"invalid")
        self.assertEqual(self.client.get(self.url + "/pages/0/preview").status_code, 409)
        source = self.root / self.extraction / "source.pdf"
        source.write_bytes(b"invalid")
        self.assertEqual(self.client.get(self.url).status_code, 409)

    def test_path_traversal_symlink_and_absolute_ref_rejected(self):
        store = RunArtifactAdapter(self.root / self.extraction)
        outside = self.root / "other.json"
        outside.write_text("{}")
        digest = sha256_file(outside)
        for ref in (str(outside), "../other.json", "native/../../other.json"):
            with self.assertRaises(ReviewError):
                QuestionReviewService._artifact(store, ref, digest)
        link = store.path("unsafe-link.json")
        link.symlink_to(outside)
        with self.assertRaises(ReviewError):
            QuestionReviewService._artifact(store, "unsafe-link.json", digest)


class ReviewDocumentTests(unittest.TestCase):
    def fixture(self):
        node = {"stable_key": "q1", "parent_key": None, "node_type": "major_question", "depth": 0,
                "sort_order": 0, "label": {"raw": "Question 1", "normalized": "Question 1"},
                "body_text": "text", "ordered_content": [{"type": "text", "text": "text", "order": 0}],
                "review_flags": [], "score": {"semantics": "unset", "points": None, "effective_points_candidate": None}}
        region = {"region_id": "f", "assigned_question_key": "q1", "text_fragments": [], "review_flags": []}
        draft = {"nodes": [node], "formula_regions": [region], "figure_regions": [], "review_flags": []}
        pin = {"run_id": None, "results": []}
        snap = initial_snapshot("sha", draft, pin)
        return draft, pin, snap

    def test_native_and_vision_decisions_require_evidence(self):
        draft, pin, base = self.fixture()
        for decision, error in (("use_native", "native_evidence_missing"), ("use_vision", "vision_evidence_missing")):
            snap = deepcopy(base)
            snap["nodes"][0]["formula_decisions"] = {"f": {"decision": decision}}
            with self.assertRaisesRegex(ReviewError, error):
                validate_snapshot(snap, base, draft, pin)

    def test_invalid_tree_order_score_and_empty_node_rejected(self):
        draft, pin, base = self.fixture()
        for mutate in (lambda n: n.update(parent_key="q1", node_type="subquestion"),
                       lambda n: n.update(parent_key="missing", node_type="subquestion"),
                       lambda n: n.update(score_points=float("nan")),
                       lambda n: n.update(score_semantics="direct", score_points=None),
                       lambda n: n.update(score_semantics="unset", score_points=10)):
            snap = deepcopy(base)
            mutate(snap["nodes"][0])
            with self.assertRaises(ReviewError):
                validate_snapshot(snap, base, draft, pin)
        snap = deepcopy(base)
        n = deepcopy(snap["nodes"][0])
        n.update(stable_key="teacher", review_node_id="teacher", source_draft_stable_key=None)
        snap["nodes"].append(n)
        with self.assertRaisesRegex(ReviewError, "duplicate_order"):
            validate_snapshot(snap, base, draft, pin)

    def test_no_vision_review_and_score_total(self):
        draft, pin, base = self.fixture()
        draft["formula_regions"] = []
        snap = deepcopy(base)
        snap.update(state="reviewed", reviewed=True)
        result = validate_snapshot(snap, base, draft, pin, mark=True)
        self.assertEqual(result["state"], "reviewed")
        self.assertIsNone(review_summary(snap, draft, pin)["total_points_candidate"])

    def test_native_only_crop_without_inference(self):
        from scoring.review_preview import native_region_preview

        with tempfile.TemporaryDirectory() as temp:
            pdf = pymupdf.open()
            page = pdf.new_page(width=300, height=400)
            page.insert_text((30, 80), "x=1")
            source = Path(temp) / "source.pdf"
            pdf.save(source)
            meta = {"page_index": 0, "rotation": 0, "cropbox": list(page.cropbox), "mediabox": list(page.mediabox), "elements": []}
            ir = {"pages": [meta], "source": {"sha256": sha256_file(source)}}
            region = {"page_index": 0, "bbox": [25, 60, 70, 85], "region_type": "formula", "region_id": "f"}
            path = native_region_preview(RunArtifactAdapter(temp), ir, region)
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(native_region_preview(RunArtifactAdapter(temp), ir, region), path)
            pdf.close()


class PreviewRotationTests(unittest.TestCase):
    def test_multi_page_metadata_and_same_question_highlights(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = pymupdf.open()
            pages = []
            for index in range(2):
                page = pdf.new_page(width=300, height=400)
                page.insert_text((30, 50), f"Page {index + 1}")
                pages.append({"page_index": index, "rotation": 0, "cropbox": list(page.cropbox), "mediabox": list(page.mediabox)})
            source = Path(temp) / "source.pdf"
            pdf.save(source)
            ir = {"pages": pages, "source": {"sha256": sha256_file(source)}}
            draft = {"nodes": [{"stable_key": "q1", "source_regions": [
                {"page_index": p, "bbox": [30, 30, 100, 60]} for p in (0, 1)]}], "formula_regions": [], "figure_regions": []}
            for index in range(2):
                _, meta = page_preview(RunArtifactAdapter(temp), ir, draft, index)
                self.assertEqual(meta["page_count"], 2)
                self.assertEqual(meta["regions"][0]["source_id"], "q1")
                self.assertEqual(meta["regions"][0]["pixel_bbox"], [45, 45, 150, 90])
            pdf.close()

    def test_rotation_crop_offset_pixels_and_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            for rotation in (0, 90, 180, 270):
                with self.subTest(rotation=rotation):
                    pdf = pymupdf.open()
                    page = pdf.new_page(width=300, height=400)
                    page.draw_rect((70, 100, 130, 130), color=None, fill=(1, 0, 0))
                    page.set_cropbox(pymupdf.Rect(40, 50, 280, 380))
                    page.set_rotation(rotation)
                    source, out = Path(temp) / f"{rotation}.pdf", Path(temp) / f"{rotation}.png"
                    pdf.save(source)
                    meta = {"page_index": 0, "rotation": rotation, "cropbox": list(page.cropbox), "mediabox": list(page.mediabox)}
                    rendered = PyMuPdfPagePreviewRenderer().render(source, meta, out)
                    expected = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                    actual = pymupdf.Pixmap(out)
                    self.assertEqual(expected.samples, actual.samples)
                    box = pdf_bbox_to_pixel([30, 50, 90, 80], page_space(meta), scale=1.5)
                    x, y = (box.x0 + box.x1) // 2, (box.y0 + box.y1) // 2
                    self.assertEqual(actual.pixel(x, y), (255, 0, 0))
                    self.assertEqual(rendered["preview_width"], actual.width)
                    with self.assertRaises(ValueError):
                        PyMuPdfPagePreviewRenderer().render(source, meta, out, {"scale": 100, "max_width": 4096, "max_height": 4096, "max_pixels": 100})
                    pdf.close()
