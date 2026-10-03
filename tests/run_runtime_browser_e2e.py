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
        geometry_test = domain.test(offering.id, name="Geometry Q1 Q2 Q3 fixture", total_points=30)
        question_ids = []
        for number in range(1, 4):
            q = domain.question(geometry_test.id, question_number=str(number), display_label=f"問題{number}",
                                sort_order=number, max_points=10, is_gradable=True,
                                question_text=f"Explain concept {number}.")
            question_ids.append(q.id)
        for kind in ("question_sheet", "model_answer_source"):
            pdf = pymupdf.open()
            page = pdf.new_page(width=600, height=800)
            for number, y in enumerate((100, 350, 600), 1):
                page.insert_text((30, y), f"Question {number}", fontsize=12)
                page.insert_text((30, y + 25), f"Explain concept {number}.", fontsize=12)
                if kind == "model_answer_source":
                    page.insert_text((30, y + 60), f"Source answer {number}.", fontsize=12)
            content = pdf.tobytes()
            pdf.close()
            digest = hashlib.sha256(content).hexdigest()
            source = root / "sources" / geometry_test.id / f"{digest}.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            geometric_material = domain.material(geometry_test.id, material_type=kind, storage_ref=str(source),
                                                original_filename=f"geometry-{kind}.pdf", mime_type="application/pdf",
                                                sha256=digest)
            if kind == "model_answer_source":
                geometry_material_id = geometric_material.id
        session.commit()
        geometry_env = {"GEOMETRY_TEST_ID": geometry_test.id, "GEOMETRY_MATERIAL_ID": geometry_material_id,
                        "GEOMETRY_QUESTION_IDS": json.dumps(question_ids)}
        review_ux_test = domain.test(offering.id, name="Review UX isolated fixture", total_points=30)
        review_ux_question_ids = []
        for number in range(1, 4):
            question = domain.question(review_ux_test.id, question_number=str(number),
                                       display_label=f"問題{number}", sort_order=number, max_points=10,
                                       is_gradable=True, question_text=f"Explain concept {number}.")
            review_ux_question_ids.append(question.id)
        domain.rubric(review_ux_test.id, {"questions": [
            {"question_id": question_id, "max_points": 10,
             "criteria": [{"id": f"existing-{index}", "description": "既存の採点基準", "points": 10}]}
            for index, question_id in enumerate(review_ux_question_ids, 1)
        ]}, source_type="manual")
        review_pdf = pymupdf.open(stream=source.read_bytes(), filetype="pdf")
        review_pdf.new_page(width=600, height=800)
        review_content = review_pdf.tobytes()
        review_pdf.close()
        review_digest = hashlib.sha256(review_content).hexdigest()
        review_source = root / "sources" / review_ux_test.id / f"{review_digest}.pdf"
        review_source.parent.mkdir(parents=True, exist_ok=True)
        review_source.write_bytes(review_content)
        review_ux_material = domain.material(
            review_ux_test.id, material_type="model_answer_source",
            storage_ref=str(review_source), original_filename="review-ux-model-answer.pdf",
            mime_type="application/pdf", sha256=review_digest)
        rubric_pdf = pymupdf.open()
        rubric_page = rubric_pdf.new_page(width=600, height=800)
        rubric_page.insert_textbox(
            pymupdf.Rect(30, 30, 570, 750),
            "Question 1\nExplain concept 1.\nA source answer.\n5 points: identify overfitting.",
            fontsize=12, lineheight=1.5,
        )
        rubric_content = rubric_pdf.tobytes()
        rubric_pdf.close()
        rubric_digest = hashlib.sha256(rubric_content).hexdigest()
        rubric_source = root / "sources" / review_ux_test.id / f"{rubric_digest}.pdf"
        rubric_source.write_bytes(rubric_content)
        rubric_material = domain.material(
            review_ux_test.id, material_type="model_answer_source",
            storage_ref=str(rubric_source), original_filename="unified-rubric-model-answer.pdf",
            mime_type="application/pdf", sha256=rubric_digest)
        geometry_env.update({"REVIEW_UX_TEST_ID": review_ux_test.id,
                             "REVIEW_UX_QUESTION_IDS": json.dumps(review_ux_question_ids),
                             "REVIEW_UX_MATERIAL_ID": review_ux_material.id,
                             "REVIEW_RUBRIC_MATERIAL_ID": rubric_material.id})
        nested_test = domain.test(offering.id, name="Nested review navigation fixture", total_points=20)
        domain.question(nested_test.id, question_number="1", display_label="問題1", sort_order=1,
                        max_points=10, is_gradable=True)
        major = domain.question(nested_test.id, question_number="2", display_label="問題2", sort_order=2,
                                max_points=None, is_gradable=False)
        sub = domain.question(nested_test.id, question_number="2.2", display_label="(2)", sort_order=2,
                              parent_id=major.id, max_points=None, is_gradable=False)
        domain.question(nested_test.id, question_number="2.2.1", display_label="1.", sort_order=1,
                        parent_id=sub.id, max_points=0, is_gradable=True)
        nested = domain.question(nested_test.id, question_number="2.2.2", display_label="2.", sort_order=2,
                                 parent_id=sub.id, max_points=10, is_gradable=True,
                                 question_text="**Recall（再現率）**を $\\frac{TP}{TP+FN}$ で示しなさい。")
        domain.question(nested_test.id, question_number="2.2.3", display_label="3.", sort_order=3,
                        parent_id=sub.id, max_points=0, is_gradable=True)
        third = domain.question(nested_test.id, question_number="3", display_label="問題3", sort_order=3,
                                max_points=None, is_gradable=False)
        third_child = domain.question(nested_test.id, question_number="3.1", display_label="(1)", sort_order=1,
                                      parent_id=third.id, max_points=0, is_gradable=True)
        domain.material(nested_test.id, material_type="model_answer_source", storage_ref=str(review_source),
                        original_filename="review-ux-nested.pdf", mime_type="application/pdf",
                        sha256=review_digest)
        domain.model_answer(nested_test.id, question_id=third_child.id, answer_text="Second-page answer.",
                            provenance_json={"segments": [{"page_index": 1, "bbox": [20, 40, 120, 55]}]})
        geometry_env.update({"NESTED_REVIEW_TEST_ID": nested_test.id,
                             "NESTED_REVIEW_QUESTION_ID": nested.id,
                             "NESTED_REVIEW_PAGE_TWO_QUESTION_ID": third_child.id})
        session.commit()
        ids = test.id, material.id
    return engine, factory, db_url, email, password, ids, geometry_env


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
        engine, factory, db_url, email, password, (test_id, material_id), geometry_env = seed(root)
        with runtime_service(root, hardware_backend="cuda") as (manager, manager_url, _):
            api_port, frontend_port = unused_port(), unused_port()
            api_url = f"http://127.0.0.1:{api_port}"
            env = {**os.environ, **geometry_env, "PYTHONPATH": str(REPO / "src"),
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
                                    "e2e/model-answer-classification-real-isolated.spec.ts",
                                    "e2e/model-answer-geometry-real-isolated.spec.ts",
                                    "e2e/model-answer-review-ux-real-isolated.spec.ts",
                                    "e2e/unified-answer-rubric-review-real.spec.ts",
                                    "e2e/model-answer-nested-navigation-real-isolated.spec.ts", "--workers=1"],
                                   cwd=REPO / "frontend", env=env, check=True)
                    assert any("POST /v1/chat/completions" in line
                               for line in manager.logs("ornith_rubric_draft")["lines"])
                    assert manager.status("ornith_rubric_draft")["pid"] is not None
                    manager.stop("ornith_rubric_draft")
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
