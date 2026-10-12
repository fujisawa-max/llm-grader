# J.UI.Admin.1b First-run Setup Wizard Report

## Summary

First-run setup is implemented using the existing authentication/session and
password hashing code. Setup is available only while no active administrator
exists. The role is fixed server-side to `admin`; the request cannot select a
role.

## First-run Detection / Setup Status API

`GET /api/v1/setup/status` returns `setup_required` from the backend's active
administrator query. A new `setup_lock` singleton table (migration
`0014_setup_lock`) serializes initialization on PostgreSQL. No setup flag or
password column was added.

## Setup Initialize API

`POST /api/v1/setup/initialize` validates email/password, rejects duplicate
email, stores only the existing scrypt password hash, writes an audit event,
and returns the public user DTO. It never returns a password or accepts a
client role. After creation it returns 409 `SETUP_ALREADY_COMPLETED`.

## Setup UI and Routing

`/setup` provides a two-step explanation/form/completion flow. The current-user
provider checks setup status before routing unauthenticated users. Root and
login route to setup on an uninitialized database; setup redirects to login
after initialization. The completion screen has an explicit login link.

## Fresh DB Browser Smoke

An isolated SQLite database on API 8004 / Frontend 3004 was used. The browser
flow reached `/setup`, created the first administrator, showed completion,
followed the login link, rejected a second initialize request with 409, and
logged in to the admin workspace. Existing PostgreSQL and Q5 services were not
used for this mutation.

## Existing PostgreSQL Validation

The existing PostgreSQL grader already has an administrator. Migration 0014 was
applied; `/api/v1/setup/status` returns `{"setup_required": false}`. The
existing Admin, Q5 Course/Test, submissions, results, and artifacts were not
changed by the wizard. The official Q5 API remains reachable on 8000 and the
Frontend on 3001.

## Authentication Regression

The existing authentication, authorization, password reset, activation, and
ownership behavior was not changed. Targeted setup tests cover first creation,
existing Teacher non-promotion, invalid/duplicate input, fixed admin role, and
second initialization rejection. `ruff` passes for changed Python files;
frontend typecheck and build pass; lint has zero errors and existing warnings.

The setup TestClient suite can remain alive under the repository's known
Python 3.14/TestClient shutdown issue when run as a combined pytest process;
the individual API assertions and fresh-browser smoke completed. This is a
test-runner limitation, not a production setup response failure.

## Q5 / Runtime Integrity

No grading job, OCR call, reconstruction, regrade, model call, model download,
runtime change, OpenWebUI change, or Q5 source/artifact mutation occurred.

## Checklist

- [x] Backend setup status and initialize endpoints
- [x] Server-side admin role and password policy
- [x] Duplicate and second initialization rejection
- [x] Singleton lock migration 0014
- [x] `/setup` form, validation, completion, login link
- [x] Root/login/setup routing
- [x] Fresh DB browser smoke
- [x] Existing PostgreSQL setup disabled
- [x] Q5 data and artifacts unchanged
- [x] No grading/model/runtime operations

## Final Decision

**Phase J.UI.Admin.1b: COMPLETE**
