"""Deterministic projection of a saved whole-test authoring snapshot."""
from copy import deepcopy
from sqlalchemy import select, func, event, inspect as sa_inspect
from sqlalchemy.orm import Session
from .db.models import (TestQuestion, ModelAnswer, RubricVersion,
    StudentSubmission, GradingJob)


@event.listens_for(Session, "before_flush")
def prevent_mutating_confirmed_formal_state(session, _flush_context, _instances):
    """Keep the mutable legacy grading projection aligned with its active pin."""
    if session.info.get("authoring_confirmation_projection"):
        return
    from .db.models import Test, TestQuestionAsset, TestQuestionCorrection, ConfirmedAuthoringRevision
    if any(isinstance(obj, ConfirmedAuthoringRevision) for obj in (*session.dirty, *session.deleted)):
        raise ValueError("CONFIRMED_AUTHORING_REVISION_IMMUTABLE")
    test_ids = set()
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, Test):
            state = sa_inspect(obj)
            if any(state.attrs[name].history.has_changes() for name in ("name", "description", "total_points", "active_confirmed_revision_id")):
                test_ids.add(obj.id)
        elif isinstance(obj, (TestQuestion, ModelAnswer, RubricVersion)):
            test_ids.add(obj.test_id)
        elif isinstance(obj, TestQuestionAsset):
            question = session.get(TestQuestion, obj.question_id)
            if question:
                test_ids.add(question.test_id)
        elif isinstance(obj, TestQuestionCorrection):
            question = session.get(TestQuestion, obj.test_question_id)
            if question:
                test_ids.add(question.test_id)
    for test_id in test_ids:
        test = session.get(Test, test_id)
        if test and test.active_confirmed_revision_id:
            raise ValueError("TEST_CONFIRMED_REVISION_READ_ONLY")


def project_confirmed_snapshot(session, test, snapshot, actor_id):
    """Project the exact reviewed snapshot into legacy grading tables.

    Existing graded/submitted Tests are deliberately rejected: the legacy
    grading pipeline reads mutable formal rows and cannot select a historical
    whole-Test revision. This prevents confirmation from rewriting history.
    """
    if (session.scalar(select(func.count()).select_from(StudentSubmission).where(StudentSubmission.test_id == test.id))
            or session.scalar(select(func.count()).select_from(GradingJob).where(GradingJob.test_id == test.id))):
        raise ValueError("AUTHORING_HISTORICAL_GRADING_BASIS_UNSUPPORTED")

    existing = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test.id)))
    by_key = {((q.provenance or {}).get("authoring_stable_key") or q.stable_question_key or q.id): q
              for q in existing}
    nodes = [n for n in snapshot.get("nodes", []) if n.get("included", True)]
    keys = {n["stable_key"] for n in nodes}
    parent_keys = {n.get("parent_key") for n in nodes if n.get("parent_key")}
    gradable_keys = keys - parent_keys
    node_by_key = {n["stable_key"]: n for n in nodes}
    def question_path(key):
        chain, seen = [], set()
        while key:
            if key in seen or key not in node_by_key:
                raise ValueError("AUTHORING_INVALID_HIERARCHY")
            seen.add(key)
            node = node_by_key[key]
            chain.append(node["label"]["raw"])
            key = node.get("parent_key")
        return " ".join(reversed(chain))[:32]
    id_by_key = {}
    for node in nodes:
        row = by_key.get(node["stable_key"])
        if row is None:
            row = TestQuestion(test_id=test.id, question_number=question_path(node["stable_key"]),
                sort_order=node["sort_order"], provenance={"authoring_stable_key": node["stable_key"]})
            session.add(row)
            session.flush()
        id_by_key[node["stable_key"]] = row.id
    paths = [question_path(node["stable_key"]) for node in nodes]
    if len(paths) != len(set(paths)):
        raise ValueError("AUTHORING_INVALID_HIERARCHY")
    for node in nodes:
        row = session.get(TestQuestion, id_by_key[node["stable_key"]])
        parent = node.get("parent_key")
        row.question_number = question_path(node["stable_key"])
        row.display_label = node["label"]["raw"][:200]
        row.sort_order = node["sort_order"]
        row.parent_id = id_by_key.get(parent)
        row.stable_question_key = node["stable_key"]
        row.node_type = "subquestion" if parent else "major_question"
        row.is_gradable = node["stable_key"] not in parent_keys
        row.max_points = node.get("score_points") if row.is_gradable else None
        row.question_text = node.get("body_text", "")
        row.content = {"items": deepcopy(node.get("ordered_content", []))}
        row.provenance = {**(row.provenance or {}), "authoring_stable_key": node["stable_key"],
            "authoring_revision_snapshot": True}

    # Questions removed from the working hierarchy are retained for referential
    # integrity but excluded from subsequent grading inputs.
    for row in existing:
        key = (row.provenance or {}).get("authoring_stable_key")
        if key and key not in keys:
            row.is_gradable = False

    current_answers = list(session.scalars(select(ModelAnswer).where(
        ModelAnswer.test_id == test.id, ModelAnswer.is_current.is_(True))))
    next_version = max((a.version for a in session.scalars(select(ModelAnswer).where(
        ModelAnswer.test_id == test.id))), default=0) + 1
    for answer in current_answers:
        answer.is_current = False
    answer_domain = snapshot.get("domains", {}).get("answer") or {}
    answer_entries = answer_domain.get("entries", [])
    for key in gradable_keys:
        value = snapshot.get("answers", {}).get(key, {})
        accepted = [d for d in value.get("diagram_records", []) if d.get("state") == "accepted"]
        included_entries = [e for e in answer_entries if e.get("authoring_question_key") == key
            and e.get("disposition", "include") == "include"]
        provenance = {"authoring_stable_key": key, "source_draft_id": answer_domain.get("draft_id"),
            "source_sha256": answer_domain.get("source_sha256"), "source_material_id": answer_domain.get("material_id"),
            "entries": deepcopy(included_entries), "diagrams": deepcopy(accepted)}
        session.add(ModelAnswer(test_id=test.id, question_id=id_by_key[key], answer_text=value.get("primary", ""),
            material_id=answer_domain.get("material_id"), provenance_json=provenance,
            version=next_version, is_current=True))

    criteria_by_key = snapshot.get("rubrics", {})
    rubric_json = {"questions": []}
    for key in gradable_keys:
        criteria = deepcopy(criteria_by_key.get(key, []))
        # Top-level rows are authoritative and already reflect teacher edits.
        rubric_json["questions"].append({"question_id": id_by_key[key],
            "max_points": next((n.get("score_points") for n in nodes if n["stable_key"] == key), None),
            "criteria": criteria})
    session.execute(__import__('sqlalchemy').update(RubricVersion).where(
        RubricVersion.test_id == test.id, RubricVersion.status == "approved").values(status="superseded"))
    version = (session.scalar(select(func.max(RubricVersion.version)).where(RubricVersion.test_id == test.id)) or 0) + 1
    session.add(RubricVersion(test_id=test.id, version=version, status="approved", source_type="authoring_confirmation",
        rubric_json=rubric_json, rubric_text=None, generation_metadata={"authoring_stable_keys": list(keys)},
        approved_at=__import__("scoring.db.models", fromlist=["now"]).now(), approved_by_user_id=actor_id))
    test.name = snapshot["metadata"]["name"]
    test.description = snapshot["metadata"].get("description") or None
    test.total_points = snapshot["metadata"]["total_points"]
    test.status = "ready"
    session.flush()
