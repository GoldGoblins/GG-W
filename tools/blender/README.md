# GG Blender asset pipeline

## Whole-atlas places and architecture, 2026-10-04

The live EXT scene `GG_World_Places_R1` contains 48 place anchors, 1,449
shared-mesh props, 52 road POLY curves and 312 resident POLY curves. The
separate `GG_World_Kit_R1` contains twelve original vertex-coloured meshes.
`qml/assets/authored/world/places/gg-world-places-r1.blend` stores both scenes;
`gg-world-architecture-r1.glb` exports the same local mesh geometry used by
the native renderer. The original scene remains intact.

The runtime reads `qml/assets/authored/world/world-places.json` and compiled
sector buffers, rather than the full Blender project. IDs live in custom
properties and survive object renames. Engine +Y up maps to Blender +Z up;
engine +Z maps to Blender -Y. World positions are metres at scale 1.

To edit the current layout in EXT:

1. Edit mapped objects, road curves or resident curves in `GG_World_Places_R1`.
2. Run `export_gg_world_places.py` inside the live Blender MCP `exec` tool.
   Its `export_world(apply=False)` function offers a read-only preview;
   `export_world(apply=True)` saves the map atomically. Instance scales must
   be uniform. Resident stop metadata is in `route_json`; a cyclic POLY is
   a LOOP, and an open POLY is a PING_PONG route with a real return journey.
3. From `projects/gg-ai-desktop`, compile the edited source without reauthoring:

   ```sh
   python3 tools/world/build_world_places.py --compile-only
   python3 tools/world/bake_world_trees.py
   python3 tools/world/generate_sandover_planet_map.py
   python3 tests/test_game_engine_world_places.py
   ```

4. Restart the game process to consume the new compiled assets.

`build_world_places.py` without `--compile-only` recreates the designed
starting layout and overwrites saved map edits. It is an authoring tool, not
a runtime operation. `build_gg_world_places.py` recreates only our two
dedicated scenes. `sync_gg_world_places.py` refreshes those scenes from the
saved source without reimporting the reference terrain; use it only when the
JSON source should replace the scene's mapped transforms/curves.

The exporter retains sub-millimetre source coordinates within Blender's
float32 precision. Changes to route point counts also require matching
`route_json` metadata. Exporting alone does not certify that newly edited
paths are clear of buildings; run the world-places test before playing them.

This first pass provides shared architecture and saved map editing. It is
not a bidirectional live sculpt-to-runtime importer for arbitrary new meshes.
After sculpting kit meshes, the native `.ggmesh` compilation and LODs must
also be updated and checked against the Blender export.

This directory contains the first authored-content generator for the GAME
ENGINE. It runs with Blender's bundled Python and keeps generated assets
separate from the runtime fallback geometry until they pass visual and import
regression checks.

## First authored character

From the repository root:

```bash
/home/GG/blender-5.2.2-linux-x64/blender \
  --factory-startup --background \
  --python projects/gg-ai-desktop/tools/blender/build_gg_clay_hero.py -- \
  --out projects/gg-ai-desktop/qml/assets/authored/gg-clay-hero-a.glb \
  --preview /tmp/gg-clay-hero-a.png
```

The script produces an original faceted clay character with a real armature,
skinned mesh pieces, `HEAD/CHEST/MAIN_HAND/OFF_HAND/BACK/FEET` sockets and the
GAME ENGINE clips `Idle`, `Walk`, `Sprint` and `Air`. It does not copy a mesh
or texture from a reference game.

`authored/gg-clay-hero-a.glb` is the canonical player asset after passing the
local validator and QML RuntimeLoader test. The historical
`gg-authored-hero.gltf` plus its sibling `.bin` are kept as a one-file-path
compatibility alias for desktop processes that were already open before the
promotion; they contain the same generated character, not a second visual
model.

## World kit

Coastal props (mangrove, cottage, lantern post) use the same clay language:

```bash
/home/GG/blender-5.2.2-linux-x64/blender \
  --factory-startup --background \
  --python projects/gg-ai-desktop/tools/blender/build_gg_clay_world.py -- \
  --out-dir projects/gg-ai-desktop/qml/assets/authored/world
```

Live world volume still renders through the bounded native geometry cache so
dozens of trees do not each take a RuntimeLoader slot. The GLBs are the
authored source of the same silhouettes.

## Fixed planet surface

