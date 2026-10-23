#!/usr/bin/env python3
"""GG Workbench Safe Tools v1 execution boundary.

Profiles are typed and closed. There is no caller-supplied argv, shell string,
executable path, environment, network target, or persistent-write authority.
"""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.container_platform import container_user
from backend.platform_files import (
    CLOEXEC,
    NOFOLLOW,
    secure_open,
)
from backend.platform_support import (
    executable_path,
    host_environment,
    private_runtime_root,
    workspace_root,
)


import hashlib
import json
import os
import selectors
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from backend import safe_tool_contract as contract

PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
RUNTIME = private_runtime_root()

IMAGE_ID = "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174"
IMAGE_REF = "localhost/gg-code-gate:1.0.0"

READ_MAX_BYTES = 32768
SEARCH_FILE_MAX_BYTES = 1024 * 1024
SEARCH_TOTAL_MAX_BYTES = 16 * 1024 * 1024
SEARCH_MAX_HITS = 80
PROCESS_OUTPUT_MAX_BYTES = 32768
PROCESS_TIMEOUT_SECONDS = 20

DENIED_PARTS = frozenset(
    (
        ".git",
        ".ssh",
        ".gnupg",
        ".mozilla",
        "credentials",
        "credential",
        "secrets",
        "secret",
    )
)
DENIED_NAMES = frozenset(
    (
        ".env",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
        "cookies.sqlite",
        "logins.json",
    )
)

GIT_ENV = host_environment({
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/nonexistent",
})

