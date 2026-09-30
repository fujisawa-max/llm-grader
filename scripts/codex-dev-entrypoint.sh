#!/usr/bin/env bash
set -euo pipefail

project_root=/opt/llm-scoring
codex_config_template=/usr/local/share/codex-dev/config.toml

mkdir -p "$CODEX_HOME"
if [[ ! -f "$CODEX_HOME/config.toml" ]]; then
  cp "$codex_config_template" "$CODEX_HOME/config.toml"
fi

cd "$project_root"
python_lock_hash="$(sha256sum pyproject.toml | cut -d ' ' -f 1)"
python_lock_marker="$VIRTUAL_ENV/.codex-project-pyproject.sha256"
if [[ ! -r "$python_lock_marker" ]] || [[ "$(cat "$python_lock_marker")" != "$python_lock_hash" ]]; then
  python -m pip install -e '.[dev]'
  printf '%s\n' "$python_lock_hash" > "$python_lock_marker"
fi

frontend_lock_hash="$(sha256sum frontend/package-lock.json | cut -d ' ' -f 1)"
frontend_lock_marker=frontend/node_modules/.codex-project-package-lock.sha256
if [[ ! -r "$frontend_lock_marker" ]] || [[ "$(cat "$frontend_lock_marker")" != "$frontend_lock_hash" ]]; then
  (cd frontend && npm ci)
  printf '%s\n' "$frontend_lock_hash" > "$frontend_lock_marker"
fi

exec "$@"
