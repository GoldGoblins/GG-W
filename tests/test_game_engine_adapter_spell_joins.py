"""Original signed timing/range/radius joins, missing data and atomic failures."""
import struct,unittest
from tests import test_game_engine_adapter_game_data as fixture
from tools.world import engine_game_data_fixtures as data
from tools.world.engine_format_fixtures import table_dbc


class SpellJoins(unittest.TestCase):
    setUp=fixture.NativeGameplayData.setUp
    mount=fixture.NativeGameplayData.mount
    healthy=fixture.NativeGameplayData.healthy

    def test_actual_original_typed_joins_preserve_signed_scaling_and_units(self):
        self.mount(data.joined_entries(),'Joined')
        result=self.data.spells([9001],joins=True,level=12);spell=result['rows'][0]
        self.assertEqual(spell['casting_time'],dict(base_ms=1000,per_level_ms=-100,minimum_ms=500,resolved_ms=500))
        self.assertEqual(spell['duration'],dict(base_ms=-1,per_level_ms=0,max_ms=-1,permanent=True))
        self.assertEqual(spell['range'],dict(min_yards=5.,max_yards=30.,flags=0,melee=False))
        self.assertEqual(spell['effects'][0]['radius'],dict(radius_yards=10.,per_level_yards=.5,max_yards=30.))
        self.assertEqual(spell['unresolved_joins'],['SpellVisual','SpellVisualKit','SpellVisualEffectName','SpellChainEffects']);self.assertEqual(spell['missing_joins'],[])
        self.assertIs(result['execution_authority'],False)
        self.assertEqual(len(result['source_tables']),8)

    def test_optional_absent_tables_are_explicit_and_do_not_fabricate_instant_or_range(self):
        spell=self.data.spells([9001],joins=True)['rows'][0]
        self.assertIsNone(spell['casting_time']);self.assertIsNone(spell['range'])
        self.assertIsNone(spell['duration']);self.assertIsNone(spell['effects'][0]['radius'])
        self.assertIn('SpellRange',spell['unresolved_joins'])
        self.assertIn(dict(table='SpellRange',id=4),spell['missing_joins'])
        self.healthy()

    def test_missing_join_identity_reports_exact_row_and_signed_sentinel_survives(self):
        entries=data.joined_entries();rows=data.spell_rows();rows[0][18]=18;rows[0][30]=21;rows[0][36]=999;rows[0][88]=999
        entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173);self.mount(entries,'Missing')
        spell=self.data.spells([9001],joins=True,level=60)['rows'][0]
        self.assertEqual(spell['casting_time']['resolved_ms'],-1000000)
        self.assertIn(dict(table='SpellRange',id=999),spell['missing_joins'])
        self.assertIn(dict(table='SpellRadius',id=999),spell['missing_joins'])

    def test_malformed_present_join_rejects_before_loader_and_keeps_cached_metadata(self):
        for name in ('SpellCastTimes','SpellDuration','SpellRange','SpellRadius'):
            with self.subTest(name=name):
                entries=data.joined_entries();path='DBFilesClient/'+name+'.dbc';broken=bytearray(entries[path]);struct.pack_into('<I',broken,8,999);entries[path]=bytes(broken)
                self.mount(entries,name);before=self.data.spells([9001])
                with self.assertRaisesRegex(ValueError,'shape'):self.data.spells([9001],joins=True)
                self.assertEqual(self.data.spells([9001]),before);self.healthy()

    def test_nonfinite_range_or_radius_is_rejected_and_remount_discards_old_joins(self):
        entries=data.joined_entries();self.mount(entries,'Valid')
        self.assertEqual(self.data.spells([9001],joins=True)['rows'][0]['range']['max_yards'],30.)
        for name in ('SpellRange','SpellRadius'):
            broken=dict(entries);path='DBFilesClient/'+name+'.dbc';raw=bytearray(broken[path]);struct.pack_into('<f',raw,24,float('nan'));broken[path]=bytes(raw)
            self.mount(broken,name)
            with self.assertRaisesRegex(ValueError,'non-finite'):self.data.spells([9001],joins=True)
        self.mount(data.entries(),'Absent')
        self.assertIsNone(self.data.spells([9001],joins=True)['rows'][0]['range'])


if __name__=='__main__':unittest.main()
