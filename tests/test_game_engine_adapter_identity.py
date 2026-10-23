"""Canonical local identity labels through Python and original native getters."""
from copy import deepcopy
import unittest
from backend.game_engine_adapter_identity import identity,SCHEMA
from backend.game_engine_character_creation import catalog


def selected(class_id='cowboy',race_id='squirrel_fox'):
    return {'character_creation':{'active':True,'selection':{'class_id':class_id,'race_id':race_id}},
            'progression':{'class_id':'class.pathfinder','race':'ISLANDER'}}


class Identity(unittest.TestCase):
    def test_all_five_actual_classes_and_ten_catalog_races_keep_their_canonical_names(self):
        for row in catalog()['classes']:
            with self.subTest(class_id=row['id']):
                packet=identity(selected(class_id=row['id']))
                self.assertEqual(packet['class'],dict(id=row['id'],name=row['name'],file=row['id'].upper()))
        for row in catalog()['races']:
            with self.subTest(race_id=row['id']):
                packet=identity(selected(race_id=row['id']))
                self.assertEqual(packet['race'],dict(id=row['id'],name=row['name'],file=row['id'].upper()))

    def test_inactive_appearance_defaults_do_not_replace_real_pathfinder_progression(self):
        snapshot=selected();snapshot['character_creation']['active']=False
        packet=identity(snapshot)
        self.assertEqual(packet['class'],dict(id='class.pathfinder',name='Pathfinder',file='PATHFINDER'))
        self.assertEqual(packet['race'],dict(id='race.islander',name='Islander',file='ISLANDER'))

    def test_original_class_and_unknown_tokens_are_never_fabricated(self):
        packet=identity(selected('warrior','human'))
        self.assertIsNone(packet['class']);self.assertIsNone(packet['race'])
        self.assertEqual(set(packet),{'schema','class','race'})
        self.assertEqual(identity({}),dict(schema=SCHEMA,**{'class':None,'race':None}))

    def test_metadata_does_not_mutate_character_snapshot_or_add_policy(self):
        snapshot=selected();before=deepcopy(snapshot);packet=identity(snapshot)
        self.assertEqual(snapshot,before)
        self.assertNotIn('damage_bonus_stat',packet);self.assertNotIn('has_relic_slot',packet)

    def test_malformed_input_rejects_without_mutating_the_source(self):
        invalid=[None,[],{'character_creation':[]},{'progression':[]},
                 {'character_creation':{'active':'yes'}},{'character_creation':{'active':True,'selection':[]}},
                 selected(class_id=True),selected(race_id='x'*65),selected(class_id='../cowboy')]
        for snapshot in invalid:
            with self.subTest(snapshot=snapshot):
                before=deepcopy(snapshot)
                with self.assertRaises(ValueError):identity(snapshot)
                self.assertEqual(snapshot,before)


class NativeIdentity(unittest.TestCase):
    def setUp(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        self.ui=GgEngineUI();self.addCleanup(self.ui.close)

    def publish(self,packet):self.ui.publish({},False,100.,100.,name='Identity Test',identity=packet)
    def getters(self):return self.ui.evaluate('local c,cf=UnitClass("player");local r,rf=UnitRace("player");return c,cf,r,rf')

    def test_actual_selected_identity_replaces_default_player_record_and_unit(self):
        self.publish(identity(selected('rogue','mossjaw')))
        self.assertEqual(self.getters(),['Rogue','ROGUE','Mossjaw','MOSSJAW'])
        self.assertEqual(self.ui.evaluate('return UnitName("player"),GetDamageBonusStat(),UnitHasRelicSlot("player")'),['Identity Test',0,None])

    def test_selection_replacement_and_unknown_identity_do_not_keep_a_previous_class(self):
        self.publish(identity(selected()));self.assertEqual(self.getters(),['Cowboy','COWBOY','Rävekorre','SQUIRREL_FOX'])
        self.publish(identity(selected('wizard','briarstride')));self.assertEqual(self.getters(),['Trollkarl','WIZARD','Briarstride','BRIARSTRIDE'])
        self.publish(identity(selected('unknown','unknown')));self.assertEqual(self.getters(),[None,None,None,None])

    def test_fresh_ui_reloads_the_same_authoritative_progression_identity(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        packet=identity({'progression':{'class_id':'class.pathfinder','race':'TIDEBORN'}})
        self.publish(packet);self.assertEqual(self.getters(),['Pathfinder','PATHFINDER','Tideborn','TIDEBORN'])
        self.ui.close();self.ui=GgEngineUI();self.addCleanup(self.ui.close);self.publish(packet)
        self.assertEqual(self.getters(),['Pathfinder','PATHFINDER','Tideborn','TIDEBORN'])

    def test_malformed_native_packet_cannot_partially_replace_retained_player_identity(self):
        valid=identity(selected());self.publish(valid);before=self.getters()
        invalid=[[],{'schema':'wrong','class':None,'race':None},
                 {**valid,'class':{**valid['class'],'file':'WARRIOR'}},
                 {**valid,'race':{**valid['race'],'name':'bad\nname'}},
                 {**valid,'class':{**valid['class'],'damage_bonus_stat':1}},
                 {**valid,'class':{**valid['class'],'name':'x'*385}},
                 {**valid,'race':{**valid['race'],'id':True}}]
        for packet in invalid:
            with self.subTest(packet=packet):
                with self.assertRaisesRegex(ValueError,'character identity'):self.publish(packet)
                self.assertEqual(self.getters(),before)


if __name__=='__main__':unittest.main()
