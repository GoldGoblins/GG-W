"""Run with Blender --background --factory-startup --python this-file.

Uses original synthetic graph data in a temporary directory. Tests actual bpy
curves, identity-preserving rename, coordinates, shared endpoints and preview.
"""
import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tools/blender"))
from backend import game_workflow_common as common, game_workflow_flow as flow
import gg_game_workflow_routes as routes
import bpy


def main():
    with tempfile.TemporaryDirectory(prefix="gg-flow-blender-test-") as temporary:
        common.ROOT = Path(temporary) / "state"
        document = {"schema": flow.SCHEMA, "game": "Ratchet / synthetic traversal fixture",
            "coordinates": {"up": "Z", "handedness": "right", "meters_per_unit": .01},
            "nodes": [{"id": "a", "position": [0, 0, 0]}, {"id": "b", "position": [100, 0, 200]}, {"id": "c", "position": [200, 0, 200]}],
            "edges": [{"id": "ab", "from": "a", "to": "b", "directed": False}, {"id": "bc", "from": "b", "to": "c", "directed": False}],
            "routes": [{"id": "patrol", "mode": "PING_PONG", "edges": ["ab", "bc"]}]}
        original_count = len(bpy.context.scene.objects)
        source = flow.save(document)["packet_path"]
        collection = routes.import_flow(source)
        assert len(bpy.context.scene.objects) == original_count + 5
        baseline = routes.export_flow(collection)
        assert not baseline["written"]
        assert baseline["compiled"] == flow.compile_graph(document)
        edge = next(obj for obj in collection.objects if obj.get("gg_flow_edge_id") == "ab")
        edge.name = "Renamed according to the game's design"
        assert routes.export_flow(collection)["compiled"] == baseline["compiled"]
        shared = next(obj for obj in collection.objects if obj.get("gg_flow_node_id") == "b")
        shared.location.x += .5
        result = routes.export_flow(collection, apply=True)
        assert result["written"] and result["oracle"]["valid"]
        moved = next(node for node in result["compiled"]["nodes"] if node["id"] == "b")
        assert moved["position"] == [1.5, 2, 0]
        assert common.read_json(source)[1] == document
        # A curve endpoint edit and an independent node edit must agree.
        edge.data.splines[0].points[-1].co.x = 3
        try:
            routes.export_flow(collection)
        except ValueError as exc:
            assert str(exc) == "CONFLICTING_SHARED_ENDPOINT_EDITS"
        else:
            raise AssertionError("conflicting shared endpoint silently accepted")
        print("GAME_WORKFLOWS_BLENDER=PASS")


if __name__ == "__main__":
    main()
