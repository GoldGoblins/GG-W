"""Regression for the presentation-only rich 3D to DOS fallback seam."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_fallback as fallback
    from backend import game_engine_render as render
    from backend.game_engine_host import GameEngineRuntime

    rich = render.presentation_view(render.RICH_3D)
    assert rich["mode"] == render.RICH_3D
    assert rich["rich_3d"] is True
    assert rich["fallback_available"] is True
    assert rich["simulation_unchanged"] is True
    assert render.normalize_presentation_mode("dos_2d") == render.DOS_2D
    assert render.normalize_presentation_mode("invalid", "") == ""

    view = fallback.build_view(
        [{"id": "e-0000", "kind": "PLAYER", "x": 0, "z": 0}],
        [{"key": "0:0:0", "center_m": {"x": 0, "z": 0}, "surface": "LAND"}],
        state="RUNNING",
        tick=12,
        active_entities=1,
        active_particles=0,
    )
    assert view["schema"] == fallback.SCHEMA
    assert view["mode"] == "DOS_2D"
    assert view["entities"][0]["glyph"] == "@"
    assert view["terrain"][0]["glyph"] == ","
    assert view["shared_contract"].startswith("AUTHORITATIVE_")
    assert view["frame"]["renderer"] == "DOS_ASSET_COLUMNS"
    assert view["frame"]["cols"] == fallback.FRAME_COLS
    assert len(view["frame"]["glyphs"]) == fallback.FRAME_ROWS

    house = fallback.build_cell_frame(
        [
            {
                "id": "hut",
                "kind": "HOUSE",
                "x": 0,
                "y": 0,
                "z": 8,
                "yaw": 0,
                "sx": 1,
                "sy": 1,
                "sz": 1,
                "color": "#aa6633",
                "asset": {"asset_id": "test-hut", "height_m": 4.0, "asset_class": "HOUSE"},
            }
        ],
        [],
        player_x=0,
        player_y=0,
        player_z=0,
        player_yaw=0,
    )
    center = house["cols"] // 2
    middle = house["glyphs"][house["rows"] // 2][center]
    assert middle not in {" ", "."}, middle

    near_and_far = fallback.build_cell_frame(
        [
            {
                "id": "wall",
                "kind": "DOCK",
                "x": 0,
                "y": 0,
                "z": 4,
                "sx": 3,
                "sy": 1,
                "sz": 1,
                "color": "#aa3333",
                "asset": {"height_m": 1.2},
            },
            {
                "id": "tower",
                "kind": "WINDMILL",
                "x": 0,
                "y": 0,
                "z": 16,
                "sx": 1,
                "sy": 1,
                "sz": 1,
                "color": "#3366aa",
                "asset": {"height_m": 9.0},
            },
        ],
        [],
        player_yaw=0,
    )
    tower_color = "#3366aa"
    wall_color = "#aa3333"
    tower_index = near_and_far["palette"].index(tower_color)
    wall_index = near_and_far["palette"].index(wall_color)
    column_colors = [
        int(line[center * 2:center * 2 + 2], 16)
        for line in near_and_far["fg"]
    ]
    tower_row = column_colors.index(tower_index)
    wall_row = column_colors.index(wall_index)
    assert tower_row < wall_row, (tower_row, wall_row)

    palm = PROJECT / "qml" / "assets" / "authored" / "world" / "gg-sandover-palm.glb"
    if palm.is_file():
        from backend.game_engine_geometry import mesh_column_stamp

        stamp = mesh_column_stamp(palm)
        assert stamp is not None
        assert max(stamp["height"]) > 1.0
        assert len({color for color in stamp["color"] if color != "#000000"}) >= 2

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        state_fields = ("simulation", "player", "items", "people", "gear")
        baseline = {
            key: json.dumps(initial[key], sort_keys=True)
            for key in state_fields
        }

        dos = runtime.set_presentation_mode("DOS_2D")
        assert dos["render"]["presentation"]["mode"] == "DOS_2D"
        assert dos["render"]["presentation"]["reason"] == "MANUAL_DOS_MODE"
        assert dos["render"]["draw_calls"] == 0
        assert dos["render"]["fallback"]["schema"] == fallback.SCHEMA
        assert dos["render"]["fallback"]["frame"]["renderer"] == "DOS_ASSET_COLUMNS"
        assert any(
            character not in {" ", "."}
            for line in dos["render"]["fallback"]["frame"]["glyphs"]
            for character in line
        )
        kinds = {row["kind"] for row in dos["render"]["fallback"]["entities"]}
        assert {"PLAYER", "HOUSE", "PALM"} <= kinds
        assert any(
            line.startswith("GEAR ")
            for line in dos["render"]["fallback"]["terminal"]["lines"]
        )
        player = next(
            row
            for row in dos["render"]["fallback"]["entities"]
            if row["kind"] == "PLAYER"
        )
        assert {row["slot"] for row in player["equipment"]} == {
            "MAIN_HAND",
            "OFF_HAND",
            "BACK",
            "FEET",
        }
        for key in state_fields:
            assert json.dumps(dos[key], sort_keys=True) == baseline[key], key

        # The playable stream is the compact render snapshot.  Switching to
        # DOS used to leave its cell frame behind, so the canvas kept the
        # single picture from the mode change.
        before = runtime.render_snapshot()["render"]["fallback"]["frame"]
        assert before["renderer"] == "DOS_ASSET_COLUMNS"
        assert before["glyphs"]
        runtime._x[0] = float(runtime._x[0]) + 8.0
        runtime._z[0] = float(runtime._z[0]) + 4.0
        runtime._yaw[0] = float(runtime._yaw[0]) + 1.15
        runtime._dos_live_frame_at = 0.0
        after = runtime.render_snapshot()["render"]["fallback"]["frame"]
        assert after["camera"]["x"] != before["camera"]["x"]
        assert after["camera"]["yaw"] != before["camera"]["yaw"]
        assert after["glyphs"] != before["glyphs"] or after["fg"] != before["fg"]
        moved_pose = runtime.render_snapshot()["render"]["fallback"]
        assert moved_pose["terminal"]["lines"]
        assert any(line.startswith("POS ") for line in moved_pose["terminal"]["lines"])

        failed = runtime.report_graphics_failure("GPU_CONTEXT_LOST")
        assert failed["render"]["presentation"]["mode"] == "DOS_2D"
        assert failed["render"]["presentation"]["reason"] == "GPU_CONTEXT_LOST"
        restored = runtime.set_presentation_mode("RICH_3D")
        assert restored["render"]["presentation"]["mode"] == "RICH_3D"
        assert restored["render"]["presentation"]["reason"] == "NONE"
        assert restored["render"]["draw_calls"] is None
        rich_stream = runtime.render_snapshot()
        assert "fallback" not in rich_stream["render"]
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_FALLBACK_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

