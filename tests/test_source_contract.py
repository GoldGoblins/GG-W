#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT / "config/workbench-v1.2.json"
MANIFEST = PROJECT / "SOURCE-MANIFEST.json"

FROZEN = {
    "backend/local_ai_contract.py":
        "740849d413a3461d40ee83cba71c46f81ec2447ea351942e47868f3478a012d1",
    "backend/local_ai_model_runner.py":
        '1d32863be1886e737969b765b1d87744654253abc6b3074fc1dc93087e86d232',
    "schemas/local-ai-request.schema.json":
        "61fbe405c818ebd838cb51a82d0ea26ce1719742c6caaf951d02cbf346385c5b",
    "schemas/local-ai-response.schema.json":
        "f6a85fcbe5706805c5ced616a6809e38d3fda535bb141f1931b00a7fc54fe6b6",
    "tests/test_local_ai_contract.py":
        "2ddeef4d612db0f7e740a3d7bf8da96f8d4dac2b2d9dcac05e407faafb01bf85",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def main() -> int:
    for rel, expected in FROZEN.items():
        require(
            sha256(PROJECT / rel) == expected,
            "Frozen source changed: " + rel,
        )

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    require(
        cfg["schema"] == "gg.ai-desktop.workbench-config.v1.2",
        "Config schema mismatch.",
    )
    require(cfg["version"] == "1.2", "Config version mismatch.")
    require(
        cfg["data_mode"]
        == "LOCAL_MODEL_CHAT_SAFE_TOOLS_LIMITED_WRITE_AUTONOMY_CONTROL_PLANE",
        "Data mode mismatch.",
    )
    require(
        cfg["composer"]["bridge"] == "CONNECTED_LOCAL_MODEL",
        "Bridge state mismatch.",
    )
    require(
        cfg["integrations"]["model"] == "ENABLED_LOCAL_CHAT",
        "Model integration mismatch.",
    )
    for key in (
        "orchestrator",
        "operator_terminal_process",
    ):
        require(
            cfg["integrations"][key] == "DISABLED",
            "Authority expansion: " + key,
        )
    require(
        cfg["integrations"]["network"] == "TASK_SCOPED_AFTER_MANDATE",
        "Network integration is not task-scoped.",
    )
    require(
        cfg["integrations"]["real_command_execution"]
        == "ENABLED_FIXED_GREEN_SAFE_TOOLS",
        "Safe Tools execution integration mismatch.",
    )
    require(
        cfg["integrations"]["limited_write_execution"]
        == "ENABLED_EXPLICIT_CURRENT_QML_PATCH_V1",
        "Limited Write execution integration mismatch.",
    )
    require(
        cfg["integrations"]["code_gate_runtime"]
        == "ENABLED_LIMITED_WRITE_QML_PREAPPLY",
        "Limited Write Code Gate integration mismatch.",
    )
    require(
        cfg["integrations"]["autonomy"]
        == "ENABLED_TASK_BOUND_CANDIDATE_V1",
        "Autonomy integration mismatch.",
    )
    require(
        cfg["integrations"]["control_plane"]
        == "ENABLED_TYPED_CONTROL_PLANE_V1"
        and cfg["integrations"]["verified_task_apply"]
        == "ENABLED_EXPLICIT_VERIFIED_MAIN_PY_V1",
        "Control Plane integration mismatch.",
    )
    control_plane = cfg["control_plane"]
    require(
        control_plane["commands"]
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
        "Control Plane command registry mismatch.",
    )
    require(
        control_plane["authority"]
        == "CONTROL_ONLY_NO_NEW_EXECUTION_AUTHORITY_V1",
        "Control Plane authority mismatch.",
    )
    require(
        control_plane["bootstrap_apply_authority"]
        == "YELLOW_EXACT_VERIFIED_MAIN_PY_APPLY_V1"
        and control_plane["bootstrap_target"]
        == "projects/gg-ai-desktop/main.py",
        "Control Plane bootstrap apply boundary mismatch.",
    )
    require(
        control_plane["bootstrap_model_semantic_grammar"]
        == "FINITE_FIELD_BOUNDS_V1",
        "Control Plane bounded model grammar mismatch.",
    )
    require(
        control_plane["stop_priority"] == "PARSED_BEFORE_BUSY_GATE"
        and control_plane["stop_escalation"] == "TERM_THEN_KILL_3000MS"
        and control_plane["stop_idempotent"] is True,
        "Control Plane stop contract mismatch.",
    )
    for key in (
        "network_authority",
        "general_action_authority",
        "shell_authority",
        "arbitrary_exec_authority",
        "arbitrary_path_authority",
        "git_commit_authority",
    ):
        require(
            control_plane[key] == "NONE",
            "Control Plane authority expansion: " + key,
        )
    safe_tools = cfg["safe_tools"]
    require(
        safe_tools["authority"] == "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
        "Safe Tools authority mismatch.",
    )
    require(
        safe_tools["profiles"] == ["READ", "SEARCH", "GIT", "TEST", "RUN"],
        "Safe Tools profile set mismatch.",
    )
    require(
        safe_tools["caller_supplied_argv_authority"] == "NONE",
        "Caller argv authority changed.",
    )
    require(
        safe_tools["caller_supplied_executable_authority"] == "NONE",
        "Caller executable authority changed.",
    )
    require(
        safe_tools["caller_supplied_environment_authority"] == "NONE",
        "Caller environment authority changed.",
    )
    require(
        safe_tools["network_authority"] == "NONE",
        "Safe Tools network authority changed.",
    )
    require(
        safe_tools["persistent_write_authority"] == "NONE",
        "Safe Tools write authority changed.",
    )
    require(
        safe_tools["model_autonomous_tool_invocation"]
        == "ENABLED_RESIDENT_READ_SEARCH_TEST_RUN_LOOP_V1",
        "Resident READ/SEARCH/TEST/RUN loop marker mismatch.",
    )
    require(
        safe_tools["chat_model_information_tools"]
        == "ENABLED_CONTROLLED_READ_SEARCH_V1",
        "Controlled information-tool chat seam missing.",
    )

    limited_write = cfg["limited_write"]
    require(
        limited_write["authority"]
        == "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        "Limited Write authority mismatch.",
    )
    require(
        limited_write["target_workspace_object_id"]
        == "ws.file.context-composer",
        "Limited Write Workspace target mismatch.",
    )
    require(
        limited_write["target_source_path"]
        == "qml/components/ContextComposer.qml",
        "Limited Write source target mismatch.",
    )
    require(
        limited_write["patch_policy"]
        == "EXACT_SINGLE_OCCURRENCE_REPLACE_ONLY",
        "Limited Write patch policy mismatch.",
    )
    require(
        limited_write["network_authority"] == "NONE",
        "Limited Write network authority changed.",
    )
    require(
        limited_write["general_action_authority"] == "NONE",
        "Limited Write general authority changed.",
    )
    require(
        limited_write["model_autonomous_write_invocation"]
        == "DISABLED_V1",
        "Autonomous model write invocation unexpectedly enabled.",
    )
    autonomy = cfg["autonomy"]
    require(
        autonomy["authority"] == "YELLOW_LOCAL_TASK_BOUND_CANDIDATE_V1",
        "Autonomy candidate authority mismatch.",
    )
    require(
        autonomy["architecture"]
        == "REUSE_EXISTING_K7_COGNITIVE_HIERARCHY",
        "Existing cognitive hierarchy is not the autonomy runtime source.",
    )
    require(
        autonomy["parallel_agent_brain"] == "FORBIDDEN",
        "Parallel agent brain unexpectedly enabled.",
    )
    require(
        autonomy["flat_model_command_loop"] == "FORBIDDEN",
        "Flat model command loop unexpectedly enabled.",
    )
    require(
        autonomy["target_workspace_object_id"] == "ws.file.context-composer"
        and autonomy["target_source_path"]
        == "qml/components/ContextComposer.qml",
        "Autonomy v1 target expanded.",
    )
    require(
        autonomy["allowed_green_tools"]
        == ["READ", "SEARCH", "GIT", "TEST", "RUN"],
        "Autonomy GREEN tool scope mismatch.",
    )
    require(
        autonomy["model_output_authority"] == "UNTRUSTED_MODEL_OUTPUT",
        "Model output authority changed.",
    )
    for key in (
        "network_authority",
        "general_action_authority",
        "git_mutation_authority",
        "shell_authority",
    ):
        require(
            autonomy[key] == "NONE",
            "Autonomy authority expansion: " + key,
        )
    require(
        autonomy["host_write_authority"]
        == "NONE_BEFORE_SEPARATE_APPROVAL",
        "Autonomy host-write boundary changed.",
    )
    require(
        autonomy["self_authorization"] == "FORBIDDEN"
        and autonomy["authority_file_mutation"] == "FORBIDDEN",
        "Autonomy self-authority boundary changed.",
    )
    require(
        autonomy["replay_protection"] == "RUNTIME_SINGLE_USE_RECEIPT"
        and autonomy["monotonic_step_sequence"] is True
        and autonomy["session_bound"] is True,
        "Autonomy task grant replay/session binding missing.",
    )
    require(
        autonomy["persistent_apply_boundary"]
        == "EXISTING_LIMITED_WRITE_PROPOSAL_APPROVAL",
        "Autonomy persistent apply boundary mismatch.",
    )

    require(
        cfg["safety"]["general_action_authority"] == "NONE",
        "General action authority changed.",
    )
    require(
        cfg["safety"]["network_authority"] == "NONE",
        "Network authority changed.",
    )
    require(
        cfg["safety"]["task_scoped_network_authority"] == "TASK_SCOPED"
        and cfg["safety"]["task_scoped_general_action_authority"]
        == "TASK_SCOPED"
        and cfg["safety"]["task_scoped_scope_authority"]
        == "ALL_TASK_SCOPED_EFFECTS"
        and cfg["safety"]["task_scoped_requires"]
        == "MANDATE_VALID_HASH_BOUND_SINGLE_USE",
        "Task-scoped effect authority contract missing.",
    )
    workspace = cfg["workspace"]
    require(
        workspace["current_context_mode"]
        == "ALLOWLISTED_LOCAL_FILE_READ_AT_SUBMIT",
        "Current Workspace context mode mismatch.",
    )
    require(
        workspace["current_context_max_bytes"] == 16384,
        "Current Workspace context byte limit mismatch.",
    )
    require(
        workspace["current_context_default_object_id"]
        == "ws.file.context-composer",
        "Current Workspace object id mismatch.",
    )
    require(
        workspace["current_context_default_source_path"]
        == "qml/components/ContextComposer.qml",
        "Current Workspace source path mismatch.",
    )
    require(
        workspace["current_context_provenance"] == "REAL_LOCAL_FILE",
        "Current Workspace provenance mismatch.",
    )
    require(
        workspace["synthetic_fixture_context_policy"] == "BLOCK",
        "Synthetic fixture context policy mismatch.",
    )
    require(
        workspace["current_write_mode"]
        == "EXACT_PATCH_PROPOSE_PREVIEW_APPROVE_APPLY_ROLLBACK",
        "Current Workspace write mode mismatch.",
    )
    require(
        workspace["current_write_target_object_id"]
        == "ws.file.context-composer",
        "Current Workspace write object mismatch.",
    )
    require(
        workspace["current_write_target_source_path"]
        == "qml/components/ContextComposer.qml",
        "Current Workspace write source mismatch.",
    )
    require(
        "REAL_LOCAL_FILE" in cfg["ui_provenance"]["classes"],
        "REAL_LOCAL_FILE provenance class missing.",
    )

    launcher = (PROJECT / "main.py").read_text(encoding="utf-8")
    roots = import_roots(launcher)
    require(
        roots <= {
                     'PySide6',
                     '__future__',
                     'ast',
                     'backend',
                     'collections',
                     'copy',
                     'difflib',
                     'hashlib',
                     'io',
                     'json',
                     'os',
                     'pathlib',
                     're',
                     'shutil',
                     'stat',
                     'startup',
                     'subprocess',
                     'sys',
                     'tarfile',
                     'time',
                     'uuid',
                 },
        "Unexpected launcher import roots: " + repr(sorted(roots)),
    )
    require("class ChatBridge(QObject)" in launcher, "ChatBridge missing.")
    require("QProcess" in launcher, "QProcess bridge missing.")
    require(
        "bridge_signal.connect(bridge.submit)" in launcher,
        "QML bridge signal is not connected.",
    )
    for marker in (
        "CONTROL_APPLY_RUNNER_PATH",
        "control_contract.parse_control_command(value)",
        "def _submit_control(",
        "def _stop_active(",
        "def _control_apply_finished(",
        "QTimer.singleShot(3000",
        "stop_signal.connect(bridge.stopActive)",
    ):
        require(
            marker in launcher,
            "Control Plane launcher seam missing: " + marker,
        )
    for marker in (
        "WORKSPACE_CONTEXT_MAX_BYTES = 16384",
        "GROK_WORKSPACE_ALLOWLIST as WORKSPACE_CONTEXTS",
        "def resolve_workspace_context(",
        "def build_effective_prompt(",
        "secure_open(",
        "NOFOLLOW",
        "compile_chat_prompt(",
        "Selected Workspace object has no real local context source.",
    ):
        require(
            marker in launcher,
            "Real @current launcher seam missing: " + marker,
        )
    grok_contract = (
        PROJECT / "backend" / "grok_worker_contract.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '"ws.file.context-composer"',
        '"qml/components/ContextComposer.qml"',
        '"provenance": "REAL_LOCAL_FILE"',
    ):
        require(
            marker in grok_contract,
            "Shared workspace allowlist seam missing: " + marker,
        )

    context_compiler = (
        PROJECT / "backend" / "chat_context_compiler.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "Workspace content sha256:",
        "DEMAND_DRIVEN_PRIMARY_CURRENT",
        "----- BEGIN SELECTED WORKSPACE CONTEXT -----",
        "----- END SELECTED WORKSPACE CONTEXT -----",
        "LASER_IDENTITY",
        "----- USER -----",
    ):
        require(
            marker in context_compiler,
            "Demand-driven context compiler marker missing: " + marker,
        )

    for marker in (
        "SAFE_TOOL_RUNNER_PATH",
        "def parse_safe_tool_command(",
        "parse_natural_safe_tool_command(",
        "def _submit_tool(",
        "def _tool_finished(",
        "tool_contract.validate_request(",
        "tool_contract.validate_response(",
        "tool_contract.AUTHORITY",
        '"ENABLED_FIXED_GREEN_SAFE_TOOLS"',
    ):
        require(
            marker in launcher,
            "Safe Tools launcher seam missing: " + marker,
        )

    for marker in (
        "WRITE_RUNNER_PATH",
        "def parse_write_command(",
        "def _submit_write(",
        "def _write_finished(",
        "write_contract.validate_request(",
        "write_contract.validate_response(",
        "write_contract.AUTHORITY",
        '"ENABLED_EXPLICIT_CURRENT_QML_PATCH_V1"',
        '"ENABLED_LIMITED_WRITE_QML_PREAPPLY"',
    ):
        require(
            marker in launcher,
            "Limited Write launcher seam missing: " + marker,
        )

    for marker in (
        "AUTONOMY_CONTROLLER_PATH",
        "def parse_autonomy_command(",
        "def _submit_autonomy(",
        "def _autonomy_finished(",
        "def _resume_autonomy_verify(",
        "def _autonomy_verify_finished(",
        "autonomy_contract.validate_grant(",
        "autonomy_contract.validate_result(",
        "autonomy_contract.AUTHORITY",
        '"ENABLED_TASK_BOUND_CANDIDATE_V1"',
    ):
        require(
            marker in launcher,
            "Autonomy launcher seam missing: " + marker,
        )

    for rel in (
        "backend/autonomy_contract.py",
        "backend/autonomy_cognitive_adapter.py",
        "backend/autonomy_model_runner.py",
        "backend/autonomy_candidate_runner.py",
        "backend/autonomy_controller.py",
    ):
        require((PROJECT / rel).is_file(), "Autonomy source missing: " + rel)

    autonomy_controller_source = (
        PROJECT / "backend/autonomy_controller.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "GG_AUTONOMY_EVENT=",
        "GATHER_INFORMATION",
        "PLAN_ACTION",
        "make_and_revalidate_state",
        "RUNTIME_SINGLE_USE_RECEIPT",
        "WAITING_HOST_APPLY",
        "--verify-host",
    ):
        require(
            marker in autonomy_controller_source,
            "Autonomy controller invariant missing: " + marker,
        )
    require(
        "while not done" not in autonomy_controller_source
        and "model.next_command" not in autonomy_controller_source,
        "Forbidden flat model command loop marker found.",
    )


    autonomy_model_source = (
        PROJECT / "backend/autonomy_model_runner.py"
    ).read_text(encoding="utf-8")

    require(
        "segment ::= char{1,180}"
        in autonomy_model_source,
        "Legacy autonomy grammar changed.",
    )

    for marker in (
        "SELFDEV_GBNF = (",
        "def parse_selfdev_semantic_text(",
        "def execute_selfdev_semantic_transport(",
        "def run_selfdev_semantic_prompt(",
        "HYPOTHESIS_JSON=",
        "OLD_JSON=",
        "NEW_JSON=",
        "WHY_JSON=",
    ):
        require(
            marker in autonomy_model_source,
            "Selfdev semantic profile missing: "
            + marker,
        )

    require(
        "<<GG_SELFDEV_OLD>>"
        not in autonomy_model_source,
        "Ambiguous selfdev sentinel framing survived.",
    )

    for marker in (
        "SELFDEV_MAX_PROMPT_CHARS = 32000",
        "def _selfdev_should_retry(",
        "run_selfdev_semantic_prompt(",
        '"DONE_WITHOUT_CHANGE"',
        '"FOUNDATION_GATE_NOT_PASS:"',
        '"REGRESSION_FAILED:"',
    ):
        require(
            marker in launcher,
            "Selfdev hardening seam missing: "
            + marker,
        )

    selfdev_test = (
        PROJECT / "tests/test_selfdev_controller.py"
    )

    require(
        selfdev_test.is_file(),
        "Selfdev controller regression missing.",
    )

    selfdev_test_source = selfdev_test.read_text(
        encoding="utf-8"
    )

    for marker in (
        "SELFDEV_FAILURE_MATRIX=PASS",
        "SELFDEV_SEMANTIC_MULTILINE=PASS",
        "SELFDEV_FRAMING_ADVERSARIAL=PASS",
        "SELFDEV_VERIFIED_CHANGESET_SUCCESS_PATH=PASS",
    ):
        require(
            marker in selfdev_test_source,
            "Selfdev regression contract missing: "
            + marker,
        )

    write_contract_source = (
        PROJECT / "backend/write_contract.py"
    ).read_text(encoding="utf-8")
    require(
        'AUTHORITY = "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1"'
        in write_contract_source,
        "Limited Write contract authority missing.",
    )
    require(
        'TARGET_RELATIVE_PATH = "qml/components/ContextComposer.qml"'
        in write_contract_source,
        "Limited Write exact target missing.",
    )

    write_runner = (
        PROJECT / "backend/write_runner.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "secure_open(",
        "NOFOLLOW",
        "os.O_EXCL",
        "os.replace",
        "shell=False",
        '"--network=none"',
        '"--read-only"',
        "PROPOSAL_STALE_BEFORE_APPLY",
        "ROLLBACK_TARGET_NOT_EXACT_CANDIDATE",
    ):
        require(
            marker in write_runner,
            "Limited Write runner boundary missing: " + marker,
        )

    safe_contract = (
        PROJECT / "backend/safe_tool_contract.py"
    ).read_text(encoding="utf-8")
    require(
        'AUTHORITY = "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1"'
        in safe_contract,
        "Safe Tools contract authority missing.",
    )
    require(
        'PROFILE_READ = "READ"' in safe_contract
        and 'PROFILE_SEARCH = "SEARCH"' in safe_contract
        and 'PROFILE_GIT = "GIT"' in safe_contract
        and 'PROFILE_TEST = "TEST"' in safe_contract
        and 'PROFILE_RUN = "RUN"' in safe_contract,
        "Safe Tools profile contract missing.",
    )

    safe_runner = (
        PROJECT / "backend/safe_tool_runner.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "shell=False",
        "secure_open(",
        "NOFOLLOW",
        "GIT_OPTIONAL_LOCKS",
        '"--network=none"',
        '"--read-only"',
        '"--cap-drop=all"',
        '"--security-opt=no-new-privileges"',
        "PODMAN_LOCKED_READONLY_SANDBOX",
    ):
        require(
            marker in safe_runner,
            "Safe Tools runner boundary missing: " + marker,
        )

    adapter = (
        PROJECT / "backend/local_ai_chat_runner.py"
    ).read_text(encoding="utf-8")
    adapter_roots = import_roots(adapter)
    require(
        adapter_roots <= {
            "__future__",
            "backend",
            "json",
            "os",
            "stat",
            "sys",
            "pathlib",
            "local_ai_model_runner",
        },
        "Unexpected adapter import roots: " + repr(sorted(adapter_roots)),
    )
    require("base.execute_synthetic(" in adapter, "Frozen runner reuse missing.")
    require("base.PROMPT =" in adapter, "Prompt binding missing.")
    require(
        "CHAT_MODEL_GBNF" in adapter,
        "Deterministic chat grammar missing.",
    )
    require(
        '"GG_MODEL_RUNNER_OK"' in adapter,
        "Forced response marker missing.",
    )
    require(
        "base.MODEL_GBNF = CHAT_MODEL_GBNF" in adapter,
        "Chat grammar binding missing.",
    )
    require(
        "base.MODEL_GBNF = old_grammar" in adapter,
        "Chat grammar restoration missing.",
    )
    require("--execute-chat" in adapter, "Chat CLI missing.")

    control_contract_source = (
        PROJECT / "backend" / "control_plane_contract.py"
    ).read_text(encoding="utf-8")
    control_runner_source = (
        PROJECT / "backend" / "control_plane_runner.py"
    ).read_text(encoding="utf-8")
    for marker in (
        'CONTROL_AUTHORITY = "CONTROL_ONLY_NO_NEW_EXECUTION_AUTHORITY_V1"',
        'BOOTSTRAP_APPLY_AUTHORITY = "YELLOW_EXACT_VERIFIED_MAIN_PY_APPLY_V1"',
        'TARGET_RELATIVE_PATH = desktop_relative_path("main.py")',
        "class TaskLedger:",
        "def parse_control_command(",
        "def validate_apply_request(",
    ):
        require(
            marker in control_contract_source,
            "Control Plane contract marker missing: " + marker,
        )
    for marker in (
        "HOST_REPO_NOT_CLEAN",
        "BASE_HEAD_DRIFT",
        "CANDIDATE_SHA_DRIFT",
        "VERIFIED_DIFF_SHA_DRIFT",
        "_run_regression(candidate_project)",
        "os.replace(temporary, TARGET)",
        "ROLLBACK_POSTHASH_FAILED",
    ):
        require(
            marker in control_runner_source,
            "Control Plane runner marker missing: " + marker,
        )
    require(
        "shell=True" not in control_runner_source,
        "Control Plane runner gained shell execution.",
    )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(
        manifest["schema"] == "gg.ai-desktop.source-manifest.v1.2",
        "Manifest schema mismatch.",
    )
    require(manifest["version"] == "1.2", "Manifest version mismatch.")
    require(
        manifest["phase"] == "CONTROL_BOOTSTRAP_V1_CANDIDATE",
        "Manifest phase mismatch.",
    )
    require(
        manifest["plan_id"] == "GG-CONTROL-BOOTSTRAP-v1.0"
        and manifest["base_head"]
        == "70b11ca74aebd33a07657110da623af461f8f668",
        "Manifest Control Plane provenance lock mismatch.",
    )
    require(
        manifest["model_runner"]["status"]
        == "PUBLISHED_CONNECTED_VIA_LOCAL_CHAT_BRIDGE",
        "Runner publication state mismatch.",
    )
    require(
        manifest["authority"]["general_action_authority"] == "NONE",
        "Manifest action authority changed.",
    )
    require(
        manifest["authority"]["network_authority"] == "NONE",
        "Manifest network authority changed.",
    )
    require(
        manifest["authority"]["real_command_execution"]
        == "ENABLED_FIXED_GREEN_SAFE_TOOLS",
        "Manifest Safe Tools execution state mismatch.",
    )
    manifest_control = manifest["control_plane"]
    require(
        manifest_control["commands"] == control_plane["commands"],
        "Manifest Control Plane command registry mismatch.",
    )
    require(
        manifest_control["status"] == "IMPLEMENTED_PENDING_HUMAN_E2E"
        and manifest_control["authority"]
        == "CONTROL_ONLY_NO_NEW_EXECUTION_AUTHORITY_V1",
        "Manifest Control Plane status/authority mismatch.",
    )
    require(
        manifest_control["stop_priority"] == "PARSED_BEFORE_BUSY_GATE"
        and manifest_control["stop_escalation"] == "TERM_THEN_KILL_3000MS"
        and manifest_control["stop_idempotent"] is True,
        "Manifest Control Plane stop contract mismatch.",
    )
    require(
        manifest_control["apply_binding"]
        == "TASK_ID_PLUS_CANDIDATE_SHA256_PLUS_BASE_HEAD"
        and manifest_control["bootstrap_target"]
        == "projects/gg-ai-desktop/main.py",
        "Manifest Control Plane apply binding mismatch.",
    )
    require(
        manifest_control["bootstrap_model_semantic_grammar"]
        == "FINITE_FIELD_BOUNDS_V1",
        "Manifest bounded bootstrap grammar mismatch.",
    )
    for key in (
        "network_authority",
        "general_action_authority",
        "shell_authority",
        "arbitrary_exec_authority",
        "arbitrary_path_authority",
        "git_commit_authority",
    ):
        require(
            manifest_control[key] == "NONE",
            "Manifest Control Plane authority expansion: " + key,
        )
    manifest_write = manifest["limited_write_authority"]
    require(
        manifest_write["status"] == "VERIFIED_LIVE",
        "Manifest Limited Write status mismatch.",
    )
    require(
        manifest_write["human_e2e_status"] == "VERIFIED_LIVE",
        "Manifest Limited Write human E2E status mismatch.",
    )
    require(
        manifest_write["verified_live_commit"]
        == "dca1b99f5b288871538a707030ed306aa2167863",
        "Manifest Limited Write verified commit mismatch.",
    )
    require(
        manifest_write["authority"]
        == "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        "Manifest Limited Write authority mismatch.",
    )
    require(
        manifest_write["target_source_path"]
        == "qml/components/ContextComposer.qml",
        "Manifest Limited Write source target mismatch.",
    )
    require(
        manifest_write["network_authority"] == "NONE",
        "Manifest Limited Write network authority mismatch.",
    )
    require(
        manifest_write["general_action_authority"] == "NONE",
        "Manifest Limited Write general authority mismatch.",
    )
    require(
        manifest_write["model_autonomous_write_invocation"]
        == "DISABLED_V1",
        "Manifest autonomous write authority changed.",
    )

    chat_selection = manifest["chat_text_selection"]
    require(
        manifest["architecture"]["chat_text_selection"]
        == "READ_ONLY_SELECTABLE_COPYABLE",
        "Manifest chat text selection architecture mismatch.",
    )
    require(
        chat_selection["status"] == "VERIFIED_LIVE",
        "Manifest chat text selection status mismatch.",
    )
    require(
        chat_selection["human_e2e_status"] == "VERIFIED_LIVE",
        "Manifest chat text selection human E2E status mismatch.",
    )
    require(
        chat_selection["verified_live_commit"]
        == "c67d7b3a3299466125263bbba359aac64b7b24f5",
        "Manifest chat text selection verified commit mismatch.",
    )
    require(
        chat_selection["body_renderer"] == "READ_ONLY_TEXTEDIT",
        "Manifest chat text body renderer mismatch.",
    )
    require(
        chat_selection["editable"] is False,
        "Manifest chat body became editable.",
    )
    require(
        chat_selection["mouse_selection"] is True
        and chat_selection["keyboard_selection"] is True
        and chat_selection["persistent_selection"] is True,
        "Manifest chat selection controls mismatch.",
    )
    require(
        chat_selection["text_format"] == "PLAIN_TEXT",
        "Manifest chat text format mismatch.",
    )
    require(
        chat_selection["qml_gate"]
        == "REQUIRED_PREWRITE_AND_POSTWRITE",
        "Manifest chat selection QML Gate requirement mismatch.",
    )

    manifest_autonomy = manifest["autonomy_bootstrap"]
    require(
        manifest_autonomy["status"] == "IMPLEMENTED_PENDING_HUMAN_E2E",
        "Manifest autonomy status mismatch.",
    )
    require(
        manifest_autonomy["authority"]
        == "YELLOW_LOCAL_TASK_BOUND_CANDIDATE_V1",
        "Manifest autonomy authority mismatch.",
    )
    require(
        manifest_autonomy["must_reuse_existing_cognitive_hierarchy"] is True,
        "Manifest cognitive reuse invariant missing.",
    )
    require(
        manifest_autonomy["parallel_agent_brain"] == "FORBIDDEN"
        and manifest_autonomy["flat_model_command_loop"] == "FORBIDDEN",
        "Manifest autonomy brain boundary mismatch.",
    )
    require(
        manifest_autonomy["model_output_authority"]
        == "UNTRUSTED_MODEL_OUTPUT",
        "Manifest model output authority mismatch.",
    )
    require(
        manifest_autonomy["host_write_authority"]
        == "NONE_BEFORE_SEPARATE_APPROVAL",
        "Manifest autonomy host-write authority mismatch.",
    )
    require(
        manifest_autonomy["persistent_apply_boundary"]
        == "EXISTING_LIMITED_WRITE_PROPOSAL_APPROVAL",
        "Manifest autonomy apply boundary mismatch.",
    )
    require(
        manifest_autonomy["network_authority"] == "NONE"
        and manifest_autonomy["general_action_authority"] == "NONE",
        "Manifest autonomy authority expanded.",
    )
    require(
        manifest_autonomy["system_alive_local"] == "NOT_YET",
        "SYSTEM_ALIVE_LOCAL prematurely promoted.",
    )

    manifest_tools = manifest["safe_tools"]
    require(
        manifest_tools["status"] == "IMPLEMENTED",
        "Manifest Safe Tools status mismatch.",
    )
    require(
        manifest_tools["authority"] == "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
        "Manifest Safe Tools authority mismatch.",
    )
    require(
        manifest_tools["profiles"]
        == ["READ", "SEARCH", "GIT", "TEST", "RUN"],
        "Manifest Safe Tools profile set mismatch.",
    )
    require(
        manifest_tools["network_authority"] == "NONE",
        "Manifest Safe Tools network authority mismatch.",
    )
    require(
        manifest_tools["persistent_write_authority"] == "NONE",
        "Manifest Safe Tools write authority mismatch.",
    )
    workspace_context = manifest["workspace_context"]
    require(
        workspace_context["status"] == "IMPLEMENTED_REAL_CURRENT_READ_ONLY",
        "Manifest Workspace context status mismatch.",
    )
    require(
        workspace_context["object_id"] == "ws.file.context-composer",
        "Manifest Workspace object id mismatch.",
    )
    require(
        workspace_context["source_path"]
        == "qml/components/ContextComposer.qml",
        "Manifest Workspace source path mismatch.",
    )
    require(
        workspace_context["provenance"] == "REAL_LOCAL_FILE",
        "Manifest Workspace provenance mismatch.",
    )
    require(
        workspace_context["resolution"]
        == "ALLOWLISTED_LOCAL_FILE_READ_AT_SUBMIT",
        "Manifest Workspace resolution mismatch.",
    )
    require(
        workspace_context["max_bytes"] == 16384,
        "Manifest Workspace byte limit mismatch.",
    )
    require(
        workspace_context["synthetic_fixture_context_policy"] == "BLOCK",
        "Manifest synthetic context policy mismatch.",
    )

    catalog = json.loads((PROJECT / "FILE-CATALOG.json").read_text())
    expected_hashed = {
        row["path"] for row in catalog["files"]
        if row["kind"] == "file" and row["path"] != "SOURCE-MANIFEST.json"
    }
    require(
        {"AGENTS.md", "main.py", "startup.py", "backend/application_paths.py",
         "skills/gg-live-eyes/SKILL.md", "skills/gg-blender-reference-workflow/SKILL.md",
         "config/dependencies.json"}.issubset(expected_hashed),
        "Essential application sources missing from distribution.",
    )
    require(
        set(manifest["files"]) == expected_hashed,
        "Manifest file set mismatch.",
    )
    for rel, expected in manifest["files"].items():
        require(
            sha256(PROJECT / rel) == expected,
            "Manifest hash mismatch: " + rel,
        )

    for rel, expected in FROZEN.items():
        require(
            manifest["frozen_files"][rel] == expected,
            "Frozen manifest hash mismatch: " + rel,
        )

    print("SOURCE_CONTRACT_TEST=PASS")
    print("FROZEN_MODEL_RUNNER=BYTE_IDENTICAL")
    print("LOCAL_CHAT_ADAPTER=CONNECTED")
    print("REAL_CURRENT_WORKSPACE_CONTEXT=ENABLED_READ_ONLY")
    print("LIMITED_WRITE_AUTHORITY=YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1")
    print("LIMITED_WRITE_STATUS=VERIFIED_LIVE")
    print("LIMITED_WRITE_TARGET=ws.file.context-composer")
    print("CHAT_TEXT_SELECTION=READ_ONLY_SELECTABLE_COPYABLE")
    print("WORKSPACE_CONTEXT_PROVENANCE=REAL_LOCAL_FILE")
    print("MODEL_INTEGRATION=ENABLED_LOCAL_CHAT")
    print("SAFE_TOOLS=READ_SEARCH_GIT_TEST_RUN")
    print("SAFE_TOOL_AUTHORITY=GREEN_LOCAL_TYPED_SAFE_TOOLS_V1")
    print("MODEL_AUTONOMOUS_TOOL_INVOCATION=ENABLED_RESIDENT_READ_SEARCH_TEST_RUN_LOOP_V1")
    print("AUTONOMY_CORE=TASK_BOUND_CANDIDATE_V1")
    print("AUTONOMY_STATUS=IMPLEMENTED_PENDING_HUMAN_E2E")
    print("CONTROL_PLANE=IMPLEMENTED_PENDING_HUMAN_E2E")
    print("CONTROL_STOP=PARSED_BEFORE_BUSY_GATE")
    print("BOOTSTRAP_APPLY=TASK_SHA_HEAD_BOUND")
    print("PARALLEL_AGENT_BRAIN=FORBIDDEN")
    print("FLAT_MODEL_COMMAND_LOOP=FORBIDDEN")
    print("MODEL_OUTPUT_AUTHORITY=UNTRUSTED_MODEL_OUTPUT")
    print("PERSISTENT_HOST_APPLY=SEPARATE_EXISTING_LIMITED_WRITE_BOUNDARY")
    print("SYSTEM_ALIVE_LOCAL=NOT_YET")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
