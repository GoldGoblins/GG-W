#!/usr/bin/env bash
# Fast-forward update from the shared git remote (GitHub or other).
# No sudo. No force-push. No rewrite of history.

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'FAIL: do not source this file\n' >&2
  return 78
fi

set -Eeuo pipefail
export LC_ALL=C.UTF-8

HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/gg-ai-desktop-share"
ORIGIN_FILE="$STATE/origin.url"
GIT_DIR="${GG_AI_GIT_DIR:-}"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

mkdir -p "$STATE"

if [[ "${1:-}" == "--set-origin" ]]; then
  url="${2:-}"
  if [[ -z "$url" ]]; then
    fail "usage: update-gg-ai-desktop.sh --set-origin <git-url>"
  fi
  printf '%s\n' "$url" >"$ORIGIN_FILE"
  printf 'ORIGIN_SAVED=%s\n' "$url"
  exit 0
fi

if [[ -z "$GIT_DIR" ]]; then
  if [[ -d "$HERE/app/.git" ]]; then
    GIT_DIR="$HERE/app"
  elif [[ -d "$HERE/.git" ]]; then
    GIT_DIR="$HERE"
  elif [[ -d "$HERE/../.git" ]]; then
    GIT_DIR="$(cd "$HERE/.." && pwd)"
  elif [[ -d /home/GG/GoldGoblins/.git ]]; then
    GIT_DIR=/home/GG/GoldGoblins
  fi
fi

ORIGIN="${GG_AI_ORIGIN:-}"
if [[ -z "$ORIGIN" && -f "$ORIGIN_FILE" ]]; then
  ORIGIN="$(tr -d '[:space:]' <"$ORIGIN_FILE")"
fi

if [[ -z "${GIT_DIR:-}" || ! -d "$GIT_DIR/.git" ]]; then
  if [[ -z "$ORIGIN" ]]; then
    fail "no git checkout and no origin. Create a GitHub repo, then: $0 --set-origin <url>"
  fi
  TARGET="$STATE/src"
  if [[ ! -d "$TARGET/.git" ]]; then
    git clone -- "$ORIGIN" "$TARGET"
    printf 'CLONED=%s\n' "$TARGET"
  fi
  GIT_DIR="$TARGET"
fi

cd "$GIT_DIR"
if [[ -n "$ORIGIN" ]]; then
  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$ORIGIN"
  else
    git remote add origin "$ORIGIN"
  fi
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  fail "no origin. Set GitHub with: $0 --set-origin https://github.com/YOU/gg-ai-desktop.git"
fi

git fetch origin
branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
  branch=main
fi
if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  git merge --ff-only "origin/$branch"
else
  fail "origin/$branch missing — push main to GitHub first"
fi
printf 'UPDATE=PASS\n'
printf 'GIT_DIR=%s\n' "$GIT_DIR"
printf 'HEAD=%s\n' "$(git rev-parse --short HEAD)"
