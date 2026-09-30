#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

compose=(docker compose --project-directory "$root" -f "$root/compose.dev.yaml")
if [[ -f "$root/.env.dev" ]]; then
  compose+=(--env-file "$root/.env.dev")
fi

usage() {
  cat <<'EOF'
Usage: ./scripts/dev-codex.sh <up|database|shell|exec|rebuild|recreate|stop|status>

  up        Build and start only the isolated Codex development container
  database  Also start the isolated PostgreSQL development service
  shell     Open a development shell in codex-dev
  exec      Run a command in codex-dev, for example: exec codex --version
  rebuild   Pull the selected Codex base image, rebuild, and restart codex-dev
  recreate  Recreate codex-dev without removing named volumes
  stop      Stop the development containers without deleting volumes
  status    Show development container status
EOF
}

case "${1:-}" in
  up)
    "${compose[@]}" up -d --build codex-dev
    ;;
  database)
    "${compose[@]}" --profile database up -d --build codex-dev postgres-dev
    ;;
  shell)
    "${compose[@]}" up -d --build codex-dev
    exec "${compose[@]}" exec codex-dev bash --noprofile --norc -i
    ;;
  exec)
    shift
    if [[ $# -eq 0 ]]; then usage; exit 2; fi
    "${compose[@]}" up -d codex-dev
    exec "${compose[@]}" exec codex-dev "$@"
    ;;
  rebuild)
    "${compose[@]}" build --pull codex-dev
    "${compose[@]}" up -d --force-recreate codex-dev
    ;;
  recreate)
    "${compose[@]}" rm -sf codex-dev
    "${compose[@]}" up -d codex-dev
    ;;
  stop)
    "${compose[@]}" stop
    ;;
  status)
    "${compose[@]}" ps -a
    ;;
  *)
    usage
    exit 2
    ;;
esac
