"""Actual chat/cast events, no duplicate numbers, no save/log replay or stale actor."""
import copy,json,unittest
from tests import test_game_engine_adapter_spells as fixture
from backend.game_engine_adapter_feedback import view


class Feedback(unittest.TestCase):
    setUp=fixture.Spells.setUp
    target=fixture.Spells.target
    advance=fixture.Spells.advance
    control=fixture.Spells.control

    def say(self,text,kind='SAY'):
        with self.runtime._lock:self.runtime._local_client_command_locked(dict(op='Chat',text=text,chat_type=kind))

    def test_same_speaker_replaces_bubble_and_actual_self_lifetime_fades(self):
        self.say('One two three')
        self.advance(.25);first=view(self.runtime)
        self.assertEqual(len(first),1);self.assertEqual(first[0]['kind'],'BUBBLE');self.assertEqual(first[0]['alpha'],1.)
        self.say('Replacement');self.advance(.25)
        second=view(self.runtime);self.assertEqual(len(second),1);self.assertEqual(second[0]['text'],'Replacement')
        self.advance(1.);self.assertAlmostEqual(view(self.runtime)[0]['alpha'],1.)
        self.advance(.125);self.assertAlmostEqual(view(self.runtime)[0]['alpha'],.5)
        self.advance(.125);self.assertEqual(view(self.runtime),[])

    def test_real_cast_creates_exactly_one_damage_number_and_real_channel_three_heals(self):
        target=self.target();self.runtime.activate_ability('ability.island_spark');self.advance(1.5)
        rows=view(self.runtime);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['actor'],target)
        self.assertEqual((rows[0]['kind'],rows[0]['text']),('DAMAGE','28'))
        self.advance(1.6);self.assertEqual(view(self.runtime),[])
        actor=self.runtime._combat_state['actors']['player'];actor['health']-=80.
        self.runtime._spell_state['gcd_until']=0.
        self.runtime.activate_ability('ability.tide_mend');self.advance(3.)
        rows=view(self.runtime);self.assertEqual(len(rows),2)
        self.assertTrue(all(row['kind']=='HEAL' and row['text']=='+16' for row in rows))
        # Three canonical heal events occurred; the oldest number already expired.
        actual=[row for row in self.runtime._event_journal['events'] if row['kind']=='SPELL_EFFECT' and (row.get('payload') or {}).get('healing')]
        self.assertEqual(len(actual),3)

    def test_actual_live_npc_range_death_and_removal_gate_bubble_without_creating_actor(self):
        target=self.target();before=set(self.runtime._combat_state['actors'])
        with self.runtime._lock:
            self.runtime._append_event_locked('CHAT','NPC: Hello',actor_id=target,payload=dict(channel='MONSTER_SAY',message='Hello'))
            self.runtime._sim_time+=.25
        self.assertEqual(view(self.runtime)[0]['actor'],target)
        index=self.runtime._npc_index_for_id_locked(target);self.runtime._x[index]+=100
        self.assertEqual(view(self.runtime),[]);self.runtime._x[index]-=100
        self.runtime._combat_state['actors'][target]['alive']=False;self.assertEqual(view(self.runtime),[])
        self.runtime._alive[index]=False;self.assertEqual(view(self.runtime),[])
        self.assertEqual(set(self.runtime._combat_state['actors']),before)

    def test_private_channels_markup_and_epoch_do_not_leak_bubbles_or_replay_saved_journal(self):
        self.say('|cffff0000Hello|r |Hitem:1|h[item]|h')
        self.assertEqual(view(self.runtime)[0]['text'],'Hello [item]')
        self.say('private','EMOTE');self.assertEqual(len(view(self.runtime)),1)
        journal=copy.deepcopy(self.runtime._event_journal)
        with self.runtime._lock:self.runtime._reset_spells_locked()
        self.assertEqual(view(self.runtime),[]);self.runtime._event_journal=journal
        self.assertEqual(view(self.runtime),[])


if __name__=='__main__':unittest.main()
