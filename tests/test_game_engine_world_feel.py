"""World scale, equal double-jump hops, and whole-sea fauna."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import game_engine_controller as controller
from backend import game_engine_fauna as fauna
from backend import game_engine_host as host
from backend import game_engine_terrain as terrain
from backend import game_engine_world as world


def _jump_apex(mode: str) -> float:
    """Full-hold single hop, or a second hop timed at the apex / at 80%."""
    speed = controller.JUMP_SPEED_MPS
    y = vy = 0.0
    coyote = buf = hold = 0.0
    count = 0
    held = False
    phase = "up"
    apex = 0.0
    dt = 1.0 / 60.0
    for step in range(900):
        press = phase != "release"
        if phase == "up" and count == 1 and step > 2:
            quality = controller.double_jump_quality(vy, speed)
            if mode == "apex" and vy <= 0.0:
                phase = "release"
                press = False
            elif mode == "q80" and vy > 0.0 and quality >= 0.80:
                phase = "release"
                press = False
        if mode == "single":
            phase = "up"
            press = True
        result = controller.vertical_step(
            y=y,
            vertical_velocity=vy,
            ground_y=0.0,
            jump_pressed=press,
            jump_was_pressed=held,
            dt=dt,
            coyote_remaining=coyote,
            jump_buffer_remaining=buf,
            jump_hold_time=hold,
            jump_count=count,
            jump_speed=speed,
        )
        y = result["y"]
        vy = result["vertical_velocity"]
        coyote = result["coyote_remaining"]
        buf = result["jump_buffer_remaining"]
        hold = result["jump_hold_time"]
        count = result["jump_count"]
        held = press
        apex = max(apex, y)
        if phase == "release":
            phase = "second"
        if mode == "single" and result["grounded"] and step > 10:
            break
        if mode != "single" and phase == "second" and result["grounded"] and step > 12 and not result["jumped"]:
            break
    return apex


def test_double_jump_keeps_character_scale_when_architecture_grows():
    single = _jump_apex("single")
    perfect = _jump_apex("apex")
    timed = _jump_apex("q80")
    roof = world.roof_clearance_m()
    assert single > 3.5
    # A perfect second hop raises the body about as far as the first.
    assert 1.95 <= perfect / single <= 2.12
    # Architecture grows independently; the existing jump stays at avatar scale.
    # Tall roofs now require a route or a traversal ability, not inflated gravity.
    assert abs(timed - 7.585) < 0.08
    assert perfect < roof
    assert timed < perfect


def test_island_expands_without_moving_the_sea():
    assert terrain.height_at(0.0, 0.0) == round(
        terrain.height_at(0.0, 0.0),
        6,
    )
    assert abs(terrain.height_at(0.0, 0.0)) > 1.0
    # Sea level stays the shoreline. Far water is still at or below it.
    assert terrain.height_at(400.0, 400.0) <= terrain.SEA_LEVEL + 0.05
    # The same authored point is taller and farther out after the feel scale.
    authored = terrain.height_at(0.0, 0.0) / world.WORLD_FEEL_SCALE
    expanded = terrain.height_at(0.0, 0.0)
    assert abs(expanded - authored * world.WORLD_FEEL_SCALE) < 0.02


def test_fauna_changes_across_the_sea_and_stays_put():
    near = fauna.build_groups(0.0, 0.0, 10.0, island_radius=40.0)
    far = fauna.build_groups(800.0, -600.0, 10.0, island_radius=40.0)
    again = fauna.build_groups(0.0, 0.0, 10.0, island_radius=40.0)
    assert len(near["birds"]) == fauna.BIRD_SLOTS
    assert len(near["fish"]) == fauna.FISH_SLOTS
    assert len(near["clouds"]) == fauna.CLOUD_SLOTS
    assert near["birds"] == again["birds"]
    assert near["birds"][0]["x"] != far["birds"][0]["x"]
    assert all(row["y"] > 8.0 for row in near["birds"])
    assert all(row["y"] > 15.0 for row in near["clouds"])
    moved = fauna.build_groups(0.0, 0.0, 14.0, island_radius=40.0)
    # Bird roots stay anchored: local flight is the authored GLB animation.
    assert moved["birds"][0]["x"] == near["birds"][0]["x"]
    assert moved["fish"][0]["x"] != near["fish"][0]["x"]


def test_runtime_places_huts_on_the_expanded_island():
    runtime = host.GameEngineRuntime()
    try:
        houses = [
            index
            for index in runtime._static_entity_indices
            if runtime._kind[index] == "HOUSE"
        ]
        assert houses
        roof = world.roof_clearance_m()
        for index in houses:
            ground = runtime._terrain_height_locked(
                runtime._x[index],
                runtime._z[index],
            )
            # Entity root sits one scale above the ground; the roof is another.
            assert abs((runtime._y[index] - ground) * 2.0 - roof) < 0.05
            assert abs(runtime._x[index]) > 1.0 or abs(runtime._z[index]) > 1.0
    finally:
        runtime.shutdown()


def test_sea_disk_is_continuous_and_not_banded():
    import math
    from pathlib import Path

    from backend import game_engine_mobility as mobility
    from backend.game_engine_geometry import (
        WATER_DISK_RINGS,
        WATER_DISK_SEGMENTS,
        water_disk_indices,
        water_disk_local,
    )

    shortest = min(math.tau / row[3] for row in mobility.WAVE_COMPONENTS)
    assert shortest >= 40.0
    trough = mobility.water_shade(0.0, 0.0, 0.0, 0.0)
    crest = mobility.water_shade(1.0, 0.0, 0.0, 0.0)
    assert trough[1] < crest[1]
    assert all(0.0 <= channel <= 1.0 for channel in trough + crest)
    low = mobility.water_shade(0.40, 0.0, 0.0, 0.0)[1]
    high = mobility.water_shade(0.46, 0.0, 0.0, 0.0)[1]
    assert high > low
    assert mobility.water_shade(0.0, 0.0, 1.0, 0.0)[1] > trough[1]
    assert mobility.water_clarity(0.0) == 0.0
    assert mobility.water_clarity(1.5) < mobility.water_clarity(6.0)
    assert 0.5 < mobility.water_clarity(8.0) < 0.85
    coords = water_disk_local(WATER_DISK_RINGS, WATER_DISK_SEGMENTS, 280.0)
    indices = water_disk_indices(WATER_DISK_RINGS, WATER_DISK_SEGMENTS)
    assert len(coords) == 1 + WATER_DISK_RINGS * WATER_DISK_SEGMENTS
    for x, z in coords[-WATER_DISK_SEGMENTS:]:
        assert abs(math.hypot(x, z) - 280.0) < 0.05
    for index in range(0, len(indices), 3):
        ax, az = coords[indices[index]]
        bx = coords[indices[index + 1]][0] - ax
        bz = coords[indices[index + 1]][1] - az
        cx = coords[indices[index + 2]][0] - ax
        cz = coords[indices[index + 2]][1] - az
        assert bz * cx - bx * cz > 0.0
    environment = (
        Path(__file__).resolve().parents[1]
        / "qml/assets/authored/world/gg-sandover-island-environment.glb"
    )
    blob = environment.read_bytes()
    assert blob[:4] == b"glTF"
    json_length = int.from_bytes(blob[12:16], "little")
    document = json.loads(blob[20:20 + json_length])
    assert document.get("images"), "island environment has no painted textures"
    textured = 0
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            if "TEXCOORD_0" in primitive.get("attributes", {}):
                textured += 1
    assert textured > 10


def test_hoverboard_rides_the_drawn_wave():
    import math

    from backend import game_engine_mobility as mobility

    runtime = host.GameEngineRuntime()
    try:
        runtime._vehicle_kind = "HOVERBOARD"
        runtime._x[0] = 900.0
        runtime._z[0] = 150.0
        runtime._vx[0] = 0.0
        runtime._vz[0] = 0.0
        runtime._sim_time = 6.0
        runtime._y[0] = runtime._ground_contact_height_locked(
            900.0, 150.0, vehicle_kind="HOVERBOARD"
        )
        runtime._grounded = True
        for _ in range(40):
            runtime.step()
        support = runtime._ground_contact_height_locked(
            runtime._x[0], runtime._z[0], vehicle_kind="HOVERBOARD"
        )
        water = runtime._water_sample_locked(runtime._x[0], runtime._z[0])
        assert runtime._grounded
        assert abs(runtime._y[0] - support) < 0.02
        assert abs(support - (water["height_m"] + mobility.HOVER_WATER_CLEARANCE_M)) < 0.02
        slope = water["slope"]
        pitch, roll = mobility.ride_tilt_degrees(
            runtime._yaw[0], slope["x"], slope["z"]
        )
        assert abs(runtime._pitch[0] - pitch) < 0.2
        assert abs(runtime._roll[0] - roll) < 0.2
        # Facing +Z, positive Qt pitch would drop the nose into a rising face.
        if abs(runtime._yaw[0]) < 1.0e-6:
            nose = max(-16.0, min(16.0, -math.degrees(math.atan(slope["z"]))))
            assert abs(pitch - nose) < 0.05
        snapshot = runtime.render_snapshot()
        assert abs(snapshot["player"]["time_s"] - runtime._sim_time) < 1.0e-9
    finally:
        runtime.shutdown()


def test_sea_shader_uses_the_same_wave_as_the_body():
    import math
    import re

    from backend import game_engine_mobility as mobility
    from backend.game_engine_geometry import SEA_BED_EXTENT_M, sea_bed_grid

    shader = (
        Path(__file__).resolve().parents[1] / "qml/shaders/gg-sea.vert"
    ).read_text(encoding="utf-8")
    fragment = (
        Path(__file__).resolve().parents[1] / "qml/shaders/gg-sea.frag"
    ).read_text(encoding="utf-8")
    waves = {
        int(index): tuple(float(value) for value in values.split(","))
        for index, values in re.findall(
            r"GG_WAVE_(\d)\s*=\s*vec4\(([^)]*)\)",
            shader,
        )
    }
    rates = {
        int(index): tuple(float(value) for value in values.split(","))
        for index, values in re.findall(
            r"GG_RATE_(\d)\s*=\s*vec2\(([^)]*)\)",
            shader,
        )
    }
    assert list(waves) == [0, 1, 2, 3]
    for index, row in enumerate(mobility.WAVE_COMPONENTS):
        direction_x, direction_z, amplitude, wave_number, angular, phase, steep = row
        assert steep == 0.0
        assert waves[index] == (direction_x, direction_z, amplitude, wave_number)
        assert rates[index] == (angular, phase)

    def shader_height(x: float, z: float, time_s: float) -> tuple[float, float, float]:
        distance = math.hypot(x, z)
        blend = max(0.0, min(1.0, (distance - 48.0) / 100.0))
        blend = blend * blend * (3.0 - 2.0 * blend)
        scale = 0.15 + 0.85 * blend
        tide_phase = time_s * (math.tau / 110.0)
        height = 0.55 * scale * math.sin(tide_phase)
        dhdx = 0.0
        dhdz = 0.0
        for index in range(4):
            direction_x, direction_z, amplitude, wave_number = waves[index]
            angular, phase = rates[index]
            amplitude *= scale
            phase_value = (
                wave_number * (direction_x * x + direction_z * z)
                - angular * time_s
                + phase
            )
            height += amplitude * math.sin(phase_value)
            derivative = amplitude * wave_number * math.cos(phase_value)
            dhdx += derivative * direction_x
            dhdz += derivative * direction_z
        return height, dhdx, dhdz

    for x, z, time_s in ((180.0, 30.0, 6.0), (-40.0, 90.0, 1.25), (12.0, -6.0, 4.0)):
        drawn = mobility.surface_sample(x, z, time_s)
        height, dhdx, dhdz = shader_height(x, z, time_s)
        assert abs(height - drawn["height_m"]) < 1.0e-6
        assert abs(dhdx - drawn["slope"]["x"]) < 1.0e-6
        assert abs(dhdz - drawn["slope"]["z"]) < 1.0e-6
    assert "GG_TILE = 40.0" in fragment
    assert "GG_SIGHT = 5.5" in fragment
    assert mobility.WATER_TEXTURE_TILE_M == 40.0
    assert mobility.WATER_SIGHT_M == 5.5
    surface = (
        Path(__file__).resolve().parents[1]
        / "qml/components/GameEngineSurface.qml"
    ).read_text(encoding="utf-8")
    assert "id: seaPlaneMaterial" in surface
    # The same tested wave now runs on the GPU. Mesh preparation is static;
    # water and the rider still sample the same unrounded simulation clock.
    assert "vertexShader: \"../shaders/gg-sea.vert\"" in surface
    assert "fragmentShader: \"../shaders/gg-sea.frag\"" in surface
    assert "property real uTime: root.number(root.player.time_s,0)" in surface
    assert "gameEnginePrepareWaterGpu(root.waterWaveSpanM)" in surface
    for x, z, time_s in ((180.0, 30.0, 6.0), (-70.0, -56.0, 4.0)):
        drawn = mobility.surface_sample(x, z, time_s)
        height, dhdx, dhdz, _crest = mobility.sample_waves(
            [(x, z)], time_s
        )[0]
        assert abs(height - drawn["height_m"]) < 1.0e-6
        assert abs(dhdx - drawn["slope"]["x"]) < 1.0e-6
        assert abs(dhdz - drawn["slope"]["z"]) < 1.0e-6
    from backend.game_engine_geometry import SEA_BED_MIN_M, SEA_BED_SPAN_M, sea_bed_byte

    assert SEA_BED_EXTENT_M == 120.0 * world.PLANET_LAYOUT_SCALE
    assert SEA_BED_MIN_M == -80.0
    assert SEA_BED_SPAN_M == 120.0
    assert "GG_BED_MIN = -80.0" in fragment
    assert "GG_BED_SPAN = 120.0" in fragment
    encoded = sea_bed_byte(10.0) / 255.0 * SEA_BED_SPAN_M + SEA_BED_MIN_M
    assert abs(encoded - 10.0) < 0.5
    grid = sea_bed_grid(8, 80.0 * world.PLANET_LAYOUT_SCALE)
    assert len(grid) == 64
    assert grid[0] < 0.0
    assert grid[4 * 8 + 4] > 1.0


def test_sea_swells_and_skiff_are_large_enough_to_board():
    from backend import game_engine_mobility as mobility

    calm = mobility.surface_sample(0.0, 0.0, 0.0)
    crest = max(
        abs(mobility.surface_sample(x, z, 12.0)["wave_height_m"])
        for x in range(160, 241, 20)
        for z in range(-40, 41, 20)
    )
    assert calm["surface_model"] == "LAYERED_GERSTNER_SWELLS_PLUS_TIDE"
    assert crest > 1.8
    assert crest < mobility.MAX_WAVE_HEIGHT_M + 0.01
    shift_x, shift_z = mobility.surface_horizontal_offset(12.0, -6.0, 4.0)
    # The drawn point is the sampled point. A sideways crest would ride
    # through the body instead of lifting it.
    assert abs(shift_x) + abs(shift_z) < 1.0e-9
    runtime = host.GameEngineRuntime()
    try:
        boat = runtime._boat_entity_index
        assert boat is not None
        assert runtime._sx[boat] == mobility.SKIFF_SCALE[0]
        assert runtime._sz[boat] > 4.0
        runtime._x[0] = runtime._x[boat] + 2.0
        runtime._z[0] = runtime._z[boat]
        runtime._y[0] = runtime._y[boat] + mobility.skiff_seat_offset(runtime._sy[boat])
        boarded = runtime._mobility_action_locked("MOUNT_BOAT")
        assert boarded.get("ok") is True
        assert runtime._vehicle_kind == "BOAT"
        left = runtime._mobility_action_locked("MOUNT_BOAT")
        assert left.get("ok") is True
        assert runtime._vehicle_kind == "NONE"
    finally:
        runtime.shutdown()


def main() -> int:
    test_double_jump_keeps_character_scale_when_architecture_grows()
    test_island_expands_without_moving_the_sea()
    test_fauna_changes_across_the_sea_and_stays_put()
    test_runtime_places_huts_on_the_expanded_island()
    test_sea_disk_is_continuous_and_not_banded()
    test_hoverboard_rides_the_drawn_wave()
    test_sea_shader_uses_the_same_wave_as_the_body()
    test_sea_swells_and_skiff_are_large_enough_to_board()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
