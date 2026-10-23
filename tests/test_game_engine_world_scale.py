"""Larger geography must match rendering, collision, quests and bounded pools."""
from __future__ import annotations
import json
import math
import mmap
import struct
import sys
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from backend import game_engine_planet as planet, game_engine_world as world
from backend import game_engine_terrain as terrain
from backend import game_engine_assets as assets
from backend.game_engine_host import GameEngineRuntime,FIXED_DT,MAX_ENTITIES,MAX_RENDER_CHUNKS
ASSETS=PROJECT/"qml/assets/authored/world"


def glb_doc(path):
    with path.open("rb") as f:
        header=f.read(20);magic,version,total,n,kind=struct.unpack("<IIIII",header)
        assert magic==0x46546C67 and version==2 and total==path.stat().st_size
        return json.loads(f.read(n)),28+n


def triangles(doc):
    return sum(doc["accessors"][p["indices"]]["count"]//3
        for mesh in doc["meshes"] for p in mesh["primitives"])


def mesh_top(doc,node):
    mesh=doc["meshes"][node["mesh"]]
    return max(doc["accessors"][p["attributes"]["POSITION"]]["max"][1]
               for p in mesh["primitives"])*node.get("scale",[1,1,1])[1]+node["translation"][1]


def check_coastal_architecture():
    before,_=glb_doc(ASSETS/"gg-sandover-island-environment-large.glb")
    after,_=glb_doc(ASSETS/"gg-sandover-island-environment-coastal-v3.glb")
    old={n["name"]:n for n in before["nodes"] if "mesh" in n}
    new={n["name"]:n for n in after["nodes"] if "mesh" in n}
    assert len(old)==len(new)==23 and old.keys()==new.keys()
    houses=0
    for name,node in old.items():
        replacement=new[name]
        assert max(abs(a-b) for a,b in zip(node["translation"],replacement["translation"]))<2e-5
        assert abs(mesh_top(before,node)-mesh_top(after,replacement))<2e-5
        if name.startswith("Preview_Hut_"):
            houses+=1
            assert "Coastal_" in after["meshes"][replacement["mesh"]]["name"]
            # +Z-up Blender front becomes -Z in GLTF; rotate it toward the village.
            q=replacement.get("rotation",[0,0,0,1]);yaw=2*math.atan2(q[1],q[3])
            x,z=replacement["translation"][0],replacement["translation"][2]
            assert (-math.sin(yaw))*(-x)+(-math.cos(yaw))*(-z)>0
        else:
            assert max(abs(a-b) for a,b in zip(node.get("scale",[1,1,1]),replacement.get("scale",[1,1,1])))<1e-6
    assert houses==7
    for spec in assets.AUTHORED_WORLD_VARIANTS["HOUSE"]:
        assert spec["source"].name.startswith("gg-coastal-")
        doc,_=glb_doc(spec["source"])
        assert 1000<triangles(doc)<2000
        assert abs(mesh_top(doc,{**doc["nodes"][0],"translation":[0,0,0]})-3.68)<1e-5


def main():
    check_coastal_architecture()
    atlas=planet.map_contract()
    assert atlas["bounds_m"]["max_x"]-atlas["bounds_m"]["min_x"]==26500
    assert world.island_half_extent_m()*2==499.5
    original,_=glb_doc(ASSETS/"gg-sandover-planet-surface.glb")
    expanded,base=glb_doc(ASSETS/"gg-sandover-planet-surface-landscape.glb")
    assert triangles(original)==triangles(expanded)==2158648
    path=ASSETS/"gg-sandover-planet-surface-landscape.glb"
    samples=0;max_error=0
    with path.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        for mesh in expanded["meshes"]:
            primitive=mesh["primitives"][0]
            a=expanded["accessors"][primitive["attributes"]["POSITION"]]
            view=expanded["bufferViews"][a["bufferView"]]
            offset=base+view.get("byteOffset",0)+a.get("byteOffset",0)
            stride=view.get("byteStride",12)
            for i in range(0,a["count"],max(1,a["count"]//20)):
                x,y,z=struct.unpack_from("<fff",data,offset+i*stride)
                radius=world.DEFAULT_PLANET_RADIUS_METERS
                height=math.sqrt((radius+y)**2+x*x+z*z)-radius
                if height<3:continue
                error=abs(height-terrain.height_at(x,z));max_error=max(error,max_error);samples+=1
                assert error<.001,(mesh.get("name"),x,z,error)
    assert samples>100
    old_env,_=glb_doc(ASSETS/"gg-sandover-island-environment.glb")
    new_env,_=glb_doc(ASSETS/"gg-sandover-island-environment-large.glb")
    assert triangles(old_env)==triangles(new_env)
    for old,new in zip(old_env["nodes"],new_env["nodes"]):
        for axis in (0,2):
            assert abs(new["translation"][axis]*world.WORLD_PROP_SCALE
                -old["translation"][axis]*world.ISLAND_LAYOUT_SCALE)<1e-8
    runtime=GameEngineRuntime()
    try:
        for region in atlas["landmasses"]:
            runtime.explore_region(region["id"])
            x,z=runtime._x[0],runtime._z[0]
            with runtime._lock:
                runtime._running=True;runtime._tick_locked(FIXED_DT);runtime._running=False
            assert abs(runtime._x[0]-x)<.01 and abs(runtime._z[0]-z)<.01,"Old 2 km boundary remains"
            assert runtime._y[0]>terrain.height_at(x,z)
        runtime.reset()
        assert not any(runtime._kind[i]=="RAMP" for i in range(MAX_ENTITIES) if runtime._alive[i])
        assert runtime._sy[0]==1 and runtime._sx[0]==1 and runtime._sz[0]==1
        for quest in runtime._quest_catalog.values():
            objective=quest.get("objective",{})
            if objective.get("kind")!="VISIT":continue
            target=objective.get("target_id","")
            if target=="landmark.cove-waterwheel":
                assert objective["location"]=={"x":83.25,"z":-120.25}
        snapshot=runtime.snapshot()
        assert len(snapshot["render"]["entities"])<=96
        assert len(snapshot["terrain"]["cells"])<=MAX_RENDER_CHUNKS
        assert len(runtime._alive)==MAX_ENTITIES
    finally:runtime.shutdown()
    print(f"GAME_ENGINE_WORLD_SCALE_TEST=PASS ({samples} mesh/terrain points, max error {max_error:.6f} m, triangle count preserved)")

if __name__=="__main__":main()
