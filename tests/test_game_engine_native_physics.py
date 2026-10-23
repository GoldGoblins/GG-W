"""Real Box3D simulation, ABI boundaries, reproducibility and resource lifetime."""
from __future__ import annotations
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import game_engine_native_physics as physics
from backend.platform_support import native_directory, native_library_name


def floor(world):
    return world.create_body(body_type="STATIC", position=(0, -.5, 0),
                             shape={"kind": "BOX", "half_extents": (20, .5, 20)})


class NativePhysicsTests(unittest.TestCase):
    def test_compiled_probe_and_unmodified_upstream(self):
        self.assertTrue(physics.capabilities()["available"])
        result = subprocess.run([str(native_directory(PROJECT) / ("gg_physics_probe.exe" if os.name=='nt' else "gg_physics_probe"))],
                                capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")
        root = PROJECT / "native/physics/third_party/box3d"
        provenance = json.loads((root / "provenance.json").read_text())
        for name, digest in provenance["files"].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)

    def test_collision_sleep_and_impulse(self):
        with physics.PhysicsWorld() as w:
            floor(w)
            body = w.create_body(position=(0, 5, 0), shape={"kind": "SPHERE", "radius": .5})
            kinds = set()
            for _ in range(180):
                w.step(); kinds.update(e["kind"] for e in w.events())
            settled = w.state(body)
            self.assertAlmostEqual(settled["position"][1], .5, delta=.02)
            self.assertFalse(settled["awake"])
            self.assertIn("CONTACT_BEGIN", kinds); self.assertIn("BODY_SLEEP", kinds)
            w.apply(body, (0, 3, 0), mode="IMPULSE")
            w.step(10)
            self.assertGreater(w.state(body)["position"][1], 1)

    def test_all_primitive_and_convex_shapes(self):
        cases = [{"kind": "BOX"}, {"kind": "SPHERE"}, {"kind": "CAPSULE"},
                 {"kind": "CYLINDER"}, {"kind": "CONE"}, {"kind": "CONE", "top_radius": .2},
                 {"kind": "HULL", "vertices": [(-1, 0, -1), (1, 0, -1), (0, 0, 1), (0, 1, 0)]}]
        with physics.PhysicsWorld(gravity=(0, 0, 0)) as w:
            for i, shape in enumerate(cases):
                with self.subTest(shape=shape["kind"]):
                    body = w.create_body(position=(i*4, 0, 0), shape=shape)
                    self.assertGreater(w.state(body)["mass"], 0)
            w.step(10)
            self.assertEqual(w.stats()["shapes"], len(cases))
            self.assertTrue(all(math.isfinite(n) for b in w.states() for n in b["position"]))

    def test_mesh_lifetime_and_heightfield_contact(self):
        for shape, at in [({"kind": "MESH", "vertices": [(0,0,0),(4,0,0),(4,0,4),(0,0,4)],
                           "indices": [0,2,1,0,3,2]}, (1,3,1)),
                          ({"kind": "HEIGHTFIELD", "heights": [[0]*5 for _ in range(5)]}, (.25,3,.25))]:
            with self.subTest(kind=shape["kind"]), physics.PhysicsWorld() as w:
                w.create_body(body_type="STATIC", shape=shape)
                gc.collect()
                body = w.create_body(position=at, shape={"kind": "SPHERE", "radius": .5})
                w.step(180)
                self.assertAlmostEqual(w.state(body)["position"][1], .5, delta=.03)
                self.assertGreater(w.stats()["geometry_bytes"], 0)

    def test_compound_body_and_mass_update(self):
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            body = w.create_body(shape={"kind": "SPHERE", "radius": .5})
            initial = w.state(body)["mass"]
            shape = w.create_shape(body, kind="SPHERE", radius=.5, center=(1,0,0))
            self.assertAlmostEqual(w.state(body)["mass"], 2*initial, delta=1e-5)
            w.destroy_shape(shape)
            self.assertAlmostEqual(w.state(body)["mass"], initial, delta=1e-5)

    def test_continuous_collision_for_fast_body(self):
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            w.create_body(body_type="STATIC", shape={"half_extents": (.02,4,4)})
            body = w.create_body(position=(-4,0,0), linear_velocity=(800,0,0), bullet=True,
                                 shape={"kind": "SPHERE", "radius": .2})
            for _ in range(4):
                w.step(); self.assertLess(w.state(body)["position"][0], .3)

    def test_kinematic_motion_and_axis_locks(self):
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            mover = w.create_body(body_type="KINEMATIC", linear_velocity=(2,0,0), shape={"kind":"BOX"})
            locked = w.create_body(position=(0,4,0), locks=("LINEAR_X","ANGULAR_Z"), shape={"kind":"BOX"})
            w.apply(locked,(10,0,0),mode="IMPULSE");w.apply(locked,(0,0,10),mode="ANGULAR_IMPULSE")
            w.step(60)
            self.assertAlmostEqual(w.state(mover)["position"][0],2,delta=.01)
            self.assertAlmostEqual(w.state(locked)["position"][0],0,delta=1e-6)
            self.assertAlmostEqual(w.state(locked)["angular_velocity"][2],0,delta=1e-6)

    def test_queries_filters_and_sensor_events(self):
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            sensor = w.create_body(body_type="STATIC", shape={"kind":"SPHERE","radius":2,"sensor":True,"category":1})
            target = w.create_body(position=(1,0,0), shape={"kind":"SPHERE","radius":.3,"category":2})
            w.step()
            self.assertTrue(any(e["kind"]=="SENSOR_BEGIN" and e["body_a"]==sensor for e in w.events()))
            self.assertEqual(w.cast((1,4,0),(0,-8,0),mask=2)["body"],target)
            sweep = w.cast((1,4,0),(0,-8,0),points=[(0,0,0)],radius=.2,mask=2)
            self.assertTrue(sweep["hit"])
            self.assertLess(sweep["fraction"],w.cast((1,4,0),(0,-8,0),mask=2)["fraction"])
            self.assertEqual([r["body"] for r in w.overlap((1,0,0),mask=2)], [target])
            with self.assertRaises(physics.PhysicsError):w.overlap((1,0,0),radius=3,capacity=1)
            w.set_transform(target,(6,0,0));w.step()
            self.assertTrue(any(e["kind"]=="SENSOR_END" for e in w.events()))

    def test_all_joint_families_and_body_removal(self):
        for kind in physics.JOINT_TYPES:
            with self.subTest(kind=kind), physics.PhysicsWorld(gravity=(0,0,0)) as w:
                a=w.create_body(body_type="STATIC",shape={"kind":"SPHERE","radius":.2})
                b=w.create_body(position=(1,0,0),shape={"kind":"SPHERE","radius":.2})
                joint=w.create_joint(a,b,kind=kind)
                w.step(10)
                self.assertTrue(all(math.isfinite(v) for x in w.joint_force(joint).values() for v in x))
                w.destroy_body(b)
                self.assertEqual(w.stats()["joints"],0)
                with self.assertRaises(physics.PhysicsError):w.joint_force(joint)

    def test_distance_constraint_and_motor(self):
        with physics.PhysicsWorld() as w:
            a=w.create_body(body_type="STATIC",position=(0,4,0))
            b=w.create_body(position=(0,2,0),shape={"kind":"SPHERE","radius":.25})
            w.create_joint(a,b,length=2)
            w.step(180)
            self.assertAlmostEqual(math.dist(w.state(a)["position"],w.state(b)["position"]),2,delta=.02)
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            a=w.create_body(body_type="STATIC")
            b=w.create_body(shape={"kind":"BOX","half_extents":(1,.2,.2)})
            w.create_joint(a,b,kind="REVOLUTE",motor=True,motor_speed=2,max_motor=50)
            w.step(60)
            self.assertGreater(sum(v*v for v in w.state(b)["angular_velocity"]),.1)

    def test_native_recording_with_geometry_creation_and_removal(self):
        with physics.PhysicsWorld() as w:
            w.start_recording();floor(w)
            body=w.create_body(position=(0,3,0),shape={"kind":"BOX"})
            w.step(40);w.apply(body,(1,1,0),mode="IMPULSE");w.step(40)
            w.destroy_body(body);w.step(5)
            self.assertTrue(w.validate_recording())
            self.assertGreater(len(w.stop_recording()),64)

    def test_repeatability_across_worker_counts(self):
        def run(workers):
            with physics.PhysicsWorld(workers=workers) as w:
                floor(w)
                for i in range(24):
                    w.create_body(position=((i%3)-1,1+(i//3)*1.1,0),shape={"kind":"BOX"})
                w.step(180)
                return [(b["position"],b["rotation"],b["linear_velocity"],b["awake"]) for b in w.states()]
        self.assertEqual(run(1),run(1))
        self.assertEqual(run(1),run(4))

    def test_recording_capacity_does_not_hide_committed_objects(self):
        with physics.PhysicsWorld(max_bodies=2) as w:
            body=w.create_body(body_type='STATIC')
            w.start_recording()
            heights=[[0]*256 for _ in range(256)]
            for _ in range(128):
                shape=w.create_shape(body,kind='HEIGHTFIELD',heights=heights)
                w.destroy_shape(shape)
                if w.stats()['recording_overflow']:break
            self.assertTrue(w.stats()['recording_overflow'])
            other=w.create_body(shape={'kind':'SPHERE'})
            self.assertEqual(w.stats()['bodies'],2)
            self.assertEqual(w.state(other)['type'],'DYNAMIC')
            with self.assertRaises(physics.PhysicsError):w.stop_recording()
            w.start_recording();w.step();self.assertTrue(w.validate_recording())

    def test_double_position_precision(self):
        with physics.PhysicsWorld(gravity=(0,0,0)) as w:
            body=w.create_body(position=(10_000_000.125,0,0),linear_velocity=(.1,0,0),shape={"kind":"SPHERE"})
            w.step(60)
            self.assertAlmostEqual(w.state(body)["position"][0],10_000_000.225,delta=.0001)

    def test_invalid_geometry_is_rejected_and_create_rolls_back(self):
        with physics.PhysicsWorld() as w:
            for shape in ({"kind":"BOX","half_extents":(0,1,1)},
                          {"kind":"MESH","vertices":[(0,0,0),(1,0,0),(2,0,0)],"indices":[0,1,2]},
                          {"kind":"HULL","vertices":[(0,0,0)]*4},
                          {"kind":"HEIGHTFIELD","heights":[[0,0],[0]]}):
                with self.subTest(shape=shape["kind"]),self.assertRaises((ValueError,physics.PhysicsError)):
                    w.create_body(body_type="STATIC",shape=shape)
                self.assertEqual(w.stats()["bodies"],0);self.assertEqual(w.stats()["shapes"],0)
            with self.assertRaises((ValueError,physics.PhysicsError)):
                w.create_body(position=(float('nan'),0,0))

    def test_native_capacity_closed_handles_and_atomic_rejection(self):
        w=physics.PhysicsWorld(max_bodies=1)
        body=w.create_body(shape={"kind":"SPHERE"});lib=w._lib
        with self.assertRaises(physics.PhysicsError):w.create_body()
        before=w.state(body)
        bad=physics.Vec3(0,float('nan'),0);q=physics.Quat(0,0,0,1)
        self.assertEqual(lib.ggp_body_transform(w.handle,body,bad,q),-1)
        self.assertEqual(w.state(body),before)
        state=physics.BodyState();state.body=987
        self.assertEqual(lib.ggp_body_states(w.handle,C.byref(state),0),-1)
        self.assertEqual(state.body,987)
        self.assertEqual(lib.ggp_world_step(w.handle,float('nan'),4),-1)
        self.assertEqual(w.stats()["steps"],0)
        handle=w.handle;w.close();w.close()
        self.assertEqual(lib.ggp_body_state(handle,body,C.byref(state)),-1)
        self.assertEqual(state.body,987)
        with self.assertRaises(physics.PhysicsError):w.step()

    def test_parallel_world_lifetime(self):
        def run(_):
            with physics.PhysicsWorld() as w:
                floor(w);b=w.create_body(position=(0,3,0),shape={"kind":"SPHERE"});w.step(120)
                return w.state(b)["position"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(run,range(12)))
        self.assertTrue(all(row==rows[0] for row in rows))

    def test_relocatable_offline_backend(self):
        import importlib.util
        package_script=PROJECT/'tools/package_gg_game_release.py'
        spec=importlib.util.spec_from_file_location('physics_packager',package_script if package_script.is_file() else PROJECT/'packaging/catalog.py')
        packager=importlib.util.module_from_spec(spec);spec.loader.exec_module(packager)
        packaged=({p.relative_to(PROJECT).as_posix() for p in packager.package_files()} if package_script.is_file()
                  else set(packager.selected_paths(PROJECT)))
        native=native_directory(PROJECT).relative_to(PROJECT).as_posix()
        self.assertTrue({'backend/game_engine_native_physics.py','backend/game_engine_rigid_physics.py',
                         native+'/'+native_library_name('gg_physics'),native+'/physics-build.json',
                         'native/physics/gg_physics.cpp','native/physics/gg_physics.h',
                         'native/physics/third_party/box3d/provenance.json','backend/licenses/box3d-MIT.txt'}<=packaged)
        with tempfile.TemporaryDirectory(prefix="gg-physics-relocation-") as temporary:
            root=Path(temporary)
            shutil.copytree(PROJECT/'native/physics',root/'native/physics')
            for name in ('backend/game_engine_native_physics.py','backend/platform_support.py','backend/application_paths.py',
                         native+'/'+native_library_name('gg_physics'),native+'/physics-build.json'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(PROJECT/name,target)
            code="import sys;sys.path.insert(0,sys.argv[1]);from backend.game_engine_native_physics import PhysicsWorld;w=PhysicsWorld();b=w.create_body(shape={'kind':'SPHERE'});w.step();assert w.state(b)['position'][1]<0;w.close();print('PASS')"
            result=subprocess.run([sys.executable,'-I','-c',code,str(root)],capture_output=True,text=True,check=True,timeout=20)
            self.assertEqual(result.stdout.strip(),'PASS')

    def test_disabled_mode_is_explicit(self):
        code="from backend.game_engine_native_physics import capabilities,PhysicsWorld,PhysicsError;assert not capabilities()['available'];\ntry:PhysicsWorld()\nexcept PhysicsError:print('PASS')\nelse:raise AssertionError('fake physics')"
        result=subprocess.run([sys.executable,'-c',code],cwd=PROJECT,env={**os.environ,'GG_GAME_PHYSICS_NATIVE':'0'},capture_output=True,text=True,check=True,timeout=15)
        self.assertEqual(result.stdout.strip(),'PASS')


if __name__ == '__main__':unittest.main()
