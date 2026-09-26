# Incident response

Preserve append-only history first. Do not delete grading results,
reconstructions, teacher decisions, artifacts, or database rows while
diagnosing an incident.

| Incident | Immediate action | Recovery boundary |
|---|---|---|
| Backend will not start | Check PostgreSQL, environment file, port 8000, and logs | Fix configuration, then run health checks |
| Worker stopped | Inspect running/stale jobs and worker logs | Reuse sealed snapshots; explicitly recover stale jobs |
| Grading job failed | Keep failed history and stop automatic retries | Teacher review and approved regrade only |
| Model runtime failed | Inspect RuntimeManager and owned runtime state | Stop/restart owned runtime only; never stop borrowed runtime |
| Artifact missing or SHA mismatch | Stop grading and flag the incident | Verify against backup; never silently regenerate |
| Disk full | Stop ingestion/grading | Preserve artifacts, rotate approved logs/temp files, expand storage |
| PostgreSQL unavailable | Stop writes and worker retries | Restore DB service, then resume deterministically |

Record the relevant submission, question, job, regrade, teacher-decision, and
publication event IDs. Keep secrets and raw prompts out of the incident log.
