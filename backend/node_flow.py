"""Visual information-flow graph for the NODES workspace tab.

This is the unfinished machine-graph, given a Geometry Nodes-style editor.
Blocks are agents/streams. Ports sit on block edges. Wires are machine-graph
edges. Changing a wire or a block parameter changes that stream. It does not
spawn a second agent brain.
"""

from __future__ import annotations

from typing import Any

from backend import machine_graph as G
from backend import thought_desk


SCHEMA = "gg.node-flow.v1"
STREAM_SCHEMA = "gg.flow.stream.v1"
SEMANTIC = "flow.stream"
KIND_PARAM = {
    "INTENT": {"gain": 1.0, "mix": 1.0, "loops": 1.0},
    "RISK": {"gain": 1.0, "mix": 1.0, "loops": 1.0},
    "EVIDENCE": {"gain": 0.8, "mix": 1.0, "loops": 1.0},
    "CRITIC": {"gain": 1.0, "mix": 1.0, "loops": 1.0},
    "BUILDER": {"gain": 1.0, "mix": 1.0, "loops": 1.0},
    "FRONT_MAN": {"gain": 1.0, "mix": 1.0, "loops": 2.0},
    "CHAT": {"gain": 1.0, "mix": 1.0, "loops": 1.0},
    "MEMORY": {"gain": 0.6, "mix": 1.0, "loops": 1.0},
}

_GRAPH: G.MachineGraph | None = None
_LAYOUT: dict[str, dict[str, Any]] = {}


def _port(port_id: str, direction: str, max_connections: int = 8) -> G.PortSpec:
    return G.PortSpec(
        port_id=port_id,
        direction=direction,
        schema_id=STREAM_SCHEMA,
        semantic_id=SEMANTIC,
        channel_class="DATA",
        semantics="information stream",
        authority_contract="NONE",
        max_connections=max_connections,
    )


def _node(node_id: str, inputs: tuple[str, ...], outputs: tuple[str, ...]) -> G.NodeSpec:
    ports = tuple(_port(name, G.INPUT) for name in inputs) + tuple(
        _port(name, G.OUTPUT) for name in outputs
    )
    return G.NodeSpec(
        node_id=node_id,
        implementation_id="flow." + node_id.lower(),
        contract_version="v1",
        state_owner="SELF",
        ports=ports,
        authority_contract="NONE",
        enabled=True,
    )


def _edge(edge_id: str, source: str, source_port: str, target: str, target_port: str) -> G.EdgeSpec:
    return G.EdgeSpec(
        edge_id=edge_id,
        from_node_id=source,
        from_port_id=source_port,
        to_node_id=target,
        to_port_id=target_port,
        enabled=True,
    )


def default_graph() -> G.MachineGraph:
    nodes = (
        _node("INTENT", (), ("out",)),
        _node("RISK", (), ("out",)),
        _node("MEMORY", (), ("out",)),
        _node("EVIDENCE", ("in_mem",), ("out",)),
        _node("CRITIC", ("in_plan",), ("out",)),
        _node("BUILDER", ("in_ask",), ("out",)),
        _node(
            "FRONT_MAN",
            ("in_intent", "in_risk", "in_evidence", "in_critic", "in_builder"),
            ("out",),
        ),
        _node("CHAT", ("in",), ("out",)),
    )
    edges = (
        _edge("wire-intent-fm", "INTENT", "out", "FRONT_MAN", "in_intent"),
        _edge("wire-risk-fm", "RISK", "out", "FRONT_MAN", "in_risk"),
        _edge("wire-mem-ev", "MEMORY", "out", "EVIDENCE", "in_mem"),
        _edge("wire-ev-fm", "EVIDENCE", "out", "FRONT_MAN", "in_evidence"),
        _edge("wire-intent-builder", "INTENT", "out", "BUILDER", "in_ask"),
        _edge("wire-builder-critic", "BUILDER", "out", "CRITIC", "in_plan"),
        _edge("wire-critic-fm", "CRITIC", "out", "FRONT_MAN", "in_critic"),
        _edge("wire-builder-fm", "BUILDER", "out", "FRONT_MAN", "in_builder"),
        _edge("wire-fm-chat", "FRONT_MAN", "out", "CHAT", "in"),
    )
    return G.MachineGraph(nodes=nodes, edges=edges)


