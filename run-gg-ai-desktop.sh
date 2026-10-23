#!/usr/bin/env bash
# Launch GG AI Desktop from this directory (GitHub clone or GoldGoblins tree).
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'FAIL: do not source this file\n' >&2
  return 78
fi
set -Eeuo pipefail
export LC_ALL=C.UTF-8
HERE="$(cd "$(dirname "$0")" && pwd)"
SHARE="$HERE/packaging/share/run-gg-ai-desktop.sh"
if [[ -x "$SHARE" ]]; then
  exec "$SHARE" "$@"
fi
PYTHON="${PYTHON:-/usr/bin/python3}"
cd "$HERE"
exec "$PYTHON" -B "$HERE/startup.py"
