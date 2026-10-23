"""Bounded nearby ground clutter; fixed trees live in the world asset catalog.

Only cells around the viewer are sampled. Work is paced and cached; settled
frames return compact metadata without re-sampling terrain or sending plants
through the 60 Hz JSON stream. Placements survive departures and returns.
"""
from __future__ import annotations

import math
import time
from typing import Callable

from backend import game_engine_planet as planet
from backend import game_engine_world as world
from backend.game_engine_streaming import SpatialResidencyCache, StreamWindow
from backend.game_engine_native_world import prioritized_cells
from backend.game_engine_nature_catalog import PLANTS
from backend.game_engine_asset_variations import VARIANTS,variant_for
from backend.game_engine_botanical_designs import foliage_variant

SCHEMA = "gg.game-engine.ecology.v1"
CELL_M = 64.0
MAX_CACHE_CELLS = 512
CELLS_PER_UPDATE = 2
SAMPLE_STEPS_PER_UPDATE = 24
BUILD_BUDGET_S = .003
TREE_SCALE_MULTIPLIER = 7.0
SPECIES = ("oak", "oak_arch", "pine", "jungle", "palm", "mangrove", "scrub", "fern", "grass", "flowers", "deadwood") + tuple(PLANTS)
TREE_SPECIES = frozenset(SPECIES[:6] + ("deadwood",))
GROUP_KEYS = tuple((species if v==0 else species+f'-v{v}')+f':{lod}' for species in SPECIES for lod in (0,1) for v in range(VARIANTS))
GROUND_CAPS = {
    "POTATO": 96,
    "PS2_CLASSIC": 256,
    "BALANCED": 384,
    "MODERN": 512,
    "CINEMATIC": 768,
}


def unit(cx: int, cz: int, salt: int, seed: int) -> float:
    value = (cx * 374761393 + cz * 668265263 + salt * 1442695041 + seed) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    return (value ^ (value >> 16)) / 4294967296.0


def biome_at(x: float, z: float, height: float) -> str:
    region = planet.region_at(x, z)
    if region is None:
        return "OCEAN"
    rid = region["id"]
    macro = region.get("biome")
    if macro == "VOLCANIC":
        return "VOLCANIC"
    if macro == "TUNDRA":
        return "TUNDRA" if z > 1835 * planet.LAYOUT_SCALE or height > 105 else "TAIGA"
    if rid == "START_ISLAND" or rid.startswith("TIDEHOLD") or height < 12:
        return "COAST"
    if macro == "JUNGLE":
        return "WETLAND" if height < 48 else "JUNGLE"
    if rid == "EASTERN_CROWN" and height > 130:
        return "TAIGA"
    return "MEADOW" if math.sin(x * .0028) + math.sin(z * .0043) > .6 else "WOODLAND"


KITS = {
    "COAST": (("palm", "mangrove"), ("grass", "scrub"), .20),
    "WOODLAND": (("oak", "oak_arch"), ("fern", "grass", "flowers"), .46),
    "MEADOW": (("oak", "oak_arch"), ("grass", "flowers"), .10),
    "TAIGA": (("pine",), ("scrub", "grass"), .39),
    "TUNDRA": (("pine",), ("scrub",), .08),
    "JUNGLE": (("jungle", "oak_arch"), ("fern", "grass"), .49),
    "WETLAND": (("mangrove", "jungle"), ("fern", "grass"), .32),
    "VOLCANIC": (("deadwood",), ("scrub",), .07),
}
for _biome, (_trees, _ground, _density) in tuple(KITS.items()):
    KITS[_biome] = (_trees, _ground + tuple(s for s, spec in PLANTS.items() if _biome in spec[2].split()), _density)


