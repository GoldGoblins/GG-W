"""Local telemetry-only subprocess over the existing bounded pipe transport."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.game_engine_adapter_transport import BoundedWorker
from backend.platform_support import host_environment


class TmogWorker(BoundedWorker):
    def __init__(self):
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        self._start_worker(
            [str(executable), "-X", "utf8", "-B", "-u", str(Path(__file__).resolve())],
            host_environment({"PYTHONDONTWRITEBYTECODE": "1"}))


def main():
    if os.name == "nt":
        from backend.platform_process import apply_windows_worker_limits
        apply_windows_worker_limits(memory_bytes=192 * 1024**2, cpu_seconds=3600)
    from backend import tmog_contract
    from backend.tmog_sampler import PAGES
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith(b"\n"):
            return
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "pulse":
                result = tmog_contract.pulse()
            elif op == "snapshot" and request.get("page") in PAGES:
                live = request.get("live")
                if not isinstance(live, dict) or len(live.get("cores") or []) > 32:
                    raise ValueError("INVALID_TELEMETRY_SAMPLE")
                result = tmog_contract.snapshot(request["page"], live=live)
            else:
                raise ValueError("INVALID_TELEMETRY_OPERATION")
            answer = {"ok": True, "result": result}
            packet = json.dumps(answer, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(packet) > 1024**2:
                raise ValueError("TELEMETRY_RESULT_LIMIT")
        except Exception as exc:
            packet = json.dumps({"ok": False, "error": type(exc).__name__}).encode() + b"\n"
        sys.stdout.buffer.write(packet)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
