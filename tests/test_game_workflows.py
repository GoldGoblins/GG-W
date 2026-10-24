"""Cross-format workflow, provenance, stale input and independent route checks."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import game_workflow_common as common, game_workflow_formats as formats
from backend import game_workflow_scout as scout, game_workflow_context as context
from backend import game_workflow_verify as verify, game_workflow_flow as flow
from backend import game_workflow_flow_oracle as oracle, game_workflows, game_workflow_jobs as jobs


def png():
    from PIL import Image
    stream = io.BytesIO()
    Image.new("RGBA", (4, 2), (230, 80, 40, 170)).save(stream, format="PNG")
    return stream.getvalue()


def chunk(kind, data):
    return struct.pack("<III", kind, len(data), 0x1803ffff) + data


def rw():
    return chunk(22, chunk(1, struct.pack("<HH", 1, 0)) + chunk(21, chunk(1, b"platform-specific") + chunk(2, b"stone_wall\0\0") + chunk(3, b"")))


def elf():
    data = bytearray(52)
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", data, 18, 8)
    struct.pack_into("<I", data, 24, 0x100000)
    return bytes(data)


def graph(game="Jak"):
    return {"schema": flow.SCHEMA, "game": game,
            "coordinates": {"up": "Z", "handedness": "right", "meters_per_unit": .01},
            "nodes": [{"id": "a", "position": [0, 0, 0]}, {"id": "b", "position": [100, 0, 200]}, {"id": "c", "position": [200, 0, 200]}],
            "edges": [{"id": "ab", "from": "a", "to": "b", "directed": False, "agent": "climber"},
                      {"id": "bc", "from": "b", "to": "c", "directed": False, "agent": "climber"}],
            "routes": [{"id": "patrol", "mode": "PING_PONG", "edges": ["ab", "bc"]}]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gg-game-workflow-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / "state"
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.enterContext(patch.object(common, "ROOT", self.store))

    def file(self, name, data):
        path = self.assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        return path

    def context_packet(self, reference="int f(int x) { return 7; }"):
        target = self.file("ps2.elf", elf())
        export = self.file("function.json", {"name": "f", "address": "ram:00100000", "pseudocode": reference,
            "pcode": [{"opcode": "RETURN"}], "cfg": {"blocks": [{"id": 0}]}, "callees": [], "types": [{"name": "Vec3"}]})
        return context.from_export(str(export), str(target), "f"), target

    def test_same_discovery_workflow_across_games_and_formats(self):
        self.file("rw/wall.txd", rw())
        self.file("ps2/program.elf", elf())
        self.file("wow/stone.blp", b"BLP2" + bytes(8) + struct.pack("<II", 4, 4) + bytes(128))
        self.file("jak/actor.glTF", {"asset": {"version": "2.0"}, "meshes": [{"name": "character"}]})
        self.file("sly/title_specific.wad", b"unknown Sly archive; never a GTA decoder")
        self.file("ratchet/stone.png", png())
        self.file("vexx/stone.png", png())
        # Extension spelling is irrelevant; recognized magic still identifies GLB.
        result = scout.index(str(self.assets), "PS2 / RenderWare / WoW / Jak / Ratchet / Vexx / Sly")
        self.assertEqual(result["indexed"], 7)
        hits = scout.search()["hits"]
        kinds = {hit["format"] for hit in hits}
        self.assertTrue({"RENDERWARE_STREAM", "ELF", "WOW_BLP", "PNG", "OPAQUE"} <= kinds)
        opaque = next(row for row in hits if row["relative"].endswith(".wad"))
        self.assertEqual(opaque["coverage"], "IDENTITY_ONLY")
        self.assertEqual(next(row for row in hits if row["format"] == "ELF")["metadata"]["architecture"], "MIPS")
        duplicate_images = [row for row in hits if row["format"] == "PNG"]
        self.assertEqual(len({row["key"] for row in duplicate_images}), 2)
        self.assertTrue(all(row["duplicates"] == 2 for row in duplicate_images))

    def test_incremental_annotation_and_stale_source_exclusion(self):
        path = self.file("unknown.bin", b"first")
        scout.index(str(self.assets), "Ratchet")
        key = scout.search()["hits"][0]["key"]
        scout.annotate(key, "weapon vapen", "Observed mesh role, not a format guess")
        self.assertEqual(len(scout.search("vapen")["hits"]), 1)
        self.assertEqual(scout.index(str(self.assets), "Ratchet")["unchanged"], 1)
        before = path.stat()
        path.write_bytes(b"other")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        stale = scout.search("weapon")
        self.assertEqual(stale["hits"], [])
        self.assertEqual(stale["stale_excluded"], 1)
        with self.assertRaisesRegex(ValueError, "CHANGED"):
            scout.annotate(key, "wrong")
        scout.index(str(self.assets), "Ratchet")
        self.assertEqual(scout.search("weapon")["hits"], [])
        self.assertIsNone(scout.asset(key)["annotation"])
        path.unlink()
        self.assertEqual(scout.index(str(self.assets))["removed"], 1)

    def test_lexical_filters_and_user_fts_syntax_are_data(self):
        self.file("wall.png", png())
        scout.index(str(self.assets), "WoW")
        self.assertEqual(len(scout.search("textur", "WoW", "texture")["hits"]), 1)
        self.assertEqual(scout.search("textur", "Jak")["hits"], [])
        self.assertEqual(scout.search('" OR * - NEAR()')["hits"], [])

    def test_scan_limit_rolls_back_previous_catalog(self):
        self.file("a.bin", b"a")
        scout.index(str(self.assets))
        self.file("b.bin", b"b")
        with patch.object(scout, "MAX_FILES", 1):
            with self.assertRaisesRegex(ValueError, "PREVIOUS_CATALOG_PRESERVED"):
                scout.index(str(self.assets))
        self.assertEqual([row["relative"] for row in scout.search()["hits"]], ["a.bin"])

    @unittest.skipIf(os.name == 'nt', 'Windows junction boundaries are covered by test_windows_game_workflows')
    def test_symlink_and_root_boundaries(self):
        outside = self.root / "outside.png"
        outside.write_bytes(png())
        (self.assets / "escape.png").symlink_to(outside)
        self.assertEqual(scout.index(str(self.assets))["indexed"], 0)
        with self.assertRaises(ValueError):
            common.read_file(self.assets / "escape.png", root=self.assets)
        with self.assertRaises(ValueError):
            common.write_json(outside, {"overwrite": True})
        self.assertEqual(outside.read_bytes(), png())

    def test_renderware_native_data_stays_opaque_and_bad_lengths_rejected(self):
        observed = formats.renderware(rw())
        self.assertEqual(observed["metadata"]["names"], ["stone_wall"])
        self.assertEqual(observed["coverage"], "CHUNK_STRUCTURE")
        damaged = bytearray(rw())
        struct.pack_into("<I", damaged, 4, 0xffffffff)
        with self.assertRaises(ValueError):
            formats.renderware(bytes(damaged))
        self.file("bad.txd", bytes(damaged))
        self.assertEqual(scout.index(str(self.assets))["invalid"], 1)

    def test_glb_chunk_bounds(self):
        payload = json.dumps({"asset": {"version": "2.0"}, "meshes": [{"name": "climber"}]}).encode()
        payload += b" " * (-len(payload) % 4)
        data = struct.pack("<IIIII", 0x46546c67, 2, 20 + len(payload), len(payload), 0x4e4f534a) + payload
        self.assertEqual(formats.inspect(data, ".bin")["metadata"]["meshes"], 1)
        with self.assertRaises(ValueError):
            formats.inspect(data[:-1], ".glb")

    def test_contact_sheet_is_real_pixels_with_separate_source_occurrences(self):
        self.file("Jak/a.png", png())
        self.file("Sly/a.png", png())
        self.file("Ratchet/a.bin", b"opaque")
        scout.index(str(self.assets))
        rows = scout.search()["hits"]
        result = scout.contact_sheet([row["key"] for row in rows])
        self.assertTrue(Path(result["packet_path"]).is_file())
        self.assertEqual(sum(row["preview"] == "SOURCE_PIXELS" for row in result["rows"]), 2)
        self.assertEqual(sum(row["preview"] == "UNAVAILABLE" for row in result["rows"]), 1)
        manifest = common.read_json(result["packet_path"])[1]
        self.assertEqual(manifest["ordering"], "SOURCE_IDENTITY_NOT_SEARCH_RANK")
        self.assets.joinpath("Jak/a.png").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            scout.contact_sheet([row["key"] for row in rows])

    def test_context_preserves_address_spaces_types_and_ir(self):
        result, target = self.context_packet()
        value = context.load(result["packet_path"])
        self.assertEqual(value["function"]["address"], "ram:0x100000")
        self.assertEqual(value["function"]["types"], [{"name": "Vec3"}])
        self.assertEqual(value["function"]["pcode"][0]["opcode"], "RETURN")
        self.assertEqual(value["provenance"], "EXTERNAL_EXPORT_UNVERIFIED")
        self.assertEqual(context.address("rom:0000000100000000"), "rom:0x100000000")
        target.write_bytes(elf() + b"new")
        with self.assertRaisesRegex(ValueError, "ARTIFACT_CHANGED"):
            context.load(result["packet_path"])

    def test_context_exact_resolution_ambiguity_and_path_injection(self):
        target = self.file("program.elf", elf())
        directory = self.assets / "exports"
        directory.mkdir()
        for space in ("ram", "rom"):
            (directory / (space + ".json")).write_text(json.dumps({"name": "f", "address": space + ":00100000", "pseudocode": "int f(){return 7;}"}))
        self.assertEqual(context.from_export(str(directory), str(target), "f")["status"], "AMBIGUOUS")
        result = context.from_export(str(directory), str(target), "rom:0x100000")
        self.assertEqual(result["context"]["function"]["address"], "rom:0x100000")
        for query in ("../f", "0x../../secret", "ram:bad/address"):
            with self.assertRaises(ValueError):
                context.from_export(str(directory), str(target), query)

    def test_export_cannot_attach_to_a_different_artifact(self):
        target = self.file("program.elf", elf())
        exported = self.file("export.json", {"name": "f", "artifact_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            context.from_export(str(exported), str(target), "f")

    def test_candidate_constant_mismatch_fails_without_patching(self):
        result, target = self.context_packet()
        candidate = self.file("candidate.c", b"int f(int x) { return 8; }")
        original = target.read_bytes()
        checked = verify.verify(result["packet_path"], str(candidate))
        self.assertEqual(checked["acceptance"], "REJECTED")
        self.assertEqual(checked["findings"][0]["kind"], "CONSTANT_RETURN_MISMATCH")
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(candidate.read_bytes(), b"int f(int x) { return 8; }")
        self.assertEqual(common.read_json(checked["packet_path"])[1]["candidate_code"], candidate.read_text())

    def test_consistent_candidate_never_implies_semantic_acceptance(self):
        result, _ = self.context_packet()
        candidate = self.file("candidate.c", b"int f(int x) { return 7; }")
        checked = verify.verify(result["packet_path"], str(candidate))
        self.assertEqual(checked["gates"]["candidate_structure"]["state"], "CONSISTENT")
        self.assertEqual(checked["gates"]["analysis_provenance"]["state"], "UNKNOWN")
        self.assertEqual(checked["gates"]["behavior"]["state"], "UNKNOWN")
        self.assertEqual(checked["acceptance"], "UNKNOWN")

    def test_multi_function_or_unbalanced_candidate_rejected(self):
        result, _ = self.context_packet()
        for code in (b"int f(){return 1;} int g(){return 2;}", b"int f(){return 1;", b"int values[] = {1,2};"):
            with self.subTest(code=code):
                candidate = self.file("candidate.c", code)
                self.assertEqual(verify.verify(result["packet_path"], str(candidate))["acceptance"], "REJECTED")

    def test_c_octal_literals_and_unmodeled_integer_width_are_not_false_failures(self):
        result, _ = self.context_packet("int f() { return 010; }")
        candidate = self.file("candidate.c", b"int f() { return 8; }")
        self.assertEqual(verify.verify(result["packet_path"], str(candidate))["acceptance"], "UNKNOWN")
        for reference, proposed in (("int f(){return 0x100000001;}", b"int f(){return 1;}"),
                                    ("unsigned char f(){return 263;}", b"unsigned char f(){return 7;}")):
            with self.subTest(reference=reference):
                result, _ = self.context_packet(reference)
                candidate.write_bytes(proposed)
                checked = verify.verify(result["packet_path"], str(candidate))
                self.assertEqual(checked["acceptance"], "UNKNOWN")
                self.assertEqual(checked["findings"][0]["severity"], "REVIEW")

    def test_modified_evidence_packet_cannot_be_silently_reused(self):
        value = {"schema": "test", "value": 1}
        path = common.packet("test", value)
        path.write_text(json.dumps({"schema": "test", "value": 2}))
        with self.assertRaisesRegex(ValueError, "PACKET_CONTENT_CHANGED"):
            common.packet("test", value)

    def test_fixed_sandboxed_compiler_syntax_gate(self):
        good = verify.syntax_gate("int f(int x) { return x + 7; }")
        if good["state"] == "UNKNOWN":
            self.skipTest(good["reason"])
        self.assertEqual(good["state"], "PASS", good)
        bad = verify.syntax_gate("int f(int x) { return x + 7 }")
        self.assertEqual(bad["state"], "FAIL")

    def test_route_frames_elevation_and_deterministic_compilation(self):
        first = graph("Vexx")
        compiled = flow.validate(first)["compiled"]
        self.assertEqual(compiled["nodes"][1]["position"], [1, 2, 0])
        reordered = copy.deepcopy(first)
        reordered["nodes"].reverse(); reordered["edges"].reverse()
        self.assertEqual(compiled, flow.compile_graph(reordered))
        for frame in ({"up": "Y", "handedness": "left", "meters_per_unit": 2}, first["coordinates"]):
            self.assertEqual(flow.from_engine(flow.to_engine([2, 3, 4], frame), frame), [2, 3, 4])

    def test_independent_reader_catches_corrupt_compiler_output(self):
        compiled = flow.compile_graph(graph())
        compiled["edges"][0]["to"] = 9999
        self.assertFalse(oracle.inspect_bytes(json.dumps(compiled).encode())["valid"])
        compiled = flow.compile_graph(graph())
        compiled["routes"][0]["node_indices"] = [0, 2, 1]
        self.assertFalse(oracle.inspect_bytes(json.dumps(compiled).encode())["valid"])

    def test_crossing_lines_do_not_create_junctions(self):
        value = {"schema": flow.SCHEMA, "coordinates": {"up": "Y", "handedness": "right", "meters_per_unit": 1},
                 "nodes": [{"id": str(i), "position": p} for i, p in enumerate(([-1, 0, 0], [1, 0, 0], [0, 2, -1], [0, 2, 1]))],
                 "edges": [{"id": "low", "from": "0", "to": "1"}, {"id": "high", "from": "2", "to": "3"}], "routes": []}
        result = flow.validate(value)
        self.assertEqual(len(result["compiled"]["nodes"]), 4)
        self.assertIn("2 disconnected", result["oracle"]["warnings"][0])

    def test_directed_reverse_discontinuity_and_bad_coordinates_rejected(self):
        mutations = []
        value = graph(); value["edges"][0]["directed"] = True; mutations.append(value)
        value = graph(); value["routes"][0]["edges"] = ["bc", "ab"]; mutations.append(value)
        value = graph(); value["nodes"][0]["position"][0] = float("nan"); mutations.append(value)
        value = graph(); value["nodes"].append(copy.deepcopy(value["nodes"][0])); mutations.append(value)
        value = graph(); del value["coordinates"]["meters_per_unit"]; mutations.append(value)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                flow.validate(value)

    def test_dwell_preserves_distinct_coincident_activity_stops(self):
        value = graph()
        value["nodes"][2]["position"] = value["nodes"][1]["position"][:]
        value["nodes"][1].update(wait_s=0, activity="TRAVELING")
        value["nodes"][2].update(wait_s=32, activity="GUARDING")
        with self.assertRaises(ValueError):
            flow.validate(value)
        value["edges"][1]["transition"] = "DWELL"
        self.assertTrue(flow.validate(value)["oracle"]["valid"])

    @unittest.skipUnless(all((PROJECT / "qml/assets/authored/world" / name).is_file() for name in ("world-places.json", "world-landscape.json")), "Requires local map fixtures")
    def test_real_gg_maps_roundtrip_losslessly_and_stale_original_rejected(self):
        for name in ("world-places.json", "sandover-settlement.json"):
            original = json.loads((PROJECT / "qml/assets/authored/world" / name).read_text())
            source = self.file(name, original)
            imported = flow.import_map(str(source), "GG")
            exported = flow.export_map(imported["packet_path"])
            self.assertFalse(exported["changed"])
            self.assertEqual(common.read_json(exported["packet_path"])[1], original)
            source.write_bytes(source.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "ORIGINAL_MAP_CHANGED"):
                flow.export_map(imported["packet_path"])

    def test_gg_candidate_updates_stop_but_preserves_other_map_fields(self):
        original = {"schema": "gg.world-places.v1", "coordinates": "WORLD_METRES", "places": [{"id": "home"}],
                    "roads": [], "residents": [{"id": "guard", "role": "GUARD", "route_mode": "PING_PONG", "speed": 1,
                    "stops": [[0, 0, 20, "RESTING"], [1, 0, 32, "GUARDING"]]}]}
        source = self.file("map.json", original)
        imported = flow.import_map(str(source))
        value = common.read_json(imported["packet_path"])[1]
        value["nodes"][1]["position"] = [2, 0, 0]
        value["nodes"][1]["wait_s"] = 44
        packet_path = flow.save(value)["packet_path"]
        output = common.read_json(flow.export_map(packet_path)["packet_path"])[1]
        self.assertEqual(output["places"], original["places"])
        self.assertEqual(output["residents"][0]["stops"][1], [2, 0, 44, "GUARDING"])
        self.assertEqual(common.read_json(source)[1], original)

    @unittest.skipUnless((PROJECT / "qml/assets/authored/world/sandover-settlement.json").is_file(), "Requires local map fixture")
    def test_gg_roundtrip_after_coordinate_frame_conversion_preserves_scale_and_width(self):
        original = json.loads((PROJECT / "qml/assets/authored/world/sandover-settlement.json").read_text())
        source = self.file("map.json", original)
        value = common.read_json(flow.import_map(str(source))["packet_path"])[1]
        before_frame = value["coordinates"]
        after_frame = {"up": "Z", "handedness": "right", "meters_per_unit": 1}
        for node in value["nodes"]:
            node["position"] = flow.from_engine(flow.to_engine(node["position"], before_frame), after_frame)
        value["coordinates"] = after_frame
        path = flow.save(value)["packet_path"]
        exported = flow.export_map(path)
        self.assertFalse(exported["changed"])

    def test_native_wow_adapter_uses_actual_installed_reader(self):
        from backend.game_engine_adapter_formats import available
        if not available():
            self.skipTest("Verified GgEngine reader unavailable")
        from tools.world import engine_format_fixtures as fixtures
        path = self.file("gold.blp", fixtures.blp())
        result = game_workflows.execute("scout_inspect", {"path": str(path), "native": True})
        self.assertEqual(result["status"], "READY", result)
        self.assertEqual(result["coverage"], "GG_ENGINE_DECODED_METADATA")
        self.assertTrue(result["image"].startswith("file:"))
        path = self.file("panel.m2", fixtures.m2())
        result = game_workflows.execute("scout_inspect", {"path": str(path), "native": True})
        self.assertEqual(result["status"], "READY", result)
        self.assertEqual(result["native_metadata"]["format"], "M2")
        self.assertEqual(result["native_metadata"]["textures"][0]["path"], "gold.blp")

    def test_supervised_job_roundtrip_and_no_arbitrary_operations(self):
        self.file("a.png", png())
        state = jobs.start("scout_index", {"path": str(self.assets), "game": "Sly"})
        self.assertEqual(state["status"], "QUEUED", state)
        deadline = time.monotonic() + 10
        while state["status"] in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state["job_id"])
        self.assertEqual(state["status"], "COMPLETE", state)
        self.assertEqual(state["result"]["indexed"], 1)
        self.assertEqual(jobs.start("run_shell", {"command": "touch bad"})["status"], "ERROR")
        self.assertEqual(jobs.status("../escape")["status"], "ERROR")

    def test_native_decoder_inside_supervised_workflow_inherits_compatible_limits(self):
        from backend.game_engine_adapter_formats import available
        if not available():
            self.skipTest("Verified GgEngine reader unavailable")
        from tools.world import engine_format_fixtures as fixtures
        source = self.file("gold.blp", fixtures.blp())
        state = jobs.start("scout_inspect", {"path": str(source), "native": True})
        self.assertEqual(state["status"], "QUEUED")
        deadline = time.monotonic() + 10
        while state["status"] in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state["job_id"])
        self.assertEqual(state["status"], "COMPLETE", state)
        self.assertEqual(state["result"]["status"], "READY", state["result"])
        self.assertEqual(state["result"]["coverage"], "GG_ENGINE_DECODED_METADATA")

    def test_worker_paths_are_resolved_in_the_callers_workspace(self):
        self.file("a.png", png())
        old = Path.cwd()
        try:
            os.chdir(self.root)
            state = jobs.start("scout_index", {"path": "assets"})
        finally:
            os.chdir(old)
        self.assertEqual(state["status"], "QUEUED", state)
        deadline = time.monotonic() + 10
        while state["status"] in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state["job_id"])
        self.assertEqual(state["status"], "COMPLETE", state)
        self.assertEqual(state["result"]["status"], "INDEXED", state["result"])
        self.assertEqual(state["result"]["root"], str(self.assets))

    def test_async_cli_status_never_reports_an_unknown_candidate_as_success(self):
        packet, _ = self.context_packet()
        candidate = self.file("candidate.c", b"int f(int x) { return 7; }")
        environment = os.environ.copy()
        environment["GG_GAME_WORKFLOWS_ROOT"] = str(self.store)
        command = [sys.executable, "-B", str(PROJECT / "gg-game-workflows")]
        queued = subprocess.run(command + ["--no-wait", "verify", packet["packet_path"], str(candidate)],
                                capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(queued.returncode, 0, queued.stderr)
        state = json.loads(queued.stdout)
        deadline = time.monotonic() + 10
        while state["status"] in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state["job_id"])
        outcome = subprocess.run(command + ["status", state["job_id"]], capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(outcome.returncode, 1)
        self.assertEqual(json.loads(outcome.stdout)["result"]["acceptance"], "UNKNOWN")

    def test_independent_reader_rejects_nonobject_or_nonutf8_data(self):
        for data in (b"[]", b"null", b"42", b"\xff"):
            self.assertFalse(oracle.inspect_bytes(data)["valid"])

    def test_json_ambiguity_and_non_finite_values_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                common.parse_json(data)


if __name__ == "__main__":
    unittest.main()