PODMAN_ENV = host_environment({
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "HOME": str(Path.home()),
    "XDG_RUNTIME_DIR": str(private_runtime_root()),
})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_fd_limited(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = os.read(fd, min(65536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break

    return b"".join(chunks)


def _safe_runtime_path(path: Path, prefix: str) -> Path:
    if path.is_symlink():
        raise RuntimeError("runtime path is symlink")

    resolved_parent = path.parent.resolve(strict=True)
    if resolved_parent != RUNTIME:
        raise RuntimeError("runtime path parent invalid")

    if not path.name.startswith(prefix):
        raise RuntimeError("runtime path prefix invalid")

    return path


def _read_json_regular(path: Path, max_bytes: int = 65536) -> Any:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("request is not a regular file")

    info = path.stat()
    if info.st_size < 2 or info.st_size > max_bytes:
        raise RuntimeError("request size invalid")

    return json.loads(path.read_text(encoding="utf-8"))


def _write_exclusive_json(path: Path, value: dict[str, Any]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )

    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _run_limited(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int = PROCESS_TIMEOUT_SECONDS,
    max_output_bytes: int = PROCESS_OUTPUT_MAX_BYTES,
) -> tuple[int, bytes, bytes, str]:
    if os.name == "nt":
        from backend.platform_process import run_bounded
        return run_bounded(argv, cwd=cwd, env=env, timeout=timeout_seconds,
                           max_output_bytes=max_output_bytes)
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
    )

    if proc.stdout is None or proc.stderr is None:
        proc.kill()
        proc.wait(timeout=1)
        raise RuntimeError("process pipes unavailable")

    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")

    out = bytearray()
    err = bytearray()
    deadline = time.monotonic() + timeout_seconds
    trigger = "NONE"

    while selector.get_map():
        left = max(0.0, deadline - time.monotonic())
        events = selector.select(min(left, 0.05))

        for key, _mask in events:
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue

            target = out if key.data == "stdout" else err
            target.extend(chunk)

        if (
            len(out) > max_output_bytes
            or len(err) > max_output_bytes
        ):
            trigger = "OUTPUT_LIMIT"
            break

        if time.monotonic() >= deadline:
            trigger = "TIMEOUT"
            break

        if proc.poll() is not None and not events:
            # Next select drains EOF.
            pass

    if trigger != "NONE" and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)

    if proc.poll() is None:
        proc.wait(timeout=1)

    # Bounded drain.
    for stream, target in (
        (proc.stdout, out),
        (proc.stderr, err),
    ):
        try:
            remaining = stream.read(max_output_bytes + 1)
        except Exception:
            remaining = b""
        target.extend(remaining)

    if len(out) > max_output_bytes:
        out = out[:max_output_bytes]
        trigger = "OUTPUT_LIMIT"
    if len(err) > max_output_bytes:
        err = err[:max_output_bytes]
        trigger = "OUTPUT_LIMIT"

    return proc.returncode, bytes(out), bytes(err), trigger


def _git_fixed(args: list[str], max_bytes: int = 1024 * 1024) -> bytes:
    argv = [
        executable_path("git"),
        "-C",
        str(REPO),
        "--no-pager",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
        "-c",
        "core.pager=cat",
        "-c",
        "color.ui=false",
        *args,
    ]

    rc, stdout, stderr, trigger = _run_limited(
        argv,
        cwd=REPO,
        env=GIT_ENV,
        timeout_seconds=8,
        max_output_bytes=max_bytes,
    )

    if trigger != "NONE":
        raise RuntimeError("git process stopped: " + trigger)
    if rc != 0:
        raise RuntimeError(
            "git process failed: "
            + stderr.decode("utf-8", errors="replace")[:1000]
        )

    return stdout


def _tracked_files() -> list[str]:
    raw = _git_fixed(
        ["ls-files", "-z"],
        max_bytes=1024 * 1024,
    )

    paths = [
        item.decode("utf-8", errors="strict")
        for item in raw.split(b"\0")
        if item
    ]

    if len(paths) > 10000:
        raise RuntimeError("tracked file count exceeds Safe Tools v1 limit")

    return paths


def _path_denied(relative: Path) -> bool:
    lower_parts = tuple(part.lower() for part in relative.parts)

    if any(part in DENIED_PARTS for part in lower_parts):
        return True

    if relative.name.lower() in DENIED_NAMES:
        return True

    if relative.name.lower().endswith((".key", ".pem", ".p12", ".pfx")):
        return True

    return False


def _open_tracked_regular(relative_text: str, max_bytes: int) -> tuple[bytes, Path]:
    relative = Path(relative_text)

    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or _path_denied(relative)
    ):
        raise RuntimeError("path policy blocked")

    canonical = relative.as_posix()
    tracked = set(_tracked_files())

    if canonical not in tracked:
        raise RuntimeError("path is not a tracked repository file")

    repo_root = REPO.resolve(strict=True)
    target = REPO / relative
    parent = target.parent.resolve(strict=True)

    if not parent.is_relative_to(repo_root):
        raise RuntimeError("path escaped repository root")

    fd = secure_open(target, os.O_RDONLY | CLOEXEC | NOFOLLOW)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError("target is not a regular file")

        if info.st_size > max_bytes:
            raise RuntimeError("target exceeds profile byte limit")

        data = _read_fd_limited(fd, max_bytes)
    finally:
        os.close(fd)

    if len(data) > max_bytes:
        raise RuntimeError("target exceeded profile byte limit while reading")

    return data, relative


def _profile_read(request: dict[str, Any]) -> tuple[str, str]:
    path = request["arguments"]["path"]
    data, relative = _open_tracked_regular(path, READ_MAX_BYTES)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("READ target is not UTF-8 text") from exc

    output = (
        "PROFILE=READ\n"
        f"PATH={relative.as_posix()}\n"
        f"BYTES={len(data)}\n"
        f"SHA256={_sha256(data)}\n"
        "----- BEGIN FILE -----\n"
        + text
        + ("" if text.endswith("\n") else "\n")
        + "----- END FILE -----"
    )

    return output, "IN_PROCESS_TRACKED_READ"


