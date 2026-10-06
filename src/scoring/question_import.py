"""Deterministic reviewed-revision projection and confirmation service."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from .db.models import (
    QuestionImportReview,
    QuestionImportExtraction,
    Test,
    TestQuestion,
    QuestionImportConfirmation,
    QuestionImportConfirmationItem,
    TestQuestionAsset,
    TestMaterial,
)
from .pdf_native import canonical_hash, sha256_file
from .question_reviews import QuestionReviewService, ReviewError, evidence_prefix
from .review_document import validate_snapshot

SCHEMA = "question-import-confirm-v1"


def _items(node):
    return (node.get("ordered_content") or []) if isinstance(node, dict) else []


def safe_native_formula(region):
    """Only a single verbatim native span is an unambiguous linear transcription.

    Multi-span spatial expressions require an explicit teacher transcription.
    No concatenation, whitespace repair, exponent or fraction inference.
    """
    fragments = region.get("text_fragments", [])
    if len(fragments) != 1:
        return None
    value = fragments[0].get("native_text")
    return value if isinstance(value, str) and value.strip() else None


class QuestionImportPlanner:
    def __init__(self, session, root):
        self.s, self.root = session, Path(root).resolve()

    def _load(self, review_id):
        svc = QuestionReviewService(self.s, self.root)
        review = svc._review(review_id)
        draft, store, dv, ir = svc._draft(review.draft_id)
        rev = svc._revision(review, store)
        return svc, review, draft, store, dv, ir, rev

    def plan(self, review_id):
        svc, review, draft, store, dv, ir, rev = self._load(review_id)
        snap = rev.snapshot
        svc._verify_pin(store, snap.get("vision_pin", {}))
        region_by_id = {
            r["region_id"]: r
            for kind in ("formula", "figure")
            for r in dv.get(f"{kind}_regions", [])
        }
        blockers = []
        extraction = self.s.get(QuestionImportExtraction, draft.extraction_id)
        material = self.s.get(TestMaterial, extraction.material_id)
        if material.material_type == "corrected_question_sheet":
            blockers.append("correction_comparison_not_confirmable")
        warnings = []
        nodes = list(snap.get("nodes", []))
        included = [n for n in nodes if n.get("included", True)]
        if review.state != "reviewed" or snap.get("state") != "reviewed":
            blockers.append("review_not_reviewed")
        if not blockers:
            try:
                validate_snapshot(snap, snap, dv, snap["vision_pin"], mark=True)
            except ReviewError as exc:
                blockers.append(exc.code)
        by = {n["stable_key"]: n for n in nodes}
        inc_keys = {n["stable_key"] for n in included}
        children = {k: [] for k in inc_keys}
        for n in included:
            p = n.get("parent_key")
            if p and p not in inc_keys:
                blockers.append(f"orphan:{n.get('stable_key')}")
            if p in children:
                children[p].append(n)
        for k, ch in children.items():
            ch.sort(key=lambda n: (n.get("sort_order", 0), n.get("stable_key", "")))
        existing = list(
            self.s.scalars(
                select(TestQuestion).where(
                    TestQuestion.test_id
                    == self.s.get(QuestionImportExtraction, draft.extraction_id).test_id
                )
            )
        )
        existing_nums = {q.question_number for q in existing}
        existing_keys = {q.stable_question_key for q in existing if q.stable_question_key}
        roots = [n for n in included if not n.get("parent_key")]
        roots.sort(key=lambda n: (n.get("sort_order", 0), n.get("stable_key", "")))
        path = {}

        def walk(n, prefix):
            if n["stable_key"] in path:
                blockers.append("hierarchy_cycle")
                return
            path[n["stable_key"]] = prefix
            for i, c in enumerate(children.get(n["stable_key"], []), 1):
                walk(c, f"{prefix}.{i}")

        for i, n in enumerate(roots, 1):
            walk(n, str(i))
        if len(path) != len(included):
            blockers.append("hierarchy_cycle_or_orphan")
        root_offset = max((q.sort_order for q in existing if q.parent_id is None), default=-1) + 1
        plans = []
        planned_nums = set()
        for n in sorted(
            included,
            key=lambda x: (
                len(path.get(x.get("stable_key"), "").split(".")),
                path.get(x.get("stable_key"), ""),
            ),
        ):
            key = n.get("stable_key") or n.get("review_node_id")
            kids = children.get(key, [])
            grad = not kids
            if kids and n.get("score_semantics") == "direct" and n.get("score_points") is not None:
                blockers.append(f"parent_direct_score:{key}")
            mode = n.get("score_semantics") or "unset"
            pts = n.get("score_points")
            if mode == "sum_children" and not kids:
                blockers.append(f"sum_children_requires_children:{key}")
            if kids and mode == "unset":
                warnings.append(f"score_method_unset:{key}")
            if mode == "ambiguous":
                blockers.append(f"ambiguous_score:{key}")
            if mode == "each_child" and kids:
                for c in kids:
                    if c.get("score_semantics") == "direct" and c.get("score_points") not in (
                        None,
                        pts,
                    ):
                        blockers.append(f"score_conflict:{key}")
            effective = pts if grad and mode == "direct" else None
            parent = by.get(n.get("parent_key"), {})
            if grad and parent.get("score_semantics") == "each_child":
                inherited = parent.get("score_points")
                if mode not in {"unset", "direct"} or (
                    effective is not None and effective != inherited
                ):
                    blockers.append(f"score_conflict:{key}")
                else:
                    effective = inherited
            if kids and parent.get("score_semantics") == "each_child":
                blockers.append(f"each_child_structural_child:{key}")
            if grad and effective is None:
                warnings.append(f"score_unset:{key}")
            content = []
            formula_dec = n.get("formula_decisions") or {}
            figure_dec = n.get("figure_decisions") or {}
            diagram_records = n.get('diagram_records', [])
            if diagram_records:
                from .diagram_review import question_diagram_review
                try:
                    diagram_review = question_diagram_review(svc, review_id, key, rev.revision_number)
                    diagram_records = diagram_review.validate(diagram_records, rev.revision_number)
                except ValueError as exc:
                    blockers.append(str(exc))
                    diagram_records = []
            used_diagrams = set()
            for it in _items(n):
                typ = it.get("type")
                if typ == "text":
                    content.append({"type": "text", "text": it.get("text", "")})
                elif typ == "score_expression":
                    content.append(deepcopy(it))
                elif typ == "formula_region":
                    rid = it.get("region_id")
                    d = formula_dec.get(rid, {}) if isinstance(formula_dec, dict) else {}
                    decision = d.get("decision", "unreviewed")
                    trans = d.get("teacher_transcription") or d.get("transcription")
                    pin = next(
                        (
                            p
                            for p in snap.get("vision_pin", {}).get("results", [])
                            if p.get("region_id") == rid
                        ),
                        None,
                    )
                    value = None
                    source_region = region_by_id.get(rid, {})
                    if decision == "teacher_edit":
                        value = trans
                    elif decision == "use_vision" and pin:
                        view = json.loads(
                            svc._artifact(store, pin["view_ref"], pin["view_sha256"]).read_text()
                        )
                        value = view.get("transcription_normalized") or view.get("output", {}).get(
                            "recognized_expression"
                        )
                    elif decision == "use_native":
                        value = safe_native_formula(source_region)
                        if value is None:
                            blockers.append(f"native_formula_requires_teacher_edit:{rid}")
                    if not value:
                        blockers.append(f"formula_unresolved:{rid}")
                        value = ""
                    content.append(
                        {
                            "type": "formula",
                            "transcription": value,
                            "source_region_id": rid,
                            "resolution_source": decision,
                            "provenance": {
                                "review_node_id": n.get("review_node_id"),
                                "review_revision": rev.revision_number,
                                "vision_hash": (pin or {}).get("view_sha256"),
                                "evidence_identity": deepcopy(d.get("evidence_identity", {})),
                                "native_sha256": canonical_hash(source_region),
                            },
                        }
                    )
                elif typ == "figure_region":
                    rid = it.get("region_id")
                    d = figure_dec.get(rid, {}) if isinstance(figure_dec, dict) else {}
                    decision = d.get("decision", "unreviewed")
                    diagram = next((r for r in diagram_records if rid in r.get('legacy_region_ids', [r.get('legacy_region_id')])), None)
                    if decision == 'excluded' or diagram and diagram['state'] == 'excluded':
                        continue
                    if diagram and diagram['state'] == 'accepted':
                        if diagram['id'] not in used_diagrams:
                            content.append({'type': 'figure', 'source_region_id': rid,
                                'asset_key': diagram['crop_sha256'], 'diagram': diagram})
                            used_diagrams.add(diagram['id'])
                        continue
                    if decision != "accepted_as_evidence":
                        blockers.append(f"figure_unresolved:{rid}")
                    content.append(
                        {
                            "type": "figure",
                            "source_region_id": rid,
                            "asset_key": (
                                next(
                                    (
                                        p.get("crop_sha256")
                                        for p in snap.get("vision_pin", {}).get("results", [])
                                        if p.get("region_id") == rid
                                    ),
                                    None,
                                )
                            ),
                        }
                    )
                else:
                    content.append(deepcopy(it))
            content.extend({'type': 'figure', 'source_region_id': r['id'],
                'asset_key': r['crop_sha256'], 'diagram': r} for r in diagram_records
                if r['state'] == 'accepted' and not r.get('legacy_region_id'))
            qnum = path.get(key, key)
            if qnum in existing_nums:
                qnum = f"import-{key}"[:32]
            if qnum in planned_nums or qnum in existing_nums:
                blockers.append(f"question_number_collision:{qnum}")
            planned_nums.add(qnum)
            stable = f"review-{review.id[:12]}-{key}"[:128]
            if stable in existing_keys:
                blockers.append(f"stable_key_collision:{stable}")
            text = "".join(
                x.get("text", "")
                if x.get("type") == "text"
                else x.get("transcription", "")
                if x.get("type") == "formula"
                else "[図]"
                if x.get("type") == "figure"
                else ""
                for x in content
            )
            plans.append(
                {
                    "review_node_id": n.get("review_node_id") or key,
                    "review_key": key,
                    "source_draft_stable_key": n.get("source_draft_stable_key"),
                    "stable_question_key": stable,
                    "question_number": qnum,
                    "display_label": n.get("label", {}).get("normalized")
                    if isinstance(n.get("label"), dict)
                    else n.get("label"),
                    "parent_key": n.get("parent_key"),
                    "node_type": n.get("node_type", "standalone"),
                    "is_gradable": grad,
                    "question_text": text,
                    "content": {
                        "schema_version": "test-question-content.v1",
                        "items": content,
                        "score": {
                            "mode": mode,
                            "points": pts,
                            "inherited_from": n.get("parent_key")
                            if parent.get("score_semantics") == "each_child"
                            else None,
                        },
                    },
                    "max_points": effective,
                    "score_mode": mode,
                    "score_points": pts,
                    "sort_order": n.get("sort_order", 0)
                    + (root_offset if not n.get("parent_key") else 0),
                }
            )
        unresolved_score_method = any(
            children.get(n.get("stable_key") or n.get("review_node_id")) and
            n.get("score_semantics") in {"unset", "ambiguous"}
            for n in included
        )
        if unresolved_score_method or any(p["is_gradable"] and p["max_points"] is None for p in plans):
            warnings.append("total_unresolved")
        total = (
            sum(p["max_points"] for p in plans if p["is_gradable"] and p["max_points"] is not None)
            if not unresolved_score_method and not any(p["is_gradable"] and p["max_points"] is None for p in plans)
            else None
        )
        plan = {
            "schema_version": SCHEMA,
            "review_id": review.id,
            "draft_id": draft.id,
            "test_id": self.s.get(QuestionImportExtraction, draft.extraction_id).test_id,
            "revision": rev.revision_number,
            "revision_sha256": rev.revision_sha256,
            "source_draft_sha256": draft.draft_sha256,
            "nodes": plans,
            "excluded_count": len(nodes) - len(included),
            "existing_question_count": len(existing),
            "existing_questions_sha256": canonical_hash(
                sorted(
                    [
                        {
                            c.name: (
                                getattr(q, c.name).isoformat()
                                if hasattr(getattr(q, c.name), "isoformat")
                                else getattr(q, c.name)
                            )
                            for c in TestQuestion.__table__.columns
                        }
                        for q in existing
                    ],
                    key=lambda q: q["id"],
                )
            ),
            "structural_count": sum(not p["is_gradable"] for p in plans),
            "gradable_count": sum(p["is_gradable"] for p in plans),
            "formula_count": sum(
                i["type"] == "formula" for p in plans for i in p["content"]["items"]
            ),
            "figure_count": sum(
                i["type"] == "figure" for p in plans for i in p["content"]["items"]
            ),
            "total_points": total,
            "score_ready": total is not None,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "import_mode": "append",
        }
        for p in plans:
            for item in p["content"]["items"]:
                if item.get("type") == "figure" and not item.get("asset_key"):
                    plan["blockers"].append(f"figure_asset_missing:{item['source_region_id']}")
        plan["import_ready"] = not plan["blockers"]
        plan["plan_sha256"] = canonical_hash(plan)
        return plan


def write_artifact(path, value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        out.write(payload)
    if sha256_file(path) != canonical_hash(value):
        raise ReviewError("confirmation_artifact_write_error")
    return canonical_hash(value)


def copy_asset(source, destination, digest):
    if sha256_file(source) != digest:
        raise ReviewError("figure_source_hash_mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as inp, destination.open("xb") as out:
        shutil.copyfileobj(inp, out)
    if sha256_file(destination) != digest:
        raise ReviewError("figure_asset_hash_mismatch")


class QuestionImportConfirmationService(QuestionImportPlanner):
    def confirm(
        self,
        review_id,
        expected_revision,
        expected_revision_sha256,
        import_plan_sha256,
        mode="append",
    ):
        try:
            return self._confirm(
                review_id, expected_revision, expected_revision_sha256, import_plan_sha256, mode
            )
        except Exception:
            self.s.rollback()
            raise

    def _confirm(
        self, review_id, expected_revision, expected_revision_sha256, import_plan_sha256, mode
    ):
        if mode != "append":
            raise ReviewError("import_mode_required")
        # Serialize Review saves/confirmations, and appends to the same Test.
        svc = QuestionReviewService(self.s, self.root)
        review = svc._review(review_id, lock=True)
        draft, store, dv, ir = svc._draft(review.draft_id)
        extraction = self.s.get(QuestionImportExtraction, draft.extraction_id)
        self.s.scalar(select(Test).where(Test.id == extraction.test_id).with_for_update())
        prior = self.s.scalar(
            select(QuestionImportConfirmation).where(
                QuestionImportConfirmation.review_id == review_id
            )
        )
        if prior:
            if (
                prior.review_revision_number,
                prior.review_revision_sha256,
                prior.import_plan_sha256,
            ) != (expected_revision, expected_revision_sha256, import_plan_sha256):
                raise ReviewError("already_imported")
            result = self.get_confirmation(prior.id)
            self.s.commit()
            return result
        plan = self.plan(review_id)
        if (plan["revision"], plan["revision_sha256"]) != (
            expected_revision,
            expected_revision_sha256,
        ):
            raise ReviewError("stale_revision")
        if plan["plan_sha256"] != import_plan_sha256:
            raise ReviewError("stale_import_plan")
        if plan["blockers"]:
            raise ReviewError("import_blocked")
        rev = svc._revision(review, store)
        cid = str(uuid4())
        created = datetime.now(timezone.utc)
        base = store.path(f"confirmations/{cid}")
        base.mkdir(parents=True, exist_ok=False)
        # A directory without a corresponding committed DB record is an orphan.
        write_artifact(
            base / "transaction.json",
            {
                "confirmation_id": cid,
                "commit_authority": "question_import_confirmations",
                "cleanup": "manual",
            },
        )
        confirmation = QuestionImportConfirmation(
            id=cid,
            test_id=extraction.test_id,
            review_id=review_id,
            review_revision_number=expected_revision,
            review_revision_sha256=expected_revision_sha256,
            source_draft_sha256=plan["source_draft_sha256"],
            import_plan_sha256=import_plan_sha256,
            import_schema_version=SCHEMA,
            state="completed",
            artifact_ref=f"confirmations/{cid}",
            created_at=created,
            completed_at=created,
        )
        self.s.add(confirmation)
        self.s.flush()
        rows, mappings, assets = {}, [], []
        pins = {p["region_id"]: p for p in rev.snapshot["vision_pin"].get("results", [])}
        regions = {r["region_id"]: r for r in dv.get("figure_regions", [])}
        for p in plan["nodes"]:
            content = deepcopy(p["content"])
            q = TestQuestion(
                id=str(uuid4()),
                test_id=plan["test_id"],
                question_number=p["question_number"],
                title=p["display_label"],
                question_text=p["question_text"],
                max_points=p["max_points"],
                sort_order=p["sort_order"],
                parent_id=rows[p["parent_key"]].id if p["parent_key"] else None,
                stable_question_key=p["stable_question_key"],
                display_label=p["display_label"],
                node_type=p["node_type"],
                is_gradable=p["is_gradable"],
                provenance={
                    "origin": "review_import",
                    "confirmation_id": cid,
                    "review_id": review_id,
                    "revision": expected_revision,
                    "revision_sha256": expected_revision_sha256,
                    "review_node_id": p["review_node_id"],
                    "math_ocr_edits": deepcopy(next((n.get('math_ocr_edits', []) for n in rev.snapshot['nodes']
                        if n['review_node_id'] == p['review_node_id']), [])),
                },
            )
            self.s.add(q)
            self.s.flush()
            rows[p["review_key"]] = q
            for item in content["items"]:
                if item["type"] != "figure":
                    continue
                rid = item["source_region_id"]
                if item.get('diagram'):
                    record = item['diagram']
                    source = svc._artifact(store, record['artifact_ref'], record['crop_sha256'], 'diagrams/')
                    aid = str(uuid4())
                    ref = f'confirmations/{cid}/assets/{aid}.png'
                    copy_asset(source, store.path(ref), record['crop_sha256'])
                    provenance = {**record, 'confirmation_id': cid, 'extraction_id': draft.extraction_id,
                        'review_id': review_id, 'revision': expected_revision,
                        'revision_sha256': expected_revision_sha256, 'domain': 'question'}
                    asset = TestQuestionAsset(id=aid, question_id=q.id, asset_type='figure',
                        artifact_ref=ref, sha256=record['crop_sha256'], mime_type='image/png', provenance=provenance)
                    self.s.add(asset)
                    assets.append({'id': aid, 'question_id': q.id, 'artifact_ref': ref,
                                   'sha256': asset.sha256, 'provenance': provenance})
                    item['asset_id'] = aid
                    continue
                pin = pins[rid]
                source = svc._artifact(
                    store,
                    pin["crop_ref"],
                    pin["crop_sha256"],
                    evidence_prefix(rev.snapshot["vision_pin"]),
                )
                aid = str(uuid4())
                ref = f"confirmations/{cid}/assets/{aid}.png"
                copy_asset(source, store.path(ref), pin["crop_sha256"])
                region = regions[rid]
                provenance = {
                    "confirmation_id": cid,
                    "extraction_id": draft.extraction_id,
                    "review_id": review_id,
                    "revision": expected_revision,
                    "revision_sha256": expected_revision_sha256,
                    "region_id": rid,
                    "vision_run_id": rev.snapshot["vision_pin"]["run_id"],
                    "vision_result_id": pin["result_id"],
                    "source_crop_ref": pin["crop_ref"],
                    "source_crop_sha256": pin["crop_sha256"],
                    "source_pdf_sha256": ir["source"]["sha256"],
                    "page_index": region.get("page_index"),
                    "bbox": region.get("bbox"),
                    "coordinate_space": region.get("coordinate_space", "pdf_point"),
                    "semantic_role": region.get("semantic_role"),
                    "evidence_source": pin.get("evidence_source", "model_vision"),
                    "crop_metadata": pin.get("crop"),
                }
                asset = TestQuestionAsset(
                    id=aid,
                    question_id=q.id,
                    asset_type="figure",
                    artifact_ref=ref,
                    sha256=pin["crop_sha256"],
                    mime_type="image/png",
                    provenance=provenance,
                )
                self.s.add(asset)
                assets.append(
                    {
                        "id": aid,
                        "question_id": q.id,
                        "artifact_ref": ref,
                        "sha256": asset.sha256,
                        "provenance": provenance,
                    }
                )
                item["asset_id"] = aid
            q.content = content
            q.content_sha256 = canonical_hash(content)
            entry = {
                **{
                    k: deepcopy(p[k])
                    for k in (
                        "review_node_id",
                        "source_draft_stable_key",
                        "stable_question_key",
                        "parent_key",
                        "display_label",
                        "node_type",
                        "is_gradable",
                        "sort_order",
                    )
                },
                "test_question_id": q.id,
                "parent_id": q.parent_id,
                "content_sha256": q.content_sha256,
                "excluded": False,
            }
            mappings.append(entry)
            self.s.add(
                QuestionImportConfirmationItem(
                    confirmation_id=cid,
                    review_node_id=p["review_node_id"],
                    source_draft_stable_key=p["source_draft_stable_key"],
                    test_question_id=q.id,
                    stable_question_key=q.stable_question_key,
                    imported_order=len(mappings) - 1,
                    excluded=False,
                )
            )
        for n in rev.snapshot["nodes"]:
            if n["included"]:
                continue
            mappings.append(
                {
                    "review_node_id": n["review_node_id"],
                    "source_draft_stable_key": n["source_draft_stable_key"],
                    "test_question_id": None,
                    "excluded": True,
                }
            )
            self.s.add(
                QuestionImportConfirmationItem(
                    confirmation_id=cid,
                    review_node_id=n["review_node_id"],
                    source_draft_stable_key=n["source_draft_stable_key"],
                    test_question_id=None,
                    stable_question_key=None,
                    imported_order=len(mappings) - 1,
                    excluded=True,
                )
            )
        plan_file_hash = write_artifact(base / "import-plan.json", plan)
        mapping_hash = write_artifact(base / "mapping.json", mappings)
        manifest = {
            "confirmation_id": cid,
            "test_id": plan["test_id"],
            "source_pdf_sha256": ir["source"]["sha256"],
            "source_ir_sha256": canonical_hash(ir),
            "source_draft_sha256": draft.draft_sha256,
            "draft_id": draft.id,
            "extraction_id": draft.extraction_id,
            "review_id": review_id,
            "review_revision": expected_revision,
            "review_revision_sha256": expected_revision_sha256,
            "vision_pin": rev.snapshot["vision_pin"],
            "import_schema_version": SCHEMA,
            "import_plan_sha256": import_plan_sha256,
            "artifact_hashes": {"import-plan.json": plan_file_hash, "mapping.json": mapping_hash},
            "test_question_content_hashes": {q.id: q.content_sha256 for q in rows.values()},
            "assets": assets,
            "created_at": created.isoformat(),
        }
        digest = write_artifact(base / "manifest.json", manifest)
        # Hash-addressed manifest anchors integrity in the existing DB ref column.
        write_artifact(base / f"manifest-{digest}.json", manifest)
        confirmation.artifact_ref = f"confirmations/{cid}/manifest-{digest}.json"
        self.s.flush()
        result = self.get_confirmation(cid)
        self.s.commit()
        return result

    def get_confirmation(self, cid):
        c = self.s.get(QuestionImportConfirmation, cid)
        if not c:
            raise ReviewError("confirmation_not_found", 404)
        review = self.s.get(QuestionImportReview, c.review_id)
        from .db.models import QuestionImportDraft

        draft = self.s.get(QuestionImportDraft, review.draft_id)
        from .adapters.artifacts import RunArtifactAdapter

        store = RunArtifactAdapter(self.root / draft.extraction_id)
        try:
            digest = Path(c.artifact_ref).stem.removeprefix("manifest-")
            path = QuestionReviewService._artifact(
                store, c.artifact_ref, digest, f"confirmations/{cid}/"
            )
            manifest = json.loads(path.read_text())
            base = path.parent
            if sha256_file(base / "manifest.json") != digest:
                raise ValueError()
            for name, expected in manifest["artifact_hashes"].items():
                if (
                    name not in {"import-plan.json", "mapping.json"}
                    or sha256_file(base / name) != expected
                ):
                    raise ValueError()
            plan = json.loads((base / "import-plan.json").read_text())
            mapping = json.loads((base / "mapping.json").read_text())
            if (
                canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
                != c.import_plan_sha256
            ):
                raise ValueError()
            if (
                manifest["confirmation_id"],
                manifest["review_revision_sha256"],
                manifest["import_plan_sha256"],
                manifest["test_id"],
            ) != (c.id, c.review_revision_sha256, c.import_plan_sha256, c.test_id):
                raise ValueError()
            items = list(
                self.s.scalars(
                    select(QuestionImportConfirmationItem)
                    .where(QuestionImportConfirmationItem.confirmation_id == cid)
                    .order_by(QuestionImportConfirmationItem.imported_order)
                )
            )
            if len(items) != len(mapping):
                raise ValueError()
            for db_item, entry in zip(items, mapping):
                if (db_item.review_node_id, db_item.test_question_id, db_item.excluded) != (
                    entry["review_node_id"],
                    entry["test_question_id"],
                    entry["excluded"],
                ):
                    raise ValueError()
                if db_item.excluded:
                    continue
                q = self.s.get(TestQuestion, db_item.test_question_id)
                if (
                    not q
                    or canonical_hash(q.content) != entry["content_sha256"]
                    or q.content_sha256 != entry["content_sha256"]
                    or q.parent_id != entry["parent_id"]
                    or q.test_id != c.test_id
                ):
                    raise ValueError()
            for a in manifest["assets"]:
                db_asset = self.s.get(TestQuestionAsset, a["id"])
                if not db_asset or (
                    db_asset.sha256,
                    db_asset.artifact_ref,
                    db_asset.question_id,
                ) != (a["sha256"], a["artifact_ref"], a["question_id"]):
                    raise ValueError()
                QuestionReviewService._artifact(
                    store, a["artifact_ref"], a["sha256"], f"confirmations/{cid}/assets/"
                )
        except (ValueError, OSError, KeyError, TypeError, ReviewError):
            raise ReviewError("confirmation_artifact_integrity_error") from None
        return {
            "id": c.id,
            "test_id": c.test_id,
            "review_id": c.review_id,
            "revision": c.review_revision_number,
            "revision_sha256": c.review_revision_sha256,
            "plan_sha256": c.import_plan_sha256,
            "state": c.state,
            "items": mapping,
            "structural_count": plan["structural_count"],
            "gradable_count": plan["gradable_count"],
            "total_points": plan["total_points"],
            "score_ready": plan["score_ready"],
            "assets": [
                {k: a[k] for k in ("id", "question_id", "sha256")} for a in manifest["assets"]
            ],
        }
