from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

BACKEND = (
    PROJECT_ROOT
    / "backend"
)

sys.path.insert(
    0,
    str(BACKEND),
)

import machine_graph as G  # noqa: E402
import solver_router as S  # noqa: E402


def port(
    port_id: str,
    direction: str,
    schema_id: str,
    *,
    semantic_id: str | None = None,
    max_connections: int = 1,
    channel_class: str = "DATA",
    authority_contract: str = "NONE",
) -> G.PortSpec:
    return G.PortSpec(
        port_id=port_id,
        direction=direction,
        schema_id=schema_id,
        semantic_id=(
            schema_id
            if semantic_id is None
            else semantic_id
        ),
        channel_class=channel_class,
        semantics=(
            "test:"
            + port_id
        ),
        authority_contract=(
            authority_contract
        ),
        max_connections=(
            max_connections
        ),
    )


def node(
    node_id: str,
    ports: tuple[
        G.PortSpec,
        ...
    ],
    *,
    version: str = "v1",
    enabled: bool = True,
) -> G.NodeSpec:
    return G.NodeSpec(
        node_id=node_id,
        implementation_id=(
            "test."
            + node_id
        ),
        contract_version=version,
        state_owner=(
            "SELF"
        ),
        ports=ports,
        enabled=enabled,
    )


def edge(
    edge_id: str,
    source: str,
    source_port: str,
    target: str,
    target_port: str,
    *,
    enabled: bool = True,
) -> G.EdgeSpec:
    return G.EdgeSpec(
        edge_id=edge_id,
        from_node_id=source,
        from_port_id=source_port,
        to_node_id=target,
        to_port_id=target_port,
        enabled=enabled,
    )


