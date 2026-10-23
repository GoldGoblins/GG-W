"""Local-only QIP/WASM inspection and execution boundary.

QIP's useful property for GG AI Desktop is the narrow component boundary:
explicit bytes in, explicit bytes out, and no host imports.  This module
implements the first native desktop slice without adding a WASM dependency:
it parses the module header/sections itself and, when Node is available, runs
only import-free modules exposing the QIP-style ``render`` ABI.  It never
downloads a module, grants host imports, or writes the selected file.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import unquote, urlparse


SCHEMA = "gg.qip.wasm-lab.v1"
MAX_MODULE_BYTES = 1_048_576
MAX_MEMORY_PAGES = 2048  # 128 MiB, matching the QIP debugger boundary.
MAX_TABLE_ENTRIES = 4096
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 1 * 1024 * 1024
RUN_TIMEOUT_SECONDS = 4.0


class WasmFormatError(ValueError):
    pass


def _path_from_url(raw: str | os.PathLike[str]) -> Path:
    value = str(raw or "").strip()
    if value.startswith("file:"):
        parsed = urlparse(value)
        if parsed.scheme != "file":
            raise WasmFormatError("QIP_FILE_SCHEME")
        value = unquote(parsed.path)
    path = Path(value).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise WasmFormatError("QIP_FILE_NOT_FOUND") from exc
    if not path.is_file():
        raise WasmFormatError("QIP_FILE_NOT_FOUND")
    return path


def _u32(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift <= 35:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise WasmFormatError("QIP_BAD_LEB")


def _string(data: bytes, offset: int) -> tuple[str, int]:
    size, offset = _u32(data, offset)
    end = offset + size
    if end > len(data):
        raise WasmFormatError("QIP_TRUNCATED_STRING")
    return data[offset:end].decode("utf-8", errors="replace"), end


def _limits(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    flags, offset = _u32(data, offset)
    minimum, offset = _u32(data, offset)
    maximum: int | None = None
    if flags & 0x01:
        maximum, offset = _u32(data, offset)
    return {
        "min": minimum,
        "max": maximum,
        "shared": bool(flags & 0x02),
        "memory64": bool(flags & 0x04),
    }, offset


def _kind_name(kind: int) -> str:
    return {
        0: "FUNCTION",
        1: "TABLE",
        2: "MEMORY",
        3: "GLOBAL",
        4: "TAG",
    }.get(kind, "UNKNOWN")


def _parse_imports(data: bytes) -> list[dict[str, Any]]:
    count, offset = _u32(data, 0)
    rows: list[dict[str, Any]] = []
    for _ in range(count):
        module, offset = _string(data, offset)
        name, offset = _string(data, offset)
        kind = data[offset]
        offset += 1
        row: dict[str, Any] = {
            "module": module,
            "name": name,
            "kind": _kind_name(kind),
        }
        if kind == 0:
            _type_index, offset = _u32(data, offset)
        elif kind == 1:
            element_type = data[offset]
            offset += 1
            limits, offset = _limits(data, offset)
            row["table"] = {"element_type": element_type, **limits}
        elif kind == 2:
            limits, offset = _limits(data, offset)
            row["memory"] = limits
        elif kind == 3:
            if offset + 2 > len(data):
                raise WasmFormatError("QIP_TRUNCATED_GLOBAL")
            offset += 2  # value type + mutability
        elif kind == 4:
            _attribute, offset = _u32(data, offset)
            _type_index, offset = _u32(data, offset)
        else:
            raise WasmFormatError("QIP_UNKNOWN_IMPORT_KIND")
        rows.append(row)
    return rows


def _parse_exports(data: bytes) -> list[dict[str, Any]]:
    count, offset = _u32(data, 0)
    rows: list[dict[str, Any]] = []
    for _ in range(count):
        name, offset = _string(data, offset)
        if offset + 1 > len(data):
            raise WasmFormatError("QIP_TRUNCATED_EXPORT")
        kind = data[offset]
        offset += 1
        index, offset = _u32(data, offset)
        rows.append({"name": name, "kind": _kind_name(kind), "index": index})
    return rows


def _parse_limits_section(data: bytes, *, table: bool) -> list[dict[str, Any]]:
    count, offset = _u32(data, 0)
    rows: list[dict[str, Any]] = []
    for _ in range(count):
        row: dict[str, Any] = {}
        if table:
            if offset >= len(data):
                raise WasmFormatError("QIP_TRUNCATED_TABLE")
            row["element_type"] = data[offset]
            offset += 1
        limits, offset = _limits(data, offset)
        rows.append({**row, **limits})
    return rows


def _section_rows(data: bytes) -> list[tuple[int, bytes]]:
    if len(data) < 8 or data[:4] != b"\x00asm" or data[4:8] != b"\x01\x00\x00\x00":
        raise WasmFormatError("QIP_BAD_WASM_HEADER")
    offset = 8
    rows: list[tuple[int, bytes]] = []
    while offset < len(data):
        section_id = data[offset]
        offset += 1
        size, offset = _u32(data, offset)
        end = offset + size
        if end > len(data):
            raise WasmFormatError("QIP_TRUNCATED_SECTION")
        rows.append((section_id, data[offset:end]))
        offset = end
    return rows


def _limits_view(rows: list[dict[str, Any]], *, table: bool) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        minimum = int(row.get("min") or 0)
        maximum = row.get("max")
        entry: dict[str, Any] = {
            "min": minimum,
            "max": int(maximum) if maximum is not None else None,
        }
        if table:
            entry["element_type"] = int(row.get("element_type") or 0)
            entry["limit_ok"] = minimum <= MAX_TABLE_ENTRIES and (
                maximum is None or int(maximum) <= MAX_TABLE_ENTRIES
            )
        else:
            entry["min_bytes"] = minimum * 65536
            entry["max_bytes"] = (
                int(maximum) * 65536 if maximum is not None else None
            )
            entry["limit_ok"] = minimum <= MAX_MEMORY_PAGES and (
                maximum is None or int(maximum) <= MAX_MEMORY_PAGES
            )
        output.append(entry)
    return output


def inspect_bytes(data: bytes, *, name: str = "module.wasm") -> dict[str, Any]:
    if len(data) > MAX_MODULE_BYTES:
        return {
            "schema": SCHEMA,
            "state": "BLOCKED",
            "reason": "QIP_MODULE_TOO_LARGE",
            "name": name,
            "bytes": len(data),
        }
    try:
        sections = _section_rows(data)
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        function_count = 0
        custom_sections = 0
        for section_id, payload in sections:
            if section_id == 0:
                custom_sections += 1
            elif section_id == 2:
                imports.extend(_parse_imports(payload))
            elif section_id == 3:
                function_count, _ = _u32(payload, 0)
            elif section_id == 4:
                tables.extend(_parse_limits_section(payload, table=True))
            elif section_id == 5:
                memories.extend(_parse_limits_section(payload, table=False))
            elif section_id == 7:
                exports.extend(_parse_exports(payload))
        imported_memories = [row.get("memory") for row in imports if row.get("kind") == "MEMORY"]
        imported_tables = [row.get("table") for row in imports if row.get("kind") == "TABLE"]
        memory_view = _limits_view(
            memories + [row for row in imported_memories if isinstance(row, dict)],
            table=False,
        )
        table_view = _limits_view(
            tables + [row for row in imported_tables if isinstance(row, dict)],
            table=True,
        )
        has_imports = bool(imports)
        memory_ok = all(bool(row.get("limit_ok")) for row in memory_view)
        table_ok = all(bool(row.get("limit_ok")) for row in table_view)
        memory_count_ok = len(memory_view) <= 1
        table_count_ok = len(table_view) <= 1
        state = (
            "READY"
            if not has_imports
            and memory_ok
            and table_ok
            and memory_count_ok
            and table_count_ok
            else "BLOCKED"
        )
        reason = "" if state == "READY" else (
            "QIP_HOST_IMPORTS" if has_imports else (
                "QIP_MEMORY_COUNT" if not memory_count_ok else (
                    "QIP_MEMORY_LIMIT" if not memory_ok else (
                        "QIP_TABLE_COUNT" if not table_count_ok else "QIP_TABLE_LIMIT"
                    )
                )
            )
        )
        return {
            "schema": SCHEMA,
            "state": state,
            "reason": reason,
            "name": name,
            "bytes": len(data),
            "version": 1,
            "sections": len(sections),
            "custom_sections": custom_sections,
            "function_count": function_count,
            "imports": imports,
            "exports": exports,
            "memories": memory_view,
            "tables": table_view,
            "limits": {
                "max_module_bytes": MAX_MODULE_BYTES,
                "max_memory_bytes": MAX_MEMORY_PAGES * 65536,
                "max_table_entries": MAX_TABLE_ENTRIES,
            },
            "qip_abi": {
                "render_export": any(
                    row.get("name") == "render" and row.get("kind") == "FUNCTION"
                    for row in exports
                ),
                "memory_export": any(
                    row.get("name") == "memory" and row.get("kind") == "MEMORY"
                    for row in exports
                ),
                "input_pointer_export": any(
                    row.get("name") == "input_ptr" and row.get("kind") == "GLOBAL"
                    for row in exports
                ),
            },
            "execution": {
                "local_only": True,
                "imports_allowed": False,
                "runtime": "node" if shutil.which("node") else "missing",
            },
        }
    except (IndexError, ValueError, WasmFormatError) as exc:
        return {
            "schema": SCHEMA,
            "state": "BLOCKED",
            "reason": str(exc) or "QIP_BAD_WASM",
            "name": name,
            "bytes": len(data),
        }


def inspect_file(raw_path: str) -> dict[str, Any]:
    try:
        path = _path_from_url(raw_path)
        if path.suffix.lower() != ".wasm":
            raise WasmFormatError("QIP_EXPECTED_WASM")
        data = path.read_bytes()
        result = inspect_bytes(data, name=path.name)
        result["path"] = str(path)
        return result
    except (OSError, WasmFormatError) as exc:
        return {
            "schema": SCHEMA,
            "state": "BLOCKED",
            "reason": str(exc) or "QIP_FILE_READ",
            "name": Path(str(raw_path or "module.wasm")).name,
        }


_NODE_RUNNER = r'''
const fs = require("fs");

function globalValue(exports, name, fallback = null) {
  const value = exports[name];
  if (value && typeof value === "object" && "value" in value) {
    return Number(value.value);
  }
  return fallback;
}

function runOnce(bytes, input) {
  return WebAssembly.instantiate(bytes, {}).then((instance) => {
    const exp = instance.instance.exports;
    if (typeof exp.render !== "function") throw new Error("QIP_RENDER_EXPORT_MISSING");
    if (!exp.memory || !(exp.memory instanceof WebAssembly.Memory)) {
      throw new Error("QIP_MEMORY_EXPORT_MISSING");
    }
    const ptr = globalValue(exp, "input_ptr", 0);
    const cap = globalValue(exp, "input_utf8_cap", exp.memory.buffer.byteLength - ptr);
    if (!Number.isSafeInteger(ptr) || ptr < 0 || ptr > exp.memory.buffer.byteLength) {
      throw new Error("QIP_INPUT_POINTER_INVALID");
    }
    if (input.length > cap) throw new Error("QIP_INPUT_TOO_LARGE");
    new Uint8Array(exp.memory.buffer, ptr, input.length).set(input);
    const result = exp.render(input.length);
    let outputPtr = globalValue(exp, "output_ptr", null);
    let outputLen = globalValue(exp, "output_len", null);
    if (typeof result === "bigint") {
      outputPtr = Number((result >> 32n) & 0xffffffffn);
      outputLen = Number(result & 0xffffffffn);
    } else if (outputLen === null && Number.isSafeInteger(result) && result >= 0) {
      outputLen = Number(result);
    }
    if (!Number.isSafeInteger(outputPtr) || !Number.isSafeInteger(outputLen) || outputPtr < 0 || outputLen < 0) {
      throw new Error("QIP_OUTPUT_ABI_MISSING");
    }
    if (outputLen > 1048576 || outputPtr + outputLen > exp.memory.buffer.byteLength) {
      throw new Error("QIP_OUTPUT_LIMIT");
    }
    return Buffer.from(new Uint8Array(exp.memory.buffer, outputPtr, outputLen));
  });
}

async function main() {
  const file = process.argv[1];
  const input = Buffer.from(process.argv[2] || "", "base64");
  const bytes = fs.readFileSync(file);
  const first = await runOnce(bytes, input);
  const second = await runOnce(bytes, input);
  process.stdout.write(JSON.stringify({
    output_base64: first.toString("base64"),
    output_bytes: first.length,
    deterministic: first.equals(second),
  }));
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ error: String(error.message || error) }));
  process.exitCode = 2;
});
'''


def run_file(raw_path: str, input_text: str) -> dict[str, Any]:
    inspection = inspect_file(raw_path)
    if inspection.get("state") != "READY":
        return {"schema": SCHEMA, "state": "BLOCKED", "inspection": inspection}
    try:
        path = _path_from_url(raw_path)
        input_bytes = str(input_text or "").encode("utf-8")
        if len(input_bytes) > MAX_INPUT_BYTES:
            return {
                "schema": SCHEMA,
                "state": "BLOCKED",
                "reason": "QIP_INPUT_TOO_LARGE",
                "inspection": inspection,
            }
        node = shutil.which("node")
        if not node:
            return {
                "schema": SCHEMA,
                "state": "RUNTIME_MISSING",
                "reason": "NODE_RUNTIME_NOT_FOUND",
                "inspection": inspection,
            }
        started = time.monotonic()
        completed = subprocess.run(
            [
                node,
                "-e",
                _NODE_RUNNER,
                str(path),
                base64.b64encode(input_bytes).decode("ascii"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=RUN_TIMEOUT_SECONDS,
            env={
                "PATH": os.environ.get("PATH", ""),
                "NODE_NO_WARNINGS": "1",
            },
        )
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"error": "QIP_RUNTIME_OUTPUT_INVALID"}
        if completed.returncode != 0 or payload.get("error"):
            return {
                "schema": SCHEMA,
                "state": "ERROR",
                "reason": str(payload.get("error") or "QIP_RUNTIME_ERROR"),
                "inspection": inspection,
                "duration_ms": elapsed_ms,
            }
        output_b64 = str(payload.get("output_base64") or "")
        try:
            output_bytes = base64.b64decode(output_b64, validate=True)
        except (ValueError, base64.binascii.Error):
            return {
                "schema": SCHEMA,
                "state": "ERROR",
                "reason": "QIP_OUTPUT_INVALID",
                "inspection": inspection,
                "duration_ms": elapsed_ms,
            }
        if len(output_bytes) > MAX_OUTPUT_BYTES:
            return {
                "schema": SCHEMA,
                "state": "ERROR",
                "reason": "QIP_OUTPUT_LIMIT",
                "inspection": inspection,
                "duration_ms": elapsed_ms,
            }
        return {
            "schema": SCHEMA,
            "state": "DONE",
            "reason": "",
            "inspection": inspection,
            "input_bytes": len(input_bytes),
            "output_bytes": len(output_bytes),
            "output_text": output_bytes.decode("utf-8", errors="replace"),
            "output_base64": output_b64,
            "deterministic": bool(payload.get("deterministic")),
            "duration_ms": elapsed_ms,
        }
    except subprocess.TimeoutExpired:
        return {
            "schema": SCHEMA,
            "state": "TIMEOUT",
            "reason": "QIP_RUNTIME_TIMEOUT",
            "inspection": inspection,
        }
    except (OSError, ValueError) as exc:
        return {
            "schema": SCHEMA,
            "state": "ERROR",
            "reason": str(exc) or "QIP_RUNTIME_ERROR",
            "inspection": inspection,
        }
