#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import importlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

contract = importlib.import_module(
    "backend.control_plane_contract"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parser_contract() -> None:
    task_id = "task-" + "a" * 32
    sha = "b" * 64
    head = "c" * 40
    cases = {
        "/help": "HELP",
        "/commands": "HELP",
        "/status": "STATUS",
        "/status " + task_id: "STATUS",
        "/tasks": "TASKS",
        "/stop": "STOP",
        "/stop " + task_id: "STOP",
        "/inspect " + task_id: "INSPECT",
        "/logs " + task_id: "LOGS",
        "/logs " + task_id + " 200": "LOGS",
        "/diff " + task_id: "DIFF",
        "/resume " + task_id: "RESUME",
        "/cleanup " + task_id: "CLEANUP",
        "/doctor": "DOCTOR",
        "/context": "CONTEXT",
        "/bootstrap improve stop handling": "BOOTSTRAP",
        "/approve-task " + task_id + " " + sha + " " + head: "APPROVE_TASK",
        "/reject-task " + task_id + " " + sha: "REJECT_TASK",
    }
    for text, expected in cases.items():
        parsed = contract.parse_control_command(text)
        require(parsed is not None, "Control command did not parse: " + text)
        require(parsed["action"] == expected, "Control action mismatch: " + text)

    for passthrough in (
        "normal model text",
        "/read main.py",
        "/search marker",
        "/git status",
        "/test",
        "/run",
        "/selfdev goal",
        "/autonomy goal",
        "/patch-current old => new",
    ):
        require(
            contract.parse_control_command(passthrough) is None,
            "Non-control command was captured: " + passthrough,
        )

    invalid = (
        "/status bad",
        "/stop task-ABC",
        "/logs " + task_id + " 0",
        "/logs " + task_id + " 201",
        "/bootstrap",
        "/approve-task " + task_id + " short " + head,
        "/reject-task " + task_id,
        "/doctor extra",
    )
    for text in invalid:
        try:
            contract.parse_control_command(text)
        except contract.ControlContractError:
            pass
        else:
            raise RuntimeError("Invalid control command accepted: " + text)


def help_contract() -> None:
    help_text = contract.help_text()
    for command in (
        "/help",
        "/status",
        "/tasks",
        "/inspect",
        "/stop",
        "/logs",
        "/diff",
        "/resume",
        "/cleanup",
        "/doctor",
        "/context",
        "/bootstrap",
        "/approve-task",
        "/reject-task",
    ):
        require(command in help_text, "Help omitted command: " + command)
    require("SAKNAS AVSIKTLIGT" in help_text, "Forbidden authority notice missing.")


def bounded_selfdev_grammar_contract() -> None:
    from backend import autonomy_model_runner as semantic

    for marker in (
        "ijtail ::= ijchar{0,255}",
        "ijfull ::= ijchar{255}",
        "hjson ::= lead ijtail",
        "oldjson ::= ijseq8 lead ijseq8",
        "newjson ::= ijseq16",
        "whyjson ::= lead ijtail",
    ):
        require(marker in semantic.SELFDEV_GBNF, "Bounded grammar marker missing: " + marker)

    for width in range(2, 17):
        previous = "ijtail" if width == 2 else "ijseq" + str(width - 1)
        marker = (
            "ijseq"
            + str(width)
            + " ::= ijfull "
            + previous
            + " | "
            + previous
        )
        require(marker in semantic.SELFDEV_GBNF, "Bounded grammar chain missing: " + marker)
    for forbidden in (
        "hjson ::= lead ijchar*",
        "oldjson ::= ijchar* lead ijchar*",
        "newjson ::= ijchar*",
        "whyjson ::= lead ijchar*",
    ):
        require(forbidden not in semantic.SELFDEV_GBNF, "Unbounded grammar survived: " + forbidden)

    repetition_bounds = [
        int(match.group(2) or match.group(1))
        for match in re.finditer(r"\{(\d+)(?:,(\d+))?\}", semantic.SELFDEV_GBNF)
    ]
    require(
        repetition_bounds and max(repetition_bounds) <= 255,
        "Selfdev grammar exceeds llama.cpp sane repetition bounds.",
    )
    for invalid_marker in (
        "ijchar{0,1023}",
        "ijchar{0,2048}",
        "ijchar{1,6000}",
        "ijchar{0,6000}",
        "inner-char{0,8192}",
    ):
        require(
            invalid_marker not in semantic.SELFDEV_GBNF,
            "Known llama.cpp-crashing grammar survived: " + invalid_marker,
        )

    require(8 * 255 + 1 + 8 * 255 == 4081, "OLD grammar capacity changed.")
    require(16 * 255 == 4080, "NEW grammar capacity changed.")

    sample = "\n".join(
        (
            'HYPOTHESIS_JSON="bounded change"',
            'OLD_JSON="VALUE = 1"',
            'NEW_JSON="VALUE = 2"',
            'WHY_JSON="the new value satisfies the bounded goal"',
            "GG_MODEL_RUNNER_OK",
        )
    )
    parsed = semantic.parse_selfdev_semantic_text(sample)
    require(parsed["old_text"] == "VALUE = 1", "Bounded semantic OLD mismatch.")
    require(parsed["new_text"] == "VALUE = 2", "Bounded semantic NEW mismatch.")


def ledger_contract() -> None:
    task_id = "task-" + "d" * 32
    with tempfile.TemporaryDirectory(prefix="gg-control-ledger-test.") as temporary:
        parent = Path(temporary).resolve(strict=True)
        ledger = contract.TaskLedger(parent / "ledger")
        ledger.create(
            task_id,
            "BOOTSTRAP",
            "RUNNING",
            "bounded goal",
            "@current",
            "ws.file.context-composer",
            base_head="e" * 40,
        )
        ledger.append_log(task_id, "INTENT|RUNNING|bounded goal")
        current = ledger.get(task_id)
        require(current is not None, "Created task missing.")
        require(current["logs"] == ["INTENT|RUNNING|bounded goal"], "Ledger log mismatch.")

        reloaded = contract.TaskLedger(parent / "ledger")
        interrupted = reloaded.get(task_id)
        require(interrupted is not None, "Reloaded task missing.")
        require(interrupted["status"] == "BLOCKED", "Active restart did not fail closed.")
        require(
            interrupted["last_reason"] == "WORKBENCH_RESTARTED_DURING_ACTIVE_TASK",
            "Restart reason mismatch.",
        )
        reloaded.update(
            task_id,
            status="WAITING_PERSISTENT_APPLY",
            candidate_sha256="f" * 64,
            diff_sha256="1" * 64,
        )
        summary = contract.task_summary(reloaded.get(task_id) or {})
        require("WAITING_PERSISTENT_APPLY" in summary, "Task summary status missing.")
        reloaded.remove(task_id)
        require(reloaded.get(task_id) is None, "Task ledger remove failed.")


def apply_contract() -> None:
    task_id = "task-" + "2" * 32
    request = contract.validate_apply_request(
        {
            "schema": contract.APPLY_REQUEST_SCHEMA,
            "action": "APPLY_SELFDEV",
            "task_id": task_id,
            "base_head": "3" * 40,
            "target_relative_path": contract.TARGET_RELATIVE_PATH,
            "before_sha256": "4" * 64,
            "candidate_sha256": "5" * 64,
            "diff_sha256": "6" * 64,
        }
    )
    response = contract.validate_apply_response(
        {
            "schema": contract.APPLY_RESPONSE_SCHEMA,
            "task_id": task_id,
            "status": "APPLIED_VERIFIED",
            "base_head": "3" * 40,
            "before_sha256": "4" * 64,
            "candidate_sha256": "5" * 64,
            "host_after_sha256": "5" * 64,
            "host_repo_changed": True,
            "output": "verified",
        },
        request,
    )
    require(response["status"] == "APPLIED_VERIFIED", "Apply response status mismatch.")


def stop_runtime_contract() -> None:
    import importlib
    import sys
    import types
    from unittest import mock as stop_mock

    class Signal:
        def __init__(self, *_types: object) -> None:
            self.callbacks: list[object] = []

        def connect(self, callback: object) -> None:
            self.callbacks.append(callback)

        def emit(self, *args: object) -> None:
            for callback in list(self.callbacks):
                callback(*args)  # type: ignore[operator]

    class QObject:
        def __init__(self, _parent: object = None) -> None:
            pass

    class QProcess:
        class ProcessState:
            NotRunning = 0
            Running = 2

        class ProcessChannelMode:
            SeparateChannels = 1

        class ExitStatus:
            NormalExit = 0

        SeparateChannels = 1

        def __init__(self, _parent: object = None) -> None:
            self._state = self.ProcessState.Running
            self.finished = Signal()
            self.readyReadStandardOutput = Signal()
            self.terminated = False
            self.killed = False

        def state(self) -> int:
            return self._state

        def terminate(self) -> None:
            self.terminated = True
            self._state = self.ProcessState.NotRunning
            self.finished.emit(15, self.ExitStatus.NormalExit)

        def kill(self) -> None:
            self.killed = True
            self._state = self.ProcessState.NotRunning

        def deleteLater(self) -> None:
            pass

        def readAllStandardError(self) -> bytes:
            return b""

        def readAllStandardOutput(self) -> bytes:
            return b""

    class QTimer:
        @staticmethod
        def singleShot(_milliseconds: int, callback: object) -> None:
            callback()  # type: ignore[operator]

    class QCoreApplication:
        @staticmethod
        def instance() -> None:
            return None

    def slot(*_types: object, **_kwargs: object):
        def decorate(function: object) -> object:
            return function
        return decorate

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = QObject
    qtcore.Signal = Signal
    qtcore.QProcess = QProcess
    qtcore.QTimer = QTimer
    qtcore.QCoreApplication = QCoreApplication
    qtcore.QUrl = object
    qtcore.Slot = slot
    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QGuiApplication = object
    qtqml = types.ModuleType("PySide6.QtQml")
    qtqml.QQmlApplicationEngine = object
    package = types.ModuleType("PySide6")
    sys.modules["PySide6"] = package
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules.pop("backend.resident_chat_qt", None)
    require(
        "backend.resident_chat_qt" not in sys.modules,
        "Resident Qt cache was not invalidated.",
    )
    sys.modules.pop("main", None)
    application = importlib.import_module("main")

    focused_context = application._selfdev_source_context(
        (PROJECT / "main.py").read_text(encoding="utf-8"),
        "REGRESSION_FAILED:synthetic",
        24000,
    )
    for marker in (
        "DIAGNOSTIC",
        "FUNCTION parse_selfdev_command",
        "FUNCTION parse_autonomy_command",
        "FUNCTION parse_write_command",
        "FUNCTION parse_safe_tool_command",
        "ChatBridge.submit",
        "ChatBridge._submit_selfdev",
    ):
        require(
            marker in focused_context,
            "Focused selfdev context priority missing: " + marker,
        )
    require(
        len(focused_context) <= 24000,
        "Focused selfdev context exceeded the fixed budget.",
    )

    class Root:
        def __init__(self) -> None:
            self.nodes: list[tuple[str, str, str, str, str, int]] = []
            self.activities: list[tuple[bool, str]] = []

        def appendRealNode(
            self,
            author: str,
            kind: str,
            text: str,
            context: str,
            state: str,
            offset: int,
            task_id: str = "",
        ) -> None:
            self.nodes.append(
                (author, kind, text, context, state, offset, task_id)
            )

        def setBridgeActivity(self, busy: bool, task_id: str) -> None:
            self.activities.append((busy, task_id))

    root = Root()
    isolated_ledger = stop_mock.Mock()
    isolated_ledger.all.return_value = []
    with (
        stop_mock.patch.object(
            application.control_contract,
            "TaskLedger",
            return_value=isolated_ledger,
        ),
        stop_mock.patch.object(
            application.ChatBridge,
            "_recover_selfdev_records",
            return_value=None,
        ),
        stop_mock.patch.object(
            application.ChatBridge,
            "_block_unrecoverable_autonomy_records",
            return_value=None,
        ),
    ):
        bridge = application.ChatBridge(root)
    process = QProcess()
    bridge._process = process
    bridge._state = {
        "kind": "model",
        "request_id": "chat-" + "7" * 32,
        "context": "@current",
        "workspace": "ws.file.context-composer",
        "workspace_source": "qml/components/ContextComposer.qml",
        "workspace_sha256": "8" * 64,
        "evidence": "/nonexistent-evidence",
        "request_path": "/nonexistent-request",
        "stoppable": "1",
    }
    process.finished.connect(bridge._finished)
    bridge.stopActive()
    require(process.terminated, "TERM was not sent to the active runner.")
    require(
        any("STOPPED_BY_USER=" in node[2] for node in root.nodes),
        "Stopped process did not emit STOPPED_BY_USER.",
    )
    bridge.stopActive()
    require(
        any("NO_ACTIVE_TASK" in node[2] for node in root.nodes),
        "Idempotent no-active stop receipt missing.",
    )

    critical = QProcess()
    bridge._process = critical
    bridge._state = {
        "kind": "control-apply",
        "task_id": "task-" + "9" * 32,
        "context": "@current",
        "workspace": "ws.file.context-composer",
        "stoppable": "0",
    }
    bridge.stopActive()
    require(
        critical.state() != QProcess.ProcessState.NotRunning,
        "Critical atomic apply was interruptible.",
    )
    require(
        any("STOP_BLOCKED_CRITICAL_ATOMIC_APPLY" in node[2] for node in root.nodes),
        "Critical apply stop block receipt missing.",
    )
    critical.kill()
    bridge._process = None
    bridge._state = None


def synthetic_apply_runner_contract() -> None:
    from backend import control_plane_runner as runner

    def git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(repo), *args],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Synthetic git failed: "
                + result.stderr.decode("utf-8", errors="replace")
            )
        return result.stdout.decode("utf-8", errors="strict").strip()

    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    with tempfile.TemporaryDirectory(prefix="gg-control-apply-test.") as temporary:
        base = Path(temporary).resolve(strict=True)
        repo = base / "repo"
        project = repo / "projects" / "gg-ai-desktop"
        tests = project / "tests"
        runtime = base / "runtime"
        tests.mkdir(parents=True)
        runtime.mkdir(mode=0o700)
        original = b"VALUE = 1\n"
        target = project / "main.py"
        target.write_bytes(original)
        for relative in runner.REGRESSION_TESTS:
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("print('SYNTHETIC_REGRESSION=PASS')\n", encoding="utf-8")
        git(repo, "init", "-q")
        git(repo, "add", "--", ".")
        git(
            repo,
            "-c",
            "user.name=GG Control Test",
            "-c",
            "user.email=gg-control-test@localhost",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-q",
            "-m",
            "synthetic baseline",
        )
        head = git(repo, "rev-parse", "HEAD")

        old_project = runner.PROJECT
        old_repo = runner.REPO
        old_target = runner.TARGET
        old_runtime = runner._runtime_root

        def prepare_task(character: str, candidate: bytes) -> tuple[str, Path, Path]:
            task_id = "task-" + character * 32
            task_root = runtime / ("gg-selfdev-task." + character * 32)
            candidate_project = task_root / "tree" / "projects" / "gg-ai-desktop"
            candidate_tests = candidate_project / "tests"
            candidate_tests.mkdir(parents=True)
            task_root.chmod(0o700)
            (candidate_project / "main.py").write_bytes(candidate)
            for relative in runner.REGRESSION_TESTS:
                destination = candidate_project / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    "print('SYNTHETIC_REGRESSION=PASS')\n",
                    encoding="utf-8",
                )
            diff_bytes = runner._diff(original, candidate).encode("utf-8")
            (task_root / "verified.diff").write_bytes(diff_bytes)
            result = {
                "schema": "gg.workbench.selfdev-result.v1",
                "task_id": task_id,
                "base_head": head,
                "target_relative_path": contract.TARGET_RELATIVE_PATH,
                "before_sha256": digest(original),
                "candidate_sha256": digest(candidate),
                "diff_sha256": digest(diff_bytes),
                "foundation_gate_report_sha256": "a" * 64,
                "candidate_write_count": 1,
                "model_call_count": 1,
                "host_repo_changed": False,
                "persistent_selfdev_write": "NONE",
                "status": "WAITING_PERSISTENT_APPLY",
            }
            (task_root / "verified-result.json").write_bytes(
                contract.canonical_json(result)
            )
            request = contract.validate_apply_request(
                {
                    "schema": contract.APPLY_REQUEST_SCHEMA,
                    "action": "APPLY_SELFDEV",
                    "task_id": task_id,
                    "base_head": head,
                    "target_relative_path": contract.TARGET_RELATIVE_PATH,
                    "before_sha256": digest(original),
                    "candidate_sha256": digest(candidate),
                    "diff_sha256": digest(diff_bytes),
                }
            )
            request_path = runtime / ("gg-control-apply-request." + character + ".json")
            request_path.write_bytes(contract.canonical_json(request))
            request_path.chmod(0o600)
            evidence = runtime / ("gg-control-apply." + character)
            evidence.mkdir(mode=0o700)
            return task_id, request_path, evidence

        try:
            runner.PROJECT = project
            runner.REPO = repo
            runner.TARGET = target
            runner._runtime_root = lambda: runtime

            candidate = b"VALUE = 2\n"
            task_id, request_path, evidence = prepare_task("b", candidate)
            response = runner.execute(str(evidence), str(request_path))
            require(response["task_id"] == task_id, "Synthetic apply task mismatch.")
            require(target.read_bytes() == candidate, "Synthetic apply did not reach target.")
            require(
                (runtime / ("gg-selfdev-task." + "b" * 32) / "apply-receipt.json").is_file(),
                "Synthetic apply receipt missing.",
            )

            target.write_bytes(original)
            require(git(repo, "status", "--porcelain=v1") == "", "Synthetic reset not clean.")
            rollback_candidate = b"VALUE = 3\n"
            _task2, request2, evidence2 = prepare_task("c", rollback_candidate)
            real_git = runner._git
            status_calls = 0

            def fail_post_scope(*args: str, timeout: int = 30):
                nonlocal status_calls
                result = real_git(*args, timeout=timeout)
                if args and args[0] == "status":
                    status_calls += 1
                    if status_calls == 3:
                        return subprocess.CompletedProcess(
                            result.args,
                            0,
                            b"?? unexpected\x00",
                            b"",
                        )
                return result

            runner._git = fail_post_scope
            try:
                runner.execute(str(evidence2), str(request2))
            except runner.ControlApplyError as exc:
                require(
                    "POST_APPLY_SCOPE_INVALID" in str(exc),
                    "Synthetic forced rollback classified incorrectly.",
                )
            else:
                raise RuntimeError("Synthetic invalid post-scope unexpectedly applied.")
            finally:
                runner._git = real_git

            require(
                target.read_bytes() == original,
                "Synthetic post-apply failure did not restore original bytes.",
            )
        finally:
            runner.PROJECT = old_project
            runner.REPO = old_repo
            runner.TARGET = old_target
            runner._runtime_root = old_runtime


