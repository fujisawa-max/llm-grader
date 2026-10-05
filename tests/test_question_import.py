"""Authoritative confirmation integrity, rollback and conservative transcription."""

from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import patch
from sqlalchemy import select, func
from scoring.db.models import TestQuestion, TestQuestionAsset, QuestionImportConfirmation, TestQuestionCorrection
from scoring.question_import import QuestionImportConfirmationService, safe_native_formula
from scoring.pdf_native import canonical_hash, sha256_file
from tests import test_question_reviews as review_fixture


class ConfirmationTests(TestCase):
    setUp = review_fixture.ReviewApiTests.setUp
    tearDown = review_fixture.ReviewApiTests.tearDown
    save = review_fixture.ReviewApiTests.save
    ready = review_fixture.ReviewApiTests.ready

    def test_approved_refinement_keeps_source_and_confirms_teacher_crop(self):
        from scoring.question_refinement import prepare_refinement
        from scoring.question_reviews import QuestionReviewService
        from scoring.coordinate import pixel_to_normalized

        with self.sf() as s:
            svc = QuestionReviewService(s, self.root)
            draft, store, value, ir = svc._draft(self.draft_id)
            original_sha = draft.draft_sha256
            proposed = deepcopy(value)
            for region in proposed["figure_regions"]:
                page = ir["pages"][region["page_index"]]
                region["bbox"] = pixel_to_normalized(region["bbox"], page["width"], page["height"])
                region["coordinate_space"] = "normalized"
                region["semantic_role"] = "student_drawing_area"
            evidence = []
            for pin in self.data["snapshot"]["vision_pin"]["results"]:
                if pin["region_type"] != "figure":
                    continue
                evidence.append({"region_id": pin["region_id"], "crop": pin["crop"],
                    "evidence_source": "teacher_approved_crop",
                    **{f"{name}_path": store.path(pin[f"{name}_ref"]) for name in ("crop", "raw", "view")},
                    **{f"{name}_sha256": pin[f"{name}_sha256"] for name in ("crop", "raw", "view")}})
            refined = prepare_refinement(s, self.root, self.draft_id,
                approved_draft=proposed, evidence=evidence, approval="explicit fixture teacher approval")
            self.assertNotEqual(refined["id"], self.draft_id)
            self.assertEqual(svc._draft(self.draft_id)[0].draft_sha256, original_sha)
            self.data = svc.create(refined["id"])
            self.url = f"/api/v1/question-import-reviews/{self.data['id']}"
        request = self.reviewed()
        response = self.client.post(self.url + "/confirm", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        with self.sf() as s:
            assets = list(s.scalars(select(TestQuestionAsset)))
            self.assertTrue(assets)
            for asset in assets:
                self.assertEqual(asset.provenance["coordinate_space"], "normalized")
                self.assertEqual(asset.provenance["semantic_role"], "student_drawing_area")
                self.assertIsNone(asset.provenance["vision_run_id"])

    def test_correction_comparison_cannot_create_questions(self):
        from scoring.db.models import QuestionImportExtraction, TestMaterial

        body = self.reviewed()
        with self.sf() as s:
            extraction = s.get(QuestionImportExtraction, self.extraction)
            s.get(TestMaterial, extraction.material_id).material_type = "corrected_question_sheet"
            s.commit()
        plan = self.client.post(self.url + "/import-plan").json()
        self.assertIn("correction_comparison_not_confirmable", plan["blockers"])
        body["import_plan_sha256"] = plan["plan_sha256"]
        response = self.client.post(self.url + "/confirm", json=body)
        self.assertEqual(response.status_code, 409, response.text)
        with self.sf() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(TestQuestion)), 0)

    def reviewed(self):
        snap = self.ready()
        for n in snap["nodes"]:
            for rid in n["formula_decisions"]:
                n["formula_decisions"][rid] = {
                    "decision": "teacher_edit",
                    "teacher_transcription": "x ^ { 2 }",
                }
        self.save(snap)
        r = self.client.post(
            self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.data = r.json()
        r = self.client.post(self.url + "/import-plan")
        self.assertEqual(r.status_code, 200, r.text)
        self.plan = r.json()
        self.assertEqual(self.plan["blockers"], [])
        return {
            "expected_revision": self.plan["revision"],
            "expected_revision_sha256": self.plan["revision_sha256"],
            "import_plan_sha256": self.plan["plan_sha256"],
            "mode": "append",
        }

    def test_asset_artifacts_idempotency_tamper_and_sources(self):
        body = self.reviewed()
        sources = {p: sha256_file(p) for p in self.root.rglob("*") if p.is_file()}
        before_plan = deepcopy(self.plan)
        r = self.client.post(self.url + "/confirm", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        result = r.json()
        r2 = self.client.post(self.url + "/confirm", json=body)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["id"], result["id"])
        with self.sf() as s:
            questions = list(s.scalars(select(TestQuestion)))
            self.assertEqual(len(questions), len(self.plan["nodes"]))
            assets = list(s.scalars(select(TestQuestionAsset)))
            self.assertTrue(assets)
            for asset in assets:
                self.assertEqual(
                    sha256_file(self.root / self.extraction / asset.artifact_ref), asset.sha256
                )
                question = s.get(TestQuestion, asset.question_id)
                self.assertIn(asset.id, [i.get("asset_id") for i in question.content["items"]])
                self.assertEqual(canonical_hash(question.content), question.content_sha256)
            conf = s.get(QuestionImportConfirmation, result["id"])
            base = (self.root / self.extraction / conf.artifact_ref).parent
        self.assertEqual(json.loads((base / "import-plan.json").read_text()), before_plan)
        manifest = json.loads((base / "manifest.json").read_text())
        for name, digest in manifest["artifact_hashes"].items():
            self.assertEqual(sha256_file(base / name), digest)
        for path, digest in sources.items():
            self.assertEqual(sha256_file(path), digest)
        for asset in assets:
            media = self.client.get(f"/api/v1/test-question-assets/{asset.id}")
            self.assertEqual(media.status_code, 200, media.text if media.status_code != 200 else "")
            self.assertEqual(media.headers["content-type"], "image/png")
            import hashlib

            self.assertEqual(hashlib.sha256(media.content).hexdigest(), asset.sha256)
        other = {**body, "expected_revision": body["expected_revision"] + 1}
        self.assertEqual(self.client.post(self.url + "/confirm", json=other).status_code, 409)
        (base / "mapping.json").write_text("[]")
        self.assertEqual(
            self.client.get("/api/v1/question-import-confirmations/" + result["id"]).status_code,
            409,
        )

    def test_asset_failure_rolls_back_all_rows(self):
        self.failure("scoring.question_import.copy_asset")

    def test_manifest_failure_rolls_back_all_rows(self):
        from scoring.question_import import write_artifact

        def fail(path, value):
            if path.name == "manifest.json":
                raise OSError("injected manifest failure")
            return write_artifact(path, value)

        self.failure("scoring.question_import.write_artifact", fail)

    def failure(self, target, effect=None):
        body = self.reviewed()
        with self.sf() as s:
            with patch(target, side_effect=effect or OSError("injected copy failure")):
                with self.assertRaises(OSError):
                    QuestionImportConfirmationService(s, self.root).confirm(self.data["id"], **body)
            for model in (TestQuestion, TestQuestionAsset, QuestionImportConfirmation):
                self.assertEqual(s.scalar(select(func.count()).select_from(model)), 0)

    def test_pinned_crop_tamper_blocks_preflight(self):
        self.reviewed()
        pin = self.data["snapshot"]["vision_pin"]["results"][0]
        (self.root / self.extraction / pin["crop_ref"]).write_bytes(b"tampered")
        self.assertEqual(self.client.post(self.url + "/import-plan").status_code, 409)

    def test_unsafe_native_blocker_then_teacher_edit(self):
        snap = self.ready()
        self.save(snap)
        response = self.client.post(
            self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.data = response.json()
        with patch("scoring.question_import.safe_native_formula", return_value=None):
            plan = self.client.post(self.url + "/import-plan").json()
        self.assertTrue(
            any(x.startswith("native_formula_requires_teacher_edit:") for x in plan["blockers"])
        )
        snap = deepcopy(self.data["snapshot"])
        snap.update(state="editing", reviewed=False)
        self.save(snap)
        body = self.reviewed()
        self.assertTrue(body["import_plan_sha256"])

    def test_each_child_score_hierarchy_and_determinism(self):
        snap = self.ready()
        root = snap["nodes"][0]
        root.update(score_semantics="each_child", score_points=20)
        for index in range(2):
            child = deepcopy(root)
            child.update(
                review_node_id=f"teacher-{index}",
                stable_key=f"teacher-{index}",
                source_draft_stable_key=None,
                source_draft_node_id=None,
                parent_key=root["stable_key"],
                node_type="subquestion",
                depth=1,
                sort_order=index,
                label={"raw": str(index), "normalized": str(index)},
                body_text="Teacher child",
                ordered_content=[{"type": "text", "order": 0, "text": "Teacher child"}],
                score_semantics="unset",
                score_points=None,
                effective_points_candidate=None,
                formula_decisions={},
                figure_decisions={},
                review_flags=[],
                warning_states={},
            )
            snap["nodes"].append(child)
        for node in snap["nodes"]:
            for rid in node["formula_decisions"]:
                node["formula_decisions"][rid] = {
                    "decision": "teacher_edit",
                    "teacher_transcription": "x",
                }
        self.save(snap)
        response = self.client.post(
            self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        plan = self.client.post(self.url + "/import-plan").json()
        self.assertEqual(plan, self.client.post(self.url + "/import-plan").json())
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["total_points"], 40)
        self.assertEqual(plan["structural_count"], 1)
        self.assertEqual(plan["gradable_count"], 2)
        response = self.client.post(
            self.url + "/confirm",
            json={
                "expected_revision": plan["revision"],
                "expected_revision_sha256": plan["revision_sha256"],
                "import_plan_sha256": plan["plan_sha256"],
                "mode": "append",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sf() as session:
            rows = list(session.scalars(select(TestQuestion)))
            parent = next(q for q in rows if not q.is_gradable)
            self.assertIsNone(parent.max_points)
            self.assertEqual([q.max_points for q in rows if q.is_gradable], [20, 20])
            self.assertTrue(all(q.parent_id == parent.id for q in rows if q.is_gradable))

    def test_sum_children_import_plan_recurses_without_double_counting_and_propagates_unset(self):
        snap = self.ready()
        root = snap["nodes"][0]
        # The native fixture contains fragmented formula spans. This test is
        # about recursive scores; complete the existing teacher-edit requirement
        # rather than expecting unresolved native math to pass registration.
        for rid in root['formula_decisions']:
            root['formula_decisions'][rid] = {'decision': 'teacher_edit', 'teacher_transcription': 'x'}
        root.update(score_semantics="sum_children", score_points=None)

        def teacher_node(key, parent, depth, order, label, semantics, points):
            child = deepcopy(root)
            child.update(
                review_node_id=key, stable_key=key, source_draft_stable_key=None,
                source_draft_node_id=None, parent_key=parent, node_type="subquestion",
                depth=depth, sort_order=order, label={"raw": label, "normalized": label},
                body_text=label, ordered_content=[{"type": "text", "order": 0, "text": label}],
                score_semantics=semantics, score_points=points, effective_points_candidate=None,
                formula_decisions={}, figure_decisions={}, review_flags=[], warning_states={},
            )
            child.pop("source_mapping_decision", None)
            return child

        snap["nodes"].extend([
            teacher_node("teacher-a", root["stable_key"], 1, 0, "(1)", "direct", 10),
            teacher_node("teacher-b", root["stable_key"], 1, 1, "(2)", "sum_children", None),
            teacher_node("teacher-b1", "teacher-b", 2, 0, "1.", "direct", 10),
            teacher_node("teacher-b2", "teacher-b", 2, 1, "2.", "direct", 10),
            teacher_node("teacher-b3", "teacher-b", 2, 2, "3.", "direct", 10),
        ])
        self.save(snap)
        response = self.client.post(
            self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.data = response.json()
        plan = self.client.post(self.url + "/import-plan").json()
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["total_points"], 40)
        self.assertEqual(next(node for node in plan["nodes"] if node["review_key"] == root["stable_key"])["max_points"], None)
        self.assertEqual(next(node for node in plan["nodes"] if node["review_key"] == "teacher-b")["max_points"], None)
        self.assertEqual(sum(node["max_points"] or 0 for node in plan["nodes"] if node["is_gradable"]), 40)

        incomplete = deepcopy(self.data["snapshot"])
        incomplete.update(state="editing", reviewed=False)
        next(node for node in incomplete["nodes"] if node["stable_key"] == "teacher-b3").update(
            score_semantics="unset", score_points=None)
        self.save(incomplete)
        response = self.client.post(
            self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.data = response.json()
        incomplete_plan = self.client.post(self.url + "/import-plan").json()
        self.assertIsNone(incomplete_plan["total_points"])
        self.assertIn("score_unset:teacher-b3", incomplete_plan["warnings"])
        self.assertIn("total_unresolved", incomplete_plan["warnings"])

    def test_editing_and_stale_plan_rejected(self):
        p = self.client.post(self.url + "/import-plan").json()
        self.assertIn("review_not_reviewed", p["blockers"])
        body = self.reviewed()
        body["import_plan_sha256"] = "0" * 64
        self.assertEqual(self.client.post(self.url + "/confirm", json=body).status_code, 409)


class NativeSafetyTests(TestCase):
    def test_single_span_verbatim_and_fragmented_blocker(self):
        self.assertEqual(
            safe_native_formula({"text_fragments": [{"native_text": "2 1 x ^ { 2 }"}]}),
            "2 1 x ^ { 2 }",
        )
        self.assertIsNone(
            safe_native_formula({"text_fragments": [{"native_text": "x"}, {"native_text": "2"}]})
        )
        self.assertIsNone(safe_native_formula({"text_fragments": []}))


class CorrectionTests(TestCase):
    setUp = review_fixture.ReviewApiTests.setUp
    tearDown = review_fixture.ReviewApiTests.tearDown
    ready = review_fixture.ReviewApiTests.ready

    def _confirm(self):
        # Reuse the fixture's deterministic reviewed snapshot without adding
        # another Review/Confirmation implementation in this test.
        # Initial snapshots have empty decision maps. Populate decisions from
        # the fixture's owned region catalogue before marking it reviewed.
        snap = self.ready()
        for n in snap["nodes"]:
            for rid in n["formula_decisions"]:
                n["formula_decisions"][rid] = {"decision": "teacher_edit", "teacher_transcription": "x"}
            for rid in n["figure_decisions"]:
                n["figure_decisions"][rid] = {"decision": "accepted_as_evidence"}
        snap["warning_states"] = {w["id"]: {"state": "acknowledged"} for w in self.data["warnings"]}
        r = self.client.post(self.url + "/revisions", json={"base_revision": self.data["current_revision"], "snapshot": snap})
        self.assertEqual(r.status_code, 200, r.text)
        self.data = r.json()
        r = self.client.post(self.url + "/mark-reviewed", json={"base_revision": self.data["current_revision"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.data = r.json()
        plan = self.client.post(self.url + "/import-plan").json()
        self.assertFalse(plan["blockers"], plan)
        r = self.client.post(self.url + "/confirm", json={
            "expected_revision": plan["revision"], "expected_revision_sha256": plan["revision_sha256"],
            "import_plan_sha256": plan["plan_sha256"], "mode": "append"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_formula_correction_plan_apply_history_and_stale_conflict(self):
        self._confirm()
        with self.sf() as s:
            question = s.scalar(select(TestQuestion).where(TestQuestion.provenance["origin"].as_string() == "review_import"))
            item = next(i for i in question.content["items"] if i["type"] == "formula")
            qid, old_hash, region, old = question.id, question.content_sha256, item["source_region_id"], item["transcription"]
        new = r"\alpha + \beta"
        body = {"expected_content_sha256": old_hash, "operations": [{
            "source_region_id": region, "expected_old_transcription": old, "new_transcription": new}],
            "reason_code": "test_teacher_correction"}
        planned = self.client.post(f"/api/v1/test-questions/{qid}/correction-plan", json=body)
        self.assertEqual(planned.status_code, 200, planned.text)
        plan = planned.json()
        self.assertEqual(plan["current_content_sha256"], old_hash)
        with self.sf() as s:
            self.assertEqual(s.get(TestQuestion, qid).content_sha256, old_hash)
        applied = self.client.post(f"/api/v1/test-questions/{qid}/corrections", json={**body, "plan_sha256": plan["plan_sha256"]})
        self.assertEqual(applied.status_code, 200, applied.text)
        with self.sf() as s:
            question = s.get(TestQuestion, qid)
            self.assertEqual(next(i for i in question.content["items"] if i["type"] == "formula")["transcription"], new)
            row = s.scalar(select(TestQuestionCorrection).where(TestQuestionCorrection.test_question_id == qid))
            self.assertEqual(row.previous_content_sha256, old_hash)
            self.assertEqual(row.new_content_sha256, question.content_sha256)
        history = self.client.get(f"/api/v1/test-questions/{qid}/corrections")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["corrections"]), 1)
        stale = self.client.post(f"/api/v1/test-questions/{qid}/corrections", json={**body, "plan_sha256": plan["plan_sha256"]})
        self.assertEqual(stale.status_code, 409)

    def test_display_label_only_plan_apply_conflicts_and_history(self):
        self._confirm()
        with self.sf() as s:
            q = s.scalar(select(TestQuestion))
            qid = q.id
            before = {col.name: deepcopy(getattr(q, col.name)) for col in q.__table__.columns}
        body = {"expected_content_sha256": before["content_sha256"], "operations": [{
            "type": "set_display_label", "expected_old_value": before["display_label"],
            "new_value": "教師確認ラベル"}], "reason_code": "validation_label_cleanup"}
        url = f"/api/v1/test-questions/{qid}"
        plan = self.client.post(url + "/correction-plan", json=body)
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertEqual(plan.json()["changes"], ["display_label"])
        self.assertEqual(plan.json()["new_content_sha256"], before["content_sha256"])
        with self.sf() as s:
            q = s.get(TestQuestion, qid)
            self.assertEqual({col.name: getattr(q, col.name) for col in q.__table__.columns}, before)
        wrong = deepcopy(body)
        wrong["operations"][0]["expected_old_value"] = "stale label"
        self.assertEqual(self.client.post(url + "/correction-plan", json=wrong).status_code, 409)
        request = {**body, "plan_sha256": plan.json()["plan_sha256"]}
        self.assertEqual(self.client.post(url + "/corrections", json={**request, "plan_sha256": "0"*64}).status_code, 409)
        applied = self.client.post(url + "/corrections", json=request)
        self.assertEqual(applied.status_code, 200, applied.text)
        with self.sf() as s:
            q = s.get(TestQuestion, qid)
            self.assertEqual(q.display_label, "教師確認ラベル")
            for field, value in before.items():
                if field not in {"display_label", "updated_at"}:
                    self.assertEqual(getattr(q, field), value, field)
        self.assertEqual(self.client.post(url + "/corrections", json=request).status_code, 409)
        first = self.client.get(url + "/corrections").json()["corrections"][0]
        self.assertEqual(first["correction_type"], "set_display_label")
        self.assertEqual(first["previous_value"], {"display_label": before["display_label"]})
        second = deepcopy(body)
        second["operations"][0].update(expected_old_value="教師確認ラベル", new_value="次のラベル")
        p2 = self.client.post(url + "/correction-plan", json=second).json()
        r2 = self.client.post(url + "/corrections", json={**second, "plan_sha256": p2["plan_sha256"]})
        self.assertEqual(r2.status_code, 200, r2.text)
        history = self.client.get(url + "/corrections").json()["corrections"]
        self.assertEqual(history[0], first)
        self.assertEqual([h["correction_version"] for h in history], [1, 2])
        with self.sf() as s:
            manual = TestQuestion(test_id=before["test_id"], question_number="manual-label-test", display_label="manual")
            s.add(manual)
            s.commit()
            mid = manual.id
        self.assertEqual(self.client.post(f"/api/v1/test-questions/{mid}/correction-plan", json=body).status_code, 409)

    def test_title_only_plan_apply_conflicts_and_history(self):
        self._confirm()
        with self.sf() as s:
            q = s.scalar(select(TestQuestion))
            qid = q.id
            before = {col.name: deepcopy(getattr(q, col.name)) for col in q.__table__.columns}
        body = {"expected_content_sha256": before["content_sha256"], "operations": [{
            "type": "set_title", "expected_old_value": before["title"],
            "new_value": "教師確認ラベル"}], "reason_code": "validation_label_cleanup"}
        url = f"/api/v1/test-questions/{qid}"
        plan = self.client.post(url + "/correction-plan", json=body)
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertEqual(plan.json()["changes"], ["title"])
        self.assertEqual(plan.json()["new_content_sha256"], before["content_sha256"])
        with self.sf() as s:
            q = s.get(TestQuestion, qid)
            self.assertEqual({col.name: getattr(q, col.name) for col in q.__table__.columns}, before)
        wrong = deepcopy(body)
        wrong["operations"][0]["expected_old_value"] = "stale label"
        self.assertEqual(self.client.post(url + "/correction-plan", json=wrong).status_code, 409)
        request = {**body, "plan_sha256": plan.json()["plan_sha256"]}
        self.assertEqual(self.client.post(url + "/corrections", json={**request, "plan_sha256": "0"*64}).status_code, 409)
        applied = self.client.post(url + "/corrections", json=request)
        self.assertEqual(applied.status_code, 200, applied.text)
        with self.sf() as s:
            q = s.get(TestQuestion, qid)
            self.assertEqual(q.title, "教師確認ラベル")
            for field, value in before.items():
                if field not in {"title", "updated_at"}:
                    self.assertEqual(getattr(q, field), value, field)
        self.assertEqual(self.client.post(url + "/corrections", json=request).status_code, 409)
        first = self.client.get(url + "/corrections").json()["corrections"][0]
        self.assertEqual(first["correction_type"], "set_title")
        self.assertEqual(first["previous_value"], {"title": before["title"]})
        second = deepcopy(body)
        second["operations"][0].update(expected_old_value="教師確認ラベル", new_value="次のラベル")
        p2 = self.client.post(url + "/correction-plan", json=second).json()
        r2 = self.client.post(url + "/corrections", json={**second, "plan_sha256": p2["plan_sha256"]})
        self.assertEqual(r2.status_code, 200, r2.text)
        history = self.client.get(url + "/corrections").json()["corrections"]
        self.assertEqual(history[0], first)
        self.assertEqual([h["correction_version"] for h in history], [1, 2])
        with self.sf() as s:
            manual = TestQuestion(test_id=before["test_id"], question_number="manual-label-test", title="manual")
            s.add(manual)
            s.commit()
            mid = manual.id
        self.assertEqual(self.client.post(f"/api/v1/test-questions/{mid}/correction-plan", json=body).status_code, 409)

    def test_text_segment_correction_is_scoped_and_append_only(self):
        self._confirm()
        with self.sf() as s:
            q = s.scalar(select(TestQuestion))
            qid, before = q.id, deepcopy(q.content)
            digest = q.content_sha256
        index = next(i for i, item in enumerate(before["items"]) if item["type"] == "text")
        old = before["items"][index]["text"]
        body = {"expected_content_sha256": digest, "reason_code": "question_source_typo_correction",
                "operations": [{"type": "set_text_segment", "item_index": index,
                                "expected_old_text": old, "new_text": old + "訂正"}]}
        url = f"/api/v1/test-questions/{qid}"
        bad = deepcopy(body)
        bad["operations"][0]["expected_old_text"] = "stale"
        self.assertEqual(self.client.post(url + "/correction-plan", json=bad).status_code, 409)
        bad["operations"][0]["item_index"] = -1
        self.assertEqual(self.client.post(url + "/correction-plan", json=bad).status_code, 422)
        plan = self.client.post(url + "/correction-plan", json=body)
        self.assertEqual(plan.status_code, 200, plan.text)
        request = {**body, "plan_sha256": plan.json()["plan_sha256"]}
        result = self.client.post(url + "/corrections", json=request)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["correction_type"], "set_text_segment")
        self.assertEqual(self.client.post(url + "/corrections", json=request).status_code, 409)
        before["items"][index]["text"] = old + "訂正"
        with self.sf() as s:
            self.assertEqual(s.get(TestQuestion, qid).content, before)
