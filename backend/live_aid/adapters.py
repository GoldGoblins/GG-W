from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import secrets
from typing import Any

from .forensic_resolver import ProbeRequest

BASE_HEAD = "e467c56bc32155045e03e8b422c60baea25019eb"

@dataclass(frozen=True)
class ExistingComponent:
    path: str
    sha256: str
    role: str

# Content locks are generated from the uploaded current BASE_HEAD snapshot.
REQUIRED_COMPONENTS: tuple[ExistingComponent, ...] = (
    ExistingComponent('projects/gg-ai-desktop/backend/local_ai_chat_runner.py', 'e328ffd3d27638f4c2afa83d82f41f53af2448571abe7e575689f1e215968afb', 'REAL_CHAT_MODEL_TRANSPORT'),
    ExistingComponent('projects/gg-ai-desktop/backend/local_ai_model_runner.py', '1d32863be1886e737969b765b1d87744654253abc6b3074fc1dc93087e86d232', 'LOCAL_MODEL_RUNTIME'),
    ExistingComponent('projects/gg-ai-desktop/backend/local_ai_contract.py', '740849d413a3461d40ee83cba71c46f81ec2447ea351942e47868f3478a012d1', 'LOCAL_MODEL_DATA_CONTRACT'),
    ExistingComponent('projects/gg-ai-desktop/backend/safe_tool_contract.py', 'f3abc77f9a4e5fc2de187c38391f6980c5129ad3751fd2a0656e2d1a6755d0ba', 'GREEN_TOOL_CONTRACT'),
    ExistingComponent('projects/gg-ai-desktop/backend/safe_tool_runner.py', 'f6e01147ee51db19481ae907b4fc9b4bcbd145af979ef08df4c553bbe125401f', 'GREEN_TOOL_EXECUTOR'),
    ExistingComponent('projects/gg-ai-desktop/backend/write_contract.py', '2f8e0ba257a3f74fda09e29ecfb6fabc9e63681242298113cec8eee6f73e2f91', 'LIMITED_WRITE_CONTRACT'),
    ExistingComponent('projects/gg-ai-desktop/backend/write_runner.py', '54be63540f3868f214c717d6e65da6a97ca5abbd3b545ec0f06b30b8e301a8be', 'LIMITED_WRITE_EXECUTOR'),
    ExistingComponent('projects/gg-ai-desktop/backend/control_plane_contract.py', '1c38c925606799322c69b9cd87d032d1dd595ecca5cd5ee8be5c7071ea97205f', 'CONTROL_PLANE_CONTRACT'),
    ExistingComponent('projects/gg-ai-desktop/backend/control_plane_runner.py', 'f4716f7b34661f796591a19a37b297723d5bc8ba2660b91b67a8ca96144a7449', 'VERIFIED_TASK_APPLY_RUNNER'),
    ExistingComponent('projects/gg-ai-desktop/backend/autonomy_contract.py', '9b6f06b1af8515bd3502cb9acf3e9784542e354eda3ca40885b903b35b1ff8b5', 'AUTONOMY_CONTRACT'),
    ExistingComponent('projects/gg-ai-desktop/backend/autonomy_controller.py', 'f93a1d5c0be5a8edca2d232628568aa0dd512d49cec5816fe8c60dffee58fd17', 'TASK_BOUND_AUTONOMY_CONTROLLER'),
    ExistingComponent('projects/gg-ai-desktop/backend/autonomy_candidate_runner.py', '27351b5b2b9fb24b296309cc4924db4b74018655858e9ff3dfaaa2fac7841a57', 'CANDIDATE_WORKSPACE'),
    ExistingComponent('projects/gg-ai-desktop/backend/autonomy_cognitive_adapter.py', '789c0f01a249a17025257936befaf01f66bf6ca4cd3213cf69a9c96f2b9e29ac', 'COGNITIVE_STACK_ADAPTER'),
    ExistingComponent('projects/gg-ai-desktop/backend/autonomy_model_runner.py', 'de06d62ccb80c5be4599b9c6239b2b3bd361753eea81e357fa13ac0d85f720f2', 'MODEL_SEMANTIC_PROPOSER'),
    ExistingComponent('projects/gg-ai-desktop/backend/orchestrator_mandate_adapter.py', '3b27a46fda73776a031687843e6b367202700558c724db25995152dd318d31f6', 'MANDATE_REQUEST_ADAPTER'),
    ExistingComponent('projects/gg-ai-desktop/backend/orchestrator_mandate_evaluation_adapter.py', '9f056962b5b630a55347cc2de6ae3faa34cd5a38e56baf7c5ecf4688fd3151e1', 'MANDATE_EVALUATION_ADAPTER'),
    ExistingComponent('projects/gg-ai-desktop/main.py', '2f48ed1bc26350b0974b0b11b6db22eab5f5fe8434751536e9781ac596809610', 'WORKBENCH_BRIDGE'),
    ExistingComponent('projects/gg-ai-desktop/qml/Main.qml', '5095a15066c28a1c7ec3ee4c7645b069881db984420ec2e44ab710e01766032a', 'WORKBENCH_UI'),
    ExistingComponent('projects/gg-ai-desktop/qml/components/ChatNode.qml', '7a93cd927e07ae8ec666d7dafffe3cbe3b22e3c35279638a18cc3337b8f2bfc9', 'CHAT_WORK_OBJECT_HOST'),
    ExistingComponent('projects/gg-ai-desktop/qml/components/WorkObject.qml', 'c2ff24b0a60c7211f10328cbcf92f53a5d81758641684c5d0551cc36f2c84731', 'WORK_OBJECT_BASE'),
    ExistingComponent('infrastructure/code-gate/gg-code-gate.py', '784907682907c7bda20494a4b61ffe9bee3bf7c6d1e4870410202c7e5695d379', 'FOUNDATION_CODE_GATE_SOURCE'),
    ExistingComponent('infrastructure/code-gate-qml/gg-code-gate-qml.py', '7722beba215f07edffce69650fc02dd25fba5e25d1b92789e65b0b056a999330', 'QML_CODE_GATE_SOURCE'),
    ExistingComponent('infrastructure/debug-runner/gg_debug_runner.py', '85e1b5e94f759b63c5454c38266355c8ef6992ae26b2bdab152d993ea896d955', 'DEBUG_RUNNER'),
    ExistingComponent('infrastructure/local-tool-executor/gg_local_tool_executor.py', 'e1f52c523985c892ce44088346d7bb00a9a9d89e4b8e0daf3731851f23e9d464', 'CONTROLLED_LOCAL_TOOL_EXECUTOR'),
    ExistingComponent('cognitive-core/gg_cognitive_contract.py', 'e8824222fdb8f638f12c57f21a9b060f577e3a5ef5db8e034c9595677e03d79d', 'COGNITIVE_TASK_ENVELOPE'),
    ExistingComponent('cognitive-core/gg_epistemic_ledger.py', 'dd9b28b78bc6bff0770c544807dc56ab2791fee78eb5eb6aa14eb316a5a80be7', 'EPISTEMIC_LEDGER'),
    ExistingComponent('cognitive-core/gg_belief_view.py', 'c3d754e8af0f7a05ab90190603ee1fcf410ab7add9096e7ef2ccb7ea570182b9', 'BELIEF_VIEW'),
    ExistingComponent('cognitive-core/gg_goal_why.py', '05a83a935273b106ad811aac3bb31c80eaf2bd3b444d2be855486899ad591ae6', 'GOAL_WHY'),
    ExistingComponent('cognitive-core/gg_hypothesis_protocol.py', 'fa5abef6f8f87deeda8e9e083d067611b18b0038b07d040ef1363582658fdac3', 'HYPOTHESIS_PROTOCOL'),
    ExistingComponent('cognitive-core/gg_state_revalidation.py', '8a58a8b7077ac977c035225f182d46c7efb9c842f357b80be9618e6caa0ee548', 'STATE_REVALIDATION'),
    ExistingComponent('cognitive-core/gg_memory_discipline.py', 'ba9cf88bc2be1283b6aae02603868d0fb5b2f64308d1b2def9678ee0f03a824b', 'MEMORY_DISCIPLINE'),
    ExistingComponent('cognitive-core/gg_mandate_approval.py', '896b9f33da2ef8855d811da57aeb6db2bf6591bf3da3568ab1ddc5126aeac133', 'MANDATE_APPROVAL'),
)