class MachineGraphTests(
    unittest.TestCase
):
    def simple_graph(
        self,
    ) -> G.MachineGraph:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.text.v1",
                    max_connections=4,
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.text.v1",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        graph.validate()

        return graph

    def test_hash_is_order_independent(
        self,
    ) -> None:
        graph = self.simple_graph()

        reversed_graph = G.MachineGraph(
            nodes=tuple(
                reversed(
                    graph.nodes
                )
            ),
            edges=(),
        )

        self.assertEqual(
            graph.graph_sha256(),
            reversed_graph.graph_sha256(),
        )

    def test_connect_and_inverse_disconnect_round_trip(
        self,
    ) -> None:
        graph = self.simple_graph()

        connection = edge(
            "wire-1",
            "source",
            "out",
            "target",
            "in",
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=connection,
                ),
            ),
        )

        result = G.apply_patch(
            graph,
            patch,
        )

        self.assertEqual(
            1,
            len(
                result.graph.edges
            ),
        )

        restored = G.apply_patch(
            result.graph,
            result.inverse_patch,
        )

        self.assertEqual(
            graph.graph_sha256(),
            restored.graph.graph_sha256(),
        )

    def test_schema_mismatch_is_fail_closed(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v2",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

        self.assertEqual(
            0,
            len(
                graph.edges
            ),
        )

    def test_semantic_mismatch_is_fail_closed(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                    semantic_id=(
                        "gg.semantic.alpha.v1"
                    ),
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                    semantic_id=(
                        "gg.semantic.beta.v1"
                    ),
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        before = (
            graph.graph_sha256()
        )

        patch = G.GraphPatch(
            base_graph_sha256=before,
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

        self.assertEqual(
            before,
            graph.graph_sha256(),
        )

        self.assertEqual(
            (),
            graph.edges,
        )

    def test_channel_mismatch_is_fail_closed(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                    channel_class="DATA",
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                    channel_class="EVIDENCE",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

    def test_authority_contract_mismatch_is_fail_closed(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                    authority_contract="NONE",
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                    authority_contract="MANDATE_REQUIRED",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

    def test_input_connection_limit_is_enforced(
        self,
    ) -> None:
        first = node(
            "first",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                ),
            ),
        )

        second = node(
            "second",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                    max_connections=1,
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                first,
                second,
                target,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-a",
                        "first",
                        "out",
                        "target",
                        "in",
                    ),
                ),
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-b",
                        "second",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

    def test_output_fanout_can_be_declared(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.test.v1",
                    max_connections=2,
                ),
            ),
        )

        first = node(
            "first",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                ),
            ),
        )

        second = node(
            "second",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                first,
                second,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-a",
                        "source",
                        "out",
                        "first",
                        "in",
                    ),
                ),
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-b",
                        "source",
                        "out",
                        "second",
                        "in",
                    ),
                ),
            ),
        )

        result = G.apply_patch(
            graph,
            patch,
        )

        self.assertEqual(
            2,
            len(
                result.graph.edges
            ),
        )

    def test_disable_node_requires_connected_edge_disabled(
        self,
    ) -> None:
        base = self.simple_graph()

        connected = G.apply_patch(
            base,
            G.GraphPatch(
                base_graph_sha256=(
                    base.graph_sha256()
                ),
                operations=(
                    G.GraphOperation(
                        op=G.OP_CONNECT,
                        edge=edge(
                            "wire-1",
                            "source",
                            "out",
                            "target",
                            "in",
                        ),
                    ),
                ),
            ),
        ).graph

        invalid = G.GraphPatch(
            base_graph_sha256=(
                connected.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_DISABLE_NODE,
                    node_id="target",
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                connected,
                invalid,
            )

        valid = G.GraphPatch(
            base_graph_sha256=(
                connected.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_DISABLE_EDGE,
                    edge_id="wire-1",
                ),
                G.GraphOperation(
                    op=G.OP_DISABLE_NODE,
                    node_id="target",
                ),
            ),
        )

        result = G.apply_patch(
            connected,
            valid,
        )

        restored = G.apply_patch(
            result.graph,
            result.inverse_patch,
        )

        self.assertEqual(
            connected.graph_sha256(),
            restored.graph.graph_sha256(),
        )

    def test_node_replace_is_reversible(
        self,
    ) -> None:
        original = node(
            "worker",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v1",
                ),
            ),
            version="v1",
        )

        replacement = node(
            "worker",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.test.v2",
                ),
            ),
            version="v2",
        )

        graph = G.MachineGraph(
            nodes=(
                original,
            ),
            edges=(),
        )

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_REMOVE_NODE,
                    node_id="worker",
                ),
                G.GraphOperation(
                    op=G.OP_ADD_NODE,
                    node=replacement,
                ),
            ),
        )

        result = G.apply_patch(
            graph,
            patch,
        )

        self.assertEqual(
            "v2",
            result.graph.nodes[
                0
            ].contract_version,
        )

        restored = G.apply_patch(
            result.graph,
            result.inverse_patch,
        )

        self.assertEqual(
            graph.graph_sha256(),
            restored.graph.graph_sha256(),
        )

    def test_explicit_adapter_bridges_versions(
        self,
    ) -> None:
        source = node(
            "source",
            (
                port(
                    "out",
                    G.OUTPUT,
                    "gg.text.v1",
                ),
            ),
        )

        target = node(
            "target",
            (
                port(
                    "in",
                    G.INPUT,
                    "gg.text.v2",
                ),
            ),
        )

        graph = G.MachineGraph(
            nodes=(
                source,
                target,
            ),
            edges=(),
        )

        direct = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "direct",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                direct,
            )

        adapter = node(
            "adapter",
            (
                port(
                    "in-v1",
                    G.INPUT,
                    "gg.text.v1",
                ),
                port(
                    "out-v2",
                    G.OUTPUT,
                    "gg.text.v2",
                ),
            ),
        )

        adapted = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_ADD_NODE,
                    node=adapter,
                ),
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-v1",
                        "source",
                        "out",
                        "adapter",
                        "in-v1",
                    ),
                ),
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-v2",
                        "adapter",
                        "out-v2",
                        "target",
                        "in",
                    ),
                ),
            ),
        )

        result = G.apply_patch(
            graph,
            adapted,
        )

        self.assertEqual(
            3,
            len(
                result.graph.nodes
            ),
        )

        self.assertEqual(
            2,
            len(
                result.graph.edges
            ),
        )

    def test_multi_operation_failure_is_atomic(
        self,
    ) -> None:
        graph = self.simple_graph()

        before = (
            graph.graph_sha256()
        )

        patch = G.GraphPatch(
            base_graph_sha256=before,
            operations=(
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-good",
                        "source",
                        "out",
                        "target",
                        "in",
                    ),
                ),
                G.GraphOperation(
                    op=G.OP_CONNECT,
                    edge=edge(
                        "wire-bad",
                        "source",
                        "out",
                        "missing-node",
                        "in",
                    ),
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

        self.assertEqual(
            before,
            graph.graph_sha256(),
        )

        self.assertEqual(
            (),
            graph.edges,
        )

    def test_patch_preimage_mismatch_is_rejected(
        self,
    ) -> None:
        graph = self.simple_graph()

        patch = G.GraphPatch(
            base_graph_sha256=(
                "0" * 64
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_DISABLE_NODE,
                    node_id="target",
                ),
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

    def test_patch_cannot_self_grant_action_authority(
        self,
    ) -> None:
        graph = self.simple_graph()

        patch = G.GraphPatch(
            base_graph_sha256=(
                graph.graph_sha256()
            ),
            operations=(
                G.GraphOperation(
                    op=G.OP_DISABLE_NODE,
                    node_id="target",
                ),
            ),
            action_authority=(
                "SELF_GRANTED"
            ),
        )

        with self.assertRaises(
            G.MachineGraphError
        ):
            G.apply_patch(
                graph,
                patch,
            )

    def test_workbench_runtime_graph_matches_existing_call_contacts(self) -> None:
        import ast as runtime_ast
        import inspect
        import textwrap as runtime_textwrap

        import main as W
        from backend import solver_router as S
        from backend import local_ai_chat_runner as L
        from backend import autonomy_controller as A
        from backend import local_ai_model_runner as LM
        from backend import safe_tool_runner as ST
        from backend import write_runner as WR
        from backend import resident_information_state as RIS
        from backend import source_change_event as SCE
        from backend import merkle_propagation as MP
        from backend import incremental_focus as IF
        from backend.live_aid import post_draft_qml_process_runner as PDPR
        from backend.live_aid import post_draft_qml_executor as PDE
        from backend.live_aid import post_draft_qml_driver as PDD

        expected = (
            (
                "call-01",
                "context_resolver.validate_snapshot_json",
                "CHAT_BRIDGE",
                "CONTEXT_RESOLVER",
                W.ChatBridge.syncContextSnapshot,
            ),
            (
                "call-02",
                "context_resolver.resolve_snapshot",
                "CHAT_BRIDGE",
                "CONTEXT_RESOLVER",
                W.ChatBridge._resolved_chat_context,
            ),
            (
                "call-03",
                "context_resolver.render_extension",
                "CHAT_BRIDGE",
                "CONTEXT_RESOLVER",
                W.ChatBridge._resolved_chat_context,
            ),
            (
                "call-04",
                "capability_registry.CapabilityRegistry.load",
                "CHAT_BRIDGE",
                "CAPABILITY_REGISTRY",
                W.ChatBridge._ensure_natural_intent_laser,
            ),
            (
                "call-05",
                "solver_router.SolverRouter",
                "CHAT_BRIDGE",
                "SOLVER_ROUTER",
                W.ChatBridge._ensure_natural_intent_laser,
            ),
            (
                "call-06",
                "solver_router.LaserFocusCache",
                "CHAT_BRIDGE",
                "LASER_FOCUS_CACHE",
                W.ChatBridge._ensure_natural_intent_laser,
            ),
            (
                "call-07",
                "self._intent_laser.bind",
                "CHAT_BRIDGE",
                "LASER_FOCUS_CACHE",
                W.ChatBridge._natural_intent_route,
            ),
            (
                "call-08",
                "self._intent_laser.lookup",
                "CHAT_BRIDGE",
                "LASER_FOCUS_CACHE",
                W.ChatBridge._natural_intent_route,
            ),
            (
                "call-09",
                "self._router.route",
                "LASER_FOCUS_CACHE",
                "SOLVER_ROUTER",
                S.LaserFocusCache._compile,
            ),
            (
                "call-10",
                "self._router.route_focus_key",
                "LASER_FOCUS_CACHE",
                "SOLVER_ROUTER",
                S.LaserFocusCache.focus,
            ),
                        (
                "call-100",
                "initiative_proposal.derive_from_decision",
                "IDEKOMPASS",
                "INITIATIVE_PROPOSAL",
                W.idekompass_decision_ingress.decide,
            ),
(
    "call-101",
    "learning_memory.build_episodic_experience",
    "ACTION_DONE_WHEN",
    "LEARNING_MEMORY_PROMOTION",
    W.action_execution_safe_tool_adapter.action_done_when.evaluate_action_done_when,
),
            (
                "call-102",
                "live_mandate_store.put_pending",
                "CHAT_BRIDGE",
                "LIVE_MANDATE_STORE",
                W.ChatBridge._capture_pending_mandate,
            ),
            (
                "call-103",
                "live_mandate_store.approve",
                "CHAT_BRIDGE",
                "LIVE_MANDATE_STORE",
                W.ChatBridge._submit_mandate,
            ),
            (
                "call-104",
                "live_mandate_store.reject",
                "CHAT_BRIDGE",
                "LIVE_MANDATE_STORE",
                W.ChatBridge._submit_mandate,
            ),
            (
                "call-105",
                "task_scoped_action_grant.issue_from_approved_record",
                "CHAT_BRIDGE",
                "TASK_SCOPED_ACTION_GRANT",
                W.ChatBridge._submit_mandate,
            ),
(
                "call-11",
                "self._registry.active_working_set",
                "SOLVER_ROUTER",
                "CAPABILITY_REGISTRY",
                S.SolverRouter._working_set,
            ),
            (
                "call-12",
                "idekompass_decision_ingress.decide",
                "CHAT_BRIDGE",
                "IDEKOMPASS",
                W.ChatBridge.submit,
            ),
            (
                "call-13",
                "resident_state.WorkbenchResidentInformationState.bootstrap_workbench_sources",
                "CHAT_BRIDGE",
                "RESIDENT_INFORMATION",
                W.ChatBridge.__init__,
            ),
            (
                "call-14",
                "control_contract.parse_control_command",
                "CHAT_BRIDGE",
                "CONTROL_PLANE_CONTRACT",
                W.ChatBridge.submit,
            ),
            (
                "call-15",
                "post_draft_qml_process_runner.validate_request",
                "LIVE_AID_QT_BRIDGE",
                "POST_DRAFT_PROCESS_RUNNER",
                W.LiveAidQtBridge.runPostDraftRepair,
            ),
            (
                "call-16",
                "LiveAidService",
                "LIVE_AID_QT_BRIDGE",
                "LIVE_AID_SERVICE",
                W.LiveAidQtBridge.__init__,
            ),
            (
                "call-17",
                "qml_preflight_runner.validate_request",
                "LIVE_AID_QT_BRIDGE",
                "QML_PREFLIGHT_RUNNER",
                W.LiveAidQtBridge.preflight,
            ),
            (
                "call-18",
                "qml_preflight_runner.validate_response",
                "LIVE_AID_QT_BRIDGE",
                "QML_PREFLIGHT_RUNNER",
                W.LiveAidQtBridge._preflight_finished,
            ),
            (
                "call-19",
                "repair_model_runner.validate_request",
                "LIVE_AID_QT_BRIDGE",
                "REPAIR_MODEL_RUNNER",
                W.LiveAidQtBridge.requestRepair,
            ),
            (
                "call-20",
                "repair_model_runner.validate_response",
                "LIVE_AID_QT_BRIDGE",
                "REPAIR_MODEL_RUNNER",
                W.LiveAidQtBridge._repair_finished,
            ),
            (
                "call-21",
                "contract.validate_request",
                "CHAT_BRIDGE",
                "LOCAL_AI_CONTRACT",
                W.ChatBridge.submit,
            ),
            (
                "call-22",
                "contract.canonical_request_json",
                "CHAT_BRIDGE",
                "LOCAL_AI_CONTRACT",
                W.ChatBridge.submit,
            ),
            (
                "call-23",
                "contract.validate_response",
                "CHAT_BRIDGE",
                "LOCAL_AI_CONTRACT",
                W.ChatBridge._finished,
            ),
            (
                "call-24",
                "tool_contract.validate_request",
                "CHAT_BRIDGE",
                "SAFE_TOOL_CONTRACT",
                W.ChatBridge._submit_tool,
            ),
            (
                "call-25",
                "tool_contract.canonical_request_json",
                "CHAT_BRIDGE",
                "SAFE_TOOL_CONTRACT",
                W.ChatBridge._submit_tool,
            ),
            (
                "call-26",
                "tool_contract.validate_response",
                "CHAT_BRIDGE",
                "SAFE_TOOL_CONTRACT",
                W.ChatBridge._tool_finished,
            ),
            (
                "call-27",
                "write_contract.validate_request",
                "CHAT_BRIDGE",
                "WRITE_CONTRACT",
                W.ChatBridge._submit_write,
            ),
            (
                "call-28",
                "write_contract.canonical_request_json",
                "CHAT_BRIDGE",
                "WRITE_CONTRACT",
                W.ChatBridge._submit_write,
            ),
            (
                "call-29",
                "write_contract.validate_response",
                "CHAT_BRIDGE",
                "WRITE_CONTRACT",
                W.ChatBridge._write_finished,
            ),
            (
                "call-30",
                "autonomy_contract.validate_grant",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTRACT",
                W.ChatBridge._submit_autonomy,
            ),
            (
                "call-31",
                "autonomy_contract.grant_sha256",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTRACT",
                W.ChatBridge._submit_autonomy,
            ),
            (
                "call-32",
                "autonomy_contract.validate_request",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTRACT",
                W.ChatBridge._submit_autonomy,
            ),
            (
                "call-33",
                "autonomy_contract.canonical_json",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTRACT",
                W.ChatBridge._submit_autonomy,
            ),
            (
                "call-34",
                "autonomy_contract.validate_result",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTRACT",
                W.ChatBridge._autonomy_finished,
            ),
            (
                "call-35",
                "base.execute_synthetic",
                "LOCAL_AI_CHAT_RUNNER",
                "LOCAL_AI_MODEL_RUNNER",
                L.execute_chat,
            ),
            (
                "call-36",
                "candidate_runner.initialize",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-37",
                "candidate_runner.write_attempt",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-38",
                "candidate_runner.qml_gate",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-39",
                "candidate_runner.read_before",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-40",
                "candidate_runner.read_candidate",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-41",
                "candidate_runner.diff_text",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-42",
                "candidate_runner.repair_to_intended",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_CANDIDATE_RUNNER",
                A.execute,
            ),
            (
                "call-43",
                "cognition.trace_action",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-44",
                "cognition.append_claim",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-45",
                "cognition.read_records",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-46",
                "cognition.make_and_revalidate_state",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-47",
                "cognition.make_claim_candidate",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-48",
                "cognition.make_binary_hypothesis_state",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-49",
                "cognition.append_prebuilt_candidate",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_COGNITIVE_ADAPTER",
                A.execute,
            ),
            (
                "call-50",
                "self._resident_information_state.ingest_verified_write_completion",
                "CHAT_BRIDGE",
                "RESIDENT_INFORMATION",
                W.ChatBridge._write_finished,
            ),
            (
                "call-51",
                "self._resident_information_state.ingest_verified_write_rollback",
                "CHAT_BRIDGE",
                "RESIDENT_INFORMATION",
                W.ChatBridge._write_finished,
            ),
            (
                "call-52",
                "ingest_verified_host_source_change",
                "RESIDENT_INFORMATION",
                "SOURCE_CHANGE_EVENT",
                RIS.WorkbenchResidentInformationState._ingest_event,
            ),
            (
                "call-53",
                "dag.apply_leaf_change",
                "SOURCE_CHANGE_EVENT",
                "RESIDENT_MERKLE_DAG",
                SCE.ingest_verified_host_source_change,
            ),
            (
                "call-54",
                "focus_index.apply_change",
                "RESIDENT_MERKLE_DAG",
                "INCREMENTAL_FOCUS_INDEX",
                MP.ResidentMerklePropagationDAG.apply_leaf_change,
            ),
            (
                "call-55",
                "self._cache.discard",
                "INCREMENTAL_FOCUS_INDEX",
                "COMPILED_FOCUS_CACHE",
                IF.IncrementalFocusIndex._drop,
            ),
            (
                "call-56",
                "executor_module.PostDraftQmlExecutor",
                "POST_DRAFT_PROCESS_RUNNER",
                "POST_DRAFT_QML_EXECUTOR",
                PDPR.run_request,
            ),
            (
                "call-57",
                "executor.run_complete_draft",
                "POST_DRAFT_PROCESS_RUNNER",
                "POST_DRAFT_QML_EXECUTOR",
                PDPR.run_request,
            ),
            (
                "call-58",
                "post_draft_qml_driver.PostDraftQmlDriver",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor.__init__,
            ),
            (
                "call-59",
                "self.driver.snapshot",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._emit,
            ),
            (
                "call-60",
                "self.driver.snapshot",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._result,
            ),
            (
                "call-61",
                "self.driver.accept_external_fault",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._block,
            ),
            (
                "call-62",
                "self.driver.accept_preflight_response",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._execute_preflight,
            ),
            (
                "call-63",
                "self.driver.accept_repair_response",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._execute_repair,
            ),
            (
                "call-64",
                "self.driver.snapshot",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor._execute_repair,
            ),
            (
                "call-65",
                "self.driver.update_draft",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor.run_complete_draft,
            ),
            (
                "call-66",
                "self.driver.mark_draft_complete",
                "POST_DRAFT_QML_EXECUTOR",
                "POST_DRAFT_QML_DRIVER",
                PDE.PostDraftQmlExecutor.run_complete_draft,
            ),
            (
                "call-67",
                "post_draft_coordinator.PostDraftCoordinator",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.__init__,
            ),
            (
                "call-68",
                "self._coordinator.snapshot",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.snapshot,
            ),
            (
                "call-69",
                "self._coordinator.update_draft",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.update_draft,
            ),
            (
                "call-70",
                "self._coordinator.mark_draft_complete",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.mark_draft_complete,
            ),
            (
                "call-71",
                "self._coordinator.accept_validation",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.accept_preflight_response,
            ),
            (
                "call-72",
                "self._coordinator.promote_ready",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.accept_preflight_response,
            ),
            (
                "call-73",
                "self._coordinator.accept_validation",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.accept_preflight_response,
            ),
            (
                "call-74",
                "self._coordinator.accept_repair_candidate",
                "POST_DRAFT_QML_DRIVER",
                "POST_DRAFT_COORDINATOR",
                PDD.PostDraftQmlDriver.accept_repair_response,
            ),
            (
                "call-75",
                "post_draft_qml_process_runner.validate_event",
                "LIVE_AID_QT_BRIDGE",
                "POST_DRAFT_PROCESS_RUNNER",
                W.LiveAidQtBridge._consume_post_draft_stdout,
            ),
            (
                "call-76",
                "post_draft_qml_process_runner.validate_response",
                "LIVE_AID_QT_BRIDGE",
                "POST_DRAFT_PROCESS_RUNNER",
                W.LiveAidQtBridge._consume_post_draft_stdout,
            ),
            (
                "call-77",
                "cognitive.load_stack",
                "IDEKOMPASS",
                "AUTONOMY_COGNITIVE_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-78",
                "cognitive.claim_ref",
                "IDEKOMPASS",
                "AUTONOMY_COGNITIVE_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-79",
                "cognitive.claim_ref",
                "IDEKOMPASS",
                "AUTONOMY_COGNITIVE_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-80",
                "cognitive.make_and_revalidate_state",
                "IDEKOMPASS",
                "AUTONOMY_COGNITIVE_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-81",
                "orchestrator_ingress.prepare_or_block",
                "IDEKOMPASS",
                "ORCHESTRATOR_INGRESS",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-82",
                "orchestrator_policy_adapter.validate_prepared_task",
                "IDEKOMPASS",
                "ORCHESTRATOR_POLICY_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-83",
                "orchestrator_handoff_adapter.validate_policy_handoff",
                "IDEKOMPASS",
                "ORCHESTRATOR_HANDOFF_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-84",
                "orchestrator_mandate_adapter.prepare_approval_request",
                "IDEKOMPASS",
                "ORCHESTRATOR_MANDATE_ADAPTER",
                W.idekompass_decision_ingress.decide,
            ),
            (
                "call-85",
                "orchestrator_mandate_evaluation_adapter.evaluate_not_required",
                "CHAT_BRIDGE",
                "ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER",
                W.ChatBridge.submit,
            ),
            (
                "call-86",
                "self._intent_capability_registry.get",
                "CHAT_BRIDGE",
                "CAPABILITY_REGISTRY",
                W.ChatBridge._natural_action_proposal,
            ),
            (
                "call-87",
                "action_intent_contract.make_action_proposal",
                "CHAT_BRIDGE",
                "ACTION_INTENT_CONTRACT",
                W.ChatBridge._natural_action_proposal,
            ),
            (
                "call-88",
                "orchestrator_mandate_evaluation_adapter.evaluate_explicit_approval",
                "CHAT_BRIDGE",
                "ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER",
                W.ChatBridge._submit_mandate,
            ),
            (
                "call-89",
                "action_execution_eligibility.evaluate_execution_eligibility",
                "CHAT_BRIDGE",
                "ACTION_EXECUTION_ELIGIBILITY",
                W.ChatBridge._submit_mandate,
            ),
            (
                "call-90",
                "action_effect_observer.observe_safe_tool_read_effect",
                "CHAT_BRIDGE",
                "ACTION_EFFECT_OBSERVER",
                W.action_execution_safe_tool_adapter.eligible_tool_finished,
            ),
            (
                "call-91",
                "action_effect_recovery.classify_action_effect_recovery",
                "CHAT_BRIDGE",
                "ACTION_EFFECT_RECOVERY",
                W.action_execution_safe_tool_adapter.eligible_tool_finished,
            ),
            (
                "call-92",
                "action_done_when.evaluate_action_done_when",
                "CHAT_BRIDGE",
                "ACTION_DONE_WHEN",
                W.action_execution_safe_tool_adapter.eligible_tool_finished,
            ),
            (
                "call-93",
                "semantic_closure.evaluate_semantic_closure",
                "ACTION_DONE_WHEN",
                "SEMANTIC_CLOSURE",
                W.action_execution_safe_tool_adapter.action_done_when.evaluate_action_done_when,
            ),
            (
                "call-94",
                "action_task_continuity.capture_action_task",
                "CHAT_BRIDGE",
                "ACTION_TASK_CONTINUITY",
                W.ChatBridge._capture_pending_mandate,
            ),
            (
                "call-95",
                "action_task_continuity.record_action_approval",
                "CHAT_BRIDGE",
                "ACTION_TASK_CONTINUITY",
                W.ChatBridge._submit_mandate,
            ),
            (
                "call-96",
                "action_task_continuity.record_action_dispatch",
                "CHAT_BRIDGE",
                "ACTION_TASK_CONTINUITY",
                W.ChatBridge._submit_eligible_tool,
            ),
            (
                "call-97",
                "action_task_continuity.record_action_completion",
                "CHAT_BRIDGE",
                "ACTION_TASK_CONTINUITY",
                W.ChatBridge._eligible_tool_finished,
            ),
            (
                "call-98",
                "participant_task_receiver.prepare_participant_execution",
                "CHAT_BRIDGE",
                "PARTICIPANT_TASK_RECEIVER",
                W.ChatBridge.submit,
            ),
            (
                "call-99",
                "participant_task_receiver.finalize_participant_response",
                "CHAT_BRIDGE",
                "PARTICIPANT_TASK_RECEIVER",
                W.ChatBridge._finished,
            ),
        )

        def dotted_name(node: runtime_ast.AST) -> str:
            if isinstance(node, runtime_ast.Name):
                return node.id

            if isinstance(node, runtime_ast.Attribute):
                owner = dotted_name(node.value)
                return owner + "." + node.attr if owner else node.attr

            return ""

        for _edge_id, call_name, _source, _target, function in expected:
            source = runtime_textwrap.dedent(
                inspect.getsource(function)
            )
            tree = runtime_ast.parse(source)
            calls = {
                dotted_name(node.func)
                for node in runtime_ast.walk(tree)
                if isinstance(node, runtime_ast.Call)
            }
            self.assertIn(call_name, calls)

        graph = W._build_workbench_machine_graph()
        graph.validate()

        self.assertEqual(len(graph.nodes), 54)
        self.assertEqual(len(graph.edges), 165)

        nodes = {
            node.node_id: node
            for node in graph.nodes
        }
        actual = []

        for edge in sorted(
            (
                edge
                for edge in graph.edges
                if edge.edge_id.startswith("call-")
            ),
            key=lambda item: item.edge_id,
        ):
            source_node = nodes[edge.from_node_id]
            target_node = nodes[edge.to_node_id]

            source_port = next(
                port
                for port in source_node.ports
                if port.port_id == edge.from_port_id
            )
            target_port = next(
                port
                for port in target_node.ports
                if port.port_id == edge.to_port_id
            )

            self.assertEqual(
                source_port.direction,
                W.machine_graph.OUTPUT,
            )
            self.assertEqual(
                target_port.direction,
                W.machine_graph.INPUT,
            )

            for port in (
                source_port,
                target_port,
            ):
                self.assertEqual(
                    port.schema_id,
                    "gg.python-call.v1",
                )
                self.assertEqual(
                    port.channel_class,
                    "EVENT",
                )
                self.assertEqual(
                    port.semantics,
                    "direct-runtime-call",
                )
                self.assertEqual(
                    port.authority_contract,
                    "NONE",
                )

            self.assertEqual(
                source_port.semantic_id,
                target_port.semantic_id,
            )

            call_name = source_port.semantic_id.removeprefix(
                "python-call:"
            )
            actual.append(
                (
                    edge.edge_id,
                    call_name,
                    edge.from_node_id,
                    edge.to_node_id,
                )
            )

        self.assertEqual(
            tuple(actual),
            tuple(
                (
                    edge_id,
                    call_name,
                    source,
                    target,
                )
                for edge_id, call_name, source, target, _function
                in expected
            ),
        )

        process_expected = (
            (
                "proc-01-request",
                "qprocess:control-plane:apply-selfdev:request",
                "CHAT_BRIDGE",
                "CONTROL_PLANE_RUNNER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--apply-selfdev",
            ),
            (
                "proc-01-result",
                "qprocess:control-plane:apply-selfdev:result",
                "CONTROL_PLANE_RUNNER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._control_apply_finished",
            ),
            (
                "proc-02-request",
                "qprocess:local-ai:chat:request",
                "CHAT_BRIDGE",
                "LOCAL_AI_CHAT_RUNNER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--execute-chat",
            ),
            (
                "proc-02-result",
                "qprocess:local-ai:chat:result",
                "LOCAL_AI_CHAT_RUNNER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._finished",
            ),
            (
                "proc-03-request",
                "qprocess:write:execute:request",
                "CHAT_BRIDGE",
                "WRITE_RUNNER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--execute-write",
            ),
            (
                "proc-03-result",
                "qprocess:write:execute:result",
                "WRITE_RUNNER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._write_finished",
            ),
            (
                "proc-04-request",
                "qprocess:safe-tool:execute:request",
                "CHAT_BRIDGE",
                "SAFE_TOOL_RUNNER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--execute-tool",
            ),
            (
                "proc-04-result",
                "qprocess:safe-tool:execute:result",
                "SAFE_TOOL_RUNNER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._tool_finished",
            ),
            (
                "proc-05-request",
                "qprocess:autonomy:execute:request",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTROLLER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--execute",
            ),
            (
                "proc-05-result",
                "qprocess:autonomy:execute:result",
                "AUTONOMY_CONTROLLER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._autonomy_finished",
            ),
            (
                "proc-06-request",
                "qprocess:autonomy:verify-host:request",
                "CHAT_BRIDGE",
                "AUTONOMY_CONTROLLER",
                "gg.qprocess-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:--verify-host",
            ),
            (
                "proc-06-result",
                "qprocess:autonomy:verify-host:result",
                "AUTONOMY_CONTROLLER",
                "CHAT_BRIDGE",
                "gg.qprocess-result.v1",
                "ACTION_RESULT",
                "qprocess-finished:ChatBridge._autonomy_verify_finished",
            ),
            (
                "proc-07-request",
                "subprocess:autonomy:model:execute:request",
                "AUTONOMY_CONTROLLER",
                "AUTONOMY_MODEL_RUNNER",
                "gg.subprocess-request.v1",
                "ACTION_REQUEST",
                "subprocess-run:--execute",
            ),
            (
                "proc-07-result",
                "subprocess:autonomy:model:execute:result",
                "AUTONOMY_MODEL_RUNNER",
                "AUTONOMY_CONTROLLER",
                "gg.subprocess-result.v1",
                "ACTION_RESULT",
                "subprocess-completed:_model_proposal",
            ),
            (
                "proc-08-request",
                "subprocess:autonomy:safe-tool-read:request",
                "AUTONOMY_CONTROLLER",
                "SAFE_TOOL_RUNNER",
                "gg.subprocess-request.v1",
                "ACTION_REQUEST",
                "subprocess-run:--execute-tool",
            ),
            (
                "proc-08-result",
                "subprocess:autonomy:safe-tool-read:result",
                "SAFE_TOOL_RUNNER",
                "AUTONOMY_CONTROLLER",
                "gg.subprocess-result.v1",
                "ACTION_RESULT",
                "subprocess-completed:_safe_tool_read",
            ),
            (
                "proc-09-request",
                "subprocess:autonomy:write-proposal:request",
                "AUTONOMY_CONTROLLER",
                "WRITE_RUNNER",
                "gg.subprocess-request.v1",
                "ACTION_REQUEST",
                "subprocess-run:--execute-write",
            ),
            (
                "proc-09-result",
                "subprocess:autonomy:write-proposal:result",
                "WRITE_RUNNER",
                "AUTONOMY_CONTROLLER",
                "gg.subprocess-result.v1",
                "ACTION_RESULT",
                "subprocess-completed:_write_host_proposal",
            ),
            (
                "proc-10-request",
                "qprocess:live-aid:preflight:request",
                "LIVE_AID_QT_BRIDGE",
                "QML_PREFLIGHT_RUNNER",
                "gg.live-aid.qml-preflight-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:LiveAidQtBridge.preflight",
            ),
            (
                "proc-10-result",
                "qprocess:live-aid:preflight:result",
                "QML_PREFLIGHT_RUNNER",
                "LIVE_AID_QT_BRIDGE",
                "gg.live-aid.qml-preflight-response.v1",
                "ACTION_RESULT",
                "qprocess-finished:LiveAidQtBridge._preflight_finished",
            ),
            (
                "proc-11-request",
                "qprocess:live-aid:repair:request",
                "LIVE_AID_QT_BRIDGE",
                "REPAIR_MODEL_RUNNER",
                "gg.live-aid.repair-model-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:LiveAidQtBridge.requestRepair",
            ),
            (
                "proc-11-result",
                "qprocess:live-aid:repair:result",
                "REPAIR_MODEL_RUNNER",
                "LIVE_AID_QT_BRIDGE",
                "gg.live-aid.repair-model-response.v1",
                "ACTION_RESULT",
                "qprocess-finished:LiveAidQtBridge._repair_finished",
            ),
            (
                "proc-12-event",
                "qprocess:live-aid:post-draft:event",
                "POST_DRAFT_PROCESS_RUNNER",
                "LIVE_AID_QT_BRIDGE",
                "gg.live-aid.post-draft-process-event.v1",
                "EVENT",
                "qprocess-ready-read:LiveAidQtBridge._post_draft_ready_read",
            ),
            (
                "proc-12-request",
                "qprocess:live-aid:post-draft:request",
                "LIVE_AID_QT_BRIDGE",
                "POST_DRAFT_PROCESS_RUNNER",
                "gg.live-aid.post-draft-process-request.v1",
                "ACTION_REQUEST",
                "qprocess-launch:LiveAidQtBridge.runPostDraftRepair",
            ),
            (
                "proc-12-result",
                "qprocess:live-aid:post-draft:result",
                "POST_DRAFT_PROCESS_RUNNER",
                "LIVE_AID_QT_BRIDGE",
                "gg.live-aid.post-draft-process-response.v1",
                "ACTION_RESULT",
                "qprocess-finished:LiveAidQtBridge._post_draft_finished",
            ),
            (
                "proc-13-request",
                "subprocess:live-aid:post-draft-preflight:request",
                "POST_DRAFT_QML_EXECUTOR",
                "QML_PREFLIGHT_RUNNER",
                "gg.live-aid.qml-preflight-request.v1",
                "ACTION_REQUEST",
                "subprocess-run:PostDraftQmlExecutor._invoke_runner:preflight",
            ),
            (
                "proc-13-result",
                "subprocess:live-aid:post-draft-preflight:result",
                "QML_PREFLIGHT_RUNNER",
                "POST_DRAFT_QML_EXECUTOR",
                "gg.live-aid.qml-preflight-response.v1",
                "ACTION_RESULT",
                "subprocess-completed:PostDraftQmlExecutor._execute_preflight",
            ),
            (
                "proc-14-request",
                "subprocess:live-aid:post-draft-repair:request",
                "POST_DRAFT_QML_EXECUTOR",
                "REPAIR_MODEL_RUNNER",
                "gg.live-aid.repair-model-request.v1",
                "ACTION_REQUEST",
                "subprocess-run:PostDraftQmlExecutor._invoke_runner:repair",
            ),
            (
                "proc-14-result",
                "subprocess:live-aid:post-draft-repair:result",
                "REPAIR_MODEL_RUNNER",
                "POST_DRAFT_QML_EXECUTOR",
                "gg.live-aid.repair-model-response.v1",
                "ACTION_RESULT",
                "subprocess-completed:PostDraftQmlExecutor._execute_repair",
            ),
        )

        process_actual = []

        for edge in sorted(
            (
                edge
                for edge in graph.edges
                if edge.edge_id.startswith("proc-")
            ),
            key=lambda item: item.edge_id,
        ):
            source_node = nodes[edge.from_node_id]
            target_node = nodes[edge.to_node_id]

            source_port = next(
                port
                for port in source_node.ports
                if port.port_id == edge.from_port_id
            )
            target_port = next(
                port
                for port in target_node.ports
                if port.port_id == edge.to_port_id
            )

            self.assertEqual(
                source_port.direction,
                W.machine_graph.OUTPUT,
            )
            self.assertEqual(
                target_port.direction,
                W.machine_graph.INPUT,
            )
            self.assertEqual(
                source_port.schema_id,
                target_port.schema_id,
            )
            self.assertEqual(
                source_port.semantic_id,
                target_port.semantic_id,
            )
            self.assertEqual(
                source_port.channel_class,
                target_port.channel_class,
            )
            self.assertEqual(
                source_port.semantics,
                target_port.semantics,
            )
            self.assertEqual(
                source_port.authority_contract,
                "NONE",
            )
            self.assertEqual(
                target_port.authority_contract,
                "NONE",
            )

            process_actual.append(
                (
                    edge.edge_id,
                    source_port.semantic_id,
                    edge.from_node_id,
                    edge.to_node_id,
                    source_port.schema_id,
                    source_port.channel_class,
                    source_port.semantics,
                )
            )

        self.assertEqual(
            tuple(process_actual),
            process_expected,
        )

        process_boundaries = (
            (
                W.ChatBridge._start_control_apply,
                "CONTROL_APPLY_RUNNER_PATH",
                "--apply-selfdev",
                "_control_apply_finished",
            ),
            (
                W.ChatBridge.submit,
                "CHAT_RUNNER_PATH",
                "--execute-chat",
                "_finished",
            ),
            (
                W.ChatBridge._submit_write,
                "WRITE_RUNNER_PATH",
                "--execute-write",
                "_write_finished",
            ),
            (
                W.ChatBridge._submit_tool,
                "SAFE_TOOL_RUNNER_PATH",
                "--execute-tool",
                "_tool_finished",
            ),
            (
                W.ChatBridge._submit_autonomy,
                "AUTONOMY_CONTROLLER_PATH",
                "--execute",
                "_autonomy_finished",
            ),
            (
                W.ChatBridge._resume_autonomy_verify,
                "AUTONOMY_CONTROLLER_PATH",
                "--verify-host",
                "_autonomy_verify_finished",
            ),
        )

        for (
            launch_function,
            runner_path_token,
            mode_token,
            callback_name,
        ) in process_boundaries:
            source = runtime_textwrap.dedent(
                inspect.getsource(launch_function)
            )
            tree = runtime_ast.parse(source)

            self.assertIn(
                runner_path_token,
                source,
            )
            self.assertIn(
                mode_token,
                source,
            )

            finish_connections = [
                node
                for node in runtime_ast.walk(tree)
                if (
                    isinstance(node, runtime_ast.Call)
                    and dotted_name(node.func)
                    == "process.finished.connect"
                )
            ]

            self.assertEqual(
                len(finish_connections),
                1,
            )
            self.assertEqual(
                dotted_name(
                    finish_connections[0].args[0]
                ),
                "self." + callback_name,
            )

        synchronous_subprocess_boundaries = (
            (
                A._model_proposal,
                "AUTONOMY_MODEL_RUNNER",
                "--execute",
                "autonomy-semantic-proposal.json",
            ),
            (
                A._safe_tool_read,
                "SAFE_TOOL_RUNNER",
                "--execute-tool",
                "response.json",
            ),
            (
                A._write_host_proposal,
                "WRITE_RUNNER",
                "--execute-write",
                "response-propose.json",
            ),
        )

        for (
            helper_function,
            runner_token,
            mode_token,
            result_token,
        ) in synchronous_subprocess_boundaries:
            source = runtime_textwrap.dedent(
                inspect.getsource(helper_function)
            )
            tree = runtime_ast.parse(source)

            self.assertIn(runner_token, source)
            self.assertIn(mode_token, source)
            self.assertIn(result_token, source)

            run_calls = [
                node
                for node in runtime_ast.walk(tree)
                if (
                    isinstance(node, runtime_ast.Call)
                    and dotted_name(node.func) == "_run"
                )
            ]

            self.assertEqual(len(run_calls), 1)

        runtime_expected_operations = (
            (
                "runtime-01",
                "local-ai:image-inspect",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-02",
                "local-ai:container-inventory",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-03",
                "local-ai:volume-inventory",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-04",
                "local-ai:container-exists",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-05",
                "local-ai:help-run",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-06",
                "local-ai:inference-run",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-07",
                "local-ai:container-remove",
                "LOCAL_AI_MODEL_RUNNER",
                "PODMAN_LOCAL_AI_RUNTIME",
            ),
            (
                "runtime-08",
                "safe-tool:image-inspect",
                "SAFE_TOOL_RUNNER",
                "PODMAN_SAFE_TOOL_RUNTIME",
            ),
            (
                "runtime-09",
                "safe-tool:container-create",
                "SAFE_TOOL_RUNNER",
                "PODMAN_SAFE_TOOL_RUNTIME",
            ),
            (
                "runtime-10",
                "safe-tool:container-inspect",
                "SAFE_TOOL_RUNNER",
                "PODMAN_SAFE_TOOL_RUNTIME",
            ),
            (
                "runtime-11",
                "safe-tool:container-start-attach",
                "SAFE_TOOL_RUNNER",
                "PODMAN_SAFE_TOOL_RUNTIME",
            ),
            (
                "runtime-12",
                "safe-tool:container-remove",
                "SAFE_TOOL_RUNNER",
                "PODMAN_SAFE_TOOL_RUNTIME",
            ),
            (
                "runtime-13",
                "write-qml:image-inspect",
                "WRITE_RUNNER",
                "PODMAN_QML_GATE_RUNTIME",
            ),
            (
                "runtime-14",
                "write-qml:gate-run",
                "WRITE_RUNNER",
                "PODMAN_QML_GATE_RUNTIME",
            ),
        )

        for (
            operation_id,
            operation_name,
            caller_node_id,
            runtime_node_id,
        ) in runtime_expected_operations:
            request = next(
                edge
                for edge in graph.edges
                if edge.edge_id
                == operation_id + "-request"
            )

            result = next(
                edge
                for edge in graph.edges
                if edge.edge_id
                == operation_id + "-result"
            )

            self.assertEqual(
                request.from_node_id,
                caller_node_id,
            )
            self.assertEqual(
                request.to_node_id,
                runtime_node_id,
            )
            self.assertEqual(
                result.from_node_id,
                runtime_node_id,
            )
            self.assertEqual(
                result.to_node_id,
                caller_node_id,
            )

            request_source = next(
                port
                for port in nodes[
                    request.from_node_id
                ].ports
                if port.port_id
                == request.from_port_id
            )
            request_target = next(
                port
                for port in nodes[
                    request.to_node_id
                ].ports
                if port.port_id
                == request.to_port_id
            )
            result_source = next(
                port
                for port in nodes[
                    result.from_node_id
                ].ports
                if port.port_id
                == result.from_port_id
            )
            result_target = next(
                port
                for port in nodes[
                    result.to_node_id
                ].ports
                if port.port_id
                == result.to_port_id
            )

            for port in (
                request_source,
                request_target,
            ):
                self.assertEqual(
                    port.schema_id,
                    "gg.podman-operation-request.v1",
                )
                self.assertEqual(
                    port.channel_class,
                    "ACTION_REQUEST",
                )
                self.assertEqual(
                    port.semantics,
                    "podman-operation:"
                    + operation_name,
                )
                self.assertEqual(
                    port.authority_contract,
                    "NONE",
                )

            for port in (
                result_source,
                result_target,
            ):
                self.assertEqual(
                    port.schema_id,
                    "gg.podman-operation-result.v1",
                )
                self.assertEqual(
                    port.channel_class,
                    "ACTION_RESULT",
                )
                self.assertEqual(
                    port.semantics,
                    "podman-operation:"
                    + operation_name,
                )
                self.assertEqual(
                    port.authority_contract,
                    "NONE",
                )

            self.assertEqual(
                request_source.semantic_id,
                "podman:"
                + operation_name
                + ":request",
            )
            self.assertEqual(
                result_source.semantic_id,
                "podman:"
                + operation_name
                + ":result",
            )
            self.assertEqual(
                nodes[
                    runtime_node_id
                ].contract_version,
                "runtime-podman-v1",
            )

        runtime_source_contacts = (
            (
                LM.inspect_image,
                (
                    "podman",
                    "image",
                    "inspect",
                    "RUNTIME_IMAGE",
                ),
            ),
            (
                LM.require_podman_empty,
                (
                    "podman",
                    "ps",
                    "-aq",
                ),
            ),
            (
                LM.require_podman_empty,
                (
                    "podman",
                    "volume",
                    "ls",
                    "-q",
                ),
            ),
            (
                LM.container_exists,
                (
                    "podman",
                    "container",
                    "exists",
                ),
            ),
            (
                LM.execute_synthetic,
                (
                    "run_named_container(help_argv, help_name, 60)",
                ),
            ),
            (
                LM.execute_synthetic,
                (
                    "run_named_container(infer_argv, infer_name, 600)",
                ),
            ),
            (
                LM.remove_owned_container,
                (
                    "podman",
                    "rm",
                    "-f",
                ),
            ),
            (
                ST._sandbox_profile,
                (
                    "podman",
                    "image",
                    "inspect",
                    "IMAGE_REF",
                ),
            ),
            (
                ST._sandbox_profile,
                (
                    "create_argv",
                    "podman",
                    "create",
                ),
            ),
            (
                ST._inspect_created_container,
                (
                    "podman",
                    "inspect",
                    "name",
                ),
            ),
            (
                ST._sandbox_profile,
                (
                    "podman",
                    "start",
                    "--attach",
                ),
            ),
            (
                ST._sandbox_profile,
                (
                    "podman",
                    "rm",
                    "-f",
                ),
            ),
            (
                WR._canonical_qml_image_id,
                (
                    "podman",
                    "image",
                    "inspect",
                    "QML_IMAGE_REF",
                ),
            ),
            (
                WR._qml_gate,
                (
                    "podman",
                    "run",
                    "--network=none",
                    "QML_IMAGE_ID",
                ),
            ),
        )

        for function, required_tokens in runtime_source_contacts:
            source = runtime_textwrap.dedent(
                inspect.getsource(function)
            )

            normalized = runtime_ast.unparse(
                runtime_ast.parse(source)
            )

            for token in required_tokens:
                self.assertIn(
                    token,
                    normalized,
                )

        effect_expected = (
            (
                "effect-01",
                "write:approve-apply",
                "WRITE_RUNNER",
                "WRITE_EFFECT_BOUNDARY",
                "atomic-replace:approve-apply",
            ),
            (
                "effect-02",
                "write:approve-automatic-rollback",
                "WRITE_RUNNER",
                "WRITE_EFFECT_BOUNDARY",
                "atomic-replace:approve-automatic-rollback",
            ),
            (
                "effect-03",
                "write:rollback-restore",
                "WRITE_RUNNER",
                "WRITE_EFFECT_BOUNDARY",
                "atomic-replace:rollback-restore",
            ),
        )

        effect_actual = []

        for edge in sorted(
            (
                edge
                for edge in graph.edges
                if edge.edge_id.startswith("effect-")
            ),
            key=lambda item: item.edge_id,
        ):
            source_node = nodes[
                edge.from_node_id
            ]
            target_node = nodes[
                edge.to_node_id
            ]

            source_port = next(
                port
                for port in source_node.ports
                if port.port_id == edge.from_port_id
            )
            target_port = next(
                port
                for port in target_node.ports
                if port.port_id == edge.to_port_id
            )

            self.assertEqual(
                source_port.direction,
                W.machine_graph.OUTPUT,
            )
            self.assertEqual(
                target_port.direction,
                W.machine_graph.INPUT,
            )

            for port in (
                source_port,
                target_port,
            ):
                self.assertEqual(
                    port.schema_id,
                    "gg.write-effect-request.v1",
                )
                self.assertEqual(
                    port.channel_class,
                    "ACTION_REQUEST",
                )
                self.assertEqual(
                    port.authority_contract,
                    W.write_contract.AUTHORITY,
                )

            self.assertEqual(
                source_port.semantic_id,
                target_port.semantic_id,
            )
            self.assertEqual(
                source_port.semantics,
                target_port.semantics,
            )

            effect_actual.append(
                (
                    edge.edge_id,
                    source_port.semantic_id.removeprefix(
                        "write-effect:"
                    ),
                    edge.from_node_id,
                    edge.to_node_id,
                    source_port.semantics,
                )
            )

        self.assertEqual(
            tuple(effect_actual),
            effect_expected,
        )

        self.assertEqual(
            nodes["WRITE_EFFECT_BOUNDARY"].implementation_id,
            "backend.write_runner._atomic_replace",
        )
        self.assertEqual(
            nodes["WRITE_EFFECT_BOUNDARY"].contract_version,
            "runtime-effect-v1",
        )
        self.assertEqual(
            nodes["WRITE_EFFECT_BOUNDARY"].authority_contract,
            W.write_contract.AUTHORITY,
        )

        self.assertEqual(
            W.write_contract.AUTHORITY,
            "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        )
        self.assertEqual(
            W.write_contract.NETWORK_AUTHORITY,
            "NONE",
        )
        self.assertEqual(
            W.write_contract.GENERAL_ACTION_AUTHORITY,
            "NONE",
        )
        self.assertEqual(
            W.write_contract.MODEL_AUTONOMOUS_WRITE_INVOCATION,
            "DISABLED_V1",
        )

        approve_source = runtime_ast.unparse(
            runtime_ast.parse(
                runtime_textwrap.dedent(
                    inspect.getsource(
                        WR._approve
                    )
                )
            )
        )
        rollback_source = runtime_ast.unparse(
            runtime_ast.parse(
                runtime_textwrap.dedent(
                    inspect.getsource(
                        WR._rollback
                    )
                )
            )
        )
        reject_source = runtime_ast.unparse(
            runtime_ast.parse(
                runtime_textwrap.dedent(
                    inspect.getsource(
                        WR._reject
                    )
                )
            )
        )
        atomic_source = runtime_ast.unparse(
            runtime_ast.parse(
                runtime_textwrap.dedent(
                    inspect.getsource(
                        WR._atomic_replace
                    )
                )
            )
        )

        self.assertEqual(
            approve_source.count(
                "_atomic_replace(candidate)"
            ),
            1,
        )
        self.assertEqual(
            approve_source.count(
                "_atomic_replace(before)"
            ),
            1,
        )
        self.assertEqual(
            rollback_source.count(
                "_atomic_replace(before)"
            ),
            1,
        )
        self.assertNotIn(
            "_atomic_replace(",
            reject_source,
        )
        self.assertIn(
            "os.replace(temporary, target)",
            atomic_source,
        )


    def test_disabled_call_04_to_06_block_cold_construction_and_inverse_restores(
        self,
    ) -> None:
        from unittest import mock

        import main as W
        from backend import capability_registry as CREG
        from backend import solver_router as S

        expected_failure_counts = {
            "call-04":
                (0, 0, 0),

            "call-05":
                (1, 0, 0),

            "call-06":
                (1, 1, 0),
        }

        expected_restore_counts = {
            "call-04":
                (1, 1, 1),

            "call-05":
                (2, 1, 1),

            "call-06":
                (2, 2, 1),
        }

        for edge_id in (
            "call-04",
            "call-05",
            "call-06",
        ):
            with self.subTest(
                edge_id=edge_id,
            ):
                with (
                    mock.patch.object(
                        W.resident_state.WorkbenchResidentInformationState,
                        "bootstrap_workbench_sources",
                        return_value=object(),
                    ),
                    mock.patch.object(
                        W.control_contract,
                        "TaskLedger",
                        return_value=object(),
                    ),
                    mock.patch.object(
                        W.ChatBridge,
                        "_recover_selfdev_records",
                        return_value=None,
                    ),
                    mock.patch.object(
                        W.ChatBridge,
                        "_block_unrecoverable_autonomy_records",
                        return_value=None,
                    ),
                ):
                    bridge = W.ChatBridge(
                        W.QObject()
                    )

                before = (
                    bridge.machine_graph_sha256()
                )

                disabled = (
                    bridge.apply_machine_graph_patch(
                        W.machine_graph.GraphPatch(
                            base_graph_sha256=before,
                            operations=(
                                W.machine_graph.GraphOperation(
                                    op=(
                                        W.machine_graph.OP_DISABLE_EDGE
                                    ),
                                    edge_id=edge_id,
                                ),
                            ),
                        )
                    )
                )

                registry = object()
                router = object()
                laser = object()

                with (
                    mock.patch.object(
                        CREG.CapabilityRegistry,
                        "load",
                        return_value=registry,
                    ) as load_mock,
                    mock.patch.object(
                        S,
                        "SolverRouter",
                        return_value=router,
                    ) as router_mock,
                    mock.patch.object(
                        S,
                        "LaserFocusCache",
                        return_value=laser,
                    ) as laser_mock,
                ):
                    bridge._ensure_natural_intent_laser()

                    self.assertEqual(
                        expected_failure_counts[
                            edge_id
                        ],
                        (
                            load_mock.call_count,
                            router_mock.call_count,
                            laser_mock.call_count,
                        ),
                    )

                    self.assertIsNone(
                        bridge._intent_laser
                    )

                    self.assertEqual(
                        "",
                        bridge._intent_router_manifest_sha256,
                    )

                    self.assertEqual(
                        (
                            "MachineGraphError:"
                            "MACHINE_GRAPH_EDGE_DISABLED:"
                            + edge_id
                        ),
                        bridge._intent_router_error,
                    )

                    restored = (
                        bridge.apply_machine_graph_patch(
                            disabled.inverse_patch
                        )
                    )

                    self.assertEqual(
                        before,
                        restored.after_graph_sha256,
                    )

                    bridge._ensure_natural_intent_laser()

                    self.assertEqual(
                        expected_restore_counts[
                            edge_id
                        ],
                        (
                            load_mock.call_count,
                            router_mock.call_count,
                            laser_mock.call_count,
                        ),
                    )

                    self.assertIs(
                        laser,
                        bridge._intent_laser,
                    )

                    self.assertEqual(
                        64,
                        len(
                            bridge._intent_router_manifest_sha256
                        ),
                    )

                    self.assertEqual(
                        "",
                        bridge._intent_router_error,
                    )

                self.assertEqual(
                    before,
                    bridge.machine_graph_sha256(),
                )


    def test_constructor_edge_disable_preserves_valid_cached_laser(
        self,
    ) -> None:
        from unittest import mock

        import main as W
        from backend import capability_registry as CREG
        from backend import solver_router as S

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(
                W.QObject()
            )

        registry = object()
        router = object()
        laser = object()

        with (
            mock.patch.object(
                CREG.CapabilityRegistry,
                "load",
                return_value=registry,
            ) as load_mock,
            mock.patch.object(
                S,
                "SolverRouter",
                return_value=router,
            ) as router_mock,
            mock.patch.object(
                S,
                "LaserFocusCache",
                return_value=laser,
            ) as laser_mock,
        ):
            bridge._ensure_natural_intent_laser()

            self.assertEqual(
                (1, 1, 1),
                (
                    load_mock.call_count,
                    router_mock.call_count,
                    laser_mock.call_count,
                ),
            )

            self.assertIs(
                laser,
                bridge._intent_laser,
            )

            initial_sha = (
                bridge.machine_graph_sha256()
            )

            for edge_id in (
                "call-04",
                "call-05",
                "call-06",
            ):
                with self.subTest(
                    edge_id=edge_id,
                ):
                    before = (
                        bridge.machine_graph_sha256()
                    )

                    disabled = (
                        bridge.apply_machine_graph_patch(
                            W.machine_graph.GraphPatch(
                                base_graph_sha256=before,
                                operations=(
                                    W.machine_graph.GraphOperation(
                                        op=(
                                            W.machine_graph.OP_DISABLE_EDGE
                                        ),
                                        edge_id=edge_id,
                                    ),
                                ),
                            )
                        )
                    )

                    before_counts = (
                        load_mock.call_count,
                        router_mock.call_count,
                        laser_mock.call_count,
                    )

                    bridge._ensure_natural_intent_laser()

                    self.assertEqual(
                        before_counts,
                        (
                            load_mock.call_count,
                            router_mock.call_count,
                            laser_mock.call_count,
                        ),
                    )

                    self.assertIs(
                        laser,
                        bridge._intent_laser,
                    )

                    restored = (
                        bridge.apply_machine_graph_patch(
                            disabled.inverse_patch
                        )
                    )

                    self.assertEqual(
                        before,
                        restored.after_graph_sha256,
                    )

            self.assertEqual(
                initial_sha,
                bridge.machine_graph_sha256(),
            )


    def test_disabled_call_01_blocks_context_validation_and_inverse_restores(
        self,
    ) -> None:
        from unittest import mock

        import main as W
        from backend import context_resolver as CRES

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        before = bridge.machine_graph_sha256()

        disabled = bridge.apply_machine_graph_patch(
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=W.machine_graph.OP_DISABLE_EDGE,
                        edge_id="call-01",
                    ),
                ),
            )
        )

        with mock.patch.object(
            CRES,
            "validate_snapshot_json",
            return_value="C8A-CANONICAL",
        ) as validate_mock:
            bridge._context_snapshot_json = "OLD"
            bridge._context_snapshot_error = ""

            bridge.syncContextSnapshot("RAW")

            self.assertEqual(
                0,
                validate_mock.call_count,
            )
            self.assertEqual(
                "",
                bridge._context_snapshot_json,
            )
            self.assertEqual(
                "MACHINE_GRAPH_EDGE_DISABLED:call-01",
                bridge._context_snapshot_error,
            )

            restored = bridge.apply_machine_graph_patch(
                disabled.inverse_patch
            )

            self.assertEqual(
                before,
                restored.after_graph_sha256,
            )

            bridge.syncContextSnapshot("RAW")

            self.assertEqual(
                1,
                validate_mock.call_count,
            )
            self.assertEqual(
                "C8A-CANONICAL",
                bridge._context_snapshot_json,
            )
            self.assertEqual(
                "",
                bridge._context_snapshot_error,
            )


    def test_disabled_call_02_blocks_context_resolution_and_inverse_restores(
        self,
    ) -> None:
        from unittest import mock

        import main as W
        from backend import context_resolver as CRES

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        bridge._context_snapshot_json = "C8A-SNAPSHOT"

        before = bridge.machine_graph_sha256()

        disabled = bridge.apply_machine_graph_patch(
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=W.machine_graph.OP_DISABLE_EDGE,
                        edge_id="call-02",
                    ),
                ),
            )
        )

        plan = {
            "primaryObjectId":
                "object-c8a-primary",
            "objectIds": [
                "object-c8a-primary",
            ],
        }

        primary_context = {
            "source_path":
                "/tmp/c8a-primary.py",
            "sha256":
                "a" * 64,
            "object_id":
                "object-c8a-primary",
        }

        with (
            mock.patch.object(
                CRES,
                "resolve_snapshot",
                return_value=plan,
            ) as resolve_mock,
            mock.patch.object(
                W,
                "build_effective_prompt",
                return_value=(
                    "C8A-PROMPT",
                    primary_context,
                ),
            ),
            mock.patch.object(
                CRES,
                "render_extension",
                return_value="\nC8A-EXTENSION",
            ),
        ):
            with self.assertRaisesRegex(
                W.machine_graph.MachineGraphError,
                "MACHINE_GRAPH_EDGE_DISABLED:call-02",
            ):
                bridge._resolved_chat_context(
                    "Inspect",
                    "@current",
                    "object-c8a-primary",
                )

            self.assertEqual(
                0,
                resolve_mock.call_count,
            )

            restored = bridge.apply_machine_graph_patch(
                disabled.inverse_patch
            )

            self.assertEqual(
                before,
                restored.after_graph_sha256,
            )

            effective, context = (
                bridge._resolved_chat_context(
                    "Inspect",
                    "@current",
                    "object-c8a-primary",
                )
            )

            self.assertEqual(
                1,
                resolve_mock.call_count,
            )
            self.assertEqual(
                "C8A-PROMPT\nC8A-EXTENSION",
                effective,
            )
            self.assertIs(
                primary_context,
                context,
            )


    def test_disabled_call_03_blocks_context_render_and_inverse_restores(
        self,
    ) -> None:
        from unittest import mock

        import main as W
        from backend import context_resolver as CRES

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        bridge._context_snapshot_json = "C8A-SNAPSHOT"

        before = bridge.machine_graph_sha256()

        disabled = bridge.apply_machine_graph_patch(
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=W.machine_graph.OP_DISABLE_EDGE,
                        edge_id="call-03",
                    ),
                ),
            )
        )

        plan = {
            "primaryObjectId":
                "object-c8a-primary",
            "objectIds": [
                "object-c8a-primary",
            ],
        }

        primary_context = {
            "source_path":
                "/tmp/c8a-primary.py",
            "sha256":
                "a" * 64,
            "object_id":
                "object-c8a-primary",
        }

        with (
            mock.patch.object(
                CRES,
                "resolve_snapshot",
                return_value=plan,
            ) as resolve_mock,
            mock.patch.object(
                W,
                "build_effective_prompt",
                return_value=(
                    "C8A-PROMPT",
                    primary_context,
                ),
            ),
            mock.patch.object(
                CRES,
                "render_extension",
                return_value="\nC8A-EXTENSION",
            ) as render_mock,
        ):
            with self.assertRaisesRegex(
                W.machine_graph.MachineGraphError,
                "MACHINE_GRAPH_EDGE_DISABLED:call-03",
            ):
                bridge._resolved_chat_context(
                    "Inspect",
                    "@current",
                    "object-c8a-primary",
                )

            self.assertEqual(
                1,
                resolve_mock.call_count,
            )
            self.assertEqual(
                0,
                render_mock.call_count,
            )

            restored = bridge.apply_machine_graph_patch(
                disabled.inverse_patch
            )

            self.assertEqual(
                before,
                restored.after_graph_sha256,
            )

            effective, context = (
                bridge._resolved_chat_context(
                    "Inspect",
                    "@current",
                    "object-c8a-primary",
                )
            )

            self.assertEqual(
                2,
                resolve_mock.call_count,
            )
            self.assertEqual(
                1,
                render_mock.call_count,
            )
            self.assertEqual(
                "C8A-PROMPT\nC8A-EXTENSION",
                effective,
            )
            self.assertIs(
                primary_context,
                context,
            )

    def test_chatbridge_owns_one_machine_graph_with_read_only_snapshot(self) -> None:
        from unittest import mock

        import main as W

        resident_owner = object()
        ledger_owner = object()

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=resident_owner,
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=ledger_owner,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        graph = bridge._machine_graph
        self.assertIsInstance(
            graph,
            W.machine_graph.MachineGraph,
        )
        self.assertIs(
            bridge._resident_information_state,
            resident_owner,
        )
        self.assertIs(
            bridge._task_ledger,
            ledger_owner,
        )

        graph_sha256 = graph.graph_sha256()
        self.assertEqual(
            bridge.machine_graph_sha256(),
            graph_sha256,
        )

        snapshot = bridge.machine_graph_snapshot()
        self.assertEqual(
            snapshot,
            graph.as_dict(),
        )

        snapshot["schema"] = "mutated-copy"
        self.assertEqual(
            bridge.machine_graph_sha256(),
            graph_sha256,
        )

        self.assertFalse(
            hasattr(
                bridge,
                "set_machine_graph",
            )
        )
        self.assertTrue(
            hasattr(
                bridge,
                "apply_machine_graph_patch",
            )
        )

        effect_port_locations = {
            (
                edge.from_node_id,
                edge.from_port_id,
            )
            for edge in graph.edges
            if edge.edge_id in {
                "effect-01",
                "effect-02",
                "effect-03",
            }
        } | {
            (
                edge.to_node_id,
                edge.to_port_id,
            )
            for edge in graph.edges
            if edge.edge_id in {
                "effect-01",
                "effect-02",
                "effect-03",
            }
        }

        self.assertEqual(
            len(effect_port_locations),
            6,
        )

        for node in graph.nodes:
            expected_node_authority = (
                W.write_contract.AUTHORITY
                if node.node_id == "WRITE_EFFECT_BOUNDARY"
                else "NONE"
            )

            self.assertEqual(
                node.authority_contract,
                expected_node_authority,
            )

            for port in node.ports:
                expected_port_authority = (
                    W.write_contract.AUTHORITY
                    if (
                        node.node_id,
                        port.port_id,
                    )
                    in effect_port_locations
                    else "NONE"
                )

                self.assertEqual(
                    port.authority_contract,
                    expected_port_authority,
                )

    def test_chatbridge_previews_graph_patch_without_mutating_active_graph(
        self,
    ) -> None:
        from unittest import mock

        import main as W

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        before = bridge.machine_graph_sha256()

        patch = W.machine_graph.GraphPatch(
            base_graph_sha256=before,
            operations=(
                W.machine_graph.GraphOperation(
                    op=W.machine_graph.OP_DISABLE_EDGE,
                    edge_id="call-01",
                ),
            ),
        )

        result = bridge.preview_machine_graph_patch(
            patch
        )

        self.assertEqual(
            before,
            result.before_graph_sha256,
        )
        self.assertNotEqual(
            before,
            result.after_graph_sha256,
        )
        self.assertEqual(
            before,
            bridge.machine_graph_sha256(),
        )
        self.assertEqual(
            165,
            len(
                bridge._machine_graph.edges
            ),
        )

        candidate_edge = next(
            edge
            for edge in result.graph.edges
            if edge.edge_id == "call-01"
        )

        self.assertFalse(
            candidate_edge.enabled
        )

        self.assertEqual(
            "NONE",
            result.action_authority,
        )
        self.assertEqual(
            "NONE",
            result.persistent_write,
        )
        self.assertFalse(
            result.model_inference
        )

        restored = W.machine_graph.apply_patch(
            result.graph,
            result.inverse_patch,
        )

        self.assertEqual(
            before,
            restored.after_graph_sha256,
        )
        self.assertEqual(
            before,
            restored.graph.graph_sha256(),
        )
        self.assertEqual(
            before,
            bridge.machine_graph_sha256(),
        )

    def test_chatbridge_patch_preview_rejects_stale_base_without_mutation(
        self,
    ) -> None:
        from unittest import mock

        import main as W

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        before = bridge.machine_graph_sha256()

        stale_base = (
            "0" * 64
            if before != "0" * 64
            else "1" * 64
        )

        patch = W.machine_graph.GraphPatch(
            base_graph_sha256=stale_base,
            operations=(
                W.machine_graph.GraphOperation(
                    op=W.machine_graph.OP_DISABLE_EDGE,
                    edge_id="call-01",
                ),
            ),
        )

        with self.assertRaises(
            W.machine_graph.MachineGraphError
        ):
            bridge.preview_machine_graph_patch(
                patch
            )

        self.assertEqual(
            before,
            bridge.machine_graph_sha256(),
        )

    def test_chatbridge_patch_preview_has_bounded_pure_effect_surface(
        self,
    ) -> None:
        import ast as runtime_ast
        import inspect
        import textwrap as runtime_textwrap

        import main as W

        source = runtime_textwrap.dedent(
            inspect.getsource(
                W.ChatBridge.preview_machine_graph_patch
            )
        )

        tree = runtime_ast.parse(
            source
        )

        def dotted(
            node: runtime_ast.AST,
        ) -> str:
            if isinstance(
                node,
                runtime_ast.Name,
            ):
                return node.id

            if isinstance(
                node,
                runtime_ast.Attribute,
            ):
                owner = dotted(
                    node.value
                )

                return (
                    owner
                    + "."
                    + node.attr
                    if owner
                    else node.attr
                )

            return ""

        calls = {
            dotted(
                node.func
            )
            for node in runtime_ast.walk(
                tree
            )
            if isinstance(
                node,
                runtime_ast.Call,
            )
        }

        self.assertIn(
            "machine_graph.apply_patch",
            calls,
        )
        self.assertIn(
            "result.validate",
            calls,
        )
        self.assertIn(
            "self._machine_graph.graph_sha256",
            calls,
        )

        forbidden_calls = {
            "open",
            "os.open",
            "subprocess.run",
            "subprocess.Popen",
            "QProcess",
        }

        self.assertFalse(
            calls
            & forbidden_calls
        )

        assignments_to_active_graph = 0

        for node in runtime_ast.walk(
            tree
        ):
            targets = []

            if isinstance(
                node,
                runtime_ast.Assign,
            ):
                targets.extend(
                    node.targets
                )

            elif isinstance(
                node,
                runtime_ast.AnnAssign,
            ):
                targets.append(
                    node.target
                )

            for target in targets:
                if (
                    isinstance(
                        target,
                        runtime_ast.Attribute,
                    )
                    and isinstance(
                        target.value,
                        runtime_ast.Name,
                    )
                    and target.value.id == "self"
                    and target.attr == "_machine_graph"
                ):
                    assignments_to_active_graph += 1

        self.assertEqual(
            0,
            assignments_to_active_graph,
        )

    def test_chatbridge_applies_call_07_runtime_graph_patch_transactionally(
        self,
    ) -> None:
        from unittest import mock

        import main as W

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        before = bridge.machine_graph_sha256()

        patch = W.machine_graph.GraphPatch(
            base_graph_sha256=before,
            operations=(
                W.machine_graph.GraphOperation(
                    op=W.machine_graph.OP_DISABLE_EDGE,
                    edge_id="call-07",
                ),
            ),
        )

        result = bridge.apply_machine_graph_patch(
            patch
        )

        self.assertEqual(
            before,
            result.before_graph_sha256,
        )
        self.assertNotEqual(
            before,
            result.after_graph_sha256,
        )
        self.assertEqual(
            result.after_graph_sha256,
            bridge.machine_graph_sha256(),
        )
        self.assertFalse(
            bridge._machine_graph_edge_enabled(
                "call-07"
            )
        )
        self.assertEqual(
            "NONE",
            result.action_authority,
        )
        self.assertEqual(
            "NONE",
            result.persistent_write,
        )
        self.assertFalse(
            result.model_inference
        )

        restored = bridge.apply_machine_graph_patch(
            result.inverse_patch
        )

        self.assertEqual(
            before,
            restored.after_graph_sha256,
        )
        self.assertEqual(
            before,
            bridge.machine_graph_sha256(),
        )
        self.assertTrue(
            bridge._machine_graph_edge_enabled(
                "call-07"
            )
        )

    def test_disabled_call_07_blocks_real_laser_bind_and_inverse_restores(
        self,
    ) -> None:
        from types import SimpleNamespace
        from unittest import mock

        import main as W

        class FakeLaser:
            def __init__(
                self,
            ) -> None:
                self.bind_calls = 0
                self.lookup_calls = 0
                self.decision = SimpleNamespace(
                    automatic_model_dispatch=False,
                    registered_capability_execution=False,
                )

            def bind(
                self,
                context,
            ):
                self.bind_calls += 1
                return SimpleNamespace(
                    handle_id="fake-handle",
                )

            def lookup(
                self,
                handle_id,
            ):
                self.lookup_calls += 1
                self.asserted_handle_id = handle_id
                return SimpleNamespace(
                    route=self.decision,
                )

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        laser = FakeLaser()
        bridge._intent_laser = laser

        workspace_context = {
            "source_path": "/tmp/example.py",
            "sha256": "a" * 64,
            "object_id": "workspace-object-1",
        }

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            first_decision, first_error = (
                bridge._natural_intent_route(
                    "route this",
                    workspace_context,
                    "",
                )
            )

        self.assertIs(
            first_decision,
            laser.decision,
        )
        self.assertEqual(
            "",
            first_error,
        )
        self.assertEqual(
            1,
            laser.bind_calls,
        )
        self.assertEqual(
            1,
            laser.lookup_calls,
        )
        self.assertEqual(
            "fake-handle",
            laser.asserted_handle_id,
        )

        before = bridge.machine_graph_sha256()

        disabled = bridge.apply_machine_graph_patch(
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=W.machine_graph.OP_DISABLE_EDGE,
                        edge_id="call-07",
                    ),
                ),
            )
        )

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            blocked_decision, blocked_error = (
                bridge._natural_intent_route(
                    "route this",
                    workspace_context,
                    "",
                )
            )

        self.assertIsNone(
            blocked_decision
        )
        self.assertEqual(
            "MACHINE_GRAPH_EDGE_DISABLED:call-07",
            blocked_error,
        )
        self.assertEqual(
            1,
            laser.bind_calls,
        )
        self.assertEqual(
            1,
            laser.lookup_calls,
        )

        restored = bridge.apply_machine_graph_patch(
            disabled.inverse_patch
        )

        self.assertEqual(
            before,
            restored.after_graph_sha256,
        )

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            restored_decision, restored_error = (
                bridge._natural_intent_route(
                    "route this",
                    workspace_context,
                    "",
                )
            )

        self.assertIs(
            restored_decision,
            laser.decision,
        )
        self.assertEqual(
            "",
            restored_error,
        )
        self.assertEqual(
            2,
            laser.bind_calls,
        )
        self.assertEqual(
            2,
            laser.lookup_calls,
        )

    def test_chatbridge_rejects_noncanonical_patch_target_without_mutation(
        self,
    ) -> None:
        from unittest import mock

        import main as W

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(
                W.QObject()
            )

        before = (
            bridge.machine_graph_sha256()
        )

        sentinel_edge = (
            "call-noncanonical-c7"
        )

        patch = (
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=(
                            W.machine_graph.OP_DISABLE_EDGE
                        ),
                        edge_id=sentinel_edge,
                    ),
                ),
            )
        )

        with self.assertRaisesRegex(
            W.machine_graph.MachineGraphError,
            "PATCH_RUNTIME_BINDING_NOT_IMPLEMENTED",
        ):
            bridge.apply_machine_graph_patch(
                patch
            )

        self.assertEqual(
            before,
            bridge.machine_graph_sha256(),
        )


    def test_disabled_call_12_blocks_real_idekompass_decide_and_inverse_restores(
        self,
    ) -> None:
        from unittest import mock

        import main as W

        workspace_context = {
            "source_path":
                "/tmp/gg-c7-machine-graph-test.py",
            "sha256":
                "c" * 64,
            "object_id":
                "workspace-object-c7-machine-graph-test",
        }

        decide_result = {
            "prompt_extension":
                "\nC7-MACHINE-GRAPH-TEST",
            "decision_kind":
                "STOP_UNCERTAINTY",
            "reason_code":
                "C7_MACHINE_GRAPH_TEST",
            "revalidation_result":
                "REVALIDATED",
        }

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(
                W.QObject()
            )

        with (
            mock.patch.object(
                W.control_contract,
                "parse_control_command",
                return_value=None,
            ),
            mock.patch.object(
                W,
                "parse_selfdev_command",
                return_value=None,
            ),
            mock.patch.object(
                W,
                "parse_autonomy_command",
                return_value=None,
            ),
            mock.patch.object(
                W,
                "parse_write_command",
                return_value=None,
            ),
            mock.patch.object(
                W,
                "parse_safe_tool_command",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_active",
                return_value=False,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_resolved_chat_context",
                return_value=(
                    "verified effective prompt",
                    workspace_context,
                ),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_natural_intent_route",
                return_value=(
                    None,
                    "C7_TEST_ROUTE_UNAVAILABLE",
                ),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_append",
            ) as append_mock,
            mock.patch.object(
                W.idekompass_decision_ingress,
                "decide",
                return_value=decide_result,
            ) as decide_mock,
            mock.patch.object(
                W.QProcess,
                "start",
                side_effect=RuntimeError(
                    "MODEL_START_MUST_NOT_BE_REACHED"
                ),
            ) as model_start_mock,
        ):
            bridge.submit(
                "Inspect verified current source.",
                "context-c7-test",
                "workspace-object-c7-machine-graph-test",
            )

            self.assertEqual(
                1,
                decide_mock.call_count,
            )

            before = (
                bridge.machine_graph_sha256()
            )

            disabled = (
                bridge.apply_machine_graph_patch(
                    W.machine_graph.GraphPatch(
                        base_graph_sha256=before,
                        operations=(
                            W.machine_graph.GraphOperation(
                                op=(
                                    W.machine_graph.OP_DISABLE_EDGE
                                ),
                                edge_id="call-12",
                            ),
                        ),
                    )
                )
            )

            self.assertFalse(
                bridge._machine_graph_edge_enabled(
                    "call-12"
                )
            )

            append_mock.reset_mock()

            bridge.submit(
                "Inspect verified current source.",
                "context-c7-test",
                "workspace-object-c7-machine-graph-test",
            )

            self.assertEqual(
                1,
                decide_mock.call_count,
            )

            idekompass_messages = [
                call.args[2]
                for call
                in append_mock.call_args_list
                if (
                    len(call.args) >= 3
                    and call.args[1]
                    == "IDEKOMPASS"
                )
            ]

            self.assertIn(
                (
                    "Read-only Idékompass blocked · "
                    "MACHINE_GRAPH_EDGE_DISABLED:call-12"
                ),
                idekompass_messages,
            )

            restored = (
                bridge.apply_machine_graph_patch(
                    disabled.inverse_patch
                )
            )

            self.assertEqual(
                before,
                restored.after_graph_sha256,
            )

            bridge.submit(
                "Inspect verified current source.",
                "context-c7-test",
                "workspace-object-c7-machine-graph-test",
            )

            self.assertEqual(
                2,
                decide_mock.call_count,
            )

            self.assertEqual(
                0,
                model_start_mock.call_count,
            )

    def test_active_patch_method_has_bounded_in_memory_effect_surface(
        self,
    ) -> None:
        import ast as runtime_ast
        import inspect
        import textwrap as runtime_textwrap

        import main as W

        source = runtime_textwrap.dedent(
            inspect.getsource(
                W.ChatBridge.apply_machine_graph_patch
            )
        )

        tree = runtime_ast.parse(
            source
        )

        def dotted(
            node: runtime_ast.AST,
        ) -> str:
            if isinstance(
                node,
                runtime_ast.Name,
            ):
                return node.id

            if isinstance(
                node,
                runtime_ast.Attribute,
            ):
                owner = dotted(
                    node.value
                )

                return (
                    owner
                    + "."
                    + node.attr
                    if owner
                    else node.attr
                )

            return ""

        calls = {
            dotted(
                node.func
            )
            for node in runtime_ast.walk(
                tree
            )
            if isinstance(
                node,
                runtime_ast.Call,
            )
        }

        self.assertIn(
            "patch.validate",
            calls,
        )
        self.assertIn(
            "self.preview_machine_graph_patch",
            calls,
        )

        forbidden_calls = {
            "open",
            "os.open",
            "subprocess.run",
            "subprocess.Popen",
            "QProcess",
        }

        self.assertFalse(
            calls
            & forbidden_calls
        )

        assignments_to_active_graph = 0

        for node in runtime_ast.walk(
            tree
        ):
            targets = []

            if isinstance(
                node,
                runtime_ast.Assign,
            ):
                targets.extend(
                    node.targets
                )

            elif isinstance(
                node,
                runtime_ast.AnnAssign,
            ):
                targets.append(
                    node.target
                )

            for target in targets:
                if (
                    isinstance(
                        target,
                        runtime_ast.Attribute,
                    )
                    and isinstance(
                        target.value,
                        runtime_ast.Name,
                    )
                    and target.value.id == "self"
                    and target.attr == "_machine_graph"
                ):
                    assignments_to_active_graph += 1

        self.assertEqual(
            1,
            assignments_to_active_graph,
        )



    def test_disabled_call_08_blocks_real_laser_lookup_and_inverse_restores(
        self,
    ) -> None:
        from types import SimpleNamespace
        from unittest import mock
        import main as W

        class FakeLaser:
            def __init__(self) -> None:
                self.bind_calls = 0
                self.lookup_calls = 0
                self.decision = SimpleNamespace(
                    automatic_model_dispatch=False,
                    registered_capability_execution=False,
                )

            def bind(self, context):
                self.bind_calls += 1
                return SimpleNamespace(handle_id="fake-handle")

            def lookup(self, handle_id):
                self.lookup_calls += 1
                return SimpleNamespace(route=self.decision)

        with (
            mock.patch.object(
                W.resident_state.WorkbenchResidentInformationState,
                "bootstrap_workbench_sources",
                return_value=object(),
            ),
            mock.patch.object(
                W.control_contract,
                "TaskLedger",
                return_value=object(),
            ),
            mock.patch.object(
                W.ChatBridge,
                "_recover_selfdev_records",
                return_value=None,
            ),
            mock.patch.object(
                W.ChatBridge,
                "_block_unrecoverable_autonomy_records",
                return_value=None,
            ),
        ):
            bridge = W.ChatBridge(W.QObject())

        laser = FakeLaser()
        bridge._intent_laser = laser
        context = {
            "source_path": "/tmp/example.py",
            "sha256": "a" * 64,
            "object_id": "workspace-object-1",
        }

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            decision, error = bridge._natural_intent_route(
                "route this",
                context,
                "",
            )

        self.assertIs(decision, laser.decision)
        self.assertEqual("", error)
        self.assertEqual(1, laser.bind_calls)
        self.assertEqual(1, laser.lookup_calls)

        before = bridge.machine_graph_sha256()
        disabled = bridge.apply_machine_graph_patch(
            W.machine_graph.GraphPatch(
                base_graph_sha256=before,
                operations=(
                    W.machine_graph.GraphOperation(
                        op=W.machine_graph.OP_DISABLE_EDGE,
                        edge_id="call-08",
                    ),
                ),
            )
        )

        self.assertFalse(
            bridge._machine_graph_edge_enabled("call-08")
        )

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            blocked, blocked_error = bridge._natural_intent_route(
                "route this",
                context,
                "",
            )

        self.assertIsNone(blocked)
        self.assertEqual(
            "MACHINE_GRAPH_EDGE_DISABLED:call-08",
            blocked_error,
        )
        self.assertEqual(2, laser.bind_calls)
        self.assertEqual(1, laser.lookup_calls)

        restored = bridge.apply_machine_graph_patch(
            disabled.inverse_patch
        )
        self.assertEqual(before, restored.after_graph_sha256)

        with mock.patch.object(
            W.ChatBridge,
            "_ensure_natural_intent_laser",
            return_value=None,
        ):
            decision2, error2 = bridge._natural_intent_route(
                "route this",
                context,
                "",
            )

        self.assertIs(decision2, laser.decision)
        self.assertEqual("", error2)
        self.assertEqual(3, laser.bind_calls)
        self.assertEqual(2, laser.lookup_calls)


    def test_solver_router_edges_are_runtime_guarded(self) -> None:
        class FakeRouter:
            def __init__(self) -> None:
                self.route_focus_key_calls = 0
                self.route_calls = 0

            def route_focus_key(self, _context: object) -> str:
                self.route_focus_key_calls += 1
                return "a" * 64

            def route(self, _context: object) -> object:
                self.route_calls += 1
                return object()

        state = {
            "call-09": True,
            "call-10": True,
        }

        def edge_enabled(edge_id: str) -> bool:
            return state[edge_id]

        router = FakeRouter()
        cache = S.LaserFocusCache(
            router,
            edge_enabled=edge_enabled,
        )
        cache.focus(object())
        self.assertEqual(router.route_focus_key_calls, 1)
        self.assertEqual(router.route_calls, 1)

        state["call-09"] = False
        router = FakeRouter()
        cache = S.LaserFocusCache(
            router,
            edge_enabled=edge_enabled,
        )
        with self.assertRaisesRegex(
            S.SolverRouterError,
            "^MACHINE_GRAPH_EDGE_DISABLED:call-09$",
        ):
            cache.focus(object())
        self.assertEqual(router.route_focus_key_calls, 1)
        self.assertEqual(router.route_calls, 0)

        state["call-09"] = True
        state["call-10"] = False
        router = FakeRouter()
        cache = S.LaserFocusCache(
            router,
            edge_enabled=edge_enabled,
        )
        with self.assertRaisesRegex(
            S.SolverRouterError,
            "^MACHINE_GRAPH_EDGE_DISABLED:call-10$",
        ):
            cache.focus(object())
        self.assertEqual(router.route_focus_key_calls, 0)
        self.assertEqual(router.route_calls, 0)

        state["call-10"] = True
        router = FakeRouter()
        legacy_cache = S.LaserFocusCache(router)
        legacy_cache.focus(object())
        self.assertEqual(router.route_focus_key_calls, 1)
        self.assertEqual(router.route_calls, 1)

        with self.assertRaisesRegex(
            S.SolverRouterError,
            "^edge_enabled invalid$",
        ):
            S.LaserFocusCache(
                FakeRouter(),
                edge_enabled=object(),
            )

if __name__ == "__main__":
    unittest.main()