def default_layout() -> dict[str, dict[str, Any]]:
    places = {
        "INTENT": (40, 40),
        "RISK": (40, 180),
        "MEMORY": (40, 320),
        "EVIDENCE": (260, 320),
        "BUILDER": (260, 40),
        "CRITIC": (260, 180),
        "FRONT_MAN": (500, 160),
        "CHAT": (740, 160),
    }
    out: dict[str, dict[str, Any]] = {}
    for node_id, (x, y) in places.items():
        params = dict(KIND_PARAM.get(node_id, {"gain": 1.0, "mix": 1.0, "loops": 1.0}))
        out[node_id] = {"x": x, "y": y, "params": params}
    return out


def reset() -> None:
    global _GRAPH, _LAYOUT
    _GRAPH = default_graph()
    _LAYOUT = default_layout()


def graph() -> G.MachineGraph:
    global _GRAPH
    if _GRAPH is None:
        reset()
    assert _GRAPH is not None
    return _GRAPH


def layout() -> dict[str, dict[str, Any]]:
    if not _LAYOUT:
        reset()
    return _LAYOUT


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return number


def evaluate(flow: G.MachineGraph | None = None) -> dict[str, Any]:
    current = flow or graph()
    nodes = {node.node_id: node for node in current.nodes}
    incoming: dict[str, list[tuple[str, str, str]]] = {key: [] for key in nodes}
    for edge in current.edges:
        if not edge.enabled:
            continue
        incoming[edge.to_node_id].append(
            (edge.from_node_id, edge.from_port_id, edge.edge_id)
        )

    values: dict[str, float] = {}
    memory_base = 0.40
    try:
        from backend.long_memory import density as memory_density

        fill = memory_density()
        if fill > 0:
            memory_base = round(0.40 + 0.40 * fill, 4)
    except Exception:
        memory_base = 0.40

    def value_of(node_id: str, stack: set[str]) -> float:
        if node_id in values:
            return values[node_id]
        if node_id in stack:
            return 0.0
        node = nodes.get(node_id)
        if node is None or not node.enabled:
            values[node_id] = 0.0
            return 0.0
        params = (layout().get(node_id) or {}).get("params") or {}
        gain = max(0.0, min(2.0, _finite(params.get("gain"), 1.0)))
        mix = max(0.0, min(1.0, _finite(params.get("mix"), 1.0)))
        base = {
            "INTENT": 0.70,
            "RISK": 0.55,
            "MEMORY": memory_base,
            "EVIDENCE": 0.45,
            "CRITIC": 0.60,
            "BUILDER": 0.65,
            "FRONT_MAN": 0.0,
            "CHAT": 0.0,
        }.get(node_id, 0.5)
        feeds = incoming.get(node_id) or []
        parts: list[float] = []
        stack.add(node_id)
        for source_id, _port, _edge in feeds:
            parts.append(value_of(source_id, stack))
        stack.discard(node_id)
        if node_id == "FRONT_MAN" and len(parts) >= 2:
            mean = sum(parts) / len(parts)
            contrast = (
                sum(abs(item - mean) for item in parts) / len(parts)
            )
            loops = max(1.0, min(3.0, _finite(params.get("loops"), 2.0)))
            signal = contrast * loops
        elif parts:
            signal = (1.0 - mix) * base + mix * (sum(parts) / len(parts))
        else:
            signal = base
        values[node_id] = round(max(0.0, min(2.0, signal * gain)), 4)
        return values[node_id]

    for node_id in nodes:
        value_of(node_id, set())

    chat = values.get("CHAT", 0.0)
    front = values.get("FRONT_MAN", 0.0)
    return {
        "schema": "gg.node-flow.eval.v1",
        "values": values,
        "contrast": front,
        "stream": chat,
        "note": "Contrast from interfering streams, not more energy.",
        "parallel_agent_brain": thought_desk.PARALLEL_AGENT_BRAIN,
    }


