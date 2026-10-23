"""Engine-owned physics scene and finite, asset-independent command interface."""
from __future__ import annotations

import copy
import json
import math
import re

from backend import game_engine_native_physics as native

SCHEMA = "gg.game-engine.physics-command.v1"
_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")


def identity(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError("physics object needs a short identifier")
    return value


class PhysicsScene:
    """The engine clock owns stepping; the scene owns bodies and native lifetime."""
    def __init__(self, fixed_hz=60):
        self.settings = {"fixed_hz": fixed_hz, "gravity": (0, -9.81, 0), "workers": 1,
                         "max_bodies": 2048, "substeps": 4}
        self.world = None
        self.bodies = {}
        self.shapes = {}
        self.joints = {}
        self.last_error = ""

    def ensure_world(self):
        if self.world is None:
            self.world = native.PhysicsWorld(**self.settings)
        return self.world

    def reset(self):
        if self.world is not None:
            self.world.close()
        self.world = None
        self.bodies.clear(); self.shapes.clear(); self.joints.clear()
        self.last_error = ""

    close = reset

    def step(self, dt):
        if self.world is None:
            return
        if not math.isclose(dt, 1/self.settings["fixed_hz"], rel_tol=0, abs_tol=1e-9):
            raise ValueError("physics must use the engine's fixed timestep")
        self.world.step()

    def body(self, name):
        name = identity(name)
        if name not in self.bodies:
            raise ValueError("unknown physics body")
        return self.bodies[name]

    def status(self, *, transforms=False):
        result = {"schema": native.SCHEMA, "capabilities": native.capabilities(),
                  "configured": self.world is not None, "settings": dict(self.settings), "error": self.last_error,
                  "stats": self.world.stats() if self.world is not None else {"bodies": 0, "shapes": 0, "joints": 0, "steps": 0}}
        if transforms:
            reverse = {v:k for k,v in self.bodies.items()}
            result["bodies"] = [] if self.world is None else [
                {"id": reverse[s["body"]], "scene_node": "physics:" + reverse[s["body"]],
                 **{k:v for k,v in s.items() if k != "body"}} for s in self.world.states()]
        return result

    def frame(self):
        if self.world is None:
            return {"schema": native.SCHEMA, "bodies": [], "stats": {"bodies": 0, "steps": 0}}
        reverse = {v:k for k,v in self.bodies.items()}
        return {"schema": native.SCHEMA, "stats": self.world.stats(), "bodies": [
            {"id": reverse[body], "scene_node": "physics:" + reverse[body], "position": position, "rotation": orientation}
            for body, position, orientation in self.world.poses()]}

    def request(self, raw):
        try:
            if isinstance(raw, str):
                if len(raw) > 4*1024*1024:
                    raise ValueError("physics command capacity exceeded")
                raw = json.loads(raw)
            if not isinstance(raw, dict) or set(raw) - {"op", "id", "params"}:
                raise ValueError("invalid physics command fields")
            operation = raw.get("op")
            if not isinstance(operation, str):
                raise ValueError("physics operation is required")
            params = raw.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("physics parameters must be an object")
            result = self._dispatch(operation.upper(), raw.get("id"), copy.deepcopy(params))
            return {"schema": SCHEMA, "ok": True, "result": result}
        except (ValueError, TypeError, KeyError, native.PhysicsError) as exc:
            return {"schema": SCHEMA, "ok": False, "error": str(exc)[:240]}

    def _dispatch(self, op, name, params):
        if op == "CAPABILITIES":
            if params: raise ValueError("capabilities takes no parameters")
            return native.capabilities()
        if op == "STATUS":
            if params: raise ValueError("status takes no parameters")
            return self.status(transforms=True)
        if op == "RESET":
            if params: raise ValueError("reset takes no parameters")
            self.reset(); return self.status()
        if op == "CONFIGURE":
            if self.world is not None:
                raise ValueError("reset physics before changing its configuration")
            if set(params)-{"gravity", "workers", "max_bodies", "substeps"}:
                raise ValueError("unknown physics configuration")
            settings = {**self.settings, **params}
            candidate = native.PhysicsWorld(**settings)
            self.settings, self.world = settings, candidate
            return self.status()
        supported = {"BODY_CREATE", "BODY_REMOVE", "BODY_STATE", "BODY_TRANSFORM", "BODY_VELOCITY", "BODY_FORCE",
                     "BODY_AWAKE", "SHAPE_CREATE", "SHAPE_REMOVE", "JOINT_CREATE", "JOINT_REMOVE", "JOINT_FORCE",
                     "GRAVITY", "RAYCAST", "SHAPECAST", "OVERLAP", "EVENTS", "RECORD_START", "RECORD_VERIFY"}
        if op not in supported:
            raise ValueError("unknown physics operation")
        if op == "BODY_CREATE":
            name = identity(name)
            if name in self.bodies: raise ValueError("physics body already exists")
            existed = self.world is not None
            try:
                body = self.ensure_world().create_body(**params)
            except (ValueError, TypeError, native.PhysicsError):
                if not existed and self.world is not None:
                    self.world.close()
                    self.world = None
                raise
            self.bodies[name] = body
            return {"id": name, "scene_node": "physics:" + name, "state": self.world.state(body)}
        # Read and mutation operations never implicitly create an empty world.
        if self.world is None:
            raise ValueError("physics world is not configured")
        world = self.world
        if op == "BODY_REMOVE":
            if params: raise ValueError("body removal takes no parameters")
            body = self.body(name); world.destroy_body(body); self.bodies.pop(name)
            self.shapes = {k:v for k,v in self.shapes.items() if v[1] != name}
            self.joints = {k:v for k,v in self.joints.items() if name not in v[1:]}
            return {"removed": name}
        if op == "BODY_STATE":
            if params: raise ValueError("body state takes no parameters")
            return world.state(self.body(name))
        if op == "BODY_TRANSFORM":
            world.set_transform(self.body(name), **params)
        elif op == "BODY_VELOCITY":
            world.set_velocity(self.body(name), **params)
        elif op == "BODY_FORCE":
            world.apply(self.body(name), **params)
        elif op == "BODY_AWAKE":
            world.set_awake(self.body(name), **params)
        elif op == "SHAPE_CREATE":
            name = identity(name)
            if name in self.shapes: raise ValueError("physics shape already exists")
            owner = identity(params.pop("body")); body = self.body(owner)
            shape = world.create_shape(body, **params); self.shapes[name] = (shape, owner)
            return {"id": name, "body": owner}
        elif op == "SHAPE_REMOVE":
            if params: raise ValueError("shape removal takes no parameters")
            name = identity(name)
            if name not in self.shapes: raise ValueError("unknown physics shape")
            world.destroy_shape(self.shapes[name][0]); self.shapes.pop(name)
        elif op == "JOINT_CREATE":
            name = identity(name)
            if name in self.joints: raise ValueError("physics joint already exists")
            a, b = identity(params.pop("body_a")), identity(params.pop("body_b"))
            joint = world.create_joint(self.body(a), self.body(b), **params)
            self.joints[name] = (joint, a, b); return {"id": name}
        elif op in {"JOINT_REMOVE", "JOINT_FORCE"}:
            if params: raise ValueError("joint operation takes no parameters")
            name = identity(name)
            if name not in self.joints: raise ValueError("unknown physics joint")
            if op == "JOINT_FORCE": return world.joint_force(self.joints[name][0])
            world.destroy_joint(self.joints[name][0]); self.joints.pop(name)
        elif op == "GRAVITY":
            world.set_gravity(**params)
        elif op in {"RAYCAST", "SHAPECAST"}:
            if op == "RAYCAST" and ("points" in params or params.get("radius", 0) != 0):
                raise ValueError("raycast has no shape")
            if op == "SHAPECAST" and "points" not in params:
                raise ValueError("shapecast needs convex points")
            result = world.cast(**params)
            result["id"] = next((k for k,v in self.bodies.items() if v == result["body"]), None)
            return result
        elif op == "OVERLAP":
            reverse = {v:k for k,v in self.bodies.items()}
            return [{"id": reverse[row["body"]], **row} for row in world.overlap(**params)]
        elif op == "EVENTS":
            if params: raise ValueError("events takes no parameters")
            reverse = {v:k for k,v in self.bodies.items()}
            return [{"id_a": reverse.get(e["body_a"]), "id_b": reverse.get(e["body_b"]), **e} for e in world.events()]
        elif op == "RECORD_START":
            if params: raise ValueError("record start takes no parameters")
            world.start_recording()
        elif op == "RECORD_VERIFY":
            if params: raise ValueError("record verify takes no parameters")
            return {"verified": world.validate_recording()}
        return {"completed": op}


class RigidPhysicsMixin:
    def physics_command(self, request):
        with self._lock:
            return self._rigid_physics.request(request)

    def physics_status(self):
        with self._lock:
            return self._rigid_physics.status(transforms=True)

    def _tick_rigid_physics_locked(self, dt):
        try:
            self._rigid_physics.step(dt)
        except (ValueError, native.PhysicsError) as exc:
            self._rigid_physics.last_error = str(exc)[:240]
            self._running = False
            self._append_event_locked("PHYSICS_ERROR", self._rigid_physics.last_error)
