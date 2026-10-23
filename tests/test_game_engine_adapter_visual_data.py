"""Real MPQ visual graph joins through retained typed readers and bounded failures."""
import struct,unittest
from tests import test_game_engine_adapter_game_data as fixture
from tools.world import engine_game_data_fixtures as data
from tools.world.engine_format_fixtures import table_dbc


class VisualData(unittest.TestCase):
    setUp=fixture.NativeGameplayData.setUp
    mount=fixture.NativeGameplayData.mount
    healthy=fixture.NativeGameplayData.healthy

    def test_real_stages_attachment_tags_chain_clamp_and_signed_scroll(self):
        self.mount(data.visual_entries(),'Visuals')
        result=self.data.spells([9001],joins=True);spell=result['rows'][0];visual=spell['visual']
        self.assertIsNotNone(visual)
        self.assertEqual((visual['precast'],visual['cast'],visual['impact']),(81,82,81))
        self.assertEqual(visual['missile_path'],'GG/FixtureSpark.m2')
        self.assertEqual(visual['area_path'],'GG/FixtureArea.m2')
        self.assertEqual(visual['kits']['81']['effects'],[
            dict(attachment_tag=20,effect_id=91,path='GG/FixtureSpark.m2'),
            dict(attachment_tag=65535,effect_id=92,path='GG/FixtureArea.m2')])
        proc=visual['kits']['81']['character_procs'][0]
        self.assertEqual(proc['type'],0);self.assertEqual(proc['chain']['effect_id'],101)
        self.assertEqual(proc['chain']['beams'],3);self.assertTrue(proc['chain']['channel'])
        self.assertEqual(proc['chain']['effect']['scroll_period_s'],-.5)
        self.assertEqual(proc['chain']['effect']['texture'],'GG/FixtureBeam.blp')
        self.assertEqual(spell['missing_joins'],[]);self.assertEqual(spell['unresolved_joins'],[])
        self.assertIs(result['execution_authority'],False)

    def test_absent_visual_table_never_fabricates_graph_and_missing_chain_is_explicit(self):
        entries=data.visual_entries();del entries['DBFilesClient/SpellVisualKit.dbc']
        self.mount(entries,'Absent');spell=self.data.spells([9001],joins=True)['rows'][0]
        self.assertIsNone(spell['visual']);self.assertIn('SpellVisualKit',spell['unresolved_joins'])
        entries=data.visual_entries();entries['DBFilesClient/SpellChainEffects.dbc']=table_dbc([],8)
        self.mount(entries,'MissingChain');spell=self.data.spells([9001],joins=True)['rows'][0]
        self.assertIn(dict(table='SpellChainEffects',id=101),spell['missing_joins'])
        self.assertIsNone(spell['visual']['kits']['81']['character_procs'][0]['chain']['effect'])

    def test_malformed_and_nonfinite_visual_tables_keep_earlier_metadata_and_worker_alive(self):
        for index,name in enumerate(('SpellVisual','SpellVisualKit','SpellVisualEffectName','SpellChainEffects')):
            entries=data.visual_entries();path='DBFilesClient/'+name+'.dbc';raw=bytearray(entries[path]);struct.pack_into('<I',raw,8,999);entries[path]=bytes(raw)
            self.mount(entries,'Shape'+str(index));before=self.data.spells([9001])
            with self.assertRaisesRegex(ValueError,'shape'):self.data.spells([9001],joins=True)
            self.assertEqual(self.data.spells([9001]),before);self.healthy()
        entries=data.visual_entries();raw=bytearray(entries['DBFilesClient/SpellVisualKit.dbc']);struct.pack_into('<f',raw,20+19*4,float('nan'));entries['DBFilesClient/SpellVisualKit.dbc']=bytes(raw)
        self.mount(entries,'NaN')
        with self.assertRaisesRegex(ValueError,'non-finite'):self.data.spells([9001],joins=True)
        self.healthy()


if __name__=='__main__':unittest.main()
