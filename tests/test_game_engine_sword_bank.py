"""Check shipped sword meshes, stable bindings, and curved enchant placement."""
import hashlib,json,math,os,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_assets as assets
from backend.game_engine_sword_designs import SWORDS,sword_effect
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def main():
    authored=ROOT/'qml/assets/authored'
    metadata=json.loads((authored/'items/weapon-sword.variants.json').read_text())
    assert len(metadata)==36 and len({r['name'] for r in metadata})==36
    spec=assets.DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.weapon_sword']
    selected=assets._inspect_static_item_asset('itemmesh.weapon_sword',spec)
    assert selected['status']=='READY',selected.get('error')
    catalog={'static_items':{'itemmesh.weapon_sword':selected}}
    shapes=[]
    for variant,row in enumerate(metadata):
        path=authored/row['source'];document,binary=read_glb(path)
        shape=bytearray();points=[]
        for mesh in document['meshes']:
            for primitive in mesh['primitives']:
                positions,_,_=rows(document,binary,primitive['attributes']['POSITION'])
                normals,_,_=rows(document,binary,primitive['attributes']['NORMAL'])
                assert all(math.isfinite(v) for p in positions+normals for v in p)
                assert all(.98<math.sqrt(sum(v*v for v in p))<1.02 for p in normals)
                points+=positions;shape.extend(b''.join(struct.pack('<3f',*p) for p in positions))
                index=document['accessors'][primitive['indices']];view=document['bufferViews'][index['bufferView']]
                kind={5121:'B',5123:'H',5125:'I'}[index['componentType']]
                offset=view.get('byteOffset',0)+index.get('byteOffset',0)
                indices=struct.unpack_from('<'+str(index['count'])+kind,binary,offset)
                assert len(indices)%3==0 and max(indices)<len(positions)
        shapes.append(hashlib.sha256(shape).digest())
        for material in document['materials']:
            texture=material.get('pbrMetallicRoughness',{}).get('baseColorTexture')
            assert texture,material['name']+' lost its painted image'
        effect=sword_effect(variant)
        assert all(abs(a-b)<1e-5 for a,b in zip(effect['path'][0],effect['base']))
        assert all(abs(a-b)<1e-5 for a,b in zip(effect['path'][-1],effect['tip']))
        for point in effect['path']:
            assert all(min(p[i] for p in points)-.001<=point[i]<=max(p[i] for p in points)+.001 for i in range(3))
        binding=assets.item_binding(catalog,'itemmesh.weapon_sword',0,appearance_index=variant)
        assert binding['source']==path.resolve().as_uri()
        assert binding['weapon_fx']['authored']==effect
        assert assets.item_binding(catalog,'itemmesh.weapon_sword',0,appearance_index=variant)==binding
    assert len(set(shapes))==36
    # Long swords and short daggers must retain different physical lengths.
    assert sword_effect(10)['tip'][1]>sword_effect(9)['tip'][1]*1.8
    assert sword_effect(17)['tip'][1]>sword_effect(32)['tip'][1]*3
    # Adding content definitions must not evict the weapon or raise the number
    # of simultaneously loaded authored items.
    extended=assets.extend_static_items(catalog,{f'itemmesh.extra{i}':spec for i in range(40)})
    assert len(extended['static_items'])==41
    assert extended['item_instance_budget']==24
    assert assets.item_binding(extended,'itemmesh.weapon_sword',24)['mode']!='AUTHORED_STATIC'
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8').replace(/^\.pragma.*$/mg,''),context);
const curved={base:{x:0,y:0,z:0},tip:{x:0,y:1,z:0},path:[{x:0,y:0,z:0},{x:.8,y:.5,z:0},{x:0,y:1,z:0}]};
const particles=[];context.emitWeaponClouds(particles,'ARCANE',curved,0,0);
assert.equal(particles.length,14);assert(particles.some(p=>p.x>.6),'glow stayed on the straight chord');
function distance(p,a,b){const dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy+(p.z-a.z)*dz)/(dx*dx+dy*dy+dz*dz)));return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy,p.z-a.z-t*dz);}
assert(particles.every(p=>Math.min(distance(p,curved.path[0],curved.path[1]),distance(p,curved.path[1],curved.path[2]))<.14),'glow left the curved blade');
const straight=[];context.emitWeaponClouds(straight,'ARCANE',{base:curved.base,tip:curved.tip},0,0);
assert.equal(straight.length,14);assert(straight.every(p=>Math.abs(p.x)<.10));
console.log('CURVED_SWORD_ENCHANT=PASS');
'''
    subprocess.run(['node','-e',script,str(ROOT/'qml/components/engine/WorldFx.js')],check=True)
    print('SWORD_BANK=PASS: 36 distinct painted meshes, stable sources, physical length differences, local blade paths and unchanged runtime instance budget')

if __name__=='__main__':main()
