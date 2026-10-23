# GG GAME ENGINE · ten-layer foundation

## Native 3D physics — 2026-10-13

The engine now owns a general Box3D physics scene with static, kinematic and
dynamic bodies, eight collider families, nine joint families, continuous
collision, queries, contact/sensor events, sleep and native recording
verification. The complete pinned C17 core is attributed and unmodified;
GG's C ABI and Python adapter handle validation, lifetime and bounded output.

The existing 60 Hz runtime advances configured physics once per tick, clears
it on reset and releases it on shutdown. Native positions/quaternions reach
explicitly registered Qt physics nodes through the render stream. The finite
desktop command interface supplies geometry and controls without selecting
game content. Build receipts verify the native source and binary before load.
See [GAME_ENGINE_PHYSICS.md](docs/GAME_ENGINE_PHYSICS.md) for the API, build,
tested capabilities, limits and recording semantics.

## Authored caricature variants — 2026-10-05

The approved bent palm, scooped cottage roof and grass-capped rock establish
`GG_PS2_CARICATURE_R1`. Google Images study captures for Jak, Ratchet, Crash,
WildStar, Conker, Spyro and Rayman are saved under
`docs/style-research-google-2026-10-05/caricature-assets`. Remakes, unrelated
asset packs and fan art are excluded from original-game comparisons. Study
boards are visible in the EXT review scene and excluded from game exports.

The rock library has 36 individually composed silhouettes: ledges, crooked
stacks, wedges, broken slabs, clusters and open stone spans. Each has a named
construction; the six related families no longer repeat six small distortions
of one model. Seven tree families have four branch/crown layouts each. Eleven
flora families have four editable near meshes and matching simpler meshes.
Twelve settlement prop families have four near models; the active actor,
equipment, weapon and nature catalogue contains 74 base assets and 296 GLBs.
Four cascade sheets decorate six saved steep river segments while retaining
the authoritative river level and slope. Existing lakes and roads retain their
eight distinct lake outlines and 52 saved road routes.

Shape changes are compiled offline. Persistent object identities choose model
variants, independently of camera heading, loading order and simulation time.
Near and middle-distance tree/settlement buffers partition saved instance
transforms between four meshes; distant sectors keep one shared simple family
mesh and the existing two-upload-per-tick cap. This avoids multiplying all
horizon batches by four. The starting island also shares the four palm and
mangrove variants, with its 23 instance transforms and top heights preserved.

`tools/world/verify_caricature_assets.py` compares protected binary streams
against the original art checkpoints: rigs, weights, clips, sockets, indices,
UVs and colours remain unchanged; all local texture references exist. Positions
and normals alone are deformed. Existing movement, harvest, combat and enchant
tests cover the gameplay seams. The editable review library is
`qml/assets/authored/variants/gg-caricature-variations.blend`; viewport captures
and real client measurements are in
`docs/style-development-2026-10-05/asset-library` and
`caricature-variants-native` / `caricature-variants-coastal`. Static client
measurements are bounded samples, not a guarantee for every region or machine.
The older `test_game_engine_assets.py` still hardcodes a retired 90-joint,
four-clip character and predates the current 25-joint, eleven-clip crew; it is
not the regression contract for these protected-stream changes.

## Real enchanting scrolls and colored weapon effects — 2026-10-05

`backend/game_engine_enchants.py` is the authoritative catalog: twelve single
color/effect presets, six paired presets and three level-60 artifact presets.
The three families are OFFENSIVE (elemental hits, burn, poison), DEFENSIVE
(ward, weaken, slow, snare, attack interval) and RECOVERY (healing, regeneration,
lifesteal). Tier 1 has one effect, tier 2 has two, and tier 3 requires all three
families and maximum character level. Six separate gear enchants boost actual
health, stamina, armor, critical chance, attack speed or spell power.

At the deterministic enchanting-table position near the starting camp, the
inventory's ENCHANTING panel creates persistent, individually identified
scrolls. Players can choose presets or compose one to three single effects;
custom IDs are canonicalized, and three-effect recipes require one effect from
each family. Crafting requires physical proximity and consumes fiber, runic oil
and moon shards. Artifact scrolls require level 60 both to craft and apply.
Applying a new enchant requires its owned inventory scroll, compatible gear and
one of the existing two enchant slots. Validation precedes both mutations;
failed applications retain the scroll and successful ones consume exactly one.
Existing saved legacy enchant IDs remain compatible.

Equipped weapon IDs resolve trusted on-hit rules in combat. Failed attacks do
not apply effects. Timed statuses refresh without delaying damage/healing ticks;
slow and snare affect real NPC velocity without changing positions or routes.
Ward absorbs actual incoming damage, regeneration/healing restore health and
lifesteal uses health damage actually dealt. Periodic damage defeats use the
same loot, XP, quest and memory hooks as direct kills, exactly once. Respawn
clears statuses. Item scroll IDs, gear metadata and combat status times survive
save/load. Starter effect values are initial balance data, not finished tuning.

The table and scroll have editable original Blender sources in
`qml/assets/authored/items/gg-enchanting-kit.blend`, textured GLBs, and a rendered
inventory icon. `GameEnchantingControls.qml` is shared by the real standalone
bag and workbench; the former's ENCHANTING button expands the recipe controls.
The generated WorldFx catalog comes from `tools/world/sync_enchant_catalog.py`.
Custom and artifact clouds cycle their exact two or three colors along the same
blade sockets at fourteen puffs per enchant; gear stat enchants use no blade FX.
Weapon-cloud diameter and radial spread are now twice the original size, with
25% stronger opacity for visibility. Particle counts and blade anchors are unchanged.

Validation: `tests/test_game_engine_enchant_scrolls.py` checks all presets,
visual/catalog parity, actual hits/statuses, scroll atomicity, category/level
checks, custom recipes, rewards, gear-derived stats and isolated save/load.
`tools/world/verify_enchant_scrolls.py` exercises real scroll APIs in the rendered
client, reviews all twenty-one palettes, checks the standalone controls and
captures the authored table. Artifacts are in
`docs/style-development-2026-10-05/enchant-scrolls/`.

## Painted V4, saved decorative foliage and bounded effects — 2026-10-05

V4 corrects the earlier noisy image pass with broad, simplified painted forms,
individual repeat scales/detail strengths, vertical wood grain and a separate
quiet turf correction. Original sources and exact built-in image-generation
prompts live in `qml/assets/authored/world/textures/clay-v4/`. The 131 GLB
wrappers retain their original position/normal/rig/animation data. Cottage
geometry is now deliberately revised as well: curved asymmetric roofs, carved
thick framing and round windows, with matching roof collision queries and
unchanged saved placement transforms.

The separate saved cosmetic layer in `world/ground-cover/` contains 434,030
noninteractive grass, fern, flower and leaf cards across the world. Four shared
cutout materials billboard around stationary roots. 128 m sectors stream with
paced uploads and profile ranges of 64–224 m (PS2_CLASSIC: 128 m), without
collision, gameplay entities or shadow maps. The existing long-range trees
and architecture retain their own range policy. Camera rotation reuses saved
instance tables instead of changing plant positions.

Equipped weapon enchants use fourteen soft, camera-facing colored clouds per
enchant along the actual mesh's blade base-to-tip region. The Iron Saber has
explicit authored/native regions and a wider equipped blade silhouette; other
weapon regions remain a content-authoring follow-up. UV radial falloff and
subtle edge movement retain the metal silhouette. These differ from the
separate free fire/lightning ability previews. Vanilla WoW image reference and
limits are recorded in `docs/style-research-google-2026-10-05/weapon-enchants/RESEARCH.md`.

Fire, magic and XP wisps use a shared HDR additive batch; smoke/foam use a
separate alpha batch. Total visible particles remain capped at 256. Positions
follow actual equipment scene nodes and the planet's render curvature. Ability
auras and defeat XP visuals consume existing authoritative snapshot events.
Bloom is restrained and disabled for POTATO. Lamp surfaces emit light, with at
most four nearby warm PointLights; emissive models remain visible farther away.

The editable EXT workspace retains all five original scenes and a new four-card
foliage scene. A reproducible Blender library-write crash for the new scene is
avoided with a regular background save. Existing authored scenes and 2197
world/landscape/route transforms were recovered, verified and saved intact.
The current review, exact prompts, validation evidence and remaining art gap
are recorded in `docs/style-development-2026-10-05/ten-pass-review/REVIEW.md`.
The V3 section below describes the preceding pass rather than current assets.

## Painted image materials — 2026-10-05

The next pass wraps the existing authored models with sixteen original image
materials, generated with the built-in image generator. The source atlas,
production tiles and exact prompt live in
`qml/assets/authored/world/textures/clay-v3/`. The generated source is
1254 × 1254; runtime tiles are 256 square, with periodic edge conditioning and
eight-pixel gutters in a shared 1088-square native atlas. Wood grain, bark,
rounded roof tiles, plaster, stone, foliage, soil, snow, water, cloth, leather,
metal and soft clay skin now have painted image detail.

`wrap_gg_clay_textures.py` adds ordinary UVs and image materials to 131 existing
GLB assets, retaining original position, normal, skin and animation bytes.
Palette-only character meshes recover material roles from their authored crew
palettes: skin stays distinct from similarly colored cloth, and eyes retain
their original material. Recompilation replaces appended data instead of
accumulating it. Color-neutral companion images retain authored vertex/faction
tints in Blender/glTF; native batches sample the colored shared atlas with
object-local projection and smooth foliage/rock blending. Explicit derivatives
and material-specific distant averages prevent atlas bleed and repeat-grid
mip artifacts. No new instances, lights or geometry were introduced.

The open EXT workspace retains all five scenes, including the original study
scene. Four authored world scenes preserve 2197 object transforms. Editable
flora, nature, village, terrain, item and nine crew source files are saved with
image nodes and UVs. Use `wrap_gg_clay_sources.py` for background source updates;
library appends into the large live workspace proved too slow. Blender was
recovered from its current autosave after an interrupted import, and its five
scenes were verified and saved back to the normal EXT workspace.

Texture binding/geometry/rig invariants, repeat compilation, world placement,
population/route, landscape and tree regressions pass. Real-client rotation
checks retain the same GPU tables and forest pixels, including the culling-off
and range-return cases on the final isolated run. The final Ashbell preview
measures 59.38–60.06 display-capped FPS, zero pending batches and zero rendering
warnings. This validates these views rather than every device or cold-load
case. Two older asset/QML tests still expect the superseded character binding
and fail; those expectations were not rewritten as part of this art task.
Evidence is in `docs/style-development-2026-10-05/painted-v3/` and
`docs/gameplay-performance-2026-10-04/tree-rotation/`.

## First visual style slice — 2026-10-05

The Google image research now feeds an implemented first art pass in Ashbell
Crossing. The 640 m fixed ground footprint adds broad colour washes, smaller
brush variation, walked margins and static contact shading. It uses one
2048-square texture and world-anchored UVs on the existing Westreach terrain
primitive. Terrain positions, normals and indices remain exact; the added UV
buffer is 887,544 bytes. `deform_world_surface.py` reapplies the art pass after
its normal topology bake. The original textures and shapes from the reference
games are not imported.

The shared cottage kit has a bowed, thick roof, timber framing, window frames
and a stone footing. The doorway stays open and the roof query uses the same
profile as the mesh. Near-road shoulders blend through vertex colours rather
than transparent decals. A shared architecture material supplies restrained
surface variation. The classic lighting profile has a warmer key and lower
cool fill. Flora uses smooth normals on organic volumes while retaining the
same vertex positions, indices and triangle counts; the distant tree meshes
remain at or below 40 triangles.

The open Blender EXT kit was updated through its sidecar, preserving all 1,871
scene object transforms. Its saved GLB and native kit pass the existing parity
and traversal checks. World placements and NPC routes are unchanged.

`tools/world/verify_style_slice.py` records two fixed real-client views and a
camera-return check. The final run is around 60 FPS on this machine with zero
pending batches, zero rendering warnings and unchanged resident GPU tables
after rotation. This is a display-capped PS2_CLASSIC view check, not a benchmark
of cold loading or every graphics profile. Evidence and before/after images
are in `docs/style-development-2026-10-05/`. The world places/population and
world tree regression checks pass. Mountain ridges, rock outcrops, shore forms
and distinct regional architectural art remain subsequent work.

This document records the implementation direction for the MMO playground:
PS2-era discipline (fixed budgets, small data, baked work, deterministic
simulation) combined with modern Qt RHI/temporal rendering where it earns its
cost.

## Original intent

An over-the-shoulder MMO with the simple readability of WoW, Jak and Sly:
ground, swimming, flight, sea travel and underwater movement share one easy
input language. The world should feel like a globe at orbital scale and like a
playable flat landscape near the character. Visible places are intended to be
reachable, while the player and developer can author content in the world.

GAME ENGINE and EXT are the authoring tools. Their saved scene, game rules and
Blender-exported runtime assets feed a separate player client. The player has
its own window, HUD, action bar, settings and addon/interface menus; editor
navigation, diagnostics and authoring controls stay in the workbench.

