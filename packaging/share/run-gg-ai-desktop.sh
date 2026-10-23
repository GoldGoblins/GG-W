#!/usr/bin/env bash
# Share launcher for GG AI Desktop. GROK TUI is the intended motor.
# No sudo. Does not start gg-host. Does not require local GGUF models.

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'FAIL: do not source this file. Run: bash %s\n' "${BASH_SOURCE[0]}" >&2
  return 78
fi

set -Eeuo pipefail
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == "--update" ]]; then
  shift
  UPDATE="$HERE/update-gg-ai-desktop.sh"
  if [[ ! -x "$UPDATE" ]]; then
    fail "update-gg-ai-desktop.sh missing"
  fi
  "$UPDATE"
fi
PROJECT="$HERE/app"
if [[ ! -f "$PROJECT/main.py" && -f "$HERE/main.py" ]]; then
  PROJECT="$HERE"
fi
if [[ ! -f "$PROJECT/main.py" && -f "$HERE/../main.py" ]]; then
  PROJECT="$(cd "$HERE/.." && pwd)"
fi
if [[ ! -f "$PROJECT/main.py" && -f "$HERE/../../main.py" ]]; then
  PROJECT="$(cd "$HERE/../.." && pwd)"
fi
MAIN="$PROJECT/main.py"
STARTUP="$PROJECT/startup.py"
PYTHON="${PYTHON:-/usr/bin/python3}"

if [[ ! -x "$PYTHON" ]]; then
  fail "python3 missing"
fi
if [[ ! -f "$MAIN" ]]; then
  fail "app/main.py missing — unpack the zip first"
fi
if [[ ! -f "$STARTUP" ]]; then
  fail "app/startup.py missing — unpack the zip first"
fi

find_grok() {
  if [[ -n "${GG_GROK_BIN:-}" && -x "${GG_GROK_BIN}" ]]; then
    printf '%s\n' "$GG_GROK_BIN"
    return 0
  fi
  local candidate
  for candidate in \
    "$HOME/.grok/bin/grok" \
    "$HOME/.local/bin/grok" \
    "$HOME/.local/share/goldgoblins/tools/grok-build/1.0.5/grok"
  do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if command -v grok >/dev/null 2>&1; then
    command -v grok
    return 0
  fi
  return 1
}

if GROK_BIN="$(find_grok)"; then
  export GG_GROK_BIN="$GROK_BIN"
fi

export GG_APP_ROOT="$PROJECT"
DEFAULT_WORKSPACE="$PROJECT"
if [[ "$(basename "$(dirname "$PROJECT")")" == projects && -f "$PROJECT/../../AGENTS.md" ]]; then
  DEFAULT_WORKSPACE="$(cd "$PROJECT/../.." && pwd)"
fi
export GG_WORKSPACE="${GG_WORKSPACE:-$DEFAULT_WORKSPACE}"

if [[ -z "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/wayland-0" ]]; then
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  export WAYLAND_DISPLAY=wayland-0
fi
if [[ -z "${DISPLAY:-}" && -S /tmp/.X11-unix/X0 ]]; then
  export DISPLAY=:0
fi
if [[ -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
  fail "no display (Wayland or X11)"
fi

printf 'GG_AI_DESKTOP=SHARE\n'
printf 'MOTOR=GROK_TUI\n'
printf 'GG_GROK_BIN=%s\n' "${GG_GROK_BIN:-not-installed}"
printf 'GG_WORKSPACE=%s\n' "$GG_WORKSPACE"
cd "$PROJECT"
exec "$PYTHON" -B "$STARTUP"
