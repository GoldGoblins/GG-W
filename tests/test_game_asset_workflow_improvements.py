"""Dependency, collection, source-preservation and real-library regressions."""
from __future__ import annotations

import json
from collections import OrderedDict
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import game_workflow_common as common, game_workflow_scout as scout
from backend import game_workflow_formats as formats, game_workflow_collections as collections
from backend import game_workflow_rig as rig, game_workflow_dependencies as deps
from backend import game_engine_asset_editor as editor, game_engine_assets as assets
from backend import game_asset_resources as resources, game_workflow_profile as profile


def fixture_dae():
    return b'''<COLLADA><asset><unit meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_geometries><geometry id="mesh"><mesh>
<source id="positions"><float_array count="9">0 0 0 1 0 0 0 0 1</float_array><technique_common><accessor count="3" stride="3"/></technique_common></source>
<source id="uv"><float_array count="6">0 0 1 0 0 1</float_array><technique_common><accessor count="3" stride="2"/></technique_common></source>
<source id="norm"><float_array count="3">0 -1 0</float_array><technique_common><accessor count="1" stride="3"/></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="1" material="surface"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><input semantic="NORMAL" source="#norm" offset="2"/><p>0 0 0 1 1 0 2 2 0</p></triangles>
</mesh></geometry></library_geometries>
<library_materials><material id="mat"/></library_materials>
<library_controllers><controller id="skin"><skin source="#mesh">
<source id="joints"><Name_array count="1">J0</Name_array><technique_common><accessor count="1" stride="1"/></technique_common></source>
<source id="ibm"><float_array count="16">1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1</float_array><technique_common><accessor count="1" stride="16"/></technique_common></source>
<source id="weights"><float_array count="1">1</float_array><technique_common><accessor count="1" stride="1"/></technique_common></source>
<joints><input semantic="JOINT" source="#joints"/><input semantic="INV_BIND_MATRIX" source="#ibm"/></joints>
<vertex_weights count="3"><input semantic="JOINT" source="#joints" offset="0"/><input semantic="WEIGHT" source="#weights" offset="1"/><vcount>1 1 1</vcount><v>0 0 0 0 0 0</v></vertex_weights>
</skin></controller></library_controllers>
<library_visual_scenes><visual_scene><node id="Skel0" name="Skel0" sid="J0" type="JOINT"><matrix>1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1</matrix></node>
<node id="Object"><instance_controller url="#skin"><bind_material><technique_common><instance_material symbol="surface" target="#mat"/></technique_common></bind_material></instance_controller></node>
</visual_scene></library_visual_scenes></COLLADA>'''


def fixture_smd():
    return b'version 1\nnodes\n0 "Skel0" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\ntime 30\n0 0 0 0 0 0 1.5707963267948966\nend\n'


