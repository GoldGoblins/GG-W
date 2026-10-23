from __future__ import annotations

import ast
import builtins
import codeop

from .contract import Diagnostic, EvidenceRef, Status
from .source_index import SourceIndex

_BUILTINS = frozenset(dir(builtins))

def _syntax_diagnostic(exc: SyntaxError, source_name: str) -> Diagnostic:
    return Diagnostic(
        status=Status.FAIL,
        code="PY_SYNTAX",
        message=exc.msg,
        source=source_name,
        line=exc.lineno,
        column=exc.offset,
        end_line=getattr(exc, "end_lineno", None),
        end_column=getattr(exc, "end_offset", None),
        suggestion="Complete or repair the Python syntax before execution.",
        blocking=True,
    )

def _looks_incomplete(source: str) -> bool:
    if not source.strip():
        return True
    try:
        result = codeop.compile_command(source, symbol="exec")
        return result is None
    except (SyntaxError, OverflowError, ValueError):
        return False

def analyze_python(source: str, source_name: str, index: SourceIndex | None) -> list[Diagnostic]:
    if _looks_incomplete(source):
        return [Diagnostic(
            status=Status.INCOMPLETE,
            code="PY_AUTHORING_INCOMPLETE",
            message="Draft is syntactically incomplete; analysis remains advisory while authoring continues.",
            source=source_name,
            blocking=False,
        )]
    try:
        tree = ast.parse(source, filename=source_name)
        compile(tree, source_name, "exec", dont_inherit=True)
    except SyntaxError as exc:
        return [_syntax_diagnostic(exc, source_name)]

    findings: list[Diagnostic] = [Diagnostic(
        status=Status.PASS,
        code="PY_COMPILE",
        message="Python parser and bytecode compile precheck passed.",
        source=source_name,
        blocking=False,
    )]

    aliases: dict[str, str] = {}
    locally_bound: set[str] = set()
    loaded_names: list[ast.Name] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
                locally_bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                locally_bound.add(alias.asname or alias.name)
                aliases[alias.asname or alias.name] = module + "." + alias.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            locally_bound.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                    locally_bound.add(arg.arg)
                if node.args.vararg:
                    locally_bound.add(node.args.vararg.arg)
                if node.args.kwarg:
                    locally_bound.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Param)):
                locally_bound.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                loaded_names.append(node)

    for node in loaded_names:
        if node.id not in locally_bound and node.id not in _BUILTINS:
            findings.append(Diagnostic(
                status=Status.UNKNOWN,
                code="PY_NAME_UNRESOLVED",
                message=f"Name {node.id!r} is not defined inside the current draft.",
                source=source_name,
                line=node.lineno,
                column=node.col_offset + 1,
                suggestion="Resolve from enclosing/project context or define/import the symbol explicitly.",
                blocking=False,
                probe={"kind": "SYMBOL_SEARCH", "symbol": node.id},
            ))

    if index is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                continue
            alias = node.value.id
            imported = aliases.get(alias)
            if imported is None or "." in imported and alias != imported.split(".")[0]:
                continue
            resolved_module = index.resolve_module(imported)
            if resolved_module is None:
                continue
            symbol = index.resolve_symbol(resolved_module, node.attr)
            module_path = index.modules[resolved_module]
            module_sha = index.source_sha(module_path) or ""
            evidence = EvidenceRef(
                source_kind="SOURCE_INDEX",
                source_id=module_path,
                source_sha256=module_sha,
                epistemic_class="OBSERVED_CONTENT_BOUND",
            )
            if symbol is None:
                findings.append(Diagnostic(
                    status=Status.FAIL,
                    code="PY_MODULE_ATTRIBUTE_MISSING",
                    message=f"Verified project module {resolved_module!r} has no top-level symbol {node.attr!r}.",
                    source=source_name,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    suggestion=f"Search {module_path} for the verified helper/signature and use that instead.",
                    blocking=True,
                    evidence=(evidence,),
                ))
            else:
                findings.append(Diagnostic(
                    status=Status.PASS,
                    code="PY_MODULE_ATTRIBUTE_VERIFIED",
                    message=f"{resolved_module}.{node.attr} exists in indexed source.",
                    source=source_name,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    blocking=False,
                    evidence=(evidence,),
                ))
    return findings