def _profile_search(request: dict[str, Any]) -> tuple[str, str]:
    literal = request["arguments"]["literal"]
    tracked = _tracked_files()

    hits: list[str] = []
    scanned = 0

    for rel_text in tracked:
        rel = Path(rel_text)

        if _path_denied(rel):
            continue

        target = REPO / rel

        try:
            if target.is_symlink():
                continue

            parent = target.parent.resolve(strict=True)
            if not parent.is_relative_to(REPO.resolve(strict=True)):
                continue

            fd = secure_open(
                target,
                os.O_RDONLY | CLOEXEC | NOFOLLOW,
            )
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    continue
                if info.st_size > SEARCH_FILE_MAX_BYTES:
                    continue
                if scanned + info.st_size > SEARCH_TOTAL_MAX_BYTES:
                    break
                data = _read_fd_limited(fd, SEARCH_FILE_MAX_BYTES)
            finally:
                os.close(fd)
        except OSError:
            continue

        if len(data) > SEARCH_FILE_MAX_BYTES:
            continue

        scanned += len(data)

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        for number, line in enumerate(text.splitlines(), start=1):
            if literal in line:
                clipped = line.strip()
                if len(clipped) > 240:
                    clipped = clipped[:237] + "..."
                hits.append(
                    f"{rel.as_posix()}:{number}:{clipped}"
                )
                if len(hits) >= SEARCH_MAX_HITS:
                    break

        if len(hits) >= SEARCH_MAX_HITS:
            break

    output = (
        "PROFILE=SEARCH\n"
        f"LITERAL={literal}\n"
        f"SCANNED_BYTES={scanned}\n"
        f"HIT_COUNT={len(hits)}\n"
        + ("\n".join(hits) if hits else "NO_MATCHES")
    )

    return output, "IN_PROCESS_TRACKED_LITERAL_SEARCH"


