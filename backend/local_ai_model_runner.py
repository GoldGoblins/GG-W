#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from types import ModuleType
from typing import Any


REPO = pathlib_repo = Path(
    "/home/GG/GoldGoblins"
)

PROJECT = (
    REPO
    / "projects/gg-ai-desktop"
)

CONTRACT_PATH = (
    PROJECT
    / "backend/local_ai_contract.py"
)

CONTRACT_SHA = (
    "740849d413a3461d40ee83cba71c46f8"
    "1ec2447ea351942e47868f3478a012d1"
)

MODEL_DIR = Path(
    "/home/GG/models/qwen3-4b-q5_k_m"
)

MODEL_PATH = (
    MODEL_DIR
    / "Qwen3-4B-Q5_K_M.gguf"
)

MODEL_SHA = (
    "aca596860e8cb40af6539e3f2ea40df"
    "305f42515deac56d49c08d39a02e6533f"
)

MODEL_BYTES = 2889513184

RUNTIME_IMAGE = (
    "localhost/gg-llama-cpp-vulkan:b10182"
)

RUNTIME_IMAGE_ID = (
    "0a4db391fe04f0a5370ccc04bf2b9c39"
    "60180e569092a1e51a48d30ab425d178"
)

RUNTIME_IMAGE_DIGEST = (
    "sha256:"
    "61f81360fdf2d10c069cf183d1a8671f"
    "19977015d8fd42ef9868654c44697e44"
)

REQUEST_ID = (
    "wb3d-synthetic-001"
)

PROMPT = (
    "Detta är syntetisk testdata. "
    "Svara kort på svenska och inkludera "
    "markören GG_MODEL_RUNNER_OK."
)

MARKER = (
    "GG_MODEL_RUNNER_OK"
)

MODEL_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "text"
    ],
    "properties": {
        "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
        }
    },
}
MODEL_GBNF = (
    'char ::= [^"\\\\\\x7F\\x00-\\x1F] | [\\\\] (["\\\\bfnrt] | "u" [0-9a-fA-F]{4})\n'
    'root ::= "{" space text-kv space "}"\n'
    'space ::= | " " | "\\n"{1,2} [ \\t]{0,20}\n'
    'text ::= "\\"" char{1,100} "\\""\n'
    'text-kv ::= "\\"text\\"" space ":" space text\n'
)



class RunnerStop(
    RuntimeError
):
    pass


def sha256_bytes(
    data: bytes,
) -> str:
    return hashlib.sha256(
        data
    ).hexdigest()


