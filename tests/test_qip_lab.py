#!/usr/bin/env python3
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import qip_lab


def uleb(value: int) -> bytes:
    out = bytearray()
    number = int(value)
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + uleb(len(payload)) + payload


def minimal_qip_module() -> bytes:
    # render(i32) -> i64; the packed return is output_ptr=16, output_len=2.
    type_payload = bytes([1, 0x60, 1, 0x7F, 1, 0x7E])
    function_payload = bytes([1, 0])
    memory_payload = bytes([1, 0, 1])
    packed = (16 << 32) | 2
    body = bytes([0, 0x42]) + uleb(packed) + bytes([0x0B])
    code_payload = bytes([1]) + uleb(len(body)) + body
    export_payload = (
        bytes([2])
        + bytes([6]) + b"memory" + bytes([2, 0])
        + bytes([6]) + b"render" + bytes([0, 0])
    )
    data_payload = (
        bytes([1, 0, 0x41, 16, 0x0B, 2]) + b"OK"
    )
    return (
        b"\x00asm\x01\x00\x00\x00"
        + section(1, type_payload)
        + section(3, function_payload)
        + section(5, memory_payload)
        + section(7, export_payload)
        + section(10, code_payload)
        + section(11, data_payload)
    )


def main() -> int:
    module = minimal_qip_module()
    inspected = qip_lab.inspect_bytes(module, name="fixture.wasm")
    assert inspected["state"] == "READY", inspected
    assert inspected["qip_abi"]["render_export"] is True
    assert inspected["qip_abi"]["memory_export"] is True
    assert inspected["memories"][0]["min_bytes"] == 65536

    too_large = qip_lab.inspect_bytes(
        b"\x00asm\x01\x00\x00\x00" + b"x" * (qip_lab.MAX_MODULE_BYTES + 1),
        name="large.wasm",
    )
    assert too_large["reason"] == "QIP_MODULE_TOO_LARGE"

    with tempfile.TemporaryDirectory(prefix="gg-qip-") as raw_dir:
        path = Path(raw_dir) / "fixture.wasm"
        path.write_bytes(module)
        result = qip_lab.run_file(str(path), "hello")
        if shutil.which("node"):
            assert result["state"] == "DONE", result
            assert result["output_text"] == "OK"
            assert result["deterministic"] is True
        else:
            assert result["state"] == "RUNTIME_MISSING"

    print("test_qip_lab: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
