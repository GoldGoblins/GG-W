"""Actual mounted MPQ -> original typed DBC readers -> bounded native worker queries."""
from pathlib import Path
import json
import os
import random
import struct
import tempfile
import unittest

from backend.game_engine_adapter_formats import NativeFormats, available
from backend.game_engine_adapter_game_data import GameplayData
from tools.world import engine_game_data_fixtures as fixtures
from tools.world.engine_format_fixtures import mpq, table_dbc


class NativeGameplayData(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='gg-game-data-')
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.reader = NativeFormats(self.root)
        self.addCleanup(self.reader.close)
        self.data = GameplayData(self.reader)
        self.mount(fixtures.entries())

    def mount(self, entries, name='Data', patch=None):
        directory = self.root/name
        directory.mkdir()
        (directory/'model.MPQ').write_bytes(mpq(entries=entries))
        if patch is not None:
            (directory/'patch.MPQ').write_bytes(mpq(entries=patch))
        self.reader.request('mount_chain', path=name, timeout=3)
        return directory

    def healthy(self):
        self.assertEqual(self.reader.request('ping'), {'abi': 1})

    def test_verified_reader_four_actual_catalogs_and_zero_blob(self):
        self.assertTrue(available())
        queries = [self.data.classes(), self.data.skills(race_id=1,class_id=1,level=5),
                   self.data.talents(race_id=1,class_id=1,tab_id=22), self.data.spells()]
        for result in queries:
            self.assertEqual(result['schema'], 'gg.engine.game-data.v1')
            self.assertEqual(result['source'], 'MOUNTED_DBC')
            self.assertIs(result['execution_authority'], False)
            self.assertEqual(result['catalog_epoch'], 1)
            self.assertNotIn('blob_base64', result)
            self.assertLess(len(json.dumps(result).encode()), 1024*1024)
        self.assertEqual([query['total'] for query in queries], [3,2,2,4])

    def test_class_semantics_missing_id_not_native_fallback_fake_row(self):
        result = self.data.classes([2,1,99])
        self.assertEqual(result['missing_ids'], [99])
        self.assertEqual(result['rows'], [
            {'id':2,'damage_bonus_stat':1,'pet_name_token':'GG_DEMON','has_relic_slot':True,'spell_family':72},
            {'id':1,'damage_bonus_stat':0,'pet_name_token':'GG_PET','has_relic_slot':False,'spell_family':71}])
        self.assertNotIn('name', result['rows'][0])

    def test_skill_rule_masks_level_flags_and_missing_joins_are_explicit(self):
        result = self.data.skills([7001,7002],race_id=1,class_id=1,level=5)
        first, second = result['rows']
        self.assertEqual(first['race_class'], {'flags':0x424,'min_level':10,'cost_index':3,
            'hidden':False,'mono':True,'unlearnable':True,'displays_untrained':False,'skill_up_silent':True})
        self.assertEqual(first['category'], {'name':'GG Crafts','order':4})
        self.assertTrue(self.data.skills([7001],race_id=1,class_id=1,level=10)['rows'][0]['race_class']['displays_untrained'])
        self.assertEqual(second['race_class']['flags'], 1)  # Zero masks admit all, after the nonmatching row.
        self.assertEqual(second['missing_joins'], [{'table':'SkillLineCategory','id':99},{'table':'SpellIcon','id':999}])
        self.assertIsNone(second['icon']); self.assertIsNone(second['category'])
        rejected = self.data.skills([7001],race_id=2,class_id=2,level=60)['rows'][0]
        self.assertIs(rejected['matching_race_class_rule'], False)
        self.assertIsNone(rejected['race_class'])

    def test_skill_duplicate_spell_uses_first_metadata_first_nonzero_forward(self):
        result = self.data.skills([9001,9004,55],kind='abilities',race_id=1,class_id=1,level=20)
        first, missing = result['rows']
        self.assertEqual(first['skill_id'], 7001)
        self.assertEqual((first['required_skill_value'],first['trivial_low'],first['trivial_high'],first['forward_spell_id']), (25,40,50,9002))
        self.assertEqual(first['spell_tab'], 7001)
        self.assertEqual(missing['missing_joins'], [{'table':'SkillLine','id':8888}])
        self.assertEqual(result['missing_ids'], [55])

    def test_talent_tabs_grid_prerequisite_and_native_ordinals_keep_file_order(self):
        overview = self.data.talents(race_id=1,class_id=1)
        self.assertEqual([r['id'] for r in overview['tabs']], [22,11])
        self.assertEqual(overview['rows'], [])
        result = self.data.talents(race_id=1,class_id=1,tab_id=22,ids=[501,502,99])
        self.assertEqual([r['id'] for r in result['rows']], [502,501])
        first, second = result['rows']
        self.assertEqual((first['ordinal'],first['row'],first['column'],first['max_rank']), (0,1,2,2))
        self.assertEqual(second['prerequisite_talent_id'], 502)
        self.assertEqual(second['prerequisite_rank'], 1)  # Original 0-based rank preserved.
        self.assertEqual(second['required_spell_id'], 9001)
        self.assertEqual(result['missing_ids'], [99])
        unknown = self.data.talents(race_id=1,class_id=1,tab_id=11)['rows'][0]
        self.assertEqual(unknown['missing_joins'], [{'table':'Talent','id':999}])
        self.assertEqual([r['id'] for r in self.data.talents(race_id=2,class_id=2)['tabs']], [33])
        with self.assertRaisesRegex(ValueError, 'not admitted'):
            self.data.talents(race_id=2,class_id=2,tab_id=22)

    def test_talent_page_does_not_expand_duplicate_identity_past_page_limit(self):
        entries = fixtures.entries()
        entries['DBFilesClient/Talent.dbc'] = table_dbc([fixtures.row(21,{0:502,1:22,2:n,4:9001}) for n in range(80)],21)
        self.mount(entries, 'Duplicates')
        page = self.data.talents(race_id=1,class_id=1,tab_id=22,limit=2)
        self.assertEqual([r['ordinal'] for r in page['rows']], [0,1])
        self.assertEqual(page['next_offset'], 2)
        selected = self.data.talents(race_id=1,class_id=1,tab_id=22,ids=[502])
        self.assertEqual([r['ordinal'] for r in selected['rows']], [0])

    def test_spells_preserve_three_effects_signed_fields_and_64_bit_family_words(self):
        first, mixed = self.data.spells([9001,9004])['rows']
        self.assertEqual(first['family_flags_words'], [0x80000001,0x80000002])
        self.assertEqual(first['power_type'], 0xfffffffe)
        self.assertEqual(first['equipped_item_class'], -1)
        self.assertEqual(first['stance_bar_order'], -2)
        self.assertEqual(first['effects'][0]['base_points'], -3)
        self.assertEqual(first['effects'][0]['dice_per_level'], -1)
        self.assertEqual(first['effects'][0]['misc_value'], -7)
        self.assertEqual(first['effects'][0]['points_per_combo_point'], 1.5)
        self.assertEqual([r['slot'] for r in mixed['effects']], [0,1,2])
        self.assertEqual([r['effect'] for r in mixed['effects']], [2,999,36])
        self.assertEqual(mixed['learned_spell_id'], 9002)
        self.assertEqual(mixed['execution_status'], 'UNMAPPED')
        self.assertEqual(mixed['missing_joins'], [{'table':'SpellIcon','id':999},{'table':'SpellDispelType','id':999},{'table':'SpellCategory','id':999}])
        self.assertEqual(first['unresolved_joins'], ['SpellCastTimes','SpellDuration','SpellRange','SpellRadius','SpellVisual'])

    def test_original_learn_slot_order_and_dispel_label_gate(self):
        hidden, learn = self.data.spells([9002,9003])['rows']
        self.assertEqual(hidden['dispel_id'], 5)
        self.assertIs(hidden['dispel_label_visible'], False)
        self.assertIsNone(hidden['dispel_name'])
        self.assertEqual(hidden['missing_joins'], [])
        self.assertEqual(learn['learn_effects'], [{'kind':'spell','id':9002},{'kind':'skill_step','skill_id':7001,'step':1}])
        self.assertEqual(self.data.spells([9001])['rows'][0]['dispel_name'], 'GG Magic')

    def test_missing_trigger_and_modal_spell_joins_never_synthesize_spell_rows(self):
        entries=fixtures.entries();rows=fixtures.spell_rows();rows[2][110]=99998;rows[2][38]=99999
        entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
        self.mount(entries,'MissingSpellJoin')
        result=self.data.spells([9003])
        spell=result['rows'][0]
        self.assertEqual(spell['missing_joins'],[{'table':'Spell','id':99998},{'table':'Spell','id':99999}])
        self.assertEqual(spell['learned_spell_id'],99998)  # Exact original wire metadata, no learned grant.
        self.assertEqual(self.data.spells([99998,99999])['missing_ids'],[99998,99999])
        self.assertIs(result['execution_authority'],False)

    def test_unmounted_reader_never_auto_discovers_or_fabricates_catalogs(self):
        reader=NativeFormats(self.root);self.addCleanup(reader.close)
        with self.assertRaisesRegex(ValueError,'not mounted'):GameplayData(reader).classes()
        self.assertEqual(reader.request('ping'),{'abi':1})

    def test_selected_missing_ids_and_deterministic_pages(self):
        page = self.data.spells(limit=2)
        self.assertEqual([r['id'] for r in page['rows']], [9001,9002])
        self.assertEqual(page['next_offset'], 2)
        last = self.data.spells(offset=2,limit=2)
        self.assertEqual([r['id'] for r in last['rows']], [9003,9004])
        self.assertIsNone(last['next_offset'])
        self.assertEqual(self.data.spells([1,9999])['missing_ids'], [1,9999])

    def test_large_spell_native_query_bypasses_export_limits_without_a_blob(self):
        entries = fixtures.entries()
        table = fixtures.large_spell_table()
        self.assertGreater(len(table), 8*1024*1024)
        entries['DBFilesClient/Spell.dbc'] = table
        self.mount(entries, 'Large')
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.reader.request('chain_read',entry='DBFilesClient/Spell.dbc',timeout=3)
        result = self.data.spells([12288,1,12289])
        self.assertEqual(result['total'], 12288)
        self.assertEqual([r['id'] for r in result['rows']], [12288,1])
        self.assertEqual(result['rows'][0]['name'], 'GG Fixture')
        self.assertEqual(result['rows'][0]['description'], 'GG large fixture')
        self.assertEqual(result['missing_ids'], [12289])
        self.assertNotIn('blob_base64', result)
        self.assertEqual([r['id'] for r in self.data.spells(offset=12286,limit=64)['rows']], [12287,12288])

    def test_patch_priority_new_mount_resets_all_catalogs_atomically(self):
        initial = [self.data.classes(),self.data.skills(race_id=1,class_id=1,level=5),
                   self.data.talents(race_id=1,class_id=1,tab_id=22),self.data.spells()]
        entries = fixtures.entries()
        rows = fixtures.spell_rows(); rows[0][120] = 'GG Patched Spark'
        patch = {'DBFilesClient/Spell.dbc': table_dbc(rows,173),
                 'DBFilesClient/ChrClasses.dbc':table_dbc([fixtures.row(17,{0:1,2:1,4:'GG_PATCH',15:99})],17)}
        self.mount(entries, 'Patched', patch=patch)
        updated = self.data.classes([1])
        self.assertEqual(updated['catalog_epoch'], 2)
        self.assertEqual(updated['rows'][0]['pet_name_token'], 'GG_PATCH')
        self.assertEqual(self.data.spells([9001])['rows'][0]['name'], 'GG Patched Spark')
        self.assertTrue(all(r['catalog_epoch']==1 for r in initial))
        self.assertEqual(self.data.skills(race_id=1,class_id=1,level=5)['catalog_epoch'],2)
        self.assertEqual(self.data.talents(race_id=1,class_id=1)['catalog_epoch'],2)

    def test_failed_mount_preserves_previous_chain_epoch_and_completed_cache(self):
        before = self.data.spells([9001])
        directory = self.root/'Corrupt'; directory.mkdir()
        (directory/'model.MPQ').write_bytes(b'not an archive')
        with self.assertRaises(ValueError): self.reader.request('mount_chain',path='Corrupt',timeout=3)
        self.assertEqual(self.data.spells([9001]),before)
        # A previously unloaded catalog must still use the old mounted chain.
        self.assertEqual(self.data.classes()['catalog_epoch'],1)
        self.healthy()

    def test_patch_tombstone_never_falls_back_to_lower_original_table(self):
        directory = self.mount(fixtures.entries(), 'Deleted')
        (directory/'patch.MPQ').write_bytes(mpq(name='DBFilesClient/Spell.dbc',deleted=True))
        self.reader.request('mount_chain',path='Deleted',timeout=3)
        with self.assertRaisesRegex(ValueError,'deleted'):
            self.data.spells([9001])
        self.assertEqual(self.data.classes()['catalog_epoch'],3)
        self.healthy()

    def test_every_required_dependency_fails_without_partial_catalog(self):
        cases = [('classes','ChrClasses'),('skills','SpellIcon'),('skills','SkillLine'),
                 ('skills','SkillLineAbility'),('skills','SkillLineCategory'),('skills','SkillRaceClassInfo'),
                 ('talents','TalentTab'),('talents','Talent'),('spells','SpellIcon'),
                 ('spells','SpellDispelType'),('spells','SpellCategory'),('spells','Spell')]
        for number, (kind, name) in enumerate(cases):
            with self.subTest(kind=kind,name=name):
                entries=fixtures.entries(); del entries[f'DBFilesClient/{name}.dbc']
                self.mount(entries, f'Missing{number}')
                query = {'classes':lambda:self.data.classes(),
                         'skills':lambda:self.data.skills(race_id=1,class_id=1,level=5),
                         'talents':lambda:self.data.talents(race_id=1,class_id=1),
                         'spells':lambda:self.data.spells()}[kind]
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError,'not in patch chain'): query()
                self.healthy()

    def test_malformed_shape_offsets_strings_and_float_recover_by_new_mount(self):
        original=fixtures.entries()
        cases=[]
        for offset,value in [(8,172),(12,688),(4,32769),(16,99999)]:
            bad=bytearray(original['DBFilesClient/Spell.dbc']);struct.pack_into('<I',bad,offset,value);cases.append(bytes(bad))
        bad=bytearray(original['DBFilesClient/Spell.dbc']);struct.pack_into('<I',bad,20+120*4,0xffffffff);cases.append(bytes(bad))
        bad=bytearray(original['DBFilesClient/Spell.dbc']);struct.pack_into('<f',bad,20+37*4,float('nan'));cases.append(bytes(bad))
        rows=fixtures.spell_rows();rows[0][120]='x'*513;cases.append(table_dbc(rows,173))
        bad=bytearray(original['DBFilesClient/Spell.dbc']);bad[-1]=1;cases.append(bytes(bad))
        for number,table in enumerate(cases):
            with self.subTest(case=number):
                entries=dict(original);entries['DBFilesClient/Spell.dbc']=table
                self.mount(entries,f'Malformed{number}')
                with self.assertRaises(ValueError):self.data.spells([9001])
                self.assertEqual(self.data.classes()['total'],3)
                self.healthy()
        self.mount(original,'Recovered')
        self.assertEqual(self.data.spells([9001])['rows'][0]['name'],'GG Spark')

    def test_signed_learn_arithmetic_overflow_is_rejected_before_original_reader(self):
        entries=fixtures.entries();rows=fixtures.spell_rows();rows[2][78]=0x7fffffff;rows[2][66]=1
        entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
        self.mount(entries,'Overflow')
        with self.assertRaisesRegex(ValueError,'arithmetic'):self.data.spells()
        self.healthy()

    def test_nonpositive_skill_step_misc_skips_original_overflowing_addition(self):
        for number,misc in enumerate([0,0xffffffff]):
            with self.subTest(misc=misc):
                entries=fixtures.entries();rows=fixtures.spell_rows()
                rows[2][108]=misc;rows[2][78]=0x7fffffff;rows[2][66]=1
                entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
                self.mount(entries,f'NonpositiveSkill{number}')
                spell=self.data.spells([9003])['rows'][0]
                self.assertEqual(spell['learn_effects'],[{'kind':'spell','id':9002}])
                self.assertEqual(spell['effects'][2]['base_points'],0x7fffffff)
                self.assertEqual(spell['effects'][2]['misc_value'],0 if misc==0 else -1)
                self.healthy()

    def test_joined_icon_copies_count_toward_expanded_text_before_typed_load(self):
        entries=fixtures.entries()
        entries['DBFilesClient/SpellIcon.dbc']=table_dbc([[1,'a'*1024],[2,'b'*1024]],2)
        entries['DBFilesClient/Spell.dbc']=fixtures.large_spell_table(32768,name='n'*512,description='',icon_id=1,active_icon_id=2)
        self.assertLess(len(entries['DBFilesClient/Spell.dbc']),32*1024*1024)
        self.mount(entries,'JoinedText')
        with self.assertRaisesRegex(ValueError,'text capacity'):
            self.data.spells([1])
        self.assertEqual(self.data.classes()['total'],3)
        self.healthy()

    def test_joined_icons_keep_original_last_nonempty_duplicate_map_semantics(self):
        entries=fixtures.entries()
        entries['DBFilesClient/SpellIcon.dbc']=table_dbc([[1,'a'*1024],[1,''],[2,'b'*1024]],2)
        entries['DBFilesClient/Spell.dbc']=fixtures.large_spell_table(20000,name='n'*512,description='',icon_id=1,active_icon_id=2)
        self.mount(entries,'JoinedWithinBudget')
        result=self.data.spells([20000])
        self.assertEqual(result['rows'][0]['icon'],'a'*1024)
        self.assertEqual(result['rows'][0]['active_icon'],'b'*1024)
        self.assertEqual(result['total'],20000)

    def test_sparse_packed_sector_capacity_precedes_original_raw_allocation(self):
        before=self.data.spells([9001])
        directory=self.root/'PackedSector';directory.mkdir()
        fixtures.sparse_sector_archive(directory/'model.MPQ')
        self.reader.request('mount_chain',path='PackedSector',timeout=3)
        with self.assertRaisesRegex(ValueError,'packed sector capacity'):
            self.data.classes()
        self.healthy()
        self.assertEqual(before['catalog_epoch'],1)

    def test_sparse_hash_and_block_index_caps_preserve_previous_chain_and_epoch(self):
        before=self.data.spells([9001])
        for label,counts in [('Hash',{'hash_rows':16777216}),('Block',{'block_rows':16777216})]:
            with self.subTest(label=label):
                directory=self.root/label;directory.mkdir()
                fixtures.sparse_index_archive(directory/'model.MPQ',**counts)
                with self.assertRaisesRegex(ValueError,'index capacity'):
                    self.reader.request('mount_chain',path=label,timeout=3)
                self.assertEqual(self.data.spells([9001]),before)
                self.healthy()

    def test_individually_bounded_sparse_sectors_have_an_aggregate_input_cap(self):
        directory=self.root/'PackedAggregate';directory.mkdir()
        (directory/'model.MPQ').write_bytes(fixtures.archive())
        fixtures.sparse_many_sector_archive(directory/'patch.MPQ')
        self.reader.request('mount_chain',path='PackedAggregate',timeout=3)
        before=self.data.spells([9001])
        with self.assertRaisesRegex(ValueError,'aggregate packed input capacity'):
            self.data.classes()
        self.assertEqual(self.data.spells([9001]),before)
        self.healthy()

    def test_aggregate_index_capacity_rejected_before_any_original_index_allocation(self):
        before=self.data.spells([9001])
        directory=self.root/'AggregateIndex';directory.mkdir()
        for number in range(9):
            fixtures.sparse_index_archive(directory/f'patch-{number}.MPQ',hash_rows=262144,block_rows=262144)
        with self.assertRaisesRegex(ValueError,'aggregate index capacity'):
            self.reader.request('mount_chain',path='AggregateIndex',timeout=3)
        self.assertEqual(self.data.spells([9001]),before)
        self.healthy()

    def test_original_small_compressed_dbc_sector_remains_readable(self):
        directory=self.root/'CompressedTable';directory.mkdir()
        content=fixtures.entries()['DBFilesClient/ChrClasses.dbc']
        (directory/'model.MPQ').write_bytes(mpq(name='DBFilesClient/ChrClasses.dbc',plain=content,compressed=True))
        self.reader.request('mount_chain',path='CompressedTable',timeout=3)
        self.assertEqual(self.data.classes([2])['rows'][0]['pet_name_token'],'GG_DEMON')
        self.healthy()

    def test_legal_packed_sector_larger_than_64k_uses_actual_expected_sector_size(self):
        directory=self.root/'LegalLargeSector';directory.mkdir()
        content=bytearray(fixtures.entries()['DBFilesClient/ChrClasses.dbc'])
        generator=random.Random(781)
        padding=bytes(generator.randrange(1,128) for _ in range(90000))
        struct.pack_into('<I',content,16,struct.unpack_from('<I',content,16)[0]+len(padding))
        content.extend(padding)
        archive=bytearray(mpq(name='DBFilesClient/ChrClasses.dbc',plain=bytes(content),compressed=True))
        struct.pack_into('<H',archive,14,8)  # 128 KiB, one legitimate large sector.
        payload_at=struct.unpack_from('<I',archive,20)[0]+16
        start,end=struct.unpack_from('<II',archive,payload_at)
        self.assertGreater(end-start,65536)
        (directory/'model.MPQ').write_bytes(archive)
        self.reader.request('mount_chain',path='LegalLargeSector',timeout=3)
        self.assertEqual(self.data.classes([2])['rows'][0]['pet_name_token'],'GG_DEMON')
        self.healthy()

    def test_changed_archive_index_is_rejected_before_uncached_catalog_load(self):
        directory=self.root/'ChangingSource';directory.mkdir()
        path=directory/'model.MPQ';path.write_bytes(fixtures.archive())
        self.reader.request('mount_chain',path='ChangingSource',timeout=3)
        before=self.data.spells([9001])
        with path.open('r+b') as source:
            source.seek(32);byte=source.read(1);source.seek(32);source.write(bytes([byte[0]^1]))
        with self.assertRaisesRegex(ValueError,'changed since mount'):
            self.data.classes()
        self.assertEqual(self.data.spells([9001]),before)
        self.healthy()

    def test_index_identity_is_checked_even_when_source_timestamp_is_restored(self):
        directory=self.root/'RestoredTimestamp';directory.mkdir()
        path=directory/'model.MPQ';path.write_bytes(fixtures.archive())
        self.reader.request('mount_chain',path='RestoredTimestamp',timeout=3)
        before=self.data.spells([9001]);identity=path.stat()
        with path.open('r+b') as source:
            source.seek(32);byte=source.read(1);source.seek(32);source.write(bytes([byte[0]^1]))
        os.utime(path,ns=(identity.st_atime_ns,identity.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'index identity changed'):
            self.data.classes()
        self.assertEqual(self.data.spells([9001]),before)
        self.healthy()

    def test_original_encrypted_and_single_unit_errors_precede_sector_read(self):
        content=fixtures.entries()['DBFilesClient/ChrClasses.dbc']
        for number,flag in enumerate([0x10000,0x1000000]):
            with self.subTest(flag=flag):
                directory=self.root/f'UnsupportedFlags{number}';directory.mkdir()
                archive=bytearray(mpq(name='DBFilesClient/ChrClasses.dbc',plain=content,compressed=True))
                block_at=struct.unpack_from('<I',archive,20)[0]
                # The last encrypted word has no later word to affect; XOR flips the same plaintext flag.
                old=struct.unpack_from('<I',archive,block_at+12)[0]
                struct.pack_into('<I',archive,block_at+12,old^flag)
                (directory/'model.MPQ').write_bytes(archive)
                self.reader.request('mount_chain',path=directory.name,timeout=3)
                with self.assertRaises(ValueError) as original:
                    self.reader.request('chain_read',entry=r'DBFilesClient\ChrClasses.dbc',timeout=3)
                with self.assertRaises(ValueError) as guarded:
                    self.data.classes()
                self.assertEqual(str(guarded.exception),str(original.exception))
                self.assertIn('reading DBFilesClient',str(guarded.exception))
                self.healthy()

    def test_declared_inflated_size_is_rejected_before_archive_read(self):
        directory=self.root/'Huge';directory.mkdir()
        (directory/'model.MPQ').write_bytes(mpq(name='DBFilesClient/ChrClasses.dbc',file_size=0xffffffff))
        self.reader.request('mount_chain',path='Huge',timeout=3)
        with self.assertRaisesRegex(ValueError,'source capacity'):self.data.classes()
        self.healthy()

    def test_repeated_shared_string_expansion_has_its_own_capacity(self):
        entries=fixtures.entries();entries['DBFilesClient/Spell.dbc']=fixtures.large_spell_table(17000,description='x'*4096)
        self.assertLess(len(entries['DBFilesClient/Spell.dbc']),32*1024*1024)
        self.mount(entries,'Expanded')
        with self.assertRaisesRegex(ValueError,'text capacity'):self.data.spells([1])
        self.assertEqual(self.data.classes()['total'],3)
        self.healthy()

    def test_cross_catalog_cache_budget_rejects_growth_retaining_completed_catalog(self):
        entries=fixtures.entries();entries['DBFilesClient/Spell.dbc']=fixtures.large_spell_table(26000)
        entries['DBFilesClient/SkillLineAbility.dbc']=table_dbc([fixtures.row(15,{0:n+1,1:7001,2:n+1}) for n in range(32768)],15)
        self.mount(entries,'CacheCapacity')
        before=self.data.spells([26000])
        with self.assertRaisesRegex(ValueError,'catalog/cache capacity'):
            self.data.skills(race_id=1,class_id=1,level=5)
        self.assertEqual(self.data.spells([26000]),before)
        self.healthy()

    def test_response_budget_counts_escaped_text_and_smaller_query_stays_valid(self):
        entries=fixtures.entries();entries['DBFilesClient/Spell.dbc']=fixtures.large_spell_table(64,description='\x01'*4096,aura='\x01'*4096)
        self.mount(entries,'ResponseCapacity')
        with self.assertRaisesRegex(ValueError,'response capacity'):self.data.spells(limit=64)
        result=self.data.spells([1])
        self.assertEqual(result['rows'][0]['description'],'\x01'*4096)
        self.assertEqual(result['total'],64)
        self.healthy()

    def test_invalid_selectors_context_and_unknown_fields_do_not_break_worker(self):
        cases=[{'ids':[1]*2},{'ids':list(range(1,66))},{'ids':[True]},{'ids':[0]},
               {'ids':[-1]},{'ids':[0x100000000]},{'ids':[1],'offset':0},
               {'limit':65},{'limit':0},{'offset':32769},{'unknown':1}]
        for fields in cases:
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.reader.request('game_data_classes',**fields)
        for race,class_id,level in [(0,1,5),(1,33,5),(1,1,61),(True,1,5)]:
            with self.subTest(race=race,class_id=class_id,level=level),self.assertRaises(ValueError):
                self.data.skills(race_id=race,class_id=class_id,level=level)
        with self.assertRaisesRegex(ValueError,'requires tab_id'):
            self.data.talents(race_id=1,class_id=1,ids=[501])
        with self.assertRaises(ValueError):self.data.classes([1],limit=1)
        self.assertEqual(self.data.classes([1])['total'],3)
        self.healthy()


if __name__ == '__main__':
    unittest.main()