def selfdev_apply_limit_alignment_contract() -> None:
    import ast as _ast

    def module_int(path: Path, name: str) -> int:
        source = path.read_text(
            encoding="utf-8",
            errors="strict",
        )

        tree = _ast.parse(
            source,
            filename=str(path),
        )

        values: list[int] = []

        for node in tree.body:
            if not isinstance(
                node,
                (
                    _ast.Assign,
                    _ast.AnnAssign,
                ),
            ):
                continue

            if isinstance(node, _ast.Assign):
                targets = node.targets
                value = node.value
            else:
                targets = [node.target]
                value = node.value

            if value is None:
                continue

            for target in targets:
                if not (
                    isinstance(target, _ast.Name)
                    and target.id == name
                ):
                    continue

                literal = _ast.literal_eval(value)

                require(
                    type(literal) is int,
                    "Limit is not an integer: "
                    + name,
                )

                values.append(literal)

        require(
            len(values) == 1,
            "Limit assignment cardinality invalid: "
            + name,
        )

        return values[0]

    main_path = PROJECT / "main.py"
    runner_path = (
        PROJECT
        / "backend/control_plane_runner.py"
    )

    selfdev_limit = module_int(
        main_path,
        "SELFDEV_MAX_TARGET_BYTES",
    )

    apply_limit = module_int(
        runner_path,
        "MAX_TARGET_BYTES",
    )

    require(
        selfdev_limit == 327680,
        "Selfdev target bound drift.",
    )

    require(
        apply_limit == 327680,
        "Control apply target bound drift.",
    )

    require(
        selfdev_limit == apply_limit,
        "Selfdev/apply size envelope diverged.",
    )

    require(
        main_path.stat().st_size
        <= selfdev_limit,
        "Real main.py exceeds selfdev/apply envelope.",
    )

    print(
        "SELFDEV_APPLY_LIMIT_ALIGNMENT=PASS"
    )


