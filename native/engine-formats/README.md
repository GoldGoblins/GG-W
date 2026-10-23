# Upstream formats in GG

The eight original reader crates, original TGA decoder and the **entire**
`engine-formats-core` library are copied unchanged. Original protocol and SRP crates
are also preserved: the 470-file inventory (283 reader files and 187 protocol/SRP
files) is in `upstream-provenance.json`. GG's C ABIs and runtimes live in separate
crates. Original licenses and notices for 64 resolved Linux build/test dependencies
(131 license texts) are included. No game installation data is redistributed.

Build with `python3 -B tools/world/build_engine_formats.py`. This uses the
existing isolated Rust toolchain and locked dependencies. Compiler and build
caches are excluded from the player package. Both native libraries have checked
source/binary build receipts; nothing compiles during game startup.

`build_engine_client.py` builds the separate original-protocol adapter. Its C ABI
exposes all 256 original outbound commands and 166 typed protocol records. GUIDs
keep all 64 bits through decimal strings. Finite encrypted loopback fixtures
exercise login, queue, roster, character actions, world entry, logout/re-entry,
fragmented headers and failure closure. Compiled codecs do not prove that every
original event is connected to the GG gameplay host.

Normal standalone startup uses GG local character selection. Up to ten characters
use bounded 8 MiB atomic save files, 60-second autosave and logout/close saving.
First use preserves existing GG progress; an explicitly empty roster stays empty.
The creator previews the actual 150 own class/colour models. A real two-process
Qt test checks creation, play and restoration of appearance, XP, gold and position.
The creator's idle animation uses its authored cadence. A filesystem lease prevents
two local clients from overwriting the same profiles. The actual character name and
local disk status reach the game/Lua view, and a failed save cancels window closing.
Original Lua Logout/ForceLogout and Quit/ForceQuit use these same save and close
guards. Character switches prepare a new original UI VM before replacing the old
one and clear active loot/craft/gossip/vendor/bank contacts. SavedVariablesPerCharacter,
private macros and character bindings have separate local files; account data stays
shared. Flat legacy character data and corrupt files are preserved. Selection VMs
cannot save stale account state. UI writes are atomic and fsync both file and parent.
The real restart test also restores a private character macro.
The selected character's live unit, money, XP and inventory state is published
before addon files and their ADDON_LOADED/PLAYER_LOGIN/PLAYER_ENTERING_WORLD
handlers. Initial login, subsequent character switches and UI reload use the
same state publisher; addons do not initialize against the default/previous
player and wait for a later tick to discover whose data they are saving.

Original five-view camera APIs and hardware-gated movement bindings now reach
the actual local GG rig. Camera poses/views and helmet/cloak visibility persist
with each character; held keys and autorun clear on load or focus loss. Lua camera
changes also update a paused Qt view. Live writes of the saved-view CVars do not
change the slots, matching the original camera construction semantics. GG walk
uses the GG controller's speed scale. Guarded stand/sit/sleep/kneel commands
drive retained own GG rigs; movement/jump stands up, and seated actors cannot
boost or draw weapons. Authored posture clips take precedence over own static
canonical-rig poses. Original vehicle/ride rigs and the full avatar graph remain.
Local target/last-target/assist/by-name and follow use actual NPC identities;
manual movement cancels follow. Own K/J/L/P keys and original Lua/macros share
the posture/sheath/walk/autorun control routes. Retained actor animations pause
with the local simulation, and the game client stops imported animation jobs
before QML teardown.

Tutorial set/clear/reset preserves original call order and persists its bank per
character. Action-bar flags, PvP, friends/ignore and faction UI preferences are
validated local state. Who lists actual live local inhabitants, retains original
Rust sort chains and returns real matching totals; friend presence is independent
of the Who filter. SAY/YELL/WHISPER/EMOTE, rolls and played time produce actual
local journal/UI events. Group/guild/channel delivery has no multiplayer host.
Original seven chat windows, 104 chat colours and all placed-frame anchors use a
bounded per-character atomic cache, restored before VARIABLES_LOADED. Drag writes
coalesce, and failed writes remain pending. Original cursor signals select actual
Qt pointer shapes; original cursor artwork is a separate corpus.

