#!/bin/sh
# Run this script explicitly with Termux's sh; no Linux shebang resolver is needed.
set -eu
gg_cli_install_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python "$gg_cli_install_dir/../install.py" --platform termux "$@"
