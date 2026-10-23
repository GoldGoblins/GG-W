from __future__ import annotations

import hashlib
import json
from typing import Any

from backend import autonomy_cognitive_adapter as cognitive
from backend import action_intent_contract
from backend import initiative_proposal
from backend import orchestrator_ingress
from backend import orchestrator_policy_adapter
from backend import orchestrator_handoff_adapter
from backend import orchestrator_mandate_adapter


SCHEMA_ID = "gg.idekompass-decision-ingress.v1"

ACTION_AUTHORITY = "NONE"
LEDGER_PERSISTENCE = "NONE"
MODEL_OUTPUT_AS_EVIDENCE = False
PLAN_ACTION_IS_APPROVAL = False
CAPABILITY_EXECUTION = "NONE"
AUTOMATIC_MODEL_DISPATCH = "NONE"
COGNITIVE_CORE_BINDING = "REAL_READ_ONLY_EPHEMERAL_VERIFIED_RECORD"

MAX_USER_TEXT = 4096
MAX_CONTEXT_FIELD = 2048
MAX_ROUTE_FIELD = 2048
MAX_PROMPT_EXTENSION = 6000


class IdekompassDecisionError(RuntimeError):
    pass


def _bounded_text(value: object, limit: int, label: str) -> str:
    result = str(value).strip()
    if not result:
        raise IdekompassDecisionError(label + "_EMPTY")
    return result[:limit]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _route_value(route_decision: object | None, name: str, fallback: str) -> str:
    if route_decision is None:
        return fallback
    value = getattr(route_decision, name, fallback)
    return _bounded_text(value, MAX_ROUTE_FIELD, "ROUTE_" + name.upper())


def _verified_context(workspace_context: dict[str, Any]) -> dict[str, str]:
    if not isinstance(workspace_context, dict):
        raise IdekompassDecisionError("WORKSPACE_CONTEXT_INVALID")

    object_id = _bounded_text(
        workspace_context.get("object_id", ""),
        MAX_CONTEXT_FIELD,
        "OBJECT_ID",
    )
    provenance = str(workspace_context.get("provenance", "")).strip()
    raw_path = str(workspace_context.get("source_path", "")).strip()
    raw_sha = str(workspace_context.get("sha256", "")).strip()
    identity_only = provenance == "REAL_UI_STATE" and not raw_path

    if identity_only:
        source_path = "(identity-only)"
        if (
            len(raw_sha) == 64
            and all(ch in "0123456789abcdef" for ch in raw_sha.lower())
        ):
            source_sha256 = raw_sha.lower()
        else:
            source_sha256 = _sha256_text("identity:" + object_id)
    else:
        source_path = _bounded_text(
            raw_path,
            MAX_CONTEXT_FIELD,
            "SOURCE_PATH",
        )
        source_sha256 = _bounded_text(
            raw_sha,
            64,
            "SOURCE_SHA256",
        )
        if (
            len(source_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in source_sha256.lower())
        ):
            raise IdekompassDecisionError("SOURCE_SHA256_INVALID")
        source_sha256 = source_sha256.lower()

    return {
        "source_path": source_path,
        "object_id": object_id,
        "sha256": source_sha256,
    }


