# J.DEPLOY.1 Docker Compose Fresh Deployment Readiness Report

## Summary

Docker assets were added for a fresh PostgreSQL-backed deployment. The
validation used a separate Compose project (`jdeploy1`) with host ports
55433 (PostgreSQL), 8100 (API), and 3101 (frontend), so the running Q5
services on 8000/3001 and the formal PostgreSQL database were not touched.

## Existing Docker Asset Audit

Before this phase there was no root Dockerfile, frontend Dockerfile, Compose
file, Docker ignore file, or root environment template. The application used
Alembic and accepted `LLM_GRADER_DATABASE_URL`, while the frontend used the
`API_PROXY_TARGET` rewrite. Those existing conventions are used by the new
files.

## Files Added / Modified

- `Dockerfile.api`
- `Dockerfile.frontend`
- `compose.yaml`
- `.dockerignore`
- `.env.example`
- `pyproject.toml` (runtime `psycopg[binary]` and `uvicorn` dependencies)
- `README.md` (Docker first-run and update instructions)

## Compose Architecture

`postgres` is persistent and health-checked. `migrate` waits for a healthy
PostgreSQL and runs `alembic upgrade head` once. `api` waits for migration
success and exposes `/api/v1/health`; `frontend` waits for a healthy API and
proxies `/api/v1` through the internal `api` service. Worker/model runtime
services are intentionally not required for setup and course administration.

## Validation

- `docker compose ... config`: PASS
- API and frontend images: PASS
- Fresh `up -d`: PASS
- PostgreSQL health: PASS
- Migration service completed successfully through the current head: PASS
- API health: PASS
- Fresh setup status: `{"setup_required":true}`: PASS
- First Admin creation and second-initialize rejection: PASS (HTTP 409)
- Admin login and `/auth/me`: PASS
- Container restart: PASS; setup remained disabled after initialization
- `down` followed by `up` without `-v`: PASS; Admin/setup state persisted
- Formal Q5 API/frontend reachability after cleanup: PASS

The temporary Compose project and volumes were removed with `down -v` after
validation. This did not address or mount the formal Q5 database or artifact
volumes.

## Security and Persistence

Database credentials come from `.env`; no repository secret is required.
Header authentication defaults to false, artifacts use a named persistent
volume, and `.env`, local databases, dumps, model files, and build caches are
ignored. `docker compose down` preserves data; `down -v` is documented as a
destructive development reset.

## Existing Q5 Integrity

Existing Q5 PostgreSQL/SQLite data, artifacts, grading results, runtime, and
OpenWebUI were not changed. No grading jobs or model calls were created.

## Remaining Issues

The repository's existing frontend dependency audit reports vulnerabilities
from the locked Next/npm dependency tree; this phase did not change application
behavior or perform an unrelated dependency upgrade. A production deployment
should set a non-example database password and a strong deployment secret in
the existing authentication configuration.

## Final Decision

Phase J.DEPLOY.1: **COMPLETE**
