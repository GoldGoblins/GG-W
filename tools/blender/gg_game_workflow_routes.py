"""Editable, tagged route curves for any game, with preview-first GG exports.

In Blender's Python console:
  import sys; sys.path.insert(0, '/home/GG/GoldGoblins/projects/gg-ai-desktop/tools/blender')
  import gg_game_workflow_routes as routes
  collection = routes.import_flow('/path/to/flow-packet.json')
  routes.export_flow(collection)             # validate and preview
  routes.export_flow(collection, apply=True) # write a new GG workflow packet

Only a new collection is authored. Existing maps and scenes are not replaced.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from backend import game_workflow_common as common, game_workflow_flow as flow


def _to_blender(point, coordinates):
    x, y, z = flow.to_engine(point, coordinates)
    return (x, -z, y)


def _from_blender(point, coordinates):
    return flow.from_engine([float(point.x), float(point.z), -float(point.y)], coordinates)


def import_flow(raw: str, *, scene=None):
    import bpy
    path, document, fingerprint = common.read_json(raw)
    flow.validate(document)
    target = scene or bpy.context.scene
    collection = bpy.data.collections.new("GG_Game_Routes")
    target.collection.children.link(collection)
    collection["gg_flow_document"] = json.dumps(document, allow_nan=False)
    collection["gg_flow_source"] = str(path)
    collection["gg_flow_source_sha256"] = fingerprint
    collection["gg_flow_routes"] = json.dumps(document.get("routes", []), allow_nan=False)
    coordinates = document["coordinates"]
    nodes = {node["id"]: node for node in document["nodes"]}
    for node in nodes.values():
        obj = bpy.data.objects.new(node["id"], None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.25
        obj.location = _to_blender(node["position"], coordinates)
        obj["gg_flow_node_id"] = node["id"]
        obj["gg_flow_metadata"] = json.dumps(node, allow_nan=False)
        collection.objects.link(obj)
    for edge in document["edges"]:
        curve = bpy.data.curves.new(edge["id"], "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = 0.035
        spline = curve.splines.new("POLY")
        points = edge.get("points", [nodes[edge["from"]]["position"], nodes[edge["to"]]["position"]])
        spline.points.add(len(points) - 1)
        for vertex, point in zip(spline.points, points):
            vertex.co = (*_to_blender(point, coordinates), 1)
        obj = bpy.data.objects.new(edge["id"], curve)
        obj["gg_flow_edge_id"] = edge["id"]
        obj["gg_flow_from"] = edge["from"]
        obj["gg_flow_to"] = edge["to"]
        obj["gg_flow_directed"] = edge.get("directed", True)
        obj["gg_flow_width_m"] = edge.get("width_m", 1)
        obj["gg_flow_metadata"] = json.dumps(edge, allow_nan=False)
        collection.objects.link(obj)
    target.view_layers[0].update()
    return collection


def export_flow(collection, *, apply: bool = False):
    import bpy
    if isinstance(collection, str):
        collection = bpy.data.collections.get(collection)
    if collection is None or not collection.get("gg_flow_document"):
        raise ValueError("SELECT_GAME_WORKFLOW_COLLECTION")
    bpy.context.view_layer.update()
    original = common.parse_json(collection["gg_flow_document"].encode())
    _, _, fingerprint = common.read_json(collection["gg_flow_source"])
    if fingerprint != collection["gg_flow_source_sha256"]:
        raise ValueError("FLOW_SOURCE_CHANGED_REIMPORT_REQUIRED")
    document = copy.deepcopy(original)
    coordinates = document["coordinates"]
    source_nodes = {node["id"]: node for node in original["nodes"]}
    nodes, edges, proposals = {}, {}, {}
    import math
    for obj in collection.all_objects:
        identity = obj.get("gg_flow_node_id")
        if identity:
            if identity in nodes:
                raise ValueError("DUPLICATE_BLENDER_NODE_ID")
            node = json.loads(obj.get("gg_flow_metadata", "{}"))
            node.update(id=identity, position=_from_blender(obj.matrix_world.translation, coordinates))
            nodes[identity] = node
        identity = obj.get("gg_flow_edge_id")
        if identity:
            if identity in edges:
                raise ValueError("DUPLICATE_BLENDER_EDGE_ID")
            if obj.type != "CURVE" or len(obj.data.splines) != 1 or obj.data.splines[0].type != "POLY":
                raise ValueError("ONE_POLY_CENTERLINE_REQUIRED")
            spline = obj.data.splines[0]
            if spline.use_cyclic_u:
                raise ValueError("CLOSE_ROUTES_WITH_EXPLICIT_EDGES")
            edge = json.loads(obj.get("gg_flow_metadata", "{}"))
            edge.update(id=identity, **{"from": obj.get("gg_flow_from"), "to": obj.get("gg_flow_to")},
                        directed=bool(obj.get("gg_flow_directed", True)), width_m=float(obj.get("gg_flow_width_m", 1)),
                        points=[_from_blender(obj.matrix_world @ point.co.xyz, coordinates) for point in spline.points])
            edges[identity] = edge
    if set(source_nodes) - set(nodes) or {edge["id"] for edge in original["edges"]} - set(edges):
        raise ValueError("MISSING_TAGGED_OBJECT_UPDATE_ROUTE_TOPOLOGY_FIRST")
    # Reconcile an edited shared curve endpoint with the matching node, while
    # rejecting conflicting independent edits. No spatial junction inference.
    for edge in edges.values():
        for index, node_id in ((0, edge["from"]), (-1, edge["to"])):
            if node_id not in nodes or len(edge["points"]) < 2:
                raise ValueError("BLENDER_EDGE_ENDPOINT_MISSING")
            old = source_nodes.get(node_id, nodes[node_id])["position"]
            curve_point = edge["points"][index]
            if math.dist(flow.to_engine(curve_point, coordinates), flow.to_engine(old, coordinates)) > 0.00001:
                proposals.setdefault(node_id, []).append(curve_point)
    for identity, values in proposals.items():
        node_point = nodes[identity]["position"]
        old = source_nodes.get(identity, nodes[identity])["position"]
        if math.dist(flow.to_engine(node_point, coordinates), flow.to_engine(old, coordinates)) > 0.00001:
            values.append(node_point)
        if any(math.dist(flow.to_engine(point, coordinates), flow.to_engine(values[0], coordinates)) > 0.00001 for point in values[1:]):
            raise ValueError("CONFLICTING_SHARED_ENDPOINT_EDITS")
        nodes[identity]["position"] = values[0]
    for edge in edges.values():
        edge["points"][0] = nodes[edge["from"]]["position"]
        edge["points"][-1] = nodes[edge["to"]]["position"]
    document["nodes"] = sorted(nodes.values(), key=lambda row: row["id"])
    document["edges"] = sorted(edges.values(), key=lambda row: row["id"])
    document["routes"] = json.loads(collection["gg_flow_routes"])
    result = flow.save(document) if apply else flow.validate(document)
    return {**result, "document": document, "written": apply, "changed": document != original}
