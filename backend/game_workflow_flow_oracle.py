"""Independent reader for compiled routes. No compiler or source validator imports.

Checks serialized identities, ranges, geometry and directed traversal. It does
not simulate collision, pathfinding, NPC logic or a proprietary game engine.
"""
import json
import math


def inspect_bytes(data: bytes) -> dict:
    errors, warnings = [], []
    try:
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("serialized route capacity")
        doc = json.loads(data)
        if not isinstance(doc, dict):
            raise ValueError("compiled document must be an object")
        if doc.get("schema") != "gg.game-workflows.flow-compiled.v1" or doc.get("coordinates") != {"up": "Y", "handedness": "right", "meters_per_unit": 1}:
            raise ValueError("compiled schema/frame")
        nodes, edges, routes = (doc.get(k) for k in ("nodes", "edges", "routes"))
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 8192 or not isinstance(edges, list) or len(edges) > 8192 or not isinstance(routes, list) or len(routes) > 1024:
            raise ValueError("collection capacity")
        for rows, label in ((nodes, "node"), (edges, "edge"), (routes, "route")):
            identities = [row["id"] for row in rows]
            if any(not isinstance(identity, str) or not identity for identity in identities) or len(identities) != len(set(identities)):
                raise ValueError("duplicate/invalid " + label + " identity")
        def position(value):
            return isinstance(value, list) and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 10000000 for v in value)
        if any(not position(node["position"]) for node in nodes):
            raise ValueError("non-finite node geometry")
        links, lookup, total_points = [set() for _ in nodes], {}, 0
        for edge in edges:
            a, b, points = edge["from"], edge["to"], edge["points"]
            if type(a) is not int or type(b) is not int or not 0 <= a < len(nodes) or not 0 <= b < len(nodes):
                raise ValueError("node index range")
            if type(edge["directed"]) is not bool or not isinstance(points, list) or not 2 <= len(points) <= 4096 or not all(position(point) for point in points):
                raise ValueError("edge geometry/direction")
            total_points += len(points)
            if total_points > 32768:
                raise ValueError("point capacity")
            if math.dist(points[0], nodes[a]["position"]) > 0.00001 or math.dist(points[-1], nodes[b]["position"]) > 0.00001:
                raise ValueError("serialized endpoint mismatch")
            transition = edge.get("transition", "MOVE")
            lengths = [math.dist(x, y) for x, y in zip(points, points[1:])]
            if transition not in ("MOVE", "DWELL") or (transition == "MOVE" and any(length < 0.000001 for length in lengths)) or (transition == "DWELL" and any(length > 0.00001 for length in lengths)):
                raise ValueError("invalid movement/dwell geometry")
            width = edge["width_m"]
            if type(width) not in (float, int) or not math.isfinite(width) or not 0.001 <= width <= 10000:
                raise ValueError("width range")
            links[a].add(b); links[b].add(a)
            lookup[edge["id"]] = edge
        for route in routes:
            legs, mode, chain = route["edges"], route["mode"], []
            if mode not in ("ONCE", "LOOP", "PING_PONG") or not isinstance(legs, list) or not 1 <= len(legs) <= 4096:
                raise ValueError("route mode/length")
            for leg in legs:
                edge = lookup[leg["edge_id"]]
                reverse = leg["reverse"]
                if type(reverse) is not bool or (reverse and edge["directed"]) or (mode == "PING_PONG" and edge["directed"]):
                    raise ValueError("one-way traversal")
                start, end = (edge["to"], edge["from"]) if reverse else (edge["from"], edge["to"])
                if chain and chain[-1] != start:
                    raise ValueError("route continuity")
                if not chain:
                    chain.append(start)
                chain.append(end)
            if route["node_indices"] != chain or (mode == "LOOP" and chain[0] != chain[-1]):
                raise ValueError("route chain/closure")
        seen, components = set(), 0
        for index in range(len(nodes)):
            if index in seen:
                continue
            components += 1
            pending = [index]; seen.add(index)
            while pending:
                for target in links[pending.pop()]:
                    if target not in seen:
                        seen.add(target); pending.append(target)
        if components > 1:
            warnings.append(f"{components} disconnected components; no junctions were inferred from crossings.")
        isolated = sum(not item for item in links)
        if isolated:
            warnings.append(f"{isolated} isolated nodes.")
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "scope": "SERIALIZED_GRAPH_STRUCTURE_AND_TRAVERSAL", "behavior_verified": False}
