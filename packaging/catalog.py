#!/usr/bin/env python3
"""Catalog and export reviewed application sources, never a user's home/cache."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
CATALOG_NAME = "FILE-CATALOG.json"
SOURCE_SUFFIXES = {".py", ".qml", ".js", ".json", ".yaml", ".yml", ".toml", ".rs", ".c", ".cpp", ".h", ".hpp", ".inl", ".natvis", ".wgsl", ".vert", ".frag", ".glsl", ".lock", ".md", ".txt", ".sh", ".qrc", ".pro", ".pri", ".cmake"}
LINKS = {".agents/skills", ".grok/skills", "tools/skills/gg-live-eyes"}
SECRET_PATTERNS = (
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{25,}"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----(?:\r?\n|\\n)[A-Za-z0-9+/]{32,}"),
)


def permitted(relative: str) -> bool:
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        return False
    if any(part in {".git", "__pycache__", "target", "build", "dist", "node_modules", "sessions", "shared-memory", "backups", ".venv", ".runtime"} for part in p.parts):
        return False
    if any(part.startswith('.venv-') for part in p.parts):
        return False
    if p.name in {"auth.json", "credentials.toml", ".gg-ai-desktop-live"} or relative == ".codex/config.toml" or p.name.startswith((".env", ".gg-live-aid-preflight.")):
        return False
    if p.suffix.lower() in {".pyc", ".log", ".tmp", ".key", ".pem", ".secret", ".gguf", ".sqlite", ".sqlite3", ".blend"}:
        return False
    return not relative.startswith(("qml/game/", "qml/assets/authored/", "qml/assets/gg-authored-", "packaging/game/"))


def selected_paths(project: Path = PROJECT) -> list[str]:
    base = json.loads((project / "packaging/source-base.json").read_text(encoding='utf-8'))
    selected = set(base["files"])
    # The native/build and UI directories retain their established structure.
    for dirname in ("backend", "config", "schemas", "tests", "native", "qml/components", "packaging", "tools/world"):
        root = project / dirname
        for parent, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {"target", "build", "dist", "__pycache__", ".git", "node_modules", "game", ".venv"}]
            for name in names:
                p = Path(parent) / name
                if p.suffix in SOURCE_SUFFIXES or name in {"qmldir", "Cargo.lock", "Cargo.toml", "CMakeLists.txt", "Containerfile", "LICENSE", "LICENSE-MIT", "LICENSE-APACHE"}:
                    selected.add(p.relative_to(project).as_posix())
    for dirname in ("knowledge", "skills", "support"):
        for p in (project / dirname).rglob("*"):
            if p.is_file():
                selected.add(p.relative_to(project).as_posix())
    for name in ("AGENTS.md", "FILE-LAYOUT.md", "requirements.txt", "gg-setup", "gg-model", "gg-knowledge", "qml/assets/knowledge-cell.png", "tools/blender/gg_blender_reference.py", "tools/install_site_runtime.py", "tools/verify_site_runtime.py", "qml/components/engine/white.png", "setup-windows.cmd", "run-gg-ai-desktop.cmd", "WINDOWS-PORT.json"):
        if name.endswith('.cmd') or name == 'WINDOWS-PORT.json':
            if not (project / name).is_file():
                continue
        selected.add(name)
    selected.update(LINKS)
    selected.update(p.name for p in project.glob("gg-*.cmd") if p.is_file())
    # Only the application's own built Windows ABIs may join a source export.
    for name in ("gg_world", "gg_presentation", "gg_physics", "gg_engine_ui", "gg_engine_formats", "gg_engine_client", "gg_webview", "gg_app_audio"):
        selected.update(p.relative_to(project).as_posix() for p in
                        (project / "backend/native").glob("windows-*/" + name + ".dll") if p.is_file())
    return sorted(p for p in selected if p != CATALOG_NAME and permitted(p))


def category(relative: str) -> str:
    first = relative.split("/", 1)[0]
    return {
        "backend": "application-code", "qml": "interface", "native": "native-engine",
        "config": "configuration", "schemas": "contracts", "knowledge": "gpt-knowledge",
        "skills": "gg-skills", "support": "shared-support", "tools": "tools",
        "tests": "tests", "packaging": "installation-and-packaging", "docs": "documentation",
    }.get(first, "entrypoints-and-guidance")


def make_catalog(project: Path = PROJECT) -> dict:
    records = []
    declared_modes = {}
    manifest_path = project / "SOURCE-MANIFEST.json"
    if os.name == "nt" and manifest_path.is_file():
        declared_modes = json.loads(manifest_path.read_text(encoding="utf-8")).get("file_modes", {})
    for relative in selected_paths(project):
        p = project / relative
        if relative in LINKS:
            is_link = p.is_symlink() or (os.name == 'nt' and p.is_junction())
            if not is_link or not p.resolve().is_relative_to(project.resolve()):
                raise ValueError("INVALID_APPLICATION_LINK: " + relative)
            records.append({"path": relative, "category": category(relative), "kind": "symlink", "target": os.path.relpath(p.resolve(), p.parent).replace(os.sep, '/')})
            continue
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(project.resolve()):
            raise ValueError("SOURCE_FILE_MISSING_OR_EXTERNAL: " + relative)
        data = p.read_bytes()
        # Report locations only: matching credential values never leave this process.
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError("CREDENTIAL_PATTERN_IN_SOURCE: " + relative)
        mode = oct(int(declared_modes.get(relative, "0644"), 8)) if os.name == "nt" else oct(p.stat().st_mode & 0o777)
        records.append({"path": relative, "category": category(relative), "kind": "file", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": mode})
    return {"schema": "gg.ai-desktop.file-catalog.v1", "application": "GG AI DESKTOP", "source_root": ".", "dependency_catalog": "config/dependencies.json", "categories": dict(sorted(collections.Counter(r["category"] for r in records).items())), "files": records}


def write_catalog(project: Path = PROJECT) -> dict:
    catalog = make_catalog(project)
    (project / CATALOG_NAME).write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding='utf-8', newline='\n')
    return catalog


def verify_catalog(project: Path = PROJECT) -> dict:
    saved = json.loads((project / CATALOG_NAME).read_text(encoding='utf-8'))
    actual = make_catalog(project)
    if saved != actual:
        raise ValueError("FILE_CATALOG_STALE: regenerate after source changes")
    return actual


def export_sources(destination: Path, project: Path = PROJECT) -> dict:
    destination = destination.resolve()
    if destination == project.resolve() or destination.is_relative_to(project.resolve()):
        raise ValueError("EXPORT_MUST_BE_OUTSIDE_SOURCE")
    if destination.exists():
        raise ValueError("EXPORT_TARGET_ALREADY_EXISTS")
    catalog = verify_catalog(project)
    destination.mkdir(parents=True)
    for row in catalog["files"]:
        if row['kind'] == 'symlink':
            continue
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / row["path"], target)
        if os.name != "nt":
            target.chmod(int(row["mode"], 8))
    from backend.application_paths import expose_directory
    for row in catalog['files']:
        if row['kind'] == 'symlink':
            target = destination / row['path']
            expose_directory(target, (target.parent / row['target']).resolve())
    shutil.copy2(project / CATALOG_NAME, destination / CATALOG_NAME)
    verify_catalog(destination)
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("write", "verify", "export"))
    parser.add_argument("destination", nargs="?")
    args = parser.parse_args()
    if args.operation == "write":
        catalog = write_catalog()
    elif args.operation == "verify":
        catalog = verify_catalog()
    else:
        if not args.destination:
            parser.error("export requires a new destination")
        catalog = export_sources(Path(args.destination))
    print(json.dumps({"status": "PASS", "files": len(catalog["files"]), "categories": catalog["categories"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
