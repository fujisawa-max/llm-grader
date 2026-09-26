"""Regression contracts captured from the H.3--H.5 production audit.

The fixtures are deliberately small and in-memory.  They exercise the same
read-only helpers used at the grading boundary; no production database row or
model endpoint is touched.
"""

import json
import unittest

from scoring.grading_audit import (
    GRADING_MODEL_INPUT_CONTRADICTION,
    GRADING_MODEL_SELF_CONTRADICTION,
    aggregate_authoritative_results,
    grading_response_warnings,
    has_matrix_vector_structure,
    reconstruction_contains_source,
    require_visual_roles,
    resolve_authoritative_result,
    resolve_selected_reconstruction,
)
from scoring.grading_execution import validate_result


Q3_SOURCE_FAITHFUL = """sin(5π/12) + sin(π/12)
= 2 sin((5π/12 + π/12)/2) cos((5π/12 - π/12)/2)
= 2 sin(π/4) cos(π/6)
= 2 · √2/2 · √3/2
= √6/2"""

Q3_OLD_INCOMPLETE = "2 sin(π/4) cos(π/6) = √6/2"
Q3_OLD_OCR = "2 sin(6π/12) cos(4π/12) = 2 sin(π/2) cos(π/3)"
Q4_MATRIX = (
    r"= \begin{pmatrix}1&1\\0&2\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}"
    "\n"
    r"+ \begin{pmatrix}1&2\\1&3\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}"
    "\n"
    r"= \begin{pmatrix}2&3\\1&5\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}"
    "\n"
    r"= \begin{pmatrix}6-3\\3-5\end{pmatrix}"
    "\n"
    r"= \begin{pmatrix}3\\-2\end{pmatrix}"
)


def simple_bundle(answer: str, question_id: str = "q") -> dict:
    entry = {
        "question_id": question_id,
        "max_points": 10,
        "criteria": [{
            "id": "criterion_1",
            "points": 10,
            "description": "criterion",
            "levels": [{"score": 0, "condition": "zero"},
                       {"score": 10, "condition": "full"}],
        }],
    }
    return {
        "identity": {"question_id": question_id, "test_id": "test"},
        "question": {"max_points": 10},
        "student_answer": {"answer_text": answer, "page_ids": ["page-1"]},
        "rubric": {"id": "rubric", "question_id": question_id,
                    "entry": entry, "entry_sha256": "unused"},
        "model_answer": {"question_id": question_id},
    }


def raw_result(question_id: str, *, evidence: str, reason: str,
               review: bool = False) -> dict:
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
        "question_id": question_id,
        "criteria": [{"criterion_id": "criterion_1", "score": 0, "max_score": 10,
                       "evidence": [{"page_id": "page-1", "quote": evidence}],
                       "reason": reason}],
        "needs_review": review, "review_reasons": [],
    }, ensure_ascii=False)}}]}


