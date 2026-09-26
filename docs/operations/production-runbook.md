# Production runbook

This runbook describes the supported Teacher/Admin operation of the grading
system. It does not change grading, reconstruction, or append-only history
semantics. Run commands as the deployment user and substitute values from the
deployment environment; never put credentials in this document.

## Roles and portal mode

`ADMIN` and `TEACHER` are staff roles. Both are allowed through the service
authorization boundary; Admin is additionally responsible for account,
diagnostic, backup, and recovery operations. Teachers manage tests, imports,
review, adjudication, regrade approval, finalization, and PDF/CSV exports.

Production defaults to `STUDENT_PORTAL_ENABLED=false`. In this mode the
student result page, result API, student PDF, and student visual asset routes
return `STUDENT_PORTAL_DISABLED`. Teacher grading, finalization, PDF, and CSV
routes remain available. Publishing may still record an internal immutable
final snapshot, but it is not a student web publication. Set the flag to
`true` only after reviewing the I.4 authorization tests. The flag is not an
authorization substitute.

## Configuration

Use [production.example.env](../../config/production.example.env) as a
non-secret inventory:

- PostgreSQL URL and backup destination
- artifact/runs roots and CORS origins
- API port `8000`, frontend port `3001`
- worker settings and PID file
- RuntimeManager URL and its dynamic `18080–18179` port range
- model/runtime configuration and log level
- `STUDENT_PORTAL_ENABLED`

Keep passwords, tokens, model credentials, and private keys in the deployment
secret store.

## Startup

Start in this order and verify each health check before continuing:

1. Confirm PostgreSQL is reachable.
2. Start FastAPI on `8000`:
   `.venv/bin/uvicorn scoring.api.server:app --host 0.0.0.0 --port 8000`
3. Start the grading worker using the deployment's managed worker command.
4. Start the Next.js frontend on `3001`:
   `npm run start -- --hostname 0.0.0.0 --port 3001`
5. Start an optional RuntimeManager/model runtime only when a job requires it.

OpenWebUI on port `3000` is external to this system. Do not stop or reconfigure
it. Borrowed runtimes are never stopped by the grading worker.

## Shutdown

Stop in reverse order: frontend, worker, owned model runtime, then backend.
Leave PostgreSQL and OpenWebUI running when they are shared services. Stop only
owned runtimes and confirm no owned worker or llama-server process remains.

## Health and monitoring

The read-only API endpoint is `GET /api/v1/health`. It reports database
reachability, portal mode, pending/failed/review-required job counts, and the
configured artifact root. Run:

```bash
PYTHONPATH=/opt/llm-scoring .venv/bin/python scripts/health_check.py \
  --api-url http://127.0.0.1:8000/api/v1 \
  --frontend-url http://127.0.0.1:3001 \
  --artifact-root /srv/llm-grader/artifacts \
  --worker-pid-file /run/llm-grader/worker.pid
```

Monitor API/frontend reachability, PostgreSQL, worker liveness, artifact
read/write access, pending and failed/review-required jobs, RuntimeManager
state, and free disk space. Logs must carry `submission_id`, `question_id`,
`grading_job_id`, `regrade_request_id`, `teacher_decision_id`, and
finalization/publication event IDs. Do not log secrets, full prompts,
credentials, or unnecessary student content. Keep application and worker logs
for the configured `LLM_GRADER_LOG_RETENTION_DAYS` (30 days is the production
example), compress older logs according to host policy, retain audit events in
the append-only database, and never automatically delete artifacts.

## Worker recovery

Use the existing stale-job/restart recovery operation after confirming the
failure. A sealed grading snapshot is reused; do not create a second job for
the same snapshot and do not run an infinite retry loop. Failed or review-
required jobs remain in history and require a teacher-approved regrade. Use the
health command and teacher review queue as read-only diagnostics. Recovery may
requeue only an explicitly identified stale job through the existing worker
operation.

## Release and rollback

1. Take a DB and artifact backup set.
2. Stop the worker.
3. Deploy the version and run migrations, if any.
4. Run backend tests, frontend typecheck/lint/build, health checks, and browser
   smoke/E2E.
5. Resume the worker and verify no duplicate jobs.

For rollback, stop the worker, restore the previous application version (not
the database), rerun health/read-only audits, then resume. Restore the database
or artifacts only through [backup-restore.md](backup-restore.md).

## Playwright rootless environment

I.5b verified Chromium `134.0.6998.35`. If root installation is unavailable,
obtain approved cached Ubuntu DEBs for `libnss3`, `libnspr4`, and
`libasound2t64`, extract them into `/tmp/i5-browser-libs`, and use:

```bash
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/path/to/chrome
export I5_BROWSER_LIB_DIR=/tmp/i5-browser-libs
scripts/playwright_browser_env.sh -- npx playwright test --project=chromium
```

The helper never runs `apt` and never downloads browser binaries. With the
optional Playwright ffmpeg package absent, video capture remains off while
traces and failure screenshots stay enabled. Run a launch/data-page smoke test
before the full suite. Clean up Chromium, worker, and owned llama-server
processes afterward.

## Production checklist

See [deployment-checklist.md](deployment-checklist.md) before every release.
# First run

On a new database with no active administrator, open the service in a browser.
The application redirects to `/setup`; create the first administrator there,
then follow the link to `/login`. The backend checks administrator existence and
disables the endpoint after the first successful creation. The existing CLI
bootstrap remains available for sealed or non-browser deployments.