def source_integration_contract() -> None:
    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")
    main_qml = (PROJECT / "qml" / "Main.qml").read_text(encoding="utf-8")
    composer = (PROJECT / "qml" / "components" / "ContextComposer.qml").read_text(
        encoding="utf-8"
    )
    runner = (PROJECT / "backend" / "control_plane_runner.py").read_text(
        encoding="utf-8"
    )
    config = json.loads(
        (PROJECT / "config" / "workbench-v1.2.json").read_text(encoding="utf-8")
    )

    require(
        main_py.index("control_contract.parse_control_command(value)")
        < main_py.index("if self._active():", main_py.index("def submit(")),
        "Control commands are not parsed before the busy gate.",
    )
    for marker in (
        "def _submit_control(",
        "def _stop_active(",
        "def _control_apply_finished(",
        "QTimer.singleShot(3000",
        '"stoppable": "0"',
        "stop_signal.connect(bridge.stopActive)",
    ):
        require(marker in main_py, "Main control integration missing: " + marker)
    for marker in (
        "signal bridgeStop()",
        "function setBridgeActivity(",
        "onStopRequested: root.bridgeStop()",
    ):
        require(marker in main_qml, "Main QML stop integration missing: " + marker)
    for marker in (
        "signal stopRequested()",
        "id: stopButton",
        "enabled: root.busy",
        "onClicked: root.stopRequested()",
    ):
        require(marker in composer, "Composer Stop button missing: " + marker)

    control = config["control_plane"]
    require(
        control["commands"]
        == [
            "/help",
            "/commands",
            "/status",
            "/tasks",
            "/inspect",
            "/stop",
            "/logs",
            "/diff",
            "/resume",
            "/cleanup",
            "/doctor",
            "/context",
            "/bootstrap",
            "/approve-task",
            "/reject-task",
        ],
        "Control command registry mismatch.",
    )
    require(control["authority"] == contract.CONTROL_AUTHORITY, "Control authority mismatch.")
    require(
        control["bootstrap_apply_authority"] == contract.BOOTSTRAP_APPLY_AUTHORITY,
        "Bootstrap apply authority mismatch.",
    )
    require(
        control["bootstrap_model_semantic_grammar"] == "FINITE_FIELD_BOUNDS_V1",
        "Bootstrap bounded semantic grammar config mismatch.",
    )
    for key in (
        "network_authority",
        "general_action_authority",
        "shell_authority",
        "arbitrary_exec_authority",
        "arbitrary_path_authority",
        "git_commit_authority",
    ):
        require(control[key] == "NONE", "Authority expansion: " + key)

    for marker in (
        "HOST_REPO_NOT_CLEAN",
        "BASE_HEAD_DRIFT",
        "CANDIDATE_SHA_DRIFT",
        "VERIFIED_DIFF_SHA_DRIFT",
        "_run_regression(candidate_project)",
        "os.replace(temporary, TARGET)",
        "HOST_POSTHASH_FAILED",
        "ROLLBACK_POSTHASH_FAILED",
    ):
        require(marker in runner, "Apply runner invariant missing: " + marker)
    require("shell=True" not in runner, "Apply runner gained shell execution.")
    require(contract.TARGET_RELATIVE_PATH in runner, "Runner target constant missing.")


