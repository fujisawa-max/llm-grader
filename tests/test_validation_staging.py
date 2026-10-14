"""Read-only source export, transactional staging, and isolated acceptance."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError

from scoring.db import models as m
from scoring.db.worker import JobWorker
from scoring.pdf_native import canonical_hash, sha256_file
from scoring import validation_staging as staging
from tests.test_revision_grading import (
    workspace as grading_workspace, confirm, create_submission, set_edition_values,
)
from tests.test_test_authoring import base, begin
from tests.run_staged_synthetic_acceptance import run_acceptance


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    yield from grading_workspace.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def evidence(workspace, tmp_path, request):
    w = workspace
    asset_id = None
    visual = getattr(request, "param", False)
    if visual:
        import base64
        path = tmp_path / "artifacts/q-assets/figure.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6pAAAAABJRU5ErkJggg=="))
        with w.sf() as session:
            asset = m.TestQuestionAsset(question_id=w.question, asset_type="figure",
                artifact_ref="figure.png", sha256=sha256_file(path), mime_type="image/png",
                provenance={"extraction_id": "q-assets", "bbox": [0, 0, 10, 20], "page_index": 0})
            session.add(asset)
            session.commit()
            asset_id = asset.id

    def include_figure(row):
        if asset_id:
            snapshot = deepcopy(row["snapshot"])
            snapshot["nodes"][0]["ordered_content"].append({"type": "figure", "asset_id": asset_id, "order": 1})
            saved = w.client.put(base(w) + "/authoring", json={
                "expected_edit_version": row["edit_version"], "snapshot": snapshot})
            assert saved.status_code == 200, saved.text
            return saved.json()
        return row

    first = set_edition_values(w, begin(w), question_text="Edition A question",
        answer_text="Edition A answer", levels=[
            {"score": 0, "condition": "A: no credit"}, {"score": 10, "condition": "A: full credit"}])
    response = confirm(w, include_figure(first))
    assert response.status_code == 200, response.text
    a = response.json()
    s1 = create_submission(w, tmp_path, "STAGING-A")
    revised = w.client.post(base(w) + "/authoring/revisions", json={"confirmed_revision_id": a["id"]})
    assert revised.status_code == 200, revised.text
    second = set_edition_values(w, revised.json(), question_text="Edition B question",
        answer_text="Edition B answer", levels=[
            {"score": 0, "condition": "B: no credit"}, {"score": 5, "condition": "B: partial"},
            {"score": 10, "condition": "B: full credit"}])
    response = confirm(w, include_figure(second))
    assert response.status_code == 200, response.text
    b = response.json()
    s2 = create_submission(w, tmp_path, "STAGING-B")
    with w.sf() as session:
        teacher_id = session.get(m.Course, w.course).owner_user_id
        # Drift only disposable-source mutable projections. Their real rows
        # may be required for FK handles, but must not become grading authority.
        session.execute(update(m.TestQuestion).where(m.TestQuestion.id == w.question).values(question_text="MUTABLE QUESTION DRIFT"))
        session.execute(update(m.ModelAnswer).where(m.ModelAnswer.test_id == w.legacy).values(answer_text="MUTABLE ANSWER DRIFT"))
        for rubric in session.scalars(select(m.RubricVersion).where(m.RubricVersion.test_id == w.legacy)).all():
            value = deepcopy(rubric.rubric_json)
            value["questions"][0]["criteria"][0]["levels"] = [
                {"score": 0, "condition": "mutable zero"}, {"score": 2, "condition": "mutable partial"},
                {"score": 10, "condition": "mutable full"}]
            session.execute(update(m.RubricVersion).where(m.RubricVersion.id == rubric.id).values(rubric_json=value))
        session.commit()
    policy = {"test_id": w.legacy, "teacher_id": teacher_id, "question_ids": [w.question],
        "revisions": [{"id": a["id"], "question_text": "Edition A question" + ("\n[図]" if visual else ""), "model_answer": "Edition A answer", "levels": [0, 10]},
                      {"id": b["id"], "question_text": "Edition B question" + ("\n[図]" if visual else ""), "model_answer": "Edition B answer", "levels": [0, 5, 10]}],
        "submissions": [{"id": s1["id"], "revision_id": a["id"]}, {"id": s2["id"], "revision_id": b["id"]}]}
    root = tmp_path / "export"
    source_db = Path(w.engine.url.database)
    source_hash = sha256_file(source_db)
    with staging.ReadOnlySource.sqlite_fixture(source_db) as source:
        with pytest.raises(OperationalError):
            source.connection.execute(text("UPDATE tests SET name='forbidden'"))
        source.connection.rollback()
        manifest = staging.export_validation_data(source, policy, source_environment="local-fixture",
            artifact_roots={"question_import": tmp_path / "artifacts", "answer_import": tmp_path / "artifacts"},
            output_root=root)
    assert sha256_file(source_db) == source_hash
    return SimpleNamespace(w=w, policy=policy, root=root, source_db=source_db,
        source_hash=source_hash, manifest=manifest, a=a, b=b,
        protected=[source_db, tmp_path / "artifacts"])


def _reseal(root, records=None, manifest=None):
    records = records or json.loads((root / "records.json").read_text())
    manifest = manifest or json.loads((root / "manifest.json").read_text())
    manifest["records_sha256"] = canonical_hash(records)
    manifest["record_inventory"] = {name: [{"id": r["id"], "sha256": canonical_hash(r)} for r in rows]
                                    for name, rows in records.items()}
    manifest["manifest_sha256"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    (root / "records.json").write_text(json.dumps(records))
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_export_import_job_worker_review_finalize_isolated(evidence, tmp_path):
    e = evidence
    stage = staging.stage_validation_data(e.root, tmp_path / "stage", e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    staging.verify_staged_database(stage, e.policy)
    manifest, records = staging.verify_export(stage, e.policy)
    assert manifest["manifest_sha256"] == e.manifest["manifest_sha256"]
    assert {r["id"] for r in records["confirmed_authoring_revisions"]} == {e.a["id"], e.b["id"]}
    for revision in records["confirmed_authoring_revisions"]:
        original = e.a if revision["id"] == e.a["id"] else e.b
        assert revision["snapshot"] == original["snapshot"]
        assert revision["snapshot_sha256"] == original["snapshot_sha256"]
    assert "model_answers" not in records
    assert "grading_jobs" not in records
    assert all(r["password_hash"] is None for r in records["users"])
    assert all("STAGING-" not in r["student_identifier"] for r in records["students"])
    assert str(tmp_path) not in json.dumps(manifest)
    result = run_acceptance(stage, e.policy, expected_manifest_sha256=e.manifest["manifest_sha256"])
    assert [r["score"] for r in result["results"]] == [10, 5]
    assert [r["edition_label"] for r in result["results"]] == ["第1版", "第2版"]
    assert result["real_model_calls"] == result["ocr_calls"] == result["production_jobs"] == 0
    assert result["published"] is False
    assert result["results"][0]["package_sha256"] != result["results"][1]["package_sha256"]
    # The ordinary source Worker cannot see either staged synthetic Job.
    normal = JobWorker(e.w.sf, grading_runner_factory=lambda: pytest.fail("normal grader invoked"))
    for item in result["results"]:
        assert normal.run_once(item["job_id"]) is None
    with e.w.sf() as session:
        assert session.scalar(select(func.count()).select_from(m.GradingJob)) == 0
        assert session.scalar(select(func.count()).select_from(m.StudentAnswerReconstruction)) == 0
        assert session.get(m.Test, e.policy["test_id"]).active_confirmed_revision_id == e.b["id"]
    assert sha256_file(e.source_db) == e.source_hash
    with pytest.raises(ValueError, match="STAGING_ACCEPTANCE_ALREADY_RUN"):
        run_acceptance(stage, e.policy, expected_manifest_sha256=e.manifest["manifest_sha256"])


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_frozen_visual_bytes_geometry_and_provenance_survive_staging(evidence, tmp_path):
    e = evidence
    stage = staging.stage_validation_data(e.root, tmp_path / "visual-stage", e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    manifest, records = staging.verify_export(stage, e.policy)
    visual_entries = [a for a in manifest["artifacts"] if a["namespace"] == "question_import"]
    assert len(visual_entries) == 1
    assert visual_entries[0]["artifact_ref"] == "q-assets/figure.png"
    for revision in records["confirmed_authoring_revisions"]:
        definition = staging.confirmed_definition(SimpleNamespace(**revision))
        reference = definition["questions"][0]["visual_references"][0]
        assert reference["provenance"]["bbox"] == [0, 0, 10, 20]
        assert reference["provenance"]["page_index"] == 0
        assert reference["sha256"] == sha256_file(stage / "artifacts/question_import/q-assets/figure.png")
    # Changing a staged crop is rejected even while the confirmed snapshot is unchanged.
    (stage / "artifacts/question_import/q-assets/figure.png").write_bytes(b"modified")
    with pytest.raises(ValueError, match="STAGING_ARTIFACT"):
        staging.verify_staged_database(stage, e.policy)


@pytest.mark.parametrize("case", ["owner", "test", "submission", "revision"])
def test_nonallowlisted_source_export_fails_without_output(evidence, tmp_path, case):
    e = evidence
    policy = deepcopy(e.policy)
    if case == "owner":
        policy["teacher_id"] = str(uuid4())
    elif case == "test":
        policy["test_id"] = e.w.fresh
    elif case == "submission":
        policy["submissions"][0]["id"] = str(uuid4())
    else:
        policy["revisions"][0]["id"] = str(uuid4())
        policy["submissions"][0]["revision_id"] = policy["revisions"][0]["id"]
    out = tmp_path / "denied-export"
    with staging.ReadOnlySource.sqlite_fixture(e.source_db) as source:
        with pytest.raises((ValueError, PermissionError)):
            staging.export_validation_data(source, policy, source_environment="test", artifact_roots={
                "question_import": tmp_path / "artifacts", "answer_import": tmp_path / "artifacts"}, output_root=out)
    assert not out.exists()
    assert sha256_file(e.source_db) == e.source_hash


@pytest.mark.parametrize("case", ["snapshot_sha", "cross_test", "fk", "schema", "pin", "extra_student", "credentials", "levels"])
def test_resealed_bad_records_are_rejected(evidence, tmp_path, case):
    e = evidence
    records = json.loads((e.root / "records.json").read_text())
    if case == "snapshot_sha":
        records["confirmed_authoring_revisions"][0]["snapshot_sha256"] = "0" * 64
    elif case == "cross_test":
        records["confirmed_authoring_revisions"][0]["test_id"] = str(uuid4())
    elif case == "fk":
        records["course_offerings"] = []
    elif case == "schema":
        revision = records["confirmed_authoring_revisions"][0]
        revision["snapshot"]["domains"]["grading_definition"]["schema_version"] = "unsupported.v99"
        revision["snapshot_sha256"] = canonical_hash(revision["snapshot"])
    elif case == "pin":
        records["student_submissions"][0]["confirmed_authoring_revision_id"] = None
    elif case == "extra_student":
        extra = deepcopy(records["students"][0])
        extra["id"] = str(uuid4())
        records["students"].append(extra)
    elif case == "credentials":
        records["users"][0]["password_hash"] = "production-secret"
    else:
        revision = records["confirmed_authoring_revisions"][0]
        revision["snapshot"]["domains"]["grading_definition"]["questions"][0]["rubric"]["criteria"][0]["levels"][0]["score"] = 7
        revision["snapshot_sha256"] = canonical_hash(revision["snapshot"])
    _reseal(e.root, records=records)
    with pytest.raises((ValueError, PermissionError)):
        staging.verify_export(e.root, e.policy)
    with pytest.raises((ValueError, PermissionError)):
        staging.stage_validation_data(e.root, tmp_path / "invalid-stage", e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    assert not (tmp_path / "invalid-stage").exists()


@pytest.mark.parametrize("case", ["missing", "modified", "traversal", "symlink", "extra", "synthetic_input"])
def test_artifact_security_and_completeness(evidence, tmp_path, case):
    e = evidence
    manifest = json.loads((e.root / "manifest.json").read_text())
    entry = manifest["artifacts"][0]
    artifact = e.root / "artifacts" / entry["namespace"] / entry["artifact_ref"]
    if case == "missing":
        artifact.unlink()
    elif case == "modified":
        artifact.write_bytes(b"corrupt")
    elif case == "traversal":
        entry["artifact_ref"] = "../../outside.pdf"
        _reseal(e.root, manifest=manifest)
    elif case == "symlink":
        external = tmp_path / "external.pdf"
        external.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(external)
    elif case == "extra":
        (e.root / "artifacts" / "unrelated-answer.pdf").write_bytes(b"unrelated")
    else:
        records = json.loads((e.root / "records.json").read_text())
        records["courses"][0]["description"] = staging.SYNTHETIC_INPUTS[0]
        _reseal(e.root, records=records, manifest=manifest)
    with pytest.raises((ValueError, OSError)):
        staging.stage_validation_data(e.root, tmp_path / "bad-artifact-stage", e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    assert not (tmp_path / "bad-artifact-stage").exists()


@pytest.mark.parametrize("case", ["missing_original", "changed_original"])
def test_registered_answer_original_source_closure(evidence, case):
    e = evidence
    manifest, records = staging.verify_export(e.root, e.policy)
    original_id = next(iter(manifest["material_dependencies"].values()))[0]["id"]
    material = next(row for row in records["test_materials"] if row["id"] == original_id)
    path = e.root / "artifacts/answer_import" / material["storage_ref"]
    assert path.suffix == ".pdf"
    if case == "missing_original":
        path.unlink()
        with pytest.raises(OSError):
            staging.verify_export(e.root, e.policy)
    else:
        material["sha256"] = "0" * 64
        _reseal(e.root, records=records)
        with pytest.raises(ValueError, match="STAGING_.*(HASH|LINEAGE|MATERIAL_ARTIFACT_MISSING)"):
            staging.verify_export(e.root, e.policy)


def test_existing_root_overlap_symlink_and_wrong_database_are_rejected(evidence, tmp_path):
    e = evidence
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(FileExistsError):
        staging.stage_validation_data(e.root, occupied, e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    assert sentinel.read_text() == "untouched"
    for destination in (tmp_path / "artifacts/staging", e.source_db):
        with pytest.raises(ValueError, match="STAGING_SOURCE_DESTINATION_OVERLAP"):
            staging.stage_validation_data(e.root, destination, e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    link = tmp_path / "linked"
    link.symlink_to(occupied, target_is_directory=True)
    with pytest.raises(ValueError, match="STAGING_SYMLINK_FORBIDDEN"):
        staging.stage_validation_data(e.root, link / "new", e.policy, protected_roots=e.protected, expected_manifest_sha256=e.manifest["manifest_sha256"])
    from tests.synthetic_validation import IsolatedSyntheticValidationWorker
    with pytest.raises(ValueError, match="SYNTHETIC_VALIDATION_DATABASE_IDENTITY_MISMATCH"):
        IsolatedSyntheticValidationWorker(e.w.sf, disposable_root=tmp_path,
            validation_database_path=tmp_path / "other.sqlite", allowed_test_ids={e.policy["test_id"]})


def test_transactional_import_rollback_and_not_ready(evidence, tmp_path, monkeypatch):
    original = staging.create_session_factory
    def failing_factory(*args, **kwargs):
        engine, sf = original(*args, **kwargs)
        @event.listens_for(engine, "before_cursor_execute")
        def fail_insert(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.startswith("INSERT INTO student_submissions"):
                raise ValueError("injected import failure")
        return engine, sf
    monkeypatch.setattr(staging, "create_session_factory", failing_factory)
    root = tmp_path / "incomplete-stage"
    with pytest.raises(ValueError, match="injected import failure"):
        staging.stage_validation_data(evidence.root, root, evidence.policy, protected_roots=evidence.protected, expected_manifest_sha256=evidence.manifest["manifest_sha256"])
    assert (root / "INCOMPLETE.json").exists()
    assert not (root / "READY.json").exists()
    with staging.ReadOnlySource.sqlite_fixture(root / "validation.sqlite") as source:
        assert source.connection.execute(text("SELECT count(*) FROM confirmed_authoring_revisions")).scalar_one() == 0
        assert source.connection.execute(text("SELECT count(*) FROM tests")).scalar_one() == 0
    with pytest.raises(OSError):
        run_acceptance(root, evidence.policy, expected_manifest_sha256=evidence.manifest["manifest_sha256"])


def test_untrusted_source_and_writable_role_rejected(monkeypatch):
    with pytest.raises(PermissionError):
        staging.ReadOnlySource(object())
    # Exercise the production permission gate without contacting a production
    # host. The independent SQLite fixture above proves actual denied writes.
    class Connection:
        def execution_options(self, **_kwargs):
            return self
        def begin(self):
            return SimpleNamespace(rollback=lambda: None)
        def execute(self, query):
            return SimpleNamespace(scalar_one=lambda: True if "write_capable" in str(query) else "on")
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=Connection, dispose=lambda: None)
    monkeypatch.setattr(staging, "create_engine", lambda *_a, **_kw: engine)
    with pytest.raises(PermissionError, match="STAGING_SOURCE_ROLE_WRITE_CAPABLE"):
        with staging.ReadOnlySource.postgres("not-a-real-credential"):
            pytest.fail("writable role accepted")


def test_trusted_hash_and_nonpostgres_source_required(evidence, tmp_path):
    with pytest.raises(ValueError, match="STAGING_TRUSTED_MANIFEST_HASH_MISMATCH"):
        staging.stage_validation_data(evidence.root, tmp_path / "wrong-checksum", evidence.policy,
            protected_roots=evidence.protected, expected_manifest_sha256="0" * 64)
    assert not (tmp_path / "wrong-checksum").exists()
    path = tmp_path / "must-not-create.sqlite"
    with pytest.raises(ValueError, match="STAGING_POSTGRES_READONLY_ROLE_REQUIRED"):
        with staging.ReadOnlySource.postgres(f"sqlite:///{path}"):
            pytest.fail("production exporter accepted writable SQLite")
    assert not path.exists()
