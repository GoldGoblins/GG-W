"""Install the reviewed per-user PHP/MariaDB Windows distributions."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.site_runtime_setup import install

if __name__ == '__main__':
    try:
        result = install()
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('SITE_') else 'SITE_RUNTIME_INSTALL_FAILED'
        print(json.dumps({'status': 'FAIL', 'reason': reason}))
        raise SystemExit(1)
    print(json.dumps(result))
