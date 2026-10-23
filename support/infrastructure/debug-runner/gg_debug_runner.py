#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from typing import Any, Iterable, Sequence

VERSION = "1.2.0-candidate"
REPAIR_EXPECTED_IMAGE_REFERENCE = "localhost/gg-code-gate:1.0.0"
REPAIR_EXPECTED_IMAGE_ID = "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174"
REPAIR_EXPECTED_IMAGE_DIGEST = "sha256:5a26c8a95d5b8fc525f62c09c3c1d8a88df6a3432b678adc8d861bae23d3510e"
REPORT_SCHEMA = "gg.debug-runner-report.v1"
CONTRACT_SCHEMA = "gg.cp5c.provenance-debug-runner-contract.v1"
DEFAULT_STATE_ROOT = Path("/home/GG/.local/state/goldgoblins/debug-runner")
DEFAULT_CONTRACT = Path(
    "/home/GG/GG-CP5C-PROVENANCE-DEBUG-RUNNER-CONTRACT-v1.0.json"
)
DEFAULT_IMAGE = "localhost/gg-code-gate:1.0.0"
LOCKED_IMAGE_ID = (
    "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174"
)
LOCKED_IMAGE_DIGEST = (
    "sha256:5a26c8a95d5b8fc525f62c09c3c1d8a88df6a3432b678adc8d861bae23d3510e"
)
EXPECTED_PODMAN_VERSION = "5.8.4"
LOCKED_CODE_GATE_VERSION = "1.0.0"
ERROR_CLASSES = {
    "SOURCE_FAIL",
    "TRANSPORT_FAIL",
    "DEPENDENCY_FAIL",
    "HARNESS_FAIL",
    "SANDBOX_FAIL",
    "TARGET_FAIL",
    "POLICY_STOP",
}
STATUSES = {"PASS", "FAIL", "CONDITIONAL"}
FORBIDDEN_SOURCE_PREFIXES = (
    Path("/root"),
    Path("/etc"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/run/secrets"),
    Path("/home/GG/.ssh"),
    Path("/home/GG/.gnupg"),
    Path("/home/GG/.config"),
)
REQUIRED_REPORT_FIELDS = {
    "schema",
    "runner_version",
    "run_id",
    "timestamps",
    "status",
    "error_class",
    "source",
    "command",
    "argv",
    "working_directory",
    "container",
    "lifecycle",
    "image",
    "mounts",
    "network",
    "identity",
    "limits",
    "execution",
    "stdout",
    "stderr",
    "exit_code",
    "signal",
    "timeout",
    "filesystem_before",
    "filesystem_after",
    "created_files",
    "modified_files",
    "missing_files",
    "artifacts",
    "cleanup",
    "tool_versions",
    "policy",
}


class RunnerError(RuntimeError):
    def __init__(self, error_class: str, message: str, exit_code: int = 1):
        if error_class not in ERROR_CLASSES:
            raise ValueError(f"unknown error class: {error_class}")
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.exit_code = exit_code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def ensure_regular_file(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise RunnerError("SOURCE_FAIL", f"{label} must be absolute: {path}")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RunnerError("SOURCE_FAIL", f"{label} missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise RunnerError("SOURCE_FAIL", f"{label} symlink forbidden: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise RunnerError("SOURCE_FAIL", f"{label} not a regular file: {path}")
    return path.resolve(strict=True)


def verify_sidecar(path: Path) -> str:
    sidecar = Path(f"{path}.sha256")
    sidecar = ensure_regular_file(sidecar, label="checksum sidecar")
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2:
        raise RunnerError("SOURCE_FAIL", f"invalid checksum sidecar: {sidecar}")
    expected_hash, expected_name = fields
    if expected_name != path.name:
        raise RunnerError(
            "SOURCE_FAIL",
            f"sidecar filename mismatch: {expected_name!r} != {path.name!r}",
        )
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise RunnerError(
            "SOURCE_FAIL",
            f"checksum mismatch for {path}: {actual_hash}",
        )
    return actual_hash


def load_contract(path: Path) -> dict[str, Any]:
    path = ensure_regular_file(path, label="contract")
    verify_sidecar(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("SOURCE_FAIL", f"contract parse failed: {exc}") from exc
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise RunnerError(
            "SOURCE_FAIL",
            f"unexpected contract schema: {payload.get('schema')!r}",
        )
    if payload.get("contract_status") != "APPROVED_FOR_PHASE_B_DESIGN":
        raise RunnerError(
            "POLICY_STOP",
            f"contract status does not allow design: {payload.get('contract_status')!r}",
        )
    return payload


def sanitize_environment() -> dict[str, str]:
    keep = {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "USER",
        "LOGNAME",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    }
    environment = {key: value for key, value in os.environ.items() if key in keep}
    environment.update(
        {
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            "SSH_AUTH_SOCK": "",
            "GIT_TERMINAL_PROMPT": "0",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "all_proxy": "",
        }
    )
    return environment


def run_capture(
    argv: Sequence[str],
    *,
    timeout_seconds: float = 15.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RunnerError("DEPENDENCY_FAIL", f"command missing: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(
            "HARNESS_FAIL",
            f"control command timed out: {shlex.join(list(argv))}",
        ) from exc
    return {
        "argv": list(argv),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def require_success(record: dict[str, Any], *, label: str) -> dict[str, Any]:
    if record["returncode"] != 0:
        raise RunnerError(
            "DEPENDENCY_FAIL",
            f"{label} failed with {record['returncode']}: {record['stderr'].strip()}",
        )
    return record


def podman_json(
    argv: Sequence[str],
    *,
    timeout_seconds: float = 15.0,
) -> Any:
    record = require_success(
        run_capture(
            ["podman", *argv],
            timeout_seconds=timeout_seconds,
            env=sanitize_environment(),
        ),
        label=f"podman {' '.join(argv)}",
    )
    try:
        return json.loads(record["stdout"])
    except json.JSONDecodeError as exc:
        raise RunnerError(
            "DEPENDENCY_FAIL",
            f"podman JSON parse failed for {' '.join(argv)}: {exc}",
        ) from exc


def runtime_snapshot() -> dict[str, list[str]]:
    env = sanitize_environment()
    containers = require_success(
        run_capture(["podman", "ps", "-aq"], env=env),
        label="podman container inventory",
    )["stdout"].splitlines()
    volumes = require_success(
        run_capture(["podman", "volume", "ls", "-q"], env=env),
        label="podman volume inventory",
    )["stdout"].splitlines()
    networks = require_success(
        run_capture(
            ["podman", "network", "ls", "--format", "{{.Name}}"],
            env=env,
        ),
        label="podman network inventory",
    )["stdout"].splitlines()
    return {
        "containers": sorted(value for value in containers if value),
        "volumes": sorted(value for value in volumes if value),
        "networks": sorted(
            value for value in networks if value and value != "podman"
        ),
    }


def verify_host_runtime() -> dict[str, Any]:
    info = podman_json(["info", "--format", "json"])
    try:
        version = str(info["version"]["Version"])
        rootless = bool(info["host"]["security"]["rootless"])
        cgroup_version = str(info["host"]["cgroupVersion"])
        cgroup_manager = str(info["host"]["cgroupManager"])
        runtime = str(info["host"]["ociRuntime"]["name"])
    except (KeyError, TypeError) as exc:
        raise RunnerError("DEPENDENCY_FAIL", "unexpected podman info schema") from exc
    crun_record = require_success(
        run_capture(["crun", "--version"], env=sanitize_environment()),
        label="crun version",
    )
    crun_lines = [
        line.strip()
        for line in crun_record["stdout"].splitlines()
        if line.strip()
    ]
    crun_version = crun_lines[0] if crun_lines else "unknown"
    facts = {
        "podman_version": version,
        "rootless": rootless,
        "cgroup_version": cgroup_version,
        "cgroup_manager": cgroup_manager,
        "oci_runtime": runtime,
        "oci_runtime_version": crun_version,
    }
    expected = {
        "podman_version": EXPECTED_PODMAN_VERSION,
        "rootless": True,
        "cgroup_version": "v2",
        "cgroup_manager": "systemd",
        "oci_runtime": "crun",
    }
    for key, expected_value in expected.items():
        if facts.get(key) != expected_value:
            raise RunnerError(
                "DEPENDENCY_FAIL",
                f"host runtime differs from locked baseline: {facts!r}",
            )
    return facts



def inspect_image(reference: str) -> dict[str, Any]:
    payload = podman_json(["image", "inspect", reference])
    if not isinstance(payload, list) or len(payload) != 1:
        raise RunnerError("DEPENDENCY_FAIL", "unexpected image inspect payload")
    record = payload[0]
    config = record.get("Config") or {}
    facts = {
        "reference": reference,
        "id": str(record.get("Id", "")),
        "digest": str(record.get("Digest", "")),
        "user": str(config.get("User", "")),
        "working_directory": str(config.get("WorkingDir", "")),
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
    }
    expected = {
        "reference": REPAIR_EXPECTED_IMAGE_REFERENCE,
        "id": REPAIR_EXPECTED_IMAGE_ID,
        "digest": REPAIR_EXPECTED_IMAGE_DIGEST,
        "user": "1000:1000",
        "working_directory": "/work",
    }
    for key, expected_value in expected.items():
        if facts.get(key) != expected_value:
            raise RunnerError(
                "DEPENDENCY_FAIL",
                f"image {key} drift: {facts.get(key)!r}",
            )
    return facts



def validate_source(source: Path, allowed_root: Path) -> Path:
    source = ensure_regular_file(source, label="source")
    if not allowed_root.is_absolute():
        raise RunnerError(
            "POLICY_STOP",
            f"allowed source root must be absolute: {allowed_root}",
        )
    try:
        allowed_root = allowed_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RunnerError(
            "SOURCE_FAIL",
            f"allowed source root missing: {allowed_root}",
        ) from exc
    if not allowed_root.is_dir() or allowed_root.is_symlink():
        raise RunnerError(
            "SOURCE_FAIL",
            f"allowed source root invalid: {allowed_root}",
        )
    if not is_relative_to(source, allowed_root):
        raise RunnerError(
            "POLICY_STOP",
            f"source outside allowed synthetic root: {source}",
        )
    for prefix in FORBIDDEN_SOURCE_PREFIXES:
        prefix_resolved = prefix.resolve(strict=False)
        if source == prefix_resolved or is_relative_to(source, prefix_resolved):
            raise RunnerError(
                "POLICY_STOP",
                f"source path forbidden by policy: {source}",
            )
    return source


def validate_state_root(path: Path) -> Path:
    if not path.is_absolute():
        raise RunnerError("POLICY_STOP", f"state root must be absolute: {path}")
    normalized = path.resolve(strict=False)
    if normalized != DEFAULT_STATE_ROOT:
        raise RunnerError(
            "POLICY_STOP",
            f"state root must equal {DEFAULT_STATE_ROOT}: {normalized}",
        )
    for parent in (normalized.parent, normalized):
        if parent.exists() and parent.is_symlink():
            raise RunnerError("POLICY_STOP", f"state path symlink forbidden: {parent}")
    normalized.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(normalized, 0o700)
    return normalized


def prepare_gate_argv(raw: Sequence[str], container_source: str) -> list[str]:
    values = list(raw)
    if values and values[0] == "--":
        values = values[1:]
    if not values:
        raise RunnerError(
            "TRANSPORT_FAIL",
            "missing Code Gate arguments after --",
        )
    marker_count = sum(value.count("{SOURCE}") for value in values)
    if marker_count != 1:
        raise RunnerError(
            "TRANSPORT_FAIL",
            f"{{SOURCE}} placeholder must occur exactly once, observed {marker_count}",
        )
    replaced = [value.replace("{SOURCE}", container_source) for value in values]
    if any("\x00" in value for value in replaced):
        raise RunnerError("TRANSPORT_FAIL", "NUL in argv is forbidden")
    return replaced


def manifest_tree(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not root.exists():
        return entries
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise RunnerError(
                "POLICY_STOP",
                f"symlink in writable tree: {path}",
            )
        if stat.S_ISDIR(metadata.st_mode):
            entries.append(
                {
                    "relative_path": relative,
                    "type": "directory",
                    "bytes": 0,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "sha256": None,
                }
            )
        elif stat.S_ISREG(metadata.st_mode):
            entries.append(
                {
                    "relative_path": relative,
                    "type": "file",
                    "bytes": metadata.st_size,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "sha256": sha256_file(path),
                }
            )
        else:
            raise RunnerError(
                "POLICY_STOP",
                f"special file in writable tree: {path}",
            )
    return entries


def diff_manifests(
    before: Iterable[dict[str, Any]],
    after: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    before_map = {entry["relative_path"]: entry for entry in before}
    after_map = {entry["relative_path"]: entry for entry in after}
    created = [after_map[name] for name in sorted(after_map.keys() - before_map.keys())]
    missing = [before_map[name] for name in sorted(before_map.keys() - after_map.keys())]
    modified = [
        {
            "relative_path": name,
            "before": before_map[name],
            "after": after_map[name],
        }
        for name in sorted(before_map.keys() & after_map.keys())
        if before_map[name] != after_map[name]
    ]
    return created, modified, missing


def write_json_atomic(path: Path, payload: Any, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def write_text_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    data = text.encode("utf-8")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def artifact_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "bytes": 0,
            "sha256": None,
        }
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def render_argv_display(argv: Sequence[str]) -> str:
    return shlex.join(list(argv))


def validate_report_shape(report: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_REPORT_FIELDS - report.keys())
    if missing:
        raise RunnerError(
            "HARNESS_FAIL",
            f"report required fields missing: {','.join(missing)}",
        )
    if report["schema"] != REPORT_SCHEMA:
        raise RunnerError("HARNESS_FAIL", "report schema mismatch")
    if report["status"] not in STATUSES:
        raise RunnerError("HARNESS_FAIL", "report status invalid")
    if report["error_class"] is not None and report["error_class"] not in ERROR_CLASSES:
        raise RunnerError("HARNESS_FAIL", "report error class invalid")
    if not isinstance(report["argv"], list) or not all(
        isinstance(value, str) for value in report["argv"]
    ):
        raise RunnerError("HARNESS_FAIL", "report argv must be a string list")
    if report["network"] != "none":
        raise RunnerError("HARNESS_FAIL", "report network must be none")
    cleanup = report["cleanup"]
    if (
        cleanup.get("cleanup_errors")
        or not cleanup.get("container_removed", False)
        or not cleanup.get("runtime_empty_after", False)
    ) and report["status"] == "PASS":
        raise RunnerError(
            "HARNESS_FAIL",
            "cleanup failure cannot be reported as PASS",
        )


def run_attached_with_limits(
    argv: Sequence[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    output_limit_bytes: int,
    env: dict[str, str],
) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        raise RunnerError("HARNESS_FAIL", "failed to open attach pipes")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", stdout_path))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", stderr_path))
    counts = {"stdout": 0, "stderr": 0}
    timed_out = False
    output_limit_exceeded = False
    killed = False
    handles = {
        "stdout": stdout_path.open("wb"),
        "stderr": stderr_path.open("wb"),
    }

    def kill_process_group() -> None:
        nonlocal killed
        if killed:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        killed = True

    try:
        while selector.get_map():
            elapsed = time.monotonic() - started
            remaining = timeout_seconds - elapsed
            if remaining <= 0 and process.poll() is None:
                timed_out = True
                kill_process_group()
                remaining = 0.1
            events = selector.select(timeout=min(max(remaining, 0.05), 0.25))
            if not events and process.poll() is not None:
                for key in list(selector.get_map().values()):
                    stream_name, _destination = key.data
                    block = os.read(key.fileobj.fileno(), 65536)
                    if block:
                        available = output_limit_bytes - counts[stream_name]
                        if available > 0:
                            handles[stream_name].write(block[:available])
                            counts[stream_name] += min(len(block), available)
                        if len(block) > max(available, 0):
                            output_limit_exceeded = True
                    else:
                        selector.unregister(key.fileobj)
                continue
            for key, _ in events:
                stream_name, _destination = key.data
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                available = output_limit_bytes - counts[stream_name]
                if available > 0:
                    handles[stream_name].write(block[:available])
                    counts[stream_name] += min(len(block), available)
                if len(block) > max(available, 0):
                    output_limit_exceeded = True
                    if process.poll() is None:
                        kill_process_group()
            if output_limit_exceeded and process.poll() is None:
                kill_process_group()
        returncode = process.wait(timeout=5)
    finally:
        selector.close()
        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "output_limit_exceeded": output_limit_exceeded,
        "stdout_bytes": counts["stdout"],
        "stderr_bytes": counts["stderr"],
        "duration_seconds": round(time.monotonic() - started, 6),
    }


def parse_wait_exit_code(text: str) -> int:
    values = [line.strip() for line in text.splitlines() if line.strip()]
    if len(values) != 1 or not re.fullmatch(r"-?[0-9]+", values[0]):
        raise RunnerError("SANDBOX_FAIL", f"unexpected podman wait output: {text!r}")
    return int(values[0])



def build_container_argv(
    *, container_name: str, run_id: str, image_reference: str,
    input_dir: Path, output_dir: Path, work_dir: Path,
    gate_argv: Sequence[str], uid: int, gid: int,
) -> list[str]:
    requested = [str(item) for item in gate_argv]
    if not requested or not requested[0] or any("\x00" in x for x in requested):
        raise RunnerError("TRANSPORT_FAIL", "invalid explicit target argv")
    entrypoint, arguments = requested[0], requested[1:]
    return [
        "podman","create","--name",container_name,
        "--label",f"io.goldgoblins.debug-runner.run-id={run_id}",
        "--pull=never","--network=none","--read-only","--read-only-tmpfs=false",
        "--tmpfs","/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--cap-drop=all","--security-opt=no-new-privileges","--userns=keep-id",
        "--user",f"{uid}:{gid}","--pids-limit=128","--memory=512m",
        "--memory-swap=512m","--cpus=1","--ulimit","nofile=256:256",
        "--workdir=/work",
        "--mount",f"type=bind,src={input_dir},target=/input,ro=true,relabel=private",
        "--mount",f"type=bind,src={output_dir},target=/output,rw=true,relabel=private",
        "--mount",f"type=bind,src={work_dir},target=/work,rw=true,relabel=private",
        "--entrypoint",entrypoint,image_reference,*arguments,
    ]


def inspect_container(name: str) -> dict[str, Any]:
    payload = podman_json(["inspect", name])
    if not isinstance(payload, list) or len(payload) != 1:
        raise RunnerError("SANDBOX_FAIL", "unexpected container inspect payload")
    return payload[0]


def verify_owned_container(record: dict[str, Any], *, run_id: str) -> None:
    labels = ((record.get("Config") or {}).get("Labels") or {})
    observed = labels.get("io.goldgoblins.debug-runner.run-id")
    if observed != run_id:
        raise RunnerError(
            "POLICY_STOP",
            f"container ownership label mismatch: {observed!r}",
        )



def verify_container_contract(
    record: dict[str, Any],
    *,
    expected_image: dict[str, Any],
    expected_input_dir: Path,
    expected_output_dir: Path,
    expected_work_dir: Path,
    expected_gate_argv: list[str],
) -> dict[str, Any]:
    config = record.get("Config") or {}
    host = record.get("HostConfig") or {}
    state = record.get("State") or {}
    network_settings = record.get("NetworkSettings") or {}
    mounts = record.get("Mounts") or []

    def normalized_argv(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise RunnerError(
                "SANDBOX_FAIL",
                f"container argv field is not a list: {type(value).__name__}",
            )
        return [str(item) for item in value]

    requested = [str(item) for item in expected_gate_argv]
    if not requested or not requested[0] or any("\x00" in x for x in requested):
        raise RunnerError("TRANSPORT_FAIL", "invalid expected target argv")
    target_entrypoint, target_arguments = requested[0], requested[1:]
    observed_entrypoint = normalized_argv(config.get("Entrypoint"))
    observed_arguments = normalized_argv(config.get("Cmd"))
    image_entrypoint = normalized_argv(expected_image.get("entrypoint"))

    checks: dict[str, bool] = {
        "image_reference": str(config.get("Image", ""))
        == str(expected_image["reference"]),
        "image_id": str(record.get("Image", "")) == str(expected_image["id"]),
        "image_digest": str(record.get("ImageDigest", ""))
        == str(expected_image["digest"]),
        "target_entrypoint_exact": observed_entrypoint == [target_entrypoint],
        "target_arguments_exact": observed_arguments == target_arguments,
        "requested_argv_exact": observed_entrypoint + observed_arguments == requested,
        "image_entrypoint_neutralized": not image_entrypoint or observed_entrypoint != image_entrypoint,
        "working_directory": str(config.get("WorkingDir", "")) == "/work",
        "container_user": str(config.get("User", "")) == "1000:1000",
        "read_only_root": host.get("ReadonlyRootfs") is True,
        "network_mode_none": str(host.get("NetworkMode", "")) == "none",
        "no_new_privileges": "no-new-privileges"
        in [str(item) for item in (host.get("SecurityOpt") or [])],
        "user_namespace_private": str(host.get("UsernsMode", "")) == "private",
        "pids_limit": host.get("PidsLimit") == 128,
        "memory_limit": host.get("Memory") == 536870912,
        "memory_swap_limit": host.get("MemorySwap") == 536870912,
        "nano_cpus": host.get("NanoCpus") == 1000000000,
        "cpu_quota": host.get("CpuQuota") == 100000,
        "cpu_period": host.get("CpuPeriod") == 100000,
        "not_privileged": host.get("Privileged") in (False, None),
        "no_devices": not (host.get("Devices") or []),
        "no_port_bindings": not (host.get("PortBindings") or {}),
        "no_host_pid_namespace": str(host.get("PidMode", "")) in ("", "private"),
        "effective_capabilities_empty": not (record.get("EffectiveCaps") or []),
        "bounding_capabilities_empty": not (record.get("BoundingCaps") or []),
        "created_not_started": (
            state.get("Status") == "created"
            and state.get("Running") is False
            and state.get("StartedAt") == "0001-01-01T00:00:00Z"
            and state.get("FinishedAt") == "0001-01-01T00:00:00Z"
        ),
        "not_oom_killed": state.get("OOMKilled") is False,
    }

    network_names = {
        str(value) for value in (network_settings.get("Networks") or {}).keys()
    }
    checks["no_unexpected_network"] = network_names.issubset({"none"})

    expected_cap_drop = {
        "CAP_CHOWN",
        "CAP_DAC_OVERRIDE",
        "CAP_FOWNER",
        "CAP_FSETID",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE",
        "CAP_SETFCAP",
        "CAP_SETGID",
        "CAP_SETPCAP",
        "CAP_SETUID",
        "CAP_SYS_CHROOT",
    }
    checks["cap_drop_all_default"] = {
        str(item) for item in (host.get("CapDrop") or [])
    } == expected_cap_drop

    checks["nofile_256"] = (host.get("Ulimits") or []) == [
        {"Name": "RLIMIT_NOFILE", "Soft": 256, "Hard": 256}
    ]

    tmpfs = host.get("Tmpfs") or {}
    tmpfs_tokens = {
        token
        for token in str(tmpfs.get("/tmp", "")).split(",")
        if token
    }
    checks["tmpfs_exact_target"] = set(tmpfs) == {"/tmp"}
    checks["tmpfs_required_options"] = {
        "rw",
        "noexec",
        "nosuid",
        "nodev",
        "size=64m",
        "mode=1777",
    }.issubset(tmpfs_tokens)

    if not isinstance(mounts, list):
        raise RunnerError("SANDBOX_FAIL", "container mounts are not a list")
    by_target: dict[str, dict[str, Any]] = {}
    duplicate_targets: set[str] = set()
    for mount in mounts:
        if not isinstance(mount, dict):
            raise RunnerError("SANDBOX_FAIL", "container mount is not an object")
        target = str(mount.get("Destination", ""))
        if target in by_target:
            duplicate_targets.add(target)
        by_target[target] = mount

    checks["mount_count"] = len(mounts) == 3
    checks["mount_targets"] = set(by_target) == {"/input", "/output", "/work"}
    checks["mount_targets_unique"] = not duplicate_targets

    def mount_check(
        target: str,
        expected_source: Path,
        expected_rw: bool,
    ) -> bool:
        mount = by_target.get(target) or {}
        raw_source = str(mount.get("Source", ""))
        if not raw_source:
            return False
        try:
            actual_source = Path(raw_source).resolve(strict=True)
            wanted_source = expected_source.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return False
        return (
            mount.get("Type") == "bind"
            and actual_source == wanted_source
            and mount.get("RW") is expected_rw
        )

    checks["input_mount"] = mount_check(
        "/input", expected_input_dir, False
    )
    checks["output_mount"] = mount_check(
        "/output", expected_output_dir, True
    )
    checks["work_mount"] = mount_check(
        "/work", expected_work_dir, True
    )

    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RunnerError(
            "SANDBOX_FAIL",
            "container semantic contract failed: " + ",".join(failed),
        )

    return {
        "schema": "gg.debug-runner.container-contract.v1.2",
        "status": "PASS",
        "checks": checks,
        "selected": {
            "image_reference": config.get("Image"),
            "image_id": record.get("Image"),
            "image_digest": record.get("ImageDigest"),
            "image_entrypoint": expected_image.get("entrypoint"),
            "target_entrypoint": observed_entrypoint,
            "target_arguments": observed_arguments,
            "requested_argv": requested,
            "working_directory": config.get("WorkingDir"),
            "user": config.get("User"),
            "network_mode": host.get("NetworkMode"),
            "security_options": host.get("SecurityOpt"),
            "cap_drop": host.get("CapDrop"),
            "effective_caps": record.get("EffectiveCaps"),
            "bounding_caps": record.get("BoundingCaps"),
            "user_namespace": host.get("UsernsMode"),
            "limits": {
                "pids": host.get("PidsLimit"),
                "memory": host.get("Memory"),
                "memory_swap": host.get("MemorySwap"),
                "nano_cpus": host.get("NanoCpus"),
                "cpu_quota": host.get("CpuQuota"),
                "cpu_period": host.get("CpuPeriod"),
                "ulimits": host.get("Ulimits"),
            },
            "tmpfs": tmpfs,
            "mounts": mounts,
            "state": state,
        },
    }



def markdown_report(report: dict[str, Any]) -> str:
    return f"""# GG Debug Runner-rapport

- Schema: `{report['schema']}`
- Runner-version: `{report['runner_version']}`
- Run-ID: `{report['run_id']}`
- Status: `{report['status']}`
- Felklass: `{report['error_class']}`
- Start UTC: `{report['timestamps']['started_at_utc']}`
- Slut UTC: `{report['timestamps']['finished_at_utc']}`

## Kommando

~~~~text
{report['command']}
~~~~

## Resultat

- Exitkod: `{report['exit_code']}`
- Signal: `{report['signal']}`
- Timeout: `{report['timeout']['timed_out']}`
- Stdout: `{report['stdout']['path']}`
- Stderr: `{report['stderr']['path']}`
- Container borttagen: `{report['cleanup']['container_removed']}`
- Tom runtime efteråt: `{report['cleanup']['runtime_empty_after']}`
"""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GG Debug Runner candidate",
        allow_abbrev=False,
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--allowed-source-root", required=True, type=Path)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output-limit-bytes", type=int, default=1024 * 1024)
    parser.add_argument("gate_argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(argv))
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be between 1 and 3600")
    if not 1024 <= args.output_limit_bytes <= 16 * 1024 * 1024:
        parser.error("--output-limit-bytes must be between 1024 and 16777216")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    started_at = utc_now()
    run_id = (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )
    state_root: Path | None = None
    run_dir: Path | None = None
    lock_handle: Any = None
    container_name = f"gg-debug-runner-{run_id.lower()}"
    container_id: str | None = None
    container_removed = True
    runtime_empty_after = False
    cleanup_errors: list[str] = []
    lifecycle: list[dict[str, Any]] = []
    status = "FAIL"
    error_class: str | None = None
    message = ""
    target_exit_code: int | None = None
    target_signal: int | None = None
    timed_out = False
    output_limit_exceeded = False
    execution_started = False
    command_argv: list[str] = []
    source_record: dict[str, Any] = {
        "host_path": str(args.source),
        "copied_path": None,
        "sha256": None,
        "bytes": None,
    }
    image_facts: dict[str, Any] = {
        "reference": args.image,
        "id": None,
        "digest": None,
        "user": None,
        "working_directory": None,
        "entrypoint": [],
        "cmd": [],
    }
    runtime_facts: dict[str, Any] = {}
    baseline_runtime: dict[str, list[str]] = {
        "containers": [],
        "volumes": [],
        "networks": [],
    }
    after_runtime: dict[str, list[str]] = {
        "containers": [],
        "volumes": [],
        "networks": [],
    }
    before_manifest: list[dict[str, Any]] = []
    after_manifest: list[dict[str, Any]] = []
    created_files: list[dict[str, Any]] = []
    modified_files: list[dict[str, Any]] = []
    missing_files: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    contract_hash: str | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    combined_log_path: Path | None = None
    inspect_path: Path | None = None
    container_contract_path: Path | None = None
    before_manifest_path: Path | None = None
    after_manifest_path: Path | None = None
    report_path: Path | None = None
    markdown_path: Path | None = None

    try:
        if os.getuid() == 0:
            raise RunnerError("POLICY_STOP", "root execution forbidden")
        if (os.getuid(), os.getgid()) != (1000, 1000):
            raise RunnerError(
                "POLICY_STOP",
                f"unexpected identity: {os.getuid()}:{os.getgid()}",
            )
        state_root = validate_state_root(args.state_root)
        lock_path = state_root / ".runner.lock"
        lock_handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        run_dir = state_root / f"RUN-{run_id}"
        run_dir.mkdir(mode=0o700)
        input_dir = run_dir / "input"
        output_dir = run_dir / "output"
        work_dir = run_dir / "work"
        logs_dir = run_dir / "logs"
        for directory in (input_dir, output_dir, work_dir, logs_dir):
            directory.mkdir(mode=0o700)

        stdout_path = logs_dir / "stdout.log"
        stderr_path = logs_dir / "stderr.log"
        combined_log_path = logs_dir / "container.log"
        inspect_path = run_dir / "container.inspect.json"
        container_contract_path = run_dir / "container.contract.json"
        before_manifest_path = run_dir / "filesystem.before.json"
        after_manifest_path = run_dir / "filesystem.after.json"
        report_path = run_dir / "debug-runner-report.json"
        markdown_path = run_dir / "debug-runner-report.md"

        _contract_payload = load_contract(args.contract)
        contract_hash = sha256_file(args.contract)

        if os.environ.get("GG_DEBUG_RUNNER_KILL_SWITCH") == "STOP":
            raise RunnerError(
                "POLICY_STOP",
                "kill switch active before podman create",
                exit_code=77,
            )

        source = validate_source(args.source, args.allowed_source_root)
        source_copy = input_dir / source.name
        with source.open("rb") as source_handle:
            descriptor = os.open(
                source_copy,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
            )
            with os.fdopen(descriptor, "wb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
        if sha256_file(source_copy) != sha256_file(source):
            raise RunnerError("TRANSPORT_FAIL", "source copy hash mismatch")
        source_record = {
            "host_path": str(source),
            "copied_path": str(source_copy),
            "container_path": f"/input/{source.name}",
            "sha256": sha256_file(source),
            "bytes": source.stat().st_size,
        }

        gate_argv = prepare_gate_argv(
            args.gate_argv,
            source_record["container_path"],
        )
        runtime_facts = verify_host_runtime()
        baseline_runtime = runtime_snapshot()
        if any(baseline_runtime.values()):
            raise RunnerError(
                "POLICY_STOP",
                f"podman baseline not empty: {baseline_runtime!r}",
            )
        image_facts = inspect_image(args.image)

        before_manifest = [
            {
                **entry,
                "relative_path": f"output/{entry['relative_path']}",
            }
            for entry in manifest_tree(output_dir)
        ] + [
            {
                **entry,
                "relative_path": f"work/{entry['relative_path']}",
            }
            for entry in manifest_tree(work_dir)
        ]
        write_json_atomic(before_manifest_path, before_manifest)

        command_argv = build_container_argv(
            container_name=container_name,
            run_id=run_id,
            image_reference=args.image,
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
            gate_argv=gate_argv,
            uid=os.getuid(),
            gid=os.getgid(),
        )

        create_record = run_capture(
            command_argv,
            timeout_seconds=30,
            env=sanitize_environment(),
        )
        lifecycle.append(
            {
                "step": "podman create",
                "argv": command_argv,
                "returncode": create_record["returncode"],
            }
        )
        if create_record["returncode"] != 0:
            raise RunnerError(
                "SANDBOX_FAIL",
                f"podman create failed: {create_record['stderr'].strip()}",
            )
        container_id = "PENDING_INSPECTION"
        create_lines = [
            line.strip()
            for line in create_record["stdout"].splitlines()
            if line.strip()
        ]
        if len(create_lines) != 1 or not re.fullmatch(r"[0-9a-f]{64}", create_lines[0]):
            raise RunnerError(
                "SANDBOX_FAIL",
                f"unexpected podman create output: {create_record['stdout']!r}",
            )
        container_id = create_lines[0]
        container_removed = False

        inspect_record = inspect_container(container_name)
        verify_owned_container(inspect_record, run_id=run_id)
        container_contract = verify_container_contract(
            inspect_record,
            expected_image=image_facts,
            expected_input_dir=input_dir,
            expected_output_dir=output_dir,
            expected_work_dir=work_dir,
            expected_gate_argv=gate_argv,
        )
        write_json_atomic(inspect_path, inspect_record)
        write_json_atomic(container_contract_path, container_contract)
        lifecycle.append(
            {
                "step": "podman inspect",
                "argv": ["podman", "inspect", container_name],
                "returncode": 0,
            }
        )

        execution_started = True
        attach_record = run_attached_with_limits(
            ["podman", "start", "--attach", container_name],
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=args.timeout_seconds,
            output_limit_bytes=args.output_limit_bytes,
            env=sanitize_environment(),
        )
        timed_out = bool(attach_record["timed_out"])
        output_limit_exceeded = bool(attach_record["output_limit_exceeded"])
        if attach_record["returncode"] < 0:
            target_signal = -attach_record["returncode"]
        lifecycle.append(
            {
                "step": "podman start",
                "argv": ["podman", "start", "--attach", container_name],
                "returncode": attach_record["returncode"],
                "timed_out": timed_out,
                "output_limit_exceeded": output_limit_exceeded,
            }
        )

        if timed_out or output_limit_exceeded:
            kill_record = run_capture(
                ["podman", "kill", "--signal", "KILL", container_name],
                timeout_seconds=15,
                env=sanitize_environment(),
            )
            lifecycle.append(
                {
                    "step": "podman kill",
                    "argv": ["podman", "kill", "--signal", "KILL", container_name],
                    "returncode": kill_record["returncode"],
                }
            )

        wait_record = run_capture(
            ["podman", "wait", container_name],
            timeout_seconds=30,
            env=sanitize_environment(),
        )
        lifecycle.append(
            {
                "step": "podman wait",
                "argv": ["podman", "wait", container_name],
                "returncode": wait_record["returncode"],
            }
        )
        if wait_record["returncode"] != 0:
            raise RunnerError(
                "SANDBOX_FAIL",
                f"podman wait failed: {wait_record['stderr'].strip()}",
            )
        target_exit_code = parse_wait_exit_code(wait_record["stdout"])
        if target_exit_code >= 128:
            target_signal = target_exit_code - 128

        logs_record = run_capture(
            ["podman", "logs", "--tail", "1000", container_name],
            timeout_seconds=15,
            env=sanitize_environment(),
        )
        combined = (logs_record["stdout"] + logs_record["stderr"]).encode("utf-8")
        write_text_atomic(
            combined_log_path,
            combined[: args.output_limit_bytes].decode(
                "utf-8",
                errors="replace",
            ),
        )
        lifecycle.append(
            {
                "step": "podman logs",
                "argv": ["podman", "logs", "--tail", "1000", container_name],
                "returncode": logs_record["returncode"],
            }
        )

        if timed_out:
            raise RunnerError("TARGET_FAIL", "target timed out")
        if output_limit_exceeded:
            raise RunnerError("TARGET_FAIL", "target output limit exceeded")
        if target_exit_code != 0:
            raise RunnerError(
                "TARGET_FAIL",
                f"target exited with code {target_exit_code}",
            )

        status = "PASS"
        error_class = None
        message = "target completed successfully"

    except BlockingIOError:
        status = "FAIL"
        error_class = "POLICY_STOP"
        message = "another Debug Runner instance holds the state lock"
    except RunnerError as exc:
        status = "FAIL"
        error_class = exc.error_class
        message = exc.message
    except BaseException as exc:
        status = "FAIL"
        error_class = "HARNESS_FAIL"
        message = f"unhandled runner exception: {type(exc).__name__}: {exc}"
    finally:
        if container_id is not None:
            try:
                owned_record = inspect_container(container_name)
                verify_owned_container(owned_record, run_id=run_id)
                remove_record = run_capture(
                    ["podman", "rm", "-f", container_name],
                    timeout_seconds=30,
                    env=sanitize_environment(),
                )
                lifecycle.append(
                    {
                        "step": "podman rm",
                        "argv": ["podman", "rm", "-f", container_name],
                        "returncode": remove_record["returncode"],
                    }
                )
                if remove_record["returncode"] != 0:
                    cleanup_errors.append(
                        f"podman rm failed: {remove_record['stderr'].strip()}"
                    )
                else:
                    container_removed = True
            except BaseException as exc:
                cleanup_errors.append(
                    f"container cleanup exception: {type(exc).__name__}: {exc}"
                )

        try:
            after_runtime = runtime_snapshot()
            runtime_empty_after = not any(after_runtime.values())
        except BaseException as exc:
            cleanup_errors.append(
                f"runtime postcheck exception: {type(exc).__name__}: {exc}"
            )
            runtime_empty_after = False

        if cleanup_errors or not container_removed or not runtime_empty_after:
            status = "FAIL"
            if error_class not in {"POLICY_STOP", "HARNESS_FAIL"}:
                error_class = "SANDBOX_FAIL"
            message = message + "; cleanup contract failed"

        if run_dir is not None:
            try:
                output_dir = run_dir / "output"
                work_dir = run_dir / "work"
                after_manifest = [
                    {
                        **entry,
                        "relative_path": f"output/{entry['relative_path']}",
                    }
                    for entry in manifest_tree(output_dir)
                ] + [
                    {
                        **entry,
                        "relative_path": f"work/{entry['relative_path']}",
                    }
                    for entry in manifest_tree(work_dir)
                ]
                created_files, modified_files, missing_files = diff_manifests(
                    before_manifest,
                    after_manifest,
                )
                if after_manifest_path is not None:
                    write_json_atomic(after_manifest_path, after_manifest)
            except BaseException as exc:
                status = "FAIL"
                error_class = "HARNESS_FAIL"
                message = (
                    message
                    + f"; filesystem manifest failed: {type(exc).__name__}: {exc}"
                )

            finished_at = utc_now()
            candidate_artifacts = [
                path
                for path in (
                    stdout_path,
                    stderr_path,
                    combined_log_path,
                    inspect_path,
                    container_contract_path,
                    before_manifest_path,
                    after_manifest_path,
                )
                if path is not None
            ]
            artifacts = [artifact_record(path) for path in candidate_artifacts]
            report = {
                "schema": REPORT_SCHEMA,
                "runner_version": VERSION,
                "run_id": run_id,
                "timestamps": {
                    "started_at_utc": started_at,
                    "finished_at_utc": finished_at,
                },
                "status": status,
                "error_class": error_class,
                "message": message,
                "source": source_record,
                "command": render_argv_display(command_argv),
                "argv": command_argv,
                "working_directory": "/work",
                "container": {
                    "name": container_name,
                    "id": container_id,
                    "inspect_path": str(inspect_path) if inspect_path else None,
                    "contract_path": str(container_contract_path)
                    if container_contract_path
                    else None,
                },
                "lifecycle": lifecycle,
                "image": image_facts,
                "mounts": [
                    {
                        "source": str(run_dir / "input"),
                        "target": "/input",
                        "access": "read_only",
                    },
                    {
                        "source": str(run_dir / "output"),
                        "target": "/output",
                        "access": "read_write",
                    },
                    {
                        "source": str(run_dir / "work"),
                        "target": "/work",
                        "access": "read_write",
                    },
                ],
                "network": "none",
                "identity": {
                    "host_uid": os.getuid(),
                    "host_gid": os.getgid(),
                    "container_user": f"{os.getuid()}:{os.getgid()}",
                    "user_namespace": "keep-id",
                },
                "limits": {
                    "pids": 128,
                    "memory": "512m",
                    "memory_swap": "512m",
                    "cpus": 1,
                    "nofile": "256:256",
                    "output_bytes_per_stream": args.output_limit_bytes,
                },
                "execution": {
                    "started": execution_started,
                    "timed_out": timed_out,
                    "output_limit_exceeded": output_limit_exceeded,
                },
                "stdout": artifact_record(stdout_path)
                if stdout_path is not None
                else {"path": None, "exists": False, "bytes": 0, "sha256": None},
                "stderr": artifact_record(stderr_path)
                if stderr_path is not None
                else {"path": None, "exists": False, "bytes": 0, "sha256": None},
                "exit_code": target_exit_code,
                "signal": target_signal,
                "timeout": {
                    "seconds": args.timeout_seconds,
                    "timed_out": timed_out,
                },
                "filesystem_before": {
                    "path": str(before_manifest_path)
                    if before_manifest_path
                    else None,
                    "entries": before_manifest,
                },
                "filesystem_after": {
                    "path": str(after_manifest_path)
                    if after_manifest_path
                    else None,
                    "entries": after_manifest,
                },
                "created_files": created_files,
                "modified_files": modified_files,
                "missing_files": missing_files,
                "artifacts": artifacts,
                "cleanup": {
                    "attempted": container_id is not None,
                    "container_removed": container_removed,
                    "runtime_empty_after": runtime_empty_after,
                    "cleanup_errors": cleanup_errors,
                },
                "tool_versions": {
                    "debug_runner": VERSION,
                    "code_gate": LOCKED_CODE_GATE_VERSION,
                    "podman": runtime_facts.get("podman_version"),
                    "crun": runtime_facts.get("oci_runtime_version"),
                    "python": sys.version.split()[0],
                },
                "policy": {
                    "contract_path": str(args.contract),
                    "contract_sha256": contract_hash,
                    "rootless_required": True,
                    "network_forbidden": True,
                    "production_data_forbidden": True,
                    "automatic_rerun": False,
                    "baseline_runtime": baseline_runtime,
                    "runtime_after": after_runtime,
                },
            }
            try:
                validate_report_shape(report)
                if report_path is None or markdown_path is None:
                    raise RunnerError("HARNESS_FAIL", "report paths unavailable")
                write_json_atomic(report_path, report)
                write_text_atomic(markdown_path, markdown_report(report))
                for path in (report_path, markdown_path):
                    sidecar = Path(f"{path}.sha256")
                    write_text_atomic(
                        sidecar,
                        f"{sha256_file(path)}  {path.name}\n",
                    )
            except BaseException as exc:
                print(
                    f"GG_DEBUG_RUNNER_REPORT_WRITE_ERROR={type(exc).__name__}:{exc}",
                    file=sys.stderr,
                )
                status = "FAIL"
                error_class = "HARNESS_FAIL"

        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                lock_handle.close()
            except OSError:
                pass

    print(f"GG_DEBUG_RUNNER_VERSION={VERSION}")
    print(f"GG_DEBUG_RUNNER_RUN_ID={run_id}")
    print(f"GG_DEBUG_RUNNER_STATUS={status}")
    print(f"GG_DEBUG_RUNNER_ERROR_CLASS={error_class or 'NONE'}")
    print(f"GG_DEBUG_RUNNER_RUN_DIR={run_dir or 'NONE'}")
    print(f"GG_DEBUG_RUNNER_REPORT={report_path or 'NONE'}")
    if report_path is not None and report_path.exists():
        print(f"GG_DEBUG_RUNNER_REPORT_SHA256={sha256_file(report_path)}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