def context_resolver_v1_ingress_contract() -> None:
    main_source = (
        PROJECT
        / "main.py"
    ).read_text(
        encoding="utf-8"
    )

    main_qml = (
        PROJECT
        / "qml/Main.qml"
    ).read_text(
        encoding="utf-8"
    )

    workspace_qml = (
        PROJECT
        / "qml/components/WorkspaceSurface.qml"
    ).read_text(
        encoding="utf-8"
    )

    composer_qml = (
        PROJECT
        / "qml/components/ContextComposer.qml"
    ).read_text(
        encoding="utf-8"
    )

    require(
        (
            "def syncContextSnapshot("
            in main_source
        ),
        "Snapshot slot missing.",
    )

    require(
        (
            "def _resolved_chat_context("
            in main_source
        ),
        "Resolved context seam missing.",
    )

    require(
        (
            "from backend import context_resolver"
            in main_source
        ),
        "Resolver import seam missing.",
    )

    require(
        (
            "contextSnapshotSync"
            in main_qml
        ),
        "Snapshot QML signal missing.",
    )

    require(
        (
            "root.contextSnapshotSync("
            "root.buildContextSnapshotJson())"
            in main_qml
        ),
        (
            "Snapshot emission missing "
            "from ordinary submit."
        ),
    )

    require(
        (
            "function contextSnapshot("
            "maximumObjects)"
            in workspace_qml
        ),
        (
            "Workspace snapshot "
            "function missing."
        ),
    )

    require(
        (
            "signal submitRequested("
            in composer_qml
            and "string text"
            in composer_qml
            and "string contextReference"
            in composer_qml
            and "string workspaceObjectId"
            in composer_qml
        ),
        (
            "Composer three-argument "
            "contract changed."
        ),
    )

    print(
        "CONTEXT_RESOLVER_INGRESS_CONTRACT=PASS"
    )


