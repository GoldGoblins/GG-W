"""Install the pinned optional GG test toolchain, outside distributable source.

Run explicitly through the GG setup action or as this script. Never runs at import.
No wallet or mnemonic values are needed for dependency installation/compilation.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
PROJECT = SOURCE.parents[1]
sys.path.insert(0, str(PROJECT))
from backend.application_paths import TOOLS_ROOT


def install(target: Path | None = None) -> Path:
    target = (target or TOOLS_ROOT / "gg-testnet").absolute()
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not node or not npm:
        raise RuntimeError("GG_TESTNET_NODE_NPM_REQUIRED")
    result = subprocess.run([node, "--version"], capture_output=True, text=True,
                            timeout=10, check=True)
    major, minor, *_ = map(int, result.stdout.strip().lstrip("v").split("."))
    if major < 22 or major % 2 or (major == 22 and minor < 13):
        raise RuntimeError("GG_TESTNET_NODE_VERSION_REQUIRED")
    target.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json", "hardhat.config.ts"):
        shutil.copy2(SOURCE / name, target / name)
    # Dependencies are original distributor packages, integrity-pinned by npm ci.
    # Install lifecycle scripts are disabled; no global packages or PATH changes.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    command = [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", str(target)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            timeout=240, creationflags=flags)
    if result.returncode:
        raise RuntimeError("GG_TESTNET_TOOLCHAIN_INSTALL_FAILED")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    install(args.target)
    print("GG_TESTNET_TOOLCHAIN_INSTALLED")
