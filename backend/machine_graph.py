from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json


MACHINE_GRAPH_SCHEMA = "gg.machine-graph.v1"
PORT_SCHEMA = "gg.machine-graph.port.v1"
NODE_SCHEMA = "gg.machine-graph.node.v1"
EDGE_SCHEMA = "gg.machine-graph.edge.v1"
OPERATION_SCHEMA = "gg.machine-graph.operation.v1"
PATCH_SCHEMA = "gg.machine-graph.patch.v1"
PATCH_RESULT_SCHEMA = "gg.machine-graph.patch-result.v1"

INPUT = "INPUT"
OUTPUT = "OUTPUT"

PORT_DIRECTIONS = {
    INPUT,
    OUTPUT,
}

CHANNEL_CLASSES = {
    "DATA",
    "EVENT",
    "CONTROL",
    "EVIDENCE",
    "STATE_REFERENCE",
    "ACTION_REQUEST",
    "ACTION_RESULT",
    "INVALIDATION",
}

OP_ADD_NODE = "ADD_NODE"
OP_REMOVE_NODE = "REMOVE_NODE"
OP_CONNECT = "CONNECT"
OP_DISCONNECT = "DISCONNECT"
OP_ENABLE_NODE = "ENABLE_NODE"
OP_DISABLE_NODE = "DISABLE_NODE"
OP_ENABLE_EDGE = "ENABLE_EDGE"
OP_DISABLE_EDGE = "DISABLE_EDGE"

PATCH_OPERATIONS = {
    OP_ADD_NODE,
    OP_REMOVE_NODE,
    OP_CONNECT,
    OP_DISCONNECT,
    OP_ENABLE_NODE,
    OP_DISABLE_NODE,
    OP_ENABLE_EDGE,
    OP_DISABLE_EDGE,
}

MAX_NODES = 4096
MAX_EDGES = 16384
MAX_PORTS_PER_NODE = 256
MAX_PATCH_OPERATIONS = 1024


class MachineGraphError(
    RuntimeError
):
    pass


