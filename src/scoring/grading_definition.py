"""Canonical Web grading contract. No filesystem assignment or inference dependency.

Compilation is pure: incomplete teacher policy is representable in a draft but
never executable. Saved contracts are recomputed/verified at confirmation.
"""

from copy import deepcopy
import math
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re


from .pdf_native import canonical_hash

SCHEMA = "web-grading-definition.v1"
SHA = re.compile(r"^[0-9a-f]{64}$")


def _integer(value, *, positive=False):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value == int(value)
        and value >= (1 if positive else 0)
    )


def compile_definition(snapshot, evidence=None):
    """Return a deterministic definition and actionable completeness issues."""
    evidence = deepcopy(
        evidence
        if evidence is not None
        else snapshot.get("domains", {}).get("grading_definition", {}).get("evidence", {})
    )
    issues, questions = [], []
    question_domain = snapshot.get("domains", {}).get("question") or {}
    regions = {r["region_id"]: r for r in question_domain.get("document", {}).get("regions", [])}
    pins = {
        r["region_id"]: r
        for r in question_domain.get("snapshot", {}).get("vision_pin", {}).get("results", [])
    }
    nodes = [n for n in snapshot.get("nodes", []) if n.get("included", True)]
    by_key = {n["stable_key"]: n for n in nodes}
    children = {n.get("parent_key") for n in nodes}

    def issue(key, code, message, criterion=None, section="rubric"):
        issues.append(
            {
                "question_key": key,
                "origin": "grading_definition",
                "section": section,
                "code": code,
                "field": "levels" if section == "rubric" else "content",
                "message": message,
                "criterion_id": criterion,
                "expected_state": "この基準で使用する得点と部分点の条件を設定してください。"
                if section == "rubric"
                else "該当する本文・図と元資料を確認してください。",
                "action_label": "得点段階を設定" if section == "rubric" else "本文・図を確認",
            }
        )

    def crop_binding(record, key, role):
        if role == "model_answer_reference":
            domain = snapshot.get("domains", {}).get("answer") or {}
            entry = next(
                (
                    e
                    for e in domain.get("entries", [])
                    if e.get("authoring_question_key") == key
                    and any(
                        r.get("id") == record.get("id")
                        and r.get("crop_sha256") == record.get("crop_sha256")
                        for r in e.get("diagram_records", [])
                    )
                ),
                {},
            )
            source_id = entry.get("source_draft_id") or domain.get("draft_id")
            source = domain.get("sources", {}).get(source_id) or domain
            ir_ref = source.get("artifact_ref")
            if not isinstance(ir_ref, str) or source.get("material_id") != record.get(
                "material_id"
            ):
                return None
            directory = str(PurePosixPath(ir_ref).parent)
            namespace = "answer_import"
        else:
            ref = question_domain.get("document", {}).get("artifact_ref", "")
            if not ref.startswith("question-imports/") or "/review/" not in ref:
                return None
            directory = ref.removeprefix("question-imports/").split("/review/", 1)[0]
            namespace = "question_import"
        relative = str(PurePosixPath(directory) / str(record.get("artifact_ref", "")))
        if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            return None
        return {
            "namespace": namespace,
            "artifact_ref": relative,
            "sha256": record.get("crop_sha256"),
        }

    def references(records, key, role):
        result = []
        for record in records:
            if record.get("state") != "accepted":
                continue
            # Existing domain validators attest source ownership and crop bytes.
            # Freeze the complete record rather than dropping manual/reuse history.
            valid = (
                record.get("teacher_confirmed") or record.get("trust_state", "trusted") == "trusted"
            )
            valid = valid and record.get("trust_state") != "hard_invalid"
            valid = (
                valid
                and SHA.fullmatch(str(record.get("source_sha256", "")))
                and SHA.fullmatch(str(record.get("crop_sha256", "")))
            )
            bbox = (
                record.get("final_bbox") or record.get("crop_bbox") or record.get("automatic_bbox")
            )
            valid = (
                valid
                and isinstance(bbox, list)
                and len(bbox) == 4
                and all(type(v) in (int, float) and math.isfinite(v) for v in bbox)
            )
            valid = valid and bbox[0] < bbox[2] and bbox[1] < bbox[3] if valid else False
            width, height = record.get("page_width"), record.get("page_height")
            valid = bool(
                valid
                and type(record.get("page_index")) is int
                and record["page_index"] >= 0
                and type(width) in (int, float)
                and type(height) in (int, float)
                and math.isfinite(width)
                and math.isfinite(height)
                and width > 0
                and height > 0
                and 0 <= bbox[0] < bbox[2] <= width
                and 0 <= bbox[1] < bbox[3] <= height
                and isinstance(record.get("artifact_ref"), str)
                and bool(record["artifact_ref"])
                and record.get("material_id") in {m["id"] for m in snapshot.get("materials", [])}
            )
            binding = crop_binding(record, key, role)
            valid = valid and binding is not None
            if not valid:
                issue(
                    key,
                    "grading_visual_incomplete",
                    "図を使った採点に必要な参照範囲が未確認です。",
                    section="answer" if role == "model_answer_reference" else "question",
                )
            if not valid:
                issues[-1].update(
                    field="diagram",
                    diagram_id=record.get("id"),
                    action_label="図の参照を確認",
                    expected_state="図の出典と範囲を確認してください。必要ならPDFから図を選び直してください。",
                )
                if role == "model_answer_reference":
                    entry = next(
                        (
                            e
                            for e in snapshot.get("domains", {})
                            .get("answer", {})
                            .get("entries", [])
                            if e.get("authoring_question_key") == key
                            and any(
                                r.get("id") == record.get("id")
                                and r.get("crop_sha256") == record.get("crop_sha256")
                                for r in e.get("diagram_records", [])
                            )
                        ),
                        None,
                    )
                    if entry:
                        issues[-1]["entry_id"] = entry["id"]
            result.append(
                {
                    "role": role,
                    "diagram_id": record.get("id"),
                    "asset_id": "diagram-"
                    + sha256(
                        (str(record.get("id")) + ":" + str(record.get("crop_sha256"))).encode()
                    ).hexdigest(),
                    "sha256": record.get("crop_sha256"),
                    "source_question_id": key,
                    "mime_type": "image/png",
                    "immutable_artifact": binding,
                    "purpose": "question_context"
                    if role == "question_context"
                    else "model_answer_reference",
                    "coordinate_schema": "pdf-page-points-top-left.v1",
                    "page_index": record.get("page_index"),
                    "bbox": deepcopy(bbox),
                    "crop_bbox": deepcopy(record.get("crop_bbox")),
                    "source_role": next(
                        (
                            m.get("role")
                            for m in snapshot.get("materials", [])
                            if m["id"] == record.get("material_id")
                        ),
                        None,
                    ),
                    "crop_renderer_version": "pymupdf-diagram-crop.v1",
                    "record": deepcopy(record),
                }
            )
        return result

    for node in nodes:
        key = node["stable_key"]
        source = evidence.get("questions", {}).get(key, {})
        items, text = [], []
        question_refs = references(node.get("diagram_records", []), key, "question_context")
        authored = node.get(
            "ordered_content", [{"type": "text", "text": node.get("body_text", "")}]
        )
        # Formal-only legacy content is frozen on initial capture; use it only
        # while its captured authoring text projection remains unchanged.
        if source.get("content") and source.get("authoring_content") == authored:
            authored = source["content"].get("items", [])
        for item in authored:
            kind = item.get("type")
            if kind == "text":
                value = str(item.get("text", ""))
                items.append({"type": "text", "text": value})
                text.append(value)
            elif kind in {"formula", "formula_region"}:
                decision = node.get("formula_decisions", {}).get(item.get("region_id"), {})
                if decision.get("decision") in {"excluded", "merged_into_text"}:
                    continue
                value = (
                    item.get("transcription")
                    if kind == "formula"
                    else decision.get("teacher_transcription")
                )
                if kind == "formula_region" and (
                    not decision or decision.get("decision") == "use_native"
                ):
                    value = "\n".join(
                        f.get("native_text", "")
                        for f in regions.get(item.get("region_id"), {}).get("text_fragments", [])
                    )
                elif kind == "formula_region" and decision.get("decision") == "use_vision":
                    value = pins.get(item.get("region_id"), {}).get("candidate")
                if not isinstance(value, str) or not value.strip():
                    issue(
                        key,
                        "grading_question_formula",
                        "採点に使用する数式の本文を確認してください。",
                        section="question",
                    )
                    value = ""
                items.append({"type": "formula", "transcription": value})
                text.append(value)
            elif kind in {"figure", "figure_region"}:
                decision = node.get("figure_decisions", {}).get(item.get("region_id"), {})
                if decision.get("decision") == "excluded":
                    continue
                ref = next(
                    (
                        r
                        for r in question_refs
                        if item.get("region_id")
                        in [
                            r["record"].get("legacy_region_id"),
                            *r["record"].get("legacy_region_ids", []),
                        ]
                    ),
                    None,
                )
                asset = (
                    evidence.get("assets", {}).get(item.get("asset_id"))
                    if kind == "figure"
                    else None
                )
                if asset and (
                    asset.get("mime_type") not in {"image/png", "image/jpeg"}
                    or not SHA.fullmatch(str(asset.get("sha256", "")))
                    or not asset.get("immutable_artifact")
                ):
                    asset = None
                if asset:
                    question_refs.append(
                        {
                            **deepcopy(asset),
                            "role": "question_context",
                            "purpose": "question_context",
                        }
                    )
                if not ref and not asset:
                    issue(
                        key,
                        "grading_question_figure",
                        "問題の図の採点用参照を確認してください。",
                        section="question",
                    )
                reference = deepcopy(ref or asset)
                items.append(
                    {
                        "type": "figure",
                        "asset_id": (ref or {}).get("asset_id") or (asset or {}).get("asset_id"),
                        "sha256": (ref or {}).get("record", {}).get("crop_sha256")
                        or (asset or {}).get("sha256"),
                        "reference": reference,
                    }
                )
                text.append("[図]")
            elif kind == "score_expression":
                items.append({"type": kind, "text": str(item.get("text", ""))})
            else:
                issue(
                    key,
                    "grading_question_schema",
                    "採点に使用する問題本文の形式を確認してください。",
                    section="question",
                )
        if not any(value.strip() for value in text) and not question_refs:
            issue(
                key,
                "question_body",
                "採点に使用する問題文または確認済みの図を確認してください。",
                section="question",
            )
        answer = deepcopy(snapshot.get("answers", {}).get(key, {}))
        selected_entries = [
            deepcopy(e)
            for e in snapshot.get("domains", {}).get("answer", {}).get("entries", [])
            if e.get("authoring_question_key") == key
            and e.get("disposition", "include") == "include"
        ]
        records = {
            (r["id"], r.get("crop_sha256")): r
            for r in answer.get("diagram_records", [])
            if r.get("state") == "accepted"
        }
        for entry in selected_entries:
            records.update(
                {
                    (r["id"], r.get("crop_sha256")): r
                    for r in entry.get("diagram_records", [])
                    if r.get("state") == "accepted"
                }
            )
        answer["diagram_records"] = list(records.values())
        answer["selected_entries"] = selected_entries
        answer_refs = references(answer["diagram_records"], key, "model_answer_reference")
        criteria = []
        used = set()
        executable_ids = set()
        for c in snapshot.get("rubrics", {}).get(key, []) if key not in children else []:
            if c.get("excluded"):
                continue
            cid, points, levels = c.get("id"), c.get("points"), c.get("levels", [])
            identity_valid = isinstance(cid, str) and bool(cid) and cid not in used
            points_valid = _integer(points, positive=True)
            description_valid = isinstance(c.get("description"), str) and bool(
                c["description"].strip()
            )
            if not identity_valid:
                issue(
                    key,
                    "grading_criterion_identity",
                    "採点基準の対応が不明または重複しています。必要な基準を確認してください。",
                    cid,
                )
                issues[-1].update(
                    field="content",
                    action_label="採点基準を修正",
                    expected_state="重複している基準を除外するか、基準を追加し直してください。",
                )
            if not description_valid:
                issue(key, "grading_criterion_description", "採点基準の本文が未設定です。", cid)
                issues[-1].update(
                    field="content",
                    action_label="採点基準を修正",
                    expected_state="この基準で確認する内容を入力してください。",
                )
            if not points_valid:
                issue(
                    key,
                    "grading_criterion_points",
                    "採点基準の配点を正の整数で設定してください。",
                    cid,
                )
                issues[-1].update(
                    field="points",
                    action_label="配点を修正",
                    expected_state="この基準の正しい配点を入力してください。",
                )
            valid = isinstance(levels, list) and bool(levels)
            scores = []
            for level in levels if isinstance(levels, list) else []:
                score = level.get("score") if isinstance(level, dict) else None
                condition = level.get("condition") if isinstance(level, dict) else None
                good = (
                    _integer(score)
                    and (not points_valid or score <= points)
                    and isinstance(condition, str)
                    and bool(condition.strip())
                )
                valid = valid and good
                if good:
                    scores.append(int(score))
            valid = (
                valid
                and len(scores) == len(set(scores))
                and (not points_valid or max(scores, default=-1) == points)
            )
            if not valid:
                issue(
                    key,
                    "grading_levels_incomplete",
                    "採点基準の得点段階が未設定または不完全です。部分点の条件を確認してください。",
                    cid,
                )
            if isinstance(cid, str):
                used.add(cid)
            executable_id = (
                cid
                if isinstance(cid, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", cid)
                else "criterion-" + sha256(str(cid).encode()).hexdigest()
            )
            if executable_id in executable_ids:
                issue(
                    key,
                    "grading_criterion_identity",
                    "採点基準の識別情報が重複しています。対象基準を確認し、必要なら追加し直してください。",
                    cid,
                )
            executable_ids.add(executable_id)
            criteria.append(
                {
                    "criterion_id": cid,
                    "executable_id": executable_id,
                    "description": c.get("description"),
                    "max_score": int(points) if _integer(points) else points,
                    "levels": [
                        {
                            **deepcopy(level),
                            "score": int(level["score"])
                            if _integer(level.get("score"))
                            else level.get("score"),
                        }
                        for level in levels
                        if isinstance(level, dict)
                    ]
                    if isinstance(levels, list)
                    else [],
                }
            )
        if key not in children:
            points = node.get("score_points")
            if points is not None and not _integer(points, positive=True):
                issue(
                    key,
                    "grading_score_contract",
                    "採点に使用する配点は正の整数で設定してください。",
                    section="question",
                )
                issues[-1].update(
                    field="score",
                    action_label="配点を修正",
                    expected_state="設問の配点を正の整数で設定してください。",
                )
        questions.append(
            {
                "question_key": key,
                "parent_key": node.get("parent_key"),
                "sort_order": node.get("sort_order"),
                "label": deepcopy(node.get("label") or {"raw": key}),
                "title": source.get("title"),
                "gradable": key not in children,
                "max_points": node.get("score_points") if key not in children else None,
                "score_semantics": node.get("score_semantics"),
                "effective_score_semantics": "sum_children" if key in children else "direct",
                "content": {"schema_version": "test-question-content.v1", "items": items},
                "own_text": "\n".join(text),
                "answer": answer,
                "rubric": {"aggregation": "sum", "criteria": criteria},
                "visual_references": question_refs + answer_refs,
                "corrections": deepcopy(source.get("corrections", [])),
                "authoring_decisions": {
                    k: deepcopy(node.get(k))
                    for k in (
                        "formula_decisions",
                        "figure_decisions",
                        "math_ocr_edits",
                        "source_mapping_decision",
                    )
                },
            }
        )
    for question in questions:
        chain, seen, current = [], set(), question
        index = {q["question_key"]: q for q in questions}
        while current:
            if current["question_key"] in seen:
                issue(
                    question["question_key"],
                    "grading_hierarchy",
                    "設問の階層を確認してください。",
                    section="question",
                )
                break
            seen.add(current["question_key"])
            chain.append(current)
            parent = current["parent_key"]
            if parent and parent not in by_key:
                issue(
                    question["question_key"],
                    "grading_hierarchy",
                    "親設問の対応を確認してください。",
                    section="question",
                )
                break
            current = index.get(parent)
        chain.reverse()
        question["context"] = {
            "schema_version": "effective-question-context.v1",
            "question_id": question["question_key"],
            "test_id": evidence.get("test_id"),
            "max_points": question["max_points"],
            "is_gradable": question["gradable"],
            "segments": [
                {
                    "source_question_id": q["question_key"],
                    "stable_question_key": q["question_key"],
                    "display_label": q["label"]["raw"],
                    "title": q["title"],
                    "role": "self" if q["question_key"] == question["question_key"] else "ancestor",
                    "items": deepcopy(q["content"]["items"]),
                    "content_sha256": canonical_hash(q["content"]),
                }
                for q in chain
            ],
            "assets": [
                deepcopy(ref)
                for q in chain
                for ref in q["visual_references"]
                if ref["role"] == "question_context"
            ],
            "ancestor_chain": [q["question_key"] for q in chain[:-1]],
            "effective_text": "\n\n".join(
                (f"[{q['label']['raw']}]\n" if len(chain) > 1 else "") + q["own_text"]
                for q in chain
            ),
        }
        question["context"]["context_sha256"] = canonical_hash(question["context"])
    definition = {
        "schema_version": SCHEMA,
        "authority": "web_authoring",
        "interpreter_version": "discrete-integer-sum.v1",
        "complete": bool(nodes)
        and not issues
        and all(
            q["rubric"]["criteria"]
            and sum(c["max_score"] for c in q["rubric"]["criteria"] if _integer(c["max_score"]))
            == q["max_points"]
            for q in questions
            if q["gradable"]
        )
        and all(
            q["answer"].get("primary", "").strip()
            or q["visual_references"]
            and any(r["role"] == "model_answer_reference" for r in q["visual_references"])
            for q in questions
            if q["gradable"]
        )
        and sum(q["max_points"] for q in questions if q["gradable"] and _integer(q["max_points"]))
        == snapshot.get("metadata", {}).get("total_points"),
        "total_points": snapshot.get("metadata", {}).get("total_points"),
        "questions": questions,
        "materials": deepcopy(snapshot.get("materials", [])),
        "source_provenance": deepcopy(snapshot.get("source_provenance", {})),
        "source_bindings": {
            name: {
                k: (
                    {
                        field: deepcopy(value)
                        for field, value in v.items()
                        if field
                        in {
                            "id",
                            "draft_id",
                            "test_id",
                            "artifact_ref",
                            "source_pdf_sha256",
                            "source_ir_sha256",
                            "revision_sha256",
                            "page_count",
                        }
                    }
                    if k == "document"
                    else deepcopy(v)
                )
                for k, v in domain.items()
                if k
                in {
                    "draft_id",
                    "material_id",
                    "source_sha256",
                    "artifact_ref",
                    "sources",
                    "document",
                }
            }
            for name, domain in snapshot.get("domains", {}).items()
            if name in {"question", "answer", "rubric"} and isinstance(domain, dict)
        },
        "evidence": evidence,
    }
    return definition, issues


def freeze_definition(snapshot, evidence=None):
    snapshot.setdefault("domains", {})["grading_definition"] = compile_definition(
        snapshot, evidence
    )[0]


def executable_definition(snapshot):
    """Read only the immutable snapshot; never upgrade legacy revisions."""
    frozen = snapshot.get("domains", {}).get("grading_definition")
    if not isinstance(frozen, dict) or frozen.get("schema_version") != SCHEMA:
        raise ValueError("GRADING_DEFINITION_LEGACY_INCOMPLETE")
    expected, issues = compile_definition(snapshot)
    if issues or not expected["complete"] or frozen != expected:
        raise ValueError("GRADING_DEFINITION_INCOMPLETE_OR_CHANGED")
    return deepcopy(frozen)


def executable_rubric(snapshot, question_key):
    definition = executable_definition(snapshot)
    question = next(
        (q for q in definition["questions"] if q["question_key"] == question_key and q["gradable"]),
        None,
    )
    if not question:
        raise ValueError("GRADING_DEFINITION_QUESTION_NOT_FOUND")
    rubric = {
        **deepcopy(question["rubric"]),
        "question_id": question_key,
        "max_score": int(question["max_points"]),
    }
    for criterion in rubric["criteria"]:
        criterion["authoring_criterion_id"] = criterion["criterion_id"]
        criterion["criterion_id"] = criterion.pop("executable_id")
    from .core import validate_rubric

    validate_rubric(rubric)
    return rubric


def capture_evidence(session, snapshot, test_id):
    """Capture auxiliary formal context once, never on a confirmed read path."""
    from sqlalchemy import select
    from .db.models import TestQuestion, TestQuestionAsset, TestQuestionCorrection

    questions, assets = {}, {}
    rows = session.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)).all()
    by_key = {
        ((q.provenance or {}).get("authoring_stable_key") or q.stable_question_key or q.id): q
        for q in rows
    }
    for node in snapshot.get("nodes", []):
        row = by_key.get(node["stable_key"]) or next(
            (q for q in rows if q.id == node["stable_key"]), None
        )
        if row:
            corrections = session.scalars(
                select(TestQuestionCorrection)
                .where(TestQuestionCorrection.test_question_id == row.id)
                .order_by(TestQuestionCorrection.correction_version)
            ).all()
            questions[node["stable_key"]] = {
                "title": row.title,
                "content": deepcopy(row.content),
                "authoring_content": deepcopy(node.get("ordered_content", [])),
                "corrections": [
                    {
                        "id": c.id,
                        "version": c.correction_version,
                        "previous_content_sha256": c.previous_content_sha256,
                        "new_content_sha256": c.new_content_sha256,
                    }
                    for c in corrections
                ],
            }
            for asset in session.scalars(
                select(TestQuestionAsset).where(TestQuestionAsset.question_id == row.id)
            ):
                assets[asset.id] = {
                    "asset_id": asset.id,
                    "mime_type": asset.mime_type,
                    "asset_type": asset.asset_type,
                    "sha256": asset.sha256,
                    "artifact_ref": asset.artifact_ref,
                    "immutable_artifact": {
                        "namespace": "question_import",
                        "artifact_ref": str(
                            PurePosixPath(str((asset.provenance or {}).get("extraction_id", "")))
                            / asset.artifact_ref
                        ),
                        "sha256": asset.sha256,
                    },
                    "provenance": deepcopy(asset.provenance),
                    "question_key": node["stable_key"],
                }
    return {"test_id": test_id, "questions": questions, "assets": assets}


