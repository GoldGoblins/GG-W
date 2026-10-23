"""Actual compiled ABI, source/reference parity, bounds and Qt integration."""
from __future__ import annotations
import ctypes as C
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['GG_GAME_WORLD_NATIVE']='required'
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend import game_engine_native_world as core
from backend.platform_support import native_directory, native_library_name
from backend.game_engine_streaming import SpatialResidencyCache,StreamWindow
from backend.game_engine_world_trees import sector_in_range

def camera(x=0,y=0,z=0,heading=0,pitch=0,far=1000):
    h,p=math.radians(heading),math.radians(pitch)
    return ((x,y,z),(math.sin(h)*math.cos(p),math.sin(p),math.cos(h)*math.cos(p)),
            (-math.cos(h),0,math.sin(h)),(-math.sin(h)*math.sin(p),math.cos(p),-math.cos(h)*math.sin(p)),math.tan(math.pi/8),1.6,far)

class NativeWorldTests(unittest.TestCase):
    def test_real_build_and_executable(self):
        self.assertEqual(core.status()['backend'],'CPP')
        binary=native_directory(PROJECT)/('gg_world_probe.exe' if os.name=='nt' else 'gg_world_probe')
        result=subprocess.run([str(binary)],check=True,capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')

    def test_negative_grid_and_stable_priority(self):
        rng=random.Random(943)
        for x,z,far in [(-.01,-64.01,256),(32,32,0),(64,-64,88)]+[(rng.uniform(-100000,100000),rng.uniform(-100000,100000),rng.uniform(0,10000)) for _ in range(200)]:
            w=StreamWindow.at(x,z,far,64)
            inner=1+int(max(0,far)/64)
            self.assertEqual((w.x,w.z,w.inner,w.outer),(math.floor(x/64),math.floor(z/64),inner,max(inner+2,8)))
            expected=[(w.x+dx,w.z+dz) for dx in range(-3,4) for dz in range(-3,4)]
            expected.sort(key=lambda c:((c[0]+.5)*64-x)**2+((c[1]+.5)*64-z)**2)
            self.assertEqual(core.prioritized_cells(x,z,64),expected)

    def test_dwell_touch_and_capacity_override(self):
        c=SpatialResidencyCache(2)
        c.put('a',object());c.scope((0,0),100,0)
        self.assertEqual(c.scope((500,0),100,29.999),0)
        self.assertEqual(c.scope((500,0),100,30),1)
        c.put('a',1);c.put('b',2);c.scope((0,0),100,40)
        self.assertEqual(c.fetch('a'),1);c.put('c',3)
        self.assertEqual(list(c),['a','c'])
        self.assertEqual(c.scope((500,0),100,70),0)  # touched/new entries stamp here
        self.assertEqual(c.scope((500,0),100,101),0)  # still local
        self.assertEqual(c.scope((0,0),100,101),2)
        self.assertEqual(c.stamps,{})

    def test_random_residency_reference_parity(self):
        rng=random.Random(37);native=SpatialResidencyCache(31);reference=SpatialResidencyCache(31,native=False)
        for i in range(2000):
            action=rng.randrange(7);key=rng.randrange(70)
            for cache in (native,reference):
                if action<2:cache.put(key,(i,key))
                elif action==2:cache.fetch(key)
                elif action==3:cache.scope((i%317*32,-(i%91)*64),256,float(i))
                elif action==4:cache.pop(key,None)
                elif action==5 and i%17==0:cache.clear()
                elif action==6:cache.touch_many(range(key,key+5))
            self.assertEqual(list(native.items()),list(reference.items()))
            self.assertEqual(native.stamps,reference.stamps)
            self.assertLessEqual(len(native),31)

    def test_mapping_lru_changes_keep_native_metadata_in_sync(self):
        for native in (True,False):
            cache=SpatialResidencyCache(3,native=native)
            cache.update(a=1,b=2);cache.setdefault('c',3)
            cache.scope((0,0),100,0)
            cache.move_to_end('c',last=False)
            cache['d']=4
            self.assertEqual(list(cache.items()),[('a',1),('b',2),('d',4)])
            self.assertEqual(set(cache.stamps),set(cache))
            self.assertEqual(cache.popitem(last=False),('a',1))
            del cache['d']
            self.assertEqual(cache.scope((500,0),100,30),1)
            self.assertEqual(cache.stamps,{})

    def test_catalog_selection_matches_existing_policy(self):
        rng=random.Random(421)
        for name in ('trees/world-trees.catalog.json','places/world-places.catalog.json','landscape/world-landscape.catalog.json','ground-cover/ground-cover.catalog.json'):
            path=PROJECT/'qml/assets/authored/world'/name
            if not path.exists():continue
            catalog=json.loads(path.read_text());sectors=catalog['sectors'];index=core.SectorIndex(sectors)
            for _ in range(24):
                view=camera(rng.uniform(-18000,18000),rng.uniform(-10,2000),rng.uniform(-18000,18000),rng.uniform(-180,180),rng.uniform(-70,70),rng.uniform(50,10000))
                padding=catalog.get('residency_padding_m',256)
                expected=[k for k,s in sectors.items() if sector_in_range(s,view,padding)]
                actual=index.select(view,padding)
                self.assertEqual([k for k,d in actual],expected)
                rotated=camera(*view[0],heading=73,pitch=55,far=view[-1])
                self.assertEqual(index.select(rotated,padding),actual)
                allowed={k:sectors[k] for k in list(sectors)[::3]}
                self.assertEqual(index.select(view,padding,allowed),[(k,d) for k,d in actual if k in allowed])
            index.close()

    def test_spheres_match_independent_plane_geometry(self):
        rng=random.Random(610)
        for _ in range(12):
            view=camera(rng.uniform(-1000,1000),70,rng.uniform(-1000,1000),rng.uniform(-180,180),rng.uniform(-60,60))
            points=[tuple(view[0][i]+rng.uniform(-1500,1500) for i in range(3)) for _ in range(500)]
            origin,forward,right,up,tangent,aspect,far=view;tx=tangent*aspect
            planes=[(forward,0),(tuple(-v for v in forward),far)]
            for axis,scale in ((right,tx),(up,tangent)):
                for sign in (-1,1):
                    normal=tuple(scale*f+sign*a for f,a in zip(forward,axis));length=math.sqrt(sum(v*v for v in normal))
                    planes.append((tuple(v/length for v in normal),0))
            expected=[all(sum(n*(p-o) for n,p,o in zip(normal,point,origin))+offset>=-1.5 for normal,offset in planes) for point in points]
            self.assertEqual(core.cull_spheres(view,points),expected)
        view=camera();depth=10;tx=view[4]*view[5]
        # A sphere intersects a side plane although its centre exceeds the
        # old unnormalized-radius test. Keep the mesh until Qt clips it.
        point=(depth*tx+1.5*math.sqrt(1+tx*tx)-.001,0,depth)
        self.assertTrue(core.cull_spheres(view,[point])[0])

    def test_raw_abi_rejects_without_partial_writes(self):
        lib=core.library();w=core.Window(123,456,7,9)
        self.assertEqual(lib.ggw_window(float('nan'),0,100,64,C.byref(w)),-1)
        self.assertEqual(w.x,123)
        cells=(core.Cell*1)(core.Cell(777,888))
        self.assertEqual(lib.ggw_grid_candidates(0,0,64,3,cells,1),-1)
        self.assertEqual(cells[0].x,777)
        v=core.view_buffer(camera());spheres=(core.Sphere*2)(core.Sphere((C.c_double*3)(0,0,10),1),core.Sphere((C.c_double*3)(0,float('nan'),10),1))
        flags=(C.c_uint8*2)(7,8)
        self.assertEqual(lib.ggw_cull_spheres(C.byref(v),spheres,2,flags),-1)
        self.assertEqual(list(flags),[7,8])
        self.assertFalse(lib.ggw_cache_create(0));self.assertFalse(lib.ggw_cache_create(core.MAX_ROWS+1))
        cache=core.Residency(2);cache.put(1);cache.put(2)
        expired=(C.c_uint64*1)(999)
        self.assertEqual(lib.ggw_cache_scope(cache.handle,0,0,100,1,expired,1),-1)
        self.assertEqual(cache.stamps(),{1:None,2:None});cache.close()

    def test_closed_handles_fail_in_python(self):
        cache=core.Residency(2);cache.close();cache.close()
        with self.assertRaises(RuntimeError):cache.put(1)
        index=core.SectorIndex({'x':{'min':[0,0,0],'max':[1,1,1]}});index.close()
        with self.assertRaises(RuntimeError):index.select(camera())

    def test_disabled_mode_stays_functional(self):
        code="from backend.game_engine_native_world import status;from backend.game_engine_streaming import SpatialResidencyCache,StreamWindow;c=SpatialResidencyCache(2);c.put('a',1);assert c.backend=='PYTHON';assert StreamWindow.at(-.01,0,88,64).x==-1;print(status()['backend'])"
        result=subprocess.run([sys.executable,'-c',code],cwd=PROJECT,env={**os.environ,'GG_GAME_WORLD_NATIVE':'0'},check=True,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.stdout.strip(),'PYTHON')

    def test_simulation_and_qt_share_atomic_first_load(self):
        code="from concurrent.futures import ThreadPoolExecutor;from threading import Barrier;from backend.game_engine_native_world import status;b=Barrier(12)\ndef load(_):\n b.wait();return status()['backend']\nwith ThreadPoolExecutor(max_workers=12) as pool:assert set(pool.map(load,range(12)))=={'CPP'}\nprint('CONCURRENT_LOAD=PASS')"
        result=subprocess.run([sys.executable,'-c',code],cwd=PROJECT,env=os.environ,check=True,capture_output=True,text=True,timeout=10)
        self.assertIn('CONCURRENT_LOAD=PASS',result.stdout)

    @unittest.skipUnless((PROJECT / "backend/game_client_host.py").is_file(), "Requires optional client fixture")
    def test_qt_client_uses_native_scene_and_sector_selection(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QObject
        from backend.game_client_host import GameClientHost
        self.app=QGuiApplication.instance() or QGuiApplication([])
        host=GameClientHost();node=QObject();host.gameEngineRegisterEntityNode(node,'native-test')
        raw=json.dumps({'x':0,'y':1,'z':0,'heading':0,'pitch':0,'fov':45,'aspect':1.6,'far':10000})
        self.assertTrue(host.gameEngineSetView(raw))
        frame={'schema':'gg.game-engine.render-snapshot.v1','player':{'time_s':1},'render':{'entities':[{'id':'native-test','kind':'NPC','x':0,'y':0,'z':10}]}}
        host._json(frame)
        self.assertEqual(host._scene_driver.culling_backend,'CPP')
        self.assertGreater(host._scene_driver.culling_batches,0)
        self.assertTrue(node.property('nativeVisible'))
        trees=host.gameEngineWorldTrees();self.assertEqual(trees.measurements()['selection_backend'],'CPP')
        host.gameEngineSetView(raw)
        if trees.assets_available:self.assertTrue(trees.wanted)
        else:
            self.assertEqual(trees.wanted,{})
            self.assertEqual(trees.measurements()['map_trees'],0)
        trees.timer.stop();trees.expiry_timer.stop()

    def test_release_core_loads_after_relocation(self):
        import tempfile,shutil
        with tempfile.TemporaryDirectory(prefix='gg-native-relocation-') as tmp:
            root=Path(tmp)
            native=native_directory(PROJECT).relative_to(PROJECT).as_posix()
            for name in ('backend/game_engine_native_world.py','backend/platform_support.py','backend/application_paths.py',
                         native+'/'+native_library_name('gg_world'),native+'/build.json','native/world/gg_world.h','native/world/gg_world.cpp'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(PROJECT/name,target)
            code="import sys;sys.path.insert(0,sys.argv[1]);from backend.game_engine_native_world import status,window_at;assert status()['backend']=='CPP';assert window_at(-.01,0,88,64)[0]==-1;print('RELOCATED_CORE=PASS')"
            result=subprocess.run([sys.executable,'-I','-c',code,str(root)],env=os.environ,check=True,capture_output=True,text=True,timeout=10)
            self.assertIn('RELOCATED_CORE=PASS',result.stdout)

    @unittest.skipUnless((PROJECT / "tools/package_gg_game_release.py").is_file(), "Requires optional client fixture")
    def test_release_includes_binary_source_and_notice(self):
        spec=importlib.util.spec_from_file_location('gg_package_test',PROJECT/'tools/package_gg_game_release.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        names={p.relative_to(PROJECT).as_posix() for p in mod.package_files()}
        self.assertTrue({'backend/native/linux-x86_64/libgg_world.so','backend/native/linux-x86_64/build.json','backend/game_engine_native_world.py','native/world/gg_world.cpp','native/world/gg_world.h','native/world/provenance.json','backend/licenses/engine-MIT.txt'}<=names)

if __name__=='__main__':unittest.main()