def canonical_json(
    value: object,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(
    value: object,
) -> str:
    return hashlib.sha256(
        canonical_json(value)
    ).hexdigest()


def _require_text(
    value: object,
    label: str,
    *,
    maximum: int = 1024,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
    ):
        raise MachineGraphError(
            label + "_INVALID"
        )

    return value


def _require_sha256(
    value: object,
    label: str,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
    ):
        raise MachineGraphError(
            label + "_INVALID"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise MachineGraphError(
            label + "_INVALID"
        ) from exc

    return value


@dataclass(
    frozen=True,
    slots=True,
)
class PortSpec:
    port_id: str
    direction: str
    schema_id: str
    semantic_id: str
    channel_class: str
    semantics: str
    authority_contract: str = "NONE"
    max_connections: int = 1
    schema: str = PORT_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != PORT_SCHEMA:
            raise MachineGraphError(
                "PORT_SCHEMA_INVALID"
            )

        _require_text(
            self.port_id,
            "PORT_ID",
            maximum=256,
        )

        if self.direction not in PORT_DIRECTIONS:
            raise MachineGraphError(
                "PORT_DIRECTION_INVALID"
            )

        _require_text(
            self.schema_id,
            "PORT_DATA_SCHEMA",
            maximum=256,
        )

        _require_text(
            self.semantic_id,
            "PORT_SEMANTIC_ID",
            maximum=256,
        )

        if (
            self.channel_class
            not in CHANNEL_CLASSES
        ):
            raise MachineGraphError(
                "PORT_CHANNEL_CLASS_INVALID"
            )

        _require_text(
            self.semantics,
            "PORT_SEMANTICS",
            maximum=1024,
        )

        _require_text(
            self.authority_contract,
            "PORT_AUTHORITY_CONTRACT",
            maximum=256,
        )

        if (
            not isinstance(
                self.max_connections,
                int,
            )
            or isinstance(
                self.max_connections,
                bool,
            )
            or self.max_connections < 1
            or self.max_connections > 4096
        ):
            raise MachineGraphError(
                "PORT_MAX_CONNECTIONS_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "port_id":
                self.port_id,
            "direction":
                self.direction,
            "schema_id":
                self.schema_id,
            "semantic_id":
                self.semantic_id,
            "channel_class":
                self.channel_class,
            "semantics":
                self.semantics,
            "authority_contract":
                self.authority_contract,
            "max_connections":
                self.max_connections,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class NodeSpec:
    node_id: str
    implementation_id: str
    contract_version: str
    state_owner: str
    ports: tuple[
        PortSpec,
        ...
    ]
    authority_contract: str = "NONE"
    enabled: bool = True
    schema: str = NODE_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != NODE_SCHEMA:
            raise MachineGraphError(
                "NODE_SCHEMA_INVALID"
            )

        _require_text(
            self.node_id,
            "NODE_ID",
            maximum=256,
        )

        _require_text(
            self.implementation_id,
            "NODE_IMPLEMENTATION_ID",
            maximum=512,
        )

        _require_text(
            self.contract_version,
            "NODE_CONTRACT_VERSION",
            maximum=128,
        )

        _require_text(
            self.state_owner,
            "NODE_STATE_OWNER",
            maximum=256,
        )

        _require_text(
            self.authority_contract,
            "NODE_AUTHORITY_CONTRACT",
            maximum=256,
        )

        if not isinstance(
            self.enabled,
            bool,
        ):
            raise MachineGraphError(
                "NODE_ENABLED_INVALID"
            )

        if (
            not isinstance(
                self.ports,
                tuple,
            )
            or len(self.ports)
            > MAX_PORTS_PER_NODE
        ):
            raise MachineGraphError(
                "NODE_PORTS_INVALID"
            )

        seen: set[str] = set()

        for port in self.ports:
            if not isinstance(
                port,
                PortSpec,
            ):
                raise MachineGraphError(
                    "NODE_PORT_TYPE_INVALID"
                )

            port.validate()

            if port.port_id in seen:
                raise MachineGraphError(
                    "NODE_PORT_ID_DUPLICATE"
                )

            seen.add(
                port.port_id
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "node_id":
                self.node_id,
            "implementation_id":
                self.implementation_id,
            "contract_version":
                self.contract_version,
            "state_owner":
                self.state_owner,
            "authority_contract":
                self.authority_contract,
            "enabled":
                self.enabled,
            "ports": [
                port.as_dict()
                for port
                in sorted(
                    self.ports,
                    key=lambda item:
                        item.port_id,
                )
            ],
        }


@dataclass(
    frozen=True,
    slots=True,
)
class EdgeSpec:
    edge_id: str
    from_node_id: str
    from_port_id: str
    to_node_id: str
    to_port_id: str
    enabled: bool = True
    schema: str = EDGE_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != EDGE_SCHEMA:
            raise MachineGraphError(
                "EDGE_SCHEMA_INVALID"
            )

        for value, label in (
            (
                self.edge_id,
                "EDGE_ID",
            ),
            (
                self.from_node_id,
                "EDGE_FROM_NODE",
            ),
            (
                self.from_port_id,
                "EDGE_FROM_PORT",
            ),
            (
                self.to_node_id,
                "EDGE_TO_NODE",
            ),
            (
                self.to_port_id,
                "EDGE_TO_PORT",
            ),
        ):
            _require_text(
                value,
                label,
                maximum=256,
            )

        if not isinstance(
            self.enabled,
            bool,
        ):
            raise MachineGraphError(
                "EDGE_ENABLED_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "edge_id":
                self.edge_id,
            "from_node_id":
                self.from_node_id,
            "from_port_id":
                self.from_port_id,
            "to_node_id":
                self.to_node_id,
            "to_port_id":
                self.to_port_id,
            "enabled":
                self.enabled,
        }


def _port_for(
    node: NodeSpec,
    port_id: str,
) -> PortSpec:
    matches = tuple(
        port
        for port in node.ports
        if port.port_id == port_id
    )

    if len(matches) != 1:
        raise MachineGraphError(
            "PORT_LOOKUP_CARDINALITY_INVALID"
        )

    return matches[0]


@dataclass(
    frozen=True,
    slots=True,
)
class MachineGraph:
    nodes: tuple[
        NodeSpec,
        ...
    ]
    edges: tuple[
        EdgeSpec,
        ...
    ]
    schema: str = MACHINE_GRAPH_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != MACHINE_GRAPH_SCHEMA:
            raise MachineGraphError(
                "MACHINE_GRAPH_SCHEMA_INVALID"
            )

        if (
            not isinstance(
                self.nodes,
                tuple,
            )
            or len(self.nodes)
            > MAX_NODES
        ):
            raise MachineGraphError(
                "MACHINE_GRAPH_NODES_INVALID"
            )

        if (
            not isinstance(
                self.edges,
                tuple,
            )
            or len(self.edges)
            > MAX_EDGES
        ):
            raise MachineGraphError(
                "MACHINE_GRAPH_EDGES_INVALID"
            )

        nodes: dict[
            str,
            NodeSpec,
        ] = {}

        for node in self.nodes:
            if not isinstance(
                node,
                NodeSpec,
            ):
                raise MachineGraphError(
                    "MACHINE_GRAPH_NODE_TYPE_INVALID"
                )

            node.validate()

            if node.node_id in nodes:
                raise MachineGraphError(
                    "MACHINE_GRAPH_NODE_ID_DUPLICATE"
                )

            nodes[
                node.node_id
            ] = node

        edge_ids: set[str] = set()

        connection_counts: dict[
            tuple[
                str,
                str,
            ],
            int,
        ] = {}

        for edge in self.edges:
            if not isinstance(
                edge,
                EdgeSpec,
            ):
                raise MachineGraphError(
                    "MACHINE_GRAPH_EDGE_TYPE_INVALID"
                )

            edge.validate()

            if edge.edge_id in edge_ids:
                raise MachineGraphError(
                    "MACHINE_GRAPH_EDGE_ID_DUPLICATE"
                )

            edge_ids.add(
                edge.edge_id
            )

            source = nodes.get(
                edge.from_node_id
            )

            target = nodes.get(
                edge.to_node_id
            )

            if source is None:
                raise MachineGraphError(
                    "EDGE_FROM_NODE_UNKNOWN"
                )

            if target is None:
                raise MachineGraphError(
                    "EDGE_TO_NODE_UNKNOWN"
                )

            source_port = _port_for(
                source,
                edge.from_port_id,
            )

            target_port = _port_for(
                target,
                edge.to_port_id,
            )

            if source_port.direction != OUTPUT:
                raise MachineGraphError(
                    "EDGE_SOURCE_NOT_OUTPUT"
                )

            if target_port.direction != INPUT:
                raise MachineGraphError(
                    "EDGE_TARGET_NOT_INPUT"
                )

            if (
                source_port.schema_id
                != target_port.schema_id
            ):
                raise MachineGraphError(
                    "EDGE_SCHEMA_INCOMPATIBLE"
                )

            if (
                source_port.semantic_id
                != target_port.semantic_id
            ):
                raise MachineGraphError(
                    "EDGE_SEMANTIC_INCOMPATIBLE"
                )

            if (
                source_port.channel_class
                != target_port.channel_class
            ):
                raise MachineGraphError(
                    "EDGE_CHANNEL_INCOMPATIBLE"
                )

            if (
                source_port.authority_contract
                != target_port.authority_contract
            ):
                raise MachineGraphError(
                    "EDGE_AUTHORITY_INCOMPATIBLE"
                )

            if not edge.enabled:
                continue

            if (
                not source.enabled
                or not target.enabled
            ):
                raise MachineGraphError(
                    "ENABLED_EDGE_TOUCHES_DISABLED_NODE"
                )

            for (
                node_id,
                port,
            ) in (
                (
                    source.node_id,
                    source_port,
                ),
                (
                    target.node_id,
                    target_port,
                ),
            ):
                key = (
                    node_id,
                    port.port_id,
                )

                count = (
                    connection_counts.get(
                        key,
                        0,
                    )
                    + 1
                )

                if count > port.max_connections:
                    raise MachineGraphError(
                        "PORT_CONNECTION_LIMIT_EXCEEDED"
                    )

                connection_counts[
                    key
                ] = count

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "nodes": [
                node.as_dict()
                for node
                in sorted(
                    self.nodes,
                    key=lambda item:
                        item.node_id,
                )
            ],
            "edges": [
                edge.as_dict()
                for edge
                in sorted(
                    self.edges,
                    key=lambda item:
                        item.edge_id,
                )
            ],
        }

    def graph_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(
    frozen=True,
    slots=True,
)
class GraphOperation:
    op: str
    node: NodeSpec | None = None
    node_id: str = ""
    edge: EdgeSpec | None = None
    edge_id: str = ""
    schema: str = OPERATION_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != OPERATION_SCHEMA:
            raise MachineGraphError(
                "GRAPH_OPERATION_SCHEMA_INVALID"
            )

        if self.op not in PATCH_OPERATIONS:
            raise MachineGraphError(
                "GRAPH_OPERATION_KIND_INVALID"
            )

        if self.op == OP_ADD_NODE:
            if (
                not isinstance(
                    self.node,
                    NodeSpec,
                )
                or self.node_id
                or self.edge is not None
                or self.edge_id
            ):
                raise MachineGraphError(
                    "ADD_NODE_OPERATION_INVALID"
                )

            self.node.validate()
            return

        if self.op == OP_REMOVE_NODE:
            if (
                self.node is not None
                or not self.node_id
                or self.edge is not None
                or self.edge_id
            ):
                raise MachineGraphError(
                    "REMOVE_NODE_OPERATION_INVALID"
                )

            _require_text(
                self.node_id,
                "REMOVE_NODE_ID",
                maximum=256,
            )
            return

        if self.op == OP_CONNECT:
            if (
                self.node is not None
                or self.node_id
                or not isinstance(
                    self.edge,
                    EdgeSpec,
                )
                or self.edge_id
            ):
                raise MachineGraphError(
                    "CONNECT_OPERATION_INVALID"
                )

            self.edge.validate()
            return

        if self.op == OP_DISCONNECT:
            if (
                self.node is not None
                or self.node_id
                or self.edge is not None
                or not self.edge_id
            ):
                raise MachineGraphError(
                    "DISCONNECT_OPERATION_INVALID"
                )

            _require_text(
                self.edge_id,
                "DISCONNECT_EDGE_ID",
                maximum=256,
            )
            return

        if self.op in {
            OP_ENABLE_NODE,
            OP_DISABLE_NODE,
        }:
            if (
                self.node is not None
                or not self.node_id
                or self.edge is not None
                or self.edge_id
            ):
                raise MachineGraphError(
                    "NODE_STATE_OPERATION_INVALID"
                )

            _require_text(
                self.node_id,
                "NODE_STATE_ID",
                maximum=256,
            )
            return

        if self.op in {
            OP_ENABLE_EDGE,
            OP_DISABLE_EDGE,
        }:
            if (
                self.node is not None
                or self.node_id
                or self.edge is not None
                or not self.edge_id
            ):
                raise MachineGraphError(
                    "EDGE_STATE_OPERATION_INVALID"
                )

            _require_text(
                self.edge_id,
                "EDGE_STATE_ID",
                maximum=256,
            )
            return

        raise MachineGraphError(
            "GRAPH_OPERATION_UNREACHABLE"
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        result: dict[
            str,
            object,
        ] = {
            "schema":
                self.schema,
            "op":
                self.op,
        }

        if self.node is not None:
            result[
                "node"
            ] = self.node.as_dict()

        if self.node_id:
            result[
                "node_id"
            ] = self.node_id

        if self.edge is not None:
            result[
                "edge"
            ] = self.edge.as_dict()

        if self.edge_id:
            result[
                "edge_id"
            ] = self.edge_id

        return result


@dataclass(
    frozen=True,
    slots=True,
)
class GraphPatch:
    base_graph_sha256: str
    operations: tuple[
        GraphOperation,
        ...
    ]
    action_authority: str = "NONE"
    persistent_write: str = "NONE"
    model_inference: bool = False
    schema: str = PATCH_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != PATCH_SCHEMA:
            raise MachineGraphError(
                "GRAPH_PATCH_SCHEMA_INVALID"
            )

        _require_sha256(
            self.base_graph_sha256,
            "GRAPH_PATCH_BASE",
        )

        if (
            not isinstance(
                self.operations,
                tuple,
            )
            or not self.operations
            or len(self.operations)
            > MAX_PATCH_OPERATIONS
        ):
            raise MachineGraphError(
                "GRAPH_PATCH_OPERATIONS_INVALID"
            )

        for operation in self.operations:
            if not isinstance(
                operation,
                GraphOperation,
            ):
                raise MachineGraphError(
                    "GRAPH_PATCH_OPERATION_TYPE_INVALID"
                )

            operation.validate()

        if self.action_authority != "NONE":
            raise MachineGraphError(
                "GRAPH_PATCH_ACTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise MachineGraphError(
                "GRAPH_PATCH_PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise MachineGraphError(
                "GRAPH_PATCH_MODEL_INFERENCE_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "base_graph_sha256":
                self.base_graph_sha256,
            "operations": [
                operation.as_dict()
                for operation
                in self.operations
            ],
            "action_authority":
                self.action_authority,
            "persistent_write":
                self.persistent_write,
            "model_inference":
                self.model_inference,
        }

    def patch_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(
    frozen=True,
    slots=True,
)
class GraphPatchResult:
    before_graph_sha256: str
    after_graph_sha256: str
    graph: MachineGraph
    inverse_patch: GraphPatch
    action_authority: str = "NONE"
    persistent_write: str = "NONE"
    model_inference: bool = False
    schema: str = PATCH_RESULT_SCHEMA

    def validate(
        self,
    ) -> None:
        if self.schema != PATCH_RESULT_SCHEMA:
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_SCHEMA_INVALID"
            )

        _require_sha256(
            self.before_graph_sha256,
            "GRAPH_PATCH_RESULT_BEFORE",
        )

        _require_sha256(
            self.after_graph_sha256,
            "GRAPH_PATCH_RESULT_AFTER",
        )

        if not isinstance(
            self.graph,
            MachineGraph,
        ):
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_GRAPH_INVALID"
            )

        self.graph.validate()

        if (
            self.graph.graph_sha256()
            != self.after_graph_sha256
        ):
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_AFTER_MISMATCH"
            )

        if not isinstance(
            self.inverse_patch,
            GraphPatch,
        ):
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_INVERSE_INVALID"
            )

        self.inverse_patch.validate()

        if (
            self.inverse_patch.base_graph_sha256
            != self.after_graph_sha256
        ):
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_INVERSE_BASE_MISMATCH"
            )

        if self.action_authority != "NONE":
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_ACTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise MachineGraphError(
                "GRAPH_PATCH_RESULT_MODEL_INFERENCE_INVALID"
            )


