"""Persisted selective vision service, independent of grading jobs/workers."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import time
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .adapters.artifacts import RunArtifactAdapter
from .adapters.pdf_region import PyMuPdfRegionRenderer
from .adapters.question_vision import prompt_metadata
from .db.models import QuestionImportDraft, QuestionImportExtraction, QuestionImportVisionRun, QuestionImportVisionResult
from .pdf_native import canonical_hash, sha256_file
from .question_drafts import QuestionDraftService, DraftError
from .vision_policy import VisionRoutingPolicy, POLICY_VERSION, OVERLAY_SCHEMA
from .vision_output import parse_output


class VisionError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


class VisionFallbackService:
    def __init__(self, session, root, *, inference=None, renderer=None, policy=None):
        self.session, self.root = session, Path(root).resolve()
        self.inference = inference
        self.renderer = renderer or PyMuPdfRegionRenderer()
        self.policy = policy or VisionRoutingPolicy()

    def source(self, draft_id):
        try:
            UUID(draft_id)
            record = self.session.get(QuestionImportDraft, draft_id)
            if not record:
                raise VisionError("draft_not_found", 404)
            if record.state != "completed":
                raise VisionError("draft_not_completed")
            service = QuestionDraftService(self.session, self.root)
            extraction = self.session.get(QuestionImportExtraction, record.extraction_id)
            store, ir = service._source(extraction)
            path = store.path(f"structured/{record.id}/question-draft.json")
            draft = json.loads(path.read_text())
            if (canonical_hash(draft) != record.draft_sha256 or sha256_file(path) != record.draft_sha256
                    or canonical_hash(ir) != record.source_ir_sha256 or draft["source_ir_sha256"] != record.source_ir_sha256):
                raise VisionError("source_hash_mismatch")
            pdf = store.path("source.pdf")
            if sha256_file(pdf) != extraction.source_sha256:
                raise VisionError("source_hash_mismatch")
            # Legacy H.2-A/B.1 backend produced crop-local coordinates despite
            # its mediabox label. Only that verified legacy backend is accepted.
            if ir["parser"].get("backend") != "pymupdf":
                raise VisionError("unsupported_native_coordinate_contract")
            return record, store, draft, ir, pdf
        except VisionError:
            raise
        except (DraftError, OSError, KeyError, ValueError, TypeError):
            raise VisionError("source_integrity_error") from None

    def plan(self, draft_id):
        _, _, draft, ir, _ = self.source(draft_id)
        try:
            return {"draft_id": draft_id, **self.policy.build(draft, ir)}
        except (ValueError, KeyError, TypeError):
            raise VisionError("invalid_region_evidence") from None

    def create(self, draft_id):
        plan = self.plan(draft_id)
        roles = {r["model_role"] for r in plan["routes"] if r["model_role"]}
        try:
            if roles and self.inference is None:
                raise VisionError("vision_runtime_not_configured", 503)
            models = self.inference.metadata(roles) if roles else {}
        except VisionError:
            raise
        except Exception:
            raise VisionError("missing_model_asset", 422) from None
        # Retain H.2-C's identity marker so parser updates do not create new
        # inference runs. Actual parser versions/hashes live on derived views.
        snapshot = {"plan": plan, "models": models, "prompts": prompt_metadata(),
                    "normalization_version": "conservative-vision-v1", "overlay_schema": OVERLAY_SCHEMA}
        input_hash = canonical_hash(snapshot)
        existing = self.session.scalar(select(QuestionImportVisionRun).where(
            QuestionImportVisionRun.draft_id == draft_id, QuestionImportVisionRun.input_sha256 == input_hash))
        if existing:
            return self.get(existing.id)
        run_id = str(uuid4())
        record, store, _, _, _ = self.source(draft_id)
        relative = f"vision/{run_id}"
        run = QuestionImportVisionRun(id=run_id, draft_id=draft_id, input_sha256=input_hash, state="planned",
            policy_version=POLICY_VERSION, policy_config_hash=self.policy.config_hash, schema_version=OVERLAY_SCHEMA,
            artifact_ref=f"question-imports/{record.extraction_id}/{relative}", snapshot=snapshot)
        self.session.add(run)
        try:
            self.session.flush()
            for route in plan["routes"]:
                self.session.add(QuestionImportVisionResult(run_id=run_id, region_id=route["region_id"],
                    question_stable_key=route["assigned_question_key"], region_type=route["region_type"],
                    model_role=route["model_role"], routing_decision=route["decision"],
                    state="skipped_native" if route["decision"] == "NATIVE_SUFFICIENT" else
                          "review_required" if route["decision"] == "AMBIGUOUS" else "planned",
                    evidence={"route": route}))
            write_json(store.path(f"{relative}/routing-plan.json"), plan)
            write_json(store.path(f"{relative}/manifest.json"), {**snapshot, "input_sha256": input_hash,
                       "created_at": datetime.now(timezone.utc).isoformat()})
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise VisionError("vision_run_creation_conflict") from None
        return self.get(run_id)

    def _run(self, run_id):
        try:
            UUID(run_id)
        except ValueError:
            raise VisionError("invalid_run_id", 422) from None
        run = self.session.get(QuestionImportVisionRun, run_id)
        if not run:
            raise VisionError("vision_run_not_found", 404)
        if canonical_hash(run.snapshot) != run.input_sha256:
            raise VisionError("vision_snapshot_integrity_error")
        return run

    def results(self, run_id):
        self._run(run_id)
        rows = self.session.scalars(select(QuestionImportVisionResult).where(
            QuestionImportVisionResult.run_id == run_id).order_by(QuestionImportVisionResult.region_id)).all()
        return [{k: getattr(r, k) for k in ("region_id", "question_stable_key", "region_type", "model_role",
                "routing_decision", "state", "attempts", "evidence", "error_code")} for r in rows]

    def get(self, run_id):
        r = self._run(run_id)
        return {k: getattr(r, k) for k in ("id", "draft_id", "state", "policy_version", "policy_config_hash",
                "schema_version", "artifact_ref", "input_sha256", "created_at", "updated_at", "error_code")}

    @contextmanager
    def _execution_lock(self):
        # All H.2-C calls sharing this store serialize, including API workers.
        # A process crash releases flock; resume can then reclaim running rows.
        path = RunArtifactAdapter(self.root).path("vision-execution.lock")
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise VisionError("vision_execution_busy") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def execute(self, run_id, *, region_ids=None):
        with self._execution_lock():
            return self._execute(run_id, region_ids)

    def reparse(self, run_id):
        """Add versioned parsed views; never render, infer, or replace old evidence.

        The inference input hash/snapshot and original normalized references
        remain unchanged. Parser identity belongs to each derived view.
        """
        with self._execution_lock():
            run = self._run(run_id)
            _, store, _, _, _ = self.source(run.draft_id)
            try:
                manifest = json.loads(store.path(f"vision/{run.id}/manifest.json").read_text())
                plan = json.loads(store.path(f"vision/{run.id}/routing-plan.json").read_text())
                if (canonical_hash({k: manifest[k] for k in run.snapshot}) != run.input_sha256
                        or plan != run.snapshot["plan"]):
                    raise VisionError("vision_snapshot_integrity_error")
            except (OSError, KeyError, ValueError, TypeError):
                raise VisionError("vision_snapshot_integrity_error") from None
            rows = self.session.scalars(select(QuestionImportVisionResult).where(
                QuestionImportVisionResult.run_id == run_id).order_by(QuestionImportVisionResult.region_id)).all()
            prepared = []
            for row in rows:
                if row.state != "completed":
                    continue
                evidence = row.evidence
                try:
                    for kind in ("raw", "crop", "normalized"):
                        if sha256_file(store.path(evidence[f"{kind}_ref"])) != evidence[f"{kind}_sha256"]:
                            raise VisionError("vision_result_integrity_error")
                    raw = json.loads(store.path(evidence["raw_ref"]).read_text())
                    view = parse_output(raw, row.model_role, evidence["route"]["native_fragments"],
                        source_raw_sha256=evidence["raw_sha256"], region_id=row.region_id,
                        inherited_flags=[f for f in evidence["normalized_result"].get("review_flags", [])
                                         if f in {"crop_clipped", "native_vision_disagreement"}])
                    ref = (f"vision/{run.id}/parsed/{row.region_id}/"
                           f"{view['parser_version']}/{view['normalized_sha256']}.json")
                    path = store.path(ref)
                    if path.exists() and sha256_file(path) != canonical_hash(view):
                        raise VisionError("parsed_view_integrity_error")
                    prepared.append((row, view, ref))
                except (OSError, KeyError, ValueError, TypeError):
                    raise VisionError("vision_result_integrity_error") from None
            for row, view, ref in prepared:
                path = store.path(ref)
                if not path.exists():
                    write_json(path, view)
                entry = {"artifact_ref": ref, "artifact_sha256": sha256_file(path), "result": view}
                history = dict(row.evidence.get("parsed_views", {}))
                history[view["normalized_sha256"]] = entry
                row.evidence = {**row.evidence, "parsed_views": history, "parsed_view": entry}
            self.session.commit()
            self._overlay(run, store, f"vision/{run.id}", None)
            return self.results(run_id)

    def _execute(self, run_id, region_ids):
        run = self._run(run_id)
        record, store, draft, ir, pdf = self.source(run.draft_id)
        plan = run.snapshot["plan"]
        if (plan["source_draft_sha256"] != canonical_hash(draft)
                or plan["source_ir_sha256"] != canonical_hash(ir)):
            raise VisionError("source_hash_mismatch")
        rows = self.session.scalars(select(QuestionImportVisionResult).where(
            QuestionImportVisionResult.run_id == run_id).order_by(QuestionImportVisionResult.region_id)).all()
        if region_ids is not None and not set(region_ids).issubset({r.region_id for r in rows}):
            raise VisionError("unknown_region", 422)
        relative = f"vision/{run.id}"
        try:
            saved_plan = json.loads(store.path(f"{relative}/routing-plan.json").read_text())
            manifest = json.loads(store.path(f"{relative}/manifest.json").read_text())
            saved_snapshot = {key: manifest[key] for key in run.snapshot}
            if canonical_hash(saved_snapshot) != run.input_sha256 or saved_plan != plan:
                raise VisionError("vision_snapshot_integrity_error")
        except (OSError, KeyError, ValueError, TypeError):
            raise VisionError("vision_snapshot_integrity_error") from None
        # Never repeat successful inference silently when artifacts changed.
        for row in rows:
            if row.state == "completed":
                for name in ("crop", "raw", "normalized"):
                    try:
                        if sha256_file(store.path(row.evidence[f"{name}_ref"])) != row.evidence[f"{name}_sha256"]:
                            raise VisionError("vision_result_integrity_error")
                    except (OSError, KeyError, ValueError):
                        raise VisionError("vision_result_integrity_error") from None
        pending = [r for r in rows if r.model_role and r.state != "completed" and
                   (region_ids is None or r.region_id in region_ids)]
        roles = {r.model_role for r in pending}
        if roles:
            if self.inference is None:
                raise VisionError("vision_runtime_not_configured", 503)
            try:
                actual = self.inference.metadata(roles)
                if any(actual[role] != run.snapshot["models"][role] for role in roles):
                    raise VisionError("model_configuration_changed")
            except VisionError:
                raise
            except Exception:
                run.state, run.error_code = "failed", "missing_model_asset"
                self.session.commit()
                raise VisionError("missing_model_asset", 422) from None
        run.state, run.error_code = "running", None
        self.session.commit()
        start = time.monotonic()
        for role in ("math_ocr", "ocr"):
            group = [r for r in pending if r.model_role == role]
            if not group:
                continue
            try:
                with self.inference.acquire(role, run.snapshot["models"][role]) as adapter:
                    for row in group:
                        route = next(r for r in plan["routes"] if r["region_id"] == row.region_id)
                        row.attempts += 1
                        row.state, row.error_code = "planned", None
                        self.session.commit()
                        attempt = f"{relative}/attempts/{row.region_id}-{row.attempts:04d}"
                        phase = "crop_render_failed"
                        evidence = {"route": route, "model": run.snapshot["models"][role],
                                    "prompt": run.snapshot["prompts"][role], "draft_id": run.draft_id,
                                    "runtime": getattr(adapter, "runtime_observation", {})}
                        try:
                            page = next(p for p in ir["pages"] if p["page_index"] == route["page_index"])
                            crop_ref = f"{attempt}/crop.png"
                            crop = self.renderer.render(pdf, page, route, plan["config"], store.path(crop_ref))
                            evidence.update(crop=crop, crop_ref=crop_ref, crop_sha256=crop["sha256"])
                            row.state, row.evidence, row.error_code = "rendered", evidence, None
                            self.session.commit()
                            row.state = "running"
                            self.session.commit()
                            phase = "inference_failed"
                            tick = time.monotonic()
                            raw = adapter.infer(role, store.path(crop_ref))
                            evidence["inference_seconds"] = time.monotonic()-tick
                            raw_ref = f"{attempt}/raw.json"
                            write_json(store.path(raw_ref), raw)
                            evidence.update(raw_ref=raw_ref, raw_sha256=sha256_file(store.path(raw_ref)))
                            # Persist raw evidence before any normalization failure.
                            row.evidence = dict(evidence)
                            self.session.commit()
                            phase = "normalization_failed"
                            normalized = parse_output(raw, role, route["native_fragments"],
                                source_raw_sha256=evidence["raw_sha256"], region_id=row.region_id,
                                inherited_flags=["crop_clipped"] if crop["clipped"] else [])
                            norm_ref = f"{attempt}/normalized.json"
                            write_json(store.path(norm_ref), normalized)
                            evidence.update(normalized_ref=norm_ref, normalized_sha256=sha256_file(store.path(norm_ref)),
                                            normalized_result=normalized)
                            row.state, row.error_code, row.evidence = "completed", None, evidence
                            self.session.commit()
                            self._overlay(run, store, relative, time.monotonic()-start)
                        except Exception:
                            self.session.rollback()
                            row.state, row.error_code, row.evidence = "failed", phase, evidence
                            self.session.commit()
            except Exception:
                self.session.rollback()
                for row in group:
                    if row.state != "completed":
                        row.state, row.error_code = "failed", "model_runtime_failed"
                run.error_code = "model_runtime_failed"
                self.session.commit()
                break  # Do not start a second model after startup/release failure.
        self.session.expire_all()
        rows = self.session.scalars(select(QuestionImportVisionResult).where(QuestionImportVisionResult.run_id == run_id)).all()
        run.state = "failed" if run.error_code or any(r.state == "failed" for r in rows) else "paused" if any(
            r.state in {"planned", "rendered", "running"} for r in rows) else "completed"
        self.session.commit()
        self._overlay(run, store, relative, time.monotonic()-start)
        return self.get(run.id)

    def _overlay(self, run, store, relative, duration):
        value = {"schema_version": OVERLAY_SCHEMA, "run_id": run.id, "draft_id": run.draft_id,
                 "input_sha256": run.input_sha256, "source_draft_sha256": run.snapshot["plan"]["source_draft_sha256"],
                 "results": self.results(run.id)}
        write_json(store.path(f"{relative}/overlay.json"), value)
        manifest_path = store.path(f"{relative}/manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["overlay_sha256"] = canonical_hash(value)
        _, _, draft, ir, _ = self.source(run.draft_id)
        manifest["source_parser_metadata"] = {"draft": draft.get("parser"), "native": ir["parser"]}
        manifest["result_artifacts"] = [{"region_id": r["region_id"], **{
            k: v for k, v in r["evidence"].items() if k.endswith("_sha256") or k.endswith("_ref")}}
            for r in value["results"]]
        write_json(manifest_path, manifest)
        diagnostics_path = store.path(f"{relative}/diagnostics.json")
        diagnostics = json.loads(diagnostics_path.read_text()) if diagnostics_path.exists() else {}
        diagnostics.update(state=run.state, overlay_sha256=canonical_hash(value))
        if duration is not None:
            diagnostics["last_execution_seconds"] = duration
        write_json(diagnostics_path, diagnostics)
