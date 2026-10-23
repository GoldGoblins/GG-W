"""Group BOP consent, canonical winner custody, stale source and save retry."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_social as social
from backend import game_engine_items as items


class GroupLootBinding(unittest.TestCase):
    setUp=social.Social.setUp
    publish=social.Social.publish
    call=social.Social.call
    control=social.Social.control
    service=social.Social.service
    view=social.Social.view
    move_near_npc=social.Social.move_near_npc
    open_rare_loot=social.Social.open_rare_loot

    def roll(self):
        source,item,session=self.open_rare_loot('group')
        items.definition(self.runtime._item_catalog,item['definition_id'])['bonding']=1
        self.runtime._engine_item_templates=None
        self.assertIsNone(self.runtime.loot_slot(session,source['instance_id'],item['instance_id']).get('error'))
        self.publish();return self.runtime._services['loot_rolls'][0],item

    def test_original_need_requires_matching_confirmation_binds_exact_winner_and_cannot_replay(self):
        roll,item=self.roll();key=roll['id'];before=copy.deepcopy(self.runtime._item_instances)
        self.call(f'RollOnLoot({key},1)')
        self.assertTrue(before==self.runtime._item_instances);self.assertNotIn('player',roll['votes'])
        self.assertEqual(roll['confirmation']['vote'],1)
        self.assertEqual(self.service('LootRollVote',id=key,vote=2)['error'],'LOOT_BIND_CONFIRMATION_REQUIRED')
        self.call(f'ConfirmLootRoll({key},1)')
        actual=self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['location'],'INVENTORY');self.assertEqual(actual['bound_to'],str(self.runtime._persistence_key))
        after=copy.deepcopy(self.runtime._item_instances);self.call(f'ConfirmLootRoll({key},1)')
        self.assertTrue(after==self.runtime._item_instances)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertTrue(after==self.runtime._item_instances);self.assertFalse(self.runtime._services['loot_rolls'])
        self.assertEqual(self.service('MailSend',target='player',subject='Cannot send',item=item['instance_id'])['error'],'SERVICE_WINDOW_CHANGED_OR_CLOSED')
        self.service('MailOpen')
        self.assertIn('error',self.service('MailSend',target='player',subject='Cannot send',item=item['instance_id']))

    def test_direct_need_cancel_changed_payload_and_failed_save_preserve_pending_custody(self):
        roll,item=self.roll();key=roll['id']
        self.assertEqual(self.service('LootRollVote',id=key,vote=1)['error'],'LOOT_BIND_CONFIRMATION_REQUIRED')
        self.service('LootRollConfirm',id=key,vote=1);self.service('LootRollCancelConfirm',id=key)
        self.assertEqual(self.service('LootRollVote',id=key,vote=1)['error'],'LOOT_BIND_CONFIRMATION_REQUIRED')
        self.service('LootRollConfirm',id=key,vote=1)
        actual=self.runtime._item_instances[item['instance_id']];actual['quantity']+=1
        self.assertEqual(self.service('LootRollVote',id=key,vote=1)['error'],'LOOT_BIND_CONFIRMATION_REQUIRED')
        self.runtime._item_instances[item['instance_id']]['quantity']-=1
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._services['loot_rolls']))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('LootRollVote',id=key,vote=1)['error'],'SERVICE_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._inventory,self.runtime._services['loot_rolls']))
        self.assertIsNone(self.service('LootRollVote',id=key,vote=1).get('error'))

    def test_saved_pending_consent_restores_without_vote_and_pass_never_binds_or_awards_to_player(self):
        roll,item=self.roll();key=roll['id'];self.service('LootRollConfirm',id=key,vote=1)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        actual=self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['location'],'CONTAINER');self.assertNotIn('bound_to',actual)
        self.assertNotIn('player',self.runtime._services['loot_rolls'][0]['votes'])
        self.call(f'RollOnLoot({key},0)')
        actual=self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['location'],'POCKET');self.assertEqual(actual['bound_to'],actual['owner_id'])


if __name__=='__main__':unittest.main()