def apply_patch(
    graph: MachineGraph,
    patch: GraphPatch,
) -> GraphPatchResult:
    if not isinstance(
        graph,
        MachineGraph,
    ):
        raise MachineGraphError(
            "GRAPH_TYPE_INVALID"
        )

    if not isinstance(
        patch,
        GraphPatch,
    ):
        raise MachineGraphError(
            "PATCH_TYPE_INVALID"
        )

    graph.validate()
    patch.validate()

    before_sha256 = (
        graph.graph_sha256()
    )

    if (
        patch.base_graph_sha256
        != before_sha256
    ):
        raise MachineGraphError(
            "GRAPH_PATCH_BASE_MISMATCH"
        )

    nodes: dict[
        str,
        NodeSpec,
    ] = {
        node.node_id:
            node
        for node in graph.nodes
    }

    edges: dict[
        str,
        EdgeSpec,
    ] = {
        edge.edge_id:
            edge
        for edge in graph.edges
    }

    inverse_operations: list[
        GraphOperation
    ] = []

    for operation in patch.operations:
        if operation.op == OP_ADD_NODE:
            node = operation.node

            if node is None:
                raise MachineGraphError(
                    "ADD_NODE_MISSING"
                )

            if node.node_id in nodes:
                raise MachineGraphError(
                    "ADD_NODE_ALREADY_EXISTS"
                )

            nodes[
                node.node_id
            ] = node

            inverse_operations.append(
                GraphOperation(
                    op=OP_REMOVE_NODE,
                    node_id=node.node_id,
                )
            )

            continue

        if operation.op == OP_REMOVE_NODE:
            existing_node = nodes.get(
                operation.node_id
            )

            if existing_node is None:
                raise MachineGraphError(
                    "REMOVE_NODE_NOT_FOUND"
                )

            nodes.pop(
                operation.node_id
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_ADD_NODE,
                    node=existing_node,
                )
            )

            continue

        if operation.op == OP_CONNECT:
            edge = operation.edge

            if edge is None:
                raise MachineGraphError(
                    "CONNECT_EDGE_MISSING"
                )

            if edge.edge_id in edges:
                raise MachineGraphError(
                    "CONNECT_EDGE_ALREADY_EXISTS"
                )

            edges[
                edge.edge_id
            ] = edge

            inverse_operations.append(
                GraphOperation(
                    op=OP_DISCONNECT,
                    edge_id=edge.edge_id,
                )
            )

            continue

        if operation.op == OP_DISCONNECT:
            existing_edge = edges.get(
                operation.edge_id
            )

            if existing_edge is None:
                raise MachineGraphError(
                    "DISCONNECT_EDGE_NOT_FOUND"
                )

            edges.pop(
                operation.edge_id
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_CONNECT,
                    edge=existing_edge,
                )
            )

            continue

        if operation.op == OP_ENABLE_NODE:
            existing_node = nodes.get(
                operation.node_id
            )

            if existing_node is None:
                raise MachineGraphError(
                    "ENABLE_NODE_NOT_FOUND"
                )

            if existing_node.enabled:
                raise MachineGraphError(
                    "ENABLE_NODE_ALREADY_ENABLED"
                )

            nodes[
                operation.node_id
            ] = replace(
                existing_node,
                enabled=True,
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_DISABLE_NODE,
                    node_id=operation.node_id,
                )
            )

            continue

        if operation.op == OP_DISABLE_NODE:
            existing_node = nodes.get(
                operation.node_id
            )

            if existing_node is None:
                raise MachineGraphError(
                    "DISABLE_NODE_NOT_FOUND"
                )

            if not existing_node.enabled:
                raise MachineGraphError(
                    "DISABLE_NODE_ALREADY_DISABLED"
                )

            nodes[
                operation.node_id
            ] = replace(
                existing_node,
                enabled=False,
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_ENABLE_NODE,
                    node_id=operation.node_id,
                )
            )

            continue

        if operation.op == OP_ENABLE_EDGE:
            existing_edge = edges.get(
                operation.edge_id
            )

            if existing_edge is None:
                raise MachineGraphError(
                    "ENABLE_EDGE_NOT_FOUND"
                )

            if existing_edge.enabled:
                raise MachineGraphError(
                    "ENABLE_EDGE_ALREADY_ENABLED"
                )

            edges[
                operation.edge_id
            ] = replace(
                existing_edge,
                enabled=True,
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_DISABLE_EDGE,
                    edge_id=operation.edge_id,
                )
            )

            continue

        if operation.op == OP_DISABLE_EDGE:
            existing_edge = edges.get(
                operation.edge_id
            )

            if existing_edge is None:
                raise MachineGraphError(
                    "DISABLE_EDGE_NOT_FOUND"
                )

            if not existing_edge.enabled:
                raise MachineGraphError(
                    "DISABLE_EDGE_ALREADY_DISABLED"
                )

            edges[
                operation.edge_id
            ] = replace(
                existing_edge,
                enabled=False,
            )

            inverse_operations.append(
                GraphOperation(
                    op=OP_ENABLE_EDGE,
                    edge_id=operation.edge_id,
                )
            )

            continue

        raise MachineGraphError(
            "GRAPH_PATCH_OPERATION_UNREACHABLE"
        )

    candidate = MachineGraph(
        nodes=tuple(
            sorted(
                nodes.values(),
                key=lambda item:
                    item.node_id,
            )
        ),
        edges=tuple(
            sorted(
                edges.values(),
                key=lambda item:
                    item.edge_id,
            )
        ),
    )

    candidate.validate()

    after_sha256 = (
        candidate.graph_sha256()
    )

    inverse_patch = GraphPatch(
        base_graph_sha256=(
            after_sha256
        ),
        operations=tuple(
            reversed(
                inverse_operations
            )
        ),
    )

    result = GraphPatchResult(
        before_graph_sha256=(
            before_sha256
        ),
        after_graph_sha256=(
            after_sha256
        ),
        graph=candidate,
        inverse_patch=inverse_patch,
    )

    result.validate()

    return result
