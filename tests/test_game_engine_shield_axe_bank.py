"""Verify shipped equipment geometry, physical variety and scythe attachment."""
import hashlib,json,math,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_assets as assets
from backend.game_engine_shield_axe_designs import SHIELDS,AXES,equipment_visual
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def main():
    authored=ROOT/'qml/assets/authored';bounds={};max_vertices=0;max_triangles=0
    for family,designs in (('shield',SHIELDS),('axe',AXES)):
        metadata=json.loads((authored/'items'/f'weapon-{family}.variants.json').read_text())
        assert len(metadata)==36 and len({r['name'] for r in metadata})==36
        asset_id='itemmesh.weapon_'+family
        selected=assets._inspect_static_item_asset(asset_id,assets.DEFAULT_STATIC_ITEM_ASSET_SPECS[asset_id])
        assert selected['status']=='READY',selected.get('error')
        catalog={'static_items':{asset_id:selected}};shapes=[]
        for variant,row in enumerate(metadata):
            assert row['name']==designs[variant][0]
            path=authored/row['source'];document,binary=read_glb(path)
            points=[];shape=bytearray();steel_points=[];vertex_count=0;triangle_count=0
            for mesh in document['meshes']:
                for primitive in mesh['primitives']:
                    pos,_,_=rows(document,binary,primitive['attributes']['POSITION'])
                    normals,_,_=rows(document,binary,primitive['attributes']['NORMAL'])
                    tex=document['accessors'][primitive['attributes']['TEXCOORD_0']];tex_view=document['bufferViews'][tex['bufferView']]
                    assert tex['componentType']==5126 and tex['type']=='VEC2'
                    tex_start=tex_view.get('byteOffset',0)+tex.get('byteOffset',0);tex_stride=tex_view.get('byteStride',8)
                    uv=[struct.unpack_from('<2f',binary,tex_start+i*tex_stride) for i in range(tex['count'])]
                    assert all(math.isfinite(v) for p in pos+normals+uv for v in p)
                    assert all(.98<math.sqrt(sum(v*v for v in p))<1.02 for p in normals)
                    assert len({tuple(round(x,5) for x in p) for p in uv})>2
                    points+=pos;shape.extend(b''.join(struct.pack('<3f',*p) for p in pos));vertex_count+=len(pos)
                    accessor=document['accessors'][primitive['indices']];view=document['bufferViews'][accessor['bufferView']]
                    kind={5121:'B',5123:'H',5125:'I'}[accessor['componentType']]
                    offset=view.get('byteOffset',0)+accessor.get('byteOffset',0)
                    indices=struct.unpack_from('<'+str(accessor['count'])+kind,binary,offset)
                    assert len(indices)%3==0 and max(indices)<len(pos);triangle_count+=len(indices)//3
                    for a,b,c in zip(indices[::3],indices[1::3],indices[2::3]):
                        ab=[pos[b][i]-pos[a][i] for i in range(3)];ac=[pos[c][i]-pos[a][i] for i in range(3)]
                        cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
                        assert sum(v*v for v in cross)>1e-20,(family,variant,'collapsed triangle')
                    material=document['materials'][primitive['material']]
                    pbr=material['pbrMetallicRoughness'];assert pbr.get('baseColorTexture'),material['name']
                    if all(abs(a-b)<1e-5 for a,b in zip(pbr['baseColorFactor'][:3],(.40,.53,.59))):steel_points+=pos
            assert vertex_count<12000 and triangle_count<10000
            max_vertices=max(max_vertices,vertex_count);max_triangles=max(max_triangles,triangle_count)
            shapes.append(hashlib.sha256(shape).digest())
            bounds[family,variant]=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
            assert bounds[family,variant][2]>.09,'lost thickness or rear grip'
            binding=assets.item_binding(catalog,asset_id,0,appearance_index=variant)
            assert binding['source']==path.resolve().as_uri()
            assert binding['appearance_name']==row['name']
            assert assets.item_binding(catalog,asset_id,0,appearance_index=variant)==binding
            if family=='axe':
                effect=equipment_visual(family,variant)['weapon_fx']['authored']
                assert binding['weapon_fx']['authored']==effect
                assert effect['base']==effect['path'][0] and effect['tip']==effect['path'][-1]
                for point in effect['path']:
                    assert all(min(p[i] for p in points)-.002<=point[i]<=max(p[i] for p in points)+.002 for i in range(3))
                if row['weapon_subtype']=='scythe':
                    # Steel end cap is part of the real blade, independent of
                    # socket/brass primitives. The previous floating blade
                    # began 15-22 cm away from its shaft eye.
                    joint=row['blade_attachment']
                    assert min(math.dist(joint,p) for p in steel_points)<.060,(variant,'blade detached')
                    assert math.dist(effect['base'],joint)<.080,(variant,'FX root detached')
        assert len(set(shapes))==36
        assert assets.item_binding(catalog,asset_id,24)['mode']!='AUTHORED_STATIC'
    scythes=[r for r in json.loads((authored/'items/weapon-axe.variants.json').read_text()) if r['weapon_subtype']=='scythe']
    assert len(scythes)==6
    assert [r['wielding_reference'] for r in scythes].count('1H')==3
    assert [r['wielding_reference'] for r in scythes].count('2H')==3
    assert bounds['shield',7][1]>bounds['shield',0][1]*2.5,'tower and buckler lost their relative size'
    assert bounds['axe',33][1]>bounds['axe',30][1]*1.6,'1H and 2H scythes lost their relative size'
    assert assets.MAX_AUTHORED_ITEM_INSTANCES==24
    print(f'SHIELD_AXE_BANK=PASS: 72 painted meshes, 6 connected scythes, stable bindings, max {max_vertices} vertices / {max_triangles} triangles, 24 runtime instances')

if __name__=='__main__':main()
