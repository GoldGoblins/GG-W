from __future__ import annotations

from backend.platform_files import (
    NOFOLLOW,
    secure_open,
)
from backend.platform_support import (
    executable_path,
    host_environment,
    private_runtime_root,
    workspace_root,
)


from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable
import uuid

from . import post_draft_qml_driver


PROJECT = Path(
    __file__
).resolve().parents[2]

PREFLIGHT_RUNNER_PATH = (
    PROJECT
    / "backend"
    / "live_aid"
    / "qml_preflight_runner.py"
)

REPAIR_RUNNER_PATH = (
    PROJECT
    / "backend"
    / "live_aid"
    / "repair_model_runner.py"
)


class ExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    state: str
    source: str
    source_sha256: str
    repair_attempts: int
    model_dispatch_count: int
    execution_ready: bool
    blocked_fault_layer: str
    blocked_reason: str
    model_evidence_paths: tuple[str, ...]
    events: tuple[dict[str, Any], ...]


DETERMINISTIC_FALLBACK_OUTCOMES = frozenset(
    (
        "CLOSED",
        "NOT_APPLICABLE",
        "UNSUPPORTED",
        "EXECUTION_FAILED_CLOSED",
        "REVALIDATION_NOT_DONE",
    )
)

MODEL_FALLBACK_ALLOWED_OUTCOMES = frozenset(
    (
        "NOT_APPLICABLE",
        "UNSUPPORTED",
        "EXECUTION_FAILED_CLOSED",
        "REVALIDATION_NOT_DONE",
    )
)


@dataclass(frozen=True)
class DeterministicFallbackDecision:
    outcome: str
    reason: str

    @property
    def model_fallback_allowed(
        self,
    ) -> bool:
        return (
            self.outcome
            in MODEL_FALLBACK_ALLOWED_OUTCOMES
        )


