"""Run isolated production-frontend E2E through real API/Manager/managed stub.

Usage: python -m tests.run_runtime_browser_e2e
Requires npm dependencies and installed Playwright Chromium. No real model call.
"""

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import pymupdf
from sqlalchemy import func, select

from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import GradingJob
from scoring.domain import DomainService
from tests.runtime_fixture import REPO, runtime_service, stop_process, unused_port, wait_http


def seed(root):
    db_url = f"sqlite:///{root / 'isolated.sqlite'}"
    engine, factory = create_session_factory(db_url)
    init_database(engine)
    password = secrets.token_urlsafe(24)
    email = "runtime-fixture@example.invalid"
    with factory() as session:
        domain = DomainService(session)
        admin = domain.user(display_name="Isolated runtime teacher", email=email, role="admin",
                            password_hash=hash_password(password), is_active=True)
        course = domain.course(admin.id, name="Isolated runtime course")
        offering = domain.offering(course.id, academic_year=2026, term="fall")
        test = domain.test(offering.id, name="Runtime classification fixture", total_points=10)
        domain.question(test.id, question_number="1", display_label="問題1", sort_order=1,
                        max_points=10, is_gradable=True, question_text="Describe the idea of overfitting.")
        pdf = pymupdf.open()
        page = pdf.new_page(width=600, height=800)
        text = ("Question 1\nExplain overfitting and state its effect.\n"
                "The model memorizes the training examples and generalizes poorly.\n"
                "5 points: identify overfitting.\nAlternative: describe high variance.")
        page.insert_textbox(pymupdf.Rect(30, 30, 570, 750), text, fontsize=12, lineheight=1.5)
        content = pdf.tobytes()
        pdf.close()
        digest = hashlib.sha256(content).hexdigest()
        source = root / "sources" / test.id / f"{digest}.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(content)
        material = domain.material(test.id, material_type="model_answer_source", storage_ref=str(source),
                                   original_filename="semantic-model-answer.pdf", mime_type="application/pdf",
                                   sha256=digest)
        session.commit()
        ids = test.id, material.id
    return engine, factory, db_url, email, password, ids


def json_request(opener, url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="llm-grader-runtime-e2e-") as temporary:
        root = Path(temporary)
        engine, factory, db_url, email, password, (test_id, material_id) = seed(root)
        with runtime_service(root, hardware_backend="cuda") as (manager, manager_url, _):
            api_port, frontend_port = unused_port(), unused_port()
            api_url = f"http://127.0.0.1:{api_port}"
            env = {**os.environ, "PYTHONPATH": str(REPO / "src"),
                   "LLM_GRADER_DATABASE_URL": db_url,
                   "LLM_GRADER_ARTIFACT_ROOT": str(root),
                   "LLM_GRADER_QUESTION_IMPORT_ROOT": str(root / "question-imports"),
                   "LLM_GRADER_ALLOWED_ROOTS": str(root),
                   "LLM_GRADER_ALLOW_HEADER_AUTH": "false", "LLM_GRADER_COOKIE_SECURE": "false",
                   "LLM_GRADER_RUNTIME_MANAGER_URL": manager_url,
                   "LLM_GRADER_MODEL_ANSWER_CLASSIFIER_PROFILE": "ornith_rubric_draft",
                   "LLM_GRADER_TRUSTED_RUNTIME_HOSTS": "127.0.0.2",
                   "API_PROXY_TARGET": api_url,
                   "E2E_FRONTEND_URL": f"http://127.0.0.1:{frontend_port}",
                   "MODEL_ANSWER_CLASSIFICATION_TEST_ID": test_id,
                   "MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID": material_id,
                   "MODEL_ANSWER_CLASSIFICATION_EMAIL": email,
                   "MODEL_ANSWER_CLASSIFICATION_PASSWORD": password, "RUNTIME_MANAGER_E2E": "1"}
            api = frontend = None
            try:
                with (root / "api.log").open("w") as api_log, (root / "frontend.log").open("w") as frontend_log:
                    import sys
                    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "scoring.api.server:app",
                                            "--host", "127.0.0.1", "--port", str(api_port)],
                                           cwd=REPO, env=env, stdout=api_log, stderr=subprocess.STDOUT)
                    wait_http(api_url + "/api/v1/health", api)
                    if not args.skip_build:
                        subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env=env, check=True)
                    frontend = subprocess.Popen(["npm", "run", "start", "--", "--hostname", "127.0.0.1",
                                                 "--port", str(frontend_port)], cwd=REPO / "frontend",
                                                env=env, stdout=frontend_log, stderr=subprocess.STDOUT,
                                                start_new_session=True)
                    wait_http(env["E2E_FRONTEND_URL"] + "/login", frontend, timeout=60)
                    subprocess.run(["npm", "run", "e2e", "--",
                                    "e2e/runtime-classification-real-isolated.spec.ts",
                                    "e2e/model-answer-classification-real-isolated.spec.ts", "--workers=1"],
                                   cwd=REPO / "frontend", env=env, check=True)
                    assert any("POST /v1/chat/completions" in line
                               for line in manager.logs("ornith_rubric_draft")["lines"])
                    assert manager.status("ornith_rubric_draft")["pid"] is None
                    # Keep API/Frontend alive with no model, and check graceful fallback via real API.
                    (root / "synthetic.gguf").unlink()
                    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                    json_request(opener, api_url + "/api/v1/auth/login", {"email": email, "password": password})
                    statuses = json_request(opener, api_url + "/api/v1/system/runtimes")
                    assert all(row["availability"] == "model_missing" for row in statuses)
                    draft = json_request(opener, f"{api_url}/api/v1/tests/{test_id}/model-answer-imports", {"material_id": material_id})
                    classified = json_request(opener, f"{api_url}/api/v1/model-answer-import-drafts/{draft['id']}/classify",
                                              {"expected_revision": draft["revision"]})
                    assert classified["entries"][0]["answer_text"] == draft["entries"][0]["answer_text"]
                    assert classified["entries"][0]["semantic_classification"]["reason"] == "classification_failed"
                    json_request(opener, api_url + "/api/v1/health")
                    with factory() as session:
                        assert session.scalar(select(func.count()).select_from(GradingJob)) == 0
                    print("PASS: normal API bootstrap / real Manager / managed stub / browser / model-missing fallback; grading jobs 0")
            except Exception:
                for name in ["api.log", "frontend.log", "runtime-manager.log", "ornith_rubric_draft.log"]:
                    path = root / name
                    if path.exists():
                        print(f"{name}:\n{path.read_text()[-5000:]}")
                raise
            finally:
                if frontend:
                    # npm starts Next as a child: terminate only this isolated process group.
                    import signal
                    if frontend.poll() is None:
                        os.killpg(frontend.pid, signal.SIGTERM)
                    stop_process(frontend)
                if api:
                    stop_process(api)
                engine.dispose()


if __name__ == "__main__":
    main()