class FloraStreamer:
    def __init__(self, seed: int):
        self.seed = int(seed)
        self.cache = SpatialResidencyCache(MAX_CACHE_CELLS)
        self.groups = {}
        self._anchor = None
        self._terrain_revision = None
        self._revision = 0
        self._view = {}
        self._partial = None

    def _cell_samples(self, cx: int, cz: int, height_at: Callable):
        # A jittered lattice prevents overlapping trunks while keeping a
        # natural distribution; the shared seed is independent of camera/time.
        for index in range(64):
            # Each yielded checkpoint caps even a cell containing mostly
            # rejected water/cliff candidates; one cell is not an atomic hitch.
            yield None
            x = (cx + (index % 8 + .5) / 8) * CELL_M
            z = (cz + (index // 8 + .5) / 8) * CELL_M
            x += (unit(cx, cz, index * 7 + 1, self.seed) - .5) * 4
            z += (unit(cx, cz, index * 7 + 2, self.seed) - .5) * 4
            # The authored village has plants, paths and gameplay clearance.
            if max(abs(x), abs(z)) < 92:
                continue
            if not (planet.MAP_BOUNDS_M["min_x"] <= x <= planet.MAP_BOUNDS_M["max_x"]
                    and planet.MAP_BOUNDS_M["min_z"] <= z <= planet.MAP_BOUNDS_M["max_z"]):
                continue
            if planet.region_at(x, z) is None:
                continue
            height = float(height_at(x, z))
            if not math.isfinite(height) or height < 1.2:
                continue
            from backend.game_engine_landscape import clutter_allowed,biome_at as landscape_biome
            if not clutter_allowed(x,z):
                continue
            biome = biome_at(x, z, height)
            _, ground, density = KITS[biome]
            if landscape_biome(x,z)=='FIELDS':ground=('grass',)
            random = unit(cx, cz, index * 7 + 3, self.seed)
            # Thirty-two metre trunk lattice, jittered like the old placement.
            # Larger crowns keep space between trunks; small flora still use
            # the original eight metre lattice.
            tree_site = index % 8 % 4 == 1 and index // 8 % 4 == 1
            is_tree = tree_site and random < min(.95, density * 2)
            # Large objects are saved map placements, uploaded by the retained
            # world-tree renderer. Runtime scatter is only for small plants.
            if is_tree:
                continue
            # A region-dependent gap leaves glades and traversable clearances.
            if random > .83:
                continue
            slope = math.hypot(float(height_at(x + 1, z)) - height,
                               float(height_at(x, z + 1)) - height)
            if not math.isfinite(slope) or slope > .85:
                continue
            choices = ground
            species = choices[int(unit(cx, cz, index * 7 + 4, self.seed) * len(choices))]
            scale = (.80 + unit(cx, cz, index * 7 + 5, self.seed) * .46)
            tint = .90 + unit(cx, cz, index * 7 + 6, self.seed) * .16
            radius = world.DEFAULT_PLANET_RADIUS_METERS
            render_y = math.sqrt(max(1, (radius + height) ** 2 - x*x - z*z)) - radius
            yield {"id": f"flora:{cx}:{cz}:{index}", "species": species,
                         "x": x, "y": render_y - .06, "z": z, "ground_height_m": height,
                         "yaw": unit(cx, cz, index * 7, self.seed) * 360,
                         "scale": scale, "tint": tint, "biome": biome}

    def update(self, x: float, z: float, *, profile: str, terrain_revision: int,
               height_at: Callable) -> dict:
        if not math.isfinite(x) or not math.isfinite(z):
            raise ValueError("finite flora focus required")
        ground_cap = GROUND_CAPS.get(profile, GROUND_CAPS["BALANCED"])
        anchor = (math.floor(x / 32), math.floor(z / 32), profile)
        if terrain_revision != self._terrain_revision:
            self.cache.clear()
            self._anchor = None
            self._partial = None
            self._terrain_revision = terrain_revision
        window = StreamWindow.at(x, z, 88, CELL_M)
        # Ground clutter needs a small walking/flight prefetch ring, independent
        # of the kilometre-scale camera horizon used for permanent objects.
        desired = prioritized_cells(x,z,CELL_M,3)
        pending = [cell for cell in desired if cell not in self.cache]
        started = time.perf_counter()
        completed = 0
        for _ in range(SAMPLE_STEPS_PER_UPDATE):
            if time.perf_counter()-started >= BUILD_BUDGET_S or completed >= CELLS_PER_UPDATE:
                break
            if self._partial is None:
                missing = next((cell for cell in pending if cell not in self.cache), None)
                if missing is None:
                    break
                self._partial = (missing, self._cell_samples(*missing, height_at), [])
            cell, samples, rows = self._partial
            try:
                sample = next(samples)
                if sample is not None:
                    rows.append(sample)
            except StopIteration:
                self.cache.put(cell, tuple(rows))
                self._partial = None
                completed += 1
        self.cache.touch_many(desired)
        self.cache.scope((x, z), (window.outer+2)*CELL_M*math.sqrt(2), time.monotonic())
        if anchor == self._anchor and completed == 0 and self._view:
            self._view["pending_cells"] = sum(cell not in self.cache for cell in desired)
            return self._view
        self._anchor = anchor
        focus_x, focus_z = (anchor[0]+.5)*32, (anchor[1]+.5)*32
        candidates = []
        for cell in desired:
            for row in self.cache.get(cell, ()):
                distance = math.hypot(row["x"]-focus_x, row["z"]-focus_z)
                if distance <= 88:
                    candidates.append((distance, row["id"], row))
        candidates.sort(key=lambda r: (r[0], r[1]))
        counts = {"trees": 0, "ground": 0}
        groups = {}
        for distance, identity, row in candidates:
            if counts['ground'] >= ground_cap:
                break
            v=foliage_variant(identity,row['species'],row['biome'])
            groups.setdefault((row['species'] if v==0 else row['species']+f'-v{v}')+':0',[]).append(row)
            counts['ground'] += 1
        self.groups = groups
        self._revision += 1
        self._view = {"schema": SCHEMA, "revision": self._revision,
                      "strategy": "NEARBY_CLUTTER_PACED_CELLS_NATIVE_GPU_INSTANCING",
                      "profile": profile, "instance_count": sum(counts.values()),
                      "trees": counts["trees"], "ground": counts["ground"],
                      "pending_cells": sum(cell not in self.cache for cell in desired),
                      "resident_cells": len(self.cache), "cell_build_cap": CELLS_PER_UPDATE,
                      "sample_step_cap": SAMPLE_STEPS_PER_UPDATE,
                      "sample_budget_ms": BUILD_BUDGET_S*1000,
                      "prefetch_window_cells": len(desired), "cache_cap": MAX_CACHE_CELLS,
                      "cache_grace_s": 30, "residency_source": "GG_ENGINE_ADAPTED_WINDOW_AND_SPATIAL_CACHE",
                      "residency_backend": self.cache.backend,
                      "tree_cap": 0, "ground_cap": ground_cap,
                      "ground_distance_m": 88,
                      "world_trees": "FIXED_MAP_SECTORS_TERRAIN_CAMERA_FAR_PLANE",
                      "groups": {key: len(rows) for key, rows in groups.items()},
                      "collision": "DECORATIVE_FLORA_ONLY", "land_fauna": "SEPARATE_NATURE_WORLD"}
        return self._view
