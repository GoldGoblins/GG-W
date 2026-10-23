"""Game-independent route authoring and GG map round trips inspired by GTA Flow.

No road/NPC type is inferred from a mesh or game title. Connectivity is authored
with node IDs; crossing polylines do not create implicit junctions.
"""
from __future__ import annotations

import copy
import json
import math

from backend import game_workflow_common as common

SCHEMA = "gg.game-workflows.flow.v1"
COMPILED_SCHEMA = "gg.game-workflows.flow-compiled.v1"
MAX_NODES, MAX_EDGES, MAX_ROUTES, MAX_POINTS = 8192, 8192, 1024, 32768


def _number(value, *, low=-10000000, high=10000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("INVALID_FINITE_NUMBER")
    return float(value)


def _id(value):
    if not isinstance(value, str) or not value or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise ValueError("INVALID_STABLE_ID")
    return value


def _coordinates(value):
    if not isinstance(value, dict) or value.get("up") not in ("Y", "Z") or value.get("handedness") not in ("right", "left"):
        raise ValueError("EXPLICIT_COORDINATE_FRAME_REQUIRED")
    scale = _number(value.get("meters_per_unit"), low=0.000001, high=1000000)
    return value["up"], value["handedness"], scale


def to_engine(point, coordinates):
    up, handedness, scale = _coordinates(coordinates)
    if not isinstance(point, list) or len(point) != 3:
        raise ValueError("THREE_COORDINATES_REQUIRED")
    x, y, z = (_number(v) * scale for v in point)
    if handedness == "left":
        x = -x
    result = [x, y, z] if up == "Y" else [x, z, -y]
    if any(abs(v) > 10000000 for v in result):
        raise ValueError("CANONICAL_COORDINATE_LIMIT")
    return result


def from_engine(point, coordinates):
    up, handedness, scale = _coordinates(coordinates)
    x, y, z = point if up == "Y" else [point[0], -point[2], point[1]]
    if handedness == "left":
        x = -x
    return [v / scale for v in (x, y, z)]


def compile_graph(document: dict) -> dict:
    if document.get("schema") != SCHEMA:
        raise ValueError("FLOW_DOCUMENT_REQUIRED")
    coordinates = document.get("coordinates")
    _coordinates(coordinates)
    nodes, edges, routes = (document.get(k, []) for k in ("nodes", "edges", "routes"))
    if any(not isinstance(v, list) for v in (nodes, edges, routes)) or not 1 <= len(nodes) <= MAX_NODES or len(edges) > MAX_EDGES or len(routes) > MAX_ROUTES:
        raise ValueError("FLOW_CAPACITY_LIMIT")
    node_map, edge_map, source_positions = {}, {}, {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("NODE_OBJECT_REQUIRED")
        identity = _id(node.get("id"))
        if identity in node_map:
            raise ValueError("DUPLICATE_NODE_ID")
        node_map[identity] = {**node, "position": to_engine(node.get("position"), coordinates)}
        source_positions[identity] = node["position"]
    sorted_nodes = sorted(node_map)
    indices = {identity: index for index, identity in enumerate(sorted_nodes)}
    total_points = 0
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("EDGE_OBJECT_REQUIRED")
        identity = _id(edge.get("id"))
        if identity in edge_map:
            raise ValueError("DUPLICATE_EDGE_ID")
        start, end = edge.get("from"), edge.get("to")
        if start not in node_map or end not in node_map:
            raise ValueError("EDGE_ENDPOINT_MISSING")
        if not isinstance(edge.get("directed", True), bool):
            raise ValueError("EDGE_DIRECTION_MUST_BE_BOOLEAN")
        points = edge.get("points", [source_positions[start], source_positions[end]])
        if not isinstance(points, list) or not 2 <= len(points) <= 4096:
            raise ValueError("EDGE_POINT_LIMIT")
        total_points += len(points)
        if total_points > MAX_POINTS:
            raise ValueError("TOTAL_POINT_LIMIT")
        points = [to_engine(point, coordinates) for point in points]
        for point, expected in ((points[0], node_map[start]["position"]), (points[-1], node_map[end]["position"])):
            if math.dist(point, expected) > 0.00001:
                raise ValueError("EDGE_ENDPOINT_POSITION_MISMATCH")
        transition = edge.get("transition", "MOVE")
        if transition not in ("MOVE", "DWELL"):
            raise ValueError("UNKNOWN_TRANSITION_KIND")
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        if (transition == "MOVE" and any(length < 0.000001 for length in lengths)) or (transition == "DWELL" and any(length > 0.00001 for length in lengths)):
            raise ValueError("ZERO_LENGTH_MOVE_OR_NONZERO_DWELL")
        width = _number(edge.get("width_m", 1), low=0.001, high=10000)
        edge_map[identity] = {**edge, "id": identity, "from": indices[start], "to": indices[end],
                              "directed": edge.get("directed", True), "points": points, "width_m": width, "transition": transition}
    compiled_routes, route_ids = [], set()
    for route in routes:
        if not isinstance(route, dict):
            raise ValueError("ROUTE_OBJECT_REQUIRED")
        identity = _id(route.get("id"))
        if identity in route_ids:
            raise ValueError("DUPLICATE_ROUTE_ID")
        route_ids.add(identity)
        mode, legs = route.get("mode", "ONCE"), route.get("edges", [])
        if mode not in ("LOOP", "PING_PONG", "ONCE") or not isinstance(legs, list) or not 1 <= len(legs) <= 4096:
            raise ValueError("INVALID_ROUTE_MODE_OR_LEGS")
        visited, normalized = [], []
        for leg in legs:
            name, reverse = (leg, False) if isinstance(leg, str) else (leg.get("edge_id"), leg.get("reverse", False)) if isinstance(leg, dict) else (None, False)
            if name not in edge_map or not isinstance(reverse, bool):
                raise ValueError("ROUTE_EDGE_MISSING")
            edge = edge_map[name]
            if reverse and edge["directed"]:
                raise ValueError("ONE_WAY_EDGE_REVERSED")
            start, end = (edge["to"], edge["from"]) if reverse else (edge["from"], edge["to"])
            if visited and visited[-1] != start:
                raise ValueError("ROUTE_DISCONTINUITY")
            if not visited:
                visited.append(start)
            visited.append(end)
            normalized.append({"edge_id": name, "reverse": reverse})
        if mode == "LOOP" and visited[-1] != visited[0]:
            raise ValueError("LOOP_NOT_CLOSED")
        if mode == "PING_PONG" and any(edge_map[leg["edge_id"]]["directed"] for leg in normalized):
            raise ValueError("PING_PONG_REQUIRES_BIDIRECTIONAL_EDGES")
        compiled_routes.append({**route, "edges": normalized, "mode": mode, "node_indices": visited})
    return {"schema": COMPILED_SCHEMA, "game": str(document.get("game", ""))[:120],
            "coordinates": {"up": "Y", "handedness": "right", "meters_per_unit": 1},
            "nodes": [node_map[identity] for identity in sorted_nodes], "edges": [edge_map[identity] for identity in sorted(edge_map)],
            "routes": sorted(compiled_routes, key=lambda r: r["id"])}


def validate(document: dict) -> dict:
    from backend.game_workflow_flow_oracle import inspect_bytes
    compiled = compile_graph(document)
    data = json.dumps(compiled, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    oracle = inspect_bytes(data)
    if not oracle["valid"]:
        raise ValueError("INDEPENDENT_ROUTE_CHECK_FAILED: " + "; ".join(oracle["errors"])[:512])
    return {"status": "READY", "summary": f"{len(compiled['nodes'])} nodes · {len(compiled['edges'])} edges · {len(compiled['routes'])} routes",
            "compiled": compiled, "oracle": oracle}


def save(document: dict) -> dict:
    result = validate(document)
    source = common.packet("flow", document)
    compiled = common.packet("flow-compiled", result["compiled"])
    return {**result, "packet_path": str(source), "compiled_path": str(compiled)}


def _gg_coordinates(original):
    schema = original.get("schema")
    expected = "WORLD_METRES" if schema == "gg.world-places.v1" else "ISLAND_AUTHORING_METRES"
    if original.get("coordinates") != expected:
        raise ValueError("GG_MAP_COORDINATE_CONVENTION_UNSUPPORTED")
    scale = 1.0
    if schema == "gg.settlement.v1":
        from backend.game_engine_world import ISLAND_LAYOUT_SCALE
        scale = ISLAND_LAYOUT_SCALE
    return {"up": "Y", "handedness": "right", "meters_per_unit": scale}


def import_map(raw: str, game: str = "") -> dict:
    path, original, fingerprint = common.read_json(raw)
    if original.get("schema") == SCHEMA:
        return save(original)
    schema = original.get("schema")
    if schema not in ("gg.world-places.v1", "gg.settlement.v1"):
        raise ValueError("FLOW_OR_GG_MAP_REQUIRED")
    coordinates = _gg_coordinates(original)
    scale = coordinates["meters_per_unit"]
    document = {"schema": SCHEMA, "game": str(game)[:120],
                "coordinates": coordinates,
                "nodes": [], "edges": [], "routes": [],
                "binding": {"source_path": str(path), "source_sha256": fingerprint, "schema": schema,
                            "coordinates": copy.deepcopy(coordinates)}}
    binding = []
    for field in ("roads", "residents" if schema == "gg.world-places.v1" else "routines"):
        for row in original.get(field, []):
            identity = _id(row.get("id"))
            stop_key = "points" if field == "roads" else "stops"
            points = row.get(stop_key, [])
            if len(points) < 2:
                raise ValueError("GG_ROUTE_NEEDS_AT_LEAST_TWO_POINTS")
            node_ids = []
            for index, point in enumerate(points):
                if not isinstance(point, list) or len(point) < 2:
                    raise ValueError("INVALID_GG_ROUTE_POINT")
                name = f"{field}:{identity}:p{index}"
                metadata = {"wait_s": point[2], "activity": point[3] if len(point) > 3 else "TRAVELING"} if stop_key == "stops" else {}
                document["nodes"].append({"id": name, "position": [point[0], 0, point[1]], **metadata})
                node_ids.append(name)
            mode = "ONCE" if field == "roads" else row.get("route_mode", "LOOP")
            pairs = list(zip(node_ids, node_ids[1:]))
            if mode == "LOOP":
                pairs.append((node_ids[-1], node_ids[0]))
            edge_ids = []
            source_points = {node["id"]: node["position"] for node in document["nodes"][-len(node_ids):]}
            for index, (start, end) in enumerate(pairs):
                edge_id = f"{field}:{identity}:e{index}"
                document["edges"].append({"id": edge_id, "from": start, "to": end, "directed": False,
                                           "agent": "pedestrian" if stop_key == "stops" else "path",
                                           "transition": "DWELL" if stop_key == "stops" and source_points[start] == source_points[end] else "MOVE",
                                           "width_m": row.get("width_m", 1) * scale if field == "roads" else 1})
                edge_ids.append(edge_id)
            route_id = field + ":" + identity
            document["routes"].append({"id": route_id, "edges": edge_ids, "mode": mode})
            binding.append({"field": field, "id": identity, "route_id": route_id, "node_ids": node_ids,
                            "edge_ids": edge_ids, "point_key": stop_key})
    document["binding"]["rows"] = binding
    return save(document)


def export_map(raw: str) -> dict:
    _, document, _ = common.read_json(raw)
    result = validate(document)
    binding = document.get("binding", {})
    if not isinstance(binding, dict) or binding.get("schema") not in ("gg.world-places.v1", "gg.settlement.v1"):
        raise ValueError("GG_MAP_BINDING_REQUIRED")
    path, original, fingerprint = common.read_json(binding.get("source_path", ""))
    if fingerprint != binding.get("source_sha256") or original.get("schema") != binding["schema"]:
        raise ValueError("ORIGINAL_MAP_CHANGED_REIMPORT_REQUIRED")
    output = copy.deepcopy(original)
    original_coordinates = _gg_coordinates(original)
    nodes = {row["id"]: row for row in document["nodes"]}
    routes = {row["id"]: row for row in document["routes"]}
    edges = {row["id"]: row for row in document["edges"]}
    for row in binding.get("rows", []):
        source_rows = {item["id"]: item for item in output[row["field"]]}
        target = source_rows[row["id"]]
        route = routes[row["route_id"]]
        if route["edges"] != row["edge_ids"] or any(name not in nodes for name in row["node_ids"]):
            raise ValueError("GG_ADAPTER_TOPOLOGY_CHANGED_USE_GENERIC_FLOW_EXPORT")
        expected_pairs = list(zip(row["node_ids"], row["node_ids"][1:]))
        if route.get("mode", "ONCE") == "LOOP":
            expected_pairs.append((row["node_ids"][-1], row["node_ids"][0]))
        if len(expected_pairs) != len(row["edge_ids"]) or any(
            (edges[name]["from"], edges[name]["to"]) != pair or len(edges[name].get("points", [])) not in (0, 2)
            for name, pair in zip(row["edge_ids"], expected_pairs)):
            raise ValueError("GG_ADAPTER_TOPOLOGY_CHANGED_USE_GENERIC_FLOW_EXPORT")
        # This adapter preserves GG's stop metadata and 2D authoring schema.
        points = copy.deepcopy(target[row["point_key"]])
        for point, name in zip(points, row["node_ids"]):
            position = to_engine(nodes[name]["position"], document["coordinates"])
            x, y, z = from_engine(position, original_coordinates)
            if abs(y) > 0.00001:
                raise ValueError("GG_2D_ROUTE_CANNOT_PRESERVE_ELEVATION")
            point[:2] = [round(x, 6), round(z, 6)]
            if row["point_key"] == "stops":
                wait = _number(nodes[name].get("wait_s", point[2]), low=0, high=86400)
                point[2] = wait
                activity = str(nodes[name].get("activity", point[3] if len(point) > 3 else "TRAVELING"))
                if len(activity) > 80:
                    raise ValueError("ACTIVITY_LIMIT")
                if len(point) > 3 or activity != "TRAVELING":
                    point[3:] = [activity]
        target[row["point_key"]] = points
        if row["point_key"] == "stops":
            mode = route.get("mode", "LOOP")
            if mode not in ("LOOP", "PING_PONG"):
                raise ValueError("GG_RESIDENT_MODE_UNSUPPORTED")
            if mode != target.get("route_mode", "LOOP"):
                target["route_mode"] = mode
        else:
            widths = {edges[name].get("width_m", 1) for name in row["edge_ids"]}
            if len(widths) != 1:
                raise ValueError("GG_ROAD_REQUIRES_UNIFORM_WIDTH")
            width = widths.pop() / original_coordinates["meters_per_unit"]
            if not math.isclose(width, target["width_m"], abs_tol=0.000001, rel_tol=0):
                target["width_m"] = round(width, 6)
    output_path = common.packet("gg-map-candidate", output)
    return {"status": "READY", "summary": "GG map candidate exported · original map preserved", "changed": output != original,
            "packet_path": str(output_path), "original_path": str(path), "oracle": result["oracle"],
            "limits": ["Review and apply through the existing Blender/map authoring workflow; this export does not replace the live map."]}