## Ten implementation layers

1. **Movement and camera** — fixed-step input, WoW-style character-facing
   movement (`W/S` move, `A/D` turn, `Q/E` strafe), independent right-mouse
   orbit camera, yaw/pitch/distance and camera-relative world fields.
2. **Seamless traversal** — `GROUND`, `SWIM` and `FLY` share movement grammar;
   constraints change without a zone transition.
3. **Planet and streaming** — stable cell keys, deterministic interest cells,
   projected-error LOD metadata and a local tangent frame mapped to a
   double-precision planet frame. The current slice now also emits a
   deterministic analytic heightfield, biome, water-depth, cell-edge and
   visibility contract for every loaded cell.
4. **Abilities and combat** — data-driven Surge, Undertow and Sky Leap with
   resource, cooldown, impulse and pooled FX, plus bounded actor health,
   deterministic attacks, retaliation, defeat loot and respawn; edge-triggered
   input prevents held-key event spam.
5. **RPG economy** — deterministic affix loot, enchant slots, recipes,
   inventory counts, races, classes, specs, talents, XP, ascension and paragon
   state.
6. **In-game editor** — bounded versioned scene document, live primitive
   placement and undo; developer and user commands share the same document
   operations. Terrain authoring now adds bounded per-cell height, biome and
   water overrides with its own undo history and memory persistence.
7. **Low-cost renderer** — QtQuick3D through Qt RHI, bounded render lists,
   per-entity cell/LOD metadata, allowlisted glTF 2.0 RuntimeLoader assets,
   SceneEnvironment NoAA/MSAA/SSAA and measured host snapshot timing.
8. **MMO seam** — sequence-numbered local-loopback network contract, cell
   interest, quantized-cell replication plan and memory-only persistence.
9. **Cinematic diorama** — over-shoulder/diorama/orbit presets, baked-key
   lighting, sparse dynamic contact effects, filmic tone mapping and a visible
   orbit representation.
10. **Optional modern GPU layers** — explicit POTATO/BALANCED/MODERN/CINEMATIC
    policy profiles. DLSS, FSR and XeSS remain extension points. Native flora
    instancing is implemented; Qt GPU timestamps are enabled in the isolated
    rendering probe, with unavailable values kept explicit in normal use.

## Facts and findings

- The first standalone Linux client now mounts the same `GameEngineSurface`
  renderer in player mode, so it uses the current playable island and asset
  bindings without carrying the desktop workbench host. Its small Qt bridge
  exposes only simulation, input and render geometry. The standalone window
  owns its pause/settings/addon screens and player HUD.
- The launcher has a local development mode that reads the checkout directly.
  Installed packages check the stable GitHub Release feed and accept only the
  versioned Linux game archive after verifying its published SHA-256 digest.
  Updates are installed in a version directory and selected by an atomic
  pointer, leaving the source checkout and previous installed version intact.
  A release package must be published before another computer can download
  the project’s changes.

- The current desktop has Qt 6.11/PySide6 and QtQuick3D available, so the
  first renderer can use the existing native Qt RHI without importing a large
  engine or proprietary assets.
- The current Qt surface successfully loads and renders the built-in primitive
  scene offscreen. Qt's `View3D.renderStats` is separate from the host's CPU
  snapshot timing.
- Loaded terrain cells now carry a compact LOD-sized height grid. A lazy
  QtQuick3D geometry cache turns those grids into indexed position/normal/UV
  meshes (`5x5` near, `3x3` mid, `2x2` horizon), while retaining the same
  analytic height query used by movement and water.
- Terrain patches add a shallow edge skirt to the native mesh. It hides only
  cross-LOD T-junction cracks; the shared analytic heights, normals and
  physics samples remain the source of truth.
- Terrain patches keep their seabed geometry in shallow/deep cells instead of
  deleting every water-cell mesh. The shared sea-level surface hides the
  submerged part, while the continuous heightfield prevents rectangular holes
  at shoreline transitions. Normals are sampled from the global field so
  different LOD densities do not introduce a lighting seam at a cell edge.
- World scale is now explicit: one gameplay unit is one game metre, the
  authored character fixture is about `1.5 m` tall, and the default third-
  person camera starts at `18 m`. The default gameplay interest set is still
  `7x7` cells (`49` cells / `112 m` coverage), while presentation streams a
  separate `21x21` render set (`441` cells / `336 m` coverage). The outer
  render-only `ORBIT` cells use thin HLOD tiles instead of disappearing;
  physics, NPC navigation and network interest remain on the smaller set.
- Character-like actors use one active visual model. The player uses the
  original `GG_Codex_Original` Blender character; NPCs and ambient actors use
  deterministic variants of the rigged GG Codex Blender characters. A shared
  low-poly humanoid geometry remains the fallback while an authored loader is
  unavailable or exceeds its eight-instance budget. The existing fixed-step
  root pose and Blender `Idle/Walk/Sprint/Air` clips drive the same characters.
- Authored character import now has a bounded local glTF 2.0 seam. The backend
  validates source, buffer, mesh, vertex, joint and animation budgets once at
  runtime start, then publishes an asset binding beside the unchanged
  animation state/phase contract. QML uses `RuntimeLoader` for at most eight
  character instances and takes over when the imported scene has a real
  visual child. A missing clip is reported as `ROOT_POSE_ONLY` and keeps that
  same authored model visible; there is never a second character body.
- The item layer now separates authored definitions from runtime instances.
  One definition can be represented as a ground drop, container content,
  inventory stack, equipped item or NPC pocket item, with an explicit rarity,
  context visual and bounded state transition. This is the contract needed for
  loot tables, equipment and future modular attachments without duplicating
  item rules in QML.
- The first item catalogue carries the full rarity ladder (`TRASH` through
  `ARTIFACT`), weighted deterministic coastal/goblin loot tables, a supply
  crate with contents, a visible saber/shard/boot drop, and player/NPC item
  ownership. Item and world-prop rows now resolve through the native clay
  asset kit: one indexed, vertex-colored mesh per bounded asset family. The
  old shared 12-segment/6-ring sphere remains only as an explicit compatibility
  fallback for a host that has not exposed the asset-geometry slots; the
  current host never uses it for a known item or prop.
- The official [Khronos glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)
  confirms that skins bind joints and inverse bind matrices to a mesh, while
  animations store node keyframes; it intentionally leaves playback order,
  looping and runtime selection to the client. The engine therefore keeps
  `IDLE/WALK/SPRINT/AIR` selection and root-pose blending in the game-side
  contract instead of hiding it in a file format.
- Qt's [RuntimeLoader documentation](https://doc.qt.io/qt-6/qml-qtquick3d-assetutils-runtimeloader.html)
  confirms local glTF 2.0/GLB loading and explicitly warns that the loader does
  not sandbox or validate asset contents. Qt's [asset introduction](https://doc.qt.io/qt-6/quick3d-asset-intro.html)
  also notes that runtime loading is significantly less efficient than the
  offline Balsam path. The current importer consequently stays allowlisted,
  validates before QML, and reserves RuntimeLoader for the bounded authored
  seam rather than the eventual high-volume item path.
- The official [Unreal World Partition overview](https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition-in-unreal-engine)
  and [MassGameplay overview](https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-mass-gameplay-in-unreal-engine)
  reinforce the same scalable shape: distance-based cell streaming, data
  layers, representation LODs, instanced low-cost representations and object
  pooling. The local engine applies the principles as compact cell/LOD/item
  budgets without importing Unreal code or claiming its runtime.
- The official [EQS documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/environment-query-system-in-unreal-engine)
  and [AI Perception documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/ai-perception-in-unreal-engine)
  support a later living-world layer where bounded perception/events feed
  decisions. The current NPC state machine remains intentionally smaller, but
  item interaction already emits inspectable events that can become stimuli.
- The GAME ENGINE stage now fills the body and places the navigation and
  inspector cards above it as translucent overlays, following the OSINT
  surface's information-dense composition instead of reserving two opaque
  columns beside the render view.
- The input contract now keeps camera orbit separate from ground locomotion:
  the character's yaw is authoritative for W/S and Q/E, while A/D changes
  that yaw in place. Primary and alternate keys are bounded data, so a replay,
  native client or future editor can consume the same action IDs. The project
  pins the classic mapping intentionally even if a current live WoW update
  changes its defaults.
- The addon seam borrows the useful architecture of WoW unit-frame systems:
  state producers publish small named elements and layouts decide how to show
  them. The local registry is event-driven, explicitly budgeted and native
  data-only; it does not execute arbitrary third-party scripts. The first
  `UNIT_FRAMES` view is a compact player/resource/cell/target overlay. The
  keybinding and addon profiles travel through the existing memory-only save
  seam, so a world reset does not unexpectedly erase the user's layout.
