import os
from .app import create_app
from ..db import create_session_factory
from ..runtime import RuntimeManagerClient
from ..operations import env_bool

url = os.getenv("LLM_GRADER_DATABASE_URL", "sqlite:///llm_grader_api.db")
_, session_factory = create_session_factory(url)
roots = os.getenv("LLM_GRADER_ALLOWED_ROOTS", ".").split(":")
portal_enabled = env_bool("STUDENT_PORTAL_ENABLED", False)
app = create_app(session_factory, allowed_roots=roots, student_portal_enabled=portal_enabled)
runtime_url = os.getenv("LLM_GRADER_RUNTIME_MANAGER_URL")
if runtime_url:
    app = create_app(session_factory, allowed_roots=roots,
                     runtime_client=RuntimeManagerClient(runtime_url),
                     student_portal_enabled=portal_enabled)
