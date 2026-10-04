from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from scoring.api import create_app
from scoring.auth import SESSION_COOKIE, authorize_domain_path, create_session
from scoring.db import create_session_factory, init_database
from scoring.db.models import User
from scoring.domain import DomainService


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GRADER_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("LLM_GRADER_ALLOW_HEADER_AUTH", "false")
    engine, factory = create_session_factory(f"sqlite:///{tmp_path / 'isolated.db'}")
    init_database(engine)
    tokens, users = {}, {}
    with factory() as session:
        for role in ("teacher", "admin", "student"):
            user = User(display_name=role, email=f"{role}@example.test", role=role, is_active=True)
            session.add(user)
            session.flush()
            tokens[role] = create_session(session, user)
            users[role] = user.id
        domain = DomainService(session)
        course = domain.course(users["teacher"], name="isolated")
        offering = domain.offering(course.id, academic_year=2026, term="fall")
        exam = domain.test(offering.id, name="isolated")
        test_id = exam.id
        session.commit()
    app = create_app(factory, allowed_roots=[tmp_path], model_answer_classifier=SimpleNamespace(manager=object(), profile_id="ornith_rubric_draft"))
    yield app, factory, tokens, users, test_id
    engine.dispose()


def test_original_domain_guard_rejects_generic_teacher_path(context):
    _, factory, _, users, _ = context
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/text-tools/latex-normalize", "headers": [], "query_string": b""})
    with factory() as session:
        with pytest.raises(HTTPException) as error:
            authorize_domain_path(request, session, session.get(User, users["teacher"]))
    assert error.value.status_code == 404
    assert error.value.detail["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("role", ["teacher", "admin"])
def test_staff_generic_handler_does_not_use_domain_path(context, role, caplog):
    app, _, tokens, _, _ = context
    with patch("scoring.api.app.authorize_domain_path", side_effect=AssertionError("generic tool called domain auth")), patch("scoring.api.text_tools.LatexNormalizer.normalize", return_value={"status": "no_change", "normalized_text": "TP"}) as normalize:
        caplog.set_level("INFO", logger="scoring.api.text_tools")
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE, tokens[role])
        response = client.post("/api/v1/text-tools/latex-normalize", json={"text": "TP"})
    assert response.status_code == 200
    normalize.assert_called_once()
    assert "latex API request" in caplog.text
    assert "/api/v1/text-tools/latex-normalize" in app.openapi()["paths"]


@pytest.mark.parametrize("role,status", [("student", 403), (None, 401)])
def test_generic_tool_rejects_non_staff_without_inference(context, role, status):
    app, _, tokens, _, _ = context
    client = TestClient(app)
    if role:
        client.cookies.set(SESSION_COOKIE, tokens[role])
    with patch("scoring.api.text_tools.LatexNormalizer.normalize") as normalize:
        response = client.post("/api/v1/text-tools/latex-normalize", json={"text": "TP"})
    assert response.status_code == status
    normalize.assert_not_called()


def test_model_answer_import_preserves_domain_authorization(context):
    app, _, tokens, _, test_id = context
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, tokens["teacher"])
    with patch("scoring.api.app.authorize_domain_path", wraps=authorize_domain_path) as guard:
        response = client.get(f"/api/v1/tests/{test_id}/model-answer-import-drafts")
    assert response.status_code == 200
    assert guard.call_count == 1


def test_teacher_session_reaches_real_app_route(context):
    app, _, tokens, _, _ = context
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, tokens["teacher"])
    with patch("scoring.api.text_tools.LatexNormalizer.normalize", return_value={"status": "no_change", "normalized_text": "TP"}) as normalize:
        response = client.post("/api/v1/text-tools/latex-normalize", json={"text": "TP"})
    assert response.status_code == 200, response.json()
    normalize.assert_called_once()


@pytest.mark.parametrize("role,status", [("student", 403), (None, 401)])
def test_source_math_tool_requires_staff(context, role, status):
    app, _, tokens, _, _ = context
    client = TestClient(app)
    if role:
        client.cookies.set(SESSION_COOKIE, tokens[role])
    with patch("scoring.source_math_ocr.SourceMathOCR.propose") as propose:
        response = client.post("/api/v1/model-answer-import-drafts/missing/entries/missing/math-ocr",
                               json={"text": "x=1", "expected_revision": 1})
    assert response.status_code == status
    propose.assert_not_called()


def test_source_math_tool_rejects_arbitrary_path(context):
    app, _, tokens, _, _ = context
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, tokens["admin"])
    response = client.post("/api/v1/model-answer-import-drafts/missing/entries/missing/math-ocr",
                           json={"text": "x=1", "expected_revision": 1, "path": "/etc/passwd"})
    assert response.status_code == 422