def snapshot() -> dict[str, Any]:
    current = graph()
    places = layout()
    blocks = []
    for node in sorted(current.nodes, key=lambda item: item.node_id):
        spot = places.get(node.node_id) or {"x": 40, "y": 40, "params": {}}
        blocks.append(
            {
                **node.as_dict(),
                "kind": node.node_id,
                "x": int(spot.get("x") or 40),
                "y": int(spot.get("y") or 40),
                "params": dict(spot.get("params") or {}),
            }
        )
    eval_row = evaluate(current)
    return {
        "schema": SCHEMA,
        "mode": "INFORMATION_FLOW",
        "parallel_agent_brain": thought_desk.PARALLEL_AGENT_BRAIN,
        "graph_sha256": current.graph_sha256(),
        "blocks": blocks,
        "wires": [edge.as_dict() for edge in sorted(current.edges, key=lambda item: item.edge_id)],
        "eval": eval_row,
        "note": "Blocks are streams. Wires are machine-graph edges. Drag a param to retune the agent.",
    }


def _apply(op: G.GraphOperation) -> dict[str, Any]:
    global _GRAPH
    current = graph()
    patch = G.GraphPatch(
        base_graph_sha256=current.graph_sha256(),
        operations=(op,),
        action_authority="NONE",
        persistent_write="NONE",
        model_inference=False,
    )
    result = G.apply_patch(current, patch)
    _GRAPH = result.graph
    return snapshot()


def connect(from_node: str, from_port: str, to_node: str, to_port: str) -> dict[str, Any]:
    edge_id = (
        "wire-"
        + str(from_node).strip()
        + "-"
        + str(from_port).strip()
        + "-"
        + str(to_node).strip()
        + "-"
        + str(to_port).strip()
    )
    return _apply(
        G.GraphOperation(
            op=G.OP_CONNECT,
            edge=_edge(edge_id, from_node, from_port, to_node, to_port),
        )
    )


def disconnect(edge_id: str) -> dict[str, Any]:
    return _apply(G.GraphOperation(op=G.OP_DISCONNECT, edge_id=str(edge_id or "").strip()))


def toggle_node(node_id: str, enabled: bool) -> dict[str, Any]:
    op = G.OP_ENABLE_NODE if enabled else G.OP_DISABLE_NODE
    # disable edges first if turning a node off
    current = graph()
    if not enabled:
        for edge in current.edges:
            if (
                edge.enabled
                and (
                    edge.from_node_id == node_id
                    or edge.to_node_id == node_id
                )
            ):
                _apply(G.GraphOperation(op=G.OP_DISABLE_EDGE, edge_id=edge.edge_id))
    return _apply(G.GraphOperation(op=op, node_id=str(node_id or "").strip()))


def move(node_id: str, x: float, y: float) -> dict[str, Any]:
    key = str(node_id or "").strip()
    spot = layout().setdefault(key, {"x": 40, "y": 40, "params": {}})
    spot["x"] = max(0, min(2400, int(_finite(x, 40))))
    spot["y"] = max(0, min(1600, int(_finite(y, 40))))
    return snapshot()


def set_param(node_id: str, key: str, value: float) -> dict[str, Any]:
    node_key = str(node_id or "").strip()
    param = str(key or "").strip().lower()
    if param not in {"gain", "mix", "loops"}:
        raise G.MachineGraphError("PARAM_UNKNOWN")
    spot = layout().setdefault(node_key, {"x": 40, "y": 40, "params": {}})
    params = dict(spot.get("params") or {})
    number = _finite(value, 1.0)
    if param == "loops":
        number = max(1.0, min(3.0, number))
    else:
        number = max(0.0, min(2.0, number))
    params[param] = round(number, 4)
    spot["params"] = params
    return snapshot()
