"""Owned Box3D worlds behind GG's versioned native physics ABI.

The engine works in metres, kilograms and seconds, with Y up and x,y,z,w
quaternions. No assets, network downloads or builds occur at runtime.
"""
from __future__ import annotations
from backend.platform_support import native_directory, native_library_name

import ctypes as C
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import threading
import weakref

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "native/physics"
SCHEMA = "gg.game-engine.rigid-physics.v1"
BODY_TYPES = ("STATIC", "KINEMATIC", "DYNAMIC")
SHAPE_TYPES = ("BOX", "SPHERE", "CAPSULE", "HULL", "MESH", "HEIGHTFIELD", "CYLINDER", "CONE")
JOINT_TYPES = ("DISTANCE", "REVOLUTE", "PRISMATIC", "SPHERICAL", "WELD", "WHEEL", "MOTOR", "PARALLEL", "FILTER")
EVENT_TYPES = ("CONTACT_BEGIN", "CONTACT_END", "CONTACT_HIT", "SENSOR_BEGIN", "SENSOR_END", "BODY_SLEEP")
MAX_EVENTS = 8192
ALL_BITS = (1 << 64) - 1
Vec3 = C.c_double * 3
Quat = C.c_double * 4
DP = C.POINTER(C.c_double)
U64 = C.c_uint64
U32 = C.c_uint32


class PhysicsError(RuntimeError):
    """A native physics operation failed without changing authority or assets."""


class WorldDef(C.Structure):
    _fields_ = [("gravity", Vec3), ("workers", U32), ("max_bodies", U32)]


class BodyDef(C.Structure):
    _fields_ = [("position", Vec3), ("rotation", Quat), ("linear_velocity", Vec3),
                ("angular_velocity", Vec3), ("linear_damping", C.c_double),
                ("angular_damping", C.c_double), ("gravity_scale", C.c_double),
                ("type", U32), ("flags", U32), ("locks", U32)]


class ShapeDef(C.Structure):
    _fields_ = [("kind", U32), ("flags", U32), ("category", U64), ("mask", U64),
                ("density", C.c_double), ("friction", C.c_double), ("restitution", C.c_double),
                ("dimensions", Vec3), ("center", Vec3), ("rotation", Quat),
                ("points", DP), ("indices", C.POINTER(U32)), ("point_count", U32),
                ("index_count", U32), ("count_x", U32), ("count_z", U32)]


class BodyState(C.Structure):
    _fields_ = [("body", U64), ("position", Vec3), ("rotation", Quat),
                ("linear_velocity", Vec3), ("angular_velocity", Vec3),
                ("mass", C.c_double), ("type", U32), ("awake", U32)]


class JointDef(C.Structure):
    _fields_ = [("body_a", U64), ("body_b", U64), ("kind", U32), ("flags", U32),
                ("anchor_a", Vec3), ("anchor_b", Vec3), ("rotation_a", Quat), ("rotation_b", Quat),
                ("length", C.c_double), ("lower", C.c_double), ("upper", C.c_double),
                ("hertz", C.c_double), ("damping", C.c_double), ("motor_speed", C.c_double),
                ("max_motor", C.c_double), ("linear_velocity", Vec3), ("angular_velocity", Vec3)]


class Hit(C.Structure):
    _fields_ = [("shape", U64), ("body", U64), ("point", Vec3), ("normal", Vec3),
                ("fraction", C.c_double), ("hit", U32)]


class Event(C.Structure):
    _fields_ = [("kind", U32), ("shape_a", U64), ("shape_b", U64), ("body_a", U64),
                ("body_b", U64), ("point", Vec3), ("normal", Vec3), ("speed", C.c_double)]


