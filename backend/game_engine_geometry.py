"""Small QtQuick3D geometry builders for the GAME ENGINE preview.

The simulation owns the terrain field.  This module turns one bounded height
grid from that contract into a native ``QQuick3DGeometry`` object and builds
one reusable low-poly character mesh.  It keeps the renderer cheap (a 5x5
grid for the nearest cell and eight cached character pose phases) while
allowing the surface to show slopes, rounded hills, authored brush relief and
a readable humanoid silhouette instead of one cube or render object per
detail.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry, QQuick3DTextureData

from backend import game_engine_mobility as mobility_contract
from backend import game_engine_world as world_scale


MAX_GEOMETRIES = 128
VERTEX_STRIDE = 32  # position (3), normal (3), UV (2), all little-endian f32
TERRAIN_VERTEX_STRIDE = 48  # position, normal, UV, RGBA vertex color, all f32
# The character mesh carries one RGBA vertex color after its position and
# normal.  Keeping this stride separate means terrain and item geometry retain
# their existing ABI while characters can have several readable material
# regions in one Model/draw path.
CHARACTER_VERTEX_STRIDE = 40  # position (3), normal (3), color (4)
CHARACTER_STYLE_ID = "GG_CLAY_LOW_POLY"
CHARACTER_STYLE_VERSION = "v1"
CHARACTER_POSE_BUCKETS = 8
CHARACTER_MOTION_STATES = {"IDLE", "WALK", "SPRINT", "AIR"}
ASSET_VERTEX_STRIDE = 40  # position (3), normal (3), RGBA vertex color (4)
ASSET_STYLE_ID = "GG_CLAY_ASSET_KIT"
ASSET_STYLE_VERSION = "v1"
MAX_ASSET_GEOMETRIES = 96
LOW_POLY_SPHERE_SEGMENTS = 12
LOW_POLY_SPHERE_RINGS = 6
LOW_POLY_SPHERE_RADIUS = 50.0
TERRAIN_SKIRT_DEPTH_M = 0.25
TERRAIN_SKIRT_NORMAL_UP = 0.88
WATER_GRID_SIZE = 65
WATER_VERTEX_STRIDE = 48  # position, normal, UV, RGBA; all little-endian f32
WATER_SURFACE_SPAN_M = 560.0
WATER_SPAN_MAX_M = 800.0
# Keep the shoreline triangles small enough that the water mask does not
# reveal the coarse radial fan as large pale polygons around the island.
WATER_DISK_RINGS = 48
WATER_DISK_SEGMENTS = 96
WATER_DISK_RADIAL_POWER = 1.65
PLANET_WATER_VERTEX_STRIDE = WATER_VERTEX_STRIDE
PLANET_WATER_RADIUS_M = 1_000_000.0
PLANET_WATER_RADIAL_RINGS = 192
PLANET_WATER_SEGMENTS = 128
HORIZON_RINGS = 22
HORIZON_SEGMENTS = WATER_DISK_SEGMENTS
HORIZON_INNER_M = WATER_SURFACE_SPAN_M * 0.5
HORIZON_OUTER_M = 4200.0 * world_scale.PLANET_LAYOUT_SCALE
HORIZON_LIP_M = 0.0
# One baked island height field for water clarity. The shader samples it.
# Row 0 is south, because Qt Quick 3D's v=0 is the bottom of the texture.
# Stored as RGBA8, not a float texture: a float texture makes the whole
# material draw nothing, so the sea disappears.
SEA_BED_EXTENT_M = 120.0 * world_scale.PLANET_LAYOUT_SCALE
SEA_BED_RESOLUTION = 96
SEA_BED_MIN_M = -80.0
SEA_BED_SPAN_M = 120.0
PARTICLE_BATCH_CAPACITY = 256
PARTICLE_VERTEX_STRIDE = 48  # position, normal, RGBA vertex color, soft-card UV
PARTICLE_HALF_SIZE_M = 0.055


def water_surface_y(x: float, z: float, height: float) -> float:
    """Curved sea height. The disk and the horizon ring both use this."""
    radial = max(1.0, PLANET_WATER_RADIUS_M + height)
    return math.sqrt(max(
        1.0,
        radial * radial - x * x - z * z,
    )) - PLANET_WATER_RADIUS_M


def water_disk_indices(rings: int, segments: int) -> list[int]:
    """Triangles for a disk. Vertex 0 is the center. Ring 1 is the first loop.

    Winding matches the old grid: the geometric normal points up.
    """
    indices: list[int] = []

    def vertex(ring: int, segment: int) -> int:
        return 1 + (ring - 1) * segments + (segment % segments)

    for segment in range(segments):
        indices.extend((0, vertex(1, segment + 1), vertex(1, segment)))
    for ring in range(1, rings):
        for segment in range(segments):
            inner = vertex(ring, segment)
            inner_next = vertex(ring, segment + 1)
            outer = vertex(ring + 1, segment)
            outer_next = vertex(ring + 1, segment + 1)
            indices.extend((
                inner, inner_next, outer,
                inner_next, outer_next, outer,
            ))
    return indices


def water_disk_local(rings: int, segments: int, radius: float) -> list[tuple[float, float]]:
    """Local XZ of the disk. Outer ring sits on ``radius``."""
    coords = [(0.0, 0.0)]
    power = WATER_DISK_RADIAL_POWER
    for ring in range(1, rings + 1):
        distance = radius * (ring / float(rings)) ** power
        for segment in range(segments):
            angle = math.tau * segment / float(segments)
            coords.append((distance * math.cos(angle), distance * math.sin(angle)))
    return coords


def sea_bed_grid(
    resolution: int = SEA_BED_RESOLUTION,
    extent: float = SEA_BED_EXTENT_M,
) -> list[float]:
    """Island heights, row-major, south to north. Open water is negative."""
    from backend import game_engine_terrain as terrain_contract

    step = (2.0 * extent) / float(resolution)
    empty: dict[tuple[int, int], tuple[dict[str, Any], ...]] = {}
    values: list[float] = []
    for row in range(resolution):
        z = -extent + (row + 0.5) * step
        for col in range(resolution):
            x = -extent + (col + 0.5) * step
            values.append(terrain_contract.height_at(
                x,
                z,
                brush_stamps=[],
                brush_index=empty,
            ))
    return values


def sea_bed_byte(height: float) -> int:
    """Encode one height into the red channel the sea shader reads back."""
    span = SEA_BED_SPAN_M if SEA_BED_SPAN_M else 1.0
    unit = (float(height) - SEA_BED_MIN_M) / span
    if unit < 0.0:
        unit = 0.0
    elif unit > 1.0:
        unit = 1.0
    return int(round(unit * 255.0))


def _bind_water_attributes(geometry: QQuick3DGeometry) -> None:
    geometry.setStride(WATER_VERTEX_STRIDE)
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.PositionSemantic,
        0,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.NormalSemantic,
        12,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.TexCoordSemantic,
        24,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.ColorSemantic,
        32,
        QQuick3DGeometry.Attribute.F32Type,
    )


class WaterWaveGeometry:
    """Player-centered sea disk driven by the same waves as the hull."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        span_m: float = WATER_SURFACE_SPAN_M,
        grid_size: int = WATER_GRID_SIZE,
    ) -> None:
        self.geometry = QQuick3DGeometry(parent)
        self.geometry.setObjectName("gameEngineAnalyticWaveSurface")
        self._span_m = max(64.0, min(WATER_SPAN_MAX_M, _finite_float(span_m, WATER_SURFACE_SPAN_M)))
        self._grid_size = self._safe_grid_size(grid_size, WATER_GRID_SIZE)
        _bind_water_attributes(self.geometry)
        self.geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self._rings = WATER_DISK_RINGS
        self._segments = WATER_DISK_SEGMENTS
        indices = water_disk_indices(self._rings, self._segments)
        self.geometry.setIndexData(struct.pack("<%dH" % len(indices), *indices))
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.IndexSemantic,
            0,
            QQuick3DGeometry.Attribute.U16Type,
        )
        wave_bound = mobility_contract.MAX_WAVE_HEIGHT_M + 1.0
        half_span = self._span_m * 0.5
        self.geometry.setBounds(
            QVector3D(-half_span, -wave_bound, -half_span),
            QVector3D(half_span, wave_bound, half_span),
        )
        # One island-height grid for shoreline opacity. Not a GPU texture:
        # that path drew nothing in the game view.
        self._bed = sea_bed_grid()
        self.seabed = QQuick3DTextureData(parent)
        self.seabed.setSize(QSize(SEA_BED_RESOLUTION, SEA_BED_RESOLUTION))
        self.seabed.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.seabed.setHasTransparency(False)
        self.seabed.setTextureData(bytes(channel for h in self._bed
            for channel in (max(0,min(255,round((h-SEA_BED_MIN_M)/SEA_BED_SPAN_M*255))),0,0,255)))
        self._disk_cache: list[tuple[float, float]] | None = None
        self._disk_cache_radius: float | None = None
        self.update(0.0, 0.0, 0.0, 0.0, self._span_m, self._grid_size)

    def prepare_gpu(self, span_m=WATER_SURFACE_SPAN_M):
        """Upload a fixed local mesh once; the shader evaluates the live waves."""
        radius=max(32.,min(WATER_SPAN_MAX_M,float(span_m))*.5)
        if getattr(self,'_gpu_radius',None)==radius:return
        points=water_disk_local(self._rings,self._segments,radius)
        data=b''.join(struct.pack('<12f',x,0,z,0,1,0,x/40,z/40,0,0,0,1) for x,z in points)
        self.geometry.setVertexData(data)
        self.geometry.setBounds(QVector3D(-radius,-1000,-radius),QVector3D(radius,8,radius))
        self._gpu_radius=radius

    def _bed_height(self, x: float, z: float) -> float | None:
        extent = SEA_BED_EXTENT_M
        if x <= -extent or x >= extent or z <= -extent or z >= extent:
            return None
        resolution = SEA_BED_RESOLUTION
        step = (2.0 * extent) / float(resolution)
        fx = (x + extent) / step - 0.5
        fz = (z + extent) / step - 0.5
        x0 = int(math.floor(fx))
        z0 = int(math.floor(fz))
        if x0 < 0:
            x0 = 0
        elif x0 >= resolution:
            x0 = resolution - 1
        if z0 < 0:
            z0 = 0
        elif z0 >= resolution:
            z0 = resolution - 1
        x1 = x0 + 1 if x0 + 1 < resolution else x0
        z1 = z0 + 1 if z0 + 1 < resolution else z0
        tx = fx - math.floor(fx)
        tz = fz - math.floor(fz)
        bed = self._bed
        row0 = z0 * resolution
        row1 = z1 * resolution
        h00 = bed[row0 + x0]
        h10 = bed[row0 + x1]
        h01 = bed[row1 + x0]
        h11 = bed[row1 + x1]
        return (h00 + (h10 - h00) * tx) + ((h01 + (h11 - h01) * tx) - (h00 + (h10 - h00) * tx)) * tz

    @staticmethod
    def _safe_grid_size(value: Any, default: int) -> int:
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = default
        return max(9, min(81, size))

    def update(
        self,
        center_x: Any,
        center_z: Any,
        time_s: Any,
        sea_level_m: Any,
        span_m: Any = WATER_SURFACE_SPAN_M,
        grid_size: Any = WATER_GRID_SIZE,
    ) -> None:
        # The shaded material never appeared in the game view. These vertices
        # are the picture: world XZ, the same height the body samples.
        del grid_size
        center_x = _finite_float(center_x)
        center_z = _finite_float(center_z)
        time_s = _finite_float(time_s)
        sea_level_m = _finite_float(sea_level_m)
        span_m = max(64.0, min(WATER_SPAN_MAX_M, _finite_float(span_m, self._span_m)))
        self._span_m = span_m
        radius = span_m * 0.5
        if self._disk_cache is None or self._disk_cache_radius != radius:
            self._disk_cache = water_disk_local(self._rings, self._segments, radius)
            self._disk_cache_radius = radius
        coords = self._disk_cache
        points = [(center_x + local_x, center_z + local_z) for local_x, local_z in coords]
        samples = mobility_contract.sample_waves(points, time_s, sea_level_m=sea_level_m)
        tile = mobility_contract.WATER_TEXTURE_TILE_M
        vertex_data = bytearray(len(points) * WATER_VERTEX_STRIDE)
        min_y = math.inf
        max_y = -math.inf
        for index, ((world_x, world_z), sample) in enumerate(zip(points, samples)):
            height, slope_x, slope_z, crest = sample
            normal_length = math.sqrt(slope_x * slope_x + 1.0 + slope_z * slope_z) or 1.0
            normal_y = 1.0 / normal_length
            ground = self._bed_height(world_x, world_z)
            depth = 12.0 if ground is None else height - ground
            shore = max(0.0, min(1.0, 1.0 - depth / 2.0))
            shade_r, shade_g, shade_b, _ = mobility_contract.water_shade(
                crest, math.hypot(slope_x, slope_z), shore, 0.0
            )
            alpha = mobility_contract.water_clarity(depth)
            world_y = water_surface_y(world_x, world_z, height) - sea_level_m
            if world_y < min_y:
                min_y = world_y
            if world_y > max_y:
                max_y = world_y
            struct.pack_into(
                "<12f",
                vertex_data,
                index * WATER_VERTEX_STRIDE,
                world_x,
                world_y,
                world_z,
                -slope_x / normal_length,
                normal_y,
                -slope_z / normal_length,
                world_x / tile,
                world_z / tile,
                shade_r,
                shade_g,
                shade_b,
                alpha,
            )
        self.geometry.setVertexData(bytes(vertex_data))
        self.geometry.setBounds(
            QVector3D(center_x - radius - 4.0, min_y - 0.5, center_z - radius - 4.0),
            QVector3D(center_x + radius + 4.0, max_y + 0.5, center_z + radius + 4.0),
        )


