"""Shipped gun surfaces, open muzzles, proportions and real dual-hand state."""
import copy,hashlib,json,math,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_assets as assets,game_engine_items as items
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_pistol_designs import PISTOLS
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def indices(document,binary,accessor_id):
    acc=document['accessors'][accessor_id];view=document['bufferViews'][acc['bufferView']]
    return struct.unpack_from('<'+str(acc['count'])+{5121:'B',5123:'H',5125:'I'}[acc['componentType']],binary,view.get('byteOffset',0)+acc.get('byteOffset',0))

def ray_x_hit(triangle,y,z):
    """Intersection of the bore axis with a real exported triangle, in Y/Z."""
    a,b,c=triangle
    by,bz=b[1]-a[1],b[2]-a[2];cy,cz=c[1]-a[1],c[2]-a[2]
    determinant=by*cz-bz*cy
    if abs(determinant)<1e-12:return None
    dy,dz=y-a[1],z-a[2]
    u=(dy*cz-dz*cy)/determinant;v=(by*dz-bz*dy)/determinant
    if u<0 or v<0 or u+v>1:return None
    return a[0]+u*(b[0]-a[0])+v*(c[0]-a[0])

def check_meshes():
    root=ROOT/'qml/assets/authored';metadata=json.loads((root/'items/weapon-pistol.variants.json').read_text())
    assert len(metadata)==36 and len({row['name'] for row in metadata})==36
    spec=assets._inspect_static_item_asset('itemmesh.weapon_pistol',assets.DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.weapon_pistol'])
    assert spec['status']=='READY',spec
    catalog={'static_items':{'itemmesh.weapon_pistol':spec}}
    shapes=[];bounds={};max_vertices=0;max_triangles=0
    for variant,row in enumerate(metadata):
        assert row['name']==PISTOLS[variant][0]
        document,binary=read_glb(root/row['source']);points=[];triangles=[];shape=bytearray();count=0
        for mesh in document['meshes']:
            for primitive in mesh['primitives']:
                pos,_,_=rows(document,binary,primitive['attributes']['POSITION'])
                normal,_,_=rows(document,binary,primitive['attributes']['NORMAL'])
                assert all(math.isfinite(v) for p in pos+normal for v in p)
                assert all(.98<math.sqrt(sum(v*v for v in p))<1.02 for p in normal)
                uv=document['accessors'][primitive['attributes']['TEXCOORD_0']]
                assert uv['type']=='VEC2' and uv['count']==len(pos)
                material=document['materials'][primitive['material']]
                assert material['pbrMetallicRoughness'].get('baseColorTexture'),(variant,material['name'])
                order=indices(document,binary,primitive['indices'])
                assert len(order)%3==0 and max(order)<len(pos)
                for a,b,c in zip(order[::3],order[1::3],order[2::3]):
                    ab=[pos[b][i]-pos[a][i] for i in range(3)];ac=[pos[c][i]-pos[a][i] for i in range(3)]
                    cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
                    assert sum(v*v for v in cross)>1e-20,(variant,'collapsed triangle')
                    triangles.append((pos[a],pos[b],pos[c]))
                points+=pos;count+=len(pos);shape.extend(b''.join(struct.pack('<3f',*p) for p in pos))
        assert count<12000 and len(triangles)<10000,(variant,count,len(triangles))
        max_vertices=max(max_vertices,count);max_triangles=max(max_triangles,len(triangles))
        shapes.append(hashlib.sha256(shape).digest())
        bounds[variant]=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
        assert bounds[variant][2]>.08,'lost barrel thickness'
        binding=assets.item_binding(catalog,'itemmesh.weapon_pistol',0,appearance_index=variant)
        assert binding['source']==(root/row['source']).resolve().as_uri()
        assert binding['appearance_name']==row['name']
        assert assets.item_binding(catalog,'itemmesh.weapon_pistol',0,appearance_index=variant)==binding
        effect=row['weapon_fx']['authored']
        assert len(effect['path'])==5 and effect['path'][0]==effect['base'] and effect['path'][-1]==effect['tip']
        assert binding['weapon_fx']['authored']==effect
        for point in effect['path']:
            assert all(min(p[i] for p in points)-.002<=point[i]<=max(p[i] for p in points)+.002 for i in range(3))
        for x,y,z in row['muzzle_points']:
            hits=[value for tri in triangles if (value:=ray_x_hit(tri,y,z)) is not None and value<=x+.002]
            assert hits and x-max(hits)>.004,(variant,'muzzle capped',x-max(hits) if hits else None)
        actual_glow=any(any(float(v)>0 for v in m.get('emissiveFactor',[])) for m in document['materials'])
        assert actual_glow==bool(row.get('emissive_feature')),(variant,'exported emissive mismatch')
    assert len(set(shapes))==36
    for variant in (1,12):
        assert bounds[variant][0]/bounds[variant][1]>1.6,(variant,'1911 grip dominates slide',bounds[variant])
    assert len(metadata[2]['muzzle_points'])==4 and len(metadata[21]['muzzle_points'])==6
    assert len({p[1] for p in metadata[2]['muzzle_points']})==1
    assert len({p[2] for p in metadata[2]['muzzle_points']})==4,'duckfoot barrels stacked vertically'
    assert bounds[10][0]>bounds[1][0]*2,'shotgun did not retain a long stock/barrel'
    assert len(metadata[10]['muzzle_points'])==2
    assert assets.item_binding(catalog,'itemmesh.weapon_pistol',24)['mode']!='AUTHORED_STATIC'
    print(f'PISTOL_MESHES=PASS: 36 originals, open bores, long 1911 proportions, max {max_vertices} vertices / {max_triangles} triangles')

def check_equipment():
    runtime=GameEngineRuntime()
    try:
        ids={name:next(f'{name}-{i}' for i in range(10000) if items.item_appearance_index(f'{name}-{i}')==variant) for name,variant in (('a',1),('b',12),('c',9),('long',10))}
        for name in ids.values():
            runtime._item_instances[name]=items.make_instance(runtime._item_catalog,name,'item.weapon_pistol')
        runtime._item_instances['qa-axe']=items.make_instance(runtime._item_catalog,'qa-axe','item.weapon_axe')
        assert runtime.equip_item(ids['a'])['item_result']['slot']=='MAIN_HAND'
        assert runtime.equip_item(ids['b'])['item_result']['slot']=='OFF_HAND'
        for name,key in ((ids['a'],'enchant.ember_edge'),(ids['b'],'enchant.storm_edge')):
            result=runtime.enchant_gear(name,key)
            assert not result.get('error'),result.get('error')
        snapshot=runtime.snapshot();worn={r['equipped_slot']:r for r in snapshot['items']['equipment']}
        assert worn['MAIN_HAND']['instance_id']==ids['a'] and worn['OFF_HAND']['instance_id']==ids['b']
        assert worn['MAIN_HAND']['attachment']['node']=='SOCKET_MAIN_HAND'
        assert worn['OFF_HAND']['attachment']['node']=='SOCKET_OFF_HAND'
        assert worn['OFF_HAND']['equip_slots']==['MAIN_HAND','OFF_HAND']
        effects=runtime._player_combat_profile_locked()['enchant_effects']
        assert {e['source_id'] for e in effects}>={'enchant.ember_edge','enchant.storm_edge'}
        before=copy.deepcopy(runtime._item_instances)
        assert runtime.equip_item('qa-axe','OFF_HAND')['error']=='ITEM_EQUIP_SLOT_INCOMPATIBLE'
        assert runtime.equip_item(ids['c'],'HEAD')['error']=='ITEM_EQUIP_SLOT_INCOMPATIBLE'
        assert runtime._item_instances==before
        runtime.save_state();runtime.reset();restored=runtime.load_state()
        worn={r['equipped_slot']:r for r in restored['items']['equipment']}
        assert worn['MAIN_HAND']['instance_id']==ids['a'] and worn['OFF_HAND']['instance_id']==ids['b']
        assert len(worn['OFF_HAND']['gear']['enchantments'])==1
        result=runtime.equip_item(ids['c'],'OFF_HAND')
        assert result['item_result']['slot']=='OFF_HAND'
        assert runtime._item_instances[ids['a']]['location']=='EQUIPPED'
        assert runtime._item_instances[ids['b']]['location']=='INVENTORY'
        assert runtime._item_instances[ids['c']]['location']=='EQUIPPED'
        assert runtime.equip_item(ids['long'],'OFF_HAND')['error']=='ITEM_EQUIP_SLOT_INCOMPATIBLE'
        two_handed=runtime.equip_item(ids['long'])
        assert not two_handed.get('error'),two_handed.get('error')
        assert not any(r['equipped_slot']=='OFF_HAND' for r in two_handed['items']['equipment'])
        assert runtime.equip_item(ids['b'],'OFF_HAND')['error']=='ITEM_EQUIP_TWO_HANDS_OCCUPIED'
        print('AKIMBO_STATE=PASS: explicit and automatic hands, rejection without mutation, enchants and save/load')
    finally:runtime.shutdown()

if __name__=='__main__':check_meshes();check_equipment()
