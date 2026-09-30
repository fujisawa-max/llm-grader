# Containerized Codex Development

`compose.yaml` is the normal application deployment. `compose.dev.yaml` is a separate local development environment. It does not use the production PostgreSQL or artifact volumes, and it never mounts the host Docker socket. The default command starts only `codex-dev`; the optional `database` profile adds a private PostgreSQL 16 service on the development-only bridge network.

## First build and start

From the repository root:

```bash
cp .env.dev.example .env.dev
# Set DEV_POSTGRES_PASSWORD to a locally generated value if you will use the database profile.
./scripts/dev-codex.sh up
```

The image uses OpenAI's `ghcr.io/openai/codex-universal:latest` base, selects Python 3.12 and Node 22, installs this repository's Python development dependencies and frontend lockfile, installs Chromium and its system libraries for Playwright, and installs the pinned Codex CLI. The default CLI version matches the audited host version (`0.159.1`). To update it, change `CODEX_CLI_VERSION` in `.env.dev` and run `./scripts/dev-codex.sh rebuild`; update the base separately by changing `CODEX_BASE_IMAGE` and rebuilding.

Open a shell with:

```bash
./scripts/dev-codex.sh shell
```

The project is mounted at `/opt/llm-scoring`, the same path as on the host. The container user receives the host UID/GID, so new and modified worktree files keep host ownership. Codex state is stored in the `codex_home` named volume at `/home/codex/.codex`; authentication is not copied into the repository or bind-mounted from the host. The first login is interactive:

```bash
codex login --device-auth
codex login status
```

The login and config survive container recreation. Then start the TUI with `codex`, or run a one-shot prompt with `codex exec "Reply with only: OK"`.

Git uses the mounted `.git` working tree. If commits need an identity, set it in the persistent container config (the git config is kept in `codex_home`):

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.invalid"
```

Host SSH directories and Git credential stores are not mounted. For remotes that need credentials, authenticate through a separately approved container-side method or push from the host.

## Development tools

Inside the container, use the image-owned Python environment rather than the host `.venv`:

```bash
python --version
pytest -q tests/test_review_document_text_editing.py
ruff check src tests
cd frontend
npm ci
npm run typecheck
npm run lint
npm run build
npx playwright --version
```

The Playwright Chromium binary is installed under `/opt/playwright-browsers`. `frontend/node_modules`, `.next`, the Python environment, package caches, and Codex home each use Docker named volumes. The entrypoint checks `pyproject.toml` and `package-lock.json` hashes and refreshes dependencies when either changes.

To run the API and frontend from the Codex shell, use separate terminals:

```bash
# Terminal 1
export LLM_GRADER_DATABASE_URL=sqlite:////tmp/llm-grader-dev.sqlite
export LLM_GRADER_ARTIFACT_ROOT=/tmp/llm-grader-dev-artifacts
export LLM_GRADER_ALLOWED_ROOTS=/tmp/llm-grader-dev-artifacts
uvicorn scoring.api.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2
cd /opt/llm-scoring/frontend
API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev -- --hostname 0.0.0.0 --port 3000
```

The dev frontend and API are exposed only on host loopback at `http://127.0.0.1:13000` and `http://127.0.0.1:18080`. Override these ports in `.env.dev` if needed.

Run browser tests from `frontend` after starting the frontend. Since Chromium runs inside `codex-dev`, point it at the container port rather than the host-published port:

```bash
E2E_FRONTEND_URL=http://127.0.0.1:3000 npm run e2e -- e2e/reviews.spec.ts
```

For PostgreSQL-backed development, start the isolated database profile:

```bash
./scripts/dev-codex.sh database
```

From `codex-dev`, connect to `postgres-dev:5432` using `DEV_POSTGRES_DB`, `DEV_POSTGRES_USER`, and `DEV_POSTGRES_PASSWORD` from `.env.dev` (or the explicitly local-only compose defaults). PostgreSQL has no host-published port and uses its own `postgres_dev_data` volume. This database is separate from every service in `compose.yaml`.

## Stop, recreate, and update

```bash
./scripts/dev-codex.sh stop       # stop services; preserve all volumes
./scripts/dev-codex.sh recreate   # recreate only codex-dev; preserve login and dependencies
./scripts/dev-codex.sh rebuild    # pull base image and rebuild the Codex image
```

Do not use `docker compose down -v` unless you intend to delete Codex login/config, development dependencies, and the dev database. This command does not affect `compose.yaml` volumes because the Compose project name is distinct, but it is still destructive to this dev environment.

## Isolation and troubleshooting

- Only `/opt/llm-scoring` is bind-mounted. No host home, SSH directory, Docker socket, or other host path is mounted. Codex authentication lives in a dedicated named volume.
- The Codex config sets `approval_policy = "never"`, `sandbox_mode = "workspace-write"`, and workspace-write network access. The Docker container remains unprivileged and has no Docker daemon access.
- The image prefers IPv4 through its own `/etc/gai.conf`; host networking settings are not changed. To inspect name resolution from the container, run `getent ahosts auth.openai.com` or try `curl -4 -I https://auth.openai.com`.
- If sign-in is missing, run `codex login --device-auth` inside `codex-dev`; check persistence with `codex login status`, recreate the container, and check again.
- If package dependencies changed, the entrypoint notices lockfile changes on the next start. To force a frontend refresh, run `cd frontend && npm ci`; to force Python dependency resolution, run `python -m pip install -e '.[dev]'`.
- If Chromium reports missing libraries, rebuild the image so `playwright install-deps chromium` can run again.
- If a host port is busy, set `DEV_FRONTEND_PORT` or `DEV_API_PORT` in `.env.dev` and recreate the container.

The development stack is intended for source editing, tests, and local application development. It does not start grading workers, model runtimes, or OCR services.
