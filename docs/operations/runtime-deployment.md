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

## Hardware and GPU passthrough

The standard x86-64 runtime image contains isolated CPU, CUDA, and Vulkan binary
sets pinned to llama.cpp b9265. CPU/CUDA use official images; Vulkan is built from
the same tag on Ubuntu 24.04 to avoid mixing newer glibc requirements. This is
larger and slower to build than the former CPU image, but a single deployed image
can select a backend at startup without rebuilding for the host. No host GPU is
inspected during Docker build. CUDA runtime libraries are included; driver
libraries must be injected by NVIDIA Toolkit. ROCm is optional: install a
compatible ROCm binary and dependencies in a custom image and set
`LLM_GRADER_ROCM_BINARY` to its wrapper path. Standard AMD support uses Vulkan.

### NVIDIA

Install the host driver and NVIDIA Container Toolkit following vendor guidance.
Confirm `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`
works. This does not imply GPUs are exposed to every container. Use the host
helper below or explicitly merge `compose.runtime-nvidia.yaml`. It reserves all
visible GPUs and does not modify Docker daemon configuration. A6000 and other
names are not hardcoded; native device enumeration reports names and memory.

### AMD / Ryzen

The host must provide readable/writable DRM render devices under `/dev/dri`.
The helper passes this GPU directory and its numeric render group to the
non-root runtime process. `/dev/kfd` and its group are passed if present for
optional ROCm. No privileged mode, extra capabilities, host namespaces, or Docker
socket are required. ROCm compatibility is device/driver dependent; Vulkan is
used when ROCm cannot enumerate usable devices. Vulkan software renderers such
as llvmpipe are not accepted as GPUs. UMA memory reported by a driver is not a
guarantee of dedicated VRAM or safe model residency.

### CPU and automatic host exposure

Plain `docker compose up -d --build` intentionally remains CPU-host-safe. Compose
has no optional GPU reservation or optional missing device mapping. An
unconditional NVIDIA reservation fails without Toolkit; an unconditional AMD
device mapping fails without the device. Environment hints inside a container
cannot grant devices that Docker has not exposed.

```bash
# Preview only; no containers are started and no files/configuration are changed:
python3 scripts/runtime-compose.py --dry-run
# Select host GPU exposure, then run normal Compose:
python3 scripts/runtime-compose.py
# Same selected configuration for later operations:
python3 scripts/runtime-compose.py -- logs runtime-manager
```

The helper is a host deployment tool and requires Python 3 and Docker Compose.
It gives NVIDIA priority when its device nodes and Toolkit runtime are detected.
Otherwise it checks DRM sysfs PCI vendor IDs for AMD (0x1002), rather than
assuming every render node is AMD. It uses these facts to choose
explicit override files. With no suitable GPU configuration it runs the base
Compose. It does not reset databases or change daemon settings. Use the helper
consistently for later recreate/up operations; plain Compose may remove GPU
exposure on a recreate. No override is written to `.env` automatically.

For explicit NVIDIA deployment:
`docker compose -f compose.yaml -f compose.runtime-nvidia.yaml up -d --build`.
For AMD, merge `compose.runtime-amd.yaml` and set `GPU_RENDER_GID` to the render
device group; merge `compose.runtime-rocm.yaml` and set `GPU_KFD_GID` if using
ROCm. On unusual CDI-only or mixed DRM-group hosts, configure an explicit
deployment override rather than guessing. Existing deployment credentials are
still required; “clone and start” does not provision credentials or models.

### Detection, override, and diagnostics

At Manager startup each configured binary runs `--list-devices` in an isolated,
time-limited subprocess. GPU selection requires successful enumeration of actual
GPU devices, not merely `/dev/nvidia*`, `/dev/kfd`, environment variables, or
`nvidia-smi`. CPU binary load is checked separately. Backend library failures and
permission failures are recorded in `/internal/hardware` diagnostics and manager
logs. CPU-only hosts may log expected unavailable GPU probes.

`LLM_GRADER_RUNTIME_BACKEND=auto` selects CUDA → ROCm → Vulkan → CPU. Explicit
`cuda`, `rocm`, `vulkan`, or `cpu` is respected. An unavailable explicit backend
reports `backend_unavailable` without killing Manager/API. Per-profile `backend`
can override the default. Model assignment remains independent of hardware.

`gpu_layers: "auto"` maps to `-ngl auto` on the pinned GPU binaries (native VRAM
fitting), and `-ngl 0` on CPU. Explicit integer layer counts remain unchanged.
Multi-GPU scheduling uses llama.cpp defaults; use profile `additional_args` for
`--split-mode`, `--tensor-split`, or `--main-gpu`. Model size alone does not cause
rejection. Actual GPU OOM/backend failures during startup in auto mode retry the
CPU binary once and retain the fallback reason; explicit GPU selections do not
silently switch. CPU startup can still fail due to insufficient RAM or a bad
model, and is reported rather than endlessly retried.

