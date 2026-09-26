"""Start an isolated empty SQLite API for the browser setup smoke test."""
import os
from scoring.db import create_session_factory, init_database

url = os.environ["SETUP_SMOKE_DATABASE_URL"]
engine, _ = create_session_factory(url)
init_database(engine)
os.environ.update(LLM_GRADER_DATABASE_URL=url, LLM_GRADER_ALLOW_HEADER_AUTH="false",
                  LLM_GRADER_COOKIE_SECURE="false", STUDENT_PORTAL_ENABLED="false")
os.execv("/opt/llm-scoring/.venv/bin/uvicorn", ["uvicorn", "scoring.api.server:app", "--host", "0.0.0.0", "--port", os.getenv("SETUP_SMOKE_PORT", "8004")])