Every original UI queue is inventoried. Required missing hosts report explicit
failure and drain their queues so stale operations cannot replay later. This is
not an implementation of mail, auction, trade, party/guild, pets, taxi and the
other rejected services. Contextual cursor sale consumption is never blindly
drained. The audit distinguishes source drains, rejection and behavior evidence.

The native character adapter selects original drawn/stowed melee, ranged, shield,
ammo and quiver joints, including per-arm visual state, weapon/ammo path columns,
and distinct logical attachments sharing a joint. Hidden helm/cloak choices affect
the atlas/geosets and attachments. Own GG GLBs use their authored hand/back sockets;
the compact render stream retains those states. The original timed sheath graph,
private bag-to-quiver election and spell/enchantment visual state remain partial.

Placed M2 animation keys now cross the original interval windows and transform
through the actual bone/placement pose into Qt coordinates. $SND/$DSO fire at
that point; $DSL/$DSE register/release the original shared ambient-kit pool.
The pool keeps 32 kits, 256 records per kit and four audible channels in claim
order, with stable nearest-record ties, three-second release fades and voice
generation checks. Owner eviction discards queued/late IO results and a live
channel moves without restarting. The scanner reports discarded catch-up after
a one-second gap, allows at most four loop boundaries and caps a frame at 64
keys. Original creature/GO-specific voice, combat, footsteps and spell channels,
masked overlays, transport/pane rebasing and original corpus coverage remain
partial; unhandled tags are reported rather than assigned invented sounds.

The GG addon panel lists the original native registry and uses its enable verbs.
Choices are atomic local files per character; clean profiles do not write default
choices, and entries for temporarily uninstalled addons are retained. The startup
walk uses the original `can_load` startup gate; `LoadAddOn` retains the separate
demand gate. Disabled required dependencies cannot run, and an optional disabled
dependency does not block its sibling. A failed save retains both enable rows and
pending keybinding writes for retry. UI reload prepares a replacement VM before
closing the current one and rejects buttons from an earlier UI generation. The
real Qt restart test exercises the panel and restores an addon disabled through
its buttons. GG uses bounded JSON rather than the original `AddOns.txt`; original
realm-wide inheritance, glue AddOns screen and signature verdicts remain distinct
unverified behaviors.

Consumed crafting instances are reclaimed rather than accumulating tombstones
against the 96-instance world budget. Ingredient deductions precede product
allocation, including products already earlier in inventory dictionary order.
Crafting predicts the resulting live instance and 64-cell bag counts before
spending: a rejected craft leaves the materials intact. Repeated craft/consume
cycles, full-live-registry rejection and same-transaction freed slots are tested.

Original gossip/quest verbs use the actual nearby GG giver and its live dialog.
Accept, progress, reward, decline, close and exact log abandonment change the real
local state; repeated, stale and out-of-range rewards cannot duplicate payment.
Original talent bindings show GG ranks and spend actual local talent points.
GG's current point budget is projected into the original rank view; it does not
invent original class DBC caps. Local respec refunds the actual spent GG ranks
once, using an explicit free GG policy; original trainer fees/contact remain.

Original Craft/TradeSkill APIs show actual GG recipe products, ingredients and bag
counts. Workstation contact, materials, backpack cells and world-instance capacity
are checked before spending. Create All advances one transaction per 100 ms of local
play; stop, close, contact loss and failure cancel its bounded queue. Original physical
LootButton clicks and the own Qt contents panel transfer one exact chest instance.
Visible slots stay fixed and clear in place; duplicate/stale/range/full-bag actions
cannot duplicate or lose items. Ordinary Lua LootButton:Click stays inert, matching
the original. Corpse/fishing/bind/master-loot and the original DBC profession corpus
still require separate mappings. Own Qt recipe and contents panels are exercised in
the real client, with screenshots and zero QML errors.

