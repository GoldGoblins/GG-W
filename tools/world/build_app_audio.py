"""Build GG's application-only Windows audio service with the installed SDK."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from backend.platform_build import build_environment, build_tool
from backend.platform_support import native_directory


def build():
    if os.name != "nt":
        raise RuntimeError("This backend uses Windows application loopback")
    source = PROJECT / "native/audio/gg_app_audio.cpp"
    output = native_directory(PROJECT)
    output.mkdir(parents=True, exist_ok=True)
    env = build_environment()
    with tempfile.TemporaryDirectory(prefix=".gg-app-audio-", dir=output) as directory:
        temporary = Path(directory)
        target = temporary / "gg_app_audio.dll"
        command = [build_tool("cl.exe", env), "/nologo", "/O2", "/MD", "/W4", "/EHsc",
                   "/std:c++17", "/D_WIN32_WINNT=0x0A00", "/DNTDDI_VERSION=0x0A00000A",
                   "/LD", str(source), "/link", "/OUT:" + str(target),
                   "ole32.lib", "mmdevapi.lib", "uuid.lib"]
        result = subprocess.run(command, env=env, cwd=temporary, capture_output=True,
                                text=True, errors="replace", timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        checked = subprocess.run([sys.executable, "-B", "-c",
            "import ctypes,sys; assert ctypes.CDLL(sys.argv[1]).gga_abi_version()==1", str(target)],
            capture_output=True, text=True, timeout=10)
        if checked.returncode:
            raise RuntimeError("The application audio ABI probe failed")
        receipt = {"schema": "gg.app-audio-build.v1", "abi": 1,
                   "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "binary_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                   "binary_bytes": target.stat().st_size, "compiler": "MSVC",
                   "scope": "APPLICATION_PROCESS_TREE_ONLY"}
        os.replace(target, output / target.name)
        (output / "app-audio-build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "binary_bytes": receipt["binary_bytes"]}


if __name__ == "__main__":
    print(json.dumps(build()))
