"""Independently authored WDBC gameplay rows; no original client content or artwork."""
from __future__ import annotations

import struct
from tools.world.engine_format_fixtures import mpq, table_dbc

SPELL_FLOATS = (37, 73, 74, 75, 97, 98, 99, 112, 113, 114, 167, 168, 169)


def row(fields, values):
    result = [0] * fields
    for index, value in values.items():
        result[index] = value & 0xffffffff if isinstance(value, int) else value
    return result


def spell_rows():
    def spell(identity, name, rank, effects):
        values = {0: identity, 1: 2, 2: 7, 4: 1, 18: 1, 19: 1250, 20: 500,
                  28: 3, 29: 5, 30: 9, 31: -2, 32: 12, 36: 4, 37: 8.5,
                  58: -1, 117: 1, 118: 2, 120: name, 129: rank,
                  138: 'An independently authored GG fixture.', 147: 'GG fixture aura.',
                  160: 71, 161: 0x80000001, 162: 0x80000002, 166: -2,
                  167: 1., 168: .5, 169: .25}
        values.update({61+i: value for i, value in enumerate(effects)})
        result = row(173, values)
        for index in SPELL_FLOATS:
            result[index] = float(result[index])
        return result
    first = spell(9001, 'GG Spark', 'Rank One', (2, 0, 0))
    for index, value in {64: 5, 67: 1, 70: -1, 73: .25, 76: -3,
                         82: 6, 88: 11, 94: 125, 97: .75, 106: -7, 112: 1.5}.items():
        first[index] = value & 0xffffffff if isinstance(value, int) else value
    second = spell(9002, 'GG Spark', 'Rank Two', (2, 0, 0))
    second[4] = 5  # A real dispel row whose original label gate hides its name.
    learn = spell(9003, 'GG Teaching Token', '', (0, 36, 44))
    learn[110] = 9002; learn[108] = 7001; learn[78] = 0xffffffff; learn[66] = 2
    mixed = spell(9004, 'GG Unmapped Mix', '', (2, 999, 36))
    mixed[111] = 9002; mixed[117] = 999; mixed[2] = 999; mixed[4] = 999
    return [first, second, learn, mixed]


def entries(*, spells=None):
    data = {
        'ChrClasses': (17, [row(17, {0:1,2:0,4:'GG_PET',15:71}),
                           row(17, {0:2,2:1,4:'GG_DEMON',15:72,16:1}),
                           row(17, {0:3,2:1,4:'GG_PET',15:73})]),
        'SpellIcon': (2, [[1,'GG/FixtureSpark'],[2,'GG/FixtureActive']]),
        'SkillLine': (22, [row(22, {0:7001,1:8,3:'GG Embercraft',12:'GG fixture profession.',21:1}),
                          row(22, {0:7002,1:99,3:'GG Wildcraft',12:'GG fixture missing category.',21:999})]),
        'SkillLineCategory': (11, [row(11, {0:8,1:'GG Crafts',10:4})]),
        'SkillRaceClassInfo': (8, [row(8, {0:1,1:7001,2:1,3:1,4:0x424,5:10,7:3}),
                                  row(8, {0:2,1:7002,2:1,3:2,4:0x81,5:30}),
                                  row(8, {0:3,1:7002,2:0,3:0,4:1})]),
        # The first duplicate spell row owns metadata; the first nonzero later forward wins.
        'SkillLineAbility': (15, [row(15, {0:1,1:7001,2:9001,7:25,10:50,11:40}),
                                  row(15, {0:2,1:7002,2:9001,7:99,8:9002,10:999,11:998}),
                                  row(15, {0:3,1:7002,2:9001,8:9999}),
                                  row(15, {0:4,1:7001,2:9002,7:50}),
                                  row(15, {0:5,1:8888,2:9004,7:1})]),
        'TalentTab': (15, [row(15, {0:22,1:'GG Ember Tree',11:1,12:1,13:2,14:'GGEmber'}),
                           row(15, {0:11,1:'GG Frost Tree',11:1,12:1,13:1,14:'GGFrost'}),
                           row(15, {0:33,1:'GG Other Tree',11:2,12:2,14:'GGOther'})]),
        'Talent': (21, [row(21, {0:502,1:22,2:1,3:2,4:9001,5:9002,19:1}),
                        row(21, {0:501,1:22,2:0,3:0,4:9004,13:502,16:1,20:9001}),
                        row(21, {0:503,1:11,4:9001,13:999})]),
        'SpellDispelType': (12, [row(12, {0:1,1:'GG Magic',10:1,11:'GG Magic'}),
                                 row(12, {0:5,1:'GG Hidden',10:0})]),
        'SpellCategory': (2, [[7,2]]),
        'Spell': (173, spell_rows() if spells is None else spells),
    }
    return {f'DBFilesClient/{name}.dbc': table_dbc(rows, fields) for name, (fields, rows) in data.items()}