class PlanetWaterGeometry:
    """Far sea ring. Same waves, texture and shade as the near disk.

    The first ring tucks a little under the disk so the join is a circle of
    one material, not a square seam. Render distance stays the outer radius.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        radius_m: float = PLANET_WATER_RADIUS_M,
        radial_rings: int = PLANET_WATER_RADIAL_RINGS,
        segments: int = PLANET_WATER_SEGMENTS,
    ) -> None:
        self.geometry = QQuick3DGeometry(parent)
        self.geometry.setObjectName("gameEngineCurvedPlanetWater")
        self.radius_m = max(10_000.0, _finite_float(radius_m, PLANET_WATER_RADIUS_M))
        self._rings = HORIZON_RINGS
        self._segments = HORIZON_SEGMENTS
        self._inner_m = HORIZON_INNER_M
        _bind_water_attributes(self.geometry)
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.IndexSemantic,
            0,
            QQuick3DGeometry.Attribute.U16Type,
        )

        segments = self._segments
        rings = self._rings
        index_values: list[int] = []
        for ring in range(rings - 1):
            inner_start = ring * segments
            outer_start = (ring + 1) * segments
            for segment in range(segments):
                next_segment = (segment + 1) % segments
                inner = inner_start + segment
                inner_next = inner_start + next_segment
                outer = outer_start + segment
                outer_next = outer_start + next_segment
                index_values.extend((inner, inner_next, outer, inner_next, outer_next, outer))
        self.geometry.setIndexData(struct.pack("<%dH" % len(index_values), *index_values))
        self.geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self._horizon_cache: list[tuple[float, float, float, float]] | None = None
        self._horizon_cache_inner: float | None = None
        self._horizon_stamp: tuple[float, float, float] | None = None
        self.update(0.0, 0.0, 0.0, 0.0)

    def prepare_gpu(self, inner_m=HORIZON_INNER_M):
        inner=max(32.,float(inner_m))
        if getattr(self,'_gpu_inner',None)==inner:return
        data=bytearray()
        for ring in range(self._rings):
            t=ring/(self._rings-1);fade=t*t*(3-2*t)
            distance=inner+(HORIZON_OUTER_M-inner)*t**1.55
            for segment in range(self._segments):
                angle=segment*math.tau/self._segments;x=distance*math.cos(angle);z=distance*math.sin(angle)
                data.extend(struct.pack('<12f',x,0,z,0,1,0,x/40,z/40,fade,0,0,1))
        self.geometry.setVertexData(bytes(data))
        self.geometry.setBounds(QVector3D(-HORIZON_OUTER_M,-2000,-HORIZON_OUTER_M),QVector3D(HORIZON_OUTER_M,8,HORIZON_OUTER_M))
        self._gpu_inner=inner

    def update(
        self,
        center_x: Any,
        center_z: Any,
        time_s: Any,
        sea_level_m: Any,
        inner_m: Any = None,
    ) -> None:
        """Rebuild the far ring around the player. Outer radius stays 4200 m."""
        center_x = _finite_float(center_x)
        center_z = _finite_float(center_z)
        time_s = _finite_float(time_s)
        sea_level_m = _finite_float(sea_level_m)
        # This ring shares vertices at its inner edge with the near disk.
        # Its waves must use the same center and simulation time every update;
        # a throttled ring leaves a moving seam across the sea.
        self._horizon_stamp = (center_x, center_z, time_s)
        if inner_m is not None:
            self._inner_m = max(32.0, _finite_float(inner_m, HORIZON_INNER_M))
        if self._horizon_cache is None or self._horizon_cache_inner != self._inner_m:
            segments = self._segments
            rings = self._rings
            angle_step = math.tau / float(segments)
            inner = self._inner_m
            inner_start = inner - HORIZON_LIP_M
            cached: list[tuple[float, float, float, float]] = []
            for ring in range(rings):
                t = ring / float(rings - 1)
                fade = t * t * (3.0 - 2.0 * t)
                distance = inner_start + (HORIZON_OUTER_M - inner_start) * (t ** 1.55)
                y_bias = 0.0
                for segment in range(segments):
                    angle = angle_step * segment
                    cached.append((
                        distance * math.cos(angle),
                        distance * math.sin(angle),
                        y_bias,
                        fade,
                    ))
            self._horizon_cache = cached
            self._horizon_cache_inner = self._inner_m
        records = self._horizon_cache
        points = [(center_x + local_x, center_z + local_z) for local_x, local_z, _bias, _fade in records]
        samples = mobility_contract.sample_waves(points, time_s, sea_level_m=sea_level_m)
        from backend import game_engine_terrain as terrain_contract

        tile = mobility_contract.WATER_TEXTURE_TILE_M
        vertex_data = bytearray(len(points) * WATER_VERTEX_STRIDE)
        for index, ((world_x, world_z), record, sample) in enumerate(zip(points, records, samples)):
            _lx, _lz, y_bias, fade = record
            height, slope_x, slope_z, crest = sample
            normal_length = math.sqrt(slope_x * slope_x + 1.0 + slope_z * slope_z) or 1.0
            normal_y = 1.0 / normal_length
            world_y = water_surface_y(world_x, world_z, height) - sea_level_m + y_bias
            alpha = mobility_contract.water_clarity(12.0)
            shore = 0.0
            if abs(world_x) < SEA_BED_EXTENT_M and abs(world_z) < SEA_BED_EXTENT_M:
                ground = terrain_contract.height_at(world_x, world_z)
                depth = height - ground
                shore = max(0.0, min(1.0, 1.0 - depth / 2.0))
                alpha = mobility_contract.water_clarity(depth)
            shade_r, shade_g, shade_b, _ = mobility_contract.water_shade(
                crest, math.hypot(slope_x, slope_z), shore, fade
            )
            struct.pack_into(
                "<12f",
                vertex_data,
                index * WATER_VERTEX_STRIDE,
                world_x,
                world_y,
                world_z,
                -slope_x / normal_length,
                normal_y,
                -slope_z / normal_length,
                world_x / tile,
                world_z / tile,
                shade_r,
                shade_g,
                shade_b,
                alpha,
            )
        self.geometry.setVertexData(bytes(vertex_data))
        self.geometry.setBounds(
            QVector3D(center_x - HORIZON_OUTER_M, -20.0, center_z - HORIZON_OUTER_M),
            QVector3D(center_x + HORIZON_OUTER_M, mobility_contract.MAX_WAVE_HEIGHT_M + 1.0, center_z + HORIZON_OUTER_M),
        )


class ParticleBatchGeometry:
    """One colored, crossed-billboard batch for bounded PS1/PS2-style FX.

    The old path made every spark a separate QtQuick3D Model and material.
    This keeps the same authoritative particle positions/colors but submits a
    single small mesh. Two crossed, center-faded cards give smoke and magic a
    soft edge; the same slots can draw narrow beams for lightning and lasers.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        self.geometry = QQuick3DGeometry(parent)
        self.geometry.setObjectName("gameEngineParticleBatch")
        self.geometry.setStride(PARTICLE_VERTEX_STRIDE)
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.PositionSemantic,
            0,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.NormalSemantic,
            12,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.ColorSemantic,
            24,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.TexCoordSemantic,
            40,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.geometry.addAttribute(
            QQuick3DGeometry.Attribute.IndexSemantic,
            0,
            QQuick3DGeometry.Attribute.U16Type,
        )
        indices: list[int] = []
        for particle_index in range(PARTICLE_BATCH_CAPACITY):
            base = particle_index * 10
            for offset in (0, 5):
                for corner in range(4):
                    indices.extend((
                        base + offset,
                        base + offset + 1 + corner,
                        base + offset + 1 + (corner + 1) % 4,
                    ))
        self.geometry.setIndexData(
            struct.pack("<%dH" % len(indices), *indices)
        )
        self.geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self._vertex_data = bytearray(
            PARTICLE_BATCH_CAPACITY * 10 * PARTICLE_VERTEX_STRIDE
        )
        self._active_count = -1
        self.geometry.setBounds(
            QVector3D(-0.1, -0.1, -0.1),
            QVector3D(0.1, 0.1, 0.1),
        )
        self.update(())

    def update(self, rows: Any) -> int:
        """Copy at most the simulation's visible FX budget into one mesh."""
        active = [
            row for row in rows
            if isinstance(row, dict)
        ][:PARTICLE_BATCH_CAPACITY] if isinstance(rows, (list, tuple)) else []
        if not active and self._active_count == 0:
            return 0
        data = bytearray(len(self._vertex_data))
        min_x = min_y = min_z = math.inf
        max_x = max_y = max_z = -math.inf
        vertex_index = 0

        for row in active:
            x = _finite_float(row.get("x"))
            y = _finite_float(row.get("y"))
            z = _finite_float(row.get("z"))
            tint = QColor(str(row.get("color") or "#d8bd78"))
            if not tint.isValid():
                tint = QColor("#d8bd78")
            red, green, blue, alpha = (
                tint.redF(), tint.greenF(), tint.blueF(), tint.alphaF()
            )
            kind = str(row.get("kind") or "SPARK").upper()
            defaults = {
                "SPARK": 0.055, "FLAME": 0.20, "SMOKE": 0.45,
                "GAS": 0.50, "ARCANE": 0.16, "SHADOW": 0.34,
                "LIGHTNING": 0.055, "LASER": 0.065, "FOAM": 0.18,
            }
            half = max(0.02, min(4.0, _finite_float(
                row.get("size"), defaults.get(kind, PARTICLE_HALF_SIZE_M)
            )))
            stretch = max(0.25, min(5.0, _finite_float(row.get("stretch"), 1.0)))
            alpha *= max(0.0, min(1.0, _finite_float(row.get("opacity"), 1.0)))
            ex = _finite_float(row.get("ex"), x)
            ey = _finite_float(row.get("ey"), y)
            ez = _finite_float(row.get("ez"), z)
            beam = kind in {"LIGHTNING", "LASER"} and (ex, ey, ez) != (x, y, z)
            if beam:
                dx, dy, dz = ex - x, ey - y, ez - z
                length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
                ux, uy, uz = dx / length, dy / length, dz / length
                side = math.hypot(dx, dz)
                axis_a = (-dz / side, 0.0, dx / side) if side > 1.0e-5 else (1.0, 0.0, 0.0)
                axis_b = (
                    uy * axis_a[2],
                    uz * axis_a[0] - ux * axis_a[2],
                    -uy * axis_a[0],
                )
                planes = []
                for axis in (axis_a, axis_b):
                    ax, ay, az = (part * half for part in axis)
                    planes.append(((x + ex) * 0.5, (y + ey) * 0.5, (z + ez) * 0.5,
                        ((x - ax, y - ay, z - az), (ex - ax, ey - ay, ez - az),
                         (ex + ax, ey + ay, ez + az), (x + ax, y + ay, z + az)), axis))
            elif kind == "ENCHANT":
                right = tuple(_finite_float(row.get(k), d) for k, d in
                    (("rx", 1.0), ("ry", 0.0), ("rz", 0.0)))
                up = tuple(_finite_float(row.get(k), d) for k, d in
                    (("ux", 0.0), ("uy", 1.0), ("uz", 0.0)))
                corners = tuple(tuple(p + half * sx * r + half * sy * u
                    for p, r, u in zip((x, y, z), right, up))
                    for sx, sy in ((-1,-1),(1,-1),(1,1),(-1,1)))
                planes = [(x, y, z, corners, (0.0,0.0,1.0)),
                    (x, y, z, ((x,y,z),)*4, (0.0,0.0,1.0))]
            else:
                high = half * stretch
                planes = [
                    (x, y, z,
                     ((x - half, y - high, z), (x + half, y - high, z),
                      (x + half, y + high, z), (x - half, y + high, z)),
                     (0.0, 0.0, 1.0)),
                    (x, y, z,
                     ((x, y - high, z - half), (x, y - high, z + half),
                      (x, y + high, z + half), (x, y + high, z - half)),
                     (1.0, 0.0, 0.0)),
                ]
            edge_alpha = alpha if kind == "ENCHANT" else alpha * (0.10 if beam else 0.0)
            for plane_index, (cx, cy, cz, corners, normal) in enumerate(planes):
                shade = 1.0 if plane_index == 0 else 0.86
                card_alpha = 0.0 if kind == "ENCHANT" and plane_index else 1.0
                for position, opacity, uv in [((cx, cy, cz), alpha, (.5,.5)), *(
                    (corner, edge_alpha, uv) for corner,uv in zip(corners,((0.,0.),(1.,0.),(1.,1.),(0.,1.)))
                )]:
                    struct.pack_into(
                        "<12f",
                        data,
                        vertex_index * PARTICLE_VERTEX_STRIDE,
                        *position,
                        *normal,
                        red * shade, green * shade, blue * shade, opacity * card_alpha,
                        uv[0] + (4.0+2.0*int(row['attachment_index'])
                            if row.get('attachment_local') else 2.0 if row.get('through_fog') else 0.0), uv[1],
                    )
                    vertex_index += 1
                bounds=row.get('attachment_bounds')
                # Shader-attached vertices are local, but native frustum
                # culling needs their world bounds. Include the complete
                # weapon swing between simulation publications.
                bounds_points=((bounds[0]-4,bounds[1]-4,bounds[2]-4),
                               (bounds[0]+4,bounds[1]+4,bounds[2]+4)) if bounds else corners
                for px, py, pz in bounds_points:
                    min_x = min(min_x, px)
                    min_y = min(min_y, py)
                    min_z = min(min_z, pz)
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)
                    max_z = max(max_z, pz)

        self.geometry.setVertexData(bytes(data))
        if active:
            self.geometry.setBounds(
                QVector3D(min_x, min_y, min_z),
                QVector3D(max_x, max_y, max_z),
            )
        else:
            self.geometry.setBounds(
                QVector3D(-0.001, -0.001, -0.001),
                QVector3D(0.001, 0.001, 0.001),
            )
        self._active_count = len(active)
        # Publish changed data/bounds after the geometry is already in a scene.
        self.geometry.update()
        return len(active)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _cell_coordinates(cell: dict[str, Any]) -> tuple[int, int] | None:
    try:
        return int(cell.get("x", 0)), int(cell.get("z", 0))
    except (TypeError, ValueError):
        return None


CHARACTER_CAST_VARIANTS = ("CROWD", "WANDERER", "GUARDIAN", "CRITTER")


def character_variant_key(value: Any = "CROWD") -> str:
    kind = str(value or "CROWD").strip().upper()
    if kind in {"WANDERER", "GUARDIAN", "CRITTER"}:
        return kind
    return "CROWD"


def character_pose_key(
    motion_state: Any = "IDLE",
    phase: Any = 0.0,
) -> tuple[str, int]:
    """Quantize a pose to a small reusable geometry variant.

    A real skinned importer can later consume the same state and phase.  The
    preview deliberately quantizes the phase so thirty render updates per
    second do not create a new native QObject for every frame.
    """
    state = str(motion_state or "IDLE").strip().upper()
    if state not in CHARACTER_MOTION_STATES:
        state = "IDLE"
    safe_phase = _finite_float(phase) % math.tau
    bucket = int(
        math.floor(
            safe_phase / math.tau * CHARACTER_POSE_BUCKETS + 0.5
        )
    ) % CHARACTER_POSE_BUCKETS
    return state, bucket


def _rotate_x(y: float, z: float, angle: float) -> tuple[float, float]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return y * cosine - z * sine, y * sine + z * cosine


def _rotate_y(x: float, z: float, angle: float) -> tuple[float, float]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return x * cosine - z * sine, x * sine + z * cosine


def _append_vertex(
    vertex_data: bytearray,
    position: tuple[float, float, float],
    normal: tuple[float, float, float],
    *,
    uv: tuple[float, float] = (0.0, 0.0),
    color: tuple[float, float, float, float] | None = None,
) -> None:
    """Append one interleaved vertex for either legacy or colored geometry."""
    if color is None:
        vertex_data.extend(struct.pack("<8f", *position, *normal, *uv))
        return
    vertex_data.extend(struct.pack("<10f", *position, *normal, *color))


def _grid_for_cell(
    cell: dict[str, Any],
) -> tuple[int, list[float]] | None:
    geometry = cell.get("geometry")
    values = cell.get("height_grid_m")
    if not isinstance(geometry, dict) or not isinstance(values, list):
        return None
    try:
        grid_size = int(geometry.get("vertex_grid", 0))
    except (TypeError, ValueError):
        return None
    if grid_size < 2 or grid_size > 5 or len(values) != grid_size * grid_size:
        return None
    safe_values = [
        _finite_float(value)
        for value in values
    ]
    return grid_size, safe_values


def _normal_grid_for_cell(
    cell: dict[str, Any],
    grid_size: int,
) -> list[tuple[float, float, float]] | None:
    """Read shared-field normals when the terrain contract provides them."""
    values = cell.get("normal_grid")
    if not isinstance(values, list) or len(values) != grid_size * grid_size * 3:
        return None
    safe_values = [_finite_float(value) for value in values]
    result: list[tuple[float, float, float]] = []
    for index in range(0, len(safe_values), 3):
        nx, ny, nz = safe_values[index:index + 3]
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        result.append((nx / length, ny / length, nz / length))
    return result


def _smoothstep(start: float, end: float, value: float) -> float:
    if end <= start:
        return 1.0 if value >= end else 0.0
    amount = max(0.0, min(1.0, (value - start) / (end - start)))
    return amount * amount * (3.0 - 2.0 * amount)


def _blend_rgb(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    amount: float,
) -> tuple[float, float, float]:
    blend = max(0.0, min(1.0, float(amount)))
    return tuple(
        left[index] * (1.0 - blend) + right[index] * blend
        for index in range(3)
    )


