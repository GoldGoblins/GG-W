"""Behavior checks for GgEngine-derived residency and native flora streaming."""
import json, os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend.game_engine_ecology import FloraStreamer, GROUP_KEYS, MAX_CACHE_CELLS, biome_at, TREE_SPECIES
from backend.game_engine_streaming import SpatialResidencyCache, StreamWindow
from backend.game_engine_terrain import DEFAULT_WORLD_SEED, height_at


def settle(stream, x, z, profile="PS2_CLASSIC", revision=0):
    for _ in range(2200):
        view = stream.update(x,z,profile=profile,terrain_revision=revision,height_at=height_at)
        if view["pending_cells"] == 0:
            return view
    raise AssertionError("flora preload never settles")


def main():
    # Low shores keep their climate; neither arctic nor ash islands get palms.
    assert biome_at(-5450, -6025, 3) == "VOLCANIC"
    assert biome_at(-100, 9175, 3) == "TAIGA"
    window = StreamWindow.at(-.01,-64.01,256,64)
    assert (window.x,window.z)==(-1,-2)
    assert window.inner==5 and window.outer==8
    assert all(window.keeps(cell) for cell in window.wanted())
    assert window.keeps((window.x+9,window.z)) and not window.keeps((window.x+10,window.z))
    cache=SpatialResidencyCache(2);cache.put("tree",1)
    assert cache.scope((0,0),100,0)==0
    assert cache.scope((500,0),100,29)==0
    assert cache.scope((500,0),100,30)==1
    cache.put("a",1);cache.put("b",2);cache.fetch("a");cache.put("c",3)
    assert list(cache)==["a","c"] and len(cache.stamps)==2

    a=FloraStreamer(DEFAULT_WORLD_SEED);v=settle(a,-7350,200)
    assert v["trees"]==0 and 0<v["ground"]<=256
    assert v['ground_distance_m']==88
    assert v['world_trees']=='FIXED_MAP_SECTORS_TERRAIN_CAMERA_FAR_PLANE'
    assert len(a.cache)<=MAX_CACHE_CELLS and set(a.groups)<=set(GROUP_KEYS)
    assert all(a.groups.values()) and sum(map(len,a.groups.values()))==v['ground']
    initial={r["id"]:(r["x"],r["y"],r["z"],r["yaw"],key) for key,rows in a.groups.items() for r in rows}
    # Settled snapshots must not sample any terrain or recompile placements.
    def forbidden_sample(*args):raise AssertionError("terrain sampled while settled")
    old_revision=v["revision"]
    settled=a.update(-7350,200,profile="PS2_CLASSIC",terrain_revision=0,height_at=forbidden_sample)
    assert settled["revision"]==old_revision
    # Leaving and returning reconstructs the same positions, not new RNG.
    settle(a,7200,100);settle(a,-7350,200)
    returned={r["id"]:(r["x"],r["y"],r["z"],r["yaw"],key) for key,rows in a.groups.items() for r in rows}
    assert initial==returned
    for rows in a.groups.values():
        for row in rows:
            assert row['species'] not in TREE_SPECIES
            assert 5.6 <= row['scale'] < 8.82 if row['species'] in TREE_SPECIES else .8 <= row['scale'] < 1.26
            assert row["ground_height_m"]>=1.2
            assert max(abs(row["x"]),abs(row["z"]))>=92
            assert abs(height_at(row["x"],row["z"])-row["ground_height_m"])<1e-8
    b=FloraStreamer(DEFAULT_WORLD_SEED);settle(b,-7350,200)
    assert a.groups==b.groups
    # A terrain edit cancels the partial job and all previous terrain samples.
    empty=a.update(-7350,200,profile="POTATO",terrain_revision=1,height_at=lambda x,z:-10)
    assert empty["instance_count"]==0 and empty["resident_cells"]==0

    from PySide6.QtGui import QGuiApplication, QVector3D
    from backend.game_engine_ecology_render import FloraRenderCache
    app=QGuiApplication.instance() or QGuiApplication([])
    renderer=FloraRenderCache()
    manifest=json.loads((PROJECT/"qml/assets/authored/flora/flora-kit.asset.json").read_text())
    for key in GROUP_KEYS:
        geometry=renderer.geometry(key);assert geometry is not None
        assert len(bytes(geometry.indexData()))==manifest["assets"][key]["triangles"]*12
    for key,rows in b.groups.items():
        if not rows:continue
        table=renderer.table(key,rows,b._revision)
        assert table.instancePosition(0).distanceToPoint(QVector3D(rows[0]["x"],rows[0]["y"],rows[0]["z"]))<.001
        original=bytes(table.getInstanceBuffer()[0])
        assert len(original)==len(rows)*80
        assert renderer.table(key,rows,b._revision+1) is table
        assert bytes(table.getInstanceBuffer()[0])==original
    print(json.dumps({"status":"PASS","trees":v["trees"],"ground":v["ground"],"meshes":len(renderer.meshes),"checks":"residency, memory cap, seed/return, water/cliffs/village, terrain invalidation, zero settled sampling, native instance ABI"}))
    return 0

if __name__=="__main__":raise SystemExit(main())