def reject_web_legacy_policy(session, test_id):
    """Explicit boundary: legacy assignment cannot override a Web edition."""
    from .db.models import Test, ConfirmedAuthoringRevision

    test = session.get(Test, test_id)
    confirmed = (
        session.get(ConfirmedAuthoringRevision, test.active_confirmed_revision_id)
        if test and test.active_confirmed_revision_id
        else None
    )
    if confirmed and canonical_hash(confirmed.snapshot) != confirmed.snapshot_sha256:
        raise ValueError("GRADING_DEFINITION_SNAPSHOT_HASH_MISMATCH")
    if confirmed and "grading_definition" in confirmed.snapshot.get("domains", {}):
        raise ValueError("LEGACY_ASSIGNMENT_NOT_ALLOWED_FOR_WEB_TEST")


def verify_artifacts(session, snapshot, test_id, question_root, answer_root):
    """Verify immutable bytes at confirmation; never discover/render a crop."""
    from types import SimpleNamespace
    from .authoring_revision_artifacts import confirmed_crop_path
    from .grading_context import asset_path
    from .db.models import TestQuestionAsset

    owner = SimpleNamespace(snapshot=snapshot, test_id=test_id)
    for entry in snapshot.get("domains", {}).get("answer", {}).get("entries", []):
        if entry.get("disposition", "include") != "include":
            continue
        for record in entry.get("diagram_records", []):
            if record.get("state") == "accepted":
                confirmed_crop_path(
                    session, owner, entry["id"], record["id"], question_root, answer_root
                )
    for node in snapshot.get("nodes", []):
        if not node.get("included", True):
            continue
        for record in node.get("diagram_records", []):
            if record.get("state") == "accepted":
                confirmed_crop_path(
                    session, owner, node["stable_key"], record["id"], question_root, answer_root
                )
    for ref in (
        snapshot.get("domains", {})
        .get("grading_definition", {})
        .get("evidence", {})
        .get("assets", {})
        .values()
    ):
        asset = session.get(TestQuestionAsset, ref["asset_id"])
        if not asset or asset.sha256 != ref["sha256"] or asset.artifact_ref != ref["artifact_ref"]:
            raise ValueError("GRADING_DEFINITION_ASSET_CHANGED")
        asset_path(asset, question_root)


