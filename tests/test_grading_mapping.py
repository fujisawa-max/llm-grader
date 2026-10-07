from copy import deepcopy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from scoring.api.app import create_app
from scoring.db import create_session_factory, init_database
from scoring.domain import DomainService
from scoring.grading_context import ContextError
from scoring.grading_inputs import prepare_inputs
from scoring.grading_mapping import (
    GradingInputAssembler,
    QuestionIdentityResolver,
    prepare_submission_bundles,
)
from scoring.pdf_native import sha256_file
from tests.mapping_fixture import create_mapping_fixture
from tests.http_auth import authenticate_fixture


class GradingMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine, self.sf = create_session_factory("sqlite:///:memory:")
        init_database(self.engine)
        self.s = self.sf()
        self.f = create_mapping_fixture(self.s, self.root)

    def tearDown(self):
        self.s.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def assembler(self):
        self.s.flush()
        return GradingInputAssembler(
            self.s, self.f["test"].id, root=self.root, allowed_roots=[self.root]
        )

    def result(self):
        return self.assembler().evaluate(self.f["submission"].id)

    def save(self, doc):
        path = self.root / "submission.json"
        path.write_text(json.dumps(doc))
        self.f["material"].sha256 = sha256_file(path)

    def codes(self):
        return {c["code"] for r in self.result()["questions"] for c in r["blockers"]}

    def test_four_way_shuffle_duplicates_context_and_snapshot_equivalence(self):
        result = self.result()
        self.assertTrue(result["can_build_all_inputs"])
        self.assertEqual(result["gradable_count"], 3)
        bundles = {r["question_id"]: r["bundle"] for r in result["questions"]}
        for key, q in self.f["questions"].items():
            b = bundles[q.id]
            self.assertIn(f"QUESTION_TOKEN_{key}", b["question"]["context"]["effective_text"])
            self.assertIn(f"PARENT_TOKEN_{key[0]}", b["question"]["context"]["effective_text"])
            self.assertNotIn(f"PARENT_TOKEN_{'B' if key[0] == 'A' else 'A'}", json.dumps(b))
            self.assertEqual(b["student_answer"]["pages"][0]["page_id"], f"STUDENT_TOKEN_{key}")
            self.assertEqual(b["model_answer"]["content"], f"MODEL_TOKEN_{key}")
            self.assertEqual(
                b["rubric"]["entry"]["criteria"][0]["description"], f"RUBRIC_TOKEN_{key}"
            )
            self.assertEqual(b["question"]["max_points"], 10)
        dry = prepare_submission_bundles(
            self.s, self.f["test"].id, [self.f["submission"]], self.root, root=self.root
        )
        self.assertEqual({b["identity"]["question_id"]: b for b in dry}, bundles)
        inputs = prepare_inputs(
            self.s,
            self.f["test"].id,
            list(self.f["questions"].values()),
            list(self.f["models"].values()),
            self.f["rubric"],
            self.root,
            self.root / "run",
            root=self.root,
        )
        for qid, b in bundles.items():
            self.assertEqual(inputs[qid]["context"], b["question"]["context"])
            self.assertEqual(inputs[qid]["reference_text"], b["model_answer"]["content"])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_hash_order_independence_and_content_sensitivity(self):
        original = {
            r["question_id"]: r["bundle"]["bundle_sha256"] for r in self.result()["questions"]
        }
        doc = deepcopy(self.f["document"])
        doc["answers"].reverse()
        doc["pages"].reverse()
        self.save(doc)
        rubric = self.f["rubric"]
        rubric.rubric_json = {"questions": list(reversed(rubric.rubric_json["questions"]))}
        self.assertEqual(
            original,
            {r["question_id"]: r["bundle"]["bundle_sha256"] for r in self.result()["questions"]},
        )
        q = self.f["questions"]["A1"]

        def value():
            return next(
                r["bundle"]["bundle_sha256"]
                for r in self.result()["questions"]
                if r["question_id"] == q.id
            )

        previous = value()
        for change in (
            lambda: setattr(self.f["models"]["A1"], "answer_text", "changed"),
            lambda: setattr(q, "question_text", "changed question"),
            lambda: (self.root / "A1.png").write_bytes(b"changed source"),
        ):
            change()
            self.assertNotEqual(previous, value())
            previous = value()
        entries = deepcopy(rubric.rubric_json)
        next(e for e in entries["questions"] if e["question_id"] == q.id)["criteria"][0][
            "description"
        ] = "changed criterion"
        rubric.rubric_json = entries
        self.assertNotEqual(previous, value())

    def test_identity_priority_legacy_ambiguous_and_title_independence(self):
        resolver = self.assembler().resolver
        q = self.f["questions"]["A1"]
        for field, value in (
            ("test_question_id", q.id),
            ("stable_question_key", q.stable_question_key),
            ("question_number", "A1"),
        ):
            found, _, warnings = resolver.resolve({field: value})
            self.assertEqual(found.id, q.id)
            self.assertEqual(bool(warnings), field == "question_number")
        q.title = "corrected"
        q.display_label = "(1)"
        self.assertEqual(resolver.resolve({"question_id": q.id})[0].id, q.id)
        with self.assertRaisesRegex(ContextError, "NOT_FOUND"):
            resolver.resolve({"display_label": "(1)"})
        duplicate = SimpleNamespace(id="other", stable_question_key="other", question_number="A1")
        with self.assertRaisesRegex(ContextError, "AMBIGUOUS"):
            QuestionIdentityResolver([q, duplicate]).resolve({"question_number": "A1"})
        with self.assertRaisesRegex(ContextError, "IDENTITY_MISMATCH"):
            resolver.resolve({"test_question_id": q.id, "question_number": "B1"})

    def test_missing_duplicate_structural_orphan_and_wrong_owner(self):
        base = self.f["document"]
        cases = []
        doc = deepcopy(base)
        doc["answers"].pop()
        cases.append((doc, "MISSING_STUDENT_ANSWER"))
        doc = deepcopy(base)
        doc["answers"].append(doc["answers"][0])
        cases.append((doc, "DUPLICATE_STUDENT_ANSWER"))
        doc = deepcopy(base)
        doc["answers"][0]["question_id"] = self.f["parents"]["A"].id
        cases.append((doc, "ANSWER_MAPPED_TO_STRUCTURAL_QUESTION"))
        doc = deepcopy(base)
        doc["answers"][0]["question_id"] = "unknown"
        cases.append((doc, "ORPHAN_STUDENT_ANSWER"))
        for field, code in (
            ("student_id", "CROSS_STUDENT_ANSWER_MAPPING"),
            ("test_id", "CROSS_TEST_ANSWER_MAPPING"),
            ("submission_id", "CROSS_SUBMISSION_ANSWER_MAPPING"),
        ):
            doc = deepcopy(base)
            doc[field] = "wrong"
            cases.append((doc, code))
        for doc, code in cases:
            with self.subTest(code=code):
                self.save(doc)
                self.assertIn(code, self.codes())
                self.assertFalse(self.result()["can_build_all_inputs"])

    def test_cross_test_answers_and_rubric(self):
        d = DomainService(self.s)
        other = d.test(self.f["test"].course_offering_id, name="other", total_points=10)
        foreign = d.question(other.id, question_number="X", max_points=10)
        doc = deepcopy(self.f["document"])
        doc["answers"][0]["question_id"] = foreign.id
        self.save(doc)
        self.assertIn("CROSS_TEST_ANSWER_MAPPING", self.codes())
        entries = deepcopy(self.f["rubric"].rubric_json)
        entries["questions"][0]["question_id"] = foreign.id
        self.f["rubric"].rubric_json = entries
        self.assertIn("CROSS_TEST_RUBRIC_MAPPING", self.codes())

    def test_rubric_duplicate_missing_unknown_structural(self):
        r = self.f["rubric"]
        base = deepcopy(r.rubric_json)
        for target, code in (
            ("unknown", "UNKNOWN_RUBRIC_QUESTION"),
            (self.f["parents"]["A"].id, "RUBRIC_MAPPED_TO_STRUCTURAL_QUESTION"),
            (base["questions"][1]["question_id"], "DUPLICATE_RUBRIC_ENTRY"),
        ):
            data = deepcopy(base)
            data["questions"][0]["question_id"] = target
            r.rubric_json = data
            self.assertIn(code, self.codes())
        data = deepcopy(base)
        data["questions"].pop()
        r.rubric_json = data
        self.assertIn("MISSING_RUBRIC", self.codes())

    def test_model_versions_mismatch_and_unset_score(self):
        q = self.f["questions"]["A1"]
        new = DomainService(self.s).model_answer(
            self.f["test"].id, question_id=q.id, answer_text="version 2"
        )
        a = self.assembler()
        self.assertEqual(a.question_part(q.id)["model_answer"]["id"], new.id)
        a.answers[q.id] = [self.f["models"]["B1"]]
        with self.assertRaisesRegex(ContextError, "MODEL_ANSWER_QUESTION_MISMATCH"):
            a.question_part(q.id)
        new.is_current = False
        self.assertIn("MISSING_MODEL_ANSWER", self.codes())
        q.max_points = None
        self.assertIn("MISSING_MAX_POINTS", self.codes())

    def test_negative_swaps_independent_identity_and_snapshot(self):
        doc = deepcopy(self.f["document"])
        doc["answers"][0]["test_question_id"] = self.f["questions"]["A1"].id
        self.save(doc)
        self.assertIn("QUESTION_IDENTITY_MISMATCH", self.codes())
        self.save(self.f["document"])
        # Same declared ID but a different execution source is caught at snapshot boundary.
        with patch("scoring.core.load_assignment") as load:
            load.side_effect = None
            load.return_value = (
                {},
                [],
                [
                    {
                        "submission_id": "h2g-submission",
                        "pages": [
                            {"page_id": f"STUDENT_TOKEN_{key}", "path": self.root / f"{key}.png"}
                            for key in ("A1", "A2", "B1")
                        ],
                        "answers": [
                            {
                                "question_id": self.f["questions"]["A1"].id,
                                "page_ids": ["STUDENT_TOKEN_A2"],
                            }
                        ],
                    }
                ],
            )
            with self.assertRaisesRegex(ContextError, "SNAPSHOT_MISMATCH"):
                prepare_submission_bundles(
                    self.s, self.f["test"].id, [self.f["submission"]], self.root
                )

    def test_http_read_only_and_isolation(self):
        self.s.commit()
        with TestClient(
            create_app(self.sf, allowed_roots=[self.root], question_import_root=self.root)
        ) as raw:
            client = authenticate_fixture(raw, self.s, self.f["user"])
            base = f"/api/v1/tests/{self.f['test'].id}/submissions/{self.f['submission'].id}"
            response = client.get(base + "/grading-input-readiness")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["can_build_all_inputs"])
            q = self.f["questions"]["A1"]
            self.assertEqual(
                client.get(base + f"/questions/{q.id}/grading-input-preview").status_code, 200
            )
            p = self.f["parents"]["A"]
            self.assertEqual(
                client.get(base + f"/questions/{p.id}/grading-input-preview").status_code, 409
            )
            self.assertEqual(
                client.get(
                    base.replace(self.f["submission"].id, "other") + "/grading-input-readiness"
                ).status_code,
                404,
            )
            self.assertNotIn(str(self.root), response.text)

    def test_material_hash_and_path_safety(self):
        self.f["material"].sha256 = "0" * 64
        self.assertIn("STUDENT_ANSWER_SOURCE_HASH_MISMATCH", self.codes())
        self.f["material"].storage_ref = "/etc/passwd"
        self.assertIn("STUDENT_ANSWER_SOURCE_UNAVAILABLE", self.codes())
        self.f["material"].storage_ref = str(self.root / "submission.json")
        doc = deepcopy(self.f["document"])
        doc["pages"][0]["image"] = "../outside.png"
        self.save(doc)
        self.assertIn("STUDENT_ANSWER_ASSET_MISSING", self.codes())

    def test_asset_isolation_integrity_and_authoritative_formula(self):
        from scoring.db.models import TestQuestionAsset as Asset
        from scoring.pdf_native import canonical_hash

        q = self.f["questions"]["B1"]
        directory = self.root / "extract"
        directory.mkdir()
        (directory / "figure.png").write_bytes((self.root / "B1.png").read_bytes())
        asset = Asset(
            question_id=q.id,
            asset_type="figure",
            artifact_ref="figure.png",
            sha256=sha256_file(directory / "figure.png"),
            mime_type="image/png",
            provenance={"extraction_id": "extract"},
        )
        self.s.add(asset)
        self.s.flush()
        q.content = {
            "schema_version": "test-question-content.v1",
            "items": [
                {"type": "formula", "transcription": r"\alpha + \beta"},
                {"type": "figure", "asset_id": asset.id},
            ],
        }
        q.content_sha256 = canonical_hash(q.content)
        for row in self.result()["questions"]:
            self.assertEqual(len(row["bundle"]["assets"]), int(row["question_id"] == q.id))
        self.assertIn(
            r"\alpha + \beta",
            self.assembler().question_part(q.id)["question"]["context"]["effective_text"],
        )
        (directory / "figure.png").write_bytes(b"tampered")
        self.assertIn("ASSET_HASH_MISMATCH", self.codes())
        (directory / "figure.png").unlink()
        self.assertIn("ASSET_MISSING", self.codes())

    def test_swapped_assignment_rubric_rejected(self):
        for left, right in (("A1", "A2"), ("A2", "A1")):
            path = self.root / f"{left}.rubric.json"
            data = json.loads(path.read_text())
            data["criteria"][0]["description"] = f"RUBRIC_TOKEN_{right}"
            path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "ASSIGNMENT_RUBRIC_MISMATCH"):
            prepare_inputs(
                self.s,
                self.f["test"].id,
                list(self.f["questions"].values()),
                list(self.f["models"].values()),
                self.f["rubric"],
                self.root,
                self.root / "run",
                root=self.root,
            )

    def test_answer_id_swap_never_leaks_into_original_question(self):
        doc = deepcopy(self.f["document"])
        doc["answers"][-1]["question_id"] = self.f["questions"]["B1"].id
        self.save(doc)
        result = self.result()
        a1 = next(
            r for r in result["questions"] if r["question_id"] == self.f["questions"]["A1"].id
        )
        self.assertIsNone(a1["bundle"])
        self.assertIn("MISSING_STUDENT_ANSWER", {c["code"] for c in a1["blockers"]})
        self.assertIn("DUPLICATE_STUDENT_ANSWER", self.codes())

    def test_timestamp_does_not_affect_bundle_hash(self):
        from datetime import datetime, timezone

        before = self.result()
        self.f["models"]["A1"].created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.f["rubric"].approved_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(before, self.result())
