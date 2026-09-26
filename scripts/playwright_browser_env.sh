#!/usr/bin/env bash
set -euo pipefail

# Rootless Playwright Chromium helper. It never runs apt and never downloads
# browser binaries. Put cached Ubuntu DEBs in I5_BROWSER_DEB_DIR when needed.

if [[ -n "${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-}" ]]; then
  BROWSER="$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
else
  BROWSER="${1:-}"
  shift || true
fi
LIB_DIR="${I5_BROWSER_LIB_DIR:-/tmp/i5-browser-libs}"
DEB_DIR="${I5_BROWSER_DEB_DIR:-}"

if [[ -z "$BROWSER" || ! -x "$BROWSER" ]]; then
  echo "Set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to the existing Chromium binary." >&2
  exit 2
fi

if [[ -n "$DEB_DIR" ]]; then
  command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required for cached DEB extraction" >&2; exit 2; }
  mkdir -p "$LIB_DIR"
  for deb in "$DEB_DIR"/libnss3_*.deb "$DEB_DIR"/libnspr4_*.deb "$DEB_DIR"/libasound2t64_*.deb; do
    [[ -f "$deb" ]] || continue
    dpkg-deb -x "$deb" "$LIB_DIR"
  done
fi

export LD_LIBRARY_PATH="${LIB_DIR}/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
echo "Chromium: $("$BROWSER" --version)"
echo "Unresolved libraries:"
ldd "$BROWSER" | grep 'not found' || true

if [[ "${1:-}" == "--" ]]; then
  shift
  exec "$@"
fi
