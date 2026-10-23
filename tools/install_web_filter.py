#!/usr/bin/env python3
"""Install original uBlock Origin and build GG's small WebView2 host on Windows.

Run explicitly during an approved setup/update task. Application startup never
downloads software. The extension's own normal filter-list updates stay enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SDK_VERSION = "1.0.4258.31"
UBLOCK_VERSION = "1.75.0"
SDK_URL = f"https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{SDK_VERSION}/microsoft.web.webview2.{SDK_VERSION}.nupkg"
UBLOCK_URL = f"https://github.com/gorhill/uBlock/releases/download/{UBLOCK_VERSION}/uBlock0_{UBLOCK_VERSION}.chromium.zip"


def download(url: str, maximum: int = 32 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "GG-Web-Filter-Setup"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Vendor archive exceeds the download limit")
    return data


def unpack(data: bytes, destination: Path, *, sdk: bool = False) -> None:
    base = destination.resolve()
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            parts = Path(normalized).parts
            if (not parts or any(part in ("..", ".") or ":" in part for part in parts)
                    or normalized.startswith("/") or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("Unsafe vendor archive path")
            target = (base / normalized).resolve()
            if not target.is_relative_to(base):
                raise ValueError("Vendor archive escapes its destination")
            total += info.file_size
            if total > 96 * 1024 * 1024:
                raise ValueError("Vendor archive exceeds the expansion limit")
            if sdk and not (normalized.startswith("build/native/include/")
                            or normalized.startswith("build/native/x64/")
                            or normalized in ("LICENSE.txt", "NOTICE.txt")):
                continue
            if info.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def build_host(sdk: Path, output: Path) -> None:
    from backend.platform_build import build_environment, build_tool
    environment = build_environment()
    source = ROOT / "native/webview/gg_webview.cpp"
    command = [build_tool("cl.exe", environment), "/nologo", "/EHsc", "/std:c++17", "/O2", "/MD", "/LD",
               "/I" + str(sdk / "build/native/include"), str(source), "/Fe:" + str(output),
               "/Fo:" + str(output.with_suffix(".obj")), "/link",
               str(sdk / "build/native/x64/WebView2LoaderStatic.lib"), "user32.lib", "ole32.lib",
               "oleaut32.lib", "version.lib", "advapi32.lib", "shlwapi.lib"]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).decode("utf-8", "replace")[-8000:])


def install(*, sdk_package: Path | None = None, ublock_package: Path | None = None) -> dict:
    if os.name != "nt":
        raise RuntimeError("This installer is for the Windows WEB engine")
    from backend.application_paths import STATE_ROOT
    sdk_data = sdk_package.read_bytes() if sdk_package else download(SDK_URL)
    extension_data = ublock_package.read_bytes() if ublock_package else download(UBLOCK_URL)
    digest = hashlib.sha256(extension_data).hexdigest()
    destination = STATE_ROOT / "web-extensions"
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gg-web-filter-install-") as temporary:
        stage = Path(temporary)
        sdk = stage / "sdk"
        unpack(sdk_data, sdk, sdk=True)
        unpack(extension_data, stage / "extension")
        source = stage / "extension/uBlock0.chromium"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if (manifest.get("name") != "uBlock Origin" or manifest.get("version") != UBLOCK_VERSION
                or manifest.get("manifest_version") != 2):
            raise ValueError("Unexpected uBlock Origin package")
        built = stage / "gg_webview.dll"
        build_host(sdk, built)
        library = ROOT / "backend/native/windows-x86_64/gg_webview.dll"
        library.parent.mkdir(parents=True, exist_ok=True)
        # Do not replace extension files in place: WebView2 unloads changed
        # extensions. Every upstream release gets its own immutable directory.
        extension = destination / ("ublock-" + UBLOCK_VERSION + "-" + digest[:12])
        if not extension.exists():
            staging = destination / (extension.name + ".installing")
            if staging.exists():
                raise RuntimeError("An incomplete extension installation needs inspection")
            shutil.copytree(source, staging)
            staging.replace(extension)
        staging_library = library.with_suffix(".new.dll")
        shutil.copy2(built, staging_library)
        staging_library.replace(library)
        notice_root = ROOT / "native/webview"
        for name in ("LICENSE.txt", "NOTICE.txt"):
            shutil.copy2(sdk / name, notice_root / ("MICROSOFT-" + name))
        info = {
            "schema": "gg.web-content-blocking.v1", "provider": "uBlock Origin", "version": UBLOCK_VERSION,
            "source": UBLOCK_URL, "archive_sha256": digest, "directory": str(extension),
            "modified": False, "sdk_version": SDK_VERSION, "sdk_source": SDK_URL,
        }
        saved = destination / "install.json"
        temporary_info = saved.with_suffix(".tmp")
        temporary_info.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        temporary_info.replace(saved)
        metadata = {"source": "native/webview/gg_webview.cpp", "sdk_version": SDK_VERSION,
                    "source_sha256": hashlib.sha256((ROOT / "native/webview/gg_webview.cpp").read_bytes()).hexdigest(),
                    "dll_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}
        (library.parent / "webview-build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"extension": "uBlock Origin", "version": UBLOCK_VERSION,
            "extension_bytes": len(extension_data), "sdk_bytes": len(sdk_data),
            "host_bytes": library.stat().st_size, "restart_required": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-package", type=Path, help="Reuse an original downloaded Microsoft SDK archive")
    parser.add_argument("--ublock-package", type=Path, help="Reuse an original downloaded uBlock release archive")
    arguments = parser.parse_args()
    print(json.dumps(install(sdk_package=arguments.sdk_package, ublock_package=arguments.ublock_package)))


if __name__ == "__main__":
    main()