def _terrain_surface_color(
    world_x: float,
    world_z: float,
    height: float,
    normal: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    """Blend beach, grass and exposed stone from the shared terrain samples."""
    patch_noise = 0.5 + 0.5 * (
        math.sin(world_x * 0.145 + world_z * 0.071 + 0.8)
        * math.sin(world_z * 0.132 - world_x * 0.047 - 0.35)
    )
    damp_sand = (0.56, 0.41, 0.25)
    warm_sand = (0.78, 0.62, 0.36)
    grass_low = (0.08, 0.30, 0.075)
    grass_high = (0.25, 0.49, 0.10)

    shore = _blend_rgb(
        damp_sand,
        warm_sand,
        _smoothstep(-0.40, 0.55, height),
    )
    grass = _blend_rgb(
        grass_low,
        grass_high,
        0.22 + patch_noise * 0.66,
    )
    color = _blend_rgb(shore, grass, _smoothstep(-0.08, 0.55, height))

    slope_up = max(0.0, min(1.0, normal[1]))
    # Rock is a property of the same continuous heightfield used for contact
    # and navigation.  Broad elevation bands give steep, non-walkable faces a
    # Sandover-like sandstone read without laying a second mesh over the ground.
    cliff_by_slope = 1.0 - _smoothstep(0.62, 0.92, slope_up)
    layer_wave = math.sin(
        height * 2.7
        + 0.25 * math.sin(world_x * 0.12 + world_z * 0.10)
    )
    sandstone_light = (0.70, 0.43, 0.24)
    sandstone_dark = (0.39, 0.19, 0.11)
    layer_amount = _smoothstep(-0.55, 0.55, layer_wave)
    layer_color = _blend_rgb(sandstone_dark, sandstone_light, layer_amount)
    stone_color = _blend_rgb(layer_color, (0.27, 0.14, 0.10), patch_noise * 0.30)
    exposed_rock = min(0.94, cliff_by_slope * (0.82 + patch_noise * 0.14))
    color = _blend_rgb(color, stone_color, exposed_rock)
    return (color[0], color[1], color[2], 1.0)


def _append_terrain_skirt(
    vertex_data: bytearray,
    index_values: list[int],
    heights: list[float],
    grid_size: int,
    ordered_edge: list[int],
    normal: tuple[float, float, float],
    step: float,
    cell_x: int,
    cell_z: int,
) -> None:
    """Append one cheap vertical edge curtain for LOD seam protection.

    Adjacent patches share the analytic field's endpoint heights, but a 5x5
    patch next to a 3x3 or 2x2 patch can still have a rasterization gap at a
    T-junction.  A shallow curtain hides only that sub-pixel crack and keeps
    the real heightfield untouched.
    """
    top_indices: list[int] = []
    bottom_indices: list[int] = []
    # The curtain is a geometric seam guard, not a cliff face. A purely
    # horizontal normal receives almost no light from the preview's cheap
    # directional key and reads as a black crack in the terrain. Bias its
    # shading toward the terrain's upward normal while retaining a little
    # outward direction so the strip still rolls naturally at the edge.
    raw_nx, raw_ny, raw_nz = normal
    horizontal = math.sqrt(raw_nx * raw_nx + raw_nz * raw_nz) or 1.0
    upward = TERRAIN_SKIRT_NORMAL_UP
    side = math.sqrt(max(0.0, 1.0 - upward * upward))
    nx = raw_nx / horizontal * side
    ny = upward
    nz = raw_nz / horizontal * side
    for source_index in ordered_edge:
        row, column = divmod(source_index, grid_size)
        x = column * step
        y = float(heights[source_index])
        z = row * step
        top_indices.append(len(vertex_data) // TERRAIN_VERTEX_STRIDE)
        top_color = _terrain_surface_color(
            cell_x * 16.0 + x,
            cell_z * 16.0 + z,
            y,
            normal,
        )
        vertex_data.extend(
            struct.pack(
                "<12f",
                x,
                y,
                z,
                nx,
                ny,
                nz,
                column / float(grid_size - 1),
                row / float(grid_size - 1),
                *top_color,
            )
        )
        bottom_y = y - TERRAIN_SKIRT_DEPTH_M
        bottom_indices.append(len(vertex_data) // TERRAIN_VERTEX_STRIDE)
        shadow_color = _blend_rgb(
            (top_color[0], top_color[1], top_color[2]),
            (0.28, 0.20, 0.14),
            0.36,
        )
        vertex_data.extend(
            struct.pack(
                "<12f",
                x,
                bottom_y,
                z,
                nx,
                ny,
                nz,
                column / float(grid_size - 1),
                row / float(grid_size - 1),
                *shadow_color,
                1.0,
            )
        )
    for index in range(len(top_indices) - 1):
        top_a = top_indices[index]
        top_b = top_indices[index + 1]
        bottom_a = bottom_indices[index]
        bottom_b = bottom_indices[index + 1]
        index_values.extend(
            (
                top_a,
                top_b,
                bottom_b,
                top_a,
                bottom_b,
                bottom_a,
            )
        )


def _append_box(
    vertex_data: bytearray,
    index_values: list[int],
    center: tuple[float, float, float],
    half_size: tuple[float, float, float],
    rotation_x: float = 0.0,
    color: tuple[float, float, float, float] | None = None,
    vertex_stride: int = VERTEX_STRIDE,
) -> None:
    """Append one flat-shaded box to a combined character mesh."""
    cx, cy, cz = center
    hx, hy, hz = half_size
    faces = (
        ((0.0, -1.0, 0.0),
         ((-hx, -hy, -hz), (hx, -hy, -hz),
          (hx, -hy, hz), (-hx, -hy, hz))),
        ((0.0, 1.0, 0.0),
         ((-hx, hy, -hz), (-hx, hy, hz),
          (hx, hy, hz), (hx, hy, -hz))),
        ((0.0, 0.0, -1.0),
         ((-hx, -hy, -hz), (-hx, hy, -hz),
          (hx, hy, -hz), (hx, -hy, -hz))),
        ((0.0, 0.0, 1.0),
         ((-hx, -hy, hz), (hx, -hy, hz),
          (hx, hy, hz), (-hx, hy, hz))),
        ((-1.0, 0.0, 0.0),
         ((-hx, -hy, hz), (-hx, hy, hz),
          (-hx, hy, -hz), (-hx, -hy, -hz))),
        ((1.0, 0.0, 0.0),
         ((hx, -hy, -hz), (hx, hy, -hz),
          (hx, hy, hz), (hx, -hy, hz))),
    )
    for normal, corners in faces:
        start = len(vertex_data) // vertex_stride
        nx, ny, nz = normal
        normal_y, normal_z = _rotate_x(ny, nz, rotation_x)
        for index, (x, y, z) in enumerate(corners):
            rotated_y, rotated_z = _rotate_x(y, z, rotation_x)
            _append_vertex(
                vertex_data,
                (cx + x, cy + rotated_y, cz + rotated_z),
                (nx, normal_y, normal_z),
                uv=(
                    0.0 if index in (0, 3) else 1.0,
                    0.0 if index in (0, 1) else 1.0,
                ),
                color=color,
            )
        index_values.extend(
            (
                start,
                start + 1,
                start + 2,
                start,
                start + 2,
                start + 3,
            )
        )


def _append_ellipsoid(
    vertex_data: bytearray,
    index_values: list[int],
    center: tuple[float, float, float],
    radius: tuple[float, float, float],
    *,
    segments: int = 8,
    rings: int = 4,
    rotation_x: float = 0.0,
    yaw: float = 0.0,
    color: tuple[float, float, float, float] | None = None,
    vertex_stride: int = VERTEX_STRIDE,
) -> None:
    """Append a small smooth low-poly ellipsoid for a torso, limb or frond."""
    cx, cy, cz = center
    rx, ry, rz = radius
    start = len(vertex_data) // vertex_stride
    for ring in range(rings + 1):
        theta = math.pi * ring / float(rings)
        sine = math.sin(theta)
        cosine = math.cos(theta)
        for segment in range(segments):
            phi = math.tau * segment / float(segments)
            x = sine * math.cos(phi)
            y = cosine
            z = sine * math.sin(phi)
            ox, oy, oz = x * rx, y * ry, z * rz
            oy, oz = _rotate_x(oy, oz, rotation_x)
            ox, oz = _rotate_y(ox, oz, yaw)
            nx, ny, nz = x, y, z
            ny, nz = _rotate_x(ny, nz, rotation_x)
            nx, nz = _rotate_y(nx, nz, yaw)
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            _append_vertex(
                vertex_data,
                (cx + ox, cy + oy, cz + oz),
                (nx / length, ny / length, nz / length),
                uv=(segment / float(segments), ring / float(rings)),
                color=color,
            )
    for ring in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            top_left = start + ring * segments + segment
            top_right = start + ring * segments + next_segment
            bottom_left = top_left + segments
            bottom_right = start + (ring + 1) * segments + next_segment
            index_values.extend(
                (
                    top_left,
                    bottom_left,
                    top_right,
                    top_right,
                    bottom_left,
                    bottom_right,
                )
            )


def build_low_poly_sphere_geometry() -> QQuick3DGeometry:
    """Build the shared sphere used by small props and item fallbacks.

    Qt's ``#Sphere`` convenience mesh is useful for smoke tests, but its
    default topology is far too dense for dozens of tiny world objects.  This
    sphere keeps the existing 100-unit primitive scale contract (radius 50),
    uses only 12 segments and 6 rings, and shares smooth vertex normals so it
    reads round without paying for thousands of faces per instance.
    """
    segments = LOW_POLY_SPHERE_SEGMENTS
    rings = LOW_POLY_SPHERE_RINGS
    radius = LOW_POLY_SPHERE_RADIUS
    vertex_data = bytearray()

    def append_vertex(x: float, y: float, z: float, u: float, v: float) -> None:
        length = math.sqrt(x * x + y * y + z * z) or 1.0
        vertex_data.extend(
            struct.pack(
                "<8f",
                x * radius,
                y * radius,
                z * radius,
                x / length,
                y / length,
                z / length,
                u,
                v,
            )
        )

    # One shared pole per cap avoids the degenerate triangles produced by a
    # conventional UV grid while the duplicated longitude seam keeps UVs
    # continuous for a future textured item material.
    append_vertex(0.0, 1.0, 0.0, 0.5, 0.0)
    ring_vertex_count = segments + 1
    for ring in range(1, rings):
        theta = math.pi * ring / float(rings)
        sine = math.sin(theta)
        cosine = math.cos(theta)
        for segment in range(ring_vertex_count):
            phi = math.tau * segment / float(segments)
            append_vertex(
                sine * math.cos(phi),
                cosine,
                sine * math.sin(phi),
                segment / float(segments),
                ring / float(rings),
            )
    bottom_index = len(vertex_data) // VERTEX_STRIDE
    append_vertex(0.0, -1.0, 0.0, 0.5, 1.0)

    index_values: list[int] = []
    first_ring = 1
    for segment in range(segments):
        next_segment = segment + 1
        index_values.extend((
            0,
            first_ring + next_segment,
            first_ring + segment,
        ))
    for ring in range(1, rings - 1):
        current = 1 + (ring - 1) * ring_vertex_count
        next_ring = current + ring_vertex_count
        for segment in range(segments):
            next_segment = segment + 1
            top_left = current + segment
            top_right = current + next_segment
            bottom_left = next_ring + segment
            bottom_right = next_ring + next_segment
            index_values.extend((
                top_left,
                bottom_left,
                top_right,
                top_right,
                bottom_left,
                bottom_right,
            ))
    last_ring = 1 + (rings - 2) * ring_vertex_count
    for segment in range(segments):
        next_segment = segment + 1
        index_values.extend((
            last_ring + segment,
            last_ring + next_segment,
            bottom_index,
        ))

    geometry = QQuick3DGeometry()
    geometry.setObjectName("gameLowPolySphereGeometry")
    geometry.setStride(VERTEX_STRIDE)
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.PositionSemantic,
        0,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.NormalSemantic,
        12,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.TexCoordSemantic,
        24,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.IndexSemantic,
        0,
        QQuick3DGeometry.Attribute.U16Type,
    )
    geometry.setVertexData(bytes(vertex_data))
    geometry.setIndexData(struct.pack("<%dH" % len(index_values), *index_values))
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    geometry.setBounds(
        QVector3D(-radius, -radius, -radius),
        QVector3D(radius, radius, radius),
    )
    return geometry


def _append_face(
    vertex_data: bytearray,
    index_values: list[int],
    positions: tuple[tuple[float, float, float], ...],
    normal: tuple[float, float, float],
    color: tuple[float, float, float, float],
) -> None:
    """Append one flat-shaded triangle or quad to a colored asset mesh."""
    start = len(vertex_data) // ASSET_VERTEX_STRIDE
    for position in positions:
        _append_vertex(
            vertex_data,
            position,
            normal,
            color=color,
        )
    if len(positions) == 3:
        index_values.extend((start, start + 1, start + 2))
    elif len(positions) == 4:
        index_values.extend(
            (start, start + 1, start + 2, start, start + 2, start + 3)
        )


def _append_cylinder_y(
    vertex_data: bytearray,
    index_values: list[int],
    center_y: float,
    height: float,
    bottom_radius: float,
    top_radius: float,
    color: tuple[float, float, float, float],
    *,
    segments: int = 8,
    center_x: float = 0.0,
    center_z: float = 0.0,
) -> None:
    """Append a Gouraud-shaded vertical cylinder/cone with real cap geometry.

    Side vertices share radial normals so trunks and posts read as clay
    tubes instead of octagonal crystals.  Caps stay flat.  Optional
    ``center_x`` / ``center_z`` place stilts and poles off the origin.
    """
    segments = max(6, int(segments))
    cx = float(center_x)
    cz = float(center_z)
    bottom_y = center_y - height * 0.5
    top_y = center_y + height * 0.5
    bottom_start = len(vertex_data) // ASSET_VERTEX_STRIDE
    for segment in range(segments):
        angle = math.tau * segment / float(segments)
        nx = math.cos(angle)
        nz = math.sin(angle)
        _append_vertex(
            vertex_data,
            (cx + bottom_radius * nx, bottom_y, cz + bottom_radius * nz),
            (nx, 0.0, nz),
            color=color,
        )
    top_start = len(vertex_data) // ASSET_VERTEX_STRIDE
    for segment in range(segments):
        angle = math.tau * segment / float(segments)
        nx = math.cos(angle)
        nz = math.sin(angle)
        _append_vertex(
            vertex_data,
            (cx + top_radius * nx, top_y, cz + top_radius * nz),
            (nx, 0.0, nz),
            color=color,
        )
    for segment in range(segments):
        next_segment = (segment + 1) % segments
        index_values.extend(
            (
                bottom_start + segment,
                top_start + segment,
                bottom_start + next_segment,
                bottom_start + next_segment,
                top_start + segment,
                top_start + next_segment,
            )
        )

    for y, radius, normal, reverse in (
        (bottom_y, bottom_radius, (0.0, -1.0, 0.0), True),
        (top_y, top_radius, (0.0, 1.0, 0.0), False),
    ):
        center_index = len(vertex_data) // ASSET_VERTEX_STRIDE
        _append_vertex(vertex_data, (cx, y, cz), normal, color=color)
        ring_start = len(vertex_data) // ASSET_VERTEX_STRIDE
        for segment in range(segments):
            angle = math.tau * segment / float(segments)
            _append_vertex(
                vertex_data,
                (cx + radius * math.cos(angle), y, cz + radius * math.sin(angle)),
                normal,
                color=color,
            )
        for segment in range(segments):
            current = ring_start + segment
            following = ring_start + (segment + 1) % segments
            if reverse:
                index_values.extend((center_index, following, current))
            else:
                index_values.extend((center_index, current, following))


def _append_torus_y(
    vertex_data: bytearray,
    index_values: list[int],
    center_y: float,
    major_radius: float,
    tube_radius: float,
    color: tuple[float, float, float, float],
    *,
    major_segments: int = 10,
    tube_segments: int = 4,
) -> None:
    """Append a compact ring around the Y axis for readable metal/clay trim."""
    major_segments = max(6, int(major_segments))
    tube_segments = max(3, int(tube_segments))
    start = len(vertex_data) // ASSET_VERTEX_STRIDE
    for major in range(major_segments):
        u = math.tau * major / float(major_segments)
        for tube in range(tube_segments):
            v = math.tau * tube / float(tube_segments)
            radial = major_radius + tube_radius * math.cos(v)
            position = (
                radial * math.cos(u),
                center_y + tube_radius * math.sin(v),
                radial * math.sin(u),
            )
            normal = (
                math.cos(v) * math.cos(u),
                math.sin(v),
                math.cos(v) * math.sin(u),
            )
            _append_vertex(vertex_data, position, normal, color=color)
    for major in range(major_segments):
        next_major = (major + 1) % major_segments
        for tube in range(tube_segments):
            next_tube = (tube + 1) % tube_segments
            current = start + major * tube_segments + tube
            right = start + next_major * tube_segments + tube
            upper = start + next_major * tube_segments + next_tube
            left = start + major * tube_segments + next_tube
            index_values.extend((current, right, upper, current, upper, left))


def _append_bipyramid_y(
    vertex_data: bytearray,
    index_values: list[int],
    center_y: float,
    height: float,
    radius: float,
    color: tuple[float, float, float, float],
    highlight: tuple[float, float, float, float] | None = None,
    *,
    center_x: float = 0.0,
    center_z: float = 0.0,
    segments: int = 6,
) -> None:
    """Append a faceted crystal with a deliberately small triangle budget."""
    segments = max(4, int(segments))
    top = (center_x, center_y + height * 0.5, center_z)
    bottom = (center_x, center_y - height * 0.5, center_z)
    highlight = highlight or color
    for segment in range(segments):
        angle = math.tau * segment / float(segments)
        next_angle = math.tau * (segment + 1) / float(segments)
        current = (
            center_x + radius * math.cos(angle),
            center_y,
            center_z + radius * math.sin(angle),
        )
        following = (
            center_x + radius * math.cos(next_angle),
            center_y,
            center_z + radius * math.sin(next_angle),
        )
        mid_angle = (angle + next_angle) * 0.5
        top_normal = (0.42 * math.cos(mid_angle), 0.88, 0.42 * math.sin(mid_angle))
        bottom_normal = (0.42 * math.cos(mid_angle), -0.88, 0.42 * math.sin(mid_angle))
        _append_face(vertex_data, index_values, (top, following, current), top_normal, highlight)
        _append_face(vertex_data, index_values, (bottom, current, following), bottom_normal, color)


def _append_tapered_blade_y(
    vertex_data: bytearray,
    index_values: list[int],
    bottom_y: float,
    shoulder_y: float,
    tip_y: float,
    width: float,
    depth: float,
    color: tuple[float, float, float, float],
    highlight: tuple[float, float, float, float],
) -> None:
    """Append a shallow, pointed blade instead of a rectangular weapon block."""
    base = (
        (-width, bottom_y, -depth),
        (width, bottom_y, -depth),
        (width, bottom_y, depth),
        (-width, bottom_y, depth),
    )
    shoulder = (
        (-width * 0.82, shoulder_y, -depth * 0.78),
        (width * 0.82, shoulder_y, -depth * 0.78),
        (width * 0.82, shoulder_y, depth * 0.78),
        (-width * 0.82, shoulder_y, depth * 0.78),
    )
    _append_face(vertex_data, index_values, (base[0], base[1], base[2], base[3]), (0.0, -1.0, 0.0), color)
    for index in range(4):
        following = (index + 1) % 4
        normal = (
            (base[index][0] + base[following][0]) * 0.5,
            0.18,
            (base[index][2] + base[following][2]) * 0.5,
        )
        length = math.sqrt(sum(component * component for component in normal)) or 1.0
        normal = tuple(component / length for component in normal)
        _append_face(
            vertex_data,
            index_values,
            (base[index], base[following], shoulder[following], shoulder[index]),
            normal,
            color if index != 0 else highlight,
        )
    tip = (0.0, tip_y, 0.0)
    for index in range(4):
        following = (index + 1) % 4
        _append_face(
            vertex_data,
            index_values,
            (shoulder[index], shoulder[following], tip),
            (0.0, 0.86, 0.0),
            highlight if index in (0, 1) else color,
        )


def _append_wedge(
    vertex_data: bytearray,
    index_values: list[int],
    half_x: float,
    bottom_y: float,
    top_y: float,
    half_z: float,
    color: tuple[float, float, float, float],
    highlight: tuple[float, float, float, float],
) -> None:
    """Append a sloped ramp/roof prism with a non-box silhouette."""
    a = (-half_x, bottom_y, -half_z)
    b = (half_x, bottom_y, -half_z)
    c = (half_x, bottom_y, half_z)
    d = (-half_x, bottom_y, half_z)
    e = (-half_x, top_y, half_z)
    f = (half_x, top_y, half_z)
    _append_face(vertex_data, index_values, (a, d, c, b), (0.0, -1.0, 0.0), color)
    _append_face(vertex_data, index_values, (a, b, f, e), (0.0, 0.55, -0.83), highlight)
    _append_face(vertex_data, index_values, (d, e, f, c), (0.0, 0.0, 1.0), color)
    _append_face(vertex_data, index_values, (a, e, d), (-1.0, 0.0, 0.0), color)
    _append_face(vertex_data, index_values, (b, c, f), (1.0, 0.0, 0.0), color)


def _build_colored_geometry(
    object_name: str,
    vertex_data: bytearray,
    index_values: list[int],
) -> QQuick3DGeometry:
    """Finalize one cached native asset geometry with the shared color ABI."""
    if not vertex_data or not index_values:
        raise ValueError("colored asset geometry cannot be empty")
    vertex_count = len(vertex_data) // ASSET_VERTEX_STRIDE
    if vertex_count > 65535:
        raise ValueError("colored asset geometry exceeds U16 index budget")
    positions = [
        struct.unpack_from("<3f", vertex_data, index * ASSET_VERTEX_STRIDE)
        for index in range(vertex_count)
    ]
    minimum = tuple(min(position[axis] for position in positions) for axis in range(3))
    maximum = tuple(max(position[axis] for position in positions) for axis in range(3))
    geometry = QQuick3DGeometry()
    geometry.setObjectName(object_name)
    geometry.setStride(ASSET_VERTEX_STRIDE)
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.PositionSemantic,
        0,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.NormalSemantic,
        12,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.ColorSemantic,
        24,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.IndexSemantic,
        0,
        QQuick3DGeometry.Attribute.U16Type,
    )
    geometry.setVertexData(bytes(vertex_data))
    geometry.setIndexData(struct.pack("<%dH" % len(index_values), *index_values))
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    geometry.setBounds(
        QVector3D(*minimum),
        QVector3D(*maximum),
    )
    return geometry


def _asset_mesh_palette() -> dict[str, tuple[float, float, float, float]]:
    """Return the muted, vertex-colored clay palette used by every asset family."""
    return {
        "wood": (0.42, 0.22, 0.12, 1.0),
        "wood_light": (0.65, 0.38, 0.18, 1.0),
        "metal": (0.32, 0.42, 0.52, 1.0),
        "metal_light": (0.58, 0.68, 0.72, 1.0),
        "leather": (0.36, 0.15, 0.09, 1.0),
        "cloth": (0.10, 0.34, 0.32, 1.0),
        "cloth_light": (0.22, 0.52, 0.45, 1.0),
        "coral": (0.82, 0.34, 0.34, 1.0),
        "gold": (0.86, 0.58, 0.18, 1.0),
        "gold_light": (0.98, 0.80, 0.34, 1.0),
        "green": (0.34, 0.72, 0.28, 1.0),
        "green_dark": (0.18, 0.46, 0.16, 1.0),
        "leaf": (0.46, 0.78, 0.28, 1.0),
        "violet": (0.52, 0.34, 0.76, 1.0),
        "glow": (0.46, 0.78, 0.86, 1.0),
        "bone": (0.72, 0.68, 0.50, 1.0),
        "dark": (0.07, 0.055, 0.075, 1.0),
    }


def _build_saber_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_tapered_blade_y(
        vertices, indices, -0.08, 0.50, 0.66, 0.085, 0.025,
        palette["metal"], palette["metal_light"],
    )
    _append_box(vertices, indices, (0.0, -0.16, 0.0), (0.16, 0.026, 0.055), color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_cylinder_y(vertices, indices, -0.36, 0.38, 0.045, 0.052, palette["leather"], segments=7)
    _append_ellipsoid(vertices, indices, (0.0, -0.57, 0.0), (0.08, 0.07, 0.08), segments=6, rings=2, color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetIronSaber", vertices, indices)


def _build_axe_geometry(asset_id: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    legendary = "tidebreaker" in asset_id.lower()
    _append_cylinder_y(vertices, indices, -0.02, 0.88, 0.045, 0.058, palette["wood_light"], segments=7)
    _append_box(vertices, indices, (0.13, 0.27, 0.0), (0.16 if legendary else 0.13, 0.18, 0.035), color=palette["gold"] if legendary else palette["metal"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (0.0, 0.46, 0.0), (0.09, 0.06, 0.07), segments=6, rings=2, color=palette["metal_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (0.0, -0.47, 0.0), (0.07, 0.055, 0.07), segments=6, rings=2, color=palette["leather"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetAxe", vertices, indices)


def _build_bow_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_box(vertices, indices, (0.0, 0.0, 0.0), (0.035, 0.09, 0.045), color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (-0.11, 0.31, 0.0), (0.055, 0.27, 0.045), segments=6, rings=2, rotation_x=-0.22, color=palette["wood"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (0.11, 0.31, 0.0), (0.055, 0.27, 0.045), segments=6, rings=2, rotation_x=0.22, color=palette["wood"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_box(vertices, indices, (0.0, 0.30, -0.012), (0.012, 0.28, 0.012), color=palette["metal_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetDriftwoodBow", vertices, indices)


def _build_shield_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_ellipsoid(vertices, indices, (0.0, 0.0, 0.0), (0.42, 0.46, 0.10), segments=8, rings=3, color=palette["metal"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_torus_y(vertices, indices, 0.0, 0.31, 0.035, palette["gold"], major_segments=10, tube_segments=4)
    _append_bipyramid_y(vertices, indices, 0.0, 0.24, 0.09, palette["gold"], palette["gold_light"], segments=5)
    return _build_colored_geometry("gameAssetBuckler", vertices, indices)


def _build_wearable_geometry(asset_id: str, item_kind: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    lower = asset_id.lower()
    if "cloak" in lower:
        _append_ellipsoid(vertices, indices, (0.0, -0.02, 0.04), (0.40, 0.55, 0.10), segments=8, rings=3, color=palette["cloth"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_box(vertices, indices, (0.0, 0.40, -0.02), (0.22, 0.045, 0.06), color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    elif "boot" in lower or "feet" in item_kind.lower():
        _append_box(vertices, indices, (-0.13, -0.06, -0.05), (0.13, 0.28, 0.17), color=palette["leather"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (0.0, -0.25, -0.13), (0.20, 0.10, 0.26), segments=6, rings=2, color=palette["leather"], vertex_stride=ASSET_VERTEX_STRIDE)
    elif "glove" in lower or "hands" in item_kind.lower():
        for x in (-0.20, 0.20):
            _append_ellipsoid(vertices, indices, (x, 0.0, 0.0), (0.15, 0.20, 0.12), segments=6, rings=2, color=palette["cloth_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    else:
        _append_ellipsoid(vertices, indices, (0.0, 0.0, 0.0), (0.42, 0.50, 0.27), segments=8, rings=3, color=palette["cloth"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (-0.33, 0.18, 0.0), (0.14, 0.18, 0.16), segments=6, rings=2, color=palette["cloth_light"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (0.33, 0.18, 0.0), (0.14, 0.18, 0.16), segments=6, rings=2, color=palette["cloth_light"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_box(vertices, indices, (0.0, -0.18, -0.27), (0.29, 0.04, 0.025), color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetWearable", vertices, indices)


def _build_compass_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_torus_y(vertices, indices, 0.0, 0.30, 0.045, palette["gold"], major_segments=10, tube_segments=4)
    _append_ellipsoid(vertices, indices, (0.0, 0.0, 0.0), (0.27, 0.035, 0.27), segments=8, rings=2, color=palette["glow"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_box(vertices, indices, (0.0, 0.045, 0.0), (0.21, 0.018, 0.025), color=palette["coral"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetCompass", vertices, indices)


def _build_plant_geometry(asset_id: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_cylinder_y(vertices, indices, -0.02, 0.54, 0.025, 0.018, palette["green"], segments=5)
    for x, z, rotation in ((-0.10, 0.0, -0.45), (0.10, 0.02, 0.45), (0.0, 0.06, 0.0)):
        _append_ellipsoid(vertices, indices, (x, 0.20, z), (0.12, 0.035, 0.06), segments=5, rings=2, rotation_x=rotation, color=palette["green"], vertex_stride=ASSET_VERTEX_STRIDE)
    if "seed" in asset_id.lower():
        _append_bipyramid_y(vertices, indices, 0.0, 0.20, 0.08, palette["coral"], palette["gold"], segments=5)
    return _build_colored_geometry("gameAssetPlant", vertices, indices)


def _build_crystal_geometry(asset_id: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    lower = asset_id.lower()
    primary = palette["violet"] if any(token in lower for token in ("moon", "void", "amethyst", "umbra")) else palette["glow"]
    if "coral" in lower:
        primary = palette["coral"]
    if "bone" in lower or "fang" in lower:
        primary = palette["bone"]
    vertices = bytearray()
    indices: list[int] = []
    _append_bipyramid_y(vertices, indices, 0.0, 0.64, 0.22, primary, palette["gold_light"], segments=6)
    return _build_colored_geometry("gameAssetCrystal", vertices, indices)


def _build_gem_geometry(asset_id: str) -> QQuick3DGeometry:
    """Build a jewel with a belt and crown instead of a generic shard."""
    palette = _asset_mesh_palette()
    lower = asset_id.lower()
    primary = palette["glow"]
    if "ruby" in lower or "coral" in lower:
        primary = palette["coral"]
    elif "emerald" in lower or "wild" in lower:
        primary = palette["green"]
    elif "amethyst" in lower or "sapphire" in lower or "storm" in lower:
        primary = palette["violet"] if "amethyst" in lower else palette["glow"]
    elif "onyx" in lower or "void" in lower:
        primary = palette["dark"]
    vertices = bytearray()
    indices: list[int] = []
    _append_bipyramid_y(
        vertices, indices, 0.0, 0.48, 0.25, primary,
        palette["gold_light"], segments=6,
    )
    _append_torus_y(
        vertices, indices, -0.02, 0.18, 0.018,
        palette["metal_light"], major_segments=8, tube_segments=3,
    )
    return _build_colored_geometry("gameAssetGem", vertices, indices)


def _build_rune_geometry(asset_id: str) -> QQuick3DGeometry:
    """Build a compact rune tablet with a raised central sigil."""
    palette = _asset_mesh_palette()
    lower = asset_id.lower()
    stone = palette["violet"] if any(
        token in lower for token in ("umbra", "vex", "void")
    ) else palette["bone"]
    vertices = bytearray()
    indices: list[int] = []
    _append_cylinder_y(
        vertices, indices, -0.04, 0.12, 0.22, 0.20, stone, segments=6,
    )
    _append_bipyramid_y(
        vertices, indices, 0.08, 0.22, 0.075,
        palette["gold"], palette["gold_light"], segments=5,
    )
    _append_torus_y(
        vertices, indices, -0.04, 0.16, 0.018,
        palette["metal_light"], major_segments=8, tube_segments=3,
    )
    return _build_colored_geometry("gameAssetRune", vertices, indices)


def _build_key_geometry() -> QQuick3DGeometry:
    """Build a readable key with a ring, shaft and two teeth."""
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_torus_y(
        vertices, indices, -0.34, 0.13, 0.035,
        palette["gold"], major_segments=9, tube_segments=4,
    )
    _append_cylinder_y(
        vertices, indices, -0.04, 0.48, 0.045, 0.055,
        palette["gold_light"], segments=7,
    )
    _append_box(
        vertices, indices, (0.0, 0.20, 0.0), (0.10, 0.035, 0.055),
        color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE,
    )
    for x in (-0.07, 0.07):
        _append_box(
            vertices, indices, (x, 0.30, 0.0), (0.025, 0.08, 0.055),
            color=palette["gold_light"], vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameAssetTidegateKey", vertices, indices)


def _build_enchant_scroll_geometry() -> QQuick3DGeometry:
    """Rolled parchment, two timber spindles and a raised violet wax seal."""
    vertices = bytearray()
    indices: list[int] = []
    paper = (.84, .71, .48, 1.)
    wood = (.42, .22, .12, 1.)
    _append_box(vertices, indices, (0., 0., 0.), (.24, .30, .014), color=paper, vertex_stride=ASSET_VERTEX_STRIDE)
    _append_cylinder_y(vertices, indices, 0., .68, .042, .042, wood, segments=8, center_x=-.24)
    _append_cylinder_y(vertices, indices, 0., .68, .042, .042, wood, segments=8, center_x=.24)
    _append_ellipsoid(vertices, indices, (0., -.08, .038), (.07, .07, .024),
        segments=8, rings=3, color=(.52,.22,.72,1.), vertex_stride=ASSET_VERTEX_STRIDE)
    for line in range(4):
        _append_box(vertices, indices, (0., .20-line*.06, .018), (.16,.006,.004),
            color=(.30,.17,.11,1.), vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry('gameAssetEnchantScroll', vertices, indices)


def _build_consumable_geometry(asset_id: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    if "fish" in asset_id.lower() or "ration" in asset_id.lower():
        _append_ellipsoid(vertices, indices, (0.0, 0.0, 0.0), (0.36, 0.16, 0.16), segments=8, rings=3, color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (0.28, 0.0, 0.0), (0.12, 0.13, 0.15), segments=6, rings=2, color=palette["bone"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_box(vertices, indices, (0.0, 0.0, -0.17), (0.28, 0.025, 0.025), color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    else:
        _append_cylinder_y(vertices, indices, -0.02, 0.48, 0.16, 0.13, palette["coral"], segments=8)
        _append_cylinder_y(vertices, indices, 0.28, 0.10, 0.09, 0.09, palette["gold"], segments=7)
        _append_ellipsoid(vertices, indices, (0.0, -0.27, 0.0), (0.17, 0.05, 0.17), segments=7, rings=2, color=palette["wood"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetConsumable", vertices, indices)


def _build_crown_geometry(asset_id: str) -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    metal = palette["coral"] if "circlet" in asset_id.lower() else palette["gold"]
    _append_torus_y(vertices, indices, -0.08, 0.28, 0.045, metal, major_segments=9, tube_segments=4)
    for index in range(5):
        angle = math.tau * index / 5.0
        _append_bipyramid_y(
            vertices, indices, 0.12 + (0.045 if index % 2 else 0.0), 0.30, 0.065,
            metal, palette["gold_light"], segments=5,
            center_x=0.22 * math.cos(angle),
            center_z=0.22 * math.sin(angle),
        )
    return _build_colored_geometry("gameAssetCrown", vertices, indices)


def _build_totem_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_cylinder_y(vertices, indices, -0.05, 0.72, 0.09, 0.12, palette["wood"], segments=7)
    _append_ellipsoid(vertices, indices, (0.0, 0.43, 0.0), (0.23, 0.24, 0.20), segments=7, rings=3, color=palette["coral"], vertex_stride=ASSET_VERTEX_STRIDE)
    for x in (-0.075, 0.075):
        _append_ellipsoid(vertices, indices, (x, 0.48, -0.185), (0.028, 0.035, 0.018), segments=5, rings=2, color=palette["gold_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_torus_y(vertices, indices, -0.37, 0.13, 0.025, palette["gold"], major_segments=8, tube_segments=3)
    return _build_colored_geometry("gameAssetGoblinTotem", vertices, indices)


def _build_lantern_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_cylinder_y(vertices, indices, -0.92, 1.55, 0.055, 0.07, palette["wood"], segments=12)
    _append_box(
        vertices, indices, (0.0, -0.92, 0.0), (0.16, 0.05, 0.16),
        color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.0, 0.58, 0.0), (0.16, 0.18, 0.16),
        color=palette["metal"], vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_ellipsoid(
        vertices, indices, (0.0, 0.58, 0.0), (0.12, 0.14, 0.12),
        segments=7, rings=2, color=palette["gold_light"],
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_torus_y(
        vertices, indices, 0.74, 0.13, 0.025, palette["metal_light"],
        major_segments=8, tube_segments=3,
    )
    return _build_colored_geometry("gameAssetLantern", vertices, indices)


def _build_chest_geometry() -> QQuick3DGeometry:
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_box(vertices, indices, (0.0, -0.18, 0.0), (0.44, 0.25, 0.34), color=palette["wood"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (0.0, 0.14, 0.0), (0.44, 0.22, 0.34), segments=8, rings=2, color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    for x in (-0.31, 0.31):
        _append_box(vertices, indices, (x, -0.18, -0.35), (0.035, 0.27, 0.025), color=palette["metal"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_box(vertices, indices, (0.0, -0.16, -0.37), (0.08, 0.10, 0.035), color=palette["gold"], vertex_stride=ASSET_VERTEX_STRIDE)
    _append_ellipsoid(vertices, indices, (0.0, -0.12, -0.41), (0.035, 0.045, 0.018), segments=6, rings=2, color=palette["gold_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    return _build_colored_geometry("gameAssetSupplyChest", vertices, indices)


def build_item_geometry(asset_id: Any, item_kind: Any = "ITEM") -> QQuick3DGeometry:
    """Build one original clay-style item mesh from the stable asset id."""
    wanted = str(asset_id or "item.unknown").strip().lower()
    kind = str(item_kind or "ITEM").strip().upper()
    if kind == "CONTAINER" or any(token in wanted for token in ("crate", "cache", "reliquary", "chest")):
        return _build_chest_geometry()
    if "key" in wanted:
        return _build_key_geometry()
    if any(token in wanted for token in ("saber", "sword")):
        return _build_saber_geometry()
    if "hatchet" in wanted or "axe" in wanted:
        return _build_axe_geometry(wanted)
    if "bow" in wanted:
        return _build_bow_geometry()
    if any(token in wanted for token in ("buckler", "shield")):
        return _build_shield_geometry()
    if any(token in wanted for token in ("crown", "circlet")):
        return _build_crown_geometry(wanted)
    if any(token in wanted for token in ("vest", "jacket", "mail", "cloak", "glove", "boot")) or kind == "ARMOR":
        return _build_wearable_geometry(wanted, kind)
    if "enchant_scroll" in wanted:
        return _build_enchant_scroll_geometry()
    if "compass" in wanted:
        return _build_compass_geometry()
    if "lantern" in wanted:
        return _build_lantern_geometry()
    if "totem" in wanted:
        return _build_totem_geometry()
    if any(token in wanted for token in ("herb", "seed")):
        return _build_plant_geometry(wanted)
    if any(token in wanted for token in ("ration", "fish", "tonic")):
        return _build_consumable_geometry(wanted)
    if "rune" in wanted or kind == "RUNE":
        return _build_rune_geometry(wanted)
    if "gem" in wanted or kind == "GEM":
        return _build_gem_geometry(wanted)
    if any(token in wanted for token in ("shard", "pearl", "fragment", "relic", "fang", "rune", "gem", "heart")) or kind in {"MATERIAL", "RUNE", "GEM", "TRINKET"}:
        return _build_crystal_geometry(wanted)
    return _build_crystal_geometry(wanted)


def _build_palm_geometry() -> QQuick3DGeometry:
    """Sandover palm: a readable trunk with an umbrella crown, not a leaf wall.

    Local Y is -1 at the ground and +1 at the crown so entity ``sy`` is
    half-height in metres.  Fronds stay near the top and stick outward.
    A tall XZ scale must not turn them into a hedge that hides the village.
    """
    trunk = (0.52, 0.32, 0.12, 1.0)
    trunk_ring = (0.64, 0.40, 0.16, 1.0)
    # Sandover reads lime from the 18 m camera. Dark greens collapse to a
    # black asterisk. Keep the crown at the top and let the blades hang.
    frond_a = (0.46, 0.78, 0.22, 1.0)
    frond_b = (0.62, 0.86, 0.28, 1.0)
    frond_c = (0.34, 0.68, 0.18, 1.0)
    heart = (0.40, 0.72, 0.20, 1.0)
    coconut = (0.58, 0.34, 0.10, 1.0)
    coconut_gold = (0.86, 0.58, 0.16, 1.0)
    vertices = bytearray()
    indices: list[int] = []
    _append_ellipsoid(
        vertices, indices, (0.0, -0.98, 0.0), (0.12, 0.05, 0.12),
        segments=8, rings=3, color=trunk, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_cylinder_y(
        vertices, indices, -0.92, 0.22, 0.085, 0.062, trunk, segments=12
    )
    _append_cylinder_y(
        vertices, indices, 0.18, 0.62, 0.062, 0.040, trunk, segments=12
    )
    for ring_y, radius in ((-0.62, 0.078), (-0.18, 0.068), (0.22, 0.052)):
        _append_torus_y(
            vertices, indices, ring_y, radius, 0.014, trunk_ring,
            major_segments=10, tube_segments=3,
        )
    _append_ellipsoid(
        vertices, indices, (0.0, 0.68, 0.0), (0.09, 0.10, 0.09),
        segments=8, rings=4, color=heart, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    for index in range(10):
        yaw = math.tau * index / 10.0
        color = (frond_a, frond_b, frond_c)[index % 3]
        _append_ellipsoid(
            vertices, indices,
            (0.22 * math.sin(yaw), 0.58, 0.22 * math.cos(yaw)),
            (0.09, 0.032, 0.48),
            segments=10, rings=4, rotation_x=1.05, yaw=yaw,
            color=color, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for index in range(6):
        yaw = math.tau * index / 6.0 + 0.28
        _append_ellipsoid(
            vertices, indices,
            (0.12 * math.sin(yaw), 0.72, 0.12 * math.cos(yaw)),
            (0.07, 0.026, 0.28),
            segments=8, rings=3, rotation_x=0.72, yaw=yaw,
            color=frond_b, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for offset, color in (
        ((-0.07, 0.58, 0.05), coconut),
        ((0.08, 0.57, 0.04), coconut_gold),
        ((0.0, 0.56, -0.08), coconut),
    ):
        _append_ellipsoid(
            vertices, indices, offset, (0.045, 0.05, 0.045),
            segments=6, rings=3, color=color, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldPalm", vertices, indices)


def _build_stilt_hut_geometry(variant: int = 0) -> QQuick3DGeometry:
    """Enterable stilt house: deck matches the thatch, posts on the edge.

    Local Y is -1 at the ground and +1 at the ridge.  The door is a hole.
    Walk collision uses the same layout in ``game_engine_assets``.
    """
    palette = _asset_mesh_palette()
    variant = int(variant) % 4
    roof_palettes = (
        ((0.72, 0.27, 0.13, 1.0), (0.49, 0.16, 0.09, 1.0), (0.88, 0.43, 0.20, 1.0)),
        ((0.78, 0.39, 0.16, 1.0), (0.54, 0.23, 0.10, 1.0), (0.92, 0.58, 0.24, 1.0)),
        ((0.60, 0.34, 0.15, 1.0), (0.39, 0.22, 0.11, 1.0), (0.78, 0.49, 0.20, 1.0)),
        ((0.76, 0.24, 0.12, 1.0), (0.48, 0.14, 0.09, 1.0), (0.94, 0.42, 0.16, 1.0)),
    )
    thatch, thatch_dark, thatch_tip = roof_palettes[variant]
    plaster = (0.88, 0.73, 0.52, 1.0)
    mat_col = (
        (0.48, 0.19, 0.12, 1.0),
        (0.20, 0.39, 0.34, 1.0),
        (0.42, 0.29, 0.14, 1.0),
        (0.44, 0.20, 0.12, 1.0),
    )[variant]
    wood = palette["wood"]
    wood_light = palette["wood_light"]
    wood_dark = (0.28, 0.14, 0.07, 1.0)
    vertices = bytearray()
    indices: list[int] = []
    deck_hx, deck_hz = 1.005, 0.870
    room_hx, room_hz = 0.625, 0.516
    wall_t = 0.038
    door_half = 0.261
    deck_y = -0.359
    wall_mid, wall_hy = 0.065, 0.413
    posts = (
        (-deck_hx + 0.065, -deck_hz + 0.065),
        (0.0, -deck_hz + 0.065),
        (deck_hx - 0.065, -deck_hz + 0.065),
        (-deck_hx + 0.065, 0.0),
        (deck_hx - 0.065, 0.0),
        (-deck_hx + 0.065, deck_hz - 0.065),
        (0.0, deck_hz - 0.065),
        (deck_hx - 0.065, deck_hz - 0.065),
    )
    for x, z in posts:
        _append_cylinder_y(
            vertices, indices, -0.679, 0.641, 0.054, 0.046, wood,
            segments=10, center_x=x, center_z=z,
        )
        _append_box(
            vertices, indices, (x, -0.337, z), (0.065, 0.022, 0.065),
            color=wood_dark, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for index in range(9):
        plank_z = -deck_hz + 0.087 + index * (deck_hz * 2.0 - 0.174) / 8.0
        _append_box(
            vertices, indices, (0.0, deck_y, plank_z), (0.984, 0.019, 0.076),
            color=wood_light if index % 2 == 0 else wood,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    _append_box(
        vertices, indices, (0.0, wall_mid, room_hz),
        (room_hx + wall_t, wall_hy, wall_t),
        color=plaster, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (-room_hx, wall_mid, 0.0),
        (wall_t, wall_hy, room_hz),
        color=plaster, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (room_hx, wall_mid, 0.0),
        (wall_t, wall_hy, room_hz),
        color=plaster, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    wing = (room_hx - door_half) * 0.5
    _append_box(
        vertices, indices, (-door_half - wing, wall_mid, -room_hz),
        (wing + wall_t, wall_hy, wall_t),
        color=plaster, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (door_half + wing, wall_mid, -room_hz),
        (wing + wall_t, wall_hy, wall_t),
        color=plaster, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (-door_half, wall_mid, -room_hz),
        (0.022, wall_hy, 0.027),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (door_half, wall_mid, -room_hz),
        (0.022, wall_hy, 0.027),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.0, 0.445, -room_hz),
        (door_half + 0.022, 0.033, 0.027),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.0, -0.343, -room_hz - 0.043),
        (door_half + 0.033, 0.016, 0.054),
        color=wood_dark, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (room_hx + 0.011, 0.114, 0.190),
        (0.016, 0.076, 0.087),
        color=(0.12, 0.26, 0.25, 1.0), vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.082, -0.337, 0.054),
        (0.299, 0.011, 0.217),
        color=mat_col, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    roof_layers = (
        (
            (0.400, 0.120, 0.910, 0.800, thatch_dark, 16),
            (0.522, 0.150, 0.820, 0.640, thatch, 16),
            (0.660, 0.160, 0.660, 0.430, thatch_dark, 14),
            (0.790, 0.160, 0.450, 0.230, thatch, 12),
            (0.900, 0.110, 0.250, 0.040, thatch_tip, 8),
        ),
        (
            (0.360, 0.100, 0.970, 0.850, thatch_dark, 16),
            (0.475, 0.120, 0.850, 0.650, thatch, 16),
            (0.600, 0.130, 0.660, 0.450, thatch_dark, 14),
            (0.725, 0.125, 0.470, 0.225, thatch, 12),
            (0.840, 0.100, 0.240, 0.035, thatch_tip, 8),
        ),
        (
            (0.390, 0.115, 0.880, 0.760, thatch_dark, 16),
            (0.520, 0.155, 0.790, 0.620, thatch, 16),
            (0.665, 0.170, 0.630, 0.420, thatch_dark, 14),
            (0.810, 0.170, 0.440, 0.210, thatch, 12),
            (0.935, 0.105, 0.225, 0.035, thatch_tip, 8),
        ),
        (
            (0.400, 0.115, 0.920, 0.780, thatch_dark, 16),
            (0.530, 0.145, 0.800, 0.620, thatch, 16),
            (0.665, 0.145, 0.640, 0.420, thatch_dark, 14),
            (0.790, 0.145, 0.430, 0.210, thatch, 12),
            (0.910, 0.110, 0.230, 0.035, thatch_tip, 8),
        ),
    )[variant]
    for center_y, height, r0, r1, color, segs in roof_layers:
        _append_cylinder_y(
            vertices, indices, center_y, height, r0, r1, color, segments=segs,
        )
    # The shared room/deck/collision footprint stays identical, while these
    # hand-built details give each resident hut its own readable silhouette.
    trim = (0.30, 0.16, 0.09, 1.0)
    if variant == 1:
        for x in (-0.43, 0.43):
            _append_box(
                vertices, indices, (x, 0.06, -room_hz - 0.047),
                (0.105, 0.19, 0.035),
                color=(0.16, 0.36, 0.36, 1.0),
                vertex_stride=ASSET_VERTEX_STRIDE,
            )
        _append_box(
            vertices, indices, (0.0, 0.50, -room_hz - 0.115),
            (0.38, 0.025, 0.12),
            color=wood_light,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    elif variant == 2:
        for x in (-0.51, 0.51):
            _append_box(
                vertices, indices, (x, 0.40, -room_hz - 0.06),
                (0.035, 0.055, 0.07),
                color=(0.93, 0.72, 0.32, 1.0),
                vertex_stride=ASSET_VERTEX_STRIDE,
            )
        _append_ellipsoid(
            vertices, indices, (0.0, 0.88, 0.0), (0.10, 0.08, 0.10),
            segments=8, rings=3, color=(0.94, 0.70, 0.28, 1.0),
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    elif variant == 3:
        for x in (-0.72, 0.72):
            _append_box(
                vertices, indices, (x, -0.045, -0.18),
                (0.20, 0.025, 0.44),
                color=(0.84, 0.62, 0.34, 1.0),
                vertex_stride=ASSET_VERTEX_STRIDE,
            )
        _append_box(
            vertices, indices, (0.0, 0.10, -room_hz - 0.07),
            (0.31, 0.04, 0.035),
            color=(0.32, 0.18, 0.11, 1.0),
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    _append_box(
        vertices, indices, (0.0, -0.130, deck_hz - 0.022),
        (0.924, 0.019, 0.016),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (-0.571, -0.130, -deck_hz + 0.022),
        (0.391, 0.019, 0.016),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.571, -0.130, -deck_hz + 0.022),
        (0.391, 0.019, 0.016),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (-deck_hx + 0.022, -0.130, 0.082),
        (0.016, 0.019, 0.680),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (deck_hx - 0.022, -0.130, 0.082),
        (0.016, 0.019, 0.680),
        color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_cylinder_y(
        vertices, indices, -0.641, 0.533, 0.014, 0.014, wood,
        segments=6, center_x=-0.087, center_z=-0.967,
    )
    _append_cylinder_y(
        vertices, indices, -0.641, 0.533, 0.014, 0.014, wood,
        segments=6, center_x=0.087, center_z=-0.967,
    )
    for step_y in (-0.902, -0.772, -0.641, -0.511, -0.391):
        _append_box(
            vertices, indices, (0.0, step_y, -0.967), (0.098, 0.011, 0.014),
            color=wood_light, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry(
        "gameWorldStiltHut" if variant == 0 else "gameWorldStiltHut_%d" % variant,
        vertices,
        indices,
    )


def _build_dock_geometry() -> QQuick3DGeometry:
    """Sandover pier: plank deck, fat pilings, open-water bollard.

    The deck uses the existing half-height anchor while the pilings continue
    below local -1 into the shallow seabed. Length lives in Z on purpose; do
    not stretch a cube into a pier.
    """
    palette = _asset_mesh_palette()
    wood = palette["wood"]
    wood_light = palette["wood_light"]
    wood_dark = (0.28, 0.14, 0.07, 1.0)
    vertices = bytearray()
    indices: list[int] = []
    for index in range(9):
        plank_z = -3.03 + index * 0.74
        color = wood_light if index % 2 == 0 else wood
        _append_box(
            vertices, indices, (0.0, -0.38, plank_z), (1.07, 0.067, 0.33),
            color=color, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for pile_z in (-2.81, -0.88, 1.04, 2.82):
        for pile_x in (-0.86, 0.86):
            _append_cylinder_y(
                vertices, indices, -1.37, 2.06, 0.09, 0.08, wood_dark,
                segments=8, center_x=pile_x, center_z=pile_z,
            )
    for beam_z in (-1.84, 0.23, 2.01):
        _append_box(
            vertices, indices, (0.0, -0.56, beam_z), (0.92, 0.074, 0.10),
            color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for rail_x in (-1.04, 1.04):
        _append_box(
            vertices, indices, (rail_x, 0.07, -0.88), (0.05, 0.06, 2.00),
            color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
        )
        for post_z in (-2.59, -0.88, 0.82):
            _append_cylinder_y(
                vertices, indices, 0.07, 0.89, 0.04, 0.04, wood,
                segments=6, center_x=rail_x, center_z=post_z,
            )
    _append_cylinder_y(
        vertices, indices, 0.0, 2.0, 0.11, 0.09, wood,
        segments=10, center_z=3.12,
    )
    _append_cylinder_y(
        vertices, indices, 0.44, 0.10, 0.16, 0.16, palette["gold"],
        segments=10, center_x=-0.05, center_z=3.12,
    )
    _append_box(
        vertices, indices, (0.42, -0.08, -2.36), (0.27, 0.24, 0.33),
        color=wood_dark, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.42, 0.18, -2.36), (0.30, 0.04, 0.36),
        color=wood_light, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    return _build_colored_geometry("gameWorldDock", vertices, indices)


def _build_windmill_geometry() -> QQuick3DGeometry:
    """Small stucco coastal windmill with four readable cloth sails."""
    vertices = bytearray()
    indices: list[int] = []
    plaster = (0.82, 0.70, 0.49, 1.0)
    roof = (0.68, 0.22, 0.10, 1.0)
    roof_light = (0.86, 0.39, 0.17, 1.0)
    timber = (0.34, 0.19, 0.11, 1.0)
    canvas = (0.87, 0.76, 0.56, 1.0)
    canvas_warm = (0.79, 0.52, 0.30, 1.0)
    _append_cylinder_y(
        vertices, indices, -0.245, 1.49, 0.39, 0.235, plaster, segments=12,
    )
    _append_cylinder_y(
        vertices, indices, 0.515, 0.16, 0.285, 0.16, roof, segments=12,
    )
    _append_cylinder_y(
        vertices, indices, 0.625, 0.12, 0.18, 0.025, roof_light, segments=10,
    )
    _append_box(
        vertices, indices, (0.0, -0.47, -0.238), (0.105, 0.31, 0.028),
        color=timber, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.0, -0.91, 0.0), (0.47, 0.055, 0.43),
        color=timber, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    hub_y = 0.485
    hub_z = 0.282
    for blade_index in range(4):
        angle = math.tau * blade_index / 4.0 + math.pi / 4.0
        axis_x, axis_y = math.cos(angle), math.sin(angle)
        side_x, side_y = -axis_y, axis_x
        root_radius, tip_radius = 0.105, 0.735
        root_width, tip_width = 0.042, 0.135
        positions = (
            (axis_x * root_radius + side_x * root_width,
             hub_y + axis_y * root_radius + side_y * root_width, hub_z),
            (axis_x * root_radius - side_x * root_width,
             hub_y + axis_y * root_radius - side_y * root_width, hub_z),
            (axis_x * tip_radius - side_x * tip_width,
             hub_y + axis_y * tip_radius - side_y * tip_width, hub_z),
            (axis_x * tip_radius + side_x * tip_width,
             hub_y + axis_y * tip_radius + side_y * tip_width, hub_z),
        )
        _append_face(
            vertices,
            indices,
            positions,
            (0.0, 0.0, 1.0),
            canvas if blade_index % 2 == 0 else canvas_warm,
        )
        spar_positions = (
            (axis_x * 0.06 + side_x * 0.018,
             hub_y + axis_y * 0.06 + side_y * 0.018, hub_z + 0.014),
            (axis_x * 0.06 - side_x * 0.018,
             hub_y + axis_y * 0.06 - side_y * 0.018, hub_z + 0.014),
            (axis_x * 0.79 - side_x * 0.018,
             hub_y + axis_y * 0.79 - side_y * 0.018, hub_z + 0.014),
            (axis_x * 0.79 + side_x * 0.018,
             hub_y + axis_y * 0.79 + side_y * 0.018, hub_z + 0.014),
        )
        _append_face(
            vertices,
            indices,
            spar_positions,
            (0.0, 0.0, 1.0),
            timber,
        )
    _append_ellipsoid(
        vertices,
        indices,
        (0.0, hub_y, hub_z + 0.035),
        (0.13, 0.13, 0.09),
        segments=8,
        rings=4,
        color=roof_light,
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    return _build_colored_geometry("gameWorldWindmill", vertices, indices)


def _build_path_geometry() -> QQuick3DGeometry:
    """Thin irregular sandstone segment for the village footpath."""
    vertices = bytearray()
    indices: list[int] = []
    stones = (
        ((0.0, -0.970, -0.69), (0.92, 0.030, 0.25), (0.68, 0.51, 0.32, 1.0)),
        ((0.0, -0.970, 0.00), (0.96, 0.030, 0.27), (0.77, 0.61, 0.39, 1.0)),
        ((0.0, -0.970, 0.69), (0.90, 0.030, 0.25), (0.68, 0.51, 0.32, 1.0)),
    )
    for center, half_size, color in stones:
        _append_box(
            vertices,
            indices,
            center,
            half_size,
            color=color,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldPath", vertices, indices)


def _build_mangrove_geometry(variant: int = 0) -> QQuick3DGeometry:
    """Fallback for the authored mangrove: exposed roots and a lobed crown."""
    palette = _asset_mesh_palette()
    variant = int(variant) % 4
    vertices = bytearray()
    indices: list[int] = []
    trunk = (0.40, 0.25, 0.13, 1.0)
    leaf_colors = (
        (palette["leaf"], palette["green"], palette["green_dark"]),
        (palette["green"], (0.55, 0.73, 0.31, 1.0), palette["leaf"]),
        ((0.28, 0.55, 0.22, 1.0), palette["leaf"], (0.44, 0.65, 0.25, 1.0)),
        (palette["green_dark"], palette["green"], (0.61, 0.75, 0.34, 1.0)),
    )[variant]
    _append_cylinder_y(
        vertices, indices, -0.26, 1.48, 0.12, 0.095, trunk, segments=12,
    )
    for angle in (0.2, 2.1, 4.2):
        dx, dz = math.cos(angle), math.sin(angle)
        _append_cylinder_y(
            vertices,
            indices,
            -0.74,
            0.55,
            0.035,
            0.022,
            palette["wood_light"],
            segments=7,
            center_x=dx * 0.23,
            center_z=dz * 0.23,
        )
    lobes = (
        (-0.36, 0.44, -0.12, 0.43, 0.37, 0.40),
        (0.08, 0.57, 0.13, 0.50, 0.43, 0.46),
        (0.42, 0.38, -0.08, 0.38, 0.34, 0.37),
        (-0.08, 0.77, 0.03, 0.34, 0.31, 0.32),
    )
    for index, (x, y, z, rx, ry, rz) in enumerate(lobes):
        _append_ellipsoid(
            vertices,
            indices,
            (x, y, z),
            (rx, ry, rz),
            segments=12,
            rings=6,
            rotation_x=(-0.12, 0.16, -0.20, 0.08)[index],
            yaw=0.24 * variant,
            color=leaf_colors[index % len(leaf_colors)],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldMangroveFallback", vertices, indices)


def _build_rock_geometry(variant: int = 0) -> QQuick3DGeometry:
    """36 authored coastal rock silhouettes, cached by stable world identity."""
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/world/rocks'/f'rock-{int(variant)%36:02d}.ggmesh'
    if path.is_file():
        data=path.read_bytes();magic,stride,nv,ni=struct.unpack_from('<8sIII',data)
        if magic!=b'GGFLORA1' or stride!=40 or nv>10000 or ni>30000:raise ValueError('Invalid authored rock mesh')
        end=20+nv*stride
        if len(data)!=end+ni*4:raise ValueError('Truncated authored rock mesh')
        return _build_colored_geometry('gameWorldRockCluster_%d'%int(variant),bytearray(data[20:end]),list(struct.unpack_from('<'+str(ni)+'I',data,end)))
    variant = int(variant) % 4
    vertices = bytearray()
    indices: list[int] = []
    shadow = (0.36, 0.27, 0.23, 1.0)
    mid = (0.58, 0.38, 0.25, 1.0)
    sun = (0.78, 0.54, 0.32, 1.0)
    gray = (0.48, 0.42, 0.34, 1.0)
    if variant == 0:
        forms = (
            (-0.30, -0.65, 0.02, (0.70, 0.35, 0.62), gray),
            (0.18, -0.48, -0.04, (0.48, 0.50, 0.48), mid),
            (-0.08, -0.08, 0.08, (0.39, 0.62, 0.40), sun),
            (0.53, -0.68, 0.15, (0.34, 0.30, 0.42), shadow),
        )
    elif variant == 1:
        forms = (
            (-0.52, -0.70, 0.02, (0.46, 0.31, 0.55), mid),
            (0.00, -0.54, -0.12, (0.62, 0.42, 0.63), sun),
            (0.48, -0.68, 0.12, (0.42, 0.32, 0.47), gray),
            (0.13, -0.17, -0.02, (0.32, 0.45, 0.34), shadow),
        )
    elif variant == 2:
        forms = (
            (-0.24, -0.67, 0.12, (0.74, 0.33, 0.55), shadow),
            (0.29, -0.45, -0.12, (0.48, 0.51, 0.46), mid),
            (-0.10, -0.16, -0.02, (0.40, 0.47, 0.38), sun),
            (0.30, 0.11, -0.02, (0.24, 0.24, 0.25), gray),
        )
    else:
        forms = (
            (-0.42, -0.70, -0.06, (0.48, 0.31, 0.47), gray),
            (0.28, -0.62, 0.10, (0.55, 0.40, 0.67), shadow),
            (-0.04, -0.23, 0.04, (0.51, 0.55, 0.45), mid),
            (0.02, 0.20, 0.05, (0.33, 0.40, 0.34), sun),
        )
    for index, (x, y, z, radii, color) in enumerate(forms):
        _append_ellipsoid(
            vertices,
            indices,
            (x, y, z),
            radii,
            segments=9 if index < 2 else 8,
            rings=4,
            rotation_x=(0.09, -0.17, 0.13, -0.08)[index],
            yaw=0.37 * variant + 0.41 * index,
            color=color,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    # A few small exposed sandstone chips break the smooth boulder bases.
    for x, z, radius in ((-0.62, 0.36, 0.10), (0.58, -0.35, 0.08)):
        _append_ellipsoid(
            vertices,
            indices,
            (x, -0.88, z),
            (radius * 1.4, radius, radius),
            segments=6,
            rings=3,
            color=sun,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldRockCluster_%d" % variant, vertices, indices)


def _build_market_stall_geometry(variant: int = 0) -> QQuick3DGeometry:
    """A village vendor canopy, counter and legible wares at player scale."""
    variant = int(variant) % 4
    vertices = bytearray()
    indices: list[int] = []
    wood = (0.38, 0.22, 0.12, 1.0)
    timber = (0.61, 0.38, 0.20, 1.0)
    canvas = (
        ((0.88, 0.40, 0.19, 1.0), (0.95, 0.78, 0.48, 1.0)),
        ((0.19, 0.51, 0.47, 1.0), (0.93, 0.78, 0.50, 1.0)),
        ((0.75, 0.27, 0.17, 1.0), (0.97, 0.84, 0.58, 1.0)),
        ((0.31, 0.47, 0.28, 1.0), (0.89, 0.67, 0.35, 1.0)),
    )[variant]
    for x in (-0.70, 0.70):
        for z in (-0.54, 0.54):
            _append_cylinder_y(
                vertices,
                indices,
                -0.39,
                1.22,
                0.045,
                0.035,
                wood,
                segments=8,
                center_x=x,
                center_z=z,
            )
    _append_box(
        vertices, indices, (0.0, -0.20, 0.0), (0.78, 0.12, 0.61),
        color=timber, vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_box(
        vertices, indices, (0.0, -0.05, -0.015), (0.74, 0.025, 0.56),
        color=(0.80, 0.58, 0.34, 1.0),
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    # Alternating canopy panels give the roof a hand-sewn silhouette.
    for index in range(6):
        x = -0.59 + index * 0.236
        _append_box(
            vertices,
            indices,
            (x, 0.67, 0.0),
            (0.119, 0.075, 0.67),
            rotation_x=0.10 if index % 2 == 0 else -0.10,
            color=canvas[index % 2],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    _append_box(
        vertices, indices, (0.0, 0.57, -0.64), (0.71, 0.10, 0.07),
        color=canvas[0], vertex_stride=ASSET_VERTEX_STRIDE,
    )
    for index, (x, color) in enumerate(((-0.40, (0.90, 0.48, 0.22, 1.0)), (0.0, (0.90, 0.74, 0.31, 1.0)), (0.40, (0.30, 0.62, 0.52, 1.0)))):
        _append_ellipsoid(
            vertices,
            indices,
            (x, 0.10, -0.18),
            (0.16, 0.12, 0.14),
            segments=7,
            rings=3,
            color=color,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    _append_box(
        vertices, indices, (0.42, 0.32, -0.65), (0.18, 0.20, 0.035),
        color=canvas[1], vertex_stride=ASSET_VERTEX_STRIDE,
    )
    return _build_colored_geometry("gameWorldMarketStall_%d" % variant, vertices, indices)


def _build_fish_rack_geometry() -> QQuick3DGeometry:
    """A timber drying rack with a readable row of hanging fish."""
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    wood = (0.43, 0.27, 0.15, 1.0)
    for x in (-0.68, 0.68):
        _append_cylinder_y(
            vertices, indices, -0.24, 1.32, 0.052, 0.038, wood,
            segments=8, center_x=x,
        )
        _append_box(
            vertices, indices, (x * 0.68, -0.46, 0.0), (0.42, 0.035, 0.10),
            rotation_x=0.48 if x < 0 else -0.48,
            color=wood,
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for y in (0.26, 0.68):
        _append_box(
            vertices, indices, (0.0, y, 0.0), (0.74, 0.045, 0.045),
            color=palette["wood_light"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for index in range(5):
        x = -0.47 + index * 0.235
        y = 0.44 + (0.07 if index % 2 else 0.0)
        _append_cylinder_y(
            vertices, indices, y + 0.09, 0.18, 0.014, 0.012,
            palette["wood"], segments=5, center_x=x,
        )
        _append_ellipsoid(
            vertices,
            indices,
            (x, y - 0.05, -0.035),
            (0.115, 0.052, 0.045),
            segments=8,
            rings=3,
            yaw=0.10 if index % 2 else -0.10,
            color=(0.76, 0.49 + 0.04 * (index % 2), 0.25, 1.0),
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldFishRack", vertices, indices)


def _build_boat_geometry() -> QQuick3DGeometry:
    """A hand-shaped coastal skiff rather than another scaled box."""
    vertices = bytearray()
    indices: list[int] = []
    hull = (0.40, 0.20, 0.11, 1.0)
    hull_light = (0.72, 0.43, 0.23, 1.0)
    inner = (0.87, 0.66, 0.39, 1.0)
    lower = ((-0.12, -0.76, -0.92), (0.12, -0.76, -0.92), (0.14, -0.77, 0.84), (-0.14, -0.77, 0.84))
    upper = ((-0.56, -0.26, -0.60), (0.56, -0.26, -0.60), (0.50, -0.31, 0.65), (-0.50, -0.31, 0.65))
    _append_face(vertices, indices, (lower[0], lower[3], lower[2], lower[1]), (0.0, -1.0, 0.0), hull)
    for index in range(4):
        following = (index + 1) % 4
        _append_face(
            vertices,
            indices,
            (lower[index], lower[following], upper[following], upper[index]),
            (0.0, 0.68, -0.73) if index in (0, 2) else (1.0 if index == 1 else -1.0, 0.2, 0.0),
            hull_light if index % 2 == 0 else hull,
        )
    _append_face(vertices, indices, upper, (0.0, 1.0, 0.0), inner)
    for z in (-0.38, 0.28):
        _append_box(
            vertices, indices, (0.0, -0.20, z), (0.44, 0.045, 0.065),
            color=hull_light, vertex_stride=ASSET_VERTEX_STRIDE,
        )
    _append_cylinder_y(
        vertices, indices, -0.03, 0.94, 0.025, 0.025,
        (0.47, 0.30, 0.15, 1.0), segments=7, center_x=0.40, center_z=0.08,
    )
    _append_ellipsoid(
        vertices, indices, (0.41, 0.43, 0.10), (0.24, 0.025, 0.16),
        segments=6, rings=2, rotation_x=-0.12,
        color=(0.88, 0.74, 0.47, 1.0), vertex_stride=ASSET_VERTEX_STRIDE,
    )
    return _build_colored_geometry("gameWorldFishingSkiff", vertices, indices)


def _build_bridge_geometry() -> QQuick3DGeometry:
    """Plank boardwalk with timber rails for the sheltered cove approach."""
    vertices = bytearray()
    indices: list[int] = []
    wood = (0.40, 0.24, 0.14, 1.0)
    plank = (0.68, 0.43, 0.24, 1.0)
    for index in range(11):
        z = -0.95 + index * 0.19
        _append_box(
            vertices,
            indices,
            (0.0, -0.39 + 0.06 * math.cos(index * 0.52), z),
            (0.55, 0.052, 0.083),
            rotation_x=0.018 * math.sin(index * 0.8),
            color=plank if index % 3 else (0.76, 0.52, 0.30, 1.0),
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for x in (-0.50, 0.50):
        for z in (-0.92, -0.31, 0.31, 0.92):
            _append_cylinder_y(
                vertices, indices, -1.025, 2.95, 0.045, 0.038,
                wood, segments=7, center_x=x, center_z=z,
            )
        _append_box(
            vertices, indices, (x, 0.30, 0.0), (0.045, 0.045, 1.0),
            color=wood, vertex_stride=ASSET_VERTEX_STRIDE,
        )
        _append_box(
            vertices, indices, (x * 0.70, -0.34, 0.0), (0.10, 0.045, 1.0),
            color=(0.34, 0.20, 0.12, 1.0),
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldCoveBoardwalk", vertices, indices)


def _build_stone_steps_geometry() -> QQuick3DGeometry:
    """Sandstone steps and cheek stones used where the village path rises."""
    vertices = bytearray()
    indices: list[int] = []
    colors = (
        (0.68, 0.48, 0.31, 1.0),
        (0.78, 0.58, 0.38, 1.0),
        (0.57, 0.39, 0.27, 1.0),
    )
    for index in range(6):
        top = -0.80 + index * 0.27
        z = -0.70 + index * 0.27
        _append_box(
            vertices,
            indices,
            (0.0, top - 0.08, z),
            (0.62, 0.12, 0.27),
            color=colors[index % len(colors)],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    for x in (-0.60, 0.60):
        for index in range(3):
            _append_ellipsoid(
                vertices,
                indices,
                (x, -0.72 + index * 0.37, -0.42 + index * 0.37),
                (0.12, 0.18, 0.19),
                segments=7,
                rings=3,
                color=colors[(index + 1) % len(colors)],
                vertex_stride=ASSET_VERTEX_STRIDE,
            )
    return _build_colored_geometry("gameWorldSandstoneSteps", vertices, indices)


def _build_village_totem_geometry() -> QQuick3DGeometry:
    """Original stacked-face shrine pole, not a copy of another game's idol."""
    palette = _asset_mesh_palette()
    vertices = bytearray()
    indices: list[int] = []
    _append_cylinder_y(
        vertices, indices, -0.55, 0.55, 0.10, 0.12, palette["wood"], segments=8
    )
    _append_ellipsoid(
        vertices, indices, (0.0, -0.05, 0.0), (0.22, 0.20, 0.20),
        segments=10, rings=5, color=palette["coral"],
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_ellipsoid(
        vertices, indices, (0.0, 0.32, 0.0), (0.18, 0.18, 0.18),
        segments=10, rings=5, color=palette["gold"],
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    _append_ellipsoid(
        vertices, indices, (0.0, 0.58, 0.0), (0.12, 0.14, 0.12),
        segments=8, rings=4, color=palette["leaf"],
        vertex_stride=ASSET_VERTEX_STRIDE,
    )
    for x in (-0.08, 0.08):
        _append_ellipsoid(
            vertices, indices, (x, 0.0, -0.18), (0.03, 0.035, 0.02),
            segments=6, rings=3, color=palette["gold_light"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    return _build_colored_geometry("gameWorldTotem", vertices, indices)


_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BIN_CHUNK = 0x004E4942
_GLTF_FLOAT = 5126
_GLTF_UNSIGNED_SHORT = 5123
_GLTF_UNSIGNED_INT = 5125
_GLTF_VEC3 = "VEC3"
_GLTF_SCALAR = "SCALAR"
_GLTF_TYPE_SIZE = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT4": 16,
}
_GLTF_COMPONENT_SIZE = {
    5120: 1,
    5121: 1,
    5122: 2,
    5123: 2,
    5125: 4,
    5126: 4,
}


def _mat4_identity() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _mat4_mul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [
            sum(left[row][k] * right[k][col] for k in range(4))
            for col in range(4)
        ]
        for row in range(4)
    ]


def _mat4_from_node(node: dict[str, Any]) -> list[list[float]]:
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 16:
        try:
            values = [float(value) for value in matrix]
        except (TypeError, ValueError):
            values = []
        if len(values) == 16:
            return [
                [values[0], values[4], values[8], values[12]],
                [values[1], values[5], values[9], values[13]],
                [values[2], values[6], values[10], values[14]],
                [values[3], values[7], values[11], values[15]],
            ]
    result = _mat4_identity()
    translation = node.get("translation")
    if isinstance(translation, list) and len(translation) >= 3:
        try:
            tx, ty, tz = (float(translation[0]), float(translation[1]), float(translation[2]))
        except (TypeError, ValueError):
            tx, ty, tz = (0.0, 0.0, 0.0)
        moved = _mat4_identity()
        moved[0][3] = tx
        moved[1][3] = ty
        moved[2][3] = tz
        result = _mat4_mul(result, moved)
    rotation = node.get("rotation")
    if isinstance(rotation, list) and len(rotation) >= 4:
        try:
            qx, qy, qz, qw = (
                float(rotation[0]),
                float(rotation[1]),
                float(rotation[2]),
                float(rotation[3]),
            )
        except (TypeError, ValueError):
            qx, qy, qz, qw = (0.0, 0.0, 0.0, 1.0)
        xx, yy, zz = qx * qx, qy * qy, qz * qz
        xy, xz, yz = qx * qy, qx * qz, qy * qz
        wx, wy, wz = qw * qx, qw * qy, qw * qz
        rotated = [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), 0.0],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), 0.0],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        result = _mat4_mul(result, rotated)
    scale = node.get("scale")
    if isinstance(scale, list) and len(scale) >= 3:
        try:
            sx, sy, sz = (float(scale[0]), float(scale[1]), float(scale[2]))
        except (TypeError, ValueError):
            sx, sy, sz = (1.0, 1.0, 1.0)
        scaled = _mat4_identity()
        scaled[0][0] = sx
        scaled[1][1] = sy
        scaled[2][2] = sz
        result = _mat4_mul(result, scaled)
    return result


def _mat4_transform_point(
    matrix: list[list[float]],
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def _mat4_transform_dir(
    matrix: list[list[float]],
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    dx = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z
    dy = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z
    dz = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (dx / length, dy / length, dz / length)


def _glb_chunks(source: bytes) -> tuple[dict[str, Any], bytes] | None:
    if len(source) < 20:
        return None
    try:
        magic, version, declared = struct.unpack_from("<4sII", source, 0)
    except struct.error:
        return None
    if magic != b"glTF" or version != 2 or declared > len(source):
        return None
    offset = 12
    document: dict[str, Any] | None = None
    blob = b""
    while offset + 8 <= declared:
        try:
            chunk_length, chunk_type = struct.unpack_from("<II", source, offset)
        except struct.error:
            return None
        offset += 8
        end = offset + chunk_length
        if end > declared or end > len(source):
            return None
        payload = source[offset:end]
        offset = end
        if chunk_type == _GLB_JSON_CHUNK:
            try:
                parsed = json.loads(payload.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if isinstance(parsed, dict):
                document = parsed
        elif chunk_type == _GLB_BIN_CHUNK:
            blob = payload
    if document is None:
        return None
    return document, blob


def _gltf_accessor_bytes(
    document: dict[str, Any],
    blob: bytes,
    index: Any,
) -> tuple[bytes, int, int, int] | None:
    accessors = document.get("accessors")
    views = document.get("bufferViews")
    if not isinstance(accessors, list) or not isinstance(views, list):
        return None
    try:
        accessor = accessors[int(index)]
        view = views[int(accessor.get("bufferView", -1))]
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
    if not isinstance(accessor, dict) or not isinstance(view, dict):
        return None
    try:
        count = int(accessor.get("count", 0))
        component_type = int(accessor.get("componentType", 0))
        view_offset = int(view.get("byteOffset", 0))
        accessor_offset = int(accessor.get("byteOffset", 0))
        view_length = int(view.get("byteLength", 0))
    except (TypeError, ValueError):
        return None
    type_name = str(accessor.get("type", _GLTF_SCALAR))
    components = _GLTF_TYPE_SIZE.get(type_name, 0)
    component_size = _GLTF_COMPONENT_SIZE.get(component_type, 0)
    if count <= 0 or components <= 0 or component_size <= 0:
        return None
    stride = int(view.get("byteStride") or 0) or (components * component_size)
    start = view_offset + accessor_offset
    needed = start + stride * (count - 1) + components * component_size
    if start < 0 or needed > len(blob) or needed - view_offset > view_length + accessor_offset:
        if start < 0 or start + count * components * component_size > len(blob):
            return None
        stride = components * component_size
        needed = start + count * stride
        if needed > len(blob):
            return None
    return blob[start:needed], count, stride, component_type


def _gltf_positions(
    document: dict[str, Any],
    blob: bytes,
    index: Any,
) -> list[tuple[float, float, float]] | None:
    unpacked = _gltf_accessor_bytes(document, blob, index)
    if unpacked is None:
        return None
    payload, count, stride, component_type = unpacked
    if component_type != _GLTF_FLOAT:
        return None
    positions: list[tuple[float, float, float]] = []
    for row in range(count):
        offset = row * stride
        try:
            x, y, z = struct.unpack_from("<3f", payload, offset)
        except struct.error:
            return None
        positions.append((float(x), float(y), float(z)))
    return positions


def _gltf_indices(
    document: dict[str, Any],
    blob: bytes,
    index: Any,
) -> list[int] | None:
    unpacked = _gltf_accessor_bytes(document, blob, index)
    if unpacked is None:
        return None
    payload, count, stride, component_type = unpacked
    indices: list[int] = []
    for row in range(count):
        offset = row * stride
        try:
            if component_type == _GLTF_UNSIGNED_SHORT:
                value = struct.unpack_from("<H", payload, offset)[0]
            elif component_type == _GLTF_UNSIGNED_INT:
                value = struct.unpack_from("<I", payload, offset)[0]
            else:
                return None
        except struct.error:
            return None
        indices.append(int(value))
    return indices


def _gltf_material_color(
    document: dict[str, Any],
    index: Any,
) -> tuple[float, float, float, float]:
    materials = document.get("materials")
    default = (0.46, 0.28, 0.12, 1.0)
    if not isinstance(materials, list):
        return default
    try:
        material = materials[int(index)]
    except (TypeError, ValueError, IndexError):
        return default
    if not isinstance(material, dict):
        return default
    pbr = material.get("pbrMetallicRoughness")
    factor = pbr.get("baseColorFactor") if isinstance(pbr, dict) else None
    if not isinstance(factor, list) or len(factor) < 3:
        return default
    try:
        red, green, blue = float(factor[0]), float(factor[1]), float(factor[2])
        alpha = float(factor[3]) if len(factor) > 3 else 1.0
    except (TypeError, ValueError):
        return default
    return (
        max(0.0, min(1.0, red)),
        max(0.0, min(1.0, green)),
        max(0.0, min(1.0, blue)),
        max(0.0, min(1.0, alpha)),
    )


def mesh_column_stamp(path: Any, columns: int = 8) -> dict[str, Any] | None:
    """Bin one authored GLB into a coarse height-and-color stamp.

    The DOS presentation reads this stamp instead of inventing a second
    silhouette.  Vertices stay in the same node space the low-poly loader
    uses.  Files large enough to be a terrain or planet mesh are skipped.
    """
    file_path = path if isinstance(path, Path) else Path(str(path or ""))
    try:
        if not file_path.is_file() or file_path.stat().st_size > 4_000_000:
            return None
        parsed = _glb_chunks(file_path.read_bytes())
    except OSError:
        return None
    if parsed is None:
        return None
    document, blob = parsed
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    if not isinstance(nodes, list) or not isinstance(meshes, list):
        return None
    scenes = document.get("scenes")
    scene_index = document.get("scene", 0)
    try:
        scene = scenes[int(scene_index)] if isinstance(scenes, list) else None
    except (TypeError, ValueError, IndexError):
        scene = None
    roots = scene.get("nodes") if isinstance(scene, dict) else None
    if not isinstance(roots, list) or not roots:
        roots = list(range(len(nodes)))

    samples: list[tuple[float, float, float, float, float, float]] = []
    sample_budget = 12000

    def emit_mesh(mesh_index: int, matrix: list[list[float]]) -> None:
        if len(samples) >= sample_budget:
            return
        try:
            mesh = meshes[int(mesh_index)]
        except (TypeError, ValueError, IndexError):
            return
        if not isinstance(mesh, dict):
            return
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list):
            return
        for primitive in primitives:
            if len(samples) >= sample_budget or not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict):
                continue
            positions = _gltf_positions(document, blob, attributes.get("POSITION"))
            if not positions:
                continue
            red, green, blue, _alpha = _gltf_material_color(
                document,
                primitive.get("material"),
            )
            step = max(1, len(positions) // max(1, sample_budget - len(samples)))
            for position in positions[::step]:
                world = _mat4_transform_point(matrix, *position)
                samples.append((world[0], world[1], world[2], red, green, blue))
                if len(samples) >= sample_budget:
                    break

    def walk(node_index: Any, parent: list[list[float]]) -> None:
        try:
            node = nodes[int(node_index)]
        except (TypeError, ValueError, IndexError):
            return
        if not isinstance(node, dict):
            return
        world = _mat4_mul(parent, _mat4_from_node(node))
        if "mesh" in node:
            emit_mesh(node.get("mesh"), world)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child, world)

    for root_index in roots:
        walk(root_index, _mat4_identity())
    if len(samples) < 3:
        return None
    min_x = min(sample[0] for sample in samples)
    max_x = max(sample[0] for sample in samples)
    min_y = min(sample[1] for sample in samples)
    max_y = max(sample[1] for sample in samples)
    min_z = min(sample[2] for sample in samples)
    max_z = max(sample[2] for sample in samples)
    span_x = max(max_x - min_x, 1e-4)
    span_z = max(max_z - min_z, 1e-4)
    count = max(2, min(12, int(columns)))
    height = [0.0] * (count * count)
    color_sum = [[0.0, 0.0, 0.0, 0.0] for _ in range(count * count)]
    for sample_x, sample_y, sample_z, red, green, blue in samples:
        ix = min(count - 1, int((sample_x - min_x) / span_x * count))
        iz = min(count - 1, int((sample_z - min_z) / span_z * count))
        index = iz * count + ix
        top = sample_y - min_y
        if top > height[index]:
            height[index] = top
        bucket = color_sum[index]
        bucket[0] += max(0.0, min(1.0, red))
        bucket[1] += max(0.0, min(1.0, green))
        bucket[2] += max(0.0, min(1.0, blue))
        bucket[3] += 1.0
    colors: list[str] = []
    for bucket in color_sum:
        if bucket[3] <= 0.0:
            colors.append("#000000")
            continue
        colors.append(
            "#{:02x}{:02x}{:02x}".format(
                int(bucket[0] / bucket[3] * 255.0),
                int(bucket[1] / bucket[3] * 255.0),
                int(bucket[2] / bucket[3] * 255.0),
            )
        )
    if max(height) <= 1e-4:
        return None
    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "min_z": min_z,
        "max_z": max_z,
        "nx": count,
        "nz": count,
        "height": [round(value, 4) for value in height],
        "color": colors,
    }


def _geometry_from_authored_world_glb(
    kind: str,
    variant: int = 0,
) -> QQuick3DGeometry | None:
    """Import one Blender world GLB into the shared native mesh cache.

    Play instantiates this mesh many times.  Decoding the file per tree
    through RuntimeLoader is what made the village hitch; the GLB stays the
    authored source, the runtime keeps one QQuick3DGeometry.
    """
    try:
        from backend.game_engine_assets import (
            AUTHORED_WORLD_SOURCES,
            AUTHORED_WORLD_VARIANTS,
        )
    except Exception:
        return None
    source_key = str(kind or "").strip().upper()
    variants = AUTHORED_WORLD_VARIANTS.get(source_key, ())
    if variants:
        try:
            spec = variants[int(variant) % len(variants)]
        except (TypeError, ValueError):
            spec = variants[0]
    else:
        spec = AUTHORED_WORLD_SOURCES.get(source_key)
    if not isinstance(spec, dict):
        return None
    source = spec.get("source")
    path = source if isinstance(source, Path) else Path(str(source or ""))
    if not path.is_file():
        return None
    try:
        parsed = _glb_chunks(path.read_bytes())
    except OSError:
        return None
    if parsed is None:
        return None
    document, blob = parsed
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    if not isinstance(nodes, list) or not isinstance(meshes, list):
        return None
    scenes = document.get("scenes")
    scene_index = document.get("scene", 0)
    try:
        scene = scenes[int(scene_index)] if isinstance(scenes, list) else None
    except (TypeError, ValueError, IndexError):
        scene = None
    roots = scene.get("nodes") if isinstance(scene, dict) else None
    if not isinstance(roots, list) or not roots:
        roots = list(range(len(nodes)))

    transformed: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float, float]]] = []
    triangles: list[tuple[int, int, int]] = []

    def emit_mesh(mesh_index: int, matrix: list[list[float]]) -> None:
        try:
            mesh = meshes[int(mesh_index)]
        except (TypeError, ValueError, IndexError):
            return
        if not isinstance(mesh, dict):
            return
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list):
            return
        for primitive in primitives:
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict):
                continue
            positions = _gltf_positions(document, blob, attributes.get("POSITION"))
            if not positions:
                continue
            normals = _gltf_positions(document, blob, attributes.get("NORMAL"))
            indices = _gltf_indices(document, blob, primitive.get("indices"))
            if not indices:
                continue
            color = _gltf_material_color(document, primitive.get("material"))
            base = len(transformed)
            for vertex_index, position in enumerate(positions):
                world = _mat4_transform_point(matrix, *position)
                if normals and vertex_index < len(normals):
                    normal = _mat4_transform_dir(matrix, *normals[vertex_index])
                else:
                    normal = (0.0, 1.0, 0.0)
                transformed.append((world, normal, color))
            for cursor in range(0, len(indices) - 2, 3):
                triangles.append(
                    (
                        base + indices[cursor],
                        base + indices[cursor + 1],
                        base + indices[cursor + 2],
                    )
                )

    def walk(node_index: Any, parent: list[list[float]]) -> None:
        try:
            node = nodes[int(node_index)]
        except (TypeError, ValueError, IndexError):
            return
        if not isinstance(node, dict):
            return
        world = _mat4_mul(parent, _mat4_from_node(node))
        if "mesh" in node:
            emit_mesh(node.get("mesh"), world)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child, world)

    for root_index in roots:
        walk(root_index, _mat4_identity())
    if not transformed or not triangles:
        return None
    if len(transformed) > 65535:
        return None

    min_x = min(point[0][0] for point in transformed)
    min_y = min(point[0][1] for point in transformed)
    min_z = min(point[0][2] for point in transformed)
    max_x = max(point[0][0] for point in transformed)
    max_y = max(point[0][1] for point in transformed)
    max_z = max(point[0][2] for point in transformed)
    height = max(max_y - min_y, 1e-4)
    scale = 2.0 / height
    mid_x = (min_x + max_x) * 0.5
    mid_z = (min_z + max_z) * 0.5
    vertices = bytearray()
    for position, normal, color in transformed:
        packed = struct.pack(
            "<10f",
            (position[0] - mid_x) * scale,
            (position[1] - min_y) * scale - 1.0,
            (position[2] - mid_z) * scale,
            normal[0],
            normal[1],
            normal[2],
            color[0],
            color[1],
            color[2],
            color[3],
        )
        vertices.extend(packed)
    indices = [index for triangle in triangles for index in triangle]
    if not vertices or not indices:
        return None
    return _build_colored_geometry("gameAuthoredWorld_%s" % kind.lower(), vertices, indices)


def _build_world_prop_geometry(kind: Any, variant: int = 0) -> QQuick3DGeometry | None:
    """Build a shared world-prop family with four deterministic visual variants."""
    palette = _asset_mesh_palette()
    wanted = str(kind or "PROP").strip().upper()
    variant = int(variant) % 4
    vertices = bytearray()
    indices: list[int] = []
    if "SETTLEMENT_ROADS" in wanted or "SETTLEMENT_FENCES" in wanted:
        from backend.game_engine_settlement import build_geometry
        return build_geometry(wanted)
    if "RAMP" in wanted:
        return _build_stone_steps_geometry()
    if "MANGROVE" in wanted:
        baked = _geometry_from_authored_world_glb("MANGROVE")
        if baked is not None:
            return baked
        return _build_mangrove_geometry(variant)
    if "PALM" in wanted or "TREE" in wanted:
        baked = _geometry_from_authored_world_glb("PALM")
        if baked is not None:
            return baked
        return _build_palm_geometry()
    if "TIDEHOUSE" not in wanted and any(
        token in wanted for token in ("HOUSE", "BUILDING", "STRUCTURE", "HUT")
    ):
        baked = _geometry_from_authored_world_glb("HOUSE", variant)
        if baked is not None:
            return baked
        return _build_stilt_hut_geometry(variant)
    if "ROCK" in wanted or "BOULDER" in wanted:
        return _build_rock_geometry(variant)
    if "DOCK" in wanted or "PIER" in wanted:
        baked = _geometry_from_authored_world_glb("DOCK")
        if baked is not None:
            return baked
        return _build_dock_geometry()
    if "WINDMILL" in wanted:
        baked = _geometry_from_authored_world_glb("WINDMILL")
        if baked is not None:
            return baked
        return _build_windmill_geometry()
    if "WATER_WHEEL" in wanted or "WATERWHEEL" in wanted:
        baked = _geometry_from_authored_world_glb("WATER_WHEEL")
        if baked is not None:
            return baked
    if "PATH" in wanted or "TRAIL" in wanted:
        return _build_path_geometry()
    if "BRIDGE" in wanted or "BOARDWALK" in wanted:
        return _build_bridge_geometry()
    if "FISH_RACK" in wanted or "FISHING_RACK" in wanted:
        return _build_fish_rack_geometry()
    if "MARKET" in wanted or "STALL" in wanted:
        return _build_market_stall_geometry(variant)
    if "BOAT" in wanted or "CANOE" in wanted:
        return _build_boat_geometry()
    if "TOTEM" in wanted or "SHRINE" in wanted:
        return _build_village_totem_geometry()
    if "TIDEHOUSE" in wanted:
        return _build_stilt_hut_geometry(variant)
    if "LIGHT" in wanted or "LANTERN" in wanted:
        return _build_lantern_geometry()
    if "SPAWN" in wanted:
        _append_torus_y(vertices, indices, -0.18, 0.34, 0.055, palette["violet"], major_segments=10, tube_segments=4)
        _append_cylinder_y(vertices, indices, -0.48, 0.70, 0.07, 0.10, palette["metal"], segments=7)
        return _build_colored_geometry("gameWorldSpawnMarker", vertices, indices)
    if "STRESS" in wanted:
        _append_ellipsoid(vertices, indices, (0.0, -0.48, 0.0), (0.42, 0.52, 0.36), segments=6, rings=3, color=palette["bone"], vertex_stride=ASSET_VERTEX_STRIDE)
        return _build_colored_geometry("gameWorldStressPebble", vertices, indices)
    if variant == 0:
        _append_ellipsoid(vertices, indices, (0.0, -0.48, 0.0), (0.48, 0.52, 0.40), segments=7, rings=3, color=palette["bone"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (0.18, -0.35, -0.16), (0.25, 0.30, 0.22), segments=6, rings=2, color=palette["metal_light"], vertex_stride=ASSET_VERTEX_STRIDE)
        _append_ellipsoid(vertices, indices, (-0.22, -0.62, 0.12), (0.22, 0.18, 0.20), segments=6, rings=2, color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE)
    elif variant == 1:
        # Readable mangrove: trunk, knee-roots and a stacked canopy so the
        # silhouette still works at the default 18 m third-person camera.
        # Canopy tessellation is higher because these instances are metres
        # tall; a 7-segment ellipsoid at 4 m reads as a crystal, not clay.
        _append_cylinder_y(vertices, indices, -0.92, 1.35, 0.11, 0.16, palette["wood"], segments=12)
        for x, z in ((-0.22, 0.18), (0.24, 0.12), (-0.08, -0.24)):
            _append_box(
                vertices, indices, (x, -0.78, z), (0.05, 0.22, 0.05),
                color=palette["wood_light"], vertex_stride=ASSET_VERTEX_STRIDE,
            )
        _append_ellipsoid(
            vertices, indices, (0.0, 0.42, 0.0), (0.62, 0.38, 0.58),
            segments=14, rings=7, color=palette["leaf"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
        _append_ellipsoid(
            vertices, indices, (-0.28, 0.18, 0.12), (0.38, 0.28, 0.34),
            segments=12, rings=6, color=palette["green"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
        _append_ellipsoid(
            vertices, indices, (0.30, 0.22, -0.10), (0.42, 0.30, 0.36),
            segments=12, rings=6, color=palette["green_dark"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
        _append_ellipsoid(
            vertices, indices, (0.04, 0.68, 0.08), (0.28, 0.22, 0.26),
            segments=10, rings=5, color=palette["leaf"],
            vertex_stride=ASSET_VERTEX_STRIDE,
        )
    elif variant == 2:
        _append_cylinder_y(vertices, indices, -0.86, 0.18, 0.36, 0.31, palette["metal"], segments=7)
        _append_cylinder_y(vertices, indices, -0.42, 0.72, 0.22, 0.15, palette["metal_light"], segments=6)
        _append_torus_y(vertices, indices, -0.76, 0.27, 0.03, palette["gold"], major_segments=8, tube_segments=3)
        _append_bipyramid_y(vertices, indices, 0.08, 0.40, 0.16, palette["coral"], palette["gold_light"], segments=5)
    else:
        _append_cylinder_y(vertices, indices, -0.58, 0.78, 0.28, 0.24, palette["wood_light"], segments=8)
        _append_torus_y(vertices, indices, -0.56, 0.27, 0.025, palette["metal"], major_segments=8, tube_segments=3)
        _append_torus_y(vertices, indices, -0.30, 0.27, 0.025, palette["metal"], major_segments=8, tube_segments=3)
    return _build_colored_geometry("gameWorldProp_%d" % variant, vertices, indices)


def preview_item_geometry(host,asset_id,item_kind,owner):
    """Reuse the mesh recipe with graphics objects owned by this preview window."""
    from PySide6.QtQuick import QQuickItem
    if not isinstance(owner,QQuickItem):return None
    caches=getattr(host,'_preview_item_geometry_caches',None)
    if caches is None:caches={};host._preview_item_geometry_caches=caches
    key=id(owner)
    if key not in caches:
        if len(caches)>=8:return None
        caches[key]=AssetGeometryCache(owner)
        owner.destroyed.connect(lambda *_:caches.pop(key,None))
    geometry=caches[key].geometry_for_item(asset_id,item_kind)
    if geometry.parent() is None:geometry.setParent(caches[key])
    from PySide6.QtQml import QQmlEngine
    QQmlEngine.setObjectOwnership(geometry,QQmlEngine.CppOwnership)
    return geometry


class AssetGeometryCache(QObject):
    """Keep one native mesh per bounded item/prop family, never per frame."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: dict[tuple[str, str], QQuick3DGeometry] = {}
        self._props: dict[tuple[str, int], QQuick3DGeometry] = {}

    @staticmethod
    def _safe_key(value: Any, fallback: str) -> str:
        wanted = str(value or fallback).strip().lower()
        return wanted[:96] or fallback

    def geometry_for_item(self, asset_id: Any, item_kind: Any = "ITEM") -> QQuick3DGeometry:
        key = (self._safe_key(asset_id, "item.unknown"), self._safe_key(item_kind, "ITEM"))
        geometry = self._items.get(key)
        if geometry is None:
            if len(self._items) >= MAX_ASSET_GEOMETRIES:
                # Unknown content shares a deterministic generic mesh once the
                # bounded native family cache is full.
                key = ("item.unknown", "ITEM")
                geometry = self._items.get(key)
            if geometry is None:
                geometry = build_item_geometry(*key)
                self._items[key] = geometry
        return geometry

    def geometry_for_world_prop(self, kind: Any = "PROP", variant: Any = 0) -> QQuick3DGeometry:
        safe_kind = self._safe_key(kind, "PROP").upper()
        original_kind = safe_kind
        # World asset bindings carry a semantic geometry key.  Keep the
        # numeric variant as a compatibility input for older snapshots, but
        # let the declared family win whenever it is present.
        family_aliases = {
            "WORLD.PROP.ROCK": ("ROCK", None),
            "WORLD.PROP.MANGROVE": ("MANGROVE", 0),
            "WORLD.PROP.SHRINE": ("TOTEM", 0),
            "WORLD.PROP.BARREL": ("PROP", 3),
        }
        alias = family_aliases.get(original_kind)
        if alias is not None:
            safe_kind, fixed_variant = alias
        else:
            fixed_variant = None
        safe_variant = 0
        variant_count=36 if 'ROCK' in safe_kind or 'BOULDER' in safe_kind else 4
        try:
            safe_variant = int(variant) % variant_count
        except (TypeError, ValueError):
            digits = "".join(character for character in str(variant) if character.isdigit())
            try:
                safe_variant = int(digits or "0") % variant_count
            except ValueError:
                safe_variant = 0
        if fixed_variant is not None:
            safe_variant = fixed_variant
        # Ramps and named structures have one shape; ordinary props are four
        # shared silhouettes selected by a stable entity variant.
        if any(
            token in safe_kind
            for token in (
                "RAMP",
                "PALM",
                "TREE",
                "DOCK",
                "TOTEM",
                "LIGHT",
                "LANTERN",
                "SPAWN",
                "STRESS",
            )
        ):
            safe_variant = 0
        key = (safe_kind, safe_variant)
        geometry = self._props.get(key)
        if geometry is None:
            if len(self._props) >= MAX_ASSET_GEOMETRIES:
                key = ("PROP", safe_variant)
                geometry = self._props.get(key)
            if geometry is None:
                geometry = _build_world_prop_geometry(*key)
                self._props[key] = geometry
        return geometry


def build_character_geometry(
    motion_state: Any = "IDLE",
    phase: Any = 0.0,
    variant: Any = "CROWD",
) -> QQuick3DGeometry:
    """Build the original GG clay-style crowd mesh in gameplay units.

    This is deliberately a single indexed geometry object, not a collection
    of QML Models.  The silhouette is assembled from a small number of
    faceted ellipsoids and boxes, while RGBA vertex colors separate skin,
    cloth, hair, boots and accent pieces without a texture lookup.  The
    resulting mesh is an actual 3D asset generated by the engine and can be
    replaced by an authored/retargeted asset later without changing the
    simulation contract.
    """
    pose_state, pose_bucket = character_pose_key(motion_state, phase)
    pose_phase = pose_bucket / float(CHARACTER_POSE_BUCKETS) * math.tau
    stride = math.sin(pose_phase) if pose_state in {"WALK", "SPRINT"} else 0.0
    swing = (
        0.38 if pose_state == "SPRINT" else 0.28
    ) * stride
    if pose_state == "AIR":
        # A small readable airborne spread; root pitch still comes from the
        # deterministic animation contract.
        swing = 0.22
    if pose_state == "IDLE":
        swing = 0.0

    # Jak/Sly/Fable clay: saturated local colors that still read when a
    # warm key light and a cool sky fill hit the same mesh.  Near-black
    # hair/boots crush to silhouettes under filmic tonemapping.
    cast = character_variant_key(variant)
    skin = (0.94, 0.62, 0.38, 1.0)
    skin_light = (0.99, 0.80, 0.54, 1.0)
    cloth = (0.16, 0.58, 0.52, 1.0)
    cloth_light = (0.32, 0.74, 0.58, 1.0)
    accent = (0.96, 0.50, 0.16, 1.0)
    belt = (0.52, 0.26, 0.12, 1.0)
    hair = (0.28, 0.14, 0.08, 1.0)
    boots = (0.36, 0.20, 0.12, 1.0)
    eyes = (0.10, 0.07, 0.05, 1.0)
    if cast == "WANDERER":
        cloth = (0.78, 0.52, 0.22, 1.0)
        cloth_light = (0.92, 0.70, 0.32, 1.0)
        accent = (0.22, 0.46, 0.58, 1.0)
        hair = (0.18, 0.10, 0.06, 1.0)
    elif cast == "GUARDIAN":
        cloth = (0.28, 0.36, 0.46, 1.0)
        cloth_light = (0.48, 0.56, 0.64, 1.0)
        accent = (0.82, 0.62, 0.22, 1.0)
        belt = (0.42, 0.40, 0.38, 1.0)
        boots = (0.22, 0.22, 0.24, 1.0)
        hair = (0.16, 0.16, 0.18, 1.0)
    elif cast == "CRITTER":
        cloth = (0.42, 0.58, 0.32, 1.0)
        cloth_light = (0.58, 0.72, 0.40, 1.0)
        accent = (0.86, 0.46, 0.28, 1.0)
        skin = (0.82, 0.52, 0.30, 1.0)
        skin_light = (0.92, 0.68, 0.42, 1.0)
        hair = (0.40, 0.22, 0.10, 1.0)

    vertex_data = bytearray()
    index_values: list[int] = []

    def ellipsoid(
        center: tuple[float, float, float],
        radius: tuple[float, float, float],
        color: tuple[float, float, float, float],
        *,
        segments: int = 8,
        rings: int = 3,
        rotation_x: float = 0.0,
    ) -> None:
        _append_ellipsoid(
            vertex_data,
            index_values,
            center,
            radius,
            segments=segments,
            rings=rings,
            rotation_x=rotation_x,
            color=color,
            vertex_stride=CHARACTER_VERTEX_STRIDE,
        )

    def box(
        center: tuple[float, float, float],
        half_size: tuple[float, float, float],
        color: tuple[float, float, float, float],
        *,
        rotation_x: float = 0.0,
    ) -> None:
        _append_box(
            vertex_data,
            index_values,
            center,
            half_size,
            rotation_x=rotation_x,
            color=color,
            vertex_stride=CHARACTER_VERTEX_STRIDE,
        )

    # Rounded torso and pelvis establish the exaggerated readable silhouette.
    # The overlap is intentional: it avoids a visible seam while the color
    # change reads as a short jacket over trousers.
    ellipsoid((0.0, 0.03, 0.0), (0.36, 0.38, 0.25), cloth, segments=12, rings=6)
    ellipsoid((0.0, -0.29, 0.0), (0.29, 0.16, 0.22), boots, segments=10, rings=4)
    box((0.0, -0.245, -0.225), (0.27, 0.052, 0.025), belt)
    box((0.0, 0.03, -0.252), (0.18, 0.16, 0.018), cloth_light)
    ellipsoid((0.0, 0.04, -0.274), (0.055, 0.065, 0.025), accent, segments=8, rings=3)

    # Neck, shoulders and hands make the pose legible even at the distant
    # crowd LOD.  The small shoulder pieces add character without requiring a
    # second clothing model or a normal map.
    ellipsoid((0.0, 0.39, 0.0), (0.115, 0.12, 0.12), skin, segments=8, rings=4)
    for x in (-0.32, 0.32):
        ellipsoid((x, 0.22, 0.0), (0.14, 0.11, 0.16), accent, segments=8, rings=4)

    for x in (-0.42, 0.42):
        arm_swing = -swing if x < 0.0 else swing
        ellipsoid(
            (x, 0.02, 0.0),
            (0.115, 0.255, 0.115),
            cloth_light,
            segments=8,
            rings=5,
            rotation_x=arm_swing,
        )
        ellipsoid(
            (x * 1.08, -0.205, -0.01),
            (0.105, 0.105, 0.105),
            skin_light,
            segments=8,
            rings=4,
            rotation_x=arm_swing,
        )

    for x in (-0.14, 0.14):
        leg_swing = swing if x < 0.0 else -swing
        ellipsoid(
            (x, -0.50, 0.0),
            (0.13, 0.235, 0.14),
            cloth,
            segments=8,
            rings=5,
            rotation_x=leg_swing,
        )
        ellipsoid(
            (x, -0.76, -0.06),
            (0.15, 0.095, 0.225),
            boots,
            segments=8,
            rings=4,
            rotation_x=leg_swing,
        )

    # Smooth Gouraud head: RenderWare-era clay, not a faceted icosahedron.
    ellipsoid((0.0, 0.59, 0.0), (0.235, 0.25, 0.225), skin_light, segments=12, rings=6)
    ellipsoid((0.0, 0.73, 0.018), (0.245, 0.14, 0.232), hair, segments=10, rings=4)
    for x in (-0.235, 0.235):
        ellipsoid((x, 0.59, 0.0), (0.045, 0.075, 0.075), skin, segments=8, rings=3)
    for x in (-0.082, 0.082):
        ellipsoid((x, 0.635, -0.219), (0.027, 0.032, 0.018), eyes, segments=8, rings=3)
    ellipsoid((0.0, 0.585, -0.226), (0.042, 0.050, 0.028), skin, segments=8, rings=3)
    ellipsoid((0.0, 0.835, 0.02), (0.115, 0.095, 0.11), hair, segments=8, rings=4)

    straw = (0.86, 0.62, 0.28, 1.0)
    iron = (0.46, 0.50, 0.56, 1.0)
    if cast == "WANDERER":
        ellipsoid((0.0, 0.84, 0.0), (0.34, 0.05, 0.34), straw, segments=10, rings=3)
        ellipsoid((0.0, 0.92, 0.0), (0.16, 0.09, 0.16), straw, segments=8, rings=3)
        ellipsoid((0.0, 0.06, 0.24), (0.13, 0.11, 0.11), straw, segments=8, rings=4)
    elif cast == "GUARDIAN":
        ellipsoid((0.0, 0.84, 0.02), (0.26, 0.12, 0.22), iron, segments=10, rings=4)
        box((0.0, 0.66, -0.18), (0.16, 0.05, 0.04), iron)
        box((0.0, 0.08, -0.02), (0.28, 0.08, 0.18), iron)
        box((0.0, 0.96, 0.0), (0.03, 0.12, 0.03), accent)
    elif cast == "CRITTER":
        ellipsoid((0.20, 0.78, 0.04), (0.06, 0.14, 0.10), hair, segments=8, rings=3)
        ellipsoid((-0.20, 0.78, 0.04), (0.06, 0.14, 0.10), hair, segments=8, rings=3)
        ellipsoid((0.0, -0.18, 0.28), (0.07, 0.08, 0.16), accent, segments=8, rings=3)

    index_data = struct.pack("<%dH" % len(index_values), *index_values)
    geometry = QQuick3DGeometry()
    default_idle = pose_state == "IDLE" and pose_bucket == 0 and cast == "CROWD"
    geometry.setObjectName(
        "gameCharacterBodyGeometry"
        if default_idle
        else "gameCharacterBodyGeometry_%s_%s_%d" % (cast, pose_state, pose_bucket)
    )
    geometry.setStride(CHARACTER_VERTEX_STRIDE)
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.PositionSemantic,
        0,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.NormalSemantic,
        12,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.ColorSemantic,
        24,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.IndexSemantic,
        0,
        QQuick3DGeometry.Attribute.U16Type,
    )
    geometry.setVertexData(bytes(vertex_data))
    geometry.setIndexData(index_data)
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    geometry.setBounds(
        QVector3D(-0.62, -0.88, -0.52),
        QVector3D(0.62, 0.96, 0.52),
    )
    return geometry


def build_terrain_geometry(cell: dict[str, Any]) -> QQuick3DGeometry | None:
    """Build one indexed, lit patch from a compact terrain cell contract."""
    if not isinstance(cell, dict):
        return None
    coordinates = _cell_coordinates(cell)
    grid = _grid_for_cell(cell)
    if coordinates is None or grid is None:
        return None
    cell_x, cell_z = coordinates
    grid_size, heights = grid
    cell_size = 16.0
    step = cell_size / float(grid_size - 1)
    shared_normals = _normal_grid_for_cell(cell, grid_size)

    vertex_data = bytearray()
    for row in range(grid_size):
        for column in range(grid_size):
            index = row * grid_size + column
            height = heights[index]
            if shared_normals is not None:
                nx, ny, nz = shared_normals[index]
            else:
                if column == 0:
                    slope_x = (heights[index + 1] - height) / step
                elif column == grid_size - 1:
                    slope_x = (height - heights[index - 1]) / step
                else:
                    slope_x = (
                        heights[index + 1] - heights[index - 1]
                    ) / (2.0 * step)
                if row == 0:
                    slope_z = (
                        heights[index + grid_size] - height
                    ) / step
                elif row == grid_size - 1:
                    slope_z = (
                        height - heights[index - grid_size]
                    ) / step
                else:
                    slope_z = (
                        heights[index + grid_size]
                        - heights[index - grid_size]
                    ) / (2.0 * step)
                normal_length = math.sqrt(
                    slope_x * slope_x + 1.0 + slope_z * slope_z
                ) or 1.0
                nx = -slope_x / normal_length
                ny = 1.0 / normal_length
                nz = -slope_z / normal_length
            world_x = cell_x * cell_size + column * step
            world_z = cell_z * cell_size + row * step
            color = _terrain_surface_color(
                world_x,
                world_z,
                height,
                (nx, ny, nz),
            )
            vertex_data.extend(
                struct.pack(
                    "<12f",
                    column * step,
                    height,
                    row * step,
                    nx,
                    ny,
                    nz,
                    column / float(grid_size - 1),
                    row / float(grid_size - 1),
                    *color,
                )
            )

    index_values: list[int] = []
    for row in range(grid_size - 1):
        for column in range(grid_size - 1):
            top_left = row * grid_size + column
            top_right = top_left + 1
            bottom_left = top_left + grid_size
            bottom_right = bottom_left + 1
            # Counter-clockwise when viewed from above: front faces point +Y.
            index_values.extend(
                (
                    top_left,
                    bottom_left,
                    top_right,
                    top_right,
                bottom_left,
                bottom_right,
            )
        )
    # Keep the patch's actual vertices exactly on the shared heightfield and
    # add only a shallow edge curtain for mismatched neighbouring LODs.
    north_edge = [column for column in range(grid_size)]
    south_edge = [
        (grid_size - 1) * grid_size + column
        for column in range(grid_size - 1, -1, -1)
    ]
    west_edge = [row * grid_size for row in range(grid_size - 1, -1, -1)]
    east_edge = [row * grid_size + (grid_size - 1) for row in range(grid_size)]
    for edge, normal in (
        (north_edge, (0.0, 0.0, -1.0)),
        (south_edge, (0.0, 0.0, 1.0)),
        (west_edge, (-1.0, 0.0, 0.0)),
        (east_edge, (1.0, 0.0, 0.0)),
    ):
        _append_terrain_skirt(
            vertex_data,
            index_values,
            heights,
            grid_size,
            edge,
            normal,
            step,
            cell_x,
            cell_z,
        )
    index_data = struct.pack(
        "<%dH" % len(index_values),
        *index_values,
    )

    geometry = QQuick3DGeometry()
    geometry.setObjectName(
        "terrainPatch_%s" % str(cell.get("key", "%d:%d" % (cell_x, cell_z)))
    )
    geometry.setStride(TERRAIN_VERTEX_STRIDE)
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.PositionSemantic,
        0,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.NormalSemantic,
        12,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.TexCoordSemantic,
        24,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.ColorSemantic,
        32,
        QQuick3DGeometry.Attribute.F32Type,
    )
    geometry.addAttribute(
        QQuick3DGeometry.Attribute.IndexSemantic,
        0,
        QQuick3DGeometry.Attribute.U16Type,
    )
    geometry.setVertexData(bytes(vertex_data))
    geometry.setIndexData(index_data)
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    min_height = min(heights)
    max_height = max(heights)
    # A completely flat patch has a zero-thickness AABB. Some render paths
    # can cull such a mesh before its triangles are considered, so give it a
    # tiny conservative vertical extent without changing vertex data.
    if max_height - min_height < 0.02:
        min_height -= 0.01
        max_height += 0.01
    min_height -= TERRAIN_SKIRT_DEPTH_M
    geometry.setBounds(
        QVector3D(0.0, min_height, 0.0),
        QVector3D(cell_size, max_height, cell_size),
    )
    return geometry


class TerrainGeometryCache(QObject):
    """Keep current cell geometry alive while bounding native object growth."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: dict[str, tuple[tuple[Any, ...], QQuick3DGeometry]] = {}

    def retain(self, keys: set[str]) -> None:
        for key in tuple(self._entries):
            if key not in keys:
                entry = self._entries.pop(key, None)
                if entry is not None:
                    # QML may still be finishing the old delegate for this
                    # cell during the current event turn. deleteLater keeps
                    # that handoff safe while the QObject parent prevents a
                    # Python/QML ownership race.
                    entry[1].deleteLater()

    def update_cells(self, cells: dict[str, dict[str, Any]]) -> None:
        """Refresh already-instantiated cells without replacing their QObject."""
        for key, cell in cells.items():
            if key in self._entries:
                self.geometry_for_cell(cell)

    def geometry_for_cell(
        self,
        cell: dict[str, Any] | None,
    ) -> QQuick3DGeometry | None:
        if not isinstance(cell, dict):
            return None
        key = str(cell.get("key", ""))
        grid = _grid_for_cell(cell)
        if not key or grid is None:
            entry = self._entries.pop(key, None)
            if entry is not None:
                entry[1].deleteLater()
            return None
        grid_size, heights = grid
        coordinates = _cell_coordinates(cell)
        if coordinates is None:
            return None
        signature = (
            coordinates[0],
            coordinates[1],
            grid_size,
            tuple(heights),
        )
        existing = self._entries.get(key)
        if existing is not None and existing[0] == signature:
            return existing[1]
        geometry = build_terrain_geometry(cell)
        if geometry is None:
            entry = self._entries.pop(key, None)
            if entry is not None:
                entry[1].deleteLater()
            return None
        if existing is not None:
            current_geometry = existing[1]
            # QML keeps the geometry QObject as the Model's property. Updating
            # its buffers in place makes a live terrain edit visible even when
            # Repeater3D reuses the delegate for the same cell key.
            current_geometry.setStride(geometry.stride())
            current_geometry.setVertexData(geometry.vertexData())
            current_geometry.setIndexData(geometry.indexData())
            current_geometry.setBounds(geometry.boundsMin(), geometry.boundsMax())
            self._entries[key] = (signature, current_geometry)
            return current_geometry
        if key not in self._entries and len(self._entries) >= MAX_GEOMETRIES:
            evicted = self._entries.pop(next(iter(self._entries)))
            evicted[1].deleteLater()
        self._entries[key] = (signature, geometry)
        return geometry
