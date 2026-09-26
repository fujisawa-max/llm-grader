import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from scoring.api.app import create_app
from scoring.db.database import Base
from scoring.operations import env_bool, student_portal_enabled


def test_environment_boolean_parsing():
    assert env_bool("FLAG", False, environ={"FLAG": "true"}) is True
    assert env_bool("FLAG", True, environ={"FLAG": "off"}) is False
    assert env_bool("FLAG", True, environ={"FLAG": "unexpected"}) is True
    assert student_portal_enabled(False) is False


def test_student_portal_disabled_blocks_all_student_routes(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = create_app(factory, allowed_roots=[tmp_path], student_portal_enabled=False)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/student/results/not-a-real-submission",
            headers={"X-Role": "student", "X-Student-ID": "student-1"},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STUDENT_PORTAL_DISABLED"


def test_health_reports_operational_counters_and_portal_state(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    old_root = os.environ.get("LLM_GRADER_ARTIFACT_ROOT")
    os.environ["LLM_GRADER_ARTIFACT_ROOT"] = str(tmp_path)
    try:
        app = create_app(factory, allowed_roots=[tmp_path], student_portal_enabled=False)
        with TestClient(app) as client:
            payload = client.get("/api/v1/health").json()
    finally:
        if old_root is None:
            os.environ.pop("LLM_GRADER_ARTIFACT_ROOT", None)
        else:
            os.environ["LLM_GRADER_ARTIFACT_ROOT"] = old_root
    assert payload["status"] == "ok"
    assert payload["student_portal_enabled"] is False
    assert payload["jobs"] == {"pending": 0, "failed": 0, "review_required": 0}