def _profile_git(request: dict[str, Any]) -> tuple[str, str]:
    if _git_fixed(["remote"]).strip():
        raise RuntimeError("Safe GIT profile requires zero configured remotes")

    operation = request["arguments"]["operation"]

    mapping = {
        "status": [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        "diff": [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--",
        ],
        "log": [
            "log",
            "-n",
            "20",
            "--no-decorate",
            "--format=%H%x09%s",
        ],
        "show-head": [
            "show",
            "--stat",
            "--oneline",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "HEAD",
        ],
    }

    raw = _git_fixed(mapping[operation], max_bytes=PROCESS_OUTPUT_MAX_BYTES)
    text = raw.decode("utf-8", errors="replace")

    output = (
        "PROFILE=GIT\n"
        f"OPERATION={operation}\n"
        "NETWORK_AUTHORITY=NONE\n"
        "REMOTE_COUNT=0\n"
        + (text if text else "(empty)")
    )

    return output, "HOST_GIT_FIXED_ARGV"


def _copy_project_snapshot(destination: Path) -> None:
    destination.mkdir(mode=0o700)

    for source in sorted(PROJECT.rglob("*")):
        relative = source.relative_to(PROJECT)
        target = destination / relative

        if source.is_symlink():
            raise RuntimeError(
                "project symlink is not allowed in sandbox snapshot: "
                + relative.as_posix()
            )

        if source.is_dir():
            target.mkdir(exist_ok=True)
            continue

        if not source.is_file():
            raise RuntimeError(
                "unsupported project filesystem object: "
                + relative.as_posix()
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()

        fd = secure_open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o400,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)


def _canonical_image_id(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("image id missing")

    if value.startswith("sha256:"):
        value = value[7:]

    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RuntimeError("image id invalid")

    return value


def _inspect_created_container(
    name: str,
    snapshot: Path,
    entrypoint: str,
    cmd: list[str],
) -> None:
    result = subprocess.run(
        [executable_path("podman"), "inspect", name],
        cwd=REPO,
        env=PODMAN_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError("podman inspect failed")

    raw = json.loads(result.stdout.decode("utf-8"))

    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise RuntimeError("podman inspect shape invalid")

    item = raw[0]

    if _canonical_image_id(item.get("Image")) != IMAGE_ID:
        raise RuntimeError("sandbox image id mismatch")

    config = item.get("Config") or {}
    host = item.get("HostConfig") or {}
    state = item.get("State") or {}
    network = item.get("NetworkSettings") or {}
    mounts = item.get("Mounts") or []

    if config.get("Entrypoint") != [entrypoint]:
        raise RuntimeError("sandbox entrypoint mismatch")
    if config.get("Cmd") != cmd:
        raise RuntimeError("sandbox command mismatch")
    if config.get("WorkingDir") != "/project":
        raise RuntimeError("sandbox workdir mismatch")
    if config.get("User") != container_user():
        raise RuntimeError("sandbox user mismatch")

    if host.get("ReadonlyRootfs") is not True:
        raise RuntimeError("sandbox root is not read-only")
    if host.get("NetworkMode") != "none":
        raise RuntimeError("sandbox network mode mismatch")
    if host.get("Privileged") is not False:
        raise RuntimeError("sandbox privileged mismatch")
    if host.get("Devices") not in ([], None):
        raise RuntimeError("sandbox devices are not empty")
    if host.get("PortBindings") not in ({}, None):
        raise RuntimeError("sandbox port bindings are not empty")

    security = host.get("SecurityOpt") or []
    if not any("no-new-privileges" in str(x) for x in security):
        raise RuntimeError("sandbox NoNewPrivs missing")

    cap_drop = host.get("CapDrop") or []
    if not isinstance(cap_drop, list) or len(cap_drop) < 10:
        raise RuntimeError("sandbox capability drop contract missing")

    if state.get("Status") != "created" or state.get("Running") is not False:
        raise RuntimeError("sandbox was not inspected pre-start")

    networks = network.get("Networks") or {}
    if set(networks) not in (set(), {"none"}):
        raise RuntimeError("sandbox network attachment mismatch")

    if len(mounts) != 1:
        raise RuntimeError("sandbox mount count mismatch")

    mount = mounts[0]
    if mount.get("Destination") != "/project":
        raise RuntimeError("sandbox mount destination mismatch")
    if mount.get("RW") is not False:
        raise RuntimeError("sandbox project mount is writable")
    if Path(str(mount.get("Source"))).resolve() != snapshot.resolve():
        raise RuntimeError("sandbox mount source mismatch")


def _sandbox_profile(profile: str) -> tuple[str, str]:
    image = subprocess.run(
        [
            executable_path("podman"),
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            IMAGE_REF,
        ],
        cwd=REPO,
        env=PODMAN_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if image.returncode != 0:
        raise RuntimeError("locked sandbox image is unavailable")

    if _canonical_image_id(
        image.stdout.decode("utf-8").strip()
    ) != IMAGE_ID:
        raise RuntimeError("locked sandbox image drift")

    nonce = uuid.uuid4().hex[:24]
    snapshot_root = RUNTIME / ("gg-safe-tool-snapshot." + nonce)
    snapshot = snapshot_root / "project"
    container_name = "gg-safe-tool-" + nonce

    snapshot_root.mkdir(mode=0o700)

    if profile == contract.PROFILE_TEST:
        code = (
            "import runpy\n"
            "paths=["
            "'/project/tests/test_local_ai_contract.py',"
            "'/project/tests/test_source_contract.py',"
            "'/project/tests/test_ux_baseline_contract.py',"
            "'/project/tests/test_safe_tool_contract.py'"
            "]\n"
            "for p in paths:\n"
            "  try:\n"
            "    runpy.run_path(p,run_name='__main__')\n"
            "  except SystemExit as e:\n"
            "    c=0 if e.code is None else int(e.code)\n"
            "    if c!=0: raise\n"
            "print('SAFE_TOOL_TEST_SUITE=PASS')\n"
        )
        entrypoint = "/usr/bin/python3"
        cmd = ["-B", "-c", code]
        required_markers = (
            "LOCAL_AI_CONTRACT_TEST=PASS",
            "SOURCE_CONTRACT_TEST=PASS",
            "UX_LOCAL_CHAT_CONTRACT=PASS",
            "SAFE_TOOL_CONTRACT_TEST=PASS",
            "SAFE_TOOL_TEST_SUITE=PASS",
        )
    else:
        entrypoint = "/usr/bin/python3"
        cmd = [
            "-B",
            "/project/backend/local_ai_model_runner.py",
        ]
        required_markers = (
            "WB3D_MODEL_RUNNER_SELFTEST=PASS",
            "WB3D_MODEL_RUNNER_SELFTEST_PODMAN_EXECUTION=NO",
            "WB3D_MODEL_RUNNER_SELFTEST_NETWORK=NO",
        )

    try:
        _copy_project_snapshot(snapshot)

        create_argv = [
            executable_path("podman"),
            "create",
            "--name",
            container_name,
            "--pull=never",
            "--network=none",
            "--no-hosts",
            "--read-only",
            "--read-only-tmpfs=false",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--userns=keep-id",
            "--user",
            container_user(),
            "--pids-limit=128",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1",
            "--ulimit",
            "nofile=256:256",
            "--workdir=/project",
            "--mount",
            (
                "type=bind,src="
                + str(snapshot)
                + ",target=/project,ro=true,relabel=private"
            ),
            "--entrypoint",
            entrypoint,
            IMAGE_ID,
            *cmd,
        ]

        created = subprocess.run(
            create_argv,
            cwd=REPO,
            env=PODMAN_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if created.returncode != 0:
            raise RuntimeError(
                "sandbox create failed: "
                + created.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[:1000]
            )

        _inspect_created_container(
            container_name,
            snapshot,
            entrypoint,
            cmd,
        )

        rc, stdout, stderr, trigger = _run_limited(
            [
                executable_path("podman"),
                "start",
                "--attach",
                container_name,
            ],
            cwd=REPO,
            env=PODMAN_ENV,
            timeout_seconds=20,
            max_output_bytes=PROCESS_OUTPUT_MAX_BYTES,
        )

        if trigger != "NONE":
            raise RuntimeError("sandbox stopped: " + trigger)

        if rc != 0:
            raise RuntimeError(
                "sandbox profile failed: "
                + stderr.decode("utf-8", errors="replace")[:1000]
            )

        text = stdout.decode("utf-8", errors="replace")

        for marker in required_markers:
            if marker not in text:
                raise RuntimeError(
                    "sandbox expected marker missing: " + marker
                )

        output = (
            f"PROFILE={profile}\n"
            "BACKEND=PODMAN_LOCKED_READONLY_SANDBOX\n"
            "NETWORK_MODE=none\n"
            "PROJECT_MOUNT=READ_ONLY_SNAPSHOT\n"
            + text
        )

        return output, "PODMAN_LOCKED_READONLY_SANDBOX"

    finally:
        subprocess.run(
            [
                executable_path("podman"),
                "rm",
                "-f",
                container_name,
            ],
            cwd=REPO,
            env=PODMAN_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        shutil.rmtree(snapshot_root, ignore_errors=True)


def _response(
    request: dict[str, Any],
    *,
    status: str,
    output: str,
    backend: str,
) -> dict[str, Any]:
    encoded = output.encode("utf-8")
    if len(encoded) > PROCESS_OUTPUT_MAX_BYTES:
        output = encoded[:PROCESS_OUTPUT_MAX_BYTES].decode(
            "utf-8",
            errors="replace",
        )

    value = {
        "schema": contract.RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "status": status,
        "profile": request["profile"],
        "output": output,
        "evidence": {
            "authority": contract.AUTHORITY,
            "effect_class": "READ_ONLY",
            "network_authority": "NONE",
            "persistent_write_authority": "NONE",
            "backend": backend,
            "output_sha256": _sha256(output.encode("utf-8")),
        },
    }

    return contract.validate_response(
        value,
        request["request_id"],
        request["profile"],
    )


def execute(evidence: Path, request_path: Path) -> int:
    evidence = _safe_runtime_path(evidence, "gg-safe-tool.")
    request_path = _safe_runtime_path(
        request_path,
        "gg-workbench-tool-request.",
    )

    if evidence.exists():
        if evidence.is_symlink() or not evidence.is_dir():
            raise RuntimeError("evidence path invalid")
        if any(evidence.iterdir()):
            raise RuntimeError("evidence directory is not empty")
    else:
        evidence.mkdir(mode=0o700)

    request = contract.validate_request(
        _read_json_regular(request_path)
    )

    _write_exclusive_json(
        evidence / "request.json",
        request,
    )

    profile = request["profile"]

    if profile == contract.PROFILE_READ:
        output, backend = _profile_read(request)
    elif profile == contract.PROFILE_SEARCH:
        output, backend = _profile_search(request)
    elif profile == contract.PROFILE_GIT:
        output, backend = _profile_git(request)
    elif profile in (contract.PROFILE_TEST, contract.PROFILE_RUN):
        output, backend = _sandbox_profile(profile)
    else:
        raise RuntimeError("profile dispatcher invariant failed")

    response = _response(
        request,
        status="PASS",
        output=output,
        backend=backend,
    )

    _write_exclusive_json(
        evidence / "response.json",
        response,
    )

    print("SAFE_TOOL_EXECUTION=PASS")
    print("SAFE_TOOL_PROFILE=" + profile)
    print("SAFE_TOOL_AUTHORITY=" + contract.AUTHORITY)
    print("SAFE_TOOL_EFFECT_CLASS=READ_ONLY")
    print("SAFE_TOOL_NETWORK_AUTHORITY=NONE")
    print("SAFE_TOOL_PERSISTENT_WRITE_AUTHORITY=NONE")
    print("SAFE_TOOL_BACKEND=" + backend)
    print("SAFE_TOOL_RESPONSE_SHA256=" + response["evidence"]["output_sha256"])
    return 0


def selftest() -> int:
    contract.validate_request(
        {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "tool-" + ("b" * 32),
            "profile": "READ",
            "arguments": {"path": "projects/gg-ai-desktop/main.py"},
        }
    )

    forbidden = (
        "shell" + "=True",
        "os." + "system(",
        "subprocess." + "call(",
        "cu" + "rl ",
        "wg" + "et ",
    )
    source = Path(__file__).read_text(encoding="utf-8")

    for marker in forbidden:
        if marker in source:
            raise RuntimeError("forbidden executor marker: " + marker)

    print("SAFE_TOOL_RUNNER_SELFTEST=PASS")
    print("CALLER_SUPPLIED_ARGV_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_EXECUTABLE_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_ENV_AUTHORITY=NONE")
    print("NETWORK_AUTHORITY=NONE")
    print("PERSISTENT_WRITE_AUTHORITY=NONE")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--selftest"]:
        return selftest()

    if len(sys.argv) != 4 or sys.argv[1] != "--execute-tool":
        print(
            "usage: safe_tool_runner.py --execute-tool EVIDENCE REQUEST_JSON",
            file=sys.stderr,
        )
        return 64

    evidence = Path(sys.argv[2])
    request_path = Path(sys.argv[3])

    try:
        return execute(evidence, request_path)
    except Exception as exc:
        try:
            if evidence.parent.resolve(strict=True) == RUNTIME:
                if evidence.exists() and evidence.is_dir() and not evidence.is_symlink():
                    failure = {
                        "schema": "gg.workbench.safe-tool-failure.v1",
                        "reason": str(exc),
                    }
                    failure_path = evidence / "runner-failure.json"
                    if not failure_path.exists():
                        _write_exclusive_json(failure_path, failure)
        except Exception:
            pass

        print("SAFE_TOOL_EXECUTION=FAIL", file=sys.stderr)
        print("STOP_REASON=" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
