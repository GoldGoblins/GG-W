from __future__ import annotations

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
QML_ROOT = PROJECT / "qml"
ENTRY = Path("qml/components/WorkspaceSurface.qml")

_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE = re.compile(r"//[^\n]*")
_IMPORT = re.compile(r'import\s+"([^"]+)"')
_TYPE = re.compile(r"(?<![\w.])([A-Z][A-Za-z0-9]+)\s*\{")
_RESOLVED = re.compile(
    r'(?:source|url)\s*:\s*(?:Qt\.resolvedUrl\()?"([^"]+\.(?:qml|js))"'
)


def _strip(source: str) -> str:
    source = _BLOCK.sub("", source)
    return _LINE.sub("", source)


def _read(rel: Path) -> str:
    path = PROJECT / rel
    if path.is_symlink() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _existing(rel: Path) -> Path | None:
    path = PROJECT / rel
    if path.is_symlink() or not path.is_file():
        return None
    try:
        path.relative_to(QML_ROOT)
    except ValueError:
        return None
    return rel


def _refs(rel: Path, source: str) -> list[Path]:
    found: list[Path] = []
    parent = rel.parent
    for raw in _IMPORT.findall(source):
        if raw.startswith("http:") or raw.startswith("https:"):
            continue
        candidate = (parent / raw).as_posix()
        if candidate.startswith("qml/"):
            item = _existing(Path(candidate))
        else:
            item = _existing(Path("qml") / Path(raw))
            if item is None:
                item = _existing(parent / raw)
        if item is not None:
            found.append(item)
    for raw in _RESOLVED.findall(source):
        item = _existing(parent / raw)
        if item is None and not raw.startswith("/"):
            item = _existing(Path("qml") / raw)
        if item is not None:
            found.append(item)
    search_dirs = (parent, Path("qml/components"), Path("qml"))
    for name in _TYPE.findall(source):
        filename = name + ".qml"
        for folder in search_dirs:
            item = _existing(folder / filename)
            if item is not None:
                found.append(item)
                break
    return found


def queue(entry: Path = ENTRY) -> list[str]:
    start = _existing(entry)
    if start is None:
        return []
    ordered: list[Path] = []
    seen: set[Path] = set()

    def walk(rel: Path) -> None:
        if rel in seen:
            return
        seen.add(rel)
        text = _strip(_read(rel))
        for child in _refs(rel, text):
            walk(child)
        ordered.append(rel)

    walk(start)
    defer = {"qml/components/WebPane.qml"}
    return [
        path.as_posix()
        for path in ordered
        if path.suffix == ".qml" and path.as_posix() not in defer
    ]
