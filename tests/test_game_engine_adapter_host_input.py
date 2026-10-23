"""Original host-input drain and real pet/profession training tooltip views."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services


class HostInput(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc
    tame=services.Services.tame

    def setUp(self):
        services.Services.setUp(self)
        self.ui.execute("CHAT_COUNT=0;CHAT_TEXT='';CF=CreateFrame('Frame');CF:RegisterEvent('CHAT_MSG_SAY');CF:SetScript('OnEvent',function() CHAT_COUNT=CHAT_COUNT+1;CHAT_TEXT=arg1 end)")

    def submit(self,line):
        self.ui.request('chat_input',line=line)
        packet=self.ui.request('requests');self.presentation._ui_requests(packet);self.publish()
        return packet

    def test_original_host_queue_says_once_and_same_parser_targets_and_changes_actual_posture(self):
        packet=self.submit('Hello from the dock')
        self.assertEqual(packet['chat_input'],['Hello from the dock'])
        self.assertFalse(any(r['method']=='take_chat_input' for r in packet['unimplemented']))
        self.assertEqual(self.ui.evaluate('return CHAT_COUNT,CHAT_TEXT'),[1,'Hello from the dock'])
        self.presentation._ui_requests(self.ui.request('requests'));self.publish()
        self.assertEqual(self.ui.evaluate('return CHAT_COUNT'),[1])
        self.move_near_npc();self.publish();self.submit('/targetexact Mira Saltwake')
        self.assertEqual(self.runtime._combat_target_id,'npc-wanderer-01')
        self.submit('/kneel');self.assertEqual(self.runtime._stand_state,8)

    def test_oversized_batch_invalid_line_and_empty_input_never_emit_partial_chat(self):
        for _ in range(65):self.ui.request('chat_input',line='bounded batch')
        self.presentation._ui_requests(self.ui.request('requests'));self.publish()
        self.assertEqual(self.ui.evaluate('return CHAT_COUNT'),[0])
        for line in ('a\nsecond line','x'*256):
            with self.assertRaises((ValueError,RuntimeError)):self.ui.request('chat_input',line=line)
        self.submit('  ');self.assertEqual(self.ui.evaluate('return CHAT_COUNT'),[0])

    def trainer_tip(self,name):
        self.call("SetTrainerServiceTypeFilter('used',1);TIP=CreateFrame('GameTooltip','HostTrainerTip');for i=1,GetNumTrainerServices() do local n=GetTrainerServiceInfo(i);if n=="+repr(name)+" then TIP:SetTrainerService(i) end end")
        return self.ui.evaluate("local text='';for i=1,TIP:NumLines() do local row=getglobal('HostTrainerTipTextLeft'..i);if row then text=text..(row:GetText() or '')..'\\n' end end;return text")[0]

    def test_original_trainer_hover_describes_unlearned_guard_without_training_or_spending(self):
        pet=self.tame();self.move_near_npc();self.service('TrainerOpen',target='npc-wanderer-01');self.publish()
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,pet['learned']))
        text=self.trainer_tip('Guard');self.assertIn('Guard',text);self.assertIn('3 armor',text)
        self.assertNotIn(str(0x800103),pet['learned'])
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,pet['learned']))

    def test_profession_hover_is_real_and_unknown_spell_lookup_refuses_without_learning_or_save(self):
        self.move_near_npc();self.service('TrainerOpen',target='npc-wanderer-01',mode='PROFESSION');self.publish()
        before=copy.deepcopy((self.runtime._profession_state,self.runtime._economy_state,self.runtime._item_instances))
        text=self.trainer_tip('Blacksmithing');self.assertIn('Blacksmithing',text);self.assertIn('level 1',text)
        with patch.object(self.runtime,'save_state',wraps=self.runtime.save_state) as save:
            self.assertEqual(self.service('SpellTooltipRequest',id=1,pet=False)['error'],'SPELL_TEMPLATE_NOT_LOCAL')
            self.assertEqual(self.service('SpellTooltipRequest',id=0x800103,pet=True)['error'],'SPELL_TEMPLATE_NOT_LOCAL')
            self.assertFalse(save.called)
        self.assertEqual(before,(self.runtime._profession_state,self.runtime._economy_state,self.runtime._item_instances))

if __name__=='__main__':unittest.main()
