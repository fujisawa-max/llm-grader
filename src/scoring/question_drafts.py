"""Draft persistence and validated artifact boundary, separate from grading."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .adapters.artifacts import RunArtifactAdapter
from .db.models import QuestionImportExtraction, QuestionImportDraft, QuestionImportDraftNode
from .pdf_native import canonical_hash, sha256_file
from .question_structure import QuestionStructureParser, PARSER_VERSION, DRAFT_SCHEMA


class DraftError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


class QuestionDraftService:
    def __init__(self, session, root):
        self.session = session
        self.root = Path(root).resolve()
        self.parser = QuestionStructureParser()

    def _store(self, extraction_id):
        try:
            UUID(extraction_id)
        except ValueError:
            raise DraftError("invalid_extraction_id", 422) from None
        try:
            base = RunArtifactAdapter(self.root).path(extraction_id)
        except ValueError:
            raise DraftError("unsafe_artifact_reference") from None
        return RunArtifactAdapter(base)

    def _source(self, extraction):
        if extraction.state != "completed":
            raise DraftError("extraction_not_completed")
        store = self._store(extraction.id)
        try:
            ir_path = store.path("native/document-ir.json")
            ir = json.loads(ir_path.read_text())
            manifest = json.loads(store.path("native/manifest.json").read_text())
            if (sha256_file(ir_path) != manifest["ir_sha256"] or canonical_hash(ir) != manifest["ir_sha256"]
                    or ir["source"]["sha256"] != extraction.source_sha256
                    or ir["source"]["material_id"] != extraction.material_id
                    or ir["parser"]["config_hash"] != extraction.extraction_config_hash
                    or ir["schema_version"] != extraction.schema_version
                    or ir["parser"]["version"] != extraction.parser_version
                    or ir["parser"]["backend"] != extraction.parser_backend
                    or ir["parser"]["library"] != extraction.parser_library
                    or canonical_hash(ir["parser"]["config"]) != extraction.extraction_config_hash
                    or manifest["schema_version"] != ir["schema_version"]
                    or manifest["source"] != ir["source"] or manifest["parser"] != ir["parser"]):
                raise DraftError("source_ir_integrity_error")
            return store, ir
        except (OSError, ValueError, KeyError, TypeError):
            raise DraftError("source_ir_integrity_error") from None

    def generate(self, extraction_id):
        extraction = self.session.get(QuestionImportExtraction, extraction_id)
        if not extraction:
            raise DraftError("extraction_not_found", 404)
        store, ir = self._source(extraction)
        source_hash = canonical_hash(ir)
        query = select(QuestionImportDraft).where(QuestionImportDraft.extraction_id == extraction_id,
            QuestionImportDraft.source_ir_sha256 == source_hash, QuestionImportDraft.parser_version == getattr(self.parser, "version", PARSER_VERSION),
            QuestionImportDraft.parser_config_hash == self.parser.config_hash)
        existing = self.session.scalar(query)
        if existing:
            if existing.state != "completed":
                raise DraftError("draft_not_completed")
            return self.get(existing.id)
        draft_id = str(uuid4())
        relative = f"structured/{draft_id}"
        record = QuestionImportDraft(id=draft_id, extraction_id=extraction_id, state="generating", schema_version=DRAFT_SCHEMA,
            parser_name=getattr(self.parser, "name", "native-question-structure"), parser_version=getattr(self.parser, "version", PARSER_VERSION), parser_config_hash=self.parser.config_hash,
            source_ir_sha256=source_hash, artifact_ref=f"question-imports/{extraction_id}/{relative}")
        self.session.add(record)
        try:
            self.session.flush()  # Unique input constraint serializes concurrent generation.
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(query)
            if existing and existing.state == "completed":
                return self.get(existing.id)
            raise DraftError("draft_generation_conflict") from None
        try:
            layout, draft = self.parser.build(ir)
            record.draft_sha256 = canonical_hash(draft)
            record.review_required = draft["review_required"]
            record.total_points_candidate = draft["total_points_candidate"]
            parents = {}
            for n in draft["nodes"]:
                node_id = str(uuid4())
                self.session.add(QuestionImportDraftNode(id=node_id, draft_id=draft_id,
                    parent_id=parents.get(n["parent_key"]), stable_key=n["stable_key"], node_type=n["node_type"],
                    depth=n["depth"], sort_order=n["sort_order"], label_raw=n["label"]["raw"], label_normalized=n["label"]["normalized"],
                    body_text=n["body_text"], score_semantics=n["score"]["semantics"], score_points=n["score"]["points"],
                    effective_points_candidate=n["score"]["effective_points_candidate"], aggregate_points_candidate=n["score"]["aggregate_points_candidate"],
                    evidence={"source_regions": n["source_regions"], "score": n["score"], "formula_regions": n["formula_regions"], "figure_regions": n["figure_regions"],
                             "ordered_content": n["ordered_content"]},
                    review_required=n["review_required"], review_flags=n["review_flags"]))
                self.session.flush()
                parents[n["stable_key"]] = node_id
            values = {"layout-projection.json": layout, "question-draft.json": draft,
                      "diagnostics.json": {"review_flags": draft["review_flags"], "unassigned_content": draft["unassigned_content"]},
                      "manifest.json": {"source_pdf_sha256": ir["source"]["sha256"], "source_ir_sha256": source_hash,
                        "source_ir_schema_version": ir["schema_version"], "native_parser": ir["parser"], "structure_parser": draft["parser"],
                        "draft_schema_version": DRAFT_SCHEMA, "coordinate_space": draft["coordinate_space"],
                        "layout_projection_sha256": canonical_hash(layout),
                        "draft_sha256": record.draft_sha256, "created_at": datetime.now(timezone.utc).isoformat()}}
            for name, value in values.items():
                path = store.path(f"{relative}/{name}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            record.state = "completed"
            self.session.commit()
        except Exception:
            self.session.rollback()
            # No partial nodes are published. Failed lifecycle record retains a
            # safe error code; private traceback is not exposed through the API.
            self.session.add(QuestionImportDraft(id=draft_id, extraction_id=extraction_id, state="failed", schema_version=DRAFT_SCHEMA,
                parser_name=getattr(self.parser, "name", "native-question-structure"), parser_version=getattr(self.parser, "version", PARSER_VERSION), parser_config_hash=self.parser.config_hash,
                source_ir_sha256=source_hash, artifact_ref=f"question-imports/{extraction_id}/{relative}",
                error_code="draft_generation_failed", error_message="問題構造の解析に失敗しました"))
            self.session.commit()
            raise DraftError("draft_generation_failed") from None
        return self.get(draft_id)

    def latest(self, extraction_id):
        if not self.session.get(QuestionImportExtraction, extraction_id):
            raise DraftError("extraction_not_found", 404)
        record = self.session.scalar(select(QuestionImportDraft).where(QuestionImportDraft.extraction_id == extraction_id)
                                     .order_by(QuestionImportDraft.created_at.desc(), QuestionImportDraft.id))
        if not record:
            raise DraftError("draft_not_found", 404)
        return self.get(record.id)

    def get(self, draft_id):
        record = self.session.get(QuestionImportDraft, draft_id)
        if not record:
            raise DraftError("draft_not_found", 404)
        result = {k: getattr(record, k) for k in ("id", "extraction_id", "state", "schema_version", "parser_name", "parser_version",
                  "parser_config_hash", "source_ir_sha256", "draft_sha256", "review_required", "total_points_candidate", "created_at", "updated_at", "error_code", "error_message")}
        if record.state != "completed":
            return result
        try:
            UUID(record.id)
            store = self._store(record.extraction_id)
            path = store.path(f"structured/{record.id}/question-draft.json")
            draft = json.loads(path.read_text())
            if canonical_hash(draft) != record.draft_sha256:
                raise DraftError("draft_integrity_error")
        except (OSError, ValueError, KeyError):
            raise DraftError("draft_integrity_error") from None
        result.update(coordinate_space=draft.get("coordinate_space", {}), nodes=draft["nodes"], review_flags=draft["review_flags"],
                      formula_regions=[{**{k: r.get(k) for k in ("region_id", "page_index", "bbox", "source_element_ids", "assigned_question_key", "review_flags", "routing_evidence")},
                                        "coordinate_space": r.get("coordinate_space", "pdf_point"), "reference_plane": r.get("reference_plane")} for r in draft["formula_regions"]],
                      figure_regions=[{**{k: r[k] for k in ("region_id", "page_index", "bbox", "source_element_ids", "assigned_question_key", "review_flags")},
                                       "coordinate_space": r.get("coordinate_space", "pdf_point"), "reference_plane": r.get("reference_plane")} for r in draft["figure_regions"]],
                      unassigned_content_count=len(draft["unassigned_content"]))
        return result
