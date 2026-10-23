"""Shipped botanical geometry, climate selection and saved tree identities."""
import gzip,hashlib,json,math,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.game_engine_botanical_designs import FLOWERS,TREES,FOLIAGE,TREE_VARIANTS,FOLIAGE_BIOMES,tree_variant,foliage_variant
from backend.game_engine_ecology_render import instance_bytes
from tools.world.scale_sandover_environment import read_glb

AUTH=ROOT/'qml/assets/authored'

def native(path):
    data=path.read_bytes();magic,stride,nv,ni=struct.unpack_from('<8sIII',data)
    assert magic==b'GGFLORA1' and stride==40 and 0<nv<=12000,(path.name,nv)
    assert ni%3==0 and len(data)==20+nv*40+ni*4,path.name
    shape=bytearray()
    for i in range(nv):
        vertex=struct.unpack_from('<10f',data,20+i*40)
        assert all(math.isfinite(v) for v in vertex),path.name
        assert .98<math.sqrt(sum(v*v for v in vertex[3:6]))<1.02,path.name
        shape.extend(struct.pack('<3f',*vertex[:3]))
    assert max(struct.unpack_from('<'+str(ni)+'I',data,20+nv*40))<nv,path.name
    return hashlib.sha256(shape).digest()

def main():
    from backend.game_engine_painted_materials import family_for
    assert family_for('Lila iris painted petals',(.49,.27,.74),'flora')==15
    assert family_for('Goblin eye iris',(.49,.27,.74),'character') is None
    bank=json.loads((AUTH/'variants/biodiversity.catalog.json').read_text())['families']
    for family,roster in (('oak',TREES),('flowers',FLOWERS),('fern',FOLIAGE)):
        entries=bank['flora/'+family]['variants']
        assert len(entries)==36 and len({r[0] for r in roster})==36
        assert [e['design'] for e in entries]==[r[0] for r in roster]
        assert len({native(AUTH/'flora'/e['parts']['body']['compiled']) for e in entries})==36
        for entry in entries:
            document,_=read_glb(AUTH/entry['source'])
            assert document.get('images') and document.get('textures'),entry['design']
            assert all(m.get('pbrMetallicRoughness',{}).get('baseColorTexture') for m in document['materials']),entry['design']
    # White/yellow/red/blue flowers and their constructions survive curation.
    by_name={r[0]:r for r in FLOWERS}
    assert by_name['Prästkrage'][2][0]>.9 and by_name['Prästkrage'][2][2]>.8
    assert by_name['Solros'][2][0]>.9 and by_name['Solros'][2][2]<.15
    assert by_name['Vallmo'][2][0]>.9 and by_name['Vallmo'][2][2]<.2
    assert by_name['Blåklint'][2][2]>.8 and by_name['Blåklint'][2][0]<.3
    assert len({r[1] for r in FLOWERS})>=28
    for family,choices in TREE_VARIANTS.items():
        selected={tree_variant('tree:'+str(i),family) for i in range(1000)}
        assert selected==set(choices),(family,selected)
        for v in choices:
            native(AUTH/'flora'/(family+('' if not v else '-v'+str(v))+'-lod0.ggmesh'))
        for identity in ('fixed:1','fixed:2'):
            assert tree_variant(identity,family)==tree_variant(identity,family)
    for biome in FOLIAGE_BIOMES:
        for family in ('fern','scrub','grass'):
            assert {foliage_variant(str(i),family,biome) for i in range(100)}<=set(FOLIAGE_BIOMES[biome])
    # Every near matrix matches its saved tree and its climate-correct mesh.
    world=AUTH/'world/trees';catalog=json.loads((world/'world-trees.catalog.json').read_text())
    count=0
    with (world/catalog['data_file']).open('rb') as data:
        for sector,spec in catalog['sectors'].items():
            rows=json.loads(gzip.decompress((world/(sector.replace(':','_')+'.json.gz')).read_bytes()))
            count+=len(rows)
            for species,group in spec['groups'].items():
                assert sum(v['count'] for v in group['near_variants'])==group['count']
                for batch in group['near_variants']:
                    expected=[r for r in rows if r['species']==species
                        and [math.floor(r['x']/128),math.floor(r['z']/128)]==batch['chunk']
                        and tree_variant(r['id'],species)==batch['variant']]
                    data.seek(batch['offset'])
                    assert data.read(batch['count']*80)==b''.join(instance_bytes(r) for r in expected)
    assert count==catalog['tree_count']
    print('BOTANICAL_BANKS=PASS: 108 curated designs, valid painted meshes, climate selection and '+str(count)+' saved tree positions')

if __name__=='__main__':main()