class Stats(C.Structure):
    _fields_ = [(name, U32) for name in ("bodies", "shapes", "joints", "contacts", "awake", "workers", "events", "event_overflow", "recording", "recording_overflow")] + [
        ("geometry_bytes", U64), ("steps", U64), ("step_ms", C.c_double)]


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in SOURCE.rglob("*") if p.is_file()):
        digest.update(path.relative_to(SOURCE).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


_load_lock = threading.RLock()
_lib = None
_attempted = False
_reason = "NOT_LOADED"


def library():
    global _lib, _attempted, _reason
    with _load_lock:
        mode = os.environ.get("GG_GAME_PHYSICS_NATIVE", "auto")
        if mode == "0":
            return None
        if not _attempted:
            _attempted = True
            try:
                if os.name != "nt" and (platform.system(), platform.machine()) != ("Linux", "x86_64"):
                    raise PhysicsError("unsupported native physics platform")
                root = native_directory(PROJECT)
                receipt = json.loads((root / "physics-build.json").read_text())
                binary = root / native_library_name("gg_physics")
                if receipt.get("abi") != 1 or receipt.get("precision") != "DOUBLE_POSITIONS" or receipt.get("source_sha256") != source_digest():
                    raise PhysicsError("physics source/build mismatch")
                if receipt.get("binary_sha256") != hashlib.sha256(binary.read_bytes()).hexdigest():
                    raise PhysicsError("physics binary/build mismatch")
                lib = C.CDLL(str(binary))
                defs = {
                    "ggp_abi_version": ([], U32), "ggp_last_error": ([], C.c_char_p),
                    "ggp_world_create": ([C.POINTER(WorldDef)], U64), "ggp_world_destroy": ([U64], C.c_int),
                    "ggp_world_step": ([U64, C.c_double, U32], C.c_int), "ggp_world_gravity": ([U64, DP], C.c_int),
                    "ggp_world_stats": ([U64, C.POINTER(Stats)], C.c_int),
                    "ggp_body_create": ([U64, C.POINTER(BodyDef)], U64), "ggp_body_destroy": ([U64, U64], C.c_int),
                    "ggp_body_state": ([U64, U64, C.POINTER(BodyState)], C.c_int),
                    "ggp_body_states": ([U64, C.POINTER(BodyState), U32], C.c_int),
                    "ggp_body_transform": ([U64, U64, DP, DP], C.c_int),
                    "ggp_body_velocity": ([U64, U64, DP, DP], C.c_int),
                    "ggp_body_force": ([U64, U64, DP, DP, U32], C.c_int), "ggp_body_awake": ([U64, U64, U32], C.c_int),
                    "ggp_shape_create": ([U64, U64, C.POINTER(ShapeDef)], U64), "ggp_shape_destroy": ([U64, U64], C.c_int),
                    "ggp_joint_create": ([U64, C.POINTER(JointDef)], U64), "ggp_joint_destroy": ([U64, U64], C.c_int),
                    "ggp_joint_force": ([U64, U64, DP, DP], C.c_int),
                    "ggp_cast": ([U64, DP, DP, DP, U32, C.c_double, U64, C.POINTER(Hit)], C.c_int),
                    "ggp_overlap": ([U64, DP, DP, U32, C.c_double, U64, C.POINTER(U64), U32], C.c_int),
                    "ggp_events": ([U64, C.POINTER(Event), U32], C.c_int),
                    "ggp_record_start": ([U64], C.c_int), "ggp_record_stop": ([U64], C.c_int),
                    "ggp_record_copy": ([U64, C.POINTER(C.c_uint8), U32], C.c_int),
                    "ggp_replay_validate": ([C.POINTER(C.c_uint8), U32], C.c_int),
                }
                for name, (args, result) in defs.items():
                    function = getattr(lib, name)
                    function.argtypes, function.restype = args, result
                if lib.ggp_abi_version() != 1:
                    raise PhysicsError("unsupported physics ABI")
                _lib, _reason = lib, "READY"
            except (OSError, ValueError, AttributeError, PhysicsError) as exc:
                _reason = str(exc)[:200]
        if _lib is None and mode == "required":
            raise PhysicsError("native physics required: " + _reason)
        return _lib


def capabilities() -> dict:
    lib = library()
    return {"schema": SCHEMA, "backend": "BOX3D" if lib else "UNAVAILABLE", "version": "0.1.0",
            "available": lib is not None, "reason": "DISABLED" if os.environ.get("GG_GAME_PHYSICS_NATIVE") == "0" else _reason,
            "body_types": list(BODY_TYPES), "shape_types": list(SHAPE_TYPES), "joint_types": list(JOINT_TYPES),
            "queries": ["RAY", "CONVEX_CAST", "CONVEX_OVERLAP"], "continuous_collision": True,
            "recording": "NATIVE_BOUNDED", "precision": "DOUBLE_POSITIONS", "units": "METRES_KILOGRAMS_SECONDS",
            "quaternion_order": "XYZW", "up_axis": "Y", "max_worlds": 8, "max_events": MAX_EVENTS}


def scalar(value, low=-1e6, high=1e6) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("physics value must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("physics number out of range")
    return value


def integer(value, low, high) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("physics integer out of range")
    return value


def vector(value, size=3, limit=1e6):
    if not isinstance(value, (tuple, list)) or len(value) != size:
        raise ValueError("invalid physics vector length")
    return (C.c_double * size)(*(scalar(x, -limit, limit) for x in value))


def rotation(value):
    q = vector(value, 4)
    length = math.sqrt(sum(x*x for x in q))
    if length < 1e-8:
        raise ValueError("physics quaternion must be nonzero")
    return Quat(*(x/length for x in q))


def enum(value, choices) -> int:
    if not isinstance(value, str) or value.upper() not in choices:
        raise ValueError("unknown physics type")
    return choices.index(value.upper())


def point_buffer(values, maximum=65536):
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= maximum:
        raise ValueError("invalid physics point capacity")
    return (C.c_double * (len(values)*3))(*(x for p in values for x in vector(p)))


def locked(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            if not self._finalizer.alive:
                raise PhysicsError("physics world is closed")
            return function(self, *args, **kwargs)
    return wrapped


def _state(s: BodyState) -> dict:
    return {"body": s.body, "position": list(s.position), "rotation": list(s.rotation),
            "linear_velocity": list(s.linear_velocity), "angular_velocity": list(s.angular_velocity),
            "mass": s.mass, "type": BODY_TYPES[s.type], "awake": bool(s.awake)}


class PhysicsWorld:
    """One independently owned physics world; all methods serialize with close."""
    def __init__(self, *, gravity=(0, -9.81, 0), workers=1, max_bodies=2048, fixed_hz=60, substeps=4):
        self._lock = threading.RLock()
        self.fixed_hz = integer(fixed_hz, 30, 240)
        self.substeps = integer(substeps, 1, 16)
        self.max_bodies = integer(max_bodies, 1, 8192)
        self._lib = library()
        if self._lib is None:
            raise PhysicsError("Box3D physics is unavailable: " + capabilities()["reason"])
        definition = WorldDef(vector(gravity, limit=1000), integer(workers, 1, 16), self.max_bodies)
        self.handle = self._lib.ggp_world_create(C.byref(definition))
        if not self.handle:
            raise PhysicsError(self._error())
        self._finalizer = weakref.finalize(self, self._lib.ggp_world_destroy, self.handle)
        self._bodies = set()
        self._shapes = {}
        self._joints = {}
        self._states_buffer = (BodyState * self.max_bodies)()
        self._events_buffer = (Event * MAX_EVENTS)()

    def _error(self):
        return self._lib.ggp_last_error().decode("utf-8", "replace")

    def _call(self, name, *args, handle=False):
        result = getattr(self._lib, name)(self.handle, *args)
        if result < 0 or handle and result == 0:
            raise PhysicsError(self._error())
        return result

    def close(self):
        with self._lock:
            self._finalizer()
            self._bodies.clear(); self._shapes.clear(); self._joints.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @locked
    def create_body(self, *, body_type="DYNAMIC", position=(0, 0, 0), orientation=(0, 0, 0, 1),
                    linear_velocity=(0, 0, 0), angular_velocity=(0, 0, 0), linear_damping=0,
                    angular_damping=0, gravity_scale=1, bullet=False, sleeping=True, awake=True,
                    enabled=True, locks=(), shape=None):
        lock_names = ("LINEAR_X", "LINEAR_Y", "LINEAR_Z", "ANGULAR_X", "ANGULAR_Y", "ANGULAR_Z")
        if not isinstance(locks, (tuple, list)):
            raise ValueError("physics locks must be a sequence")
        mask = 0
        for name in locks:
            mask |= 1 << enum(name, lock_names)
        flags = int(bool(bullet)) | int(bool(sleeping))*2 | int(bool(enabled))*4 | int(bool(awake))*8
        d = BodyDef(vector(position, limit=1e9), rotation(orientation), vector(linear_velocity, limit=1000),
                    vector(angular_velocity, limit=1000), scalar(linear_damping, 0, 1000), scalar(angular_damping, 0, 1000),
                    scalar(gravity_scale, -100, 100), enum(body_type, BODY_TYPES), flags, mask)
        body = self._call("ggp_body_create", C.byref(d), handle=True)
        self._bodies.add(body)
        if shape is not None:
            try:
                if not isinstance(shape, dict):
                    raise ValueError("physics shape must be a definition")
                self.create_shape(body, **shape)
            except Exception:
                self.destroy_body(body)
                raise
        return body

    @locked
    def destroy_body(self, body):
        body = integer(body, 1, ALL_BITS)
        self._call("ggp_body_destroy", body)
        self._bodies.discard(body)
        self._shapes = {k:v for k,v in self._shapes.items() if v != body}
        self._joints = {k:v for k,v in self._joints.items() if body not in v}

    @locked
    def create_shape(self, body, *, kind="BOX", half_extents=(.5, .5, .5), radius=.5, half_height=.5,
                     top_radius=0, center=(0, 0, 0), orientation=(0, 0, 0, 1), vertices=None, indices=None,
                     heights=None, scale=(1, 1, 1), density=1, friction=.6, restitution=0,
                     category=1, mask=ALL_BITS, sensor=False, events=True):
        body = integer(body, 1, ALL_BITS)
        d = ShapeDef()
        d.kind = enum(kind, SHAPE_TYPES)
        d.flags = int(bool(sensor)) | (14 if events else 0)
        d.category, d.mask = integer(category, 0, ALL_BITS), integer(mask, 0, ALL_BITS)
        d.density, d.friction, d.restitution = scalar(density, 0, 1e6), scalar(friction, 0, 100), scalar(restitution, 0, 1)
        d.center, d.rotation = vector(center), rotation(orientation)
        buffers = []
        if d.kind == 0:
            d.dimensions = vector(half_extents, limit=50000)
        elif d.kind in (1, 2, 6, 7):
            d.dimensions = Vec3(scalar(radius, .001, 50000), scalar(half_height, 0, 50000), scalar(top_radius, 0, 50000))
        elif d.kind in (3, 4):
            data = point_buffer(vertices, 256 if d.kind == 3 else 65536)
            buffers.append(data); d.points = data; d.point_count = len(vertices)
            if d.kind == 4:
                if not isinstance(indices, (list, tuple)) or not 3 <= len(indices) <= 393216 or len(indices) % 3:
                    raise ValueError("invalid physics triangle index capacity")
                data_i = (U32 * len(indices))(*(integer(i, 0, len(vertices)-1) for i in indices))
                buffers.append(data_i); d.indices = data_i; d.index_count = len(indices)
        else:
            if not isinstance(heights, (tuple, list)) or not 2 <= len(heights) <= 256:
                raise ValueError("height field must have at least two rows")
            if not isinstance(heights[0], (tuple, list)) or not 2 <= len(heights[0]) <= 256:
                raise ValueError("height field must have at least two columns")
            d.count_z, d.count_x = len(heights), len(heights[0])
            if any(not isinstance(row, (tuple, list)) or len(row) != d.count_x for row in heights):
                raise ValueError("height field rows must have equal lengths")
            values = [scalar(h, -50000, 50000) for row in heights for h in row]
            data = (C.c_double * len(values))(*values)
            buffers.append(data); d.points = data; d.point_count = len(values); d.dimensions = vector(scale, limit=50000)
        shape = self._call("ggp_shape_create", body, C.byref(d), handle=True)
        self._shapes[shape] = body
        return shape

    @locked
    def destroy_shape(self, shape):
        shape = integer(shape, 1, ALL_BITS)
        self._call("ggp_shape_destroy", shape); self._shapes.pop(shape, None)

    @locked
    def state(self, body):
        result = BodyState()
        self._call("ggp_body_state", integer(body, 1, ALL_BITS), C.byref(result))
        return _state(result)

    @locked
    def states(self):
        count = self._call("ggp_body_states", self._states_buffer, self.max_bodies)
        return [_state(self._states_buffer[i]) for i in range(count)]

    @locked
    def poses(self):
        """Only the fields needed by the render stream; detailed state stays queryable."""
        count = self._call("ggp_body_states", self._states_buffer, self.max_bodies)
        return [(s.body, list(s.position), list(s.rotation))
                for s in (self._states_buffer[i] for i in range(count))]

    @locked
    def set_transform(self, body, position, orientation=(0, 0, 0, 1)):
        self._call("ggp_body_transform", integer(body, 1, ALL_BITS), vector(position, limit=1e9), rotation(orientation))

    @locked
    def set_velocity(self, body, linear=(0, 0, 0), angular=(0, 0, 0)):
        self._call("ggp_body_velocity", integer(body, 1, ALL_BITS), vector(linear, limit=1000), vector(angular, limit=1000))

    @locked
    def apply(self, body, value, *, mode="FORCE", point=None):
        modes = ("FORCE", "IMPULSE", "TORQUE", "ANGULAR_IMPULSE")
        self._call("ggp_body_force", integer(body, 1, ALL_BITS), vector(value),
                   None if point is None else vector(point, limit=1e9), enum(mode, modes))

    @locked
    def set_awake(self, body, awake=True):
        self._call("ggp_body_awake", integer(body, 1, ALL_BITS), int(bool(awake)))

    @locked
    def set_gravity(self, gravity):
        self._call("ggp_world_gravity", vector(gravity, limit=1000))

    @locked
    def create_joint(self, body_a, body_b, *, kind="DISTANCE", anchor_a=(0, 0, 0), anchor_b=(0, 0, 0),
                     orientation_a=(0, 0, 0, 1), orientation_b=(0, 0, 0, 1), length=1, lower=0, upper=1,
                     spring=False, hertz=0, damping=1, limit=False, motor=False, motor_speed=0,
                     max_motor=100, linear_velocity=(0, 0, 0), angular_velocity=(0, 0, 0), collide_connected=False):
        flags = int(bool(collide_connected)) | int(bool(spring))*2 | int(bool(limit))*4 | int(bool(motor))*8
        d = JointDef(integer(body_a, 1, ALL_BITS), integer(body_b, 1, ALL_BITS), enum(kind, JOINT_TYPES), flags,
                     vector(anchor_a), vector(anchor_b), rotation(orientation_a), rotation(orientation_b),
                     scalar(length, .001, 100000), scalar(lower, -100000, 100000), scalar(upper, -100000, 100000),
                     scalar(hertz, 0, 1000), scalar(damping, 0, 100), scalar(motor_speed, -1000, 1000),
                     scalar(max_motor, 0, 1e6), vector(linear_velocity, limit=1000), vector(angular_velocity, limit=1000))
        joint = self._call("ggp_joint_create", C.byref(d), handle=True)
        self._joints[joint] = (body_a, body_b)
        return joint

    @locked
    def destroy_joint(self, joint):
        joint = integer(joint, 1, ALL_BITS)
        self._call("ggp_joint_destroy", joint); self._joints.pop(joint, None)

    @locked
    def joint_force(self, joint):
        force, torque = Vec3(), Vec3()
        self._call("ggp_joint_force", integer(joint, 1, ALL_BITS), force, torque)
        return {"force": list(force), "torque": list(torque)}

    @locked
    def cast(self, origin, translation, *, points=None, radius=0, mask=ALL_BITS):
        data = None if points is None else point_buffer(points, 256)
        result = Hit()
        self._call("ggp_cast", vector(origin, limit=1e9), vector(translation), data, 0 if points is None else len(points),
                   scalar(radius, 0, 50000), integer(mask, 0, ALL_BITS), C.byref(result))
        return {"hit": bool(result.hit), "body": result.body, "shape": result.shape, "point": list(result.point),
                "normal": list(result.normal), "fraction": result.fraction}

    @locked
    def overlap(self, origin, *, points=((0, 0, 0),), radius=.5, mask=ALL_BITS, capacity=256):
        data = point_buffer(points, 256)
        capacity = integer(capacity, 1, 32768)
        result = (U64 * capacity)()
        count = self._call("ggp_overlap", vector(origin, limit=1e9), data, len(points), scalar(radius, 0, 50000),
                           integer(mask, 0, ALL_BITS), result, capacity)
        return [{"shape": result[i], "body": self._shapes[result[i]]} for i in range(count)]

    @locked
    def step(self, ticks=1):
        for _ in range(integer(ticks, 1, 240)):
            self._call("ggp_world_step", 1 / self.fixed_hz, self.substeps)

    @locked
    def events(self):
        count = self._call("ggp_events", self._events_buffer, MAX_EVENTS)
        return [{"kind": EVENT_TYPES[e.kind], "shape_a": e.shape_a, "shape_b": e.shape_b,
                 "body_a": e.body_a, "body_b": e.body_b, "point": list(e.point), "normal": list(e.normal),
                 "speed": e.speed} for e in (self._events_buffer[i] for i in range(count))]

    @locked
    def stats(self):
        result = Stats()
        self._call("ggp_world_stats", C.byref(result))
        return {"backend": "BOX3D", "fixed_hz": self.fixed_hz, "substeps": self.substeps,
                **{name: getattr(result, name) for name, _ in Stats._fields_}}

    @locked
    def start_recording(self):
        self._call("ggp_record_start")

    @locked
    def stop_recording(self) -> bytes:
        size = self._call("ggp_record_stop")
        result = (C.c_uint8 * size)()
        self._call("ggp_record_copy", result, size)
        return bytes(result)

    @locked
    def validate_recording(self) -> bool:
        """Verify this world's own native recording; external byte streams are not accepted."""
        data = self.stop_recording()
        buffer = (C.c_uint8 * len(data)).from_buffer_copy(data)
        result = self._lib.ggp_replay_validate(buffer, len(data))
        if result < 0:
            raise PhysicsError(self._error())
        return bool(result)