def verify_components(repo_root: Path, components: tuple[ExistingComponent, ...] | None = None) -> list[str]:
    components = REQUIRED_COMPONENTS if components is None else components
    problems: list[str] = []
    for item in components:
        path = repo_root / item.path
        if path.is_symlink() or not path.is_file():
            problems.append("MISSING:" + item.path)
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item.sha256:
            problems.append("SHA_DRIFT:" + item.path)
    return problems

def safe_tool_request(probe: ProbeRequest, request_id: str | None = None) -> dict[str, Any]:
    if probe.profile not in {"READ", "SEARCH", "GIT", "TEST", "RUN"}:
        raise ValueError("PROBE_NOT_SAFE_TOOL_PROFILE")
    request_id = request_id or ("tool-" + secrets.token_hex(16))
    return {
        "schema": "gg.workbench.safe-tool-request.v1",
        "request_id": request_id,
        "profile": probe.profile,
        "arguments": probe.arguments,
    }

def validate_safe_tool_response(value: dict[str, Any], *, request_id: str, profile: str) -> None:
    required = {"schema", "request_id", "status", "profile", "output", "evidence"}
    if set(value) != required:
        raise ValueError("SAFE_TOOL_RESPONSE_FIELDS")
    if value["schema"] != "gg.workbench.safe-tool-response.v1":
        raise ValueError("SAFE_TOOL_RESPONSE_SCHEMA")
    if value["request_id"] != request_id or value["profile"] != profile:
        raise ValueError("SAFE_TOOL_RESPONSE_BINDING")
    evidence = value["evidence"]
    if evidence.get("authority") != "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1":
        raise ValueError("SAFE_TOOL_AUTHORITY")
    if evidence.get("effect_class") != "READ_ONLY":
        raise ValueError("SAFE_TOOL_EFFECT")
    if evidence.get("network_authority") != "NONE":
        raise ValueError("SAFE_TOOL_NETWORK")
    if evidence.get("persistent_write_authority") != "NONE":
        raise ValueError("SAFE_TOOL_WRITE")

def debug_runner_contract() -> dict[str, Any]:
    return {
        "runner_source": "infrastructure/debug-runner/gg_debug_runner.py",
        "report_schema": "gg.debug-runner-report.v1",
        "network": "none",
        "automatic_rerun": False,
        "expected_image_id": "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174",
        "consumes_after_authoring_preflight": True,
    }

def code_gate_contract() -> dict[str, Any]:
    return {
        "foundation_image_id": "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174",
        "qml_image_id": "851b076f4c9d16ecff0b802276858ff4756bd226387f09db7b5a9bb0222d9cef",
        "foundation_runner": "infrastructure/code-gate/gg-code-gate.py",
        "qml_runner": "infrastructure/code-gate-qml/gg-code-gate-qml.py",
        "gate_pass_is_profile_bound_only": True,
    }
