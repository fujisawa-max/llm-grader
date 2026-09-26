"""Prepare immutable domain inputs at the existing legacy grading boundary."""

from copy import deepcopy
from pathlib import Path
import shutil

from .core import load_assignment
from .adapters.artifacts import RunArtifactAdapter
from .grading_context import GradingReadinessService, asset_path, artifact_root
from .db.models import TestQuestionAsset
from .pdf_native import canonical_hash, sha256_file


def prepare_inputs(session, test_id, questions, answers, rubric, assignment_path,
                   run_path, *, root=None):
    """Require explicit, exact compatibility IDs; never infer answer-page mapping.

The existing assignment retains its teacher-authored rubric levels. They must
match the approved domain rubric's criteria; no rubric levels are generated.
"""
    readiness = GradingReadinessService(session, root=root)
    if not readiness.evaluate(test_id)["can_start_grading"]:
        raise ValueError("GRADING_NOT_READY")
    _, legacy, _ = load_assignment(assignment_path)
    from .grading_mapping import GradingInputAssembler
    assembler = GradingInputAssembler(session, test_id, root=root)
    if rubric.id != (assembler.rubric.id if assembler.rubric else None):
        raise ValueError("APPROVED_RUBRIC_MISMATCH")
    selected_answers = {a.id for values in assembler.answers.values() for a in values}
    if {a.id for a in answers if a.is_current} != selected_answers:
        raise ValueError("MODEL_ANSWER_QUESTION_MISMATCH")
    inputs = {}
    seen = set()
    for entry in legacy:
        q, _, _ = assembler.resolver.resolve({"question_id": entry["question_id"]})
        if q.id in seen:
            raise ValueError("AMBIGUOUS_QUESTION_MAPPING")
        seen.add(q.id)
        part = assembler.question_part(q.id)
        expected = part["rubric"]["entry"]
        actual = entry["rubric_data"]
        expected_criteria = [(c["id"], c["points"], c["description"]) for c in expected["criteria"]]
        actual_criteria = [(c["criterion_id"], c["max_score"], c.get("description", c.get("name", ""))) for c in actual["criteria"]]
        if (actual["max_score"] != q.max_points or expected_criteria != actual_criteria
                or actual.get("aggregation", "sum") != "sum"):
            raise ValueError("ASSIGNMENT_RUBRIC_MISMATCH")
        context = part["question"]["context"]
        inputs[entry["question_id"]] = {"context": context, "reference_text": part["model_answer"]["content"],
                                       "rubric_data": deepcopy(actual), "assets": []}
    if seen != {q.id for q in assembler.questions if q.is_gradable}:
        raise ValueError("ASSIGNMENT_QUESTION_MAPPING_MISMATCH")
    # Files are content-addressed and copied only after all input contracts pass.
    for value in inputs.values():
        for ref in value["context"]["assets"]:
            a = session.get(TestQuestionAsset, ref["asset_id"])
            source = asset_path(a, artifact_root(root))
            target = RunArtifactAdapter(run_path).path("inputs/domain-assets/" + a.sha256 + source.suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)
            if sha256_file(target) != a.sha256:
                raise ValueError("ASSET_HASH_MISMATCH")
            value["assets"].append({"path": str(target.resolve()), "sha256": a.sha256})
    return inputs


def apply_inputs(questions, inputs):
    """Pure text/content overlay plus integrity checks; scoring logic is untouched."""
    if inputs is None:
        return questions
    if set(inputs) != {q["question_id"] for q in questions}:
        raise ValueError("ASSIGNMENT_QUESTION_MAPPING_MISMATCH")
    result = deepcopy(questions)
    for q in result:
        value = inputs[q["question_id"]]
        context = value["context"]
        if canonical_hash({k: v for k, v in context.items() if k != "context_sha256"}) != context["context_sha256"]:
            raise ValueError("CONTEXT_HASH_MISMATCH")
        paths = []
        for ref in value["assets"]:
            path = Path(ref["path"])
            if not path.is_file() or sha256_file(path) != ref["sha256"]:
                raise ValueError("ASSET_HASH_MISMATCH")
            paths.append(path)
        q.update(text=context["effective_text"], reference_text=value["reference_text"],
                 rubric_data=value["rubric_data"], asset_paths=paths)
    return result