`build_gg_sandover_planet_surface.py` runs inside the visible EXT Blender
scene through the `gg-blender` MCP `exec` tool. It samples
`backend.game_engine_terrain.height_at` with the shared fixed world seed and
exports `gg-sandover-planet-surface.glb`: separate Blender mesh objects for
the named landmasses and Sandover, plus the full bathymetric floor. The atlas,
the collision sampler and this asset therefore use the same coast and relief
contract. It also creates a new editable `.blend` project scene and an asset
manifest; the existing village `.blend` stays unchanged. The exported vertices
are projected with the same spherical `planetRenderY` formula as the player,
camera and far water, then imported in planet-local world meters at scale 1.
Resolution is adaptive: 8 m across the atlas, 3 m through Sandover's blend
zone, and 0.5 m over the original village island. The central island also
uses its layered sandstone, beach and grass palette. GAME ENGINE imports the
GLB through `GameEngineSurface.qml`; its nearby procedural terrain renderer
yields while this authored surface is active, avoiding a physics-only
landform or overlapping terrain meshes.

The asset covers the current deterministic atlas bounds. New landforms must
be added to `backend/game_engine_planet.py` and regenerated through this
Blender EXT path so the map, collision and visible mesh stay aligned.

## Existing Blender character set

`export_gg_codex_characters.py` promotes the original rigged `GG_Codex_*`
characters already stored in the Sandover Blender project. Run it through the
visible EXT Blender sidecar with the project scene open. It exports the player
and eight crowd/cast variants to
`qml/assets/authored/characters/`, reuses the existing `Idle`, `Walk`,
`Sprint` and `Air` Blender actions, and adds named equipment sockets. It
duplicates source objects for export, so it does not move or rewrite the
editable Blender character models.

## Visual EXT desk + MCP

The GG AI Desktop EXT tab hosts a real Blender window (same X11 embed path as
DRAW). A localhost sidecar inside that GUI exposes `ping`, `scene`, `exec`,
`screenshot`, `inspect`, `turnaround`, `deform_rig`, `clean` and `export_glb`
on `127.0.0.1:19876`. Grok talks to it through the project MCP server
`gg-blender` instead of a headless CLI render. `inspect` counts holes and
joints, `turnaround` writes front/side/back/three-quarter plus a wireframe,
`deform_rig` builds the 90-joint deformation skeleton, and `clean` refuses
to edit until `apply` is true.

```bash
python3 projects/gg-ai-desktop/tools/blender/gg_blender_mcp.py
```

Open EXT, wait until the status says MCP LIVE, then screenshot or exec against
the visible viewport. Headless `blender --background` generators above stay
for deterministic batch exports.

## Saved settlement places and resident routes

`build_gg_settlement_layout.py` consumes
`qml/assets/authored/world/sandover-settlement.json`, the same saved map used
by the game. It creates a separate `GG_Sandover_Routes_R2` scene with two
combined road/fence meshes, place and fixture anchors, road centerlines and
resident route curves. Passing `GG_LAYOUT_CONTEXT=True` adds the existing
village and terrain as visual references; `GG_SHOW_SETTLEMENT=True` leaves
the new scene visible in EXT. Run it with `runpy.run_path` through the
`gg-blender` MCP `exec` tool. It preserves the original scene and exports only
the route meshes to `gg-sandover-routes-r2.glb`; its separate `.blend` includes
the authoring anchors and curves.

`export_gg_settlement_routes.py` reads edited anchors and POLY curves back
into the JSON. Its `export_routes(apply=False)` provides a dry run, while
running the script as `__main__` writes changed map data atomically. Custom
properties retain map identities when Blender objects are renamed. Route
stop metadata keeps waiting times and activities. After an edit, rebuild
the layout and restart the game to load the new fixed map.

All 24 resident paths are saved in the map and editable in EXT. A cyclic
POLY curve exports as `LOOP`; an open POLY curve exports as `PING_PONG`.
The latter walks back through the same intermediate stops. The engine
allocates walking time to every return leg and keeps the route clock across
day/night and visual unloading. It never resets a living actor to its home
when a routine ends. A fixed home remains available for death/respawn.

The live EXT round trip, native/GLB world positions, colors, triangle counts,
terrain contact and resident save/load are covered by
`tests/test_game_engine_settlement.py` and the actual scene verifier
`tools/world/verify_settlement_scene.py`. This is an authoring foundation;
resident route labels do not imply a complete physical AI or new merchant
transactions.
