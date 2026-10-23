from __future__ import annotations

import hashlib
from pathlib import Path

from backend import action_effect_observer


PROJECT = Path(__file__).resolve().parents[1]
MAIN = PROJECT / "main.py"
ADAPTER = (
    PROJECT
    / "backend"
    / "action_execution_safe_tool_adapter.py"
)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def fixture() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    body = "Item {\n    id: root\n}\n"
    data = body.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()

    object_id = "workspace-context-composer"
    source_path = "qml/components/ContextComposer.qml"
    request_path = (
        "projects/gg-ai-desktop/"
        + source_path
    )

    intent: dict[str, object] = {
        "effect_class": "READ_ONLY_TOOL_EXECUTION",
        "persistent_write": "RUNTIME_ONLY",
        "network": "NONE",
        "sudo": "NO",
        "target_object_id": object_id,
        "target_source_revision": digest,
    }

    eligibility: dict[str, object] = {
        "safe_tool_request": {
            "schema": "gg.safe-tool-request.v1",
            "request_id": "tool-fixture",
            "profile": "READ",
            "arguments": {
                "path": request_path,
            },
        },
    }

    workspace: dict[str, object] = {
        "object_id": object_id,
        "source_path": source_path,
        "sha256": digest,
        "bytes": len(data),
        "body": body,
    }

    output = (
        "PROFILE=READ\n"
        f"PATH={request_path}\n"
        f"BYTES={len(data)}\n"
        f"SHA256={digest}\n"
        "----- BEGIN FILE -----\n"
        + body
        + "----- END FILE -----"
    )

    response: dict[str, object] = {
        "status": "PASS",
        "output": output,
        "evidence": {
            "effect_class": "READ_ONLY",
            "persistent_write_authority": "NONE",
            "network_authority": "NONE",
            "backend": "IN_PROCESS_TRACKED_READ",
            "output_sha256": hashlib.sha256(
                output.encode("utf-8")
            ).hexdigest(),
        },
    }

    return (
        intent,
        eligibility,
        response,
        workspace,
    )


def observe(
    intent: dict[str, object],
    eligibility: dict[str, object],
    response: dict[str, object],
    workspace: dict[str, object],
) -> dict[str, object]:
    return action_effect_observer.observe_safe_tool_read_effect(
        action_intent=intent,
        execution_eligibility=eligibility,
        validated_response=response,
        workspace_object_id=str(
            workspace["object_id"]
        ),
        resolve_workspace_context_fn=(
            lambda _object_id: dict(workspace)
        ),
    )


def unit_contract() -> None:
    (
        intent,
        eligibility,
        response,
        workspace,
    ) = fixture()

    matched = observe(
        dict(intent),
        dict(eligibility),
        dict(response),
        dict(workspace),
    )

    expect(
        matched["schema"]
        == "gg.action-effect-observation.v1",
        "D69 schema mismatch",
    )
    expect(
        matched["result"] == "MATCH",
        "D69 exact READ should match",
    )
    expect(
        matched["reason_code"]
        == "EXPECTED_ACTUAL_MATCH",
        "D69 match reason mismatch",
    )
    expect(
        matched["actual_effect_verified"] is True,
        "D69 match must verify effect",
    )
    expect(
        matched["d70_required"] is False,
        "D69 match must not require D70",
    )
    expect(
        matched["mismatch_reasons"] == [],
        "D69 match must have no mismatch reasons",
    )

    changed_workspace = dict(workspace)
    changed_workspace["sha256"] = "a" * 64

    revision_mismatch = observe(
        dict(intent),
        dict(eligibility),
        dict(response),
        changed_workspace,
    )

    expect(
        revision_mismatch["result"] == "MISMATCH",
        "D69 revision drift must mismatch",
    )
    expect(
        revision_mismatch["reason_code"]
        == "TARGET_SOURCE_REVISION_MISMATCH",
        "D69 revision reason mismatch",
    )
    expect(
        revision_mismatch["actual_effect_verified"] is False,
        "D69 mismatch cannot verify effect",
    )
    expect(
        revision_mismatch["d70_required"] is True,
        "D69 mismatch must require D70",
    )

    effect_response = dict(response)
    effect_evidence = dict(
        response["evidence"]
    )
    effect_evidence["effect_class"] = "WRITE"
    effect_response["evidence"] = effect_evidence

    effect_mismatch = observe(
        dict(intent),
        dict(eligibility),
        effect_response,
        dict(workspace),
    )

    expect(
        effect_mismatch["reason_code"]
        == "EFFECT_CLASS_MISMATCH",
        "D69 effect-class reason mismatch",
    )
    expect(
        effect_mismatch["d70_required"] is True,
        "D69 effect mismatch must route to D70",
    )

    output_response = dict(response)
    output_response["output"] = (
        str(response["output"])
        + "\nDRIFT"
    )

    output_mismatch = observe(
        dict(intent),
        dict(eligibility),
        output_response,
        dict(workspace),
    )

    expect(
        output_mismatch["reason_code"]
        == "OUTPUT_PROVENANCE_MISMATCH",
        "D69 output provenance reason mismatch",
    )

    print("D69_MATCH_CLASSIFICATION=PASS")
    print("D69_MISMATCH_CLASSIFICATION=PASS")
    print("D69_D70_ROUTING_FLAG_ONLY=PASS")


def static_contract() -> None:
    observer_source = (
        PROJECT
        / "backend"
        / "action_effect_observer.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )
    adapter_source = ADAPTER.read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_source = MAIN.read_text(
        encoding="utf-8",
        errors="strict",
    )

    for forbidden in (
        "subprocess",
        "write_runner",
        "repair_to_intended",
        "accept_repair_candidate",
        "accept_repair_response",
        "AUTONOMY_CONTROLLER",
    ):
        expect(
            forbidden not in observer_source,
            "D69 observer gained forbidden effect: "
            + forbidden,
        )

    for required in (
        "observe_safe_tool_read_effect",
        "actual_effect_verified",
        "d70_required",
        "TARGET_SOURCE_REVISION_MISMATCH",
        "OUTPUT_PROVENANCE_MISMATCH",
        "IN_PROCESS_TRACKED_READ",
    ):
        expect(
            required in observer_source,
            "D69 observer marker missing: "
            + required,
        )

    for required in (
        "action_effect_observer."
        "observe_safe_tool_read_effect",
        'pending["actual_effect_observation"]',
        'observation["actual_effect_verified"]',
        "resolve_workspace_context_fn",
        "D69 LOCAL OBSERVER: APPLIED",
    ):
        expect(
            required in adapter_source,
            "D69 adapter wiring missing: "
            + required,
        )

    for required in (
        "resolve_workspace_context_fn="
        "resolve_workspace_context",
        '"ACTION_EFFECT_OBSERVER"',
        '"backend.action_effect_observer"',
        '"action_effect_observer.'
        'observe_safe_tool_read_effect"',
    ):
        expect(
            required in main_source,
            "D69 main/graph wiring missing: "
            + required,
        )

    expect(
        '"REPLAN"' not in observer_source,
        "D69 observer must not execute D70",
    )

    print("D69_COMPLETION_WIRING=PASS")
    print("D69_MACHINE_GRAPH_WIRING=PASS")
    print("D70_EXECUTION_FROM_D69=NONE")


def main() -> int:
    unit_contract()
    static_contract()
    print("D69_ACTION_EFFECT_OBSERVER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
