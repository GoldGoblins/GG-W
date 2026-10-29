#!/bin/sh
set -eu
gg_cli_install_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$gg_cli_install_dir/../install.py" --platform linux "$@"