The original-world Qt pass implements quarter-resolution Box4/Gauss4, gamma
combine, death tint and the original byte-LUT underwater wave. Six real GPU states
are compared with an independent pixel oracle, and actual client camera submersion
and Lua `ffx` switches are verified. Tiny aspect-ratio buffers, glue widgets,
mixed Qt PBR colour semantics and optional original dithering remain partial.

Original merchant Lua verbs operate on exact GG item instances, including a
chosen empty backpack cell, twelve buybacks and individual/all repairs. Buyback
uses the recorded sale price; repairs use the explicit GG condition/level policy.
Stock consists of physical GG bundles, not an invented unlimited server inventory.

`NativeFormats` owns a supervised decoder and an explicit local root.
`decode(path, **options)` returns metadata and optional raw bytes:

- BLP/TGA: RGBA, original alpha/mip/orientation semantics.
- M2 `runtime=True`: original skeleton, sequences/global tracks, alpha/RGB/UV,
  batch state, authored cameras and initial packed position/normal/UV geometry.
- `pose(path, ...)`: subsequent poses; `compact=True` omits static batch data.
- WMO `geometry=True`: static group geometry; Qt previews still use GLB.
- ADT/WMO `world_scene=True`: packed retained world geometry plus original
  terrain layers/alpha/shadow, placements, WMO colour/class/fog/portal metadata
  and separate walking/sight triangles; MCLQ/MLIQ wet grids with original kinds,
  depth coordinates and pool colors; transformed portal polygons/planes and
  group bounds/flags, MDDF placements and selected MODS/MODD props with MODR
  ownership and MODD/MOLR light probes. Optional `origin`, `position`, `rotation`, `doodad_set`
  use original Z-up coordinates; the adapter then converts to Qt Y-up.
- M2 `world_scene=True, anchor=[16 column-major floats]`: transformed initial
  Stand/global-sequence pose and separate authored collision hull; no hull means
  no fake render-mesh collider. Continuous world animation/effects remain open.
- DBC `schema=[...]`: explicit uint32/int32/float32/string column types.
- `mount_chain(path=...)`: original archive priority over an approved directory.
- `chain_read(entry=...)`: winning named entry; tombstones block older copies.
- `chain_list`: original listfile union, with listing size/name bounds.
- `sound_kit(kit=id_or_name)`: original typed SoundEntries catalog.
- `character(character=...)`: original composition from a mounted chain: RGBA
  body atlas, hair/extra/cape textures and original geoset selection.
- `pose(..., instance=...)`: also advance a pane's bounded particle pools:
  packed RGBA vertex colours, head/tail flipbooks and original emission tracks.
- `creature_display(display_id=...)`: original CreatureDisplayInfo/ModelData/Extra:
  model, scale, alpha, monster skins, NPC baked/live skin, geosets and worn parts.
- Runtime `attachments`: original attach-lookup transforms, animated by the bone palette.
  `anchor=[16 column-major floats]` samples an attached model in its parent's space.
- Runtime `ribbons`: per-instance retained RGBA strips from original ribbon tracks/gates;
  original raw blend modes 0–6, atlas cells, stored edge widths and positive gravity rise.
- `release_instance(instance=...)`: release one pane's particles and ribbons.
- `unload(path=...)`: release a retained native M2 model and its effects.

The Qt canvas uses retained geometry for live M2. Each pane owns its geometry and
material state, so two panes can play different animations of the same file.
Lua's original model clocks receive the file's facts and control the rendered
sequence/camera/light/fog/icon. Texture transforms preserve raw quaternion
rotation about the UV midpoint. Reflection coordinates are generated in camera
space. Blend modes 0–6 preserve the original blend equations. Camera-free panes
use the original orthographic framing, inherited layout scale, facing and pixel
position; authored cameras use the original root-scale law. Zero-normal vertices
retain the original ambient/SH lighting.

