"""Tiny independently authored binary assets for reader and GPU verification.

No game installation data. MPQ table encryption follows the upstream
MIT/Apache-2.0 Storm algorithm in native/engine-formats/crates/engine-mpq.
"""
import struct,zlib
from pathlib import Path

def chunk(name,payload):return name[::-1].encode()+struct.pack('<I',len(payload))+payload

def blp(compression=3,alpha_bits=8,alpha_type=0,width=2,height=2,levels=None,palette=None):
    if levels is None:levels=[bytes([36,176,240,255])*width*height]
    header=bytearray(148);header[:4]=b'BLP2';struct.pack_into('<I4BII',header,4,1,compression,alpha_bits,alpha_type,int(len(levels)>1),width,height)
    payload=bytearray(palette or bytes(1024))
    for i,level in enumerate(levels):
        struct.pack_into('<I',header,20+4*i,148+len(payload));struct.pack_into('<I',header,84+4*i,len(level));payload.extend(level)
    return bytes(header+payload)

def tga(width=2,height=2,pixels=None,kind=2,bpp=32,descriptor=0x28,palette=None):
    header=bytearray(18);header[2]=kind;struct.pack_into('<HHBB',header,12,width,height,bpp,descriptor)
    if palette is not None:header[1]=1;struct.pack_into('<HB',header,5,len(palette)//4,32)
    return bytes(header)+(palette or b'')+(pixels if pixels is not None else bytes([220,160,50,255])*width*height)

# A triangular panel in the original Z-up basis, facing +Y in Qt after conversion.
POSITIONS=[(-1,0,-1),(1,0,-1),(0,0,1)]
NORMALS=[(0,-1,0)]*3
UV=[(0,1),(1,1),(.5,0)]
def m2(texture='gold.blp',blend=0,invalid_index=False):
    data=bytearray(0x150);data[:4]=b'MD20';struct.pack_into('<I',data,4,256)
    def append_array(header_offset,count,blob):
        offset=len(data);data.extend(blob);struct.pack_into('<II',data,header_offset,count,offset);return offset
    vertices=bytearray()
    for position,normal,uv in zip(POSITIONS,NORMALS,UV):
        vertex=bytearray(48);struct.pack_into('<3f',vertex,0,*position);struct.pack_into('<3f2f',vertex,20,*normal,*uv);vertices.extend(vertex)
    append_array(68,3,vertices)
    view=append_array(76,1,bytes(44))
    append_array(view,3,struct.pack('<3H',2,0,1)) # mapping deliberately differs from triangles
    append_array(view+8,3,struct.pack('<3H',1,2,99 if invalid_index else 0))
    section=bytearray(32);struct.pack_into('<H',section,10,3);append_array(view+24,1,section)
    batch=bytearray(24);struct.pack_into('<H',batch,8,0xffff);struct.pack_into('<H',batch,14,1);append_array(view+32,1,batch)
    append_array(0x84,1,struct.pack('<HH',5,blend)) # unlit + two sided
    append_array(0x94,1,struct.pack('<H',0))
    append_array(0x9c,1,struct.pack('<H',0)) # explicit UV stage, not environment reflection
    name=texture.encode()+b'\0';offset=len(data);data.extend(name)
    append_array(0x5c,1,struct.pack('<4I',0,1,len(name),offset)) # U repeats, V clamps
    return bytes(data)

def animated_m2(*,looping=True,step=False,global_sequence=False,blend=0,camera=True,rotation=False):
    data=bytearray(m2(blend=blend))
    def array(header,count,blob):
        offset=len(data);data.extend(blob);struct.pack_into('<II',data,header,count,offset);return offset
    sequence=bytearray(68);struct.pack_into('<H',sequence,0,7);struct.pack_into('<II',sequence,4,0,1000);struct.pack_into('<I',sequence,16,int(not looping))
    array(0x1c,1,sequence)
    bone=bytearray(108);struct.pack_into('<iIh',bone,0,-1,0,-1)
    for offset in (12,40,68):struct.pack_into('<Hh',bone,offset,int(not step),-1)
    at=array(0x34,1,bone);channel=at+(40 if rotation else 12)
    array(channel+12,2,struct.pack('<II',0,1000))
    array(channel+20,2,struct.pack('<8f',0,0,0,1,0,0,1,0) if rotation else struct.pack('<6f',0,0,0,1,0,0))
    if global_sequence:
        array(0x14,1,struct.pack('<I',1000));struct.pack_into('<h',data,channel+2,0)
    vertex_offset=struct.unpack_from('<I',data,72)[0]
    for i in range(3):data[vertex_offset+i*48+12]=255
    struct.pack_into('<6f',data,0xb4,-1,0,-1,2,0,1)
    if camera:
        record=bytearray(124);struct.pack_into('<i3f',record,0,0,.61,100,.1)
        for offset in (16,56,96):struct.pack_into('<h',record,offset+2,-1)
        struct.pack_into('<3f',record,44,0,-4.2,0)
        cam=array(0x124,1,record)
        struct.pack_into('<H',data,cam+16,1)
        array(cam+28,2,struct.pack('<II',0,1000))
        array(cam+36,2,struct.pack('<18f',*( [0]*9+[1,0,0]+[0]*6)))
    return bytes(data)

def event_m2(events=None,*,looping=True,rigged=True):
    """Authored 44-byte M2 events with raw bone-local markers and timestamps."""
    data=bytearray(animated_m2(looping=looping,camera=False))
    if not rigged:struct.pack_into('<II',data,0x34,0,0)
    events=events if events is not None else [('$SND',150,0,(1,2,3),(0,250,750,1000))]
    records=bytearray()
    for tag,kit,bone,position,times in events:
        at=len(data);data.extend(struct.pack('<'+str(len(times))+'I',*times))
        record=bytearray(44);record[:4]=tag.encode();struct.pack_into('<II3f',record,4,kit,bone,*position)
        struct.pack_into('<h',record,26,-1);struct.pack_into('<II',record,36,len(times),at);records.extend(record)
    at=len(data);data.extend(records);struct.pack_into('<II',data,0x114,len(events),at)
    return bytes(data)

def material_m2():
    data=bytearray(animated_m2(blend=2))
    def array(header,count,blob):
        offset=len(data);data.extend(blob);struct.pack_into('<II',data,header,count,offset);return offset
    def track(offset,values,width):
        struct.pack_into('<Hh',data,offset,1,-1)
        array(offset+12,2,struct.pack('<II',0,1000));array(offset+20,2,struct.pack('<'+str(len(values))+width,*values))
    colors=array(0x54,1,bytes(56));track(colors,[1,1,1,1,.5,0],'f');track(colors+28,[32767,0],'h')
    view=struct.unpack_from('<I',data,80)[0];batch=struct.unpack_from('<I',data,view+36)[0];struct.pack_into('<H',data,batch+8,0)
    transform=array(0x74,1,bytes(84));track(transform,[0,0,0,.4,.2,0],'f');track(transform+28,[0,0,0,1,0,0,1,0],'f');track(transform+56,[1,1,1,2,3,1],'f')
    array(0xac,1,struct.pack('<H',0))
    return bytes(data)

def wmo_root(texture='gold.blp',blend=0,flags=5):
    mohd=bytearray(64);struct.pack_into('<I',mohd,4,1)
    material=bytearray(64);struct.pack_into('<III',material,0,flags,0,blend)
    return chunk('MVER',struct.pack('<I',17))+chunk('MOHD',mohd)+chunk('MOTX',texture.encode()+b'\0')+chunk('MOMT',material)
def wmo_group(material=0,flags=0x48):
    mogp=bytearray(68);struct.pack_into('<I',mogp,8,flags)
    for name,rows,width in (('MOVT',POSITIONS,3),('MONR',NORMALS,3),('MOTV',UV,2)):
        mogp.extend(chunk(name,struct.pack('<'+str(len(rows)*width)+'f',*(x for row in rows for x in row))))
    mogp.extend(chunk('MOVI',struct.pack('<3H',0,1,2)))
    batch=bytearray(24);struct.pack_into('<H',batch,16,3);batch[23]=material;mogp.extend(chunk('MOBA',batch))
    return chunk('MVER',struct.pack('<I',17))+chunk('MOGP',mogp)

def adt():
    header=bytearray(128);struct.pack_into('<3I',header,0,2,3,7);struct.pack_into('<I',header,0x14,128);struct.pack_into('<H',header,0x3c,1);struct.pack_into('<3f',header,0x68,10,20,30)
    return chunk('MVER',struct.pack('<I',18))+chunk('MTEX',b'gold.blp\0')+chunk('MCNK',header+chunk('MCVT',struct.pack('<145f',*(i*.25 for i in range(145)))))
def wdt():
    main=bytearray(64*64*8);struct.pack_into('<I',main,(7*64+3)*8,1)
    return chunk('MVER',struct.pack('<I',18))+chunk('MPHD',bytes(32))+chunk('MAIN',main)
def dbc():
    return b'WDBC'+struct.pack('<4I',1,4,16,7)+struct.pack('<IifI',73,-9,1.25,1)+b'\0Goblin'

def sound_dbc():
    strings=b'\0GG_Test\0stereo.wav\0GG\0';record=bytearray(116)
    for index,value in ((0,73),(1,2),(2,1),(3,9),(13,1),(23,20),(25,0x20)):
        struct.pack_into('<I',record,index*4,value)
    struct.pack_into('<f',record,24*4,.4);struct.pack_into('<2fI',record,26*4,1,60,2)
    return b'WDBC'+struct.pack('<4I',1,29,116,len(strings))+record+strings

def table_dbc(rows,fields):
    strings=bytearray(b'\0');records=bytearray()
    for row in rows:
        if len(row)!=fields:raise ValueError('Fixture DBC field mismatch')
        for value in row:
            if isinstance(value,str):
                offset=len(strings);strings.extend(value.encode()+b'\0');value=offset
            records.extend(struct.pack('<f' if isinstance(value,float) else '<I',value))
    return b'WDBC'+struct.pack('<4I',len(rows),fields,fields*4,len(strings))+records+strings

def character_entries():
    def color(w,h,rgba):return blp(width=w,height=h,levels=[bytes((rgba[2],rgba[1],rgba[0],rgba[3]))*w*h])
    sections=[[1,1,0,0,0,0,'GG/skin.blp','GG/extra.blp','',0],
              [2,1,0,1,0,0,'GG/face.blp','','',0],
              [3,1,0,3,0,0,'GG/hair.blp','','',0],
              [4,1,0,0,0,1,'GG/skin-blue.blp','','',0]]
    shirt=[0]*23;shirt[0]=73;shirt[6]=1;shirt[17]='GG_Shirt'
    cloak=[0]*23;cloak[0]=74;cloak[3]='GG_Cape';cloak[6]=1
    return {'DBFilesClient/CharSections.dbc':table_dbc(sections,10),
            'DBFilesClient/CharHairGeosets.dbc':table_dbc([[1,1,0,0,1,0],[2,1,0,1,2,0]],6),
            'DBFilesClient/CharacterFacialHairStyles.dbc':table_dbc([[1,0,0,0,0,0,1,1,1]],9),
            'DBFilesClient/ItemDisplayInfo.dbc':table_dbc([shirt,cloak],23),
            'GG/skin.blp':color(256,256,(120,80,40,255)),
            'GG/skin-blue.blp':color(256,256,(16,24,255,255)),
            'GG/extra.blp':color(2,2,(40,60,80,255)),
            'GG/face.blp':color(128,64,(200,0,0,128)),
            'GG/hair.blp':color(2,2,(20,20,20,255)),
            'Item/TextureComponents/TorsoUpperTexture/GG_Shirt_M.blp':color(128,64,(0,255,0,255)),
            'Item/ObjectComponents/Cape/GG_Cape.blp':color(2,2,(0,255,255,255))}

def particle_m2(*,flags=0x10,shape=1,blend=4,head_tail=0,rate=20,life=1,speed=1,gravity=0,tail=.2,geometry=None,recursion=None,tumble=0):
    data=bytearray(animated_m2(camera=True))
    def array(header,count,payload):
        offset=len(data);data.extend(payload);struct.pack_into('<II',data,header,count,offset);return offset
    record=bytearray(0x1f8);struct.pack_into('<I',record,4,flags)
    struct.pack_into('<HH',record,0x14,0,0);record[0x28]=blend;struct.pack_into('<H',record,0x2a,shape);record[0x2c]=head_tail
    struct.pack_into('<HH',record,0x30,1,1)
    struct.pack_into('<f3I3f',record,0x14c,.5,0xffff5010,0xff10ff20,0x001010ff,.12,.12,.02)
    struct.pack_into('<H',record,0x16c,1);struct.pack_into('<H',record,0x172,1)
    struct.pack_into('<f',record,0x17c,tail);struct.pack_into('<f',record,0x184,1)
    emitter=array(0x13c,1,record)
    for offset,name in ((0x18,geometry),(0x20,recursion)):
        if name is not None:array(emitter+offset,len(name.encode())+1,name.encode()+b'\0')
    struct.pack_into('<6f',data,emitter+0x19c,0,0,tumble,0,0,tumble*2)
    for offset,value in ((0x34,speed),(0x6c,.5),(0x88,3.14),(0xa4,gravity),(0xc0,life),(0xdc,rate),(0xf8,.6),(0x114,.6)):
        track=emitter+offset;struct.pack_into('<Hh',data,track,0,-1)
        array(track+4,1,struct.pack('<II',0,0));array(track+12,1,struct.pack('<I',0));array(track+20,1,struct.pack('<f',value))
    return bytes(data)

def mpq(name='Interface/Test.txt',plain=b'GG native readers',deleted=False,compressed=False,file_size=None,entries=None):
    mask=0xffffffff;table=[0]*0x500;seed=0x100001
    for i in range(256):
        for j in range(5):
            seed=((seed*125+3)&mask)%0x2aaaab;high=(seed&0xffff)<<16
            seed=((seed*125+3)&mask)%0x2aaaab;table[i+j*256]=high|(seed&0xffff)
    def hash_string(value,kind):
        a,b=0x7fed7fed,0xeeeeeeee
        for c in value.replace('/','\\').upper().encode():
            a=(table[kind+c]^((a+b)&mask))&mask;b=(c+a+b+(b<<5)+3)&mask
        return a
    def encrypt(values,key):
        seed=0xeeeeeeee;out=[]
        for plain in values:
            seed=(seed+table[0x400+(key&255)])&mask;out.append(plain^((key+seed)&mask));key=((((~key)<<21)+0x11111111)|(key>>11))&mask;seed=(plain+seed+(seed<<5)+3)&mask
        return struct.pack('<'+str(len(out))+'I',*out)
    rows=[(key,value,False,False,None) for key,value in entries.items()] if entries is not None else [(name,plain,compressed,deleted,file_size)]
    size=4
    while size<len(rows)*2:size*=2
    hashes=[mask]*(size*4);blocks=[];payload=bytearray();block_offset=32+size*16;start=block_offset+len(rows)*16
    for index,(name,plain,compressed,deleted,file_size) in enumerate(rows):
        data=plain;flags=0x80000000
        if deleted:data=b'';flags|=0x02000000
        if compressed:
            codec=b'\x02'+zlib.compress(plain);data=struct.pack('<II',8,8+len(codec))+codec;flags|=0x200
        slot=hash_string(name,0)&(size-1)
        while hashes[slot*4]!=mask:slot=(slot+1)&(size-1)
        hashes[slot*4:slot*4+4]=[hash_string(name,0x100),hash_string(name,0x200),0,index]
        blocks.extend([start+len(payload),len(data),len(plain) if file_size is None else file_size,flags]);payload.extend(data)
    header=b'MPQ\x1a'+struct.pack('<IIHH4I',32,start+len(payload),0,3,32,block_offset,size,len(rows))
    return header+encrypt(hashes,hash_string('(hash table)',0x300))+encrypt(blocks,hash_string('(block table)',0x300))+payload

def write_preview_assets(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    files={'gold.blp':blp(),'blue.tga':tga(),'panel.m2':animated_m2(),'hall.wmo':wmo_root('blue.tga'),'hall_000.wmo':wmo_group()}
    for name,data in files.items():(directory/name).write_bytes(data)
    return directory


def attachment_m2(*,camera=True,full_equipment=False):
    """One animated bone, six authored lookup slots and a deliberate duplicate record id."""
    data=bytearray(animated_m2(camera=camera))
    positions={0:(-.65,0,0),1:(.65,0,0),2:(-.7,0,0),5:(.55,0,.65),6:(-.55,0,.65),11:(0,0,1.05)}
    if full_equipment:positions.update({26:(.3,-.2,.5),27:(-.3,-.2,.5),28:(0,-.3,.6),30:(.2,-.2,.1),31:(-.2,-.2,.1),32:(-.3,0,-.2),33:(.3,0,-.2),35:(-.7,.2,.3)})
    records=bytearray();lookup=[0xffff]*(max(positions)+1)
    for slot,position in positions.items():
        lookup[slot]=len(records)//48;record=bytearray(48);struct.pack_into('<II3f',record,0,slot,0,*position);records.extend(record)
    # The lookup, rather than a scan of record.id, is authoritative.
    lookup[11]=len(records)//48;record=bytearray(48);struct.pack_into('<II3f',record,0,11,0,0,0,1.2);records.extend(record)
    offset=len(data);data.extend(records);struct.pack_into('<II',data,0x104,len(records)//48,offset)
    offset=len(data);data.extend(struct.pack('<'+str(len(lookup))+'H',*lookup));struct.pack_into('<II',data,0x10c,len(lookup),offset)
    return bytes(data)

def ribbon_m2(*,blend=6,gravity=0,rate=20,life=.5,gate=False):
    data=bytearray(animated_m2(camera=False))
    def array(header,count,payload):
        offset=len(data);data.extend(payload);struct.pack_into('<II',data,header,count,offset);return offset
    material=struct.unpack_from('<I',data,0x88)[0];struct.pack_into('<H',data,material+2,blend)
    record=bytearray(0xdc);struct.pack_into('<H',record,4,0)
    struct.pack_into('<3f2H',record,0x94,rate,life,gravity,2,2)
    emitter=array(0x134,1,record);array(emitter+0x14,1,struct.pack('<H',0));array(emitter+0x1c,1,struct.pack('<H',0))
    for offset,payload in ((0x24,struct.pack('<3f',1,.25,.1)),(0x40,struct.pack('<h',24575)),(0x5c,struct.pack('<f',.12)),(0x78,struct.pack('<f',.06)),(0xa4,struct.pack('<H',2))):
        track=emitter+offset;struct.pack_into('<Hh',data,track,1,-1);array(track+12,1,struct.pack('<I',0));array(track+20,1,payload)
    if gate:
        track=emitter+0xc0;struct.pack_into('<Hh',data,track,0,-1);array(track+12,3,struct.pack('<3I',0,200,400));array(track+20,3,bytes((0,1,0)))
    return bytes(data)

def equipment_entries():
    entries=character_entries();rows=[]
    entries['DBFilesClient/CharSections.dbc']=table_dbc([[1,1,0,0,0,0,'GG/skin.blp','','',0],[2,1,0,0,0,1,'GG/skin-blue.blp','','',0],[3,1,1,0,0,0,'GG/skin.blp','','',0]],10)
    for display,models,textures in ((80,('GG_Helm.mdx',''),('GG_Red','')),(81,('GG_Left.mdx','GG_Right.mdx'),('GG_Green','GG_Blue')),(82,('GG_Blade.mdx',''),('GG_Red','')),(83,('GG_Shield.mdx',''),('GG_Blue',''))):
        row=[0]*23;row[0]=display;row[1:5]=[*models,*textures];rows.append(row)
    entries['DBFilesClient/ItemDisplayInfo.dbc']=table_dbc(rows,23)
    # Independent model and texture names, per original ItemDisplayInfo semantics.
    small=bytearray(m2(texture=''));tex=struct.unpack_from('<I',small,0x60)[0];struct.pack_into('<I',small,tex,2)
    vertices=struct.unpack_from('<I',small,72)[0]
    for i,p in enumerate(POSITIONS):struct.pack_into('<3f',small,vertices+i*48,*(v*.18 for v in p))
    for folder,name in (('Head','GG_Helm_HuM'),('Head','GG_Helm_HuF'),('Shoulder','GG_Left'),('Shoulder','GG_Right'),('Weapon','GG_Blade'),('Shield','GG_Shield')):entries[f'Item/ObjectComponents/{folder}/{name}.m2']=bytes(small)
    for folder,color in (('Head','Red'),('Shoulder','Green'),('Shoulder','Blue'),('Weapon','Red'),('Shield','Blue')):
        rgba={'Red':(10,10,255,255),'Green':(10,255,10,255),'Blue':(255,10,10,255)}[color]
        entries[f'Item/ObjectComponents/{folder}/GG_{color}.blp']=blp(levels=[bytes(rgba)*4])
    return entries


def ranged_equipment_entries():
    entries=equipment_entries();rows=[]
    descriptors=((80,('GG_Helm.mdx',''),('GG_Red','')),(81,('GG_Left.mdx','GG_Right.mdx'),('GG_Green','GG_Blue')),
        (82,('GG_Blade.mdx',''),('GG_Red','')),(83,('GG_Shield.mdx',''),('GG_Blue','')),
        (84,('GG_Bow.mdx',''),('GG_Red','')),(85,('','GG_Arrow.mdx'),('','GG_Blue')),
        (86,('GG_Quiver.mdx',''),('GG_Green','')),(87,('GG_ArrowWeapon.mdx',''),('GG_Red','')))
    for display,models,textures in descriptors:
        row=[0]*23;row[0]=display;row[1:5]=[*models,*textures];rows.append(row)
    cloak=[0]*23;cloak[0]=74;cloak[3]='GG_Cape';cloak[6]=1;rows.append(cloak)
    entries['DBFilesClient/ItemDisplayInfo.dbc']=table_dbc(rows,23)
    child=entries['Item/ObjectComponents/Weapon/GG_Blade.m2']
    for folder,name,color in (('Weapon','GG_Bow','Red'),('Ammo','GG_Arrow','Blue'),('Quiver','GG_Quiver','Green'),('Weapon','GG_ArrowWeapon','Red')):
        entries[f'Item/ObjectComponents/{folder}/{name}.m2']=child
        entries[f'Item/ObjectComponents/{folder}/GG_{color}.blp']=blp(levels=[bytes((60,160,240,255))*4])
    return entries


def creature_entries():
    entries=equipment_entries()
    models=[[1,2,'GG/creature.mdx',2,2.0,0,0,0.,0.,0.,4,0,0,0,1.,3.],
            [2,0,'GG/npc.mdx',2,1.0,0,0,0.,0.,0.,0,0,0,0,1.,2.]]
    displays=[[100,1,0,0,.5,128,'GG_Monster','','',0xffffffff,0,0],
              [101,2,0,10,1.0,255,'IGNORED','','',2,0,0],
              [102,2,0,11,1.0,255,'IGNORED','','',2,0,0]]
    # Distinct baked and live character paths, both fully dressed.
    extra=[[10,1,0,0,0,0,0,0,80,81,0,0,0,0,0,0,0,0,'GG_Bake.blp'],
           [11,1,0,0,0,0,0,0,80,81,0,0,0,0,0,0,0,0,'']]
    entries['DBFilesClient/CreatureModelData.dbc']=table_dbc(models,16)
    entries['DBFilesClient/CreatureDisplayInfo.dbc']=table_dbc(displays,12)
    entries['DBFilesClient/CreatureDisplayInfoExtra.dbc']=table_dbc(extra,19)
    creature=bytearray(animated_m2());tex=struct.unpack_from('<I',creature,0x60)[0];struct.pack_into('<I',creature,tex,11);struct.pack_into('<II',creature,tex+8,0,0)
    entries['GG/creature.m2']=bytes(creature)
    npc=bytearray(attachment_m2());tex=struct.unpack_from('<I',npc,0x60)[0];struct.pack_into('<I',npc,tex,1);struct.pack_into('<II',npc,tex+8,0,0);entries['GG/npc.m2']=bytes(npc)
    entries['GG/GG_Monster.blp']=blp(levels=[bytes((255,24,16,255))*4])
    entries['Textures/BakedNpcTextures/GG_Bake.blp']=blp(width=256,height=256,levels=[bytes((255,0,200,255))*256*256])
    return entries