def idekompass_decision_ingress_contract():
    import ast as _ast
    from pathlib import Path as _Path

    project = _Path(__file__).resolve().parents[1]
    main_path = project / "main.py"
    module_path = project / "backend/idekompass_decision_ingress.py"

    main_source = main_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    module_source = module_path.read_text(
        encoding="utf-8",
        errors="strict",
    )

    if (
        main_source.count(
            "from backend import idekompass_decision_ingress"
        )
        != 1
    ):
        raise AssertionError(
            "Idékompass import cardinality mismatch"
        )

    if (
        main_source.count(
            "from backend import orchestrator_mandate_evaluation_adapter"
        )
        != 1
    ):
        raise AssertionError(
            "Mandate evaluation adapter import cardinality mismatch"
        )

    tree = _ast.parse(main_source)

    bridge = [
        node
        for node in tree.body
        if isinstance(node, _ast.ClassDef)
        and node.name == "ChatBridge"
    ]
    if len(bridge) != 1:
        raise AssertionError("ChatBridge cardinality mismatch")

    submit = [
        node
        for node in bridge[0].body
        if isinstance(node, _ast.FunctionDef)
        and node.name == "submit"
    ]
    if len(submit) != 1:
        raise AssertionError("submit cardinality mismatch")

    def call_name(call):
        target = call.func
        if isinstance(target, _ast.Name):
            return target.id
        if isinstance(target, _ast.Attribute):
            parts = [target.attr]
            base = target.value
            while isinstance(base, _ast.Attribute):
                parts.append(base.attr)
                base = base.value
            if isinstance(base, _ast.Name):
                parts.append(base.id)
            return ".".join(reversed(parts))
        return type(target).__name__

    calls = [
        (node.lineno, call_name(node))
        for node in _ast.walk(submit[0])
        if isinstance(node, _ast.Call)
    ]

    resolved = [
        line
        for line, name in calls
        if name.endswith("_resolved_chat_context")
    ]
    route = [
        line
        for line, name in calls
        if name.endswith("_natural_intent_route")
    ]
    idekompass = [
        line
        for line, name in calls
        if name == "idekompass_decision_ingress.decide"
    ]
    mandate_evaluation = [
        line
        for line, name in calls
        if name
        == "orchestrator_mandate_evaluation_adapter.evaluate_not_required"
    ]
    request = [
        line
        for line, name in calls
        if name.endswith("_submit_resident_prompt")
        and line > idekompass[0]
    ]

    if not (
        len(resolved) == 1
        and len(route) == 1
        and len(idekompass) == 1
        and len(mandate_evaluation) == 1
        and len(request) == 1
    ):
        raise AssertionError(
            "Context→Laser→Idékompass→chat call cardinality mismatch"
        )

    if not (
        resolved[0]
        < route[0]
        < idekompass[0]
        < mandate_evaluation[0]
        < request[0]
    ):
        raise AssertionError(
            "Context→Laser→Idékompass→chat order mismatch"
        )

    required = (
        'ACTION_AUTHORITY = "NONE"',
        'LEDGER_PERSISTENCE = "NONE"',
        "PLAN_ACTION_IS_APPROVAL = False",
        "MODEL_OUTPUT_AS_EVIDENCE = False",
        'CAPABILITY_EXECUTION = "NONE"',
        'AUTOMATIC_MODEL_DISPATCH = "NONE"',
        "ledger.finalize_record(",
        "ledger.verify_chain(",
        "hypothesis.build_hypothesis_state(",
        "hypothesis.select_next_step(",
        "cognitive.make_and_revalidate_state(",
    )

    for token in required:
        if token not in module_source:
            raise AssertionError(
                "Idékompass module contract missing: " + token
            )

    forbidden = (
        "append_candidate(",
        "autonomy_controller",
    )

    for token in forbidden:
        if token in module_source:
            raise AssertionError(
                "Idékompass forbidden dependency: " + token
            )

    print("IDEKOMPASS_CONTEXT_LASER_ORDER=PASS")
    print("IDEKOMPASS_LEDGER_APPEND=NONE")
    print("IDEKOMPASS_ACTION_AUTHORITY=NONE")
    print("IDEKOMPASS_CONTROL_CONTRACT=PASS")