- Research of the requested PS2 material, including the
  [Renkai Games retrospective](https://www.youtube.com/watch?v=QUBrrCTKOmQ),
  reinforces three engineering rules: prototype low-resolution gameplay and
  animation before final assets, use shared LOD/instancing paths for vistas,
  and treat texture/streaming memory as a live budget. Those rules are more
  valuable to this project than copying any one engine's surface API. The
  source-by-source review and application plan are in
  [PS2 action-adventure research](docs/PS2_ACTION_ADVENTURE_RESEARCH.md).
- The physics slice now exposes a bounded TSEU-inspired energy ledger for the
  player: tagged rest and kinetic energy are summed into an explicit
  game-mass equivalent with `E / c_game²`. Charge is kept as a separate
  gameplay channel, and no gravity or electromagnetism solver is claimed.
- The same module contains guarded real n-th roots, logarithm-based powers and
  arbitrary small-dimensional L-p norms. The fixed p=2 path remains a direct
  `sqrt` fast path because the identity is a tool for generality, not a reason
  to make the 60 Hz loop slower.
- The first NPC slice uses three deterministic archetypes (`WANDERER`,
  `GUARDIAN`, `CRITTER`) in the same entity pool as the player and props. A
  small state machine (`WANDER`, `FOLLOW`, `ALERT`, `FLEE`, `DEAD`) samples
  bounded sight perception at 20 Hz while movement remains at 60 Hz.
- NPCs expose their state, target, home cell, perception radius and reason in
  a compact inspector contract. Their movement is bounded by an authored home
  radius; line-of-sight uses a cheap static-circle segment test, and each
  decision may attach a short heightfield A* route with direct steering fallback.
- The first tiled navigation seam is now present: a `4 m` tile grid is built
  from the same terrain heightfield, with slope/step checks and bounded
  four-connected A*. The runtime caches tiles until the loaded cell set,
  movement mode or terrain authoring revision changes. NPC queries use the same
  cache, so pathfinding does not create a second terrain representation.
- Player locomotion has a small deterministic controller contract: W/S moves
  along character-facing, A/D always turns, Q/E remains an independent
  strafe, and diagonal input is normalized. Ground
  jumps use a short input buffer, coyote window and hold-sensitive height.
  The camera follows player heading with a separate right-mouse orbit offset,
  keeping its default view behind the avatar without steering movement.
  Distance and pitch remain in the shared camera snapshot.
- A small last-seen stimulus memory makes occlusion readable without a heavy
  behavior tree. The player can interact with or attack the nearest in-range
  NPC after bounded line-of-sight validation, producing a real content hook,
  combat transition or explicit occlusion result and an inspectable event.
- A large-world representation must keep global/planet coordinates away from
  the GPU and render camera-relative local coordinates. Cell keys are therefore
  part of the shared world contract, not merely a loading-screen concept.
- A continuous height function is a useful first terrain primitive: it gives
  land, shoreline, deep water and air-column data without an asset import or a
  giant vertex buffer. Cell LOD can sample the same function at different
  densities, so neighboring cells do not need a hidden seam fix.
- Water is a shared sea-level contract in this preview. The renderer can show a
  cheap local surface while the snapshot still describes the same cells below
  and above it; this keeps land, water and air from becoming separate worlds.
- Authoring deltas are stored per cell instead of baking a second terrain copy.
  Each delta is evaluated as a smooth cell-centred brush with zero strength at
  its support edge. That preserves the deterministic base world, keeps edits
  continuous across streamed cell boundaries, makes undo cheap, and gives a
  future server or content compiler a small patch list to validate.
- Sub-cell height authoring is now a second bounded patch list, separate from
  cell metadata overrides. Each stamp stores a cell anchor, world-space point,
  radius, signed strength and one of four deterministic falloffs
  (`SMOOTH`, `LINEAR`, `SHARP`, `GAUSSIAN`). The heightfield evaluates the
  stamps as one global function, so a brush can cross a cell boundary without
  duplicating vertices or introducing a seam.
- The terrain evaluator builds a small touched-cell index for the current
  snapshot. Height samples only visit stamps whose radius can reach that cell;
  this keeps the 128-stamp authoring budget cheap enough for the local
  snapshot path instead of turning every sample into a full-list scan.
- The in-game terrain target is selected from the rendered View3D when possible
  and falls back to the projected centers of the current interest cells. The
  backend revalidates the target against the loaded set, so mouse/brush input
  cannot author an unloaded or arbitrary far-away cell.
- Vendor upscalers and a custom `QQuick3DInstancing` subclass require a native
  plugin/runtime integration; a policy label alone is not evidence that they
  are active.

## Decisions

- Keep simulation data-oriented and bounded before adding visual complexity.
- Keep content, world, editor, render and network contracts as importable
  Python data layers so they can later be consumed by a native runtime,
  server, editor or QML surface.
- Use invisible cell streaming and HLOD/point-detail ideas for far data, not
  visible loading zones.
- Keep terrain cells compact: four corner samples plus a center sample are
  enough for the first renderer pass; detail geometry remains a replaceable
  representation selected by projected-error LOD.
- Let editor commands modify bounded cell patches and keep the analytic base
  immutable. Player/developer authoring can then share the same command path
  without turning the local preview into an unbounded voxel store.
- Keep geometry generation separate from simulation: Python produces the
  compact cell contract, while a bounded QtQuick3D cache owns native mesh
  objects and replaces only a cell whose height grid changed. This gives the
  preview real slopes without making the runtime depend on a large asset
  importer.
- Keep target selection bounded to loaded cells, but let the brush point be
  sub-cell: Shift-click/drag chooses a loaded cell and projects a world-space
  point inside it. Brush mode emits distance-gated stamps as the pointer moves,
  with radius and falloff controlled in the SCENE inspector. The backend clamps
  all values and owns the undo/persistence contract.
- Keep the brush representation analytic and stamp-based for now. It is a
  compact authoring layer that can later be compiled into a native patch mesh,
  tiled height texture or server-approved delta stream without changing the
  editor gesture or gameplay query API.
- Treat TSEU as an explicit energy-accounting interface, not as a new gravity
  theory. The game ledger must label its unit system and keep charge separate;
  a real GR mass, curvature solver and vacuum treatment belong to a different
  validated physics layer.
- Keep NPC decision logic small and deterministic: lower-frequency perception,
  fixed state transitions, bounded sight stimuli, authored daily schedules and
  local steering are enough to make the world feel inhabited before adding a
  larger dialogue system. The current tiled A* backend replaces the
  target/steering seam while preserving the bounded fallback; crowd avoidance
  remains deliberately disconnected.
- Spend the budget on composition, lighting, silhouette, animation and
  interaction before expensive material graphs, motion blur or dense geometry.
- Keep camera orbit and character-facing movement separate. The default action
  map is deliberately familiar (`W/S`, `A/D`, `Q/E`) but every action can be
  rebound through one bounded registry; this prevents a future UI layout from
  inventing a second control language.
- Keep UI information in small overlay addons rather than growing a permanent
  opaque side wall. Unit frames, action state, NPC state and loot/craft data
  should be independently visible, disableable and measurable.
- Keep the current figure representation as a shared low-poly body geometry
  plus one skin-colored head. Use eight cached phase variants for the current
  readable limb motion; authored rigs enter through the allowlisted asset seam
  and keep the same animation state/phase vocabulary. Do not let asset loading
  change movement, camera or the fixed render budget.
- Keep item definitions, instances, contexts and visuals separate. Inventory
  counts remain compatible with the old RPG contract, while instance state is
  the source of truth for ownership, placement, equipment and containers.
  Ground item rendering is visual-only and does not consume physics/NPC pool
  slots; all interaction commands revalidate proximity and use bounded
  deterministic transitions.
- Use one item asset identity across contexts. The native asset kit maps that
  identity to a cached low-poly sword, axe, bow, shield, wearable, compass,
  plant, crystal, consumable, lantern, totem or chest silhouette while rarity
  colors, bob/spin and equipped attachment remain data-driven. Later authored
  static meshes can take the same binding without changing loot, inventory or
  camera code.
- Keep all MMO/account/filesystem and vendor-GPU connections disabled in this
  local slice.

## Patch notes · 2026-09-13 · stable 3D models and overlay rails

The QtQuick3D surface now keeps bounded `ListModel` identities for terrain,
entities and particles. Snapshot rows are updated in place, so a 60 Hz status
update no longer destroys and recreates every `Repeater3D` delegate. This
removes the observed asset flicker/disappearance when PLAY starts or movement
changes the snapshot.

The left navigation is now a finite menu ending at `UI`, with a separate
`ENGINE` rail at the bottom. Its hamburger collapses only that navigation
menu. The right inspector has an independent arrow that folds the whole
inspector into a narrow bar and restores it without covering the stage with a
second opaque wall. The OSINT-style transparent overlays remain the default.

The QML input boundary now compensates for QtQuick3D's positive Y rotation so
the classic mapping is visually correct: `A` turns left, `D` turns right,
`Q/E` strafe, and the right mouse button only orbits the camera.

## Research ledger · 2026-09-13 · video and math follow-up

The accessible index/mirror evidence adds several useful implementation
patterns:

- Tsoding's [One Formula That Demystifies 3D Graphics](https://www.youtube.com/watch?v=qjWkNZ0SXfo)
  is a compact perspective-projection exercise. The visible chapters are
  `HTML Canvas`, `Screen Coordinates`, `3D projection`, `Z Translation`, `XZ
  Rotation`, `Wireframe` and `Why does it even work?`; the project uses the
  same inverse-depth principle in projected-error LOD decisions while leaving
  final projection to Qt RHI.
- The visible video [Y19Mw5YsgjI](https://www.youtube.com/watch?v=Y19Mw5YsgjI),
  `How One Guy FIXED Procedural Generation` by Game Dev Buddies, names the
  Oskar Stålberg/Townscaper path directly. Its visible chapters are `Oskar`,
  `Regular Grid`, `First Issue`, `Dual Grid`, `New Pieces`, `Grid Deformation`
  and `Stalberg Grid`. The transferable lesson is a small topological grammar
  that turns simple user placements into varied roofs, bridges and façades; it
  is a better fit for a future in-game authoring layer than storing millions
  of unique meshes.
- [A simple procedural animation technique](https://www.youtube.com/watch?v=qlfh_rv6khY)
  is mirrored with a chapter summary and source code in
  [animal-proc-anim](https://github.com/argonautcode/animal-proc-anim):
  distance/angle constraints, parameterized silhouettes and FABRIK are cheap
  ingredients for fish, snake, lizard and creature-like motion. Our next
  authored-rig seam can use the same fixed-step pose contract.
- The indexed [Make systems not games](https://www.youtube.com/watch?v=QPuIysZxXwM)
  material reinforces reusable, independently tested modules. That matches
  the current content/addon/editor contracts and keeps a large MMO idea from
  becoming one untestable scene.
- [XpG3YqUkCTY](https://www.youtube.com/watch?v=XpG3YqUkCTY), `How I Learned
  Procedural Generation` by Lejynn, describes a complete procedural low-poly
  terrain generator with a skybox, terrain and stylized water shader. Its
  visible chapters are `Terrain Generation`, `Coloring the Terrain`, `Diving
  into Shaders`, `Creating Vegetation` and `Exploring the Island`. The engine
  keeps the same seed/cell principle but validates every streamed cell and
  authoring delta locally.
- [J1sFBDQt8J0](https://www.youtube.com/watch?v=J1sFBDQt8J0) is indexed as
  Pixel Overload's pixel-animation tutorial. Its useful abstraction for this
  project is readable silhouettes, anticipation/overshoot and carefully chosen
  frame timing—not a literal pixel-art renderer.

- [U0a-IE5xawo](https://www.youtube.com/watch?v=U0a-IE5xawo), `The Trick To
  Instantly Make Your Game FUN` by Thomas Brush, and
  [Dtu1cozxL-Y](https://www.youtube.com/watch?v=Dtu1cozxL-Y), `I Turned a Boring
  Platformer Into an Addicting One` by Coding Quests, are game-feel references.
  The visible pages confirm their titles and context, but no complete
  transcript was exposed; therefore the implementation takeaway is limited
  to a testable `game feel` pass for movement, feedback, sound and world
  activity rather than attributing a specific recipe to either creator.

- [GXh0Vxg7AnQ](https://www.youtube.com/watch?v=GXh0Vxg7AnQ), `Simulating soft
  body animals` by argonaut, extends the same author's procedural-animation
  direction toward softer bodies. Together with `animal-proc-anim`, it
  supports keeping pose/constraint evaluation in a bounded fixed-step layer
  and letting the renderer consume a compact pose result.

- [nXrEX6j-Mws](https://www.youtube.com/watch?v=nXrEX6j-Mws), `Coding a Physics
  Engine from scratch!` by Zanzlanz, and
  [OSAOh4L41Wg](https://www.youtube.com/watch?v=OSAOh4L41Wg), `Simulating Atoms
  in C++` by kavan, reinforce a clean split between local simulation state and
  presentation. That is useful for the engine's deterministic physics seam,
  but neither video is treated as a specification for the MMO's physics.

- [VjgEOoCZ3Ys](https://www.youtube.com/watch?v=VjgEOoCZ3Ys), `I Simulated a
  Galaxy in Python` by DevPotato, is a recent small-scale physics/math
  experiment. It is relevant to a later orbital/space sandbox and to the
  project's globe-versus-local-coordinate distinction, not to the hot path of
  ground movement.

- [Nu8wLR4QqSE](https://www.youtube.com/watch?v=Nu8wLR4QqSE), `Crazy Computer
  Science Concepts (#1)` by Lattice, was resolved by title only in the visible
  pass. It remains an inspiration pointer, not evidence for a particular
  engine design.

- The visible pages did not expose complete spoken transcripts for these
  links. When YouTube exposes only title/chapters/description, the research
  process records those fields and refuses to turn comments, recommendations
  or search snippets into quotations from the video. This is the current
  answer to the transcript problem: use visible-page metadata now, and accept
  a supplied subtitle/audio file when exact wording or full coverage matters.

The visible-browser pass also resolved `b3cuul06hJc` as Absolute Terry
Davis's [451 - Exploring The Flight Simulator And First Person Shooter's Code
(TempleOS) [2015]](https://www.youtube.com/watch?v=b3cuul06hJc). The visible
chapter list is `Intro`, `Eagle Dive`, `Making The Map`, `How It Works` and
`Castle Frankenstein`. The transferable lesson is inspectable, direct data
ownership and a small map/scene pipeline—not a claim that the video supplies
the project's exact implementation.

The visible pass resolved the exact title for every supplied video, but did
not expose a complete spoken transcript for most of them. The pages provide
enough metadata to record these as bounded findings: `The Trick To Instantly
Make Your Game FUN`, `Simulating soft body animals`, `I Simulated a Galaxy in
Python`, `Coding a Physics Engine from scratch!`, `Crazy Computer Science
Concepts (#1)`, `I Turned a Boring Platformer Into an Addicting One` and
`Simulating Atoms in C++`. Comments, recommendations and search snippets are
not treated as quotations from any of those videos. Exact transcript work
still requires an exposed YouTube transcript or a subtitle/audio file; the
engine contracts do not depend on that missing text.

The TSEU note remains deliberately modest: `E/c_game²` is a tagged gameplay
energy ledger, not a new theory, a derivation of `G`, or a replacement for GR.
The log/exp identities are validated numerically for positive domains and
bounded dimensions; `sqrt` stays on the p=2 hot path.

## Assumptions and unresolved work

The planet radius is a provisional test value; a fully native C++ terrain
compiler/streamer, vertex-buffer or height-texture export, boats, richer NPC
dialogue, crowd avoidance, authoritative server reconciliation, production
asset compilation, animation clip playback/retargeting, native instancing,
GPU timestamp plumbing, vendor upscaler plugins and a sandboxed third-party
addon ABI still belong to later implementation phases. The TSEU-inspired ledger is a local
bookkeeping view;
it does not derive `G`, solve Einstein's equations or include vacuum energy by
default. The current analytic brush and shared low-poly figure are intentionally
compact authoring/render layers, not a production MMO globe renderer or final
character art pipeline.

## Patch notes · 2026-09-14 · pose geometry lifetime

The observed `IDLE → WALK/SPRINT` disappearance was isolated to the native
custom-geometry boundary, not to entity simulation or movement input. QML still
had the player/NPC row and the head primitive, but an unparented
`QQuick3DGeometry` pose variant could lose its lifetime when a `Model.geometry`
binding changed.

The surface host still owns terrain geometry through `QObject` and
`QQmlEngine.CppOwnership`. The former character pose-geometry path remains
available only to backend geometry diagnostics; it is no longer instantiated
by the live QML scene. The character regression now cycles `IDLE`, `WALK` and
`SPRINT` and checks that one rectangle model remains visible with the fixed-
step pose accents.

The same pass keeps the LOD seam curtains but gives their normals an
upward-biased lighting normal. They still cover T-junctions, but no longer
render as unlit black diagonal cracks under the inexpensive directional light.
Terrain cache eviction now schedules old native patches for deletion through a
QObject-owned cache, preserving the fixed geometry budget while QML finishes a
delegate handoff.

## Patch notes · 2026-09-14 · authored/skinned asset seam

The next render layer is now wired without changing the simulation, camera or
performance contracts. `backend/game_engine_assets.py` admits only local
allowlisted glTF 2.0/GLB sources, checks bounded source and referenced-buffer
sizes plus mesh, primitive, vertex, joint and animation counts, and publishes
an explicit `AUTHORED_SKINNED` or preview-fallback binding. The runtime reads
that manifest once, while each character row carries only its asset id, source,
instance rank, clip mapping and root-pose phase.

`GameEngineSurface.qml` uses QtQuick3D `RuntimeLoader` for the bounded authored
character slots. Each character has one active visual model: the imported
authored rectangle when it has real visual children, otherwise one primitive
rectangle while loading or after failure. There is no separate preview head,
limb mesh or live pose-geometry replacement. The loader receives the existing
entity scale, root offset, bob, lean, sway and squash, so movement, camera
orbit, terrain physics and render cadence remain untouched. A bundled
eight-vertex hero fixture proves that a real skin, two-joint skeleton and an
`Idle` clip cross the seam.

The current fixture intentionally exposes only `Idle`: `WALK`, `SPRINT` and
`AIR` still report `ROOT_POSE_ONLY` until authored clips and a proper animation
controller/retargeting layer are added. The authored rectangle remains visible
in that state because the root pose is valid and no second body is needed.
This pass proves asset admission, one-model rendering and safe fallback; it is
not yet a production content compiler or clip-blending system.

## Patch notes · 2026-09-14 · living item/world-state slice

Follow-up: BAG now selects individual inventory/equipment instances. A bounded
equipment repeater displays all equipped slots, with separate hand, chest and
head offsets. Explicit stale item IDs fail without selecting another item.
Backend and offscreen QML tests cover simultaneous four-slot equipment and
dropping the selected crown. Attachments currently follow the actor root and
bob; bone sockets and authored item meshes remain future work. The later
render-continuity pass below closes the intermittent preview-body issue by
keeping loader identity and pose transport separate and retaining a real
preview until imported visual children exist.

The GAME ENGINE now has a bounded item graph beside the existing character and
NPC graph. `game_engine_items.py` provides ten item definitions, one supply
container, seven rarity levels, two weighted loot tables and explicit visual
states for ground/container/inventory/equipped/pocket contexts. Instances keep
their own owner, quantity, condition, position, container and equipment slot.

The reset scene now shows an uncommon saber, epic moon shard, trash boot and a
lootable supply crate. The player starts with an equipped saber and compass;
the crate contains a rare jacket and legendary crown; a wandering NPC carries
an artifact totem in a pocket. The same native QtQuick3D entity repeater renders
ground items, while an equipped model attaches to the player. Item visuals
float/spin deterministically and use the rarity color ladder.

The PLAY surface now exposes `INTERACT`, `PICKUP`, `EQUIP`, `OPEN CACHE`,
`LOOT CACHE` and `DROP`. Proximity is checked in the backend; opening preserves
container contents, looting transfers them to inventory, equipping replaces a
slot, and dropping creates a new visible ground state. The item graph is part
of memory-only save/load, so the state survives a local session round trip.

Four deterministic ambient-life proxies now follow authored routes through the
same pose contract as real actors. A separate `game_engine_life.py` contract
assigns roles (fisher, traveler, scout, carrier), a 120-second world clock,
day/night schedules and a bounded `PLAYER_NEAR` stimulus. They are render-only
for this slice and therefore do not consume the fixed physics/NPC pool; the
future schedule, perception and promotion layer can turn selected proxies into
full NPCs without changing the QML row shape.

This is a vertical slice of the requested rich world, not a claim that final
AAA assets, combat AI, dialogue or an MMO server already exist. The next
layers are real clip playback/retargeting, richer quest/dialogue content,
population-scale scheduling and offline asset compilation for high-volume
streaming.

## Patch notes · 2026-09-14 · authored static item takeover

The item graph now crosses the authored/static asset seam for two bounded
fixtures. `gg-authored-saber.gltf` and `gg-authored-crate.gltf` are admitted by
the same local glTF 2.0 validator, but are classified as `AUTHORED_STATIC` and
kept separate from the skinned character budget. Item render bindings carry
their source, unit scale, instance rank and item-loader budget; the existing
ground/container/equipped context state remains authoritative.

QtQuick3D `RuntimeLoader` replaces the primitive only after success. The
primitive remains visible during an empty/error loader state, and the loader is
bounded to 24 authored item instances. The first pass therefore shows a real
imported saber in the world and equipment path plus an imported crate, while
unassigned armor, materials and creature items continue through explicit
primitive fallback. The character regression also checks that every
character-like row has exactly one active visual path.

## Patch notes · 2026-09-14 · gear tables and individual world use

The item graph now has a separate `game_engine_gear.py` table contract. It
contains 15 equipment slots, four starter gear specs, six runes, six gems,
three exact-order runewords, six gear enchantments, ten resource/material
definitions, five world stations, seven station recipes and five profession
rows. Runes and gems are item definitions with their own context-specific 3D
states, so a material can later receive an authored mesh without changing
socketing or inventory rules.

Gear instances retain slot, base type, socket capacity, ordered socket rows,
runeword match, enchantment rows, quality, base stats and derived modifiers.
Socketing validates the owned insertable and exact capacity; a runeword only
activates when its complete authored sequence and base type match. The starter
player can therefore build `Tir → Ort → Tal` into the saber and see
`Tideguard` plus its derived bonuses. Enchantments are a separate two-slot
layer, and station recipes consume bounded materials, award deterministic
quality and advance the profession row. Memory-only persistence includes the
gear and profession state.

`game_engine_npc_identity.py` adds seven named individuals across the three
physics NPCs and four ambient proxies. Each carries an occupation, personality,
needs, goals, inventory/equipment references, relationship value and an
eight-entry memory. At 2 Hz an individual can observe the player, seek food or
water, inspect a ground item, haul a cache, visit a station, gather, craft,
explore or rest. Calm physics NPCs may use that bounded target as their next
navigation target; player perception and the existing home-radius safety rule
still take precedence. Ambient people keep their render-only pool and now
expose the same individual row.

The architecture follows three useful external patterns: Diablo II's
socket/base/order validation, World of Warcraft's separated profession,
optional-reagent and quality layers, and data-oriented/batched NPC query
principles documented by Epic. These are design patterns, not imported game
content: [Arreat Summit runewords](https://classic.battle.net/Diablo2exp/items/runewords.shtml),
[Arreat Summit socketed items](https://classic.battle.net/Diablo2exp/items/socketeditems.shtml),
[WoW Dragonflight professions](https://worldofwarcraft.blizzard.com/en-us/news/23826545),
[WoW crafting quality](https://worldofwarcraft.blizzard.com/en-us/news/23827585),
[Mass Entity](https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-mass-entity-in-unreal-engine)
and [EQS](https://dev.epicgames.com/documentation/en-us/unreal-engine/environment-query-system-in-unreal-engine).

This is still a rich vertical slice, not a finished MMO content compiler. The
next safe promotion is authored meshes for the high-value gear/material rows,
then richer dialogue, crowd simulation and population-scale policies while
keeping the identity and asset tables stable.

## Patch notes · 2026-09-14 · presentation-only DOS failover

The render contract now exposes two presentation stages: `RICH_3D` and
`DOS_2D`. Both consume the same fixed-step entity, terrain, item and NPC
snapshot. `game_engine_fallback.py` builds a bounded terminal map with glyphs
for the player, NPCs, loot, caches, props and terrain, plus a compact status
ledger. It is a renderer contract, not a second simulation.

The QML surface can hide View3D and show the DOS canvas without resetting the
world, changing the camera contract, dropping inventory, rebuilding NPC
identity or altering the fixed-step clock. A graphics-failure report records a
bounded reason and switches presentation only; `RETRY 3D` restores the rich
stage. The fallback is intentionally local and deterministic, so future
native graphics watchdogs can call the same seam after a driver/context loss.

The current implementation proves in-process failover. A total QtQuick3D
plugin or desktop-process failure would require a small outer native watchdog
or a separate fallback process; that is a later platform layer. The fallback
now has a bounded command grammar, while combat/quest actions and a
process-level watchdog remain later promotions.

## Patch notes · 2026-09-14 · canonical DOS command input

`game_engine_dos.py` now validates a small terminal grammar with bounded
lengths, argument counts, directions, movement modes and target IDs. `MOVE`
and `TURN` are finite input impulses through the normal 60 Hz tick path;
`PICKUP`, `OPEN`, `LOOT`, `EQUIP`, `DROP`, `NPC`, `TRADE`, `BUY`, `SELL`, crafting, SAVE/LOAD and the
presentation switches dispatch to the existing runtime methods. Unknown,
oversized or shell-like text is rejected and never evaluated. The last command
and bounded history are shown by the DOS renderer, while gameplay mutations
remain owned by the same canonical world state.

## Patch notes · 2026-09-14 · authoritative event journal

`game_engine_events.py` now provides the versioned `gg.game-engine.events.v1`
journal. State-changing operations append bounded records with a monotonic
sequence, fixed-step tick/time, actor, subject, target, human-readable text
and a sanitized JSON payload. Retention is capped at 256 events and payload
depth, keys, list sizes and text are capped before a record can reach QML or
memory persistence.

The host keeps the older compact event stream for existing panels, but the
structured journal is the authoritative audit trail. Loot rolls, content and
station crafting, socket insertion, enchanting, item pickup/open/loot/equip/
drop, NPC interactions, NPC world-intent changes and SAVE/LOAD boundaries now
carry their real IDs and outcome data. The DOS renderer receives the latest
journal rows as terminal lines from the same snapshot; it does not generate
or mutate gameplay state. The journal is included in the memory-only save
payload and restored before the LOAD transition is recorded.

This is an audit trail, not full event sourcing: canonical inventory, gear,
identity and world structures remain the source of truth. The next promotion
is to extend the same seam with bounded combat/quest transitions and then add
an outer process watchdog for failures that cannot be handled inside the
QtQuick3D process.

## Patch notes · 2026-09-14 · committed NPC world actions

Selected NPC identities now execute a bounded world-use pass at 2 Hz after
their decision pass. `GATHER` and `HAUL` move an existing canonical item
instance into the person's pocket and remove the real child reference from a
container. `SEEK_FOOD` consumes a real food instance, `SEEK_WATER` uses a real
water/cooking target, `CRAFT` consumes the person's actual recipe inputs and
adds the actual recipe outputs, while `REST`, `OBSERVE_PLAYER`, `INSPECT_LOOT`
and `EXPLORE` commit their durable memory/need/relationship consequences.

Every attempt is distance-, capacity-, cooldown- and resource-bounded. A
missing or invalid target does not mutate state; a rejected transition is
recorded as `BLOCKED` with the concrete reason. The durable person row exposes
`world_action` (`last_action`, target, outcome, time and count), the PLAY NPC
tracker renders it, and `NPC_WORLD_ACTION` journal rows preserve actor and
target IDs. This is the first real NPC-to-world transaction layer; combat,
quest schedules and fully materialized carried gear remain later promotions.

## Patch notes · 2026-09-15 · materialized NPC inventory and atomic trade

Every valid NPC identity inventory/equipment reference now has a corresponding
canonical item instance in `POCKET` or `EQUIPPED`. Reconciliation removes only
unreferenced carried rows for that identity, so a restored save or an editor
change cannot leave a textual item table disconnected from the actual object
state. NPC crafting preflights and mutates those same instances.

`game_engine_trade.py` adds a versioned item-for-item contract. `trade_items`
requires a live physical NPC inside the interaction radius with bounded LOS,
an exact player `INVENTORY` instance and an exact NPC `POCKET` instance. Quest,
container, soulbound and explicitly bound definitions are rejected. The two
whole instances, the player's legacy counts and the NPC's durable inventory
reference are committed under one lock; a bounded rollback restores all of
them if any transition fails. The NPC receives a `TRADE` memory, the event
journal receives `NPC_TRADE` with the real IDs, and the latest trade survives
the memory-only SAVE/LOAD payload.

The same operation is reachable from rich QML and the DOS grammar:
`TRADE [npc-id] give-instance receive-instance`. This first pass deliberately
keeps item-for-item exchange separate from the vendor gold ledger; it remains
the general NPC ownership transaction that the economy layer can reuse.

## Patch notes · 2026-09-15 · physical vendor economy

`game_engine_economy.py` adds a bounded authored vendor table and a memory-only
gold ledger. The starter `vendor.mira` row points at the existing living NPC
`npc-wanderer-01`, uses explicit buy/sell prices and keeps vendor account gold
separate from the player's wallet. Stock is discovered from the NPC's real
`POCKET` instances; the economy contract never duplicates stock as presentation
data.

`BUY` transfers one complete physical instance from the vendor to the player's
`INVENTORY`, while `SELL` transfers one complete player inventory instance to
the vendor's `POCKET`. Both operations enforce proximity, LOS, ownership,
tradeability, capacity and sufficient gold. Item transition, legacy counts,
NPC identity references, wallet/vendor balances, NPC memory and the event
journal are committed together, with bounded rollback on failure. The economy
view exposes only real offer instance IDs, prices and vendor presence, so QML
and DOS can address the same state. SAVE/LOAD persists the wallet, vendor
accounts, latest transaction and bounded history; external accounts, vendors
and database persistence remain future platform layers.

## Patch notes · 2026-09-15 · deterministic vendor restock and market pressure

The first vendor now has an authored restock policy: `loot.goblin_pocket`, a
12-second fixed-step interval, a six-instance tradeable stock limit and one
bounded roll per due pass. The runtime resolves only live vendor NPCs, checks
the normal world/item budgets, rolls the existing loot-table contract with a
portable seed and creates a real NPC `POCKET` instance. The instance retains
`origin`, `base_item_id`, `roll_table_id`, `seed`, `roll` and deterministic
affixes, so stock provenance survives the same SAVE/LOAD path as every other
item.

Quotes are now derived from the authored base row plus two bounded signals:
the number of matching physical vendor instances and the vendor's per-item
market memory. Player `BUY` increments demand, `SELL` and successful
`RESTOCK` decrement it, and buy/sell multipliers are clamped before explicit
half-up rounding. The current quote, base quote, demand and stock count are
returned in the offer and transaction rows; no separate price or stock cache
can become authoritative. Failed restock attempts also persist a concrete
status and audit event, while a cooldown prevents repeated mutation every
frame.

QML exposes the actual stock limit and successful restock count next to the
wallet and real offer buttons. DOS continues to consume the same economy
snapshot, and the account's market memory, restock counters, last restock and
transaction history are bounded in the memory-only persistence payload.

## Patch notes · 2026-09-15 · vendor needs and preference decisions

The vendor catalog now contains a bounded need profile and per-definition
preferences: target stock, preference priority, a buy-price bias and a
sell-to-vendor premium. These are authored decision inputs, not an alternate
inventory. Quotes expose the same preference data, so a wanted item can become
slightly cheaper for the player to buy and more valuable for the player to
sell while the vendor is below its target.

At each due restock boundary the live vendor NPC's actual identity needs are
read. An urgent hunger, thirst or fatigue need produces a persisted `HOLD`
decision and advances the restock clock once; otherwise the vendor evaluates
its target-stock gaps and selects only among bounded valid rolls from the
configured loot table. A selected result is materialized as the same physical
NPC `POCKET` instance as before, with the selected seed and provenance. The
decision, need snapshot, selected definition, account counters and event audit
survive SAVE/LOAD and are exposed to both 3D and DOS views.

## Patch notes · 2026-09-15 · NPC progression, gear pursuit and ascension

NPC identities now carry a versioned progression state next to their needs,
goals, memory, inventory and equipment. The state uses the same bounded XP
curve as the player and stores level, XP, base stats, deterministic spec/talent
allocation, paragon, ascension, profession levels and derived combat/travel/
crafting values. Level, profession and ascension changes are simulation data,
not UI badges, and survive the existing memory-only SAVE/LOAD path.

NPC power is recalculated only from canonical `EQUIPPED` item instances. The
score includes authored rarity/quality/level, real gear stats, sockets,
runewords, enchants and rolled instance affixes. A SCAVENGER/SCOUT therefore
targets actual ground or container gear, opens/loots the real instance, compares
it against the same slot and equips it only when the score is higher. The old
item is returned to the NPC pocket as a real instance; failed transitions roll
back. Item-for-item trade and vendor `SELL` use the same comparison seam, so a
NPC can become stronger through an actual exchange as well.

Crafting reads the NPC's actual profession level, produces the corresponding
quality through the existing gear recipe contract, grants profession XP and
can equip a crafted upgrade. Successful world actions grant bounded XP once
per committed action journal count. At level 60, real paragon accumulation
can trigger a bounded ascension gate that resets the level while preserving
the persistent ascension stat bonus. `NPC_PROGRESSION` and
`NPC_POWER_CHANGED` journal rows expose the reason and before/after values.

Rich QML and the DOS fallback consume the same identity progression rows; the
fallback labels NPCs with level/power while remaining presentation-only. The
current implementation is a durable vertical slice for individual growth,
loot pursuit and gear power. Combat outcomes, quest rewards, faction/economy
strategies and daily schedules now extend the same canonical contracts;
authored population-scale progression policies remain future work.

## Patch notes · 2026-09-15 · authoritative living-world loop

The next simulation layer is now real rather than a presentation stub.
`game_engine_combat.py` owns bounded actor health, armor, damage, cooldown,
engagement, defeat counts and respawn timestamps. The host resolves a physical
close-range attack only against a live NPC inside the existing distance/LOS
contract. NPCs retaliate from the same fixed-step state; defeat freezes the
physical actor, creates a real `GROUND` item instance from the existing loot
table, grants player XP, changes that individual's faction disposition and
records memory plus an event-journal payload.

`game_engine_quests.py` adds a data-driven catalog with giver proximity,
objective events and explicit reward claiming. Defeat, pickup, equip and craft
events advance real quest state. Claiming is atomic across quest progress,
inventory instances, gold, XP and faction reputation, with rollback on a
capacity or definition failure. `game_engine_factions.py` keeps player
standing and per-person disposition durable, while
`game_engine_schedules.py` gives each identity an authored occupation day;
critical needs and actionable world targets can override a calendar slot.

The combat, quest, faction and simulation-clock state is included in the
memory-only SAVE/LOAD payload. A restored defeated NPC is represented as
`DEAD` in the same physical NPC row, and respawn remains governed by the
fixed-step clock. Rich QML and the DOS fallback receive the same actor,
objective and reputation views; DOS adds compact HP/quest/reputation lines but
does not simulate a second world. The new regression covers the complete
accept → attack → defeat → loot/XP/reputation → claim → SAVE/LOAD/fallback
path.

## Patch notes · 2026-09-16 · dialogue, social encounters and living population

`game_engine_dialogue.py` now supplies bounded authored choice graphs. The
player's `INTERACT` action opens a real tree for the nearby identity, while
`TALK npc-id choice-id` continues it from the saved node. Choices are applied
by the host to the canonical quest, faction, relationship and memory stores;
an invalid quest effect rolls those stores back together with the dialogue
state. Every successful choice also emits a `TALK` objective event, so later
quest chains can bind to conversation without UI-specific logic.

`game_engine_social.py` adds deterministic nearby-pair selection with a
cooldown, affinity, trust, meeting count and bounded history. The 2 Hz social
pass writes both participants' memories. A hostile authored pairing can enter
the existing combat resolver; a defeat creates the same physical ground loot,
NPC XP/progression and `DEAD` actor state as a player encounter. Thus NPC
combat is an event in the world ledger, not an animation-only interaction.
Negative remembered affinity is also a real input to future pair selection, so
a repeated meeting can remain tense after its first encounter rather than
resetting to a renderer-only greeting.

The living-world boundary now promotes one nearby ambient proxy every twelve
simulation seconds, up to a small explicit budget. Promotion removes the
proxy and creates a pooled physical NPC at its deterministic live position,
retaining the same identity, needs, inventory, gear, progression and memory.
The render row count therefore stays bounded while the authoritative actor
population becomes more detailed over time. The promotion set, dialogue,
social relations and simulation clock are all persisted in the same
memory-only payload and restored before the next snapshot.

Rich 3D and DOS consume the resulting `dialogue`, `social` and `living_world`
views. The terminal can start and choose conversations with the same command
grammar, while both surfaces continue to receive one authoritative snapshot.
This is the next durable seam for authored quest chains, faction-driven
encounters and eventually larger population batches; no renderer owns a
second NPC state.

## Patch notes · 2026-09-16 · authored frontier content packs and world events

`game_engine_content_packs.py` now provides a bounded, atomically activatable
content-pack seam. The first `pack.tidefall-frontier` pack adds twenty real
item definitions with explicit GROUND/CONTAINER/INVENTORY/EQUIPPED/POCKET
visual states, three loot tables, four gear recipes, materials, stations,
socketables, runes, gems, runewords, enchants, authored asset bindings, named
NPC identities, physical and ambient population rows, dialogue trees, quest
chains and scheduled faction events. The pack is data merged into the same
catalogs; it is not a second rules engine or a UI-only showcase.

Activation rebinds item, gear, NPC, dialogue, quest, vendor, asset and event
catalogs under one rollback boundary. Its initial world rows are materialized
as canonical `GROUND` item instances, and every authored asset is inspected
through the existing local glTF validation seam with a bounded primitive
fallback. The selected pack IDs, generated instances and world-event state
are included in the existing SAVE/LOAD payload, so a restored DOS session and
the rich renderer observe the same content selection and item ownership.

`game_engine_world_events.py` advances four deterministic Tidefall events on
the fixed-step clock. A start produces a real reward or loot-table roll,
updates player faction standing and writes participant memories; completion
is recorded in the bounded world ledger. `PACK` and `EVENTS` are terminal
commands, while the QML surface exposes the same activation and event summary.
The result is a larger authored world layer on top of the durable simulation
contracts, with rendering, camera, animation and DOS failover budgets left
unchanged.

## Patch notes · 2026-09-17 · render continuity and movement transport

The movement hitch had two independent causes. The QML entity signature was
including the authored asset's fixed-step animation phase, so every moving
character replaced its static `entityRow` and could re-evaluate its
`RuntimeLoader`, materials and equipment tree. Static loader identity now
contains only the stable asset/source/budget fields; pose, transform and item
bobbing travel through `entityDynamic`. Stable `renderKey` rows therefore keep
their delegate identity across movement and cell changes.

The loader handoff also checks the actual imported child scene. A successful
`RuntimeLoader` status alone no longer hides the fallback; the one primitive
rectangle remains until a visible imported model/geometry child exists. Once
the child exists, the authored rectangle is the only active character model.
The authoritative asset binding still decides eligibility and QtQuick3D owns
decoding.

Finally, the keyboard movement path now applies input to the same locked
runtime state but returns `gg.game-engine.render-snapshot.v1` directly. Full
inspector snapshots remain available for commands and UI cadence, while a key
transition no longer parses the complete inventory/NPC document. In the
pack-world offscreen regression, render updates fell from roughly 48 ms to
roughly 23 ms and 360 fixed-step movement frames retained all 18 character
visual paths with zero body gaps.

The desktop follow-up exposed the remaining visual edge case: the bundled
hero intentionally contains only `Idle`, while NPCs enter `WALK` as soon as
the simulation starts. A compact render refresh now recomputes the asset
binding for the current fixed-step motion state, so `ROOT_POSE_ONLY` reaches
QML instead of leaving a stale `READY` value from the initial snapshot. The
authored rectangle remains the single active character model in root-only
motion; the primitive rectangle is created only while the authored loader has
no usable visual child. QML still matches a ready clip name to the current
motion state, so a reconnect cannot turn an old `Idle` binding into a false
takeover. Ambient actors use the same bounded authored slots, keeping the
whole visible population on one rectangle contract instead of mixing it with
the retired detailed preview body.

## Patch notes · 2026-09-17 · authored low-poly crowd pilot

The visual fallback is now an actual shared low-poly humanoid geometry rather
than a semantic cube/rectangle label. It contains one head, torso, limbs and
feet inside one cached `QQuick3DGeometry` object (280 vertex records and 356 indexed
triangles), so a missing or not-yet-loaded authored asset cannot leave a head,
body or alternate pose object behind. The QML fallback uses the same object
for every character delegate; the simulation, camera and fixed-step budgets do
not change. The older Qt helper path is a 12-segment/6-ring shared sphere only
for non-character rounded props, never the dense built-in sphere.

The first real crowd asset is Kenney's official Blocky Characters 2.0 pilot,
copied locally with its CC0 license and texture. The validator reports it as
`AUTHORED_NODE_ANIMATED` / `GLTF_NODE_TIMELINE`: it has 27 named clips and
separate node-transform animation, but no skin. The host therefore selects it
only for NPC/ACTOR roles and a small shared instance budget; the timeline
adapter disables every imported clip and enables exactly the clip named by
the fixed-step `IDLE/WALK/SPRINT/AIR` binding. The player keeps the existing
skinned fixture until a proper retargeted hero/gear path is introduced.

Google image search is treated as a style/reference tool, not an asset
provenance source. Future hero and modular equipment work is reserved for
official CC0, rigged/retargetable packs such as Quaternius Universal Base
Characters and its animation/outfit packs; those are not silently bundled in
this patch. RenderWare/OpenGL projects were likewise not copied into the
engine: their useful ideas are VFS/manifest boundaries, cell streaming, LOD,
instancing, object pools and offline asset compilation, while the current
renderer remains original fixed-step Python plus Qt Quick 3D/RHI.

## Patch notes · 2026-09-18 · original clay low-poly crowd style

The live NPC/ambient visual no longer uses the blocky imported pilot. The
catalog now names the replacement honestly as `PROCEDURAL_GEOMETRY` with
`QQUICK3D_GEOMETRY` format and `FIXED_STEP_POSE_BUCKETS` animation. It is a
real runtime-generated 3D asset: one indexed mesh, 550 vertex records, 744
triangles and a 40-byte position/normal/RGBA-color stride. The fixed-step
state still has 32 deterministic phase buckets, but the live crowd reuses one
stable neutral geometry object and expresses those buckets through node
transforms instead of swapping meshes. The seven visible NPC/ambient crowd
slots therefore reuse geometry instead of loading seven textured scenes; the
player keeps the separate authored/skinned seam.

The new silhouette uses a rounded torso and pelvis, faceted head, hair cap,
eyes, nose, ears, hands, shoulders, trousers and rounded boots. Its material
is one matte dielectric `PrincipledMaterial` with vertex colors enabled; no
texture lookup, dense sphere or second character model is involved. Skin,
cloth, hair, boots and accent colors are therefore part of the mesh's actual
render contract, while QML still applies the same root bob/lean/sway/squash
and the backend still owns the fixed-step state.

## Patch notes · 2026-09-18 · authored clay hero promotion

The player slot now selects the canonical Blender-generated
`authored/gg-clay-hero-a.glb` through the existing local glTF admission seam.
It is a real skinned asset with 18 joints, 32 skinned primitives, six named
equipment sockets and the complete `Idle/Walk/Sprint/Air` clip contract. The
simulation still publishes the same fixed-step motion state, phase, root
offset and bounded authored-instance rank; only the visual implementation of
the player slot changes.

The Blender generator also emits a separate-glTF compatibility alias at the
historical hero URI for an already-running desktop process. `RELOAD` can then
rebind the QML RuntimeLoader without terminating the application. A narrow
source migration in `GameEngineSurface.qml` maps that old URI to the canonical
GLB; new processes use the canonical backend binding directly. No kill/restart
is part of the asset takeover path, and no second character body is created.

## Patch notes · 2026-09-26 · Blender character assets in GAME ENGINE

The player now selects the original `GG_Codex_Original` model from the visible
Blender scene. WANDERER, GUARDIAN and CRITTER use `CharacterFlow`, `Riftclaw`
and `Mossjaw`. The regular crowd cycles deterministically through seven more
GG Codex models, replacing the separate procedural crowd silhouette wherever
an authored instance is admitted.

`tools/blender/export_gg_codex_characters.py` duplicates each source mesh and
90-bone rig into a temporary Blender collection, maps the source rig's spine,
neck and shin names to the shared Blender `Idle`, `Walk`, `Sprint` and `Air`
clips, adds equipment socket nodes, and writes self-contained GLBs under
`qml/assets/authored/characters/`. The editable Sandover scene and its source
character rigs remain untouched. The existing eight-character RuntimeLoader
budget and single-model fallback still govern the live viewport.

The Kenney CC0 GLB remains locally validated as a reference/import regression
asset, but it is no longer selected for the live crowd. Google image results
and commercial game screenshots remain style references only; they are not
copied into the project and do not provide asset provenance. The style
contract is intentionally broad: readable exaggerated silhouettes, soft
faceting, muted matte colors and a small triangle budget inspired by the
user's Sly/Jak/Ratchet/WoW/Diablo direction without reproducing a protected
character or texture.

## Patch notes · 2026-09-18 · native clay asset kit

The next visual layer is now live for items and ordinary world props. The
asset table and render binding use `GG_CLAY_ASSET_KIT` with
`PROCEDURAL_GEOMETRY`, `QQUICK3D_GEOMETRY`, a 40-byte position/normal/RGBA
vertex stride and a bounded cache of 96 families. The runtime generates real
indexed meshes for weapons, armor, shields, chests, tools, trinkets, quest
objects, plants, crystals, food, consumables, lanterns and totems. World
props, ramps, houses and lights use the same native geometry seam. The mesh
builders are original runtime geometry; references remain style inspiration
only and no third-party model or texture is copied.

All five item contexts (`GROUND`, `CONTAINER`, `INVENTORY`, `EQUIPPED`,
`POCKET`) retain the same asset identity and state data. Ground instances keep
their deterministic bob/spin, while equipped instances attach to the player
without a second body or a loader per frame. The QML bridge applies a cached
geometry object at the host-ready event boundary because QtQuick3D can resolve
`Model.source` before the desktop host is attached. This closes the actual
initialization race that left a primitive source or an empty model behind;
normal current-host rendering contains no item/prop primitive fallback.

The runtime snapshot now reports `QTQUICK3D_NATIVE_GEOMETRY`, separate
procedural/authored item counts and a world-asset budget. Offscreen tests cover
native item, equipped, prop and material bindings, while the existing DOS
presentation continues to consume the same canonical item/NPC/world state.
No movement, camera, fixed-step or DOS contract was changed.

The world side now uses the same explicit seam rather than asking QML to
guess a primitive from an entity id. Each non-character world row carries a
native asset binding for a stable family: rock, mangrove, shrine, barrel,
ramp, Tidefall house or lantern. The current starter scene has 32 such rows,
all within the 96-family cache budget. The item binding reports runtime
resolution and indexed topology explicitly; it no longer publishes zero
geometry counts for meshes that are created lazily by the cache. That keeps
the snapshot honest while preserving lazy loading and the DOS presentation
fallback.

## Patch notes · 2026-09-17 · world-scale visibility calibration

The first-island view no longer treats a small 5x5 interest set as the whole
visible world. The authoritative world contract now keeps a bounded 7x7
gameplay set and publishes a separate 21x21 render set, both with explicit
coverage diameters and camera clip values. QML sizes its floor/water coverage
from the render contract and renders `ORBIT` cells as real low-cost HLOD
tiles. The character rectangle remains at authored metre scale;
the camera starts farther away and can still zoom from 6 m to 48 m, so scale
and visibility are corrected at their actual contracts rather than by shrinking
characters or adding a second visual path.

## Patch notes · 2026-09-18 · native asset metre-scale binding

The native clay asset kit now has an explicit scale boundary. Runtime-generated
world props and item meshes are built in gameplay metres, while QtQuick3D's
built-in `#Cube`/`#Sphere` compatibility meshes remain in their 100-unit
primitive space and alone use the `sceneScale` conversion. QML binds the scale
factor directly to the actual geometry object (`worldPropGeometry` or
`itemGeometry`) instead of a secondary boolean that may evaluate before an
asynchronous host geometry callback arrives.

This matters because a valid custom mesh can otherwise be present, indexed and
material-bound while still being rendered at approximately one percent of its
intended size. The QML regression now asserts native prop, ground-item and
equipped-item scales in addition to checking source-free geometry and vertex
colors. The single-model rule remains intact: no hidden duplicate body or
per-frame loader was added to repair the binding.

## Patch notes · 2026-09-18 · stable character geometry during motion

The live character fallback now keeps one native clay body mesh for the full
life of each QML entity delegate. The fixed-step animation snapshot still
publishes `IDLE`, `WALK`, `SPRINT` and `AIR`, phase, bob, lean, sway and squash;
those values are applied as deterministic node transforms. The render seam no
longer swaps a `QQuick3DGeometry` object whenever a pose bucket changes.

That swap was the actual PLAY regression: the backend and QML visibility
state remained valid, but QtQuick3D could detach the changing vertex buffer
during a render pass, leaving only a head/other prop or an empty body. The
offscreen asset regression now verifies that all visible procedural characters
share the same geometry object after the moving snapshot. Authored RuntimeLoader
assets remain a separate, bounded import path and are not duplicated to repair
the procedural crowd.

## Patch notes · 2026-09-25 · authored cove village and island surface

### What the user wanted

Make the island's actual landforms and assets read more like a cohesive
PlayStation-era coastal adventure village, using Sandover Village as a broad
reference. Camera distance and editor visibility are separate controls; this
pass changes neither camera behavior nor the Game Engine inspector buttons.
No game screenshot or image asset is part of the patch.

### Findings

- The playable island comes from one analytic height field shared by rendered
  terrain, player movement, navigation and water depth. Replacing it with a
  render-only sculpt would make those systems disagree.
- The starter village previously spent its 32-prop budget on seven repeated
  huts, eleven palms, a few landmarks and six straight path pieces. The
  existing family cache and authored static GLB seam could support more
  distinct silhouettes without growing that budget.
- One material per terrain cell made each 16 m patch read as a color tile.
  Near terrain already had continuous shared heights, so color belongs on the
  sampled vertices; distant HLOD cubes still need their own small biome
  palette because built-in cubes have no authored vertex colors.

### Decisions and implementation

- The shared height field now has an open low village green, separate raised
  windmill and northern headlands, an uneven shore and a cut-in southern cove.
  It remains deterministic and analytic, so physics and navigation follow the
  visible land.
- Terrain patches use a 48-byte position/normal/UV/RGBA vertex record and one
  shared vertex-color material. Sand, grass variation and exposed rock blend
  across cell edges. Far HLOD tiles keep reusable per-biome materials.
- The same 32 starter slots now hold seven enterable huts with four roof
  variants, four palms, three mangroves, two rock clusters, the existing
  shrine and barrel families, a windmill, market stall, fish rack, skiff,
  connected steps/paths/boardwalk and a pier.
  Existing mangrove and lantern GLBs use the authored asset path; native
  geometry remains the bounded fallback. House deck, doorway, collision and
  NPC spawn contracts stay unchanged.
- Pier and boardwalk supports now extend below their decks at the shallow
  cove. The dock sits at the cove's beach/water transition rather than far out
  over deep seabed.

### Research behind the choices

The official [Naughty Dog retrospective on Jak and Daxter](https://blog.playstation.com/archive/2017/08/24/extended-play-how-naughty-dog-went-from-crash-to-jak-daxter/)
describes a continuous explorable world and the use of LOD to protect that
experience. PlayStation's [20-year reflection](https://blog.playstation.com/2021/12/03/jak-and-daxter-turns-20-reflections-from-playstation-studios-and-friends/)
emphasizes reachable places and buildings whose interiors agree with their
exteriors. The implementation applies those principles to original GG shapes;
it does not recreate Sandover's layout or copy its models.

Epic's documentation on [landscape materials](https://dev.epicgames.com/documentation/unreal-engine/landscape-materials?application_version=4.27)
and [HLOD](https://dev.epicgames.com/documentation/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine)
supports the separation used here: blend terrain layers on detailed geometry,
then retain a cheaper far-field representation. Qt Quick 3D documents the
[custom geometry color attribute](https://doc.qt.io/qt-6/qquick3dgeometry.html)
and [vertex-color material switch](https://doc.qt.io/qt-6/qml-qtquick3d-principledmaterial.html)
that carry that blend without adding texture files.

No tests were run for this patch.

## Patch notes · 2026-09-27 · Planet horizon, sky and distant island

### Research findings

- Qt Quick 3D can draw a `SceneEnvironment.SkyBox` from a generated cubemap.
  `ProceduralSkyTextureData` exposes separate top/horizon/ground colors and a
  512×512 low setting; Qt warns that generating the texture can take time on
  embedded hardware. This renderer creates one fixed low-resolution sky at
  load, rather than regenerating or animating it per frame. See the official
  [SceneEnvironment](https://doc.qt.io/qt-6/qml-qtquick3d-sceneenvironment.html)
  and
  [ProceduralSkyTextureData](https://doc.qt.io/qt-6/qml-qtquick3d-helpers-proceduralskytexturedata.html)
  references.
- Qt's depth fog is evaluated in the fragment shader of supported materials,
  not as a separate full-screen pass. It can fade distant meshes to the same
  color as the sky/water seam. See the official
  [Fog type](https://doc.qt.io/qt-6/qml-qtquick3d-fog.html).
- Epic's Sky Atmosphere uses lookup tables to approximate planetary
  scattering and aerial perspective; its docs call out those low-resolution
  lookups as a performance optimization. HLOD groups static meshes into proxy
  geometry/materials to cut far-field work. Those are the appropriate
  production patterns; importing an entire second renderer is unnecessary
  for this one-island test map. See Epic's
  [Sky Atmosphere](https://dev.epicgames.com/documentation/unreal-engine/sky-atmosphere-component-in-unreal-engine)
  and
  [HLOD overview](https://dev.epicgames.com/documentation/unreal-engine/hierarchical-level-of-detail-overview-in-unreal-engine).

### Changes in this slice

- The old far-water cube had a finite square edge, the scene cleared to a
  single flat blue color, and the normal camera clipped at 240 m. Together
  these produced the visible rectangular seam and abrupt island disappearance.
- Replaced the far cube with one shared curved-ocean cap aligned to the
  existing 1,000 km planet-radius contract. The mesh has 24,577 vertices and
  49,024 triangles, is generated once, and uses a radial color transition
  whose outer tint matches the procedural sky's ground-horizon color. It
  costs one static geometry draw instead of a moving water wall.
- The camera's far clip now follows the geometric horizon estimate and the
  island's distance, with depth fog blending the island and water before the
  clip boundary. The existing Blender island terrain/environment GLBs remain
  the far landmark; at about 33,700 triangles combined they are a bounded
  cost for this single test island, so no extra billboard asset was added.
- Camera, dynamic actor and local wave positions now use the same curved
  tangent-frame height mapping. The near analytic wave mesh was already in
  metres but had been scaled by 0.01, shrinking its 144 m span to 1.44 m. It
  now keeps metre scale and conforms to the local ocean curvature.
- The simulation, navigation and collision heightfield remain unchanged.

### Limits and next tier

This makes the visible ocean curved and allows the camera to rise far enough
to see the island against a planetary water surface. The gameplay simulation
still uses a local tangent plane: it does not yet wrap movement around to the
planet's far side or rotate gravity/navigation with latitude. The island also
still uses its ordinary Blender GLBs at distance; a Blender-authored lower
triangle HLOD/impostor is the next step if more islands or many far landmarks
are added. Qt's GPU timing counter is not connected, so the renderer budget
here is geometric/accounting evidence, not a measured frame-time claim. The
procedural sky texture's startup generation and the new live appearance have
not been timed or visually verified in a relaunched client. No tests were run.

## Patch notes · 2026-09-26 · OpenGL/RenderWare comparison and console render path

### Facts

- [TheCherno/OpenGL](https://github.com/TheCherno/OpenGL) describes itself as
  an OpenGL-Core work in progress and learning/sandbox project. It is not a
  finished game engine and does not provide this game's player controller,
  platformer movement or spell simulation.
- [aap/librw](https://github.com/aap/librw) is an MIT-licensed, cross-platform
  reimplementation of much of RenderWare Graphics. Its scene/frame hierarchy,
  geometry/material organization and separated renderer/device interfaces are
  useful references. Its README calls PS2 rendering a test path; its own
  architecture notes list renderer and animation gaps.
- [sigmaco/rwsrc-v3.7.0.2](https://github.com/sigmaco/rwsrc-v3.7.0.2) labels
  itself RenderWare 3.7 source but states that EA/Criterion copyrights are
  reserved and gives no open-source license. It is not treated as reusable
  source material.
- GAME ENGINE is currently a deterministic 60 Hz Python simulation with a
  Qt Quick 3D scene using Qt's RHI selection. Neither linked graphics project
  is a drop-in source for the movement, grapple, water physics or abilities.

### Decisions and implementation

- Keep the existing simulation and Qt RHI boundary. Adopt applicable
  RenderWare-era renderer discipline: bounded geometry, material reuse,
  explicit quality budgets and effects grouped into fewer render objects.
- Add `PS2_CLASSIC` as the default render policy. It renders at a controlled
  internal scale, disables temporal AA, ambient occlusion, filmic tonemapping,
  point lighting and dynamic shadow maps, and keeps the existing fixed-step
  gameplay contract untouched.
- Replace one cube Model/material per particle with one indexed,
  vertex-colored geometry batch of crossed sprites. The batch is capped at
  256 visible particles; it makes one scene geometry/material binding rather
  than creating a QML Model for each particle.
- Use a 33×33 visible water grid under `PS2_CLASSIC` and retain the shared
  analytic wave function used by swimming and vehicles. Other profiles retain
  the 49×49 mesh. This lowers render sampling without changing the wave
  simulation or collision query.
- Stop reporting a guessed GPU draw-call count. The inspector now says the
  GPU counter is unavailable until a native renderer query is connected.
- No source, proprietary assets, character skeletons or animation data were
  copied from those repositories. Open-source code reuse can be assessed
  separately if the engine later moves to a native RenderWare-compatible
  renderer; the restricted RenderWare source is excluded.

### Assumptions and remaining work

The console profile is a renderer policy, not a full PS2 emulator and not a
substitute for authored animation, level design or gameplay physics. The
current water renderer still updates on its existing timer; GPU frame pacing
and actual draw counts still need a native Qt RHI profiling bridge. No tests
or live application restart were performed for this change.

## Patch notes · 2026-09-27 · Sandover ambient life groups

### Facts

- The starter island now has twenty deterministic ambient resident proxies;
  the Tidefall pack contributes four additional rows, with a shared cap of
  twenty-four. These are render and schedule proxies, not twenty-four extra
  full physics/AI actors. The existing promotion seam can convert up to four
  nearby residents into pooled NPCs, one every twelve simulation seconds.
- `tools/blender/build_gg_sandover_living_world.py` authors the fauna and
  cloud meshes in the existing `GG Sandover Village` Blender scene and exports
  three grouped GLBs. The bird group has 18 birds, 54 joints and 3,240
  triangles; the fish group has 24 fish, 48 joints and 3,456 triangles; one
  cloud bank has 480 triangles. The combined geometry is 7,176 triangles
  across 15 material primitives and about 0.9 MB of GLB data.
- The flock and school each use a single skinned GLB and one `RuntimeLoader`,
  with per-member Blender bones and the `SandoverBirdFly` / `SandoverFishSwim`
  loop. The cloud bank uses one static GLB and a cheap game-side drift path.
  This avoids one QML object or physics body per bird/fish, but a grouped GLB
  still has multiple material primitives and is not claimed to be one GPU draw.
- The extra residents reuse the existing shared crowd geometry and bounded
  authored-character path. Population schedules and deterministic movement
  stay in Python; the existing renderer owns their visuals. The existing
  authored-character RuntimeLoader cap is still eight, so excess residents
  currently use the shared procedural crowd fallback. That fallback is a
  known gap against the requirement that character animation come from Blender.

### Decisions and limits

- Keep the ambient, physical NPC and wildlife-group budgets separate. A future
  AI-controlled resident can be promoted into the existing actor pool without
  making every visible bird, fish or villager run full AI each frame.
- Do not simply raise the eight-character loader cap to twenty-four. The next
  crowd step needs a Blender-authored, low-joint/LOD representation or a
  measured instanced animation path so the increased population does not bring
  back the movement-time lag.
- The authored wildlife paths are an initial island-scale pass. The bird flock
  and fish school follow bounded group loops; resident routes remain small
  deterministic schedules. These are not yet collision-aware flocking,
  migration, navmesh paths, or a complete boat-and-wildlife ecosystem.
- The QML pane lifecycle has one `onPaneLiveChanged` owner; it resumes the
  existing runtime and retries the two Blender animation bindings there.
  Menus, camera and island terrain are unchanged by this work.

The Blender exports and source scene were updated locally through the visible
EXT Blender sidecar. The currently open GAME ENGINE process may need its normal
reload/reopen to pick up the Python population change. No tests were run, no
GitHub push or release was made, and the GPU frame-time impact has not yet been
measured in a relaunched client.

## Patch notes · 2026-09-27 · Blender crowd animation LOD

### Original intent and source review

The current island is a compact playable world for proving movement, water,
vehicles, interaction, animation and many visible residents before expanding
the map. GAME ENGINE and EXT remain creation tools; the standalone game is the
player client. The editor menus and camera controls have their own role and
were not changed here.

The earlier game research was reviewed against the open primary sources again:
Naughty Dog's Jak postmortem describes separate LOD schemes for creatures and
backgrounds, Insomniac's Ratchet postmortem describes shared LOD/instancing and
early gameplay prototypes, and Rare's Sea of Thieves technical art talk
describes a much more expensive FFT/GPU water system. RenderWare's `librw` is
an MIT graphics reimplementation with a limited PS2 path; TheCherno/OpenGL is
an educational OpenGL project. Neither is a drop-in physics, animation or
world engine for this Qt Quick 3D application. The archived RenderWare source
has no open license and was not imported. The supplied YouTube pages were
throttled during this review, so no new claim here depends on their transcripts.
The detailed game-by-game notes remain in `docs/PS2_ACTION_ADVENTURE_RESEARCH.md`.

### Findings and implementation

- The live Blender scene contains the original GG character meshes, a 90-bone
  source rig and the project's own eleven locomotion actions. Before this
  change only eight full-rig `RuntimeLoader` characters could be active. The
  default render snapshot contains 27 characters: one player, six pooled NPCs
  and twenty ambient proxies. Nineteen of those figures previously used the
  shared procedural fallback.
- `tools/blender/export_gg_codex_crowd_lod.py` creates temporary copies of
  three GG character meshes in EXT. Small facial, finger and toe weights are
  transferred to retained ancestor joints, leaving a 23-joint rig while
  preserving the eleven authored action clips. The original .blend stays
  editable and unchanged. Original flat material colors are baked into a
  per-corner vertex-color layer so each GLB has one material primitive rather
  than 18–22. The three exports are 624 KB, 631 KB and 823 KB; all were
  admitted by the existing asset inspector as skinned GLTF with eleven clips.
- The asset catalog retains the first eight full-rig slots. Later crowd ranks
  select the lighter Blender exports, up to a total authored crowd budget of
  32. If a LOD export is absent or invalid, that rank stays on the existing
  fallback rather than loading an extra full rig. The GAME ENGINE asset panel
  now reports the total crowd budget and the separate full-rig cap.
- A local read of 200 idle compact render snapshots averaged about 2.0 ms
  with 68 render entities. This is only Python snapshot time in a separate
  process. It is not a GPU measurement or proof that the live game runs faster.

### Remaining work

The new figures have not been timed in the visible Qt renderer or played in a
fresh game window. `RuntimeLoader` still has per-instance node and material
cost, and 23-joint assets are not GPU instancing. If the crowd becomes a frame
bottleneck, the next step is a measured Blender-authored pose LOD or native
instanced crowd renderer with per-figure phase data. The sea, boats, gameplay
systems, editor panels and original source scene were not changed by this pass.

## Patch notes · 2026-09-27 · World scale, equal double jump, sea-wide life

### Research read again

Session 62's sources were read again before this change. Naughty Dog's Jak and
Daxter postmortem (Stephen White, 2002) was re-read in full for the parts that
decide scale and life: physics is integrated in seconds, not frames; creatures
and backgrounds use different LOD schemes; distant shapes stay visible as
simplified flats so a landmark can be seen and then walked to. The practical
rule taken from that, and from the already recorded Ratchet postmortem, is
that jump height is measured before the art is locked. Insomniac's note that
early one-bone prototypes were used to test height, speed and timing is why
the roof line below is a jump result, not a guess in Blender. Rare's Sea of
Thieves technical art talk stays the reason the water simulator was not
replaced: their FFT sea and raymarch-free clouds are a heavier system than
this playground should copy. What transfers is the cheap part: clouds and
creatures are repeated, art-directed groups, not a unique simulation per
animal. No proprietary meshes, skeletons or levels were imported.

### What changed

- The authored island, its terrain and its props expand together by
  `WORLD_FEEL_SCALE` (1.85) around the origin. Slopes stay the same because
  horizontal distance and height scale together. Sea level stays 0. The
  render radius, horizon clip and water shader are unchanged.
- Hut roofs in the island environment are raised to the palm-crown clearance
  (4.10 m in authored space, 7.59 m after the scale). A full-hold single jump
  is about half of a perfectly timed double jump: both hops add about the
  same height when the second press is at the apex. An 80% timing, taken
  while still rising at about 20% of jump speed, reaches that roof and crown.
  The roof is walkable once the body is up there; the walls do not shove a
  character who is standing on it.
- Birds, fish and clouds are the existing Blender groups, drawn as a fixed
  budget (3 flocks, 3 schools, 5 cloud banks). Each copy is anchored to a
  world cell with its own phase and size, and fish are pushed off the island
  onto the sea. Moving reveals different groups; returning to a cell shows
  the same ones. They are not physics actors.

### Limits

The 80% and perfect hop heights are fixed-step measurements with the jump
held, then released for one frame so the second press has an edge. They are
not a recording from the live Qt window. The GPU cost of the extra eleven
group loaders was not framed. The original `.blend` was not reopened; the
roof change is in the exported environment GLB and in the gameplay scale.

## Patch notes · 2026-09-27 · Lively analytic sea and a boardable skiff

### What the sea reference actually supports

The Sea of Thieves technical art talk, and the short explainers of that
water, describe vertex displacement from layered wave formulas, crest foam,
and shore wash, with one surface shared by the picture and the hull. Their
full FFT ocean is a large GPU cost. This pass keeps the existing one-mesh
analytic sea and makes that formula do the readable part: five directional
swells, a slow tide, a small Gerstner sideways shift, and posterized vertex
foam on crests, steep faces and the beach. Swimming and the skiff sample the
same height. The far curved cap and the render distance are unchanged.

Blender's geometry-node tools were not available on the live bridge in this
pass, so no node graph was built or exported. The sea stays in the engine
because that is what has to move every frame with the hull.

### Skiff

The hull scale is now an absolute size a person can stand in, about 7.4 m
long, instead of the old toy scale times the island expansion. E boards and
leaves it when you are beside it. B still does the same. The old disembark
point was the pre-scale dock coordinate; leaving the boat now steps toward
the island.

## Patch notes · 2026-09-27 · One painted sea, PS2 tiles on the island

The moving water had split into two materials. The near grid was a pale,
high-specular square. The horizon ring was a darker matte sea. Posterized
crest colors turned the swells into stripes. That square is gone.

The near water is a disk centered on the player. The horizon ring uses the
same waves, the same shade and the same scrolling tile, and its inner lip
sits just under the disk so the join is a circle. Render distance is still
the outer ring. Short chop that the disk cannot draw cleanly was lengthened;
the ripples live in a painted 128² sea tile instead. Swimming and the skiff
still sample that same surface. The tile is original, not a copy of another
game's water.

The island GLBs were flat material colors. PS2 worlds were painted textures
on low meshes, so each material now multiplies a repeating original tile:
planks, roof courses, plaster, bark, leaves, grass, sand, stone, cloth,
rope, feathers, scales. The authored color stays the tint. Eyes and glow
stay flat. Hut roof scales were not rebuilt. The procedural skiff is still
vertex-colored; it is not one of those GLBs. Reload the game engine to see
the Python, QML and GLB changes. No GPU frame time was measured.

The near sea mesh was parented to the player, so its tile slid with them
between the 80 ms updates. It now sits in world coordinates, same as the
horizon ring. Shallow water is blended: the beach mesh already continues
under the surface, and the opacity rises over about 5.5 m so the open sea
does not turn into a hole. The repeating grids were the old high-contrast
tiles plus nearest filtering. The replacements are soft painted blotches
with bilinear filtering. Fire, lasers and lightning were not added.

The shaded sea material did not draw in the game view, so the picture is
the textured mesh again. Its vertices use the same swell as the body and
refresh at 80 ms, the rate that did not hitch. The board's pitch and roll
follow the slope in the direction it faces. The sideways crest shift stays
at zero. The horizon radius is unchanged.

## Patch notes · 2026-09-27 · Circular schools and elemental FX

### Original intent

Continue the shared analytic sea and the Blender authored wildlife. Birds and
fish should read as circular groups, the sky should hold only a few soft,
translucent clouds, and the game should have a reusable visual language for
enchants, fire, smoke, gas, lightning, arcane, shadow and laser effects.

### Facts and findings

- The existing bird and fish GLBs were grouped, but their member positions and
  world paths were slightly elliptical. Five repeated cloud banks made the sky
  busier than requested. Their glTF material was opaque.
- The particle geometry already used world metres while its QML Model still
  applied the 0.01 primitive conversion. That shrank visible particles and
  their positions by a factor of 100.
- The near and far water meshes already share the analytic wave sample. The
  new swimmer foam reads the water height from that same player sample; fish
  groups now sample the same wave at their own world positions. Both water
  meshes still use one material, now with a restrained sun glint.

### Decisions and implementation

- The authored bird and fish groups were rebuilt as circular rings. The world
  roots follow circular cell anchored orbits. Fish stay just below the moving
  surface. The fixed cloud budget is two banks, with glTF BLEND materials at
  0.22–0.35 alpha.
- One bounded Qt Quick 3D geometry batch draws faded cards and narrow crossed
  beams. It has seven preview styles, water foam, school wakes, ability bursts
  and two persistent equipped enchant auras. The BAG enchant action can apply
  the style selected in PLAY. These are original GG effects and assets.
- Gameplay particles retain their existing pool and simulation. The new
  cards are render only and capped at 80 additional rows inside the existing
  256 card geometry capacity.

### Assumptions and unresolved questions

"AAA" is treated here as a coherent moving sea, shoreline readability and
responsive local FX within the current Qt/PS2 style budget. This pass does not
claim cinematic reflection quality or GPU performance. The rebuilt GLBs and
QML/Python changes need a fresh game process before they appear. Live visual
quality and GPU frame time have not yet been measured.

## Patch notes · 2026-09-27 · Free birds and one visible water surface

### Original intent

Birds should spread through the sky and move freely. Fish may remain in
schools. The boat and hoverboard must rise and tip with the visible waves;
the sea and the rider should not appear as separate layers. Keep the sparse,
soft clouds and the colorful PS2 era effects.

### Findings

- Moving an entire bird GLB around a cell made its 18 members travel as one
  rigid clump, despite their independent wing phases.
- The near sea disk used transparent blending and low density triangles. Its
  far ring refreshed later than the disk, making large pale facets and a
  moving boundary visible in the screenshots.
- The physics and mesh already used the same analytic wave sample. The visual
  split came from water compositing and mesh timing, rather than a second
  gameplay wave formula. The painted sea tile was almost a flat teal color.
- The skiff sampled the wave for height but applied pitch in world Z instead
  of its own heading. Its rider did not inherit the hull orientation.

### Decisions and implementation

- Each bird body now has an independent broad closed path in the same skinned
  GLB, with varied altitude and faster independent wingbeats. Its world cell
  anchor stays fixed. Fish schools retain their orbit motion, with their
  dorsal shapes skimming the water surface.
- Near and far sea meshes now update on the same simulation time. They meet at
  one radius with matching wave positions and shared color shading. The far
  sea also excludes land near the island. The first pass used an alpha mask
  and depth writes, which made the water too opaque. The follow-up restores
  alpha blending with one shared 0.28–0.72 clarity curve for both meshes.
- The near disk has denser shoreline geometry, and the tile has broken light
  ribbons over dark and pale pools. Crest color follows the same wave sample.
- The skiff uses heading-aware wave pitch and roll; the rider shares the hull
  tilt. The hoverboard continues to use the sampled water height and slope.

### Assumptions and unresolved questions

This is a PS2 style visual pass within the existing CPU mesh and authored asset
budget. The exported bird GLB contains independent translation channels. The
new result still needs a fresh desktop game process and live visual inspection.

The translucent follow-up also softens the water material's sharp specular
highlights. The birds, fish schools, boat wave contact and sparse clouds remain
as authored above.

## Patch notes · 2026-09-27 · Fish that move as a school

### Original intent

Keep the accepted birds and translucent water. Fish should form a living,
coherent shoal with visibly different individual sizes, rather than a round
ring of fish travelling as a single rigid object.

### Findings and decisions

- The earlier fish mesh placed all 24 bodies on four concentric rings. Only
  tails had animation; the world root itself orbited in a circle.
- The rebuilt fish GLB fills an irregular elongated school. Size varies from
  small juveniles to larger leaders. Every fish body has its own looping
  translation and turn, while tails beat at independent rates.
- The school root now follows a bounded, gently turning harmonic path. Its
  yaw follows travel direction, and its height still samples the shared sea.

### Remaining uncertainty

The GLB export contains independent fish animation channels. Its final scale,
water visibility and motion need inspection in a fresh desktop game process.

## Patch notes · 2026-09-27 · Fish across the sea column

### Original intent and finding

The varied fish looked more alive, but the screenshot showed one conspicuous
surface patch. The three repeated groups did not cover enough ocean, and all
members sat near the same wave height.

### Decision and implementation

- Each authored ecology tile now holds 12 fish: three small shoals plus three
  independent cruisers. Their local positions spread across the cell, and the
  shoals occupy shallow, middle and deeper water levels.
- Eight bounded world-cell loaders replace three larger surface groups. Each
  tile retains independent body and tail animation; the slow cell root still
  samples the shared water surface. This places fish throughout the nearby
  traversable sea as the player moves without creating a physics body for
  every fish.
- The total visible budget is 96 fish across eight GLBs, compared with 72
  fish across three GLBs before this change. The authored triangle budget per
  group falls from 3,456 to 1,728.

### Remaining uncertainty

Individual deep fish are offset from one water sample per tile. Their precise
visibility and relation to the seabed need a live view after the game process
loads the new asset.


## Patch notes · 2026-10-02 · Native flora, culling and tab targeting

The [implementation report](docs/world-development-2026-10-02/README.md)
records GgEngine-derived streaming windows and spatial residency, paced seeded
64 m flora cells, 22 shared native geometry/instance tables, eight biome kits,
and authoritative tab targeting connected to existing attacks. This stage
adds 11 original Blender-authored flora species with near/far geometry.
The standalone package includes the compiled meshes and GgEngine MIT notice.

Camera frustum culling is now enabled. In the actual static Westreach view,
draw calls drop from 553 (culling off) to 80 (on); 640 selected flora instances
add six draw calls. Qt View3D RenderStats and DebugView expose the actual
client counters. GPU timestamps are enabled by QQuickGraphicsConfiguration
in the isolated probe; they cover the window, and absent values remain absent.
This supersedes the earlier assumption that counters require a custom RHI
bridge. Host timing remains distinct from client render/GPU timing.

The full 2,158,648-triangle planet GLB and 5.3 km atlas remain. Camera culling
and streamed decorative flora do not establish terrain geometry streaming,
a traversable globe, colliding vegetation, distant forest HLOD or land fauna.
The report links scene measurements, movement-stream CPU samples and test
results, including three older tests blocked by stale content counts.

## Patch notes · 2026-10-05 · Curated botanical banks and bounded EXT review

`game_engine_botanical_designs.py` defines three primary 36-slot rosters:
trees, flowers and foliage. Slots represent selected species or deliberate
second designs, rather than six base shapes with six small distortions. The
Blender constructors use separate cups, bells, rosettes, perforated leaves,
segmented bamboo, fronds, climbing stems and species-specific tree silhouettes.
Related render-family aliases reuse these 108 designs and are not additional
unique botanical artwork. Painted GLBs and native geometry are built offline;
the native exporter now respects authored smooth/flat corner normals.

Tree compilation, terrain-edit buffers, canopy support and produce anchors
share the same climate-appropriate variant selection from saved tree IDs.
The 12,551 saved placements remain unchanged. Foliage choices likewise use
biome and stable identity, while the existing nearby activation distance and
instance limits remain. Detailed tree pages are local; distant instances keep
the shared simplified family geometry and therefore do not preserve every
individual species silhouette at the horizon.

The actual hosted EXT viewport was used to inspect all 36 slots in each of
the three banks alongside botanical photographs and PS2 gameplay boards.
Findings and remaining art scope are in
`docs/style-development-2026-10-05/biodiversity/review/visual-review.json`.
Full-library review preparation stalled Blender; it was stopped and recovered
from saved assets. Review preparation now defaults to one bank and skips
library reads once all requested collections are present. The saved EXT desk
opens the complete flower bank, with 36 models and 36 labels. Older creature,
weapon and prop banks still require their own type curation and visual review.

Botanical geometry/binding checks, ecology residency, saved tree pages, gear
crafting and enchant/sword checks pass. The isolated real client also passed
the rotation/buffer-reuse check with no QML warnings; measured views were
about 56–60 FPS on this desktop. These measurements cover that fixture, not
every biome or the entire world. Evidence is in
`docs/style-development-2026-10-05/botanical-species-r2/scene.json`.

## Patch notes · 2026-10-05 · Curated shields, axes and scythes

Two new 36-slot curated rosters replace the older six-by-six shield and axe
constructors. Shields include bucklers, kite/heater/tower forms, curved timber,
hide, woven, shell, bone, leaf and fantasy constructions. Axe designs include
bearded heads, double bits, polearms, picks and material-specific fantasy heads.
Slots 30–32 are three one-handed scythe designs and 33–35 three two-handed
designs, with different blade curves, fittings and physical shaft lengths.
These hand classifications describe the art; new two-handed combat animations,
off-hand restrictions and separate balance/recipes are not part of this pass.

The exported GLBs have painted image materials, closed bevelled profiles,
curved shafts, actual shield rear grips and raised decoration. Paint scale is
an opt-in object property, preserving existing world/character UV mapping.
The hosted EXT desk was used to inspect all 72 slots, including enlarged
oblique groups and all six scythes together. The initial scythe attachment gap,
collapsed circular fittings and obscured shield relief were corrected during
inspection. Review evidence is in
`docs/style-development-2026-10-05/biodiversity/review/equipment-visual-review.json`.

Runtime selection retains stable item identities and the 24-instance limit.
A small compiled sidecar supplies each axe's local cutting-edge path. The
actual client revealed that a host-supplied QML sequence was rejected by
`Array.isArray`; enchant frames now accept indexed sequences and map the
curved path through the actual equipped loader and planetary render transform.
The icon builder also supplies the weapon asset-ID filenames expected by the
inventory. The new geometry/binding test verifies all 72 shipped meshes,
painted UVs, finite unit normals, noncollapsed triangles, physical size
differences, six connected scythe roots and the unchanged instance limit.

Sword, gear and enchant-scroll regressions pass. The isolated real-client
fixture equips the actual scythe and shield, verifies successful authored
loaders and all 25 curved scythe points, and retains rotation buffer reuse.
It passed without QML warnings at approximately 55–60 FPS in its three views.
This is fixture evidence, not a claim about every location or combat workload;
see `docs/style-development-2026-10-05/shields-axes-r1/scene.json`.
