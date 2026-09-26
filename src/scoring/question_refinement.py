"""Append-only, explicitly approved question draft refinement; never confirmation.

Preserves the automatic draft as evidence. Teacher crop observations are labelled
as such, not fabricated model responses. Existing Review/Confirm remains required.
"""
from copy import deepcopy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .coordinate import validate_bbox
from .pdf_native import canonical_hash, sha256_file
from .question_drafts import QuestionDraftService, DraftError
from .review_document import initial_snapshot, validate_snapshot


def prepare_refinement(session, root, source_draft_id, *, approved_draft, evidence, approval):
    if not isinstance(approval, str) or not approval.strip():
        raise DraftError("teacher_approval_required", 422)
    svc = QuestionDraftService(session, root)
    base = svc.get(source_draft_id)
    store = svc._store(base["extraction_id"])
    source = json.loads(store.path(f"structured/{source_draft_id}/question-draft.json").read_text())
    if canonical_hash(source) != base["draft_sha256"]:
        raise DraftError("draft_integrity_error")
    proposed = deepcopy(approved_draft)
    for field in ("source_ir_sha256", "schema_version", "coordinate_space", "document_context"):
        if proposed.get(field) != source.get(field):
            raise DraftError("refinement_source_changed", 422)
    ids = {n["stable_key"] for n in proposed["nodes"]}
    region_by_id = {}
    for kind in ("formula", "figure"):
        for region in proposed[f"{kind}_regions"]:
            if region.get("region_type", kind) != kind:
                raise DraftError("invalid_refinement_region_type", 422)
            region["region_type"] = kind
            rid = region["region_id"]
            if rid in region_by_id or region["assigned_question_key"] not in ids:
                raise DraftError("invalid_refinement_owner", 422)
            validate_bbox(region["bbox"], region.get("coordinate_space", "pdf_point"))
            region_by_id[rid] = region
            anchors = [n["stable_key"] for n in proposed["nodes"] for it in n["ordered_content"]
                       if it.get("region_id") == rid and it["type"] == f"{kind}_region"]
            if anchors != [region["assigned_question_key"]]:
                raise DraftError("invalid_refinement_anchor", 422)
    identity = {"draft": proposed, "approval": approval, "source_draft": source_draft_id,
                "evidence": [{k: v for k, v in e.items() if not k.endswith("_path")} for e in evidence]}
    eid = str(uuid5(NAMESPACE_URL, canonical_hash(identity)))
    pin = {"run_id": None, "evidence_id": eid, "evidence_source": "teacher_review_evidence", "results": []}
    source_pdf_sha = sha256_file(store.path("source.pdf"))
    for item in evidence:
        rid = item["region_id"]
        region = region_by_id[rid]
        if item["crop"]["source_pdf_sha256"] != source_pdf_sha:
            raise DraftError("refinement_crop_source_mismatch", 422)
        refs = {}
        for name in ("crop", "raw", "view"):
            path = Path(item[f"{name}_path"])
            if sha256_file(path) != item[f"{name}_sha256"]:
                raise DraftError("refinement_evidence_hash_mismatch")
            ref = f"review-evidence/{eid}/{rid}/{name}{'.png' if name == 'crop' else '.json'}"
            dst = store.path(ref)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                if sha256_file(dst) != item[f"{name}_sha256"]:
                    raise DraftError("refinement_evidence_hash_mismatch")
            else:
                with dst.open("xb") as stream:
                    stream.write(path.read_bytes())
            refs.update({f"{name}_ref": ref, f"{name}_sha256": item[f"{name}_sha256"]})
        pin["results"].append({**refs, "region_id": rid, "region_type": region["region_type"],
            "question_stable_key": region["assigned_question_key"], "result_id": None,
            "evidence_source": item["evidence_source"], "crop": deepcopy(item["crop"]),
            "has_candidate": False, "review_flags": item.get("review_flags", []),
            "normalized_sha256": refs["view_sha256"], "model": item.get("model"),
            "prompt": item.get("prompt")})
    proposed["review_evidence"] = pin
    proposed["refinement_provenance"] = {"source_draft_id": source_draft_id,
        "source_draft_sha256": base["draft_sha256"], "approval": approval,
        "original_regions": {k: source[k] for k in ("formula_regions", "figure_regions")}}
    snap = initial_snapshot(base["draft_sha256"], proposed, pin)
    validate_snapshot(snap, snap, proposed, pin)

    class ApprovedParser:
        name = "teacher-approved-question-refinement"
        version = "teacher-approved-refinement.v1"
        config_hash = canonical_hash(proposed)

        def build(self, ir):
            if canonical_hash(ir) != source["source_ir_sha256"]:
                raise DraftError("refinement_ir_mismatch")
            proposed["parser"] = {"name": self.name, "version": self.version, "config_hash": self.config_hash}
            return {"source_ir_sha256": source["source_ir_sha256"], "source_draft_id": source_draft_id}, proposed

    svc.parser = ApprovedParser()
    return svc.generate(base["extraction_id"])