def explicit_orchestrator_assignment_contract() -> None:
    import json as assignment_json
    from pathlib import Path as AssignmentPath
    from unittest import mock as assignment_mock

    import main as application

    registry_path = (
        application.REPO_ROOT
        / "orchestrator"
        / "registry"
        / "participant-registry-v1.0.json"
    )
    registry = assignment_json.loads(
        registry_path.read_text(
            encoding="utf-8",
            errors="strict",
        )
    )
    names: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.startswith("GG-"):
                names.add(name)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(registry)

    if tuple(sorted(names)) != tuple(
        sorted(application.ORCHESTRATOR_PARTICIPANTS)
    ):
        raise AssertionError(
            "Orchestrator participant allowlist drift."
        )

    project = AssignmentPath(application.__file__).resolve().parent
    composer = (
        project
        / "qml"
        / "components"
        / "ContextComposer.qml"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_qml = (
        project
        / "qml"
        / "Main.qml"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    for marker in (
        "signal assignmentSetRequested(",
        "signal assignmentClearRequested()",
        'objectName: "orchestratorParticipantSelector"',
        'objectName: "orchestratorCreatorActorInput"',
        'objectName: "orchestratorAssignmentSetButton"',
        'objectName: "orchestratorAssignmentClearButton"',
        "currentIndex: -1",
    ):
        if marker not in composer:
            raise AssertionError(
                "Composer assignment seam missing: " + marker
            )

    for participant in application.ORCHESTRATOR_PARTICIPANTS:
        if composer.count('"' + participant + '"') != 1:
            raise AssertionError(
                "Composer participant option mismatch: "
                + participant
            )

    for marker in (
        "signal bridgeAssignmentSet(",
        "signal bridgeAssignmentClear()",
        "root.bridgeAssignmentSet(",
        "root.bridgeAssignmentClear()",
    ):
        if marker not in main_qml:
            raise AssertionError(
                "Main QML assignment relay missing: " + marker
            )

    with (
        assignment_mock.patch.object(
            application.resident_state.WorkbenchResidentInformationState,
            "bootstrap_workbench_sources",
            return_value=object(),
        ),
        assignment_mock.patch.object(
            application.control_contract,
            "TaskLedger",
            return_value=object(),
        ),
        assignment_mock.patch.object(
            application.ChatBridge,
            "_recover_selfdev_records",
            return_value=None,
        ),
        assignment_mock.patch.object(
            application.ChatBridge,
            "_block_unrecoverable_autonomy_records",
            return_value=None,
        ),
    ):
        bridge = application.ChatBridge(application.QObject())

    bridge._append = assignment_mock.Mock()

    before = (
        bridge._orchestrator_assigned_participant,
        bridge._orchestrator_creator_actor,
    )

    bridge._setOrchestratorAssignment(
        "UNKNOWN",
        "human:owner",
    )
    if (
        bridge._orchestrator_assigned_participant,
        bridge._orchestrator_creator_actor,
    ) != before:
        raise AssertionError(
            "Invalid participant mutated assignment state."
        )

    bridge._setOrchestratorAssignment(
        "GG-AI-installator",
        "",
    )
    if (
        bridge._orchestrator_assigned_participant,
        bridge._orchestrator_creator_actor,
    ) != before:
        raise AssertionError(
            "Empty creator actor mutated assignment state."
        )

    bridge._setOrchestratorAssignment(
        "GG-AI-installator",
        "human:owner",
    )
    valid = (
        "GG-AI-installator",
        "human:owner",
    )
    if (
        bridge._orchestrator_assigned_participant,
        bridge._orchestrator_creator_actor,
    ) != valid:
        raise AssertionError(
            "Valid explicit assignment was not retained."
        )

    bridge._setOrchestratorAssignment(
        "UNKNOWN",
        "human:other",
    )
    if (
        bridge._orchestrator_assigned_participant,
        bridge._orchestrator_creator_actor,
    ) != valid:
        raise AssertionError(
            "Invalid reassignment destroyed valid state."
        )

    bridge._clearOrchestratorAssignment()
    if (
        bridge._orchestrator_assigned_participant != ""
        or bridge._orchestrator_creator_actor != ""
    ):
        raise AssertionError(
            "Explicit assignment clear did not reset state."
        )


def main() -> int:
    explicit_orchestrator_assignment_contract()
    context_resolver_v1_ingress_contract()
    idekompass_decision_ingress_contract()
    parser_contract()
    help_contract()
    bounded_selfdev_grammar_contract()
    ledger_contract()
    apply_contract()
    stop_runtime_contract()
    synthetic_apply_runner_contract()
    selfdev_apply_limit_alignment_contract()
    source_integration_contract()
    print("CONTROL_COMMAND_PARSER=PASS")
    print("STOP_BEFORE_BUSY_GATE=PASS")
    print("STOP_BUTTON=PASS")
    print("STOP_RUNTIME_TERM=PASS")
    print("CRITICAL_ATOMIC_APPLY_NOT_INTERRUPTIBLE=PASS")
    print("SELFDEV_SEMANTIC_GRAMMAR_BOUNDED=PASS")
    print("SELFDEV_FOCUSED_CONTEXT_PRIORITY=PASS")
    print("TASK_LEDGER_RESTART_FAIL_CLOSED=PASS")
    print("BOOTSTRAP_EXACT_MAIN_PY_CANDIDATE=PASS")
    print("APPROVE_TASK_TRIPLE_BINDING=PASS")
    print("ATOMIC_APPLY_ROLLBACK=PASS")
    print("SYNTHETIC_APPLY_RUNNER_E2E=PASS")
    print("ARBITRARY_EXEC_AUTHORITY=NONE")
    print("NETWORK_AUTHORITY=NONE")
    print("CONTROL_PLANE_TEST=PASS")
    return 0


def natural_intent_ingress_contract() -> None:
    import ast
    import hashlib
    import sys
    from pathlib import Path

    project = (
        Path(__file__).resolve()
        .parents[1]
    )

    repo = project.parents[1]

    backend = (
        project
        / "backend"
    )

    backend_text = str(
        backend
    )

    if backend_text not in sys.path:
        sys.path.insert(
            0,
            backend_text,
        )

    import capability_registry
    import solver_router

    main_path = (
        project
        / "main.py"
    )

    main_source = (
        main_path.read_text(
            encoding="utf-8"
        )
    )

    tree = ast.parse(
        main_source,
        filename=str(main_path),
    )

    bridges = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.ClassDef,
            )
            and node.name
            == "ChatBridge"
        )
    ]

    require(
        len(bridges) == 1,
        "ChatBridge cardinality invalid.",
    )

    methods = {
        node.name: node
        for node in bridges[
            0
        ].body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    for required in (
        "_ensure_natural_intent_laser",
        "_natural_intent_route",
        "submit",
    ):
        require(
            required in methods,
            (
                "Natural intent method missing: "
                + required
            ),
        )

    def segment(name: str) -> str:
        value = ast.get_source_segment(
            main_source,
            methods[name],
        )

        require(
            value is not None,
            (
                "AST source segment missing: "
                + name
            ),
        )

        return str(value)

    ensure_source = segment(
        "_ensure_natural_intent_laser"
    )

    route_source = segment(
        "_natural_intent_route"
    )

    submit_source = segment(
        "submit"
    )

    require(
        "CapabilityRegistry.load("
        in ensure_source,
        (
            "Capability registry load "
            "missing."
        ),
    )

    require(
        "LaserFocusCache("
        in ensure_source,
        (
            "LaserFocus cache "
            "missing."
        ),
    )

    require(
        "manifest_sha256"
        in ensure_source,
        (
            "Manifest dependency identity "
            "revalidation missing."
        ),
    )

    require(
        "RouteContext("
        in route_source,
        "RouteContext missing.",
    )

    for api_token in ('.bind(', '.lookup('):
        require(
            api_token
            in route_source,
            (
                "Locked Laser API token "
                "missing: "
                + api_token
            ),
        )

    require(
        "laser_query = normalized[:1024]"
        in route_source,
        (
            "Laser query bound "
            "missing."
        ),
    )

    require(
        "decision.automatic_model_dispatch"
        in route_source,
        (
            "Automatic model dispatch "
            "guard missing."
        ),
    )

    require(
        "decision.registered_capability_execution"
        in route_source,
        (
            "Registered execution "
            "guard missing."
        ),
    )

    submit = methods[
        "submit"
    ]

    value_assignments = [
        node
        for node in ast.walk(
            submit
        )
        if (
            isinstance(
                node,
                ast.Assign,
            )
            and len(
                node.targets
            ) == 1
            and isinstance(
                node.targets[
                    0
                ],
                ast.Name,
            )
            and node.targets[
                0
            ].id == "value"
            and isinstance(
                node.value,
                ast.Call,
            )
            and isinstance(
                node.value.func,
                ast.Attribute,
            )
            and isinstance(
                node.value.func.value,
                ast.Name,
            )
            and node.value.func.value.id
            == "text"
            and node.value.func.attr
            == "strip"
        )
    ]

    require(
        len(
            value_assignments
        ) == 1,
        (
            "Existing text.strip() "
            "normalization contract missing."
        ),
    )

    resolved_context_method = methods[
        "_resolved_chat_context"
    ]

    prompt_calls = [
        node
        for node in ast.walk(
            resolved_context_method
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "build_effective_prompt"
        )
    ]

    resolved_context_calls = [
        node
        for node in ast.walk(
            submit
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Attribute,
            )
            and isinstance(
                node.func.value,
                ast.Name,
            )
            and node.func.value.id
            == "self"
            and node.func.attr
            == "_resolved_chat_context"
        )
    ]

    natural_calls = [
        node
        for node in ast.walk(
            submit
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Attribute,
            )
            and isinstance(
                node.func.value,
                ast.Name,
            )
            and node.func.value.id
            == "self"
            and node.func.attr
            == "_natural_intent_route"
        )
    ]

    require(
        len(
            prompt_calls
        ) == 2,
        (
            "Resolved prompt branch "
            "cardinality invalid."
        ),
    )

    require(
        len(
            resolved_context_calls
        ) == 1,
        (
            "Resolved context call "
            "cardinality invalid."
        ),
    )

    require(
        len(
            natural_calls
        ) == 1,
        (
            "Natural route call cardinality "
            "invalid."
        ),
    )

    for prompt_call in prompt_calls:
        require(
            bool(
                prompt_call.args
            )
            and isinstance(
                prompt_call.args[
                    0
                ],
                ast.Name,
            )
            and prompt_call.args[
                0
            ].id == "value",
            (
                "Resolved prompt branch does "
                "not consume the shared "
                "normalized value."
            ),
        )

    for label, call in (
        (
            "context",
            resolved_context_calls[
                0
            ],
        ),
        (
            "laser",
            natural_calls[
                0
            ],
        ),
    ):
        require(
            bool(
                call.args
            )
            and isinstance(
                call.args[
                    0
                ],
                ast.Name,
            )
            and call.args[
                0
            ].id == "value",
            (
                label
                + " does not consume "
                "the shared normalized value."
            ),
        )

    require(
        value_assignments[
            0
        ].lineno
        < resolved_context_calls[
            0
        ].lineno
        < natural_calls[
            0
        ].lineno,
        (
            "Normalized user-value "
            "flow order invalid."
        ),
    )

    route_method = methods[
        "_natural_intent_route"
    ]

    resolved_assignments = [
        node
        for node in ast.walk(
            route_method
        )
        if (
            isinstance(
                node,
                ast.Assign,
            )
            and len(
                node.targets
            ) == 1
            and isinstance(
                node.targets[
                    0
                ],
                ast.Name,
            )
            and node.targets[
                0
            ].id
            == "resolved_object_id"
            and isinstance(
                node.value,
                ast.Call,
            )
            and isinstance(
                node.value.func,
                ast.Name,
            )
            and node.value.func.id
            == "str"
        )
    ]

    require(
        len(
            resolved_assignments
        ) == 1,
        (
            "Resolved workspace object id "
            "assignment missing."
        ),
    )

    resolved_source = (
        ast.get_source_segment(
            main_source,
            resolved_assignments[
                0
            ],
        )
        or ""
    )

    require(
        "workspace_context"
        in resolved_source
        and '"object_id"'
        in resolved_source,
        (
            "Route does not derive object id "
            "from resolved workspace context."
        ),
    )

    route_context_calls = [
        node
        for node in ast.walk(
            route_method
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Attribute,
            )
            and node.func.attr
            == "RouteContext"
        )
    ]

    require(
        len(
            route_context_calls
        ) == 1,
        (
            "RouteContext call cardinality "
            "invalid."
        ),
    )

    object_keywords = [
        keyword
        for keyword in route_context_calls[
            0
        ].keywords
        if keyword.arg
        == "object_id"
    ]

    require(
        len(
            object_keywords
        ) == 1,
        (
            "RouteContext object_id "
            "binding missing."
        ),
    )

    require(
        isinstance(
            object_keywords[
                0
            ].value,
            ast.Name,
        )
        and object_keywords[
            0
        ].value.id
        == "resolved_object_id",
        (
            "RouteContext does not use "
            "resolved workspace object id."
        ),
    )

    route_position = (
        submit_source.index(
            "self._natural_intent_route("
        )
    )

    context_position = (
        submit_source.index(
            "self._resolved_chat_context("
        )
    )

    require(
        context_position
        < route_position,
        (
            "Workspace context must resolve "
            "before natural routing."
        ),
    )

    for parser in (
        "parse_control_command",
        "parse_selfdev_command",
        "parse_autonomy_command",
        "parse_write_command",
        "parse_safe_tool_command",
    ):
        require(
            parser
            in submit_source,
            (
                "Explicit parser missing: "
                + parser
            ),
        )

        require(
            submit_source.index(
                parser
            )
            < route_position,
            (
                "Explicit command route moved "
                "behind natural ingress: "
                + parser
            ),
        )

    model_start = (
        submit_source.index(
            "process.start()",
            route_position,
        )
    )

    require(
        route_position
        < model_start,
        (
            "Natural routing must occur "
            "before local model start."
        ),
    )

    registry = (
        capability_registry
        .CapabilityRegistry.load(
            repo_root=repo,
            project_root=project,
            seed_path=(
                project
                / "config"
                / "capability-seeds-v1.json"
            ),
            manifest_path=(
                project
                / "SOURCE-MANIFEST.json"
            ),
        )
    )

    router = (
        solver_router.SolverRouter(
            registry
        )
    )

    laser = (
        solver_router.LaserFocusCache(
            router
        )
    )

    source = (
        project
        / "qml/components/ContextComposer.qml"
    )

    revision = hashlib.sha256(
        source.read_bytes()
    ).hexdigest()

    context = (
        solver_router.RouteContext(
            query="qml analyze",
            goal_id=(
                "goal-natural-intent-contract"
            ),
            object_id=(
                "ws.file.context-composer"
            ),
            source_revision=revision,
            language="qml",
            diagnostic_class=(
                "NATURAL_INTENT"
            ),
        )
    )

    binding_one = laser.bind(
        context
    )

    binding_two = laser.bind(
        context
    )

    require(
        binding_one.handle_id
        == binding_two.handle_id,
        (
            "Laser binding handle "
            "not deterministic."
        ),
    )

    handle = laser.lookup(
        binding_one.handle_id
    )

    require(
        handle is not None,
        (
            "Bound Laser handle "
            "not retrievable."
        ),
    )

    route = handle.route

    require(
        bool(
            route.intent
        ),
        "Route intent missing.",
    )

    require(
        bool(
            route.route_mode
        ),
        "Route mode missing.",
    )

    require(
        bool(
            route.why
        ),
        "Route WHY missing.",
    )

    require(
        route.automatic_model_dispatch
        is False,
        (
            "Router gained automatic "
            "model authority."
        ),
    )

    require(
        route.registered_capability_execution
        is False,
        (
            "Router gained registered "
            "execution authority."
        ),
    )

    long_intent = (
        "x" * 1400
    )

    projection = (
        " ".join(
            long_intent.split()
        )[:1024]
    )

    require(
        len(
            projection
        ) == 1024,
        (
            "Laser projection bound "
            "invalid."
        ),
    )

    require(
        projection
        != long_intent,
        (
            "Bounded Laser projection "
            "not distinct from long input."
        ),
    )

    print(
        "NATURAL_INTENT_INGRESS_CONTRACT=PASS"
    )
    print(
        "FOLLOW_THE_LIGHT=PASS"
    )
    print(
        "LASER_API_MODE=BIND_LOOKUP"
    )
    print(
        "SHARED_NORMALIZED_USER_VALUE=PRESERVED"
    )
    print(
        "RESOLVED_WORKSPACE_OBJECT_ID=PASS"
    )
    print(
        "LASER_QUERY_MAX_CHARS=1024"
    )
    print(
        "ROUTER_WHY=PRESENT"
    )
    print(
        "AUTOMATIC_MODEL_DISPATCH=NO"
    )
    print(
        "REGISTERED_CAPABILITY_EXECUTION=NO"
    )

if __name__ == "__main__":
    natural_intent_ingress_contract()
    raise SystemExit(main())
