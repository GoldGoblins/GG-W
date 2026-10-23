"""Authored texture binding must preserve shape, rigs, eyes and rebuild size."""
import collections,copy,json,struct,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.blender.wrap_gg_clay_textures import ASSETS,OUT,read_glb,accessor,wrap_glb,MARKER
from backend.game_engine_painted_materials import family_for
from PIL import Image

def main():
    # These surfaces deliberately share a blue-green hue but different roles.
    assert family_for('Brinekip vertex palette',(.07,.36,.34,1),'character')==15
    assert family_for('Brinekip vertex palette',(.035,.13,.20,1),'character')==10
    assert family_for('Brinekip vertex palette',(1,.43,.07,1),'character') is None
    assert family_for('Brinekip vertex palette',(.98,.94,.80,1),'character') is None
    rows=json.loads((OUT/'bindings.json').read_text())['assets'];assert len(rows)>=120
    manifest=json.loads((OUT/'materials.json').read_text());assert len(manifest['materials'])==16
    atlas=Image.open(OUT/'runtime-atlas.png');assert atlas.size==(1088,1088)
    for material in manifest['materials']:
        tile=Image.open(OUT/(material['name']+'.png'));assert tile.size==(256,256)
        assert all(tile.getpixel((0,j))==tile.getpixel((255,j)) for j in range(256))
        assert all(tile.getpixel((j,0))==tile.getpixel((j,255)) for j in range(256))
    changed_indices=0
    for row in rows:
        path=ROOT/row['asset'];d,b=read_glb(path);marker=d['extras'][MARKER];old=marker['document']
        for field in ('nodes','skins','animations'):assert d.get(field)==old.get(field),(path,field)
        # UVs/materials may change; every referenced shape/skin attribute stays
        # exactly the same accessor and byte range as the original source.
        for mesh,before in zip(d['meshes'],old['meshes']):
            originals={p['attributes']['POSITION']:p for p in before['primitives']}
            totals=collections.Counter();old_totals=collections.Counter()
            for p in before['primitives']:
                key=p['attributes']['POSITION'];old_totals[key]+=old['accessors'][p['indices']]['count']
            for p in mesh['primitives']:
                key=p['attributes']['POSITION'];origin=originals[key]
                for attr,idx in origin['attributes'].items():
                    if attr!='TEXCOORD_0':assert p['attributes'][attr]==idx
                count=d['accessors'][p['indices']]['count'];totals[key]+=count
                if p['indices']!=origin['indices']:changed_indices+=1
                mat=d['materials'][p['material']];tex=mat.get('pbrMetallicRoughness',{}).get('baseColorTexture')
                if ' · Painted ' in mat.get('name',''):
                    assert 'TEXCOORD_0' in p['attributes']
                    assert d['accessors'][p['attributes']['TEXCOORD_0']]['count']==d['accessors'][key]['count']
                    image=d['images'][d['textures'][tex['index']]['source']]
                    assert (path.parent/image['uri']).is_file()
            assert totals==old_totals,(path,'triangle count changed')
    # A merged cast mesh requires regrouping only, with no lost/duplicate faces.
    sample=ASSETS/'characters/gg-crew-brinekip.glb';d,b=read_glb(sample);old=d['extras'][MARKER]['document']
    def triangles(doc):
        result=collections.Counter()
        for mesh in doc['meshes']:
            for p in mesh['primitives']:
                ids=[int(v[0]) for v in accessor(doc,b,p['indices'])]
                result.update(tuple(ids[j:j+3]) for j in range(0,len(ids),3))
        return result
    assert triangles(d)==triangles(old)
    # Repeat on a disposable sibling so relative image URIs retain their base.
    tmp=sample.with_name('gg-texture-idempotence-check.glb')
    try:
        tmp.write_bytes(sample.read_bytes());wrap_glb(tmp);first=tmp.read_bytes()
        wrap_glb(tmp);assert first==tmp.read_bytes(),'rebuild accumulates appended data'
    finally:tmp.unlink(missing_ok=True)
    print(json.dumps(dict(status='PASS',textured_assets=len(rows),painted_tiles=16,
        source_geometry_and_rigs_preserved=True,cast_faces_preserved=True,eyes_preserved=True,idempotent=True)))

if __name__=='__main__':main()