`AssetCache.mount_chain(directory)` enables temporary on-demand extraction for
model, texture and audio references. A packaged `qml/game/Data` directory with
known MPQs is discovered lazily. No installation directory is scanned. Extraction
is capped at 128 files/64 MiB and removed when its owner closes. The native reader
keeps canonical paths inside its selected root, including resolved symlinks.
Archive mount order is the original Chain order, including deletion markers.
Core FrameXML and addons can read bounded Lua/XML source bytes directly from
the chain without temporary disk extraction. The original TOC parser, raw Lua
bytes, nested XML references, LoadOnDemand, saved state and bindings are retained.
The optional core TOC runs before addons. Broken chunks are reported while later
files and addons continue. Core and addon code share a 2048-file/8 MiB budget.

Reader, IPC, geometry, animation, decoder-time and retained-memory limits are in
`native/presentation/api.json`. Workers and temporary files close with the game
UI. Malformed assets remain isolated; retries back off for two seconds.

Character atlases and geoset selection now reuse the original CharSections,
CharacterGeosets, ItemDisplayInfo and CompositePlan. The original body, face,
hair, underwear, equipment and tabard/emblem layer rules run in the supervised
reader. Each Qt pane retains its own texture and visibility mask.
`GG_SetCharacterAppearance(frameName, options)` is a GG Lua host extension;
`nil` clears it. Options use original display IDs, not GG inventory template IDs.
The eight equipment entries are shirt/chest/belt/pants/boots/wrist/gloves/tabard.
`helmet`, `shoulders`, `mainhand`, `offhand` and `offhand_is_shield` resolve original
ItemDisplayInfo parts: race/sex helm, asymmetric shoulders, held weapon and shield.
Each part uses its independently authored model and Object texture, attached through
M2 AttachLookup, never a scan of duplicate record IDs. Missing attachment points are
reported. `appearance.attachments=[{id,model,object}]` supplies up to six explicit
parts on a model with authored lookup points. Failed staged outfits preserve the
published Qt parts; native provisional instances and memory reservations are released.
`GG_SetCreatureDisplay(frameName, displayID_or_nil)` selects the original creature
catalog. A GG snapshot asset can also supply `display_id` for `PlayerModel:SetUnit`.
NPC baked textures are used directly, with original hair/geosets and worn parts;
NPCs without a bake use the original live composite. Bound panes receive model clocks
and facts; unwrapped animation cursors keep effects alive through a clip loop, while
explicit backwards seeks still reset effects.
No original character tables or artwork are bundled; they come from the explicit
mounted chain. Independently authored fixtures verify the same interface.

Particles reuse the original emitter parser, rate/gate/parameter/global-sequence
samplers, OverLife/flipbook rules and adapted original plane/sphere/spline spawn
kernel. The Qt runtime simulates per instance and retains RGBA head/tail buffers.
Limits are eight root panes and six parts per pane (48 live attachment instances,
with six provisional slots for one outfit swap), 16 emitters/model and 256
particles/emitter, 60 Hz
substeps, 250 ms maximum frame advance, and reset on a >1 s gap or backwards
clock/seek. This is a bounded adapter, not bit-identical Bevy simulation.

Ribbons retain at most 512 edges per emitter, 16 emitters/model, a 100 ms frame
advance and 60 s edge lifetime. The original per-animation gate uses clip-local time,
while history ages on the unwrapped model clock. Shared files keep independent state.
Effect-only models also render without surface batches. Native retained files are
capped at 80, with 64 MiB of source bytes; the independent Qt geometry/texture cache
still has its combined 64 MiB budget. No cache is unbounded.