class H5BRegressionTests(unittest.TestCase):
    def test_incomplete_reconstruction_and_teacher_precedence(self):
        self.assertFalse(reconstruction_contains_source(Q3_OLD_INCOMPLETE, Q3_SOURCE_FAITHFUL))
        self.assertTrue(reconstruction_contains_source(Q3_SOURCE_FAITHFUL, Q3_SOURCE_FAITHFUL))
        selected = resolve_selected_reconstruction([
            {"id": "old-v2", "selected": False, "status": "COMPLETE"},
            {"id": "461a1daf-d16d-4dfa-a011-ff22c576c6d7", "selected": True,
             "status": "COMPLETE"},
        ])
        self.assertEqual(selected["id"], "461a1daf-d16d-4dfa-a011-ff22c576c6d7")
        self.assertNotIn(Q3_OLD_OCR, Q3_SOURCE_FAITHFUL)

    def test_matrix_vector_structure_is_not_flattened(self):
        self.assertTrue(has_matrix_vector_structure(Q4_MATRIX))
        current = resolve_selected_reconstruction([{
            "id": "f08bf635-7f1e-46dd-8256-fbffec9d82f1",
            "selected": True,
            "status": "COMPLETE",
        }])
        self.assertEqual(current["id"], "f08bf635-7f1e-46dd-8256-fbffec9d82f1")
        flattened = "= (2 3) (3) = (6-3) = (3) (-2)"
        self.assertFalse(has_matrix_vector_structure(flattened))

    def test_nonempty_answer_contradiction_is_a_review_warning(self):
        bundle = simple_bundle("(x+1)^3 = x^3 + 3x^2 + 3x + 1")
        result = json.loads(raw_result("q", evidence="No student answer was provided",
                                       reason="The student answer is missing;")
                            ["choices"][0]["message"]["content"])
        warnings = grading_response_warnings(result, bundle)
        self.assertIn(GRADING_MODEL_INPUT_CONTRADICTION, warnings)

    def test_validate_result_preserves_contradiction_as_review_required(self):
        bundle = simple_bundle("(x+1)^3 = x^3 + 3x^2 + 3x + 1")
        # validate_result also checks the semantic rubric hash; use the real
        # canonical hash in this focused contract test.
        from scoring.pdf_native import canonical_hash
        bundle["rubric"]["entry_sha256"] = canonical_hash(bundle["rubric"]["entry"])
        raw = raw_result("q", evidence="No student answer was provided",
                         reason="The student answer is missing;")
        with self.assertRaisesRegex(ValueError, "GRADING_REVIEW_REQUIRED"):
            validate_result(raw, bundle)

    def test_model_self_contradiction_warning_does_not_change_score(self):
        bundle = simple_bundle("y = 3 cos(x + π/2)")
        result = json.loads(raw_result(
            "q", evidence="最終式 y = 3 cos(x + π/2)",
            reason="The coefficient 3 is missing from the final expression.",
            review=True)["choices"][0]["message"]["content"])
        warnings = grading_response_warnings(result, bundle)
        self.assertIn(GRADING_MODEL_SELF_CONTRADICTION, warnings)
        self.assertEqual(result["criteria"][0]["score"], 0)

    def test_visual_roles_are_separate(self):
        assets = [{"role": role} for role in (
            "question_context", "model_answer_reference", "student_visual_answer")]
        require_visual_roles(assets)
        with self.assertRaisesRegex(ValueError, "VISUAL_ASSET_ROLE_INVALID"):
            require_visual_roles(assets[:-1])

    def test_teacher_adjudication_precedence_and_superseded_exclusion(self):
        q2 = resolve_authoritative_result(
            "q2/s2/q3",
            teacher_decisions=[{"id": "8886e544-aaa8-47d0-9ccb-27a5c841ce0d",
                               "status": "COMPLETE", "score": 10, "max_score": 20,
                               "decision_version": 1}],
            model_results=[{"id": "failed", "state": "failed", "score": None,
                            "max_score": 20},
                           {"id": "review", "state": "completed", "needs_review": True,
                            "score": 0, "max_score": 20}],
        )
        q3 = resolve_authoritative_result(
            "q3/s1/q3",
            teacher_decisions=[{"id": "bc98dd96-8854-4923-8b7d-de89eecb2af9",
                               "status": "COMPLETE", "score": 40, "max_score": 40,
                               "decision_version": 1}],
            model_results=[{"id": "review", "state": "failed", "score": None,
                            "max_score": 40}],
        )
        self.assertEqual((q2.score, q2.source), (10, "TEACHER_ADJUDICATION"))
        self.assertEqual((q3.score, q3.source), (40, "TEACHER_ADJUDICATION"))
        model = resolve_authoritative_result(
            "q3/s1/q1", model_results=[
                {"id": "old-0", "target": "q3/s1/q1", "state": "completed",
                 "score": 0, "max_score": 30, "completed_at": "2026-01-01",
                 "snapshot_sha256": "old"},
                {"id": "old-5", "target": "q3/s1/q1", "state": "completed",
                 "score": 5, "max_score": 30, "completed_at": "2026-01-02",
                 "superseded": True, "snapshot_sha256": "old"},
                {"id": "current-30", "target": "q3/s1/q1", "state": "completed",
                 "score": 30, "max_score": 30, "completed_at": "2026-01-03",
                 "snapshot_sha256": "current"},
            ], current_snapshot_sha="current")
        self.assertEqual(model.score, 30)

    def test_final_aggregation_and_idempotency(self):
        specs = {
            "sampleQ1/s1": ([20, 20, 30, 10, 10, 10], [16, 20, 30, 10, 10, 5]),
            "sampleQ1/s2": ([20, 20, 30, 10, 10, 10], [16, 4, 10, 10, 5, 5]),
            "sampleQ2/s1": ([20, 20, 40, 20], [20, 20, 40, 20]),
            "sampleQ2/s2": ([20, 20, 40, 20], [5, 0, 0, 10]),
            "sampleQ3/s1": ([30, 30, 40], [30, 30, 40]),
            "sampleQ3/s2": ([30, 30, 40], [5, 5, 15]),
            "sampleQ4/s1": ([30, 20, 20, 40], [30, 15, 15, 35]),
            "sampleQ4/s2": ([30, 20, 20, 40], [30, 10, 10, 20]),
        }
        rows = []
        for group, (maxima, scores) in specs.items():
            test, student = group.split("/")
            for index, (maximum, score) in enumerate(zip(maxima, scores)):
                rows.append({"target": f"{group}/q{index}", "test_id": test,
                             "student_id": student, "score": score, "max_score": maximum,
                             "source": "MODEL", "result_id": f"{group}-{index}"})
        expected = {group: 100 if group.startswith(("sampleQ1/", "sampleQ2/", "sampleQ3/")) else 110
                    for group in specs}
        result = aggregate_authoritative_results(rows, test_totals=expected,
            expected_targets=[row["target"] for row in rows])
        again = aggregate_authoritative_results(rows, test_totals=expected,
            expected_targets=[row["target"] for row in rows])
        self.assertEqual(result["totals"], again["totals"])
        self.assertEqual({k: v["score"] for k, v in result["totals"].items()},
                         {"sampleQ1/s1": 91, "sampleQ1/s2": 50,
                          "sampleQ2/s1": 100, "sampleQ2/s2": 15,
                          "sampleQ3/s1": 100, "sampleQ3/s2": 25,
                          "sampleQ4/s1": 95, "sampleQ4/s2": 70})
        self.assertEqual(len(rows), 34)


if __name__ == "__main__":
    unittest.main()
