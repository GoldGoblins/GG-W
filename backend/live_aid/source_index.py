from __future__ import annotations

import ast
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_SKIP_DIR_NAMES = {
    ".git",
    "backups",
    "__pycache__",
    "node_modules",
    ".venv",
    "models",
}
_MAX_INDEX_BYTES = 2 * 1024 * 1024

@dataclass(frozen=True)
class Symbol:
    module: str
    name: str
    kind: str
    line: int
    signature: str | None
    source_path: str
    source_sha256: str

@dataclass
class SourceIndex:
    root: Path
    files: dict[str, dict[str, Any]]
    symbols: dict[str, list[Symbol]]
    modules: dict[str, str]

    @classmethod
    def build(cls, root: Path) -> "SourceIndex":
        root = Path(root).resolve(strict=True)
        files: dict[str, dict[str, Any]] = {}
        symbols: dict[str, list[Symbol]] = {}
        modules: dict[str, str] = {}
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in _SKIP_DIR_NAMES
            ]
            folder = Path(dirpath)
            for name in filenames:
                found.append(folder / name)
        for path in sorted(found):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > _MAX_INDEX_BYTES:
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            entry: dict[str, Any] = {"sha256": digest, "bytes": len(raw), "suffix": path.suffix}
            files[rel] = entry
            if path.suffix == ".py":
                module = cls._module_name(rel)
                modules[module] = rel
                try:
                    text = raw.decode("utf-8")
                    tree = ast.parse(text, filename=rel)
                except (UnicodeDecodeError, SyntaxError) as exc:
                    entry["parse_error"] = type(exc).__name__ + ":" + str(exc)
                    continue
                rows: list[Symbol] = []
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        rows.append(Symbol(
                            module, node.name, "function", node.lineno,
                            node.name + "(" + ast.unparse(node.args) + ")",
                            rel, digest,
                        ))
                    elif isinstance(node, ast.ClassDef):
                        rows.append(Symbol(module, node.name, "class", node.lineno, None, rel, digest))
                        for child in node.body:
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                rows.append(Symbol(
                                    module, node.name + "." + child.name, "method", child.lineno,
                                    child.name + "(" + ast.unparse(child.args) + ")",
                                    rel, digest,
                                ))
                    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            if isinstance(target, ast.Name):
                                rows.append(Symbol(module, target.id, "binding", node.lineno, None, rel, digest))
                symbols[module] = rows
            elif path.suffix == ".json":
                try:
                    json.loads(raw.decode("utf-8"))
                    entry["json_valid"] = True
                except (UnicodeDecodeError, json.JSONDecodeError):
                    entry["json_valid"] = False
            elif path.suffix == ".qml":
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                entry["qml_imports"] = [
                    line.strip() for line in text.splitlines() if line.lstrip().startswith("import ")
                ]
        return cls(root, files, symbols, modules)

    @staticmethod
    def _module_name(rel: str) -> str:
        value = rel[:-3] if rel.endswith(".py") else rel
        value = value.replace("/", ".")
        if value.endswith(".__init__"):
            value = value[:-9]
        return value

    def has_path(self, relative_path: str) -> bool:
        return relative_path in self.files

    def source_sha(self, relative_path: str) -> str | None:
        row = self.files.get(relative_path)
        return None if row is None else str(row["sha256"])

    def resolve_module(self, imported: str) -> str | None:
        if imported in self.modules:
            return imported
        suffix = "." + imported
        matches = [name for name in self.modules if name.endswith(suffix)]
        return matches[0] if len(matches) == 1 else None

    def resolve_symbol(self, module: str, symbol: str) -> Symbol | None:
        resolved = self.resolve_module(module)
        if resolved is None:
            return None
        matches = [item for item in self.symbols.get(resolved, []) if item.name == symbol]
        return matches[0] if len(matches) == 1 else None

    def to_json(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": self.files,
            "modules": self.modules,
            "symbols": {
                key: [asdict(item) for item in value] for key, value in self.symbols.items()
            },
        }
