"""Explicit, read-only export and disposable import for grading acceptance.

No API/worker route imports this module. The CLI requires an operator allowlist
and a PostgreSQL role whose effective privileges prohibit writes. Local tests
use a physically read-only SQLite connection. No credentials are exported.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import create_engine, event, func, insert, or_, select, text
from sqlalchemy.sql.sqltypes import DateTime

from .db.database import Base, create_session_factory, init_database
from .db import models as m
from .grading_definition import confirmed_definition, confirmed_revision_for_test
from .pdf_native import canonical_hash

SCHEMA = "isolated-grading-export.v1"
VERSION = "j-grading-1c.v1"
TABLES = (
    "users", "courses", "course_offerings", "tests", "test_questions",
    "test_materials", "test_authoring_revisions", "confirmed_authoring_revisions",
    "rubric_versions", "students", "student_submissions",
)
MAX_BYTES = 100 * 1024 * 1024
_READONLY_TOKEN = object()
SYNTHETIC_INPUTS = ("Synthetic answer for edition A acceptance", "Synthetic answer for edition B acceptance")


def _fail(code):
    raise ValueError(code)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _dump(path, value):
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, sort_keys=True, allow_nan=False)
    path.chmod(0o600)


def _no_symlinks(path):
    path = Path(path)
    if ".." in path.parts or not path.is_absolute() or any(c in str(path) for c in ("?", "#", "\x00")):
        _fail("STAGING_PATH_INVALID")
    for part in (path, *path.parents):
        if part.is_symlink():
            _fail("STAGING_SYMLINK_FORBIDDEN")
    return path


def _relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or PurePosixPath(value).is_absolute()
            or any(p in {"", ".", ".."} for p in value.split("/"))
            or ":" in value):
        _fail("STAGING_ARTIFACT_PATH_INVALID")
    return value


def _read(root, relative):
    """Open each component without following symlinks (including during races)."""
    root = _no_symlinks(Path(root))
    parts = _relative(relative).split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                _fail("STAGING_ARTIFACT_SIZE_OR_TYPE_INVALID")
            return file.read(MAX_BYTES + 1)
    finally:
        os.close(fd)


def _new_root(path, protected):
    path = _no_symlinks(Path(path))
    for other in protected:
        other = _no_symlinks(Path(other))
        if path == other or path.is_relative_to(other) or other.is_relative_to(path):
            _fail("STAGING_SOURCE_DESTINATION_OVERLAP")
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    return path


def validate_allowlist(policy):
    if not isinstance(policy, dict) or set(policy) != {
            "test_id", "teacher_id", "question_ids", "revisions", "submissions"}:
        _fail("STAGING_EXPLICIT_ALLOWLIST_REQUIRED")
    try:
        UUID(policy["test_id"])
        UUID(policy["teacher_id"])
        questions = policy["question_ids"]
        revisions, submissions = policy["revisions"], policy["submissions"]
        if (not isinstance(questions, list) or not questions or len(set(questions)) != len(questions)
                or not isinstance(revisions, list) or len(revisions) != 2
                or not isinstance(submissions, list) or len(submissions) != 2):
            raise ValueError
        for qid in questions:
            UUID(qid)
        for revision in revisions:
            if set(revision) != {"id", "question_text", "model_answer", "levels"}:
                raise ValueError
            UUID(revision["id"])
            if (not revision["question_text"] or not revision["model_answer"]
                    or revision["levels"] not in ([0, 10], [0, 5, 10])):
                raise ValueError
        if revisions[0]["levels"] != [0, 10] or revisions[1]["levels"] != [0, 5, 10]:
            raise ValueError
        if len({r["id"] for r in revisions}) != 2 or len({s["id"] for s in submissions}) != 2:
            raise ValueError
        for sub, revision in zip(submissions, revisions):
            if set(sub) != {"id", "revision_id"} or sub["revision_id"] != revision["id"]:
                raise ValueError
            UUID(sub["id"])
    except (KeyError, TypeError, ValueError):
        _fail("STAGING_ALLOWLIST_INVALID")
    return deepcopy(policy)


# Reject effective writes, writable SET ROLE memberships, owners, schema/database
# creation, sequence advancement, and user-defined security-definer functions.
# Operators must provision/revoke grants separately; this tool changes no ACL.
PG_PRIVILEGES = """
WITH roles AS (
 SELECT oid, rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles
 WHERE rolname=current_user OR pg_has_role(current_user, oid, 'MEMBER')
)
SELECT
 EXISTS(SELECT 1 FROM roles WHERE rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls
   OR rolname IN ('pg_write_all_data','pg_write_server_files','pg_execute_server_program',
                 'pg_checkpoint','pg_maintain','pg_signal_backend'))
 OR EXISTS(SELECT 1 FROM roles r, pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
   AND c.relkind IN ('r','p','v','m','f')
   AND has_table_privilege(r.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
 OR EXISTS(SELECT 1 FROM roles r, pg_class c WHERE c.relkind='S'
   AND has_sequence_privilege(r.oid,c.oid,'USAGE,UPDATE'))
 OR EXISTS(SELECT 1 FROM roles r, pg_namespace n
   WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
   AND has_schema_privilege(r.oid,n.oid,'CREATE'))
 OR EXISTS(SELECT 1 FROM roles r, pg_database d WHERE d.datname=current_database()
   AND has_database_privilege(r.oid,d.oid,'CREATE,TEMP'))
 OR EXISTS(SELECT 1 FROM roles r, pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
   AND (p.prosecdef OR p.provolatile='v') AND has_function_privilege(r.oid,p.oid,'EXECUTE'))
AS write_capable
"""


class ReadOnlySource:
    """Capability constructed only after database-level read-only enforcement."""
    def __init__(self, connection, *, database_path=None, _token=None):
        if _token is not _READONLY_TOKEN:
            raise PermissionError("STAGING_READONLY_SOURCE_REQUIRED")
        self.connection = connection
        self.database_path = database_path

    @classmethod
    @contextmanager
    def postgres(cls, url):
        engine = create_engine(url, echo=False, hide_parameters=True)
        try:
            if engine.dialect.name != "postgresql":
                _fail("STAGING_POSTGRES_READONLY_ROLE_REQUIRED")
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
                transaction = conn.begin()
                try:
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    if conn.execute(text(PG_PRIVILEGES)).scalar_one():
                        raise PermissionError("STAGING_SOURCE_ROLE_WRITE_CAPABLE")
                    if conn.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
                        _fail("STAGING_READONLY_TRANSACTION_REQUIRED")
                    yield cls(conn, _token=_READONLY_TOKEN)
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()

    @classmethod
    @contextmanager
    def sqlite_fixture(cls, path):
        """Local tests only. OS-opened SQLite mode=ro rejects physical DB writes."""
        path = _no_symlinks(Path(path))
        if not path.is_file():
            _fail("STAGING_SOURCE_DATABASE_MISSING")
        engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true", hide_parameters=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA query_only=ON"))
                conn.exec_driver_sql("BEGIN")
                try:
                    yield cls(conn, database_path=path, _token=_READONLY_TOKEN)
                finally:
                    conn.rollback()
        finally:
            engine.dispose()


def _rows(source, model, ids, **scope):
    ids = set(ids)
    table = model.__table__
    statement = select(table).where(table.c.id.in_(sorted(ids)))
    for field, value in scope.items():
        statement = statement.where(table.c[field] == value)
    result = [_json_value(dict(row)) for row in source.connection.execute(statement).mappings()]
    if {r["id"] for r in result} != ids:
        _fail("STAGING_REQUIRED_RECORD_MISSING")
    return sorted(result, key=lambda r: r["id"])


def read_source_baseline(source, policy):
    """Counts/identity only; no unrelated Job/event/reconstruction content."""
    conn = source.connection
    tid = policy["test_id"]
    return {"active_revision": conn.execute(select(m.Test.active_confirmed_revision_id).where(m.Test.id == tid)).scalar_one(),
        "submission_pins": dict(conn.execute(select(m.StudentSubmission.id, m.StudentSubmission.confirmed_authoring_revision_id).where(
            m.StudentSubmission.test_id == tid, m.StudentSubmission.id.in_([s["id"] for s in policy["submissions"]]))).all()),
        "test_event_count": conn.execute(select(func.count()).select_from(m.DomainEvent).where(or_(
            m.DomainEvent.entity_id == tid, m.DomainEvent.payload["test_id"].as_string() == tid))).scalar_one(),
        "test_job_count": conn.execute(select(func.count()).select_from(m.GradingJob).where(m.GradingJob.test_id == tid)).scalar_one(),
        "global_health_job_counts": "unverified; compare authenticated health API separately"}


def _artifact_entry(namespace, ref, digest, data, identity, media_type):
    import hashlib
    _relative(ref)
    if not re.fullmatch("[0-9a-f]{64}", str(digest)) or hashlib.sha256(data).hexdigest() != digest:
        _fail("STAGING_ARTIFACT_HASH_MISMATCH")
    return {"namespace": namespace, "artifact_ref": ref, "sha256": digest,
            "size": len(data), "identity": identity, "media_type": media_type}


def _verify_records(records, policy, material_dependencies=None):
    """Validate exact inventory, full FK closure, and snapshot-only A/B contracts."""
    validate_allowlist(policy)
    if set(records) != set(TABLES):
        _fail("STAGING_RECORD_INVENTORY_INVALID")
    indexed = {}
    for name, rows in records.items():
        if not isinstance(rows, list) or len({r["id"] for r in rows}) != len(rows):
            _fail("STAGING_RECORD_IDENTITY_INVALID")
        indexed[name] = {r["id"]: r for r in rows}
        table = Base.metadata.tables[name]
        for row in rows:
            if set(row) != set(table.c.keys()):
                _fail("STAGING_RECORD_SCHEMA_INVALID")
    for name, rows in records.items():
        table = Base.metadata.tables[name]
        for row in rows:
            for fk in table.foreign_keys:
                value = row[fk.parent.name]
                if value is not None and value not in indexed.get(fk.column.table.name, {}):
                    _fail("STAGING_FK_DEPENDENCY_MISSING")
    if (set(indexed["tests"]) != {policy["test_id"]}
            or set(indexed["confirmed_authoring_revisions"]) != {r["id"] for r in policy["revisions"]}
            or set(indexed["student_submissions"]) != {s["id"] for s in policy["submissions"]}
            or set(indexed["test_questions"]) != set(policy["question_ids"])):
        _fail("STAGING_NON_ALLOWLISTED_RECORD")
    test = indexed["tests"][policy["test_id"]]
    course = indexed["courses"][indexed["course_offerings"][test["course_offering_id"]]["course_id"]]
    if course["owner_user_id"] != policy["teacher_id"]:
        raise PermissionError("STAGING_TEST_OWNER_REQUIRED")
    required_users = {policy["teacher_id"]}
    for table, field in (("test_authoring_revisions", "created_by"),
                         ("confirmed_authoring_revisions", "confirmed_by"),
                         ("rubric_versions", "approved_by_user_id")):
        required_users.update(r[field] for r in records[table] if r[field])
    if (set(indexed["users"]) != required_users
            or len(records["courses"]) != 1 or len(records["course_offerings"]) != 1
            or set(indexed["students"]) != {s["student_id"] for s in records["student_submissions"]}
            or set(indexed["test_authoring_revisions"]) != {r["authoring_revision_id"] for r in records["confirmed_authoring_revisions"]}
            or len(records["rubric_versions"]) != 2):
        _fail("STAGING_NON_ALLOWLISTED_DEPENDENCY")
    owner = indexed["users"][policy["teacher_id"]]
    if (any(r["password_hash"] is not None or r["email"] is not None for r in records["users"])
            or owner["role"] != "teacher"
            or any(r["is_active"] for r in records["users"] if r["id"] != owner["id"])):
        _fail("STAGING_AUTH_DATA_FORBIDDEN")
    required_materials = {s["material_id"] for s in records["student_submissions"]}
    for dependencies in (material_dependencies or {}).values():
        required_materials.update(item["id"] for item in dependencies)
    for revision in records["confirmed_authoring_revisions"]:
        required_materials.update(r["id"] for r in revision["snapshot"].get("materials", []))
    if set(indexed["test_materials"]) != required_materials:
        _fail("STAGING_NON_ALLOWLISTED_MATERIAL")
    for revision in records["confirmed_authoring_revisions"]:
        for material in revision["snapshot"].get("materials", []):
            if indexed["test_materials"][material["id"]]["sha256"] != material.get("sha256"):
                _fail("STAGING_SOURCE_IDENTITY_MISMATCH")
    if test["active_confirmed_revision_id"] != policy["revisions"][1]["id"]:
        _fail("STAGING_ACTIVE_REVISION_MISMATCH")
    previous = None
    previous_number = 0
    for expected in policy["revisions"]:
        revision = indexed["confirmed_authoring_revisions"][expected["id"]]
        if revision["test_id"] != test["id"]:
            _fail("STAGING_CROSS_TEST_REVISION")
        definition = confirmed_definition(SimpleNamespace(**revision))
        if (definition.get("authority") != "web_authoring"
                or definition.get("schema_version") != "web-grading-definition.v1"
                or definition.get("interpreter_version") != "discrete-integer-sum.v1"
                or definition.get("complete") is not True):
            _fail("STAGING_GRADING_DEFINITION_UNSUPPORTED")
        questions = definition["questions"]
        if {q.get("formal_question_id") for q in questions} != set(policy["question_ids"]):
            _fail("STAGING_QUESTION_IDENTITY_MISMATCH")
        # This acceptance has one executable Question. Do not infer a mapping
        # or expand the operator's allowlist to accommodate another shape.
        gradable = [q for q in questions if q.get("gradable")]
        if len(gradable) != 1:
            _fail("STAGING_EXPECTED_SINGLE_GRADABLE_QUESTION")
        q = gradable[0]
        if (q["own_text"] != expected["question_text"]
                or q["answer"]["primary"] != expected["model_answer"]
                or q["max_points"] != 10 or len(q["rubric"]["criteria"]) != 1
                or [v["score"] for v in q["rubric"]["criteria"][0]["levels"]] != expected["levels"]):
            _fail("STAGING_EXPECTED_POLICY_MISMATCH")
        working = indexed["test_authoring_revisions"][revision["authoring_revision_id"]]
        if (working["test_id"] != test["id"] or working["parent_confirmed_revision_id"] != previous
                or working["snapshot"] != revision["snapshot"]
                or working["snapshot_sha256"] != revision["snapshot_sha256"]
                or working["revision"] != revision["revision"]
                or working["edit_version"] != revision["edit_version"]
                or revision["revision"] <= previous_number):
            _fail("STAGING_LINEAGE_OR_SAVED_SNAPSHOT_MISMATCH")
        previous = revision["id"]
        previous_number = revision["revision"]
        rubrics = [r for r in records["rubric_versions"] if (r["generation_metadata"] or {}).get(
            "authoring_revision_id") == revision["authoring_revision_id"]]
        if len(rubrics) != 1 or rubrics[0]["test_id"] != test["id"]:
            _fail("STAGING_RUBRIC_COMPATIBILITY_REFERENCE_MISSING")
    for expected in policy["submissions"]:
        sub = indexed["student_submissions"][expected["id"]]
        if sub["test_id"] != test["id"] or sub["confirmed_authoring_revision_id"] != expected["revision_id"]:
            _fail("STAGING_SUBMISSION_PIN_MISMATCH")
        if indexed["students"][sub["student_id"]]["course_offering_id"] != test["course_offering_id"]:
            _fail("STAGING_STUDENT_OFFERING_MISMATCH")
    for name in ("test_questions", "test_materials", "test_authoring_revisions", "rubric_versions"):
        if any(r["test_id"] != test["id"] for r in records[name]):
            _fail("STAGING_CROSS_TEST_DEPENDENCY")
    return indexed


def export_validation_data(source, policy, *, source_environment, artifact_roots, output_root):
    """Export an allowlisted dependency closure; source transaction never commits."""
    if not isinstance(source, ReadOnlySource):
        raise PermissionError("STAGING_READONLY_SOURCE_REQUIRED")
    policy = validate_allowlist(policy)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", source_environment):
        _fail("STAGING_SOURCE_LABEL_INVALID")
    conn = source.connection
    if source.database_path is not None:
        if not conn.in_transaction():
            conn.exec_driver_sql("BEGIN")
        if conn.execute(text("PRAGMA query_only")).scalar_one() != 1:
            _fail("STAGING_READONLY_TRANSACTION_REQUIRED")
    elif conn.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
        _fail("STAGING_READONLY_TRANSACTION_REQUIRED")
    artifact_roots = {name: _no_symlinks(Path(root)) for name, root in artifact_roots.items()}
    if not artifact_roots or set(artifact_roots) - {"question_import", "answer_import"}:
        _fail("STAGING_SOURCE_ARTIFACT_ROOT_MISSING")
    test = _rows(source, m.Test, [policy["test_id"]])[0]
    offering = _rows(source, m.CourseOffering, [test["course_offering_id"]])[0]
    course = _rows(source, m.Course, [offering["course_id"]])[0]
    if course["owner_user_id"] != policy["teacher_id"]:
        raise PermissionError("STAGING_TEST_OWNER_REQUIRED")
    # Select no password, session, identity PDF, student contact, or auth token.
    owner = conn.execute(select(m.User.id, m.User.role, m.User.is_active).where(
        m.User.id == policy["teacher_id"])).one_or_none()
    if owner is None or owner.role not in {"teacher", "admin"} or not owner.is_active:
        raise PermissionError("STAGING_ACTIVE_TEACHER_REQUIRED")
    confirmed = _rows(source, m.ConfirmedAuthoringRevision, [r["id"] for r in policy["revisions"]], test_id=test["id"])
    if conn.execute(select(func.count()).select_from(m.ConfirmedAuthoringRevision).where(
            m.ConfirmedAuthoringRevision.test_id == test["id"])).scalar_one() != 2:
        _fail("STAGING_EDITION_LINEAGE_INCOMPLETE")
    authoring = _rows(source, m.TestAuthoringRevision, [r["authoring_revision_id"] for r in confirmed], test_id=test["id"])
    submissions = _rows(source, m.StudentSubmission, [s["id"] for s in policy["submissions"]], test_id=test["id"])
    if any(s["test_id"] != test["id"] for s in submissions):
        _fail("STAGING_NON_ALLOWLISTED_SUBMISSION")
    materials = {s["material_id"] for s in submissions}
    for revision in confirmed:
        if revision["test_id"] != test["id"]:
            _fail("STAGING_CROSS_TEST_REVISION")
        materials.update(r["id"] for r in revision["snapshot"].get("materials", []))
    materials = _rows(source, m.TestMaterial, materials, test_id=test["id"])
    students = _rows(source, m.Student, [s["student_id"] for s in submissions], course_offering_id=offering["id"])
    # Read only linked compatibility versions. Never select unrelated/current
    # policies as a substitute for missing confirmed evidence.
    rubric_ids = [r.id for r in conn.execute(select(m.RubricVersion.id).where(
        m.RubricVersion.test_id == test["id"],
        m.RubricVersion.generation_metadata["authoring_revision_id"].as_string().in_(
            [r["id"] for r in authoring])))]
    rubrics = _rows(source, m.RubricVersion, rubric_ids, test_id=test["id"])
    timestamp = datetime.now(timezone.utc).isoformat()
    actor_ids = {owner.id}
    actor_ids.update(r["created_by"] for r in authoring if r["created_by"])
    actor_ids.update(r["confirmed_by"] for r in confirmed if r["confirmed_by"])
    actor_ids.update(r["approved_by_user_id"] for r in rubrics if r["approved_by_user_id"])
    actors = conn.execute(select(m.User.id, m.User.role, m.User.created_at, m.User.updated_at).where(
        m.User.id.in_(sorted(actor_ids)))).all()
    if {actor.id for actor in actors} != actor_ids:
        _fail("STAGING_AUDIT_ACTOR_MISSING")
    users = [{"id": actor.id, "display_name": "Isolated validation actor", "email": None,
            "password_hash": None, "role": "teacher" if actor.id == owner.id else actor.role,
            "is_active": actor.id == owner.id, "must_change_password": False,
            "created_at": _json_value(actor.created_at), "updated_at": _json_value(actor.updated_at)}
            for actor in actors]
    transformations = [
        {"table": "users", "fields": ["display_name", "email", "password_hash", "role", "is_active", "must_change_password"],
         "reason": "staging-only owner session; other audit actors inactive; IDs/timestamps retained; no production credentials exported"},
        {"table": "students", "fields": ["student_identifier", "display_name"],
         "reason": "staging pseudonyms; relational identity retained"},
        {"table": "test_materials", "fields": ["storage_ref", "original_filename"],
         "reason": "relative staging storage; immutable bytes and SHA unchanged"},
    ]
    for row in students:
        row["student_identifier"] = f"validation-{row['id']}"
        row["display_name"] = "Synthetic validation student"
    records = {"users": users, "courses": [course], "course_offerings": [offering],
        "tests": [test], "test_questions": _rows(source, m.TestQuestion, policy["question_ids"], test_id=test["id"]),
        "test_materials": materials, "test_authoring_revisions": authoring,
        "confirmed_authoring_revisions": confirmed, "rubric_versions": rubrics,
        "students": students, "student_submissions": submissions}
    baseline = read_source_baseline(source, policy)
    payloads = {}
    inventory = {}
    material_dependencies = {}

    def add(namespace, ref, digest, data, identity, media_type):
        entry = _artifact_entry(namespace, ref, digest, data, identity, media_type)
        key = f"{namespace}/{ref}"
        if key in inventory and inventory[key]["sha256"] != digest:
            _fail("STAGING_ARTIFACT_IDENTITY_COLLISION")
        inventory[key] = entry
        payloads[key] = data

    for material in materials:
        original = Path(material["storage_ref"])
        if original.is_absolute():
            matches = [(namespace, root, original.relative_to(Path(root)).as_posix())
                       for namespace, root in artifact_roots.items()
                       if original.is_relative_to(Path(root))]
            if not matches:
                _fail("STAGING_MATERIAL_OUTSIDE_SOURCE_ROOTS")
            namespace, root, ref = max(matches, key=lambda r: len(str(r[1])))
        else:
            namespace = "answer_import" if material["material_type"].startswith("student") else "question_import"
            root, ref = artifact_roots.get(namespace), material["storage_ref"]
        if root is None:
            _fail("STAGING_SOURCE_ARTIFACT_ROOT_MISSING")
        data = _read(root, ref)
        suffix = Path(ref).suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".json"}:
            _fail("STAGING_SOURCE_TYPE_UNSUPPORTED")
        destination = f"materials/{material['id']}/source{suffix}"
        add("answer_import", destination, material["sha256"], data, material["id"], material["mime_type"])
        if suffix == ".json":
            document = json.loads(data)
            sub = next((s for s in submissions if s["material_id"] == material["id"]), None)
            if (sub is None or document.get("registration_only") is not True
                    or document.get("answers") or not document.get("pages")
                    or document.get("test_id") != test["id"]
                    or document.get("student_id") != sub["student_id"]
                    or document.get("submission_id") != sub["submission_key"]):
                _fail("STAGING_SOURCE_MANIFEST_UNSUPPORTED")
            original_ids, original_hashes = document.get("source_material_ids"), document.get("source_sha256s")
            if (not isinstance(original_ids, list) or not original_ids
                    or len(set(original_ids)) != len(original_ids)
                    or not isinstance(original_hashes, list) or len(original_hashes) != len(original_ids)):
                _fail("STAGING_SOURCE_MATERIAL_LINEAGE_MISSING")
            originals = _rows(source, m.TestMaterial, original_ids, test_id=test["id"])
            expected_hashes = dict(zip(original_ids, original_hashes))
            material_dependencies[material["id"]] = [{"id": mid, "sha256": digest} for mid, digest in zip(original_ids, original_hashes)]
            for original_row in originals:
                if original_row["sha256"] != expected_hashes[original_row["id"]]:
                    _fail("STAGING_SOURCE_MATERIAL_LINEAGE_CHANGED")
                if not any(row["id"] == original_row["id"] for row in materials):
                    materials.append(original_row)
            for page in document["pages"]:
                image = _relative(page["image"])
                image_suffix = PurePosixPath(image).suffix.lower()
                if image_suffix not in {".png", ".jpg", ".jpeg"}:
                    _fail("STAGING_SOURCE_PAGE_TYPE_UNSUPPORTED")
                source_ref = str(PurePosixPath(ref).parent / image)
                target_ref = str(PurePosixPath(destination).parent / image)
                add("answer_import", target_ref, page["sha256"], _read(root, source_ref),
                    page["page_id"], "image/png" if image_suffix == ".png" else "image/jpeg")
        material["storage_ref"] = destination
        material["original_filename"] = f"source{suffix}"
    for revision in confirmed:
        definition = confirmed_definition(SimpleNamespace(**revision))
        for material_ref in revision["snapshot"].get("materials", []):
            row = next((r for r in materials if r["id"] == material_ref["id"]), None)
            if row is None or row["sha256"] != material_ref.get("sha256"):
                _fail("STAGING_SOURCE_IDENTITY_MISMATCH")
        for question in definition["questions"]:
            for reference in question.get("visual_references", []):
                artifact = reference["immutable_artifact"]
                namespace = artifact["namespace"]
                if namespace not in {"question_import", "answer_import"} or not artifact_roots.get(namespace):
                    _fail("STAGING_REFERENCE_NAMESPACE_UNSUPPORTED")
                add(namespace, artifact["artifact_ref"], artifact["sha256"],
                    _read(artifact_roots[namespace], artifact["artifact_ref"]),
                    reference["asset_id"], reference.get("mime_type", "image/png"))
    materials.sort(key=lambda row: row["id"])
    _verify_records(records, policy, material_dependencies)
    serialized = json.dumps(records, ensure_ascii=False)
    if any(value in serialized or any(value.encode() in data for data in payloads.values())
           for value in SYNTHETIC_INPUTS):
        _fail("STAGING_SYNTHETIC_INPUT_IN_EXPORT")
    if sum(len(data) for data in payloads.values()) > 512 * 1024 * 1024:
        _fail("STAGING_EXPORT_TOO_LARGE")
    protected = list(artifact_roots.values()) + ([source.database_path] if source.database_path else [])
    output = _new_root(output_root, protected)
    try:
        for key, data in payloads.items():
            target = output / "artifacts" / key
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as file:
                file.write(data)
            target.chmod(0o600)
        _dump(output / "records.json", records)
        if read_source_baseline(source, policy) != baseline:
            _fail("STAGING_SOURCE_BASELINE_CHANGED")
        manifest = {"schema_version": SCHEMA, "tool_version": VERSION,
            "source_environment": source_environment, "exported_at": timestamp,
            "allowlist": policy, "source_mode": "postgresql-read-only" if source.database_path is None else "local-sqlite-read-only",
            "record_inventory": {name: [{"id": row["id"], "sha256": canonical_hash(row)}
                                          for row in rows] for name, rows in records.items()},
            "records_sha256": canonical_hash(records),
            "revision_inventory": [{"id": r["id"], "snapshot_sha256": r["snapshot_sha256"],
                "parent_revision_id": next(a["parent_confirmed_revision_id"] for a in authoring if a["id"] == r["authoring_revision_id"]),
                "grading_schema": r["snapshot"]["domains"]["grading_definition"]["schema_version"],
                "interpreter": r["snapshot"]["domains"]["grading_definition"]["interpreter_version"]} for r in confirmed],
            "submission_pins": {s["id"]: s["confirmed_authoring_revision_id"] for s in submissions},
            "active_revision": test["active_confirmed_revision_id"],
            "source_baseline": baseline,
            "material_dependencies": material_dependencies,
            "artifacts": [inventory[key] for key in sorted(inventory)],
            "transformations": transformations}
        manifest["manifest_sha256"] = canonical_hash(manifest)
        _dump(output / "manifest.json", manifest)  # Completion marker written last.
        return manifest
    except Exception:
        # Keep only our newly created incomplete export for explicit inspection;
        # never recursively delete an operator directory after an error.
        raise


def verify_export(export_root, policy, *, expected_manifest_sha256=None):
    root = _no_symlinks(Path(export_root))
    manifest = json.loads(_read(root, "manifest.json"))
    records = json.loads(_read(root, "records.json"))
    if set(manifest) != {"schema_version", "tool_version", "source_environment", "exported_at", "allowlist", "source_mode",
            "record_inventory", "records_sha256", "revision_inventory", "submission_pins", "active_revision",
            "source_baseline", "material_dependencies", "artifacts", "transformations", "manifest_sha256"}:
        _fail("STAGING_EXPORT_MANIFEST_INVALID")
    if (manifest.get("schema_version") != SCHEMA or manifest.get("tool_version") != VERSION
            or manifest.get("allowlist") != validate_allowlist(policy)
            or manifest.get("manifest_sha256") != canonical_hash({k: v for k, v in manifest.items() if k != "manifest_sha256"})
            or manifest.get("records_sha256") != canonical_hash(records)):
        _fail("STAGING_EXPORT_MANIFEST_INVALID")
    if expected_manifest_sha256 is not None and manifest["manifest_sha256"] != expected_manifest_sha256:
        _fail("STAGING_TRUSTED_MANIFEST_HASH_MISMATCH")
    expected_inventory = {name: [{"id": row["id"], "sha256": canonical_hash(row)}
                                 for row in rows] for name, rows in records.items()}
    if manifest.get("record_inventory") != expected_inventory:
        _fail("STAGING_RECORD_HASH_MISMATCH")
    indexed = _verify_records(records, policy, manifest["material_dependencies"])
    actual = set()
    for entry in manifest["artifacts"]:
        namespace, ref = entry["namespace"], _relative(entry["artifact_ref"])
        if namespace not in {"question_import", "answer_import"}:
            _fail("STAGING_REFERENCE_NAMESPACE_UNSUPPORTED")
        key = f"{namespace}/{ref}"
        if key in actual:
            _fail("STAGING_ARTIFACT_IDENTITY_COLLISION")
        actual.add(key)
        data = _read(root / "artifacts", key)
        if len(data) != entry["size"]:
            _fail("STAGING_ARTIFACT_SIZE_INVALID")
        _artifact_entry(namespace, ref, entry["sha256"], data, entry["identity"], entry["media_type"])
    required_keys = set()
    actual_material_dependencies = {}
    for material in records["test_materials"]:
        key = f"answer_import/{_relative(material['storage_ref'])}"
        required_keys.add(key)
        entry = next((a for a in manifest["artifacts"] if f"{a['namespace']}/{a['artifact_ref']}" == key), None)
        if entry is None or entry["sha256"] != material["sha256"]:
            _fail("STAGING_MATERIAL_ARTIFACT_MISSING")
        if material["storage_ref"].endswith(".json"):
            document = json.loads(_read(root / "artifacts", key))
            sub = next((s for s in records["student_submissions"] if s["material_id"] == material["id"]), None)
            if (document.get("registration_only") is not True or document.get("answers") or sub is None
                    or document.get("test_id") != policy["test_id"]
                    or document.get("student_id") != sub["student_id"]
                    or document.get("submission_id") != sub["submission_key"]):
                _fail("STAGING_SOURCE_MANIFEST_UNSUPPORTED")
            original_ids, hashes = document.get("source_material_ids"), document.get("source_sha256s")
            if (not isinstance(original_ids, list) or not original_ids or len(set(original_ids)) != len(original_ids)
                    or not isinstance(hashes, list) or len(original_ids) != len(hashes)):
                _fail("STAGING_SOURCE_MATERIAL_LINEAGE_MISSING")
            actual_material_dependencies[material["id"]] = [{"id": mid, "sha256": digest} for mid, digest in zip(original_ids, hashes)]
            for mid, digest in zip(original_ids, hashes):
                if indexed["test_materials"].get(mid, {}).get("sha256") != digest:
                    _fail("STAGING_SOURCE_MATERIAL_LINEAGE_CHANGED")
            for page in document["pages"]:
                if PurePosixPath(page["image"]).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    _fail("STAGING_SOURCE_PAGE_TYPE_UNSUPPORTED")
                page_ref = str(PurePosixPath(material["storage_ref"]).parent / _relative(page["image"]))
                required_keys.add(f"answer_import/{page_ref}")
                page_entry = next((a for a in manifest["artifacts"] if a["namespace"] == "answer_import" and a["artifact_ref"] == page_ref), None)
                if page_entry is None or page_entry["sha256"] != page["sha256"]:
                    _fail("STAGING_SOURCE_PAGE_MISSING")
    if actual_material_dependencies != manifest["material_dependencies"]:
        _fail("STAGING_SOURCE_MATERIAL_LINEAGE_CHANGED")
    for revision in records["confirmed_authoring_revisions"]:
        definition = confirmed_definition(SimpleNamespace(**revision))
        for q in definition["questions"]:
            for ref in q.get("visual_references", []):
                artifact = ref["immutable_artifact"]
                key = f"{artifact['namespace']}/{_relative(artifact['artifact_ref'])}"
                required_keys.add(key)
                entry = next((a for a in manifest["artifacts"] if f"{a['namespace']}/{a['artifact_ref']}" == key), None)
                if entry is None or entry["sha256"] != artifact["sha256"] or ref["sha256"] != artifact["sha256"]:
                    _fail("STAGING_FROZEN_REFERENCE_MISSING")
    if required_keys != actual:
        _fail("STAGING_ARTIFACT_CLOSURE_MISMATCH")
    expected_revisions = [{"id": r["id"], "snapshot_sha256": r["snapshot_sha256"],
        "parent_revision_id": indexed["test_authoring_revisions"][r["authoring_revision_id"]]["parent_confirmed_revision_id"],
        "grading_schema": r["snapshot"]["domains"]["grading_definition"]["schema_version"],
        "interpreter": r["snapshot"]["domains"]["grading_definition"]["interpreter_version"]}
        for r in records["confirmed_authoring_revisions"]]
    if (manifest["revision_inventory"] != expected_revisions
            or manifest["submission_pins"] != {s["id"]: s["confirmed_authoring_revision_id"] for s in records["student_submissions"]}
            or manifest["active_revision"] != indexed["tests"][policy["test_id"]]["active_confirmed_revision_id"]):
        _fail("STAGING_MANIFEST_IDENTITY_MISMATCH")
    # The actual filesystem must exactly match the bound inventory. No extra
    # student pages or arbitrary files can hitchhike on an export.
    files = set()
    for path in (root / "artifacts").rglob("*"):
        if path.is_symlink():
            _fail("STAGING_SYMLINK_FORBIDDEN")
        if path.is_file():
            files.add(path.relative_to(root / "artifacts").as_posix())
    if files != actual:
        _fail("STAGING_ARTIFACT_INVENTORY_MISMATCH")
    if any(value in json.dumps(records, ensure_ascii=False)
           or any(value.encode() in _read(root / "artifacts", key) for key in actual)
           for value in SYNTHETIC_INPUTS):
        _fail("STAGING_SYNTHETIC_INPUT_IN_EXPORT")
    return manifest, records


def stage_validation_data(export_root, staging_root, policy, *, protected_roots, expected_manifest_sha256):
    """Transactionally import exact verified evidence into a fresh SQLite DB."""
    if not re.fullmatch("[0-9a-f]{64}", str(expected_manifest_sha256)):
        _fail("STAGING_TRUSTED_MANIFEST_HASH_REQUIRED")
    manifest, records = verify_export(export_root, policy, expected_manifest_sha256=expected_manifest_sha256)
    if not protected_roots:
        _fail("STAGING_SOURCE_ROOTS_REQUIRED")
    root = _new_root(staging_root, [Path(export_root), *protected_roots])
    _dump(root / "INCOMPLETE.json", {"manifest_sha256": manifest["manifest_sha256"]})
    engine = None
    try:
        for artifact in manifest["artifacts"]:
            key = f"{artifact['namespace']}/{artifact['artifact_ref']}"
            data = _read(Path(export_root) / "artifacts", key)
            _artifact_entry(artifact["namespace"], artifact["artifact_ref"], artifact["sha256"],
                            data, artifact["identity"], artifact["media_type"])
            target = root / "artifacts" / key
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o600)
        engine, sf = create_session_factory(f"sqlite:///{root / 'validation.sqlite'}")
        @event.listens_for(engine, "connect")
        def enforce_fk(dbapi, _record):
            dbapi.execute("PRAGMA foreign_keys=ON")
        init_database(engine)
        with engine.begin() as conn:
            conn.execute(text("PRAGMA defer_foreign_keys=ON"))
            for name in TABLES:
                table = Base.metadata.tables[name]
                converted = deepcopy(records[name])
                for row in converted:
                    for column in table.c:
                        if isinstance(column.type, DateTime) and row.get(column.name):
                            row[column.name] = datetime.fromisoformat(row[column.name])
                if converted:
                    conn.execute(insert(table), converted)
            if conn.execute(text("PRAGMA foreign_key_check")).all():
                _fail("STAGING_FK_DEPENDENCY_MISSING")
            # Validation still occurs inside the import transaction.
            for revision in records["confirmed_authoring_revisions"]:
                confirmed_definition(SimpleNamespace(**revision))
        with sf() as session:
            roots = {n: root / "artifacts" / n for n in ("question_import", "answer_import")}
            for revision in policy["revisions"]:
                confirmed_revision_for_test(session, policy["test_id"], revision["id"], artifact_roots=roots)
        # Copy original records/manifest for independent replay verification.
        _dump(root / "records.json", records)
        _dump(root / "manifest.json", manifest)
        verify_export(root, policy)
        _dump(root / "READY.json", {"schema_version": "isolated-grading-stage.v1",
            "manifest_sha256": manifest["manifest_sha256"], "test_id": policy["test_id"],
            "database": "validation.sqlite", "never_publish": True})
        (root / "validation.sqlite").chmod(0o600)
        (root / "INCOMPLETE.json").unlink()
        return root
    finally:
        if engine is not None:
            engine.dispose()


def verify_staged_database(staging_root, policy, *, expected_manifest_sha256=None):
    """Attest imported DB rows against the export, before any synthetic execution."""
    root = _no_symlinks(Path(staging_root))
    manifest, records = verify_export(root, policy, expected_manifest_sha256=expected_manifest_sha256)
    receipt = json.loads(_read(root, "READY.json"))
    if (root / "INCOMPLETE.json").exists() or receipt != {
            "schema_version": "isolated-grading-stage.v1",
            "manifest_sha256": manifest["manifest_sha256"], "test_id": policy["test_id"],
            "database": "validation.sqlite", "never_publish": True}:
        _fail("STAGING_NOT_READY")
    with ReadOnlySource.sqlite_fixture(root / "validation.sqlite") as source:
        for name in TABLES:
            table = Base.metadata.tables[name]
            actual = [_json_value(dict(row)) for row in source.connection.execute(select(table)).mappings()]
            expected = deepcopy(records[name])
            # SQLite drops timezone offsets from DateTime columns; compare
            # instants after explicit UTC normalization, not snapshot strings.
            for row in [*actual, *expected]:
                for column in table.c:
                    if isinstance(column.type, DateTime) and row.get(column.name):
                        dt = datetime.fromisoformat(row[column.name])
                        row[column.name] = dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
            if sorted(actual, key=lambda r: r["id"]) != sorted(expected, key=lambda r: r["id"]):
                _fail("STAGING_DATABASE_RECORD_MISMATCH")
        if source.connection.execute(text("PRAGMA foreign_key_check")).all():
            _fail("STAGING_FK_DEPENDENCY_MISSING")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("export", "import", "verify"))
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--export-root", type=Path)
    parser.add_argument("--source-environment")
    parser.add_argument("--expected-manifest-sha256", help="Trusted checksum recorded at export; required for import")
    parser.add_argument("--source-roots", type=Path,
                        help="Operator JSON mapping artifact namespaces to absolute read-only roots")
    parser.add_argument("--protected-roots", type=Path,
                        help="Operator JSON list of production DB/artifact/config paths forbidden for staging")
    args = parser.parse_args()
    try:
        policy = json.loads(args.allowlist.read_text())
        if args.operation == "export":
            if not args.source_roots or not args.source_environment:
                parser.error("export requires source roots and source environment")
            url = os.environ.get("GRADING_VALIDATION_READONLY_DATABASE_URL")
            if not url:
                _fail("STAGING_READONLY_CREDENTIAL_REQUIRED")
            roots = {name: Path(value) for name, value in json.loads(args.source_roots.read_text()).items()}
            with ReadOnlySource.postgres(url) as source:
                manifest = export_validation_data(source, policy, source_environment=args.source_environment,
                    artifact_roots=roots, output_root=args.root)
                print(json.dumps({"status": "EXPORTED", "manifest_sha256": manifest["manifest_sha256"]}))
        elif args.operation == "import":
            if not args.export_root or not args.protected_roots or not args.expected_manifest_sha256:
                parser.error("import requires export root, protected roots, and trusted manifest checksum")
            stage_validation_data(args.export_root, args.root, policy,
                protected_roots=[Path(value) for value in json.loads(args.protected_roots.read_text())],
                expected_manifest_sha256=args.expected_manifest_sha256)
            print(json.dumps({"status": "STAGED"}))
        else:
            manifest, _records = verify_export(args.root, policy)
            print(json.dumps({"status": "VERIFIED", "manifest_sha256": manifest["manifest_sha256"]}))
    except Exception as exc:
        # No database URLs, paths, driver errors, or raw record content in CLI logs.
        safe = str(exc) if isinstance(exc, (ValueError, PermissionError)) and re.fullmatch(r"STAGING_[A-Z_]+", str(exc)) else "STAGING_FAILED"
        parser.exit(1, safe + "\n")


if __name__ == "__main__":
    main()