World pages now run in the real GAME ENGINE and standalone client. One loader
prepares immutable collision/sight indices and textures off the GUI thread;
Quick3D objects are created/published on the GUI thread. The current terrain
page wins, then nearby WMO/terrain pages precede distant prefetch. Up to 25
desired pages and a radius of zero/one are supported; radius zero is intended
for inspection, while radius one prefetches neighbouring travel cells.
Unchanged delegates, geometry and textures stay retained. A conservative logical
96 MiB budget covers resident spatial indices, geometry and textures with colour
mips. Temporary prepared images/IPC and retiring GPU objects are additional;
this is not a whole-process RSS ceiling. Archive extraction is evicted with pages.

Complete WMO metadata is retained while geometry and collision move together in
eight-group windows with hysteresis. A real Qt fixture traverses a 64-group WMO,
including late group ownership references, and verifies bounded residency and
floor physics. The fixture pauses teleports until the destination is resident.
An individually oversized group or excessive props still need finer subdivision.

Terrain uses original 145-vertex fans, holes/impassable flags, sequential four-layer
alpha composition, half-texel clamping and the MCSH diffuse multiplier. Repeated
base/layer/object textures share a page-owned Qt texture; alpha and
shadow textures use one mip; terrain colour mips are generated by Qt. M2/WMO and
character atlases upload the original authored BLP mip chain in a packed atlas.
The shader samples each level explicitly with derivative LOD and trilinear
filtering, clamping incomplete chains to their last authored level. Exact original
LOD/anisotropy and terrain/liquid/weather authored mips remain. WMO uses original
MOCV correction and EXT/TRANS/INT material classes, window/two-sided/unlit state,
placement transforms and group fog. Actual floor triangles classify interiors;
the actual Qt camera clips portal polygons and gates connected/exterior groups
as described below. Missing polygons use a reported conservative fallback.

The authoritative runtime samples these same floors and wall triangles, holds
unloaded/impassable cells and removes the floor at authored holes. Walking and
NPC sight use the original independent MOPY masks. Original Lua zone/interior
queries and reverb follow the selected map. GG environment geometry/static
obstacles and planet curvature are disabled for that map. NPC navigation and
content remain GG gameplay, rather than a complete original game server.

Use **DEMO WORLD** in GAME ENGINE for the own two-tile/three-room map,
**LOAD WORLD** for a scoped `gg.engine-world.v1` JSON manifest, and **GG WORLD**
to restore the prior position/provider. The standalone client also accepts
`--engine-world game/worlds/engine-demo/world.json`. An explicit optional
`archive_directory` uses the existing original archive-chain reader; no
installation directories are scanned and no installation data is bundled.

MCLQ/MLIQ surfaces now render in Quick3D using shared, bounded frame atlases.
The flip runs at the original 24 fps; liquid nibbles 6/7 scroll only on WMO.
ADT, exterior-WMO and interior-WMO water have distinct combine equations;
magma/slime are opaque and unlit. Wet-cell bilinear height, dry holes, original
liquid kind and WMO placement/storey claims drive actual GG swim physics and
`GG_GetWorldState`. Imported swim exits preserve height when leaving a ledge.
Water in the terrain overhead does not claim an interior player.
An optional manifest `liquids` object configures `STILL`, `RAPIDS`, `OCEAN`,
`MAGMA`, `SLIME`: each accepts up to 30 local `frames` and RGBA `shallow`/`deep`
values in 0..1. Without frames, the original XTextures paths are resolved from
the selected data root/chain. All frame bytes stay scoped; atlases preserve
transparent RGB and are shared by surfaces of the same kind on a page.

The real Qt perspective camera now selects WMO room visibility through
side-oriented portal planes and clipped screen rectangles. Doorway on-plane
guard, ten-hop recursion, deferred exterior windows and callback groups have
separate gates. A sealed room excludes exterior terrain/liquid rendering while
retaining its physics. Missing polygons or a graph exceeding the bounded walk
use conservative visibility, explicitly identified in stream diagnostics.

