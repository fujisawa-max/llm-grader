"""Launch the authenticated Q5 API using a protected, explicit DB configuration."""
import argparse
import os
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--database-url-file', type=Path, required=True)
p.add_argument('--port', type=int, default=8000)
p.add_argument('--artifact-root', type=Path, default=Path('/opt/llm-scoring/data/q5-artifacts'))
a = p.parse_args()
url = a.database_url_file.read_text().strip()
if not url.startswith('postgresql'):
    raise SystemExit('PostgreSQL connection required')
root = a.artifact_root.resolve()
if not root.is_dir():
    raise SystemExit('artifact root not found')
os.environ.update(LLM_GRADER_DATABASE_URL=url, LLM_GRADER_ALLOW_HEADER_AUTH='false',
                  STUDENT_PORTAL_ENABLED='false', LLM_GRADER_COOKIE_SECURE='false',
                  LLM_GRADER_ARTIFACT_ROOT=str(root),
                  LLM_GRADER_QUESTION_IMPORT_ROOT=str(root / 'question-imports'),
                  LLM_GRADER_ALLOWED_ROOTS=str(root))
os.execv('/opt/llm-scoring/.venv/bin/uvicorn', ['uvicorn', 'scoring.api.server:app',
          '--host', '0.0.0.0', '--port', str(a.port)])
