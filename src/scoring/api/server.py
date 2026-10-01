import os
from .app import create_app
from ..db import create_session_factory
from ..runtime import RuntimeManagerClient
from ..operations import env_bool

url = os.getenv("LLM_GRADER_DATABASE_URL", "sqlite:///llm_grader_api.db")
_, session_factory = create_session_factory(url)
roots = os.getenv("LLM_GRADER_ALLOWED_ROOTS", ".").split(":")
portal_enabled = env_bool("STUDENT_PORTAL_ENABLED", False)
runtime_url = os.getenv("LLM_GRADER_RUNTIME_MANAGER_URL")
app = create_app(session_factory, allowed_roots=roots,
                 runtime_client=RuntimeManagerClient(
                     runtime_url, timeout=float(os.getenv("LLM_GRADER_RUNTIME_MANAGER_TIMEOUT_SECONDS", "120")),
                     startup_timeout=float(os.getenv("LLM_GRADER_RUNTIME_START_TIMEOUT_SECONDS", "330")),
                 ) if runtime_url else None,
                 student_portal_enabled=portal_enabled)