`GET /api/v1/system/runtimes` now includes `hardware`: selected/requested backend,
GPU count/names, reported total/free memory per device, layers, selected binary,
and fallback reason. Internal hardware diagnostics include all backend probes
and their reasons. Existing readiness and model identity checks still apply.

### Troubleshooting

- GPU invisible: verify host test, exposure override, and container device groups.
- CUDA load failure: check driver compatibility with the pinned CUDA 12.8 runtime;
  inspect backend diagnostics and runtime logs. Device nodes alone are insufficient.
- AMD Vulkan unavailable: check render-node permissions and host driver support;
  no GPU is selected if native enumeration fails.
- ROCm unavailable: standard image has no ROCm distribution. Supply a compatible
  custom binary/dependencies, or use standard Vulkan.
- OOM: reduce context/batch/layers or choose a smaller model; auto may fit fewer
  layers or retry CPU, which itself needs sufficient host RAM.
- Model missing: place weights at the configured path; other services remain up.

The current development environment has no Docker/GPU access. Image build and
real NVIDIA/AMD device loading require validation on the target host; mocked
backend tests are not proof of GPU offload.

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
pytest -q tests/test_runtime_hardware.py tests/test_runtime_deployment.py tests/test_runtime.py
PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers python -m tests.run_runtime_browser_e2e
```

The browser runner creates temporary SQLite/artifact data, starts the real
manager and API, builds the production frontend, and launches a separate managed
OpenAI-compatible stub process. It verifies classification and missing-model
fallback without model inference, OCR, grading, or production data access.

## Persistent semantic-classification runtime

The classifier calls `ensure_running`, performs inference, and returns its result.
It never stops the model in a per-request `finally`. RuntimeManager retains the
managed process for subsequent requests. Explicit internal stop/restart and
Manager shutdown remain available. This release keeps the model resident until
an explicit stop: idle eviction is deferred until request leases/in-flight usage
can be tracked safely. Do not rely on automatic idle VRAM reclamation.

Timeout budgets for the synchronous classification route are now explicit:

| Path | Previous | Current default / configuration |
| --- | --- | --- |
| Browser fetch | No application timeout | Unchanged; intermediary timeouts still apply |
| Next.js rewrite → API | 30 seconds | 900 seconds; build-time `API_PROXY_TIMEOUT_MS` |
| API → Manager status/stop | 120 seconds | 120 seconds; `LLM_GRADER_RUNTIME_MANAGER_TIMEOUT_SECONDS` |
| API → Manager ensure/start/restart | 120 seconds | 330 seconds; `LLM_GRADER_RUNTIME_START_TIMEOUT_SECONDS` |
| Manager model startup | 300 seconds | Profile `startup_timeout_seconds` |
| API → model inference | 300 seconds | Profile `request_timeout_seconds` |

The frontend proxy budget covers cold loading plus inference; it is not an idle
shutdown policy. Rebuild frontend after changing the build-time proxy setting.
If increasing profile startup limits (including possible GPU→CPU retries), also
adjust Manager-client startup timeout. The route processes draft entries
sequentially, so a large draft can exceed the total proxy budget even though each
inference fits its own budget. Long-running background classification jobs are
future work; no infinite timeout is introduced here.

Only `ornith_rubric_draft` has a standard output budget of 512 tokens. Larger
segment lists may require a profile override; truncated/invalid output continues
to fall back without losing candidate text. Grader generation defaults are
unchanged. `chat_template_kwargs.enable_thinking=false` remains the request-level
non-thinking setting and is now also explicit in the classification profile.
Its effect depends on the template embedded in the deployed GGUF; verify on the
real model rather than assuming every quantization honors it.

### NVIDIA follow-up validation

1. Run semantic classification with synthetic data, not formal Q5.
2. Confirm the `/classify` POST returns 200 and the UI shows classification.
3. Through the private Manager API, check `/internal/health`: profile state should
   be `ready` (the existing enum for a running, healthy process). Record its PID.
4. Classify again: PID stays the same and runtime logs show no model reload.
5. Check `nvidia-smi`: model VRAM remains allocated after requests complete.
6. Explicitly stop the profile via the internal Manager API when testing is done;
   verify state becomes `stopped`. Manager shutdown also stops owned processes.

A disconnected health client no longer triggers a second 500 write after a
BrokenPipe/connection reset. Actual Manager errors still produce error responses.

### Source-aware数式変換（J.UI.9d）

ModelAnswer Reviewの「数式をLaTeX化」は、原文segmentと現在の本文を一意に
照合できる数式候補について、保存済みPDFの局所bboxを6pt拡張し、2倍解像度の
PNGとして `math_ocr` profileへ渡します。ページ全体は送信せず、1要求8領域まで、
各cropはページ面積の35%以下に制限します。原文と対応しない教師編集本文は
既存のtext-only normalizationを利用します。変換は自動適用されません。

通常runtime設定には既存Uni-MuMER用の `math_ocr` purposeを定義しています。
既存モデルと対応mmprojをmodel storageへ配置し、必要に応じて以下を設定します。
モデルのdownloadや別モデルの追加は行いません。

- `LLM_GRADER_MATH_MODEL_ID`（既定 `unimumer-q4`）
- `LLM_GRADER_MATH_MODEL_PATH`（既定 `/models/math-ocr.gguf`）
- `LLM_GRADER_MATH_MMPROJ_PATH`（既定 `/models/math-ocr-mmproj.gguf`）

初回はlazy起動、以降はPIDを再利用します。要求後に停止しません。
モデルが未配置でも他サービスは起動し、数式変換要求だけがエラーになります。
OCR結果は必ずcrop画像と照合してください。数値の訂正・式の補完は行いません。
適用は編集中の下書きだけを更新し、下書き保存と正式登録は別操作です。

実NVIDIA環境では、停止状態から変換→crop/KaTeX preview→適用→下書き保存→
reload→正式登録を確認し、2回目の変換でsystem runtime APIのPIDとstarted_atが
変わらないことを確認してください。正式Q5ではなく合成PDFを使用します。

### Visual math grouping（J.UI.9d-fix1）

native PDFの行境界はOCR領域の境界として扱いません。同一ページの縦overlap・
中心距離・水平gap・分数の上下関係を使ってvisual expression bandを作ります。
連続した等号列は1 cropとし、別の式の見出し・prose・別ページは結合しません。
重複する数値は完全な出現列、または原文の一意な前後anchorで対応付けます。
教師編集によって対応が曖昧な断片は置換しません。

geometryの弱い隣接だけが残る場合に限り、既存Ricohへbounded union cropとsource
segment IDを渡します。Ricohの役割は所属IDの確認だけです。既知IDの完全なpartition、
confidence、page・geometry neighborhoodを検証し、bboxはsource bboxから算出します。
未知ID・不足・重複・低信頼・不正JSONの場合はOCRを進めず、crop付き診断を返します。
正常な広い1式（Accuracy等）にはRicohを呼びません。

- 既定grouping profile: `ocr`（APIの `LLM_GRADER_MATH_GROUPING_PROFILE` で変更可能）
- Ricoh model設定: `LLM_GRADER_OCR_MODEL_ID` / `LLM_GRADER_OCR_MODEL_PATH` / `LLM_GRADER_OCR_MMPROJ_PATH`
- 同じruntime configに既存の`ocr` profileがある場合は再利用します。
- default deploymentは既存Ricohモデル用のlazy profileを定義しています。downloadは行いません。
- bbox padding 6pt、1要求8領域、ページ35%、4百万pixelの制限を維持します。
- grouping計算・vision promptのサイズを制限するため、aligned math segmentは128個までです。

Uni-MuMERのcontent/final/answer/reasoning_content/reasoning選択は共有parserを利用します。
合法な外側のMarkdown fence、`$`/`$$`、`\(`/`\[`区切りだけを除去します。数値・変数や
数学内容は書き換えません。原文の数値が変更・消失した場合は拒否し、nativeにない
追加数値はPDF照合warningとします。OCR自体の正確さは教師のcrop確認が必要です。

失敗時もstaff/owner認可された同じproposal responseにcrop・bbox・source IDs・
grouping method・source field・raw OCR・reason codeを返します。Applyはdisabledです。
raw応答は「OCR診断」へ折りたたみ、image bytesをlogsや保存draftへ残しません。
logsは領域数、method、寸法、crop SHA、field、応答長、validation/reasonを記録します。

**実GPU受入確認:** source-awareボタンを明示的に押し、ブラウザNetworkで返る
`grouping_summary`と各`math_regions`を確認してください。Precisionの全7断片が1つの
cropになり、分子・分母・分数線・等号列が画像内に含まれることを先に確認します。
実Uni-MuMERのraw OCRとfield、拒否reason、KaTeX previewを確認し、成功時のみApplyします。
2回目でmath_ocr（必要だった場合はocrも）のPID/started_atが変わらないことを確認します。
実サンプル・実モデルでこの受入を通すまでは、stub PASSだけでCOMPLETEとしません。
