# Runtime deployment

Normal `compose.yaml` starts RuntimeManager alongside the application. API uses
`http://runtime-manager:18000/internal`; neither the manager nor model ports are
published to the host. Models start lazily on `ensure_running`. No model is
downloaded automatically.

## Provisioning and startup

Place an appropriate GGUF in a dedicated model directory and set
`LLM_MODELS_DIR` to that directory. The default container path is
`/models/model.gguf`; override `LLM_GRADER_LLM_MODEL_PATH` and
`LLM_GRADER_LLM_MODEL_ID` as needed. Without a bind directory, the named volume
`llm_models` stores models. Logs use `runtime_manager_state` at `/runtime-state`.
Existing database and artifact volumes are unchanged.

```bash
docker compose build runtime-manager api
docker compose up -d
```

The default CPU binary comes from pinned official llama.cpp image
`ghcr.io/ggml-org/llama.cpp:server-b9265`. `LLAMA_SERVER_IMAGE` can override the
build source. GPU deployment requires a compatible image and explicit device
configuration; the default does not grant GPU or host namespace access.

## Models and profiles

`config/runtime.deployment.json` separates `model_definitions` from purpose
`profiles`. Both `grader` and `ornith_rubric_draft` reference `default_text`.
The latter is the default model-answer semantic classifier profile. Override
`LLM_GRADER_MODEL_ANSWER_CLASSIFIER_PROFILE` if assigning another profile.
Set `LLM_GRADER_RUNTIME_CONFIG_FILE` to mount a deployment-specific JSON file.
Restart the manager after changing configuration; live assignment changes and
model download/install are not implemented.

Each profile runs its own owned process. This configuration does not share a
loaded model automatically. Choose memory/context limits appropriate to the
host. The default text model is not a replacement for OCR or multimodal grading
models: configure their profiles, capabilities, and mmproj explicitly. Existing
schema-version-1 runtime configuration remains supported.

## Health, failure, and logs

Manager health checks configuration and status without loading models. Missing
weights produce `state: unavailable`, `availability: model_missing`, and
`error_code: model_missing` while
API/frontend remain usable. Semantic classification falls back to editable
native extraction. `GET /api/v1/system/runtimes` exposes status to authorized
staff. Model health is checked through RuntimeManager, independently of manager
liveness.

Internal API exposes `/internal/models`, `/internal/profiles`, runtime status,
health, logs, and start/stop/restart/ensure-running. These are management
primitives for future Admin integration, not a public administration API.
Managed stdout/stderr are written to bounded-tail-readable profile log files;
set operational retention/rotation externally. External runtimes are never
stopped by the manager. Shutdown terminates owned processes.

## Network trust

LocalClient permits loopback and exact hosts explicitly listed in
`LLM_GRADER_TRUSTED_RUNTIME_HOSTS`. Compose allows only `runtime-manager` in
addition to loopback. Requests stay on the configured origin; redirects,
userinfo, query strings, and arbitrary hosts are rejected. HTTP proxies are not
used for internal requests. Do not configure untrusted hosts or publicly expose
the unauthenticated internal manager API. No Docker socket is required.

For standalone deployment, run `python -m scoring.runtime.server --config PATH`.
Use host-appropriate model/log paths and `advertise_host: 127.0.0.1` rather than
the Compose service name. Set API's manager URL to
`http://127.0.0.1:18000/internal`. The legacy URL without `/internal` is normalized.

## Isolated validation

```bash
pytest -q tests/test_runtime_deployment.py tests/test_runtime.py
PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers python -m tests.run_runtime_browser_e2e
```

The browser runner creates temporary SQLite/artifact data, starts the real
manager and API, builds the production frontend, and launches a separate managed
OpenAI-compatible stub process. It verifies classification and missing-model
fallback without model inference, OCR, grading, or production data access.