def _ready_envelope(
    *,
    task: Any,
    user_text: str,
    context: dict[str, str],
    action_proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = (
        user_text
        + "\x1f"
        + context["object_id"]
        + "\x1f"
        + context["sha256"]
    )

    task_id = "chat-" + _sha256_text(binding)[:32]
    origin_id = "workbench-" + _sha256_text(context["object_id"])[:32]

    validated_action_proposal = None
    effective_risk = "GREEN"
    scope = [
        "verified local workspace source",
        "read-only cognitive primitives",
        "ordinary local chat",
    ]

    if action_proposal is not None:
        validated_action_proposal = (
            action_intent_contract.validate_action_proposal(
                action_proposal
            )
        )
        effective_risk = validated_action_proposal["risk_floor"]
        scope.extend(
            [
                "capability:"
                + validated_action_proposal["capability_human_id"],
                "action-proposal:"
                + validated_action_proposal["proposal_binding_sha256"],
                "target:"
                + validated_action_proposal["target_object_id"]
                + "@"
                + validated_action_proposal["target_source_revision"],
                "effect:"
                + validated_action_proposal["effect_class"],
            ]
        )

    envelope = {
        "schema": task.SCHEMA_ID,
        "task_id": task_id,
        "origin_id": origin_id,
        "state": "READY_FOR_CONTROL",
        "original_expression": user_text,
        "current_interpretation": (
            "Read-only Idékompass decision over verified workspace context "
            "before the existing local-chat inference path."
        ),
        "ready_core": {
            "owner": "GG",
            "goal": user_text,
            "expected_value": (
                "A deterministic plan-only cognitive decision grounded in "
                "verified local source identity."
            ),
            "scope": scope,
            "forbidden_scope": [
                "approval bypass",
                "approval scope drift",
                "target scope drift",
                "cross-task grant reuse",
                "grant replay",
                "unbounded background autonomy",
                "automatic authority expansion",
                "model output as verified evidence",
            ],
            "risk_class": effective_risk,
            "stop_conditions": [
                "verified source identity drift",
                "cognitive contract mismatch",
                "state revalidation conflict",
                "unresolved uncertainty",
                "unexpected authority expansion",
            ],
            "expected_artifacts": [
                "Goal/WHY chain",
                "hypothesis state",
                "decision envelope",
                "state revalidation result",
            ],
            "acceptance_criteria": [
                "ORIGINAL_INTENT preserved",
                "verified source identity remains provenance-bound",
                "GATHER_INFORMATION is plan-only",
                "PLAN_ACTION is plan-only",
                "ACTION_AUTHORITY remains NONE",
                "ledger append remains unused",
                "all explicitly named effects remain pending until MANDATE_VALID",
            ],
        },
    }

    return task.validate_envelope(envelope)


def _goal_chain(
    *,
    goal: Any,
    task: Any,
    envelope: dict[str, Any],
    context: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    canonical = task.canonicalize_envelope(envelope)
    source_task_sha256 = hashlib.sha256(canonical).hexdigest()

    root = goal.make_node(
        node_type="ORIGINAL_INTENT",
        parent_node_id=None,
        why=None,
        body={"statement": envelope["original_expression"]},
    )

    current = goal.make_node(
        node_type="CURRENT_TARGET",
        parent_node_id=root["node_id"],
        why=(
            "För att binda Idékompassens beslut till exakt verifierad "
            "workspace-source."
        ),
        body={
            "statement": (
                context["object_id"]
                + " → "
                + context["source_path"]
                + " · sha256 "
                + context["sha256"]
            )
        },
    )

    goal_node = goal.make_node(
        node_type="GOAL",
        parent_node_id=current["node_id"],
        why=(
            "För att bevara användarens mål utan att expandera action authority."
        ),
        body={"statement": envelope["ready_core"]["goal"]},
    )

    subgoal = goal.make_node(
        node_type="SUBGOAL",
        parent_node_id=goal_node["node_id"],
        why=(
            "För att avgöra minsta nästa kognitiva steg från verifierad evidens."
        ),
        body={
            "statement": (
                "Resolve source-bound decision sufficiency before ordinary "
                "local-chat inference."
            )
        },
    )

    task_node = goal.make_node(
        node_type="TASK",
        parent_node_id=subgoal["node_id"],
        why=(
            "För att köra read-only Idékompass utan verkställande authority."
        ),
        body={
            "task_id": envelope["task_id"],
            "source_task_sha256": source_task_sha256,
        },
    )

    continue_action = goal.make_node(
        node_type="ACTION",
        parent_node_id=task_node["node_id"],
        why=(
            "För att tillåta den redan existerande lokala chat-inferensen "
            "när source-bound route är verifierad."
        ),
        body={
            "action_id": "continue-local-chat",
            "description": (
                "Continue the existing local-chat inference path with bounded "
                "Idékompass context; execute no tool or host action."
            ),
        },
    )

    hold_action = goal.make_node(
        node_type="ACTION",
        parent_node_id=task_node["node_id"],
        why=(
            "För att hålla execution blockerad när beslutets evidens inte räcker."
        ),
        body={
            "action_id": "hold-local-chat",
            "description": (
                "Hold execution and require more verified information; "
                "perform no capability action."
            ),
        },
    )

    chain = goal.build_goal_why_chain(
        envelope,
        [
            root,
            current,
            goal_node,
            subgoal,
            task_node,
            continue_action,
            hold_action,
        ],
    )

    return chain, continue_action, hold_action


def _claim_candidate(
    *,
    ledger: Any,
    envelope: dict[str, Any],
    claim_key: str,
    statement: str,
    epistemic_class: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
) -> dict[str, Any]:
    return ledger.make_claim_candidate(
        task_id=envelope["task_id"],
        origin_id=envelope["origin_id"],
        claim_key=claim_key,
        statement=statement,
        epistemic_class=epistemic_class,
        source_kind=source_kind,
        source_id=source_id,
        source_fingerprint=source_fingerprint,
        parent_entry_sha256s=None,
    )


def _render_prompt_extension(result: dict[str, Any]) -> str:
    payload = {
        "schema": SCHEMA_ID,
        "decision_kind": result["decision_kind"],
        "reason_code": result["reason_code"],
        "selected_action_node_id": result["selected_action_node_id"],
        "revalidation_result": result["revalidation_result"],
        "revalidation_reason": result["revalidation_reason"],
        "route_intent": result["route_intent"],
        "route_mode": result["route_mode"],
        "route_why": result["route_why"],
        "verified_source_sha256": result["verified_source_sha256"],
        "action_authority": ACTION_AUTHORITY,
        "plan_action_is_approval": PLAN_ACTION_IS_APPROVAL,
        "capability_execution": CAPABILITY_EXECUTION,
        "automatic_model_dispatch": AUTOMATIC_MODEL_DISPATCH,
        "ledger_persistence": LEDGER_PERSISTENCE,
        "model_output_as_evidence": MODEL_OUTPUT_AS_EVIDENCE,
        "cognitive_core_binding": COGNITIVE_CORE_BINDING,
    }

    rendered = (
        "\n\n[GG IDEKOMPASS READ-ONLY DECISION]\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n[/GG IDEKOMPASS READ-ONLY DECISION]\n"
    )

    if len(rendered) > MAX_PROMPT_EXTENSION:
        raise IdekompassDecisionError("PROMPT_EXTENSION_BUDGET_EXCEEDED")

    return rendered


def decide(
    *,
    user_text: str,
    workspace_context: dict[str, Any],
    route_decision: object | None,
    information_available: bool = True,
    assigned_participant: str | None = None,
    creator_actor: str | None = None,
    action_proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_user = " ".join(str(user_text).split())[:MAX_USER_TEXT]
    if not normalized_user:
        raise IdekompassDecisionError("USER_TEXT_EMPTY")

    context = _verified_context(workspace_context)
    validated_action_proposal = None
    if action_proposal is not None:
        validated_action_proposal = (
            action_intent_contract.validate_action_proposal(
                action_proposal
            )
        )
        if route_decision is None:
            raise ValueError("ACTION_PROPOSAL_ROUTE_MISSING")
        if (
            getattr(route_decision, "primary_capability", None)
            != validated_action_proposal["capability_human_id"]
        ):
            raise ValueError("ACTION_PROPOSAL_ROUTE_MISMATCH")
        if (
            getattr(route_decision, "automatic_model_dispatch", None)
            is not False
        ):
            raise ValueError("ACTION_PROPOSAL_AUTODISPATCH_FORBIDDEN")
        if (
            getattr(
                route_decision,
                "registered_capability_execution",
                None,
            )
            is not False
        ):
            raise ValueError("ACTION_PROPOSAL_EXECUTION_FORBIDDEN")
        if (
            validated_action_proposal["target_object_id"]
            != context["object_id"]
            or validated_action_proposal["target_source_revision"]
            != context["sha256"]
        ):
            raise ValueError("ACTION_PROPOSAL_TARGET_MISMATCH")
    stack = cognitive.load_stack()

    task = stack["task"]
    ledger = stack["ledger"]
    goal = stack["goal"]
    hypothesis = stack["hypothesis"]

    envelope = _ready_envelope(
        task=task,
        user_text=normalized_user,
        context=context,
        action_proposal=validated_action_proposal,
    )

    goal_chain, continue_action, hold_action = _goal_chain(
        goal=goal,
        task=task,
        envelope=envelope,
        context=context,
    )

    route_intent = _route_value(
        route_decision,
        "intent",
        "UNRESOLVED",
    )
    route_mode = _route_value(
        route_decision,
        "route_mode",
        "UNRESOLVED",
    )
    route_why = _route_value(
        route_decision,
        "why",
        "No deterministic source-bound route is currently available.",
    )

    pass_key = "idekompass-route-binding"
    fail_key = "idekompass-route-binding-mismatch"

    pass_statement = (
        "The source-bound Natural Intent route is verified for "
        + context["object_id"]
        + " at sha256 "
        + context["sha256"]
        + " with intent "
        + route_intent
        + " and route mode "
        + route_mode
        + "."
    )

    fail_statement = (
        "The source-bound Natural Intent route is not sufficiently verified "
        "for the current workspace source."
    )

    route_binding = json.dumps(
        {
            "object_id": context["object_id"],
            "sha256": context["sha256"],
            "intent": route_intent,
            "route_mode": route_mode,
            "why": route_why,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    pass_candidate = _claim_candidate(
        ledger=ledger,
        envelope=envelope,
        claim_key=pass_key,
        statement=pass_statement,
        epistemic_class=(
            "VERIFIED"
            if route_decision is not None
            else "ASSUMPTION"
        ),
        source_kind=(
            "DETERMINISTIC_TOOL"
            if route_decision is not None
            else "DERIVATION"
        ),
        source_id=(
            "workbench-context-resolver+natural-intent-laser"
            if route_decision is not None
            else "idekompass-decision-ingress"
        ),
        source_fingerprint=_sha256_text(route_binding),
    )

    fail_candidate = _claim_candidate(
        ledger=ledger,
        envelope=envelope,
        claim_key=fail_key,
        statement=fail_statement,
        epistemic_class="ASSUMPTION",
        source_kind="DERIVATION",
        source_id="idekompass-decision-ingress",
        source_fingerprint=_sha256_text(fail_statement),
    )

    records: list[dict[str, Any]] = []

    if route_decision is not None:
        pass_record = ledger.finalize_record(
            pass_candidate,
            0,
            None,
            [],
        )
        ledger.verify_chain([pass_record])
        records = [pass_record]

    pass_ref = cognitive.claim_ref(pass_candidate)
    fail_ref = cognitive.claim_ref(fail_candidate)

    pass_hypothesis_statement = (
        "The verified source-bound route is sufficient to continue the "
        "existing local-chat inference path."
    )
    fail_hypothesis_statement = (
        "The source-bound route is unresolved and local-chat progression "
        "must remain cognitively blocked."
    )

    pass_hypothesis = hypothesis.make_hypothesis(
        kind="HYPOTHESIS",
        statement=pass_hypothesis_statement,
        source_kind="DERIVATION",
        source_id="idekompass-decision-ingress",
        source_fingerprint=_sha256_text(pass_hypothesis_statement),
        support_refs=[pass_ref],
        falsifier_refs=[fail_ref],
        candidate_action_node_ids=[continue_action["node_id"]],
    )

    fail_hypothesis = hypothesis.make_hypothesis(
        kind="HYPOTHESIS",
        statement=fail_hypothesis_statement,
        source_kind="DERIVATION",
        source_id="idekompass-decision-ingress",
        source_fingerprint=_sha256_text(fail_hypothesis_statement),
        support_refs=[fail_ref],
        falsifier_refs=[pass_ref],
        candidate_action_node_ids=[hold_action["node_id"]],
    )

    information_options = []

    if information_available:
        information_options.append(
            hypothesis.make_information_option(
                kind="OBSERVE_MORE",
                description=(
                    "Acquire additional verified local context before "
                    "progressing beyond the current source-bound decision."
                ),
                cost_rank="LOW",
                discriminates_hypothesis_ids=[
                    pass_hypothesis["hypothesis_id"],
                    fail_hypothesis["hypothesis_id"],
                ],
            )
        )

    requested_claim_keys = [
        pass_key,
        fail_key,
    ]

    hypothesis_state = hypothesis.build_hypothesis_state(
        records,
        requested_claim_keys,
        goal_chain,
        envelope,
        [
            pass_hypothesis,
            fail_hypothesis,
        ],
        information_options,
        "EXPLICIT_CLOSED_FOR_DECISION",
    )

    core_decision = hypothesis.select_next_step(
        hypothesis_state,
        records,
        requested_claim_keys,
        goal_chain,
        envelope,
    )

    state_base, revalidation = cognitive.make_and_revalidate_state(
        participant_id="chat-idekompass",
        records=records,
        requested_claim_keys=requested_claim_keys,
        goal_chain=goal_chain,
        hypothesis_state=hypothesis_state,
        envelope=envelope,
        stack=stack,
    )

    decision_kind = str(core_decision["kind"])
    reason_code = str(core_decision["reason_code"])
    selected_action_node_id = core_decision.get(
        "selected_action_node_id"
    )

    revalidation_result = str(
        revalidation["result"]
    )
    revalidation_reason = str(
        revalidation["reason_code"]
    )

    if revalidation_result != "REVALIDATED":
        decision_kind = "STOP_UNCERTAINTY"
        reason_code = (
            "STATE_REVALIDATION_"
            + revalidation_result
            + "_"
            + revalidation_reason
        )
        selected_action_node_id = None

    bound_action_intent = None
    if validated_action_proposal is not None:
        if decision_kind != "PLAN_ACTION":
            raise ValueError("ACTION_PROPOSAL_REQUIRES_PLAN_ACTION")
        if revalidation_result != "REVALIDATED":
            raise ValueError("ACTION_PROPOSAL_REVALIDATION_REQUIRED")
        source_binding = state_base.get("source_binding")
        if not isinstance(source_binding, dict):
            raise ValueError("ACTION_PROPOSAL_STATE_BINDING_MISSING")
        bound_action_intent = action_intent_contract.bind_action_intent(
            action_proposal=validated_action_proposal,
            task_id=envelope["task_id"],
            origin_id=envelope["origin_id"],
            state_base_revision=state_base["state_base_revision"],
            goal_chain_sha256=source_binding["goal_chain_sha256"],
            action_trace_sha256=source_binding["action_trace_sha256"],
        )

    result = {
        "schema": SCHEMA_ID,
        "decision_kind": decision_kind,
        "reason_code": reason_code,
        "selected_action_node_id": selected_action_node_id,
        "action_intent": bound_action_intent,
        "revalidation_result": revalidation_result,
        "revalidation_reason": revalidation_reason,
        "route_intent": route_intent,
        "route_mode": route_mode,
        "route_why": route_why,
        "verified_source_sha256": context["sha256"],
        "action_authority": ACTION_AUTHORITY,
        "plan_action_is_approval": PLAN_ACTION_IS_APPROVAL,
        "ledger_persistence": LEDGER_PERSISTENCE,
        "model_output_as_evidence": MODEL_OUTPUT_AS_EVIDENCE,
        "capability_execution": CAPABILITY_EXECUTION,
        "automatic_model_dispatch": AUTOMATIC_MODEL_DISPATCH,
        "cognitive_core_binding": COGNITIVE_CORE_BINDING,
        "goal_chain": goal_chain,
        "hypothesis_state": hypothesis_state,
        "state_base": state_base,
        "revalidation": revalidation,
    }

    result["initiative_proposals"] = (
        initiative_proposal.derive_from_decision(
            task_id=envelope["task_id"],
            goal_chain=goal_chain,
            state_base_revision=(
                state_base[
                    "state_base_revision"
                ]
            ),
            decision_kind=decision_kind,
            reason_code=reason_code,
            selected_action_node_id=(
                selected_action_node_id
            ),
            information_options=(
                information_options
            ),
            action_proposal=(
                validated_action_proposal
            ),
        )
    )

    result["prompt_extension"] = _render_prompt_extension(result)
    result["orchestrator_ingress"] = (
        orchestrator_ingress.prepare_or_block(
            envelope=envelope,
            verified_context=context,
            assigned_participant=assigned_participant,
            creator_actor=creator_actor,
        )
    )
    result["orchestrator_policy"] = (
        orchestrator_policy_adapter.validate_prepared_task(
            result["orchestrator_ingress"]
        )
    )
    result["orchestrator_handoff"] = (
        orchestrator_handoff_adapter.validate_policy_handoff(
            result["orchestrator_policy"]
        )
    )
    result["orchestrator_mandate"] = (
        orchestrator_mandate_adapter.prepare_approval_request(
            decision_kind=decision_kind,
            revalidation_result=revalidation_result,
            source_envelope=envelope,
            goal_chain=goal_chain,
            hypothesis_state=hypothesis_state,
            state_base=state_base,
            ledger_records=records,
            memory_records=[],
            orchestrator_policy=result["orchestrator_policy"],
            orchestrator_handoff=result["orchestrator_handoff"],
        )
    )
    return result
