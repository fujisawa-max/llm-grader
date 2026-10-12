# Production deployment checklist

- [ ] PostgreSQL backup completed and identified by backup-set ID
- [ ] Artifact backup and manifest SHA verified
- [ ] Database connection configured
- [ ] Artifact root exists, is readable, and is writable
- [ ] Backend and frontend health checks pass
- [ ] Worker is alive; pending/stale jobs reviewed
- [ ] `STUDENT_PORTAL_ENABLED` explicitly confirmed
- [ ] RuntimeManager configuration and port range checked
- [ ] Disk space checked
- [ ] Backend unittest/pytest/Ruff pass
- [ ] Frontend typecheck/lint/build pass
- [ ] Playwright Chromium smoke and E2E pass
- [ ] Backup verification dry-run pass
- [ ] Restore dry-run procedure reviewed
- [ ] OpenWebUI port 3000 and borrowed runtimes were not changed
- [ ] Rollback version and operator are recorded