MDDF objects now load with their page, with original Euler rotation, scale and
MCSH shade. Shared unique IDs across tiles have one render/collision owner;
ownership transfers when that page leaves. Conflicting shared placements reject
the incoming page without replacing the published world. MODS always-on set 0
and the selected `doodad_set` are merged; unreferenced MODD entries are omitted.
MODR ownership gates a prop while any of its rooms is visible; any exterior
owner makes its lighting exterior. Interior props use bit-exact cap96/floor112
MODD words, the original fixed-axis seven-row SH fold and the first owner's
MOLR omni lobes, transformed and windowed by authored attenuation. MOLT lamps
do not illuminate unrelated WMO surfaces. Art and original M2 hulls commit
together; hull floors retain the building's area/interior classification.
Each page admits at most 128 placements, 32 distinct M2 sources, 64 MiB M2
source bytes, 512 draw rows, 65536 draw vertices and an 8 MiB packed packet,
within the existing eight-second loader and 96 MiB residency budgets. Missing
model/texture or malformed references fail that page explicitly. World placements
now run continuous original sequence sampling, bone billboards and effects. Model
particles use retained Qt GPU instance tables with shared mesh geometry and
per-instance transforms/colors; ordinary placed world meshes still need equivalent
grouping. Original LightCatalog sampling and day/night are connected to the image.

Full compatibility remains **PARTIAL**. The current adapters cover original
time/Light.dbc lighting, terrain sheen, SIDN, underwater atmosphere, procedural
clouds, original celestial/star laws, dual down-ray/portal-hole seeds, fully flooded
groups, shared MLIQ cells, model/one-level child particles and exact terrain/hull
ground snap, the original WDL horizon/height oracle, and original weather ramps,
packet pools, wind and precipitation geometry on retained Qt instance tables.
Decoded weather/music packet bodies now reach the native visual and audio state.
Original SoundEntries, AreaTable, WMOAreaTable, ZoneMusic, SoundAmbience and
ZoneIntroMusicTable readers select background-prepared zone/Lua/ambience streams.
Day/night beds, ghost/underwater/weather priority, interior overrides, intro
cooldowns, natural-end silence, 4 s outgoing music fades and 5 s ambience
crossfades are exercised through the real mixer. SoundProviderPreferences uses
the upstream EAX-to-Freeverb projection; it does not emulate legacy FMOD.
Short effects reuse inactive clip slots and stop only their own voice generations.
The separate protocol/session adapter is available for original wire behavior;
normal local play uses the GG simulation. Archive tracks up to 8 MiB use the
bounded file cache; larger tracks stream original archive sectors through bounded
64 KiB chunks without extraction.
Weather restores ramp endpoints after worker loss; rejected draw allocations
retain the previously published Qt state.
Authored WMO/ghost skyboxes and continuous camera sphere sweeps are connected.
Remaining work includes original event-to-host binding and original-art conformance,
dense individual WMO geometry/prop subdivision, remaining camera/vehicle modes
and unit room election, complete original gameplay/audio host, weapon
timed sheath/private bag-quiver/spell visuals, exact original mip LOD/anisotropy,
terrain/liquid/weather authored mips, and pane/transport
rebasing of world-space effects. M2 stage-zero shading preserves the original
engine-formats-core batch builder's limit; it is not complete WoW multi-combiner support.
Qt's material API does not expose independent depth-test disable.
Encrypted/single-unit/PTCH MPQs retain the
original reader's unsupported status. The original BLP mip-chain formula stops
before a stored 1x1 level; that behavior is preserved.

Verification uses independently authored binary fixtures. Evidence:
`docs/engine-world-objects-2026-10-09/verification.json`. Tests requiring an original
game installation can return early in the upstream suite; they are not evidence
of real installation compatibility. Run the GG format/model/archive/short-audio
regression tests and the finite GPU/client probes for the checked integration.
The comprehensive source/module inventory and current verification artifacts are
in `docs/engine-full-audit-2026-10-09/`. Its source-integrity gate covers 791 original
files; the world/app inventory covers 64/152 root modules. These counts are not a
percentage-complete estimate and do not prove original installation compatibility.
