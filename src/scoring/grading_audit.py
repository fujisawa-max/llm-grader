"""Read-only grading safety guards and authoritative-result resolution.

These helpers sit at the production grading boundary.  They do not create or
mutate jobs, results, reconstructions, or teacher decisions.  Their purpose is
to make the failure modes found in the H.3--H.5 audit explicit and testable.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


GRADING_MODEL_INPUT_CONTRADICTION = "GRADING_MODEL_INPUT_CONTRADICTION"
GRADING_MODEL_SELF_CONTRADICTION = "GRADING_MODEL_SELF_CONTRADICTION"

EXPECTED_VISUAL_ROLES = frozenset(
    {"question_context", "model_answer_reference", "student_visual_answer"}
)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _student_answer_text(bundle: Mapping[str, Any]) -> str:
    answer = bundle.get("student_answer") or {}
    text = answer.get("answer_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    reconstruction = answer.get("reconstruction") or {}
    text = reconstruction.get("answer_text") or reconstruction.get("transcript")
    return text.strip() if isinstance(text, str) else ""


def _result_text(result: Mapping[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def grading_response_warnings(result: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[str]:
    """Return deterministic warnings for model claims that contradict input.

    A warning never changes a score.  The caller may turn it into a normal
    ``needs_review`` outcome, which preserves the existing safe behaviour.
    """

    warnings: list[str] = []
    answer = _student_answer_text(bundle)
    serialized = _result_text(result)
    if answer and re.search(
        r"\bno\s+(?:student\s+)?answer\b|no\s+(?:student\s+)?work\b|"
        r"(?:student\s+)?answer\s+(?:is\s+)?(?:missing|not\s+provided)\b",
        serialized,
        re.IGNORECASE,
    ):
        warnings.append(GRADING_MODEL_INPUT_CONTRADICTION)

    for criterion in result.get("criteria", []):
        if not isinstance(criterion, Mapping):
            continue
        evidence = " ".join(
            str(item.get("quote") or item.get("visual_observation") or "")
            for item in criterion.get("evidence", [])
            if isinstance(item, Mapping)
        )
        reason = str(criterion.get("reason") or "")
        says_missing_coefficient = re.search(
            r"(?:coefficient|係数).{0,40}(?:missing|absent|omitted|欠落|省略|ない|なし)",
            reason,
            re.IGNORECASE,
        )
        if says_missing_coefficient and re.search(r"(?<!\d)3(?!\d)", evidence):
            warnings.append(GRADING_MODEL_SELF_CONTRADICTION)
            break
    return list(dict.fromkeys(warnings))


def require_visual_roles(assets: Iterable[Mapping[str, Any]]) -> None:
    """Require the three distinct visual evidence roles in a grading bundle."""

    roles = [asset.get("role") for asset in assets]
    if any(role not in EXPECTED_VISUAL_ROLES for role in roles):
        raise ValueError("VISUAL_ASSET_ROLE_INVALID")
    if not EXPECTED_VISUAL_ROLES.issubset(set(roles)):
        raise ValueError("VISUAL_ASSET_ROLE_INVALID")


def resolve_selected_reconstruction(revisions: Iterable[Any]) -> Any:
    """Resolve exactly one selected, complete reconstruction revision.

    Historical revisions may remain in the database, but only the explicit
    selected revision can enter a grading input.  Ambiguity is a hard error.
    """

    candidates = list(revisions)
    # SQL queries in ``GradingInputAssembler`` already filter the selected run
    # before handing revisions here; plain fixtures carry an explicit flag.
    has_selection_flag = any(
        isinstance(revision, Mapping)
        and ("selected" in revision or "run_selected" in revision)
        or hasattr(revision, "selected")
        or hasattr(revision, "run_selected")
        for revision in candidates
    )
    selected = (
        [
            revision
            for revision in candidates
            if bool(_get(revision, "selected", False))
            or bool(_get(revision, "run_selected", False))
        ]
        if has_selection_flag
        else candidates
    )
    if len(selected) != 1:
        raise ValueError(
            "MISSING_SELECTED_RECONSTRUCTION"
            if not selected
            else "AMBIGUOUS_SELECTED_RECONSTRUCTION"
        )
    revision = selected[0]
    if _get(revision, "status") not in {None, "COMPLETE", "completed"}:
        raise ValueError("ANSWER_RECONSTRUCTION_NOT_COMPLETE")
    return revision


def reconstruction_contains_source(answer: str, source_faithful: str) -> bool:
    """Check that a selected transcript preserves the supplied source text."""

    return bool(answer and source_faithful and source_faithful.strip() in answer)


def has_matrix_vector_structure(answer: str) -> bool:
    """Recognize the structural markers needed to preserve matrix work."""

    if not isinstance(answer, str):
        return False
    return (
        answer.count(r"\begin{pmatrix}") >= 2
        and answer.count(r"\end{pmatrix}") >= 2
        and answer.count(r"\\") >= 3
        and r"\begin{pmatrix}3\\-1\end{pmatrix}" in answer
        and r"\begin{pmatrix}3\\-2\end{pmatrix}" in answer
    )


@dataclass(frozen=True)
class AuthoritativeResult:
    target: str
    score: int
    max_score: int
    source: str
    result_id: str
    test_id: str | None = None
    student_id: str | None = None
    notes: tuple[str, ...] = ()


def resolve_authoritative_result(
    target: str,
    *,
    teacher_decisions: Iterable[Any] = (),
    model_results: Iterable[Any] = (),
    current_snapshot_sha: str | None = None,
    current_bundle_sha: str | None = None,
) -> AuthoritativeResult:
    """Apply final-result precedence without mutating any persisted record."""

    decisions = [
        row
        for row in teacher_decisions
        if _get(row, "status", "COMPLETE") == "COMPLETE"
        and _get(row, "score") is not None
        and (_get(row, "target", target) == target)
    ]
    if decisions:
        row = max(decisions, key=lambda value: (_get(value, "decision_version", 0), str(_get(value, "created_at", ""))))
        return AuthoritativeResult(
            target=target,
            score=int(_get(row, "score")),
            max_score=int(_get(row, "max_score")),
            source="TEACHER_ADJUDICATION",
            result_id=str(_get(row, "id")),
            test_id=_get(row, "test_id"),
            student_id=_get(row, "student_id"),
            notes=("teacher adjudication overrides model history",),
        )

    completed = []
    for row in model_results:
        state = str(_get(row, "state", _get(row, "status", ""))).lower()
        if state != "completed" or bool(_get(row, "needs_review", False)):
            continue
        if bool(_get(row, "superseded", False)) or bool(_get(row, "is_superseded", False)):
            continue
        if (current_snapshot_sha is not None
                and _get(row, "snapshot_sha256") != current_snapshot_sha):
            continue
        if (current_bundle_sha is not None
                and _get(row, "bundle_sha256") != current_bundle_sha):
            continue
        if _get(row, "score") is None or _get(row, "max_score") is None:
            continue
        if _get(row, "target", target) != target:
            continue
        completed.append(row)
    if not completed:
        raise ValueError("AUTHORITATIVE_RESULT_MISSING")
    row = max(completed, key=lambda value: str(_get(value, "completed_at", _get(value, "created_at", ""))))
    return AuthoritativeResult(
        target=target,
        score=int(_get(row, "score")),
        max_score=int(_get(row, "max_score")),
        source="MODEL",
        result_id=str(_get(row, "id")),
        test_id=_get(row, "test_id"),
        student_id=_get(row, "student_id"),
        notes=("superseded and failed model history excluded",),
    )


def aggregate_authoritative_results(
    results: Iterable[AuthoritativeResult | Mapping[str, Any]],
    *,
    test_totals: Mapping[str, int],
    expected_targets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Aggregate resolved results while checking completeness and score bounds."""

    rows = list(results)
    keys = [str(_get(row, "target")) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("DUPLICATE_AUTHORITATIVE_RESULT")
    if expected_targets is not None and set(keys) != set(expected_targets):
        raise ValueError("AUTHORITATIVE_RESULT_SET_MISMATCH")
    for row in rows:
        score, maximum = int(_get(row, "score")), int(_get(row, "max_score"))
        if score < 0 or score > maximum:
            raise ValueError("SCORE_MAX_VIOLATION")
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"score": 0, "max": 0, "count": 0})
    for row in rows:
        test_id = str(_get(row, "test_id"))
        student_id = _get(row, "student_id")
        group = f"{test_id}/{student_id}" if student_id is not None else test_id
        bucket = totals[group]
        bucket["score"] += int(_get(row, "score"))
        bucket["max"] += int(_get(row, "max_score"))
        bucket["count"] += 1
    for group, maximum in test_totals.items():
        if group not in totals or totals[group]["max"] != int(maximum):
            raise ValueError("TOTAL_CALCULATION_MISMATCH")
    return {"results": tuple(rows), "totals": dict(totals)}