def large_spell_table(count=12288, *, description='GG large fixture', aura='', name='GG Fixture', icon_id=0, active_icon_id=0):
    """Reuse one tiny string block, so tests can distinguish expanded text from raw size."""
    description_offset = len(name.encode())+2
    base = row(173, {0:1,31:0,58:-1,117:icon_id,118:active_icon_id,120:1,129:0,
                     138:description_offset,147:description_offset+len(description.encode())+1})
    for index in SPELL_FLOATS:
        base[index] = 0.
    packed = bytearray()
    for value in base:
        packed.extend(struct.pack('<f' if isinstance(value,float) else '<I', value))
    records = bytearray()
    for identity in range(1, count+1):
        packed[:4] = struct.pack('<I', identity); records.extend(packed)
    strings = b'\0' + name.encode() + b'\0' + description.encode() + b'\0' + aura.encode() + b'\0'
    return b'WDBC' + struct.pack('<4I',count,173,692,len(strings)) + records + strings


def archive(data=None):
    return mpq(entries=entries() if data is None else data)


def joined_entries():
    data=entries();rows=spell_rows()
    for item in rows:
        item[18]=10;item[30]=21;item[36]=4;item[88]=13
    data['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
    data['DBFilesClient/SpellCastTimes.dbc']=table_dbc([row(4,{0:10,1:1000,2:-100,3:500}),row(4,{0:18,1:-1000000,3:-1000000})],4)
    data['DBFilesClient/SpellDuration.dbc']=table_dbc([row(4,{0:21,1:-1,3:-1})],4)
    data['DBFilesClient/SpellRange.dbc']=table_dbc([row(22,{0:4,1:5.,2:30.,3:0})],22)
    data['DBFilesClient/SpellRadius.dbc']=table_dbc([row(4,{0:13,1:10.,2:.5,3:30.})],4)
    return data


def visual_entries():
    data=joined_entries();rows=spell_rows();rows[0][115]=71
    for item in rows:item[18]=10;item[30]=21;item[36]=4;item[88]=13
    data['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
    data['DBFilesClient/SpellVisual.dbc']=table_dbc([row(16,{0:71,1:81,2:82,3:81,6:1,7:91,9:3,10:51,11:1,12:92,13:83,14:52})],16)
    kits=[]
    for identity in (81,82,83):
        kit=row(35,{0:identity,2:16,3:91,12:92,13:53,14:54,15:0,16:-1,17:-1,18:-1})
        for index in range(19,35):kit[index]=0.
        kit[19]=101.;kit[23]=8.;kit[27]=1.
        kits.append(kit)
    data['DBFilesClient/SpellVisualKit.dbc']=table_dbc(kits,35)
    data['DBFilesClient/SpellVisualEffectName.dbc']=table_dbc([[91,'GG SPARK','GG/FixtureSpark.m2',0,0],[92,'GG AREA','GG/FixtureArea.m2',0,0]],5)
    data['DBFilesClient/SpellChainEffects.dbc']=table_dbc([[101,2.,.2,.04,-.5,300,100,'GG/FixtureBeam.blp']],8)
    return data


def trigger_entries():
    data=entries()
    data['DBFilesClient/AreaTrigger.dbc']=table_dbc([
        [72,7,10.,20.,30.,3.,0.,0.,0.,0.],
        [61,7,10.,20.,30.,0.,8.,2.,4.,1.5707963267948966],
        [99,8,10.,20.,30.,2.,0.,0.,0.,0.]],10)
    return data


def sparse_sector_archive(path, *, name='DBFilesClient/ChrClasses.dbc', packed_size=256*1024*1024):
    """Only a tiny prefix is written; the oversized stored sector body is a sparse hole."""
    content=entries()[name]
    prefix=bytearray(mpq(name=name,plain=content,compressed=True))
    block_at=struct.unpack_from('<I',prefix,20)[0]
    payload_at=block_at+16  # Exactly one block; unlike the encrypted block table this is public layout.
    struct.pack_into('<II',prefix,payload_at,8,8+packed_size)
    with open(path,'wb') as output:
        output.write(prefix)
        output.truncate(payload_at+8+packed_size)


def sparse_index_archive(path, *, hash_rows=1, block_rows=1):
    """Declared index storage is physically available without creating a giant byte buffer."""
    hash_at=32;block_at=hash_at+hash_rows*16
    header=b'MPQ\x1a'+struct.pack('<IIHH4I',32,block_at+block_rows*16,0,3,hash_at,block_at,hash_rows,block_rows)
    with open(path,'wb') as output:
        output.write(header)
        output.truncate(block_at+block_rows*16)


def _block_words(values):
    """Encode one authored MPQ block row using the documented Storm table algorithm."""
    mask=0xffffffff;table=[0]*0x500;seed=0x100001
    for i in range(256):
        for j in range(5):
            seed=((seed*125+3)&mask)%0x2aaaab;high=(seed&0xffff)<<16
            seed=((seed*125+3)&mask)%0x2aaaab;table[i+j*256]=high|(seed&0xffff)
    key,seed=0x7fed7fed,0xeeeeeeee
    for character in b'(BLOCK TABLE)':
        key=(table[0x300+character]^((key+seed)&mask))&mask
        seed=(character+key+seed+(seed<<5)+3)&mask
    seed=0xeeeeeeee;encoded=[]
    for value in values:
        seed=(seed+table[0x400+(key&255)])&mask
        encoded.append(value^((key+seed)&mask))
        key=((((~key)<<21)+0x11111111)|(key>>11))&mask
        seed=(value+seed+(seed<<5)+3)&mask
    return struct.pack('<4I',*encoded)


def sparse_many_sector_archive(path, *, name='DBFilesClient/ChrClasses.dbc',
                               unpacked_size=64*1024, packed_sector_size=64*1024):
    """Every sector passes its own cap, while their sparse aggregate exceeds entry bounds."""
    prefix=bytearray(mpq(name=name,plain=b'',compressed=True,file_size=unpacked_size))
    block_at=struct.unpack_from('<I',prefix,20)[0];payload_at=block_at+16
    struct.pack_into('<H',prefix,14,0)  # 512-byte uncompressed sectors.
    sectors=(unpacked_size+511)//512;table_bytes=(sectors+1)*4
    packed_size=table_bytes+sectors*packed_sector_size
    prefix[block_at:payload_at]=_block_words([payload_at,packed_size,unpacked_size,0x80000200])
    struct.pack_into('<I',prefix,8,payload_at+packed_size)
    offsets=struct.pack('<'+str(sectors+1)+'I',*(table_bytes+i*packed_sector_size for i in range(sectors+1)))
    with open(path,'wb') as output:
        output.write(prefix[:payload_at]);output.write(offsets)
        output.truncate(payload_at+packed_size)