class Improvements(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gg-asset-improvements-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.enterContext(patch.object(common, "ROOT", self.root / "state"))

    def file(self, name, data):
        path = self.library / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(data).encode() if isinstance(data, dict) else data)
        return path

    def test_real_shared_character_editor_and_runtime_agree(self):
        path = (assets.ASSET_ROOT / "authored/variants/characters/gg-crew-briarstride-articulated-v1.glb").resolve()
        before = common.digest(path.read_bytes())
        checked = assets.inspect_asset(str(path))
        document, buffers = editor.read_model(path)
        self.assertEqual(checked["status"], "READY")
        self.assertEqual(len(document["skins"][0]["joints"]), checked["skeleton"]["joints"])
        self.assertTrue(any("../../characters/shared" in row.get("uri", "") for row in document["buffers"]))
        position = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
        self.assertEqual(len(editor.accessor(document, buffers, position)), document["accessors"][position]["count"])
        self.assertEqual(common.digest(path.read_bytes()), before)

    def test_editor_cache_sees_external_buffer_change_with_same_mtime(self):
        self.enterContext(patch.object(assets, "ASSET_ROOT", self.library))
        buffer = self.file("positions.bin", struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0))
        model = self.file("model.gltf", {"asset": {"version": "2.0"}, "buffers": [{"uri": "positions.bin", "byteLength": 36}],
                     "bufferViews": [{"buffer": 0, "byteLength": 36}], "accessors": [{"bufferView": 0, "count": 3, "type": "VEC3", "componentType": 5126}],
                     "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})
        instance = editor.AssetEditor.__new__(editor.AssetEditor)
        instance.details, instance.detail_references = OrderedDict(), OrderedDict()
        first = instance.detail(str(model))
        self.assertIs(instance.detail(str(model)), first)
        stat = buffer.stat()
        buffer.write_bytes(struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 1, 0))
        os.utime(buffer, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertIsNot(instance.detail(str(model)), first)

    def test_editor_allows_shared_root_but_refuses_escape_and_remote(self):
        self.enterContext(patch.object(assets, "ASSET_ROOT", self.library))
        self.file("shared/data.bin", b"safe")
        model = self.file("variants/model.gltf", {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4, "uri": "../shared/data.bin"}]})
        self.assertEqual(editor.read_model(model)[1], [b"safe"])
        outside = self.root / "outside.bin"
        outside.write_bytes(b"nope")
        for uri in ("../../outside.bin", "https://example.invalid/buf", "file:///etc/passwd", "../shared/data.bin?x=1", "../shared/data.bin%23frag"):
            model.write_text(json.dumps({"buffers": [{"byteLength": 4, "uri": uri}]}))
            with self.assertRaises(ValueError):
                editor.read_model(model)
            self.assertIsNotNone(assets._validate_buffer_uris(model, json.loads(model.read_text()))[1])

    def test_symlink_parent_reference_and_cumulative_buffer_budget(self):
        self.enterContext(patch.object(assets, "ASSET_ROOT", self.library))
        self.file("shared/data.bin", b"abcd")
        if os.name=='nt':
            from backend.application_paths import expose_directory
            expose_directory(self.library / 'alias',self.library / 'shared')
        else:
            (self.library / "alias").symlink_to(self.library / "shared", target_is_directory=True)
        path = self.file("model.gltf", {"buffers": [{"uri": "alias/data.bin", "byteLength": 4}]})
        with self.assertRaisesRegex(ValueError, "SYMLINK"):
            editor.read_model(path)
        self.file("shared/data.bin", b"a" * 512)
        path.write_text(json.dumps({"buffers": [{"uri": "shared/data.bin", "byteLength": 512}] * 2}))
        with patch.object(assets, "MAX_REFERENCED_BYTES", 700):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                editor.read_model(path)
        with self.assertRaisesRegex(ValueError, "LIMIT"):
            resources.data_uri("data:;base64," + "YQ==" * 50, 8)

    def test_real_daxter_keeps_layered_and_duplicate_faces(self):
        path = assets.ASSET_ROOT / "authored/concept/refs/ps2-models/daxter/Daxter.obj"
        observed = formats.inspect(path.read_bytes(), ".obj")["metadata"]
        self.assertEqual(observed["triangles"], 1356)
        self.assertEqual(observed["duplicate_position_index_faces"], 37)
        self.assertEqual(observed["geometric_coincident_faces"], 61)
        self.assertGreater(observed["coincident_material_layers"], 0)

    def test_obj_negative_indices_preserve_uv_normal_and_reject_bounds(self):
        value = formats.inspect(b'v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvn 0 0 1\nusemtl iris\nf -3/1/1 -2/1/1 -1/1/1\n', ".obj")
        self.assertEqual(value["metadata"]["triangles_by_material"], {"iris": 1})
        for bad in (b"v 0 0 0\nf 0 1 1", b"v nan 0 0", b"v 0 0 0\nf 1 1 2"):
            with self.assertRaises(ValueError):
                formats.inspect(bad, ".obj")

    def test_real_ggflora_indices_are_checked(self):
        path = next(assets.ASSET_ROOT.rglob("*.ggmesh"))
        data = path.read_bytes()
        observed = formats.inspect(data, ".ggmesh")
        stride, vertices, indices = struct.unpack_from("<III", data, 8)
        self.assertEqual(observed["metadata"]["triangles"], indices // 3)
        altered = bytearray(data)
        struct.pack_into("<I", altered, 20 + vertices * stride, vertices)
        with self.assertRaisesRegex(ValueError, "OUT_OF_RANGE"):
            formats.inspect(bytes(altered), ".ggmesh")
        with self.assertRaises(ValueError):
            formats.inspect(data[:-1], ".ggmesh")

    def test_real_dae_aliases_stale_weight_count_is_visible(self):
        path = assets.ASSET_ROOT / "authored/concept/refs/ps2-models/qwark/Captain Qwark/Qwark.dae"
        value = formats.inspect(path.read_bytes(), ".dae")["metadata"]
        self.assertIn(["Skel0", "J0"], value["joint_aliases"])
        self.assertEqual(value["joint_counts"], [92])
        self.assertEqual(value["weight_profiles"][0]["max_influences"], 3)
        self.assertEqual(value["export_array_count_issues"][0]["actual_values"], 3989)
        self.assertEqual(value["export_array_count_issues"][0]["declared_values"], 9820)

    def test_dae_dtd_bad_joint_weight_range_and_primitives_rejected(self):
        for data in (b'<!DOCTYPE COLLADA [<!ENTITY x "value">]><COLLADA/>', fixture_dae().replace(b'<v>0 0 0 0 0 0</v>', b'<v>9 0 0 0 0 0</v>'), fixture_dae().replace(b'<triangles', b'<polylist').replace(b'</triangles>', b'</polylist>')):
            with self.assertRaises(ValueError):
                formats.inspect(data, ".dae")

    def test_smd_cycle_duplicate_sample_and_nonfinite_rejected(self):
        for data in (fixture_smd().replace(b'"Skel0" -1', b'"Skel0" 0'), fixture_smd().replace(b'time 30', b'time 0'), fixture_smd().replace(b'1.5707963267948966', b'nan')):
            with self.assertRaises(ValueError):
                formats.inspect(data, ".smd")
        self.assertEqual(formats.inspect(fixture_smd(), ".smd")["metadata"]["fps"], "UNDECLARED")

    def test_dependency_changes_invalidate_asset_and_annotation_even_with_same_mtime(self):
        buffer = self.file("shared.bin", b"aaaa")
        model = self.file("model.gltf", {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4, "uri": "shared.bin"}]})
        scout.index(str(self.library))
        asset = scout.search("model")["hits"][0]
        scout.annotate(asset["key"], "approved_skin")
        before = buffer.stat()
        buffer.write_bytes(b"bbbb")
        os.utime(buffer, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(scout.search("approved_skin")["hits"], [])
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_CHANGED"):
            scout.asset(asset["key"])
        self.assertEqual(scout.index(str(self.library))["updated"], 2)
        self.assertIsNone(scout.search("model")["hits"][0]["annotation"])
        self.assertEqual(json.loads(model.read_text())["buffers"][0]["byteLength"], 4)

    def test_nested_obj_mtl_texture_dependency_and_shared_owners(self):
        texture = self.file("texture.png", b"placeholder texture identity")
        self.file("skin.mtl", b"newmtl eyes\nmap_Kd -clamp on texture.png\n")
        for name in ("model-v1.obj", "model-v2.obj"):
            self.file(name, b"mtllib skin.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl eyes\nf 1 2 3\n")
        scout.index(str(self.library))
        rows = scout.search("model")["hits"]
        self.assertEqual(len(rows), 2)
        linked = scout.relations(rows[0]["key"])
        self.assertEqual(len(linked["resources"]), 2)
        self.assertTrue(all(r["catalog_owners"] == 2 for r in linked["resources"]))
        texture.write_bytes(b"changed pixel source")
        self.assertEqual(scout.search("model")["hits"], [])

    def test_missing_dependencies_are_discovered_with_incomplete_freshness(self):
        self.file("model.gltf", {"asset": {"version": "2.0"}, "buffers": [{"uri": "absent.bin", "byteLength": 4}]})
        scout.index(str(self.library))
        row = scout.search()["hits"][0]
        self.assertEqual(row["freshness"], "DOCUMENT_CURRENT_DEPENDENCIES_INCOMPLETE")
        with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
            scout.annotate(row["key"], "verified")

    def test_collection_batches_commit_only_when_complete(self):
        self.file("a.bin", b"a")
        scout.index(str(self.library))
        self.file("b.bin", b"b")
        self.file("c.bin", b"c")
        result = collections.batch(str(self.library), batch_files=1)
        self.assertEqual(result["status"], "STAGED")
        self.assertEqual(len(scout.search()["hits"]), 1)
        while result["status"] == "STAGED":
            result = collections.batch(str(self.library), cursor=result["cursor"], batch_files=1)
        self.assertEqual(result["indexed"], 3)
        self.assertEqual(len(scout.search()["hits"]), 3)

    def test_legacy_search_migration_keeps_annotations_and_removes_deleted_hits(self):
        self.file("first.bin", b"first")
        second = self.file("second.bin", b"second")
        scout.index(str(self.library))
        key = scout.search("first")["hits"][0]["key"]
        scout.annotate(key, "retained_note")
        db = scout._db()
        with db:
            db.execute("DROP TABLE asset_search_keys")
        db.close()
        second.unlink()
        scout.index(str(self.library))
        self.assertEqual(len(scout.search("retained_note")["hits"]), 1)
        self.assertEqual(scout.search("second")["hits"], [])
        db = scout._db()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM asset_search_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM asset_search").fetchone()[0], 1)
        finally:
            db.close()

    def test_changed_batch_rolls_back_and_cannot_reuse_cursor_for_other_game(self):
        self.file("a.bin", b"a")
        scout.index(str(self.library))
        self.file("b.bin", b"b")
        result = collections.batch(str(self.library), batch_files=1)
        cursor = result["cursor"]
        with self.assertRaisesRegex(ValueError, "TARGET_CHANGED"):
            collections.batch(str(self.library), "other", cursor=cursor)
        self.file("b.bin", b"changed")
        with self.assertRaisesRegex(ValueError, "CHANGED"):
            collections.batch(str(self.library), cursor=cursor)
        self.assertEqual(len(scout.search()["hits"]), 1)
        self.assertEqual(collections.cancel(cursor)["status"], "CANCELLED")
        self.assertEqual(len(scout.search()["hits"]), 1)

    def test_flat_directory_partitions_are_disjoint_and_collect_every_file(self):
        for i in range(21):
            self.file("a" + str(i) + ".bin", bytes([i]))
        with patch.object(scout, "MAX_CATALOG", 16):
            plan = collections.plan(str(self.library))
            self.assertEqual(sum(c["files"] for c in plan["collections"]), 21)
            self.assertTrue(all(c["files"] <= 16 for c in plan["collections"]))
            for collection in plan["collections"]:
                result = collections.batch(collection["path"], recursive=collection["recursive"], partition=collection["partition"], partitions=collection["partitions"])
                self.assertEqual(result["status"], "INDEXED")
            db = scout._db()
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 21)
                self.assertEqual(db.execute("SELECT COUNT(DISTINCT collection) FROM assets").fetchone()[0], 2)
            finally:
                db.close()

    def test_rig_trial_fps_basis_and_raw_attributes_are_explicit(self):
        model = self.file("mesh.dae", fixture_dae())
        animation = self.file("clip.smd", fixture_smd())
        for fps, basis in ((0, "SMD_LOCAL"), (30, ""), (float("nan"), "SMD_LOCAL")):
            with self.assertRaises(ValueError):
                rig.trial(str(model), str(animation), fps, basis)
        result = rig.trial(str(model), str(animation), 30, "SMD_LOCAL")
        document = deps.gltf_document(Path(result["model_path"]).read_bytes(), ".glb")
        primitive = document["meshes"][0]["primitives"][0]
        self.assertEqual(set(primitive["attributes"]), {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"})
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["preservation"]["triangles"], 1)
        self.assertEqual(result["gates"]["semantic_gg_retarget"]["state"], "UNKNOWN")
        self.assertEqual(model.read_bytes(), fixture_dae())
        self.assertEqual(animation.read_bytes(), fixture_smd())

    def test_rig_trial_rejects_wrong_parent_and_weight_truncation(self):
        model = self.file("mesh.dae", fixture_dae())
        animation = self.file("clip.smd", fixture_smd().replace(b'Skel0', b'OtherRig'))
        with self.assertRaisesRegex(ValueError, "MISSING_SKIN_JOINTS"):
            rig.trial(str(model), str(animation), 30, "SMD_LOCAL")
        animation.write_bytes(fixture_smd())
        model.write_bytes(fixture_dae().replace(b'<vcount>1 1 1</vcount><v>0 0 0 0 0 0</v>',
                                               b'<vcount>5 1 1</vcount><v>0 0 0 0 0 0 0 0 0 0 0 0 0 0</v>'))
        with self.assertRaisesRegex(ValueError, "NO_TRUNCATION"):
            rig.trial(str(model), str(animation), 30, "SMD_LOCAL")

    def test_real_qwark_aliases_and_independent_bind_trial(self):
        root = assets.ASSET_ROOT / "authored/concept/refs/ps2-models/qwark/Captain Qwark"
        result = rig.trial(str(root / "Qwark.dae"), str(root / "Anims/idle1.smd"), 30, "SMD_ROOT_X90")
        self.assertEqual(result["matched_joints"], 92)
        self.assertEqual(result["omitted_unmatched_nodes"], ["blender_implicit"])
        self.assertLess(result["bind_pose_max_matrix_error"], 1e-5)
        self.assertEqual(result["preservation"]["triangles"], 3190)

    def test_trial_preserves_raw_nonunit_weights_and_refuses_helper_motion(self):
        model = self.file("mesh.dae", fixture_dae().replace(b'count="1">1</float_array>', b'count="1">0.9960784</float_array>'))
        animation = self.file("clip.smd", fixture_smd())
        value = rig.trial(str(model), str(animation), 30, "SMD_LOCAL")
        data = Path(value["model_path"]).read_bytes()
        document = deps.gltf_document(data, ".glb")
        index = document["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"]
        accessor = document["accessors"][index]
        view = document["bufferViews"][accessor["bufferView"]]
        binary_start = 20 + struct.unpack_from("<I", data, 12)[0] + 8
        weight = struct.unpack_from("<f", data, binary_start + view["byteOffset"])[0]
        self.assertAlmostEqual(weight, .9960784, places=6)
        moving_helper = fixture_smd().replace(b'0 "Skel0" -1', b'0 "Skel0" -1\n1 "blender_implicit" -1').replace(b'time 0\n', b'time 0\n1 1 0 0 0 0 0\n')
        animation.write_bytes(moving_helper)
        with self.assertRaisesRegex(ValueError, "HELPER_TRANSFORM"):
            rig.trial(str(model), str(animation), 30, "SMD_LOCAL")

    def test_real_helga_stops_on_two_inconsistent_bind_matrices(self):
        root = assets.ASSET_ROOT / "authored/concept/refs/ps2-models/helga/Helga"
        result = rig.trial(str(root / "Helga.dae"), str(root / "animations/helgaidle.smd"), 30, "SMD_ROOT_X90")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual({r["joint"] for r in result["failed_bind_joints"]}, {"J55", "J63"})
        self.assertEqual(result["gates"]["aliases_and_parents"]["state"], "PASS")
        self.assertNotIn("model_path", result)

    def test_profile_null_gpu_data_stays_unavailable_and_stale_plan_rejected(self):
        source = assets.ASSET_ROOT / "authored/characters/gg-crew-briarstride-compact.glb"
        plan = profile.plan([{"path": str(source)}])
        self.assertFalse(plan["assets"][0]["has_lod"])
        samples = [{"stage": stage, "loaded_models": 1, "visible_models": 0 if stage == "VISIBILITY" else 1, "frame_ms": 16.7,
                    "render_cpu_ms": .5, "sync_cpu_ms": .1, "gpu_window_ms": None,
                    "draw_calls": 4, "render_passes": 1, "graphics_api": "TEST_FIXTURE"} for stage in profile.STAGES for _ in range(3)]
        result = profile.record(plan["packet_path"], samples)
        self.assertEqual(result["stages"]["FULL"]["counters"]["gpu_window_ms"]["state"], "UNAVAILABLE")
        samples[0]["visible_models"] = 0
        with self.assertRaisesRegex(ValueError, "NOT_READY"):
            profile.record(plan["packet_path"], samples)
        packet = Path(plan["packet_path"])
        value = json.loads(packet.read_text())
        value["assets"][0]["full"]["identity"] = "changed"
        packet.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "ASSET_CHANGED"):
            profile.load(str(packet))

    def test_binary_capture_identity_and_tampering(self):
        first = common.artifact("scene-profile-full", b"first capture")
        second = common.artifact("scene-profile-full", b"another capture")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"first capture")
        self.assertEqual(common.artifact("scene-profile-full", b"first capture"), first)
        first.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "EVIDENCE_CHANGED"):
            common.artifact("scene-profile-full", b"first capture")


if __name__ == "__main__":
    unittest.main()
