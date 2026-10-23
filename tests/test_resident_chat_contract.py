from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.resident_chat_runner import (
        PROMPT_DELIMITER,
        PromptFramer,
        classify_runtime_failure,
        transport_encode,
    )

    multiline = "rad ett\nrad två\nåäö"
    encoded = transport_encode(multiline)
    assert encoded.endswith(b"\n")
    assert b"\n" not in encoded[:-1]
    assert b"\r" not in encoded[:-1]
    assert json.loads(encoded[:-1].decode("utf-8")) == multiline

    framer = PromptFramer()
    target = "Första å svar"
    payload = target.encode("utf-8") + PROMPT_DELIMITER
    split = payload.index("å".encode("utf-8")) + 1
    frames: list[bytes] = []
    for chunk in (
        payload[:split],
        payload[split : split + 2],
        payload[split + 2 : -2],
        payload[-2:],
    ):
        produced, _remainder = framer.feed(chunk)
        frames.extend(produced)
    assert frames == [target.encode("utf-8")]

    assert classify_runtime_failure(
        "Error: decode() failed: vk::CommandBuffer::end: ErrorOutOfDeviceMemory"
    ) == "VULKAN_OUT_OF_DEVICE_MEMORY"
    assert classify_runtime_failure(
        "Hej! Hur kan jag hjälpa dig idag?"
    ) == ""
    assert classify_runtime_failure(
        "",
        "ggml-vulkan: decode() failed",
    ) == "MODEL_DECODE_FAILED"
    assert classify_runtime_failure(
        "Error: request (2102 tokens) exceeds the available context size (2048 tokens)"
    ) == "CONTEXT_OVERFLOW"
    assert classify_runtime_failure(
        "",
        "gguf_init_from_file: failed to open GGUF file '/models/x.gguf' (Permission denied)",
    ) == "MODEL_FILE_PERMISSION_DENIED"

    runner = (PROJECT / "backend" / "resident_chat_runner.py").read_text(
        encoding="utf-8"
    )
    qt = (PROJECT / "backend" / "resident_chat_qt.py").read_text(
        encoding="utf-8"
    )
    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")
    main_qml = (PROJECT / "qml" / "Main.qml").read_text(encoding="utf-8")

    for marker in (
        '"--network=none"',
        '"--read-only"',
        '"--cap-drop=all"',
        '"--reasoning"',
        '"off"',
        '"--reasoning-budget"',
        '"0"',
        '"--no-reasoning-preserve"',
        '"--ctx-size"',
        '"2048"',
        '"--gpu-layers"',
        '"33"',
        "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "qwen25-coder-7b-instruct-q4_k_m",
        "relabel=private",
        '"--conversation"',
        '"--simple-io"',
        "MODEL_SHA256",
        "RUNTIME_IMAGE_DIGEST",
        "PROMPT_DELIMITER = b\"\\n\\n> \"",
        "transport_encode(prompt)",
        'SELFTEST=SAFE_NO_HOST_IO',
        "GG_TOOL_REQUEST=",
        '{"profile":"TEST"}',
        '{"profile":"RUN"}',
        "GG_EDIT_PROPOSAL=",
        "session: ResidentModelSession | None = None",
        "if session is not None:",
        "EVIDENCE_RUNTIME_UNWRITABLE:",
        '_emit("SESSION_STARTING", evidence=str(self.evidence))',
        "def classify_runtime_failure(",
        "RESIDENT_RUNTIME_FAILURE:",
        "blocking_podman_containers(",
        "localhost/gg-site-php",
        "CONTEXT_OVERFLOW",
        "Ingen öppen shell",
        "Inget modell-nät",
        "Allowlistad",
    ):
        assert marker in runner, marker

    for marker in (
        "class ResidentChatTransport(QObject):",
        "def submit(",
        "def stop(",
        "def shutdown_idle(",
        "beginStreamingResponse",
        "updateStreamingResponse",
        '"STREAMING"',
        '"PASS"',
        '"CANCELLED"',
        "split_think_delta(",
        "_split_think_delta(",
        '"Thought"',
        "_continue_with_information_tool(",
        "execute_host_tool(",
        "TERMINAL_RUN",
        "extract_tool_request(",
        "extract_model_host_actions(",
        "_run_host_action_batch(",
        "classify_runtime_failure(",
        "RESIDENT_RUNTIME_FAILURE:",
        "ENGINE_GROK_WORKER",
        "accept_followup(",
        "self._grok_worker().submit(",
        "upsertGrokWorkerCard",
        "_upsert_stream_card(",
        "_accumulate_narrative(",
    ):
        assert marker in qt, marker

    for marker in (
        "ResidentChatTransport(",
        "self._resident_chat.submit(",
        "self._resident_chat.stop()",
        "compile_chat_prompt(",
    ):
        assert marker in main_py, marker

    for marker in (
        "function beginStreamingResponse(",
        '"stateLabel": "STARTING"',
        "function updateStreamingResponse(requestId, bodyText, stateLabel)",
        'chatModel.setProperty(i, "bodyText", bodyText)',
        'chatModel.setProperty(i, "stateLabel", stateLabel)',
    ):
        assert marker in main_qml, marker

    live = PROJECT / "tests" / "controllers" / "live"
    if str(live) not in sys.path:
        sys.path.insert(0, str(live))
    import autonomous_read_search_host as proof

    assert proof.proof_process_exit_code(True, 0) == 0
    assert proof.proof_process_exit_code(True, 72) == 0
    assert proof.proof_process_exit_code(False, 0) == 72
    assert proof.proof_process_exit_code(False, 72) == 72
    assert proof.proof_process_exit_code(False, 73) == 73

    from backend.resident_chat_qt import split_think_delta

    first, thinking = split_think_delta("Hej <think>plan", False)
    assert first == [("text", "Hej "), ("thought", "plan")]
    assert thinking is True
    second, thinking = split_think_delta(" mer</think> svar", thinking)
    assert second == [("thought", " mer"), ("text", " svar")]
    assert thinking is False

    from backend.resident_chat_runner import blocking_podman_containers

    assert blocking_podman_containers(
        [
            "silly-php\tlocalhost/gg-site-php:1",
            "gg-resident-chat-abc\tlocalhost/gg-llama-cpp-vulkan:b10182",
        ]
    ) == []
    assert blocking_podman_containers(
        ["other\tdocker.io/library/nginx:latest"]
    ) == ["other"]

    print("RESIDENT_CHAT_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
