"""Run each crypto check with temporary state and sockets disabled."""
from pathlib import Path
import runpy
import socket
import sys
import tempfile
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import crypto_contract, kaspa_contract


def denied(*args, **kwargs):
    raise OSError("OFFLINE_TEST_NETWORK_DISABLED")


def main():
    paths = [PROJECT / "tests" / name for name in sys.argv[1:]]
    if not paths:
        paths = sorted((PROJECT / "tests").glob("test_crypto*.py")) + [PROJECT / "tests/test_polymarket_research.py"]
    failed = []
    for path in paths:
        with tempfile.TemporaryDirectory(prefix="gg-crypto-check-") as tmp:
            crypto_contract.STATE_DIR = Path(tmp) / "sol"
            kaspa_contract.STATE_DIR = Path(tmp) / "kas"
            with patch.object(socket.socket, "connect", denied), patch.object(socket.socket, "connect_ex", denied), patch.object(socket, "create_connection", denied):
                try:
                    # Each script runs in its own interpreter to prevent mock leakage.
                    if len(paths) > 1:
                        import subprocess
                        result = subprocess.run([sys.executable, "-B", __file__, path.name], cwd=PROJECT)
                        if result.returncode:
                            failed.append(path.name)
                    else:
                        runpy.run_path(str(path), run_name="__main__")
                except SystemExit as exc:
                    if exc.code:
                        failed.append(path.name)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    failed.append(path.name)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("OFFLINE_CRYPTO_CHECKS=PASS", len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
