#!/usr/bin/env bash
# Create one catalog-verified GG AI DESKTOP source directory in a ZIP.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'FAIL: do not source\n' >&2
  return 78
fi
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT_DIR="${1:-$PROJECT/dist}"
STAGE="$(mktemp -d /tmp/gg-ai-desktop-share.XXXXXX)"
NAME="GG-AI-DESKTOP-${STAMP}"
ROOT="$STAGE/$NAME"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT
mkdir -p "$OUT_DIR"
python3 -B "$HERE/catalog.py" export "$ROOT"
ZIP="$OUT_DIR/${NAME}.zip"
[[ ! -e "$ZIP" ]] || { printf 'FAIL: archive already exists\n' >&2; exit 2; }
(cd "$STAGE" && zip -qry "$ZIP" "$NAME")
printf 'SHARE_ZIP=%s\n' "$ZIP"
printf 'BYTES=%s\n' "$(wc -c < "$ZIP")"