def confirmed_definition(revision):
    """Future grading entry point: attest payload hash before reading policy."""
    if canonical_hash(revision.snapshot) != revision.snapshot_sha256:
        raise ValueError("GRADING_DEFINITION_SNAPSHOT_HASH_MISMATCH")
    return executable_definition(revision.snapshot)


def reject_mutable_web_execution(session, test_id):
    # J.GRADING.1 must route jobs through immutable Submission bindings. Until
    # then a newly compiled Web edition must not fall back to current rows.
    try:
        reject_web_legacy_policy(session, test_id)
    except ValueError as exc:
        if str(exc) != "LEGACY_ASSIGNMENT_NOT_ALLOWED_FOR_WEB_TEST":
            raise
        raise ValueError("WEB_GRADING_REVISION_BINDING_REQUIRED") from exc


def read_reference_asset(reference, roots):
    """Read content-addressed grading bytes using only frozen identity + roots."""
    from .pdf_native import sha256_file

    artifact = reference.get("immutable_artifact")
    if not isinstance(artifact, dict) or artifact.get("namespace") not in roots:
        raise ValueError("GRADING_DEFINITION_ARTIFACT_UNAVAILABLE")
    root = Path(roots[artifact["namespace"]]).resolve()
    relative = artifact.get("artifact_ref")
    if (
        not isinstance(relative, str)
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
    ):
        raise ValueError("GRADING_DEFINITION_ARTIFACT_INVALID")
    path = (root / relative).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or sha256_file(path) != artifact.get("sha256")
    ):
        raise ValueError("GRADING_DEFINITION_ARTIFACT_CHANGED")
    return path


def snapshot_evidence(snapshot, test_id=None):
    """Complete a legacy fork from its own saved evidence, never current rows."""
    sources = {q["id"]: q for q in snapshot.get("source_provenance", {}).get("questions", [])}
    return {
        "test_id": test_id,
        "questions": {
            n["stable_key"]: {
                "title": sources.get(n["stable_key"], {}).get("title"),
                "content": deepcopy(sources.get(n["stable_key"], {}).get("content")),
                "authoring_content": deepcopy(n.get("ordered_content", [])),
                "corrections": [],
            }
            for n in snapshot.get("nodes", [])
        },
        "assets": {
            a["id"]: deepcopy(a) for a in snapshot.get("source_provenance", {}).get("assets", [])
        },
    }