def sha256_file(
    path: Path,
) -> str:
    if (
        not path.is_file()
        or path.is_symlink()
    ):
        raise RunnerStop(
            "unsafe_file:"
            + str(path)
        )

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def write_new(
    path: Path,
    data: bytes,
    mode: int = 0o600,
) -> None:
    if (
        path.exists()
        or path.is_symlink()
    ):
        raise RunnerStop(
            "evidence_path_exists:"
            + str(path)
        )

    fd = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL,
        mode,
    )

    with os.fdopen(
        fd,
        "wb",
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(
            handle.fileno()
        )

    os.chmod(
        path,
        mode,
    )


def json_bytes(
    value: Any,
) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode(
        "utf-8"
    )


def run_checked(
    argv: list[str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def container_exists(
    name: str,
) -> bool:
    result = run_checked(
        [
            "podman",
            "container",
            "exists",
            name,
        ]
    )

    if result.returncode == 0:
        return True

    if result.returncode == 1:
        return False

    raise RunnerStop(
        "podman_container_exists_failed:"
        + name
        + ":"
        + result.stderr.decode(
            "utf-8",
            errors="replace",
        )
    )


def remove_owned_container(
    name: str,
) -> None:
    if not container_exists(
        name
    ):
        return

    result = run_checked(
        [
            "podman",
            "rm",
            "-f",
            name,
        ]
    )

    if result.returncode != 0:
        raise RunnerStop(
            "owned_container_cleanup_failed:"
            + name
            + ":"
            + result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )


def require_podman_empty(
    label: str,
) -> None:
    containers = run_checked(
        [
            "podman",
            "ps",
            "-aq",
        ]
    )

    volumes = run_checked(
        [
            "podman",
            "volume",
            "ls",
            "-q",
        ]
    )

    if containers.returncode != 0:
        raise RunnerStop(
            "podman_ps_failed:"
            + label
        )

    if volumes.returncode != 0:
        raise RunnerStop(
            "podman_volume_ls_failed:"
            + label
        )

    if containers.stdout.strip():
        raise RunnerStop(
            "podman_containers_not_empty:"
            + label
        )

    if volumes.stdout.strip():
        raise RunnerStop(
            "podman_volumes_not_empty:"
            + label
        )


def inspect_image() -> None:
    result = run_checked(
        [
            "podman",
            "image",
            "inspect",
            RUNTIME_IMAGE,
        ]
    )

    if result.returncode != 0:
        raise RunnerStop(
            "runtime_image_inspect_failed:"
            + result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    try:
        items = json.loads(
            result.stdout.decode(
                "utf-8",
                errors="strict",
            )
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RunnerStop(
            "runtime_image_inspect_json:"
            + repr(exc)
        ) from exc

    if (
        not isinstance(
            items,
            list,
        )
        or len(items) != 1
    ):
        raise RunnerStop(
            "runtime_image_cardinality"
        )

    image = items[0]

    if not isinstance(
        image,
        dict,
    ):
        raise RunnerStop(
            "runtime_image_type"
        )

    config = (
        image.get(
            "Config"
        )
        or {}
    )

    if not isinstance(
        config,
        dict,
    ):
        raise RunnerStop(
            "runtime_image_config_type"
        )

    image_id = str(
        image.get(
            "Id",
            "",
        )
    ).removeprefix(
        "sha256:"
    )

    digest = str(
        image.get(
            "Digest",
            "",
        )
    )

    if image_id != RUNTIME_IMAGE_ID:
        raise RunnerStop(
            "runtime_image_id_drift"
        )

    if digest != RUNTIME_IMAGE_DIGEST:
        raise RunnerStop(
            "runtime_image_digest_drift"
        )

    if image.get("Os") != "linux":
        raise RunnerStop(
            "runtime_image_os_drift"
        )

    if (
        image.get(
            "Architecture"
        )
        != "amd64"
    ):
        raise RunnerStop(
            "runtime_image_arch_drift"
        )

    if (
        config.get(
            "User"
        )
        != "1000:1000"
    ):
        raise RunnerStop(
            "runtime_image_user_drift"
        )

    if (
        config.get(
            "WorkingDir"
        )
        != "/work"
    ):
        raise RunnerStop(
            "runtime_image_workdir_drift"
        )

    if (
        config.get(
            "Entrypoint"
        )
        != [
            "/usr/local/bin/llama-cli"
        ]
    ):
        raise RunnerStop(
            "runtime_image_entrypoint_drift"
        )

    if config.get("Cmd") is not None:
        raise RunnerStop(
            "runtime_image_cmd_drift"
        )


def discover_nvidia_render() -> Path:
    dri = Path(
        "/dev/dri"
    )

    if not dri.is_dir():
        raise RunnerStop(
            "dri_directory_missing"
        )

    candidates: list[Path] = []

    for node in sorted(
        dri.glob(
            "renderD*"
        )
    ):
        if node.is_symlink():
            raise RunnerStop(
                "render_node_symlink:"
                + str(node)
            )

        info = node.stat()

        if not stat.S_ISCHR(
            info.st_mode
        ):
            raise RunnerStop(
                "render_node_not_char_device:"
                + str(node)
            )

        vendor_path = (
            Path(
                "/sys/class/drm"
            )
            / node.name
            / "device/vendor"
        )

        if not vendor_path.is_file():
            continue

        vendor = vendor_path.read_text(
            encoding="ascii"
        ).strip().lower()

        if (
            vendor == "0x10de"
            and os.access(
                node,
                os.R_OK,
            )
            and os.access(
                node,
                os.W_OK,
            )
        ):
            candidates.append(
                node
            )

    if len(candidates) != 1:
        raise RunnerStop(
            "accessible_nvidia_render_cardinality:"
            + repr(
                [
                    str(path)
                    for path in candidates
                ]
            )
        )

    return candidates[0]


def load_contract() -> ModuleType:
    if (
        sha256_file(
            CONTRACT_PATH
        )
        != CONTRACT_SHA
    ):
        raise RunnerStop(
            "contract_sha_drift"
        )

    spec = (
        importlib.util.spec_from_file_location(
            "gg_wb3d_local_ai_contract",
            CONTRACT_PATH,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RunnerStop(
            "contract_import_spec_failed"
        )

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def parse_model_stdout(
    raw: bytes,
) -> str:
    try:
        text = raw.decode(
            "utf-8",
            errors="strict",
        )
    except UnicodeDecodeError as exc:
        raise RunnerStop(
            "model_stdout_not_utf8:"
            + repr(exc)
        ) from exc

    if not text.strip():
        raise RunnerStop(
            "model_stdout_empty"
        )

    decoder = json.JSONDecoder()
    decoded_candidates = []

    for offset, character in enumerate(text):
        if character != "{":
            continue

        try:
            value, end_relative = decoder.raw_decode(
                text[offset:]
            )
        except json.JSONDecodeError:
            continue

        decoded_candidates.append(
            (
                offset,
                offset + end_relative,
                value,
            )
        )

    response_candidates = [
        item
        for item in decoded_candidates
        if (
            type(item[2]) is dict
            and set(item[2]) == {"text"}
            and type(item[2]["text"]) is str
        )
    ]

    if not response_candidates:
        raise RunnerStop(
            "model_stdout_response_json_missing"
        )

    _start, end, value = max(
        response_candidates,
        key=lambda item: item[0],
    )

    if any(
        start >= end
        for start, _end, _value
        in decoded_candidates
    ):
        raise RunnerStop(
            "model_stdout_trailing_json_after_response"
        )

    answer = value["text"]

    if (
        type(answer) is not str
        or not answer.strip()
    ):
        raise RunnerStop(
            "model_text_empty_or_invalid"
        )

    if len(answer) > 65536:
        raise RunnerStop(
            "model_text_too_long"
        )

    if MARKER not in answer:
        raise RunnerStop(
            "model_marker_missing"
        )

    return answer


def runtime_base_args(
    name: str,
) -> list[str]:
    return [
        "podman",
        "run",
        "--rm",
        "--name",
        name,
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
        "--user=1000:1000",
        "--userns=keep-id",
        "--pids-limit=256",
        "--memory=8g",
        "--memory-swap=8g",
        "--cpus=6",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=512m",
        "--env",
        "HOME=/tmp",
        "--env",
        "XDG_CACHE_HOME=/tmp/.cache",
    ]


def run_named_container(
    argv: list[str],
    name: str,
    timeout_seconds: int,
) -> tuple[
    int,
    bytes,
    bytes,
    int,
    bool,
]:
    started = time.monotonic()

    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    timed_out = False

    try:
        stdout, stderr = (
            process.communicate(
                timeout=timeout_seconds
            )
        )

    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()

        stdout, stderr = (
            process.communicate()
        )

    duration_ms = int(
        (
            time.monotonic()
            - started
        )
        * 1000
    )

    if container_exists(
        name
    ):
        remove_owned_container(
            name
        )

        if not timed_out:
            raise RunnerStop(
                "runtime_container_leftover:"
                + name
            )

    if timed_out:
        return (
            124,
            stdout,
            stderr,
            duration_ms,
            True,
        )

    return (
        process.returncode,
        stdout,
        stderr,
        duration_ms,
        False,
    )


def validate_evidence_dir(
    path: Path,
) -> Path:
    if (
        path.is_symlink()
        or not path.is_dir()
    ):
        raise RunnerStop(
            "evidence_root_unsafe"
        )

    resolved = path.resolve(
        strict=True
    )

    expected_parent = Path(
        f"/run/user/{os.getuid()}"
    ).resolve(
        strict=True
    )

    if (
        resolved.parent
        != expected_parent
    ):
        raise RunnerStop(
            "evidence_root_parent_invalid"
        )

    if not resolved.name.startswith(
        "gg-wb3d-model-runner."
    ):
        raise RunnerStop(
            "evidence_root_name_invalid"
        )

    info = resolved.stat()

    if info.st_uid != os.getuid():
        raise RunnerStop(
            "evidence_root_owner_invalid"
        )

    if stat.S_IMODE(
        info.st_mode
    ) != 0o700:
        raise RunnerStop(
            "evidence_root_mode_invalid"
        )

    return resolved


def selftest() -> int:
    good = (
        b'{"text":"Kort syntetiskt '
        b'GG_MODEL_RUNNER_OK svar."}'
    )

    if (
        parse_model_stdout(
            good
        )
        != (
            "Kort syntetiskt "
            "GG_MODEL_RUNNER_OK svar."
        )
    ):
        print(
            "SELFTEST_PARSE_MISMATCH",
            file=sys.stderr,
        )
        return 1

    bad_values = (
        (
            b'{"text":"GG_MODEL_RUNNER_OK",'
            b'"status":"PASS"}'
        ),
        b'{"text":""}',
        b'{"text":"marker saknas"}',
        b'not-json',
    )

    for raw in bad_values:
        try:
            parse_model_stdout(
                raw
            )

        except RunnerStop:
            continue

        print(
            "SELFTEST_NEGATIVE_CASE_ACCEPTED",
            file=sys.stderr,
        )
        return 1

    if set(
        MODEL_JSON_SCHEMA[
            "properties"
        ]
    ) != {
        "text"
    }:
        print(
            "SELFTEST_SCHEMA_FIELD_SET",
            file=sys.stderr,
        )
        return 1

    print(
        "WB3D_MODEL_RUNNER_SELFTEST=PASS"
    )

    print(
        "WB3D_MODEL_RUNNER_SELFTEST_PODMAN_EXECUTION=NO"
    )

    print(
        "WB3D_MODEL_RUNNER_SELFTEST_NETWORK=NO"
    )

    return 0


def evaluate_structured_gpu_proof(stderr_text: str):
    lines = stderr_text.replace("\r", "\n").splitlines()
    marker = "llama_prepare_model_devices: using device "
    identity = (
        "nvidia geforce gtx 1660 ti with max-q design",
        "nvk tu116",
    )
    selections = []
    for index, line in enumerate(lines):
        if marker not in line:
            continue
        tail = line.split(marker, 1)[1]
        device = tail.split(" ", 1)[0]
        lowered = line.lower()
        if (
            device.lower().startswith("vulkan")
            and all(token in lowered for token in identity)
        ):
            selections.append((index, device))

    offloads = []
    for index, line in enumerate(lines):
        prefix = "load_tensors: offloaded "
        if prefix not in line or " layers to GPU" not in line:
            continue
        fraction = (
            line.split(prefix, 1)[1]
            .split(" layers to GPU", 1)[0]
            .strip()
        )
        try:
            left, right = fraction.split("/", 1)
            offloaded, total = int(left), int(right)
        except ValueError:
            continue
        if offloaded == total == 37:
            offloads.append((index, offloaded, total))

    result = {
        "vulkan_proven": False,
        "nvidia_proven": bool(selections),
        "device_selection_proven": bool(selections),
        "selected_device": "",
        "offloaded_layers": 0,
        "total_layers": 0,
        "model_buffer_mib": 0.0,
        "kv_buffer_mib": 0.0,
        "compute_buffer_mib": 0.0,
    }
    if not selections or not offloads:
        return result

    offload_index, offloaded, total = offloads[-1]
    eligible = [item for item in selections if item[0] <= offload_index]
    if not eligible:
        return result

    _, selected_device = eligible[-1]

    def max_mib(label):
        token = selected_device + " " + label + " size ="
        values = []
        for line in lines[offload_index:]:
            if token not in line:
                continue
            tail = line.split(token, 1)[1].strip()
            try:
                values.append(float(tail.split()[0]))
            except (IndexError, ValueError):
                continue
        return max(values, default=0.0)

    result.update(
        {
            "selected_device": selected_device,
            "offloaded_layers": offloaded,
            "total_layers": total,
            "model_buffer_mib": max_mib("model buffer"),
            "kv_buffer_mib": max_mib("KV buffer"),
            "compute_buffer_mib": max_mib("compute buffer"),
        }
    )
    result["vulkan_proven"] = (
        result["device_selection_proven"]
        and result["offloaded_layers"] == result["total_layers"] == 37
        and result["model_buffer_mib"] > 0.0
        and result["kv_buffer_mib"] > 0.0
        and result["compute_buffer_mib"] > 0.0
    )
    result["nvidia_proven"] = result["device_selection_proven"]
    return result

def execute_synthetic(
    evidence_arg: str,
    render_arg: str,
) -> int:
    evidence = validate_evidence_dir(
        Path(
            evidence_arg
        )
    )

    requested_render = Path(
        render_arg
    )

    suffix = (
        evidence.name.removeprefix(
            "gg-wb3d-model-runner."
        )
    )

    if (
        not suffix
        or any(
            char not in (
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789"
            )
            for char in suffix
        )
    ):
        raise RunnerStop(
            "evidence_nonce_invalid"
        )

    help_name = (
        "gg-wb3d-help-"
        + suffix.lower()
    )

    infer_name = (
        "gg-wb3d-infer-"
        + suffix.lower()
    )

    expected_new_files = (
        "request.json",
        "help-stdout.txt",
        "help-stderr.txt",
        "model-stdout.txt",
        "model-stderr.txt",
        "response.json",
        "runner-report.json",
        "runner-failure.json",
    )

    for filename in expected_new_files:
        target = (
            evidence
            / filename
        )

        if (
            target.exists()
            or target.is_symlink()
        ):
            raise RunnerStop(
                "preexisting_evidence_file:"
                + filename
            )

    runtime_run_invocations = 0
    model_inference_count = 0

    try:
        require_podman_empty(
            "runner_start"
        )

        if (
            not MODEL_PATH.is_file()
            or MODEL_PATH.is_symlink()
        ):
            raise RunnerStop(
                "model_file_unsafe"
            )

        if (
            MODEL_PATH.stat().st_size
            != MODEL_BYTES
        ):
            raise RunnerStop(
                "model_size_drift"
            )

        if (
            sha256_file(
                MODEL_PATH
            )
            != MODEL_SHA
        ):
            raise RunnerStop(
                "model_sha_drift"
            )

        inspect_image()

        current_render = (
            discover_nvidia_render()
        )

        if (
            requested_render
            != current_render
        ):
            raise RunnerStop(
                "render_target_changed:"
                + str(
                    requested_render
                )
                + "->"
                + str(
                    current_render
                )
            )

        contract = load_contract()

        request = {
            "schema":
                "gg.workbench.local-ai-request.v1",

            "request_id":
                REQUEST_ID,

            "mode":
                "CHAT",

            "prompt":
                PROMPT,
        }

        validated_request = (
            contract.validate_request(
                request
            )
        )

        request_json = (
            contract.canonical_request_json(
                validated_request
            )
        )

        write_new(
            evidence
            / "request.json",
            (
                request_json
                + "\n"
            ).encode(
                "utf-8"
            ),
        )

        help_argv = (
            runtime_base_args(
                help_name
            )
            + [
                RUNTIME_IMAGE,
                "--help",
            ]
        )

        runtime_run_invocations += 1

        (
            help_rc,
            help_stdout,
            help_stderr,
            help_duration_ms,
            help_timeout,
        ) = run_named_container(
            help_argv,
            help_name,
            60,
        )

        write_new(
            evidence
            / "help-stdout.txt",
            help_stdout,
        )

        write_new(
            evidence
            / "help-stderr.txt",
            help_stderr,
        )

        if help_timeout:
            raise RunnerStop(
                "help_probe_timeout"
            )

        if help_rc != 0:
            raise RunnerStop(
                "help_probe_failed_rc:"
                + str(help_rc)
            )

        help_text = (
            help_stdout
            + b"\n"
            + help_stderr
        ).decode(
            "utf-8",
            errors="replace",
        )

        for option in (
            "--verbose",
            '--grammar',
            "--single-turn",
            "--no-display-prompt",
        ):
            if option not in help_text:
                raise RunnerStop(
                    "required_runtime_option_missing:"
                    + option
                )

        if (
            "--gpu-layers"
            in help_text
        ):
            gpu_flag = (
                "--gpu-layers"
            )

        elif (
            "--n-gpu-layers"
            in help_text
        ):
            gpu_flag = (
                "--n-gpu-layers"
            )

        else:
            raise RunnerStop(
                "gpu_layers_option_missing"
            )


        infer_argv = (
            runtime_base_args(
                infer_name
            )
            + [
                "--device",
                (
                    f"{current_render}:"
                    f"{current_render}:rwm"
                ),

                "--mount",
                (
                    f"type=bind,"
                    f"src={MODEL_DIR},"
                    "target=/models,ro"
                ),

                RUNTIME_IMAGE,

                "--model",
                "/models/Qwen3-4B-Q5_K_M.gguf",

                "--prompt",
                PROMPT,

                "--predict",
                "2969",

                "--ctx-size",
                "16384",

                "--temp",
                "0",

                "--seed",
                "42",

                '--grammar',
                MODEL_GBNF,

                gpu_flag,
                "99",

                "--single-turn",
                "--skip-chat-parsing",
                "--no-conversation",
                "--no-display-prompt",
                "--verbose",
            ]
        )

        if (
            "--reasoning-format"
            in help_text
        ):
            infer_argv.extend(
                [
                    "--reasoning-format",
                    "none",
                ]
            )

        require_podman_empty(
            "before_inference"
        )

        runtime_run_invocations += 1
        model_inference_count += 1

        (
            infer_rc,
            model_stdout,
            model_stderr,
            infer_duration_ms,
            infer_timeout,
        ) = run_named_container(
            infer_argv,
            infer_name,
            600,
        )

        write_new(
            evidence
            / "model-stdout.txt",
            model_stdout,
        )

        write_new(
            evidence
            / "model-stderr.txt",
            model_stderr,
        )

        if infer_timeout:
            raise RunnerStop(
                "model_inference_timeout"
            )

        if infer_rc != 0:
            raise RunnerStop(
                "model_inference_failed_rc:"
                + str(infer_rc)
            )

        require_podman_empty(
            "after_inference"
        )

        gpu_proof = evaluate_structured_gpu_proof(
            model_stderr.decode(
                "utf-8",
                errors="replace",
            )
        )
        vulkan_proven = gpu_proof["vulkan_proven"]
        nvidia_proven = gpu_proof["nvidia_proven"]

        if not vulkan_proven:
            raise RunnerStop(
                "vulkan_selection_not_proven"
            )

        if not nvidia_proven:
            raise RunnerStop(
                "nvidia_selection_not_proven"
            )

        answer = parse_model_stdout(
            model_stdout
        )

        response = {
            "schema":
                "gg.workbench.local-ai-response.v1",

            "request_id":
                REQUEST_ID,

            "status":
                "PASS",

            "text":
                answer,

            "evidence": {
                "model_sha256":
                    MODEL_SHA,

                "runtime_image_id":
                    RUNTIME_IMAGE_ID,

                "runtime_image_digest":
                    RUNTIME_IMAGE_DIGEST,

                "exit_code":
                    0,

                "stderr_sha256":
                    sha256_bytes(
                        model_stderr
                    ),

                "duration_ms":
                    infer_duration_ms,
            },
        }

        validated_response = (
            contract.validate_response(
                response,
                REQUEST_ID,
            )
        )

        response_json = (
            contract.canonical_response_json(
                validated_response,
                REQUEST_ID,
            )
        )

        write_new(
            evidence
            / "response.json",
            (
                response_json
                + "\n"
            ).encode(
                "utf-8"
            ),
        )

        report = {
            "schema":
                "gg.workbench.local-ai-model-runner-report.v1",

            "status":
                "PASS",

            "request_id":
                REQUEST_ID,

            "runtime_image":
                RUNTIME_IMAGE,

            "runtime_image_id":
                RUNTIME_IMAGE_ID,

            "runtime_image_digest":
                RUNTIME_IMAGE_DIGEST,

            "model_path":
                str(
                    MODEL_PATH
                ),

            "model_sha256":
                MODEL_SHA,

            "render_node":
                str(
                    current_render
                ),

            "runtime_run_invocations":
                runtime_run_invocations,

            "help_probe_count":
                1,

            "model_inference_count":
                model_inference_count,

            "network_mode":
                "none",

            "model_mount":
                "READ_ONLY_NO_RELABEL",

            "help_rc":
                help_rc,

            "help_duration_ms":
                help_duration_ms,

            "inference_rc":
                infer_rc,

            "inference_duration_ms":
                infer_duration_ms,

            "stdout_sha256":
                sha256_bytes(
                    model_stdout
                ),

            "stderr_sha256":
                sha256_bytes(
                    model_stderr
                ),

            "vulkan_proven":
                vulkan_proven,

            "nvidia_proven":
                nvidia_proven,

            "response_sha256":
                sha256_bytes(
                    (
                        response_json
                        + "\n"
                    ).encode(
                        "utf-8"
                    )
                ),
        }

        write_new(
            evidence
            / "runner-report.json",
            json_bytes(
                report
            ),
        )

        print(
            "WB3D_MODEL_RUNNER_SYNTHETIC_INFERENCE=PASS"
        )

        print(
            "MODEL_RUNTIME_RUN_INVOCATION_COUNT=2"
        )

        print(
            "HELP_PROBE_COUNT=1"
        )

        print(
            "MODEL_INFERENCE_COUNT=1"
        )

        print(
            "INFERENCE_RC=0"
        )

        print(
            "STDERR_CONTAINS_VULKAN=YES"
        )

        print(
            "STDERR_CONTAINS_NVIDIA_IDENTITY=YES"
        )

        print(
            "MODEL_RESPONSE_JSON_PARSE=PASS"
        )

        print(
            "MODEL_RESPONSE_MARKER=PASS"
        )

        print(
            "LOCAL_AI_RESPONSE_CONTRACT=PASS"
        )

        print(
            "NETWORK_MODE=none"
        )

        print(
            "MODEL_MOUNT=READ_ONLY_NO_RELABEL"
        )

        print(
            "CURRENT_NVIDIA_RENDER_NODE="
            + str(
                current_render
            )
        )

        print(
            "RESPONSE_SHA256="
            + report[
                "response_sha256"
            ]
        )

        return 0

    except RunnerStop as exc:
        cleanup_errors: list[str] = []

        for name in (
            help_name,
            infer_name,
        ):
            try:
                remove_owned_container(
                    name
                )

            except RunnerStop as cleanup_exc:
                cleanup_errors.append(
                    str(
                        cleanup_exc
                    )
                )

        failure = {
            "schema":
                "gg.workbench.local-ai-model-runner-failure.v1",

            "status":
                "FAIL",

            "reason":
                str(exc),

            "runtime_run_invocations":
                runtime_run_invocations,

            "model_inference_count":
                model_inference_count,

            "cleanup_errors":
                cleanup_errors,
        }

        failure_path = (
            evidence
            / "runner-failure.json"
        )

        if (
            not failure_path.exists()
            and not failure_path.is_symlink()
        ):
            write_new(
                failure_path,
                json_bytes(
                    failure
                ),
            )

        print(
            "WB3D_MODEL_RUNNER_STOP="
            + str(exc),
            file=sys.stderr,
        )

        if cleanup_errors:
            print(
                "WB3D_MODEL_RUNNER_CLEANUP_ERRORS="
                + repr(
                    cleanup_errors
                ),
                file=sys.stderr,
            )
            return 3

        try:
            require_podman_empty(
                "runner_failure_cleanup"
            )

        except RunnerStop as empty_exc:
            print(
                "WB3D_MODEL_RUNNER_POST_FAILURE_PODMAN="
                + str(
                    empty_exc
                ),
                file=sys.stderr,
            )
            return 4

        return 2


def main() -> int:
    args = sys.argv[1:]

    if not args:
        return selftest()

    if (
        len(args) == 3
        and args[0]
        == "--execute-synthetic"
    ):
        return execute_synthetic(
            args[1],
            args[2],
        )

    print(
        "usage: "
        "gg_local_ai_model_runner.py "
        "[--execute-synthetic "
        "EVIDENCE_DIR RENDER_NODE]",
        file=sys.stderr,
    )

    return 64


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