class PostDraftQmlExecutor:
    """Autonomous Stage-E backend executor.

    It may invoke only the frozen QML preflight runner and the frozen
    repair-model runner. It owns no persistent source-write, Git,
    shell, generic command, network, or user-code execution authority.

    Model output remains untrusted. Automatic mutation is limited to
    the private in-memory candidate held by the Stage-E driver.
    """

    def __init__(
        self,
        *,
        object_id: str,
        source_name: str,
        source_relative_path: str,
        max_repair_attempts: int = 1,
        model_dispatch_budget: int = 1,
        timeout_seconds: int = 300,
        event_sink: (
            Callable[[dict[str, Any]], None]
            | None
        ) = None,
        deterministic_fallback_gate: (
            Callable[
                [
                    post_draft_qml_driver
                    .DriverCommand
                ],
                DeterministicFallbackDecision,
            ]
            | None
        ) = None,
    ):
        if (
            not isinstance(
                model_dispatch_budget,
                int,
            )
            or isinstance(
                model_dispatch_budget,
                bool,
            )
            or not 0 <= model_dispatch_budget <= 8
        ):
            raise ExecutorError(
                "MODEL_DISPATCH_BUDGET_INVALID"
            )

        if (
            not isinstance(
                timeout_seconds,
                int,
            )
            or isinstance(
                timeout_seconds,
                bool,
            )
            or not 1 <= timeout_seconds <= 900
        ):
            raise ExecutorError(
                "TIMEOUT_INVALID"
            )

        if (
            deterministic_fallback_gate
            is not None
            and not callable(
                deterministic_fallback_gate
            )
        ):
            raise ExecutorError(
                "DETERMINISTIC_FALLBACK_GATE_INVALID"
            )

        self._deterministic_fallback_gate = (
            deterministic_fallback_gate
        )

        self.driver = (
            post_draft_qml_driver
            .PostDraftQmlDriver(
                object_id=object_id,
                source_name=source_name,
                source_relative_path=
                    source_relative_path,
                max_repair_attempts=
                    max_repair_attempts,
            )
        )

        self.model_dispatch_budget = (
            model_dispatch_budget
        )

        self.timeout_seconds = (
            timeout_seconds
        )

        self._event_sink = event_sink
        self._events: list[
            dict[str, Any]
        ] = []

        self._sequence = 0
        self._model_dispatch_count = 0
        self._model_evidence_paths: list[
            str
        ] = []

    def _emit(
        self,
        event_name: str,
        **fields: Any,
    ) -> None:
        self._sequence += 1

        snapshot = (
            self.driver.snapshot()
        )

        event: dict[str, Any] = {
            "sequence":
                self._sequence,
            "event":
                event_name,
            "driver_state":
                snapshot.state.value,
            "source_sha256":
                snapshot.source_sha256,
            "repair_attempts":
                snapshot.repair_attempts,
            "model_dispatch_count":
                self._model_dispatch_count,
        }

        event.update(fields)

        self._events.append(
            dict(event)
        )

        if self._event_sink is not None:
            self._event_sink(
                dict(event)
            )

    def _result(
        self,
    ) -> ExecutionResult:
        snapshot = (
            self.driver.snapshot()
        )

        return ExecutionResult(
            state=snapshot.state.value,
            source=snapshot.source,
            source_sha256=
                snapshot.source_sha256,
            repair_attempts=
                snapshot.repair_attempts,
            model_dispatch_count=
                self._model_dispatch_count,
            execution_ready=
                snapshot.execution_ready,
            blocked_fault_layer=
                snapshot.blocked_fault_layer,
            blocked_reason=
                snapshot.blocked_reason,
            model_evidence_paths=tuple(
                self._model_evidence_paths
            ),
            events=tuple(
                dict(item)
                for item in self._events
            ),
        )

    def _block(
        self,
        *,
        fault_layer: str,
        reason: str,
    ) -> None:
        self.driver.accept_external_fault(
            fault_layer=fault_layer,
            reason=reason,
        )

        self._emit(
            "BLOCKED",
            fault_layer=fault_layer,
            reason=reason,
        )

    def _write_request(
        self,
        *,
        prefix: str,
        request: dict[str, Any],
    ) -> tuple[Path, Path]:
        runtime = private_runtime_root().resolve(
            strict=True
        )

        token = uuid.uuid4().hex

        run_dir = runtime / (
            prefix + token
        )

        run_dir.mkdir(
            mode=0o700
        )

        request_path = (
            run_dir
            / "request.json"
        )

        payload = (
            json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | NOFOLLOW
        )

        fd = secure_open(
            request_path,
            flags,
            0o600,
        )

        try:
            os.write(
                fd,
                payload,
            )

            os.fsync(
                fd
            )
        finally:
            os.close(fd)

        return (
            run_dir,
            request_path,
        )

    def _invoke_runner(
        self,
        *,
        runner: Path,
        prefix: str,
        request: dict[str, Any],
        fault_layer: str,
    ) -> dict[str, Any]:
        resolved_runner = (
            runner.resolve(
                strict=True
            )
        )

        allowed = {
            PREFLIGHT_RUNNER_PATH.resolve(
                strict=True
            ),
            REPAIR_RUNNER_PATH.resolve(
                strict=True
            ),
        }

        if resolved_runner not in allowed:
            raise ExecutorError(
                "RUNNER_NOT_ALLOWLISTED"
            )

        (
            run_dir,
            request_path,
        ) = self._write_request(
            prefix=prefix,
            request=request,
        )

        env = os.environ.copy()

        env[
            "PYTHONDONTWRITEBYTECODE"
        ] = "1"

        env[
            "PYTHONNOUSERSITE"
        ] = "1"

        env.pop(
            "PYTHONPATH",
            None,
        )

        try:
            try:
                completed = subprocess.run(
                    [
                        executable_path("python3"),
                        "-B",
                        str(
                            resolved_runner
                        ),
                        str(
                            request_path
                        ),
                    ],
                    cwd=str(
                        PROJECT
                    ),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=
                        self.timeout_seconds,
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                reason = (
                    resolved_runner.name
                    + ":TIMEOUT"
                )

                self._block(
                    fault_layer=
                        fault_layer,
                    reason=reason,
                )

                raise ExecutorError(
                    reason
                ) from exc

            stdout = (
                completed.stdout
                .decode(
                    "utf-8",
                    "replace",
                )
                .strip()
            )

            stderr = (
                completed.stderr
                .decode(
                    "utf-8",
                    "replace",
                )
                .strip()
            )

            if completed.returncode != 0:
                reason = (
                    resolved_runner.name
                    + ":RC:"
                    + str(
                        completed.returncode
                    )
                    + ":"
                    + stderr[-1200:]
                )

                self._block(
                    fault_layer=
                        fault_layer,
                    reason=reason,
                )

                raise ExecutorError(
                    reason
                )

            try:
                value = json.loads(
                    stdout
                )
            except json.JSONDecodeError as exc:
                reason = (
                    resolved_runner.name
                    + ":STDOUT_JSON"
                )

                self._block(
                    fault_layer=
                        fault_layer,
                    reason=reason,
                )

                raise ExecutorError(
                    reason
                ) from exc

            if not isinstance(
                value,
                dict,
            ):
                reason = (
                    resolved_runner.name
                    + ":RESPONSE_NOT_OBJECT"
                )

                self._block(
                    fault_layer=
                        fault_layer,
                    reason=reason,
                )

                raise ExecutorError(
                    reason
                )

            return value

        finally:
            shutil.rmtree(
                run_dir,
                ignore_errors=True,
            )

    def _execute_preflight(
        self,
        command:
            post_draft_qml_driver
            .DriverCommand,
    ) -> (
        post_draft_qml_driver
        .DriverCommand
        | None
    ):
        self._emit(
            "VERIFYING",
            command_kind="PREFLIGHT",
        )

        response = self._invoke_runner(
            runner=
                PREFLIGHT_RUNNER_PATH,
            prefix=
                "gg-live-aid-preflight.",
            request=command.request,
            fault_layer="HARNESS",
        )

        self._emit(
            "PREFLIGHT_RESPONSE",
            gate_status=
                response.get(
                    "gate_status",
                    "",
                ),
            gate_report_sha256=
                response.get(
                    "gate_report_sha256",
                    "",
                ),
        )

        return (
            self.driver
            .accept_preflight_response(
                response
            )
        )

    def _default_deterministic_fallback_gate(
        self,
        command:
            post_draft_qml_driver
            .DriverCommand,
    ) -> DeterministicFallbackDecision:
        diagnostics = command.request.get(
            "diagnostics"
        )

        if not isinstance(
            diagnostics,
            list,
        ):
            raise ExecutorError(
                "DETERMINISTIC_DIAGNOSTICS_INVALID"
            )

        machine_safe_edit_present = False

        for diagnostic in diagnostics:
            if not isinstance(
                diagnostic,
                dict,
            ):
                continue

            fix = diagnostic.get(
                "fix"
            )

            if (
                isinstance(
                    fix,
                    dict,
                )
                and fix.get(
                    "applicability"
                ) == "safe"
                and isinstance(
                    fix.get("edits"),
                    list,
                )
                and bool(
                    fix.get("edits")
                )
            ):
                machine_safe_edit_present = True
                break

            machine_edits = diagnostic.get(
                "machine_edits"
            )

            if (
                isinstance(
                    machine_edits,
                    list,
                )
                and bool(
                    machine_edits
                )
            ):
                machine_safe_edit_present = True
                break

        if machine_safe_edit_present:
            return DeterministicFallbackDecision(
                outcome="UNSUPPORTED",
                reason=(
                    "QML_MACHINE_SAFE_EDIT_PRESENT_"
                    "BUT_EXECUTION_ADAPTER_NOT_WIRED"
                ),
            )

        return DeterministicFallbackDecision(
            outcome="NOT_APPLICABLE",
            reason=(
                "QML_PREFLIGHT_HAS_NO_EXACT_"
                "MACHINE_SAFE_EDIT"
            ),
        )

    def _deterministic_fallback_decision(
        self,
        command:
            post_draft_qml_driver
            .DriverCommand,
    ) -> DeterministicFallbackDecision:
        gate = (
            self._deterministic_fallback_gate
        )

        if gate is None:
            decision = (
                self
                ._default_deterministic_fallback_gate(
                    command
                )
            )
        else:
            decision = gate(
                command
            )

        if not isinstance(
            decision,
            DeterministicFallbackDecision,
        ):
            raise ExecutorError(
                "DETERMINISTIC_FALLBACK_DECISION_TYPE"
            )

        if (
            decision.outcome
            not in DETERMINISTIC_FALLBACK_OUTCOMES
        ):
            raise ExecutorError(
                "DETERMINISTIC_FALLBACK_OUTCOME_INVALID"
            )

        if (
            not isinstance(
                decision.reason,
                str,
            )
            or not decision.reason.strip()
            or len(decision.reason) > 512
        ):
            raise ExecutorError(
                "DETERMINISTIC_FALLBACK_REASON_INVALID"
            )

        return decision

    def _execute_repair(
        self,
        command:
            post_draft_qml_driver
            .DriverCommand,
    ) -> (
        post_draft_qml_driver
        .DriverCommand
    ):
        deterministic = (
            self
            ._deterministic_fallback_decision(
                command
            )
        )

        if deterministic.outcome == "CLOSED":
            reason = (
                "MODEL_DISPATCH_FORBIDDEN_AFTER_"
                "DETERMINISTIC_CLOSURE"
            )

            self._block(
                fault_layer="HARNESS",
                reason=reason,
            )

            raise ExecutorError(
                reason
            )

        if not deterministic.model_fallback_allowed:
            reason = (
                "MODEL_FALLBACK_NOT_AUTHORIZED:"
                + deterministic.outcome
            )

            self._block(
                fault_layer="HARNESS",
                reason=reason,
            )

            raise ExecutorError(
                reason
            )

        if (
            self._model_dispatch_count
            >= self.model_dispatch_budget
        ):
            reason = (
                "MODEL_DISPATCH_BUDGET_EXHAUSTED"
            )

            self._block(
                fault_layer="TRANSPORT",
                reason=reason,
            )

            raise ExecutorError(
                reason
            )

        self._model_dispatch_count += 1

        self._emit(
            "REPAIRING",
            command_kind="REPAIR",
            activity="GENERATING",
            deterministic_outcome=
                deterministic.outcome,
            deterministic_reason=
                deterministic.reason,
            model_fallback_required=True,
        )

        response = self._invoke_runner(
            runner=
                REPAIR_RUNNER_PATH,
            prefix=
                "gg-live-aid-repair-ui.",
            request=command.request,
            fault_layer="TRANSPORT",
        )

        evidence = response.get(
            "model_evidence_path"
        )

        if isinstance(
            evidence,
            str,
        ) and evidence:
            self._model_evidence_paths.append(
                evidence
            )

        next_command = (
            self.driver
            .accept_repair_response(
                response
            )
        )

        self._emit(
            "CANDIDATE_APPLIED_IN_MEMORY",
            candidate_sha256=
                self.driver
                .snapshot()
                .source_sha256,
        )

        return next_command

    def run_complete_draft(
        self,
        source: str,
    ) -> ExecutionResult:
        self.driver.update_draft(
            source
        )

        self._emit(
            "DRAFT"
        )

        command = (
            self.driver
            .mark_draft_complete()
        )

        self._emit(
            "DRAFT_COMPLETE"
        )

        for _step in range(16):
            if (
                command.kind
                == post_draft_qml_driver
                .DriverCommandKind
                .PREFLIGHT
            ):
                next_command = (
                    self._execute_preflight(
                        command
                    )
                )

                if next_command is None:
                    result = self._result()

                    if (
                        result.execution_ready
                        and result.state
                        == "READY_TO_RUN"
                    ):
                        self._emit(
                            "READY_TO_RUN"
                        )

                        return self._result()

                    return result

                command = (
                    next_command
                )

                continue

            if (
                command.kind
                == post_draft_qml_driver
                .DriverCommandKind
                .REPAIR
            ):
                command = (
                    self._execute_repair(
                        command
                    )
                )

                continue

            reason = (
                "UNSUPPORTED_DRIVER_COMMAND:"
                + str(
                    command.kind
                )
            )

            self._block(
                fault_layer="HARNESS",
                reason=reason,
            )

            raise ExecutorError(
                reason
            )

        reason = (
            "EXECUTOR_STEP_BUDGET_EXHAUSTED"
        )

        self._block(
            fault_layer="HARNESS",
            reason=reason,
        )

        raise ExecutorError(
            reason
        )
