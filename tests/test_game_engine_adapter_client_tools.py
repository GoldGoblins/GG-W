"""Original local Help and client requests have observable durable effects."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
import test_game_engine_adapter_services as services


class ClientTools(unittest.TestCase):
    setUp=services.Services.setUp
    call=services.Services.call
    control=services.Services.control
    publish=services.Services.publish
    service=services.Services.service
    view=services.Services.view

    def test_original_ticket_local_category_events_write_update_delete_and_reload(self):
        self.ui.execute("tickets={};statuses={};f=CreateFrame('Frame');f:RegisterEvent('UPDATE_TICKET');f:RegisterEvent('UPDATE_GM_STATUS');f:SetScript('OnEvent',function() if event=='UPDATE_TICKET' then table.insert(tickets,{arg1,arg2,arg6,arg7}) else table.insert(statuses,arg1) end end)")
        self.call('GetGMTicket() GetGMStatus()')
        self.assertEqual(self.ui.evaluate('return tickets[1][1],statuses[1]'),[0,-1])
        self.assertIn('Local issue note',self.ui.evaluate('return GetGMTicketCategories()')[1])
        self.call('NewGMTicket(1,"A local rendering issue")')
        self.assertEqual(self.ui.evaluate('return tickets[2][2],tickets[2][3],tickets[2][4]'),['A local rendering issue',0,0])
        self.runtime.load_state();self.assertEqual(self.runtime._services['support_note']['text'],'A local rendering issue')
        self.call('UpdateGMTicket(1,"Updated issue")');self.assertEqual(self.runtime._services['support_note']['text'],'Updated issue')
        self.call('DeleteGMTicket()');self.runtime.load_state();self.assertIsNone(self.runtime._services['support_note'])

    def test_failed_support_commit_preserves_text_and_invalid_category_has_no_effect(self):
        self.service('SupportWrite',category=1,text='Keep',new=True);before=copy.deepcopy(self.runtime._services['support_note'])
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('SupportWrite',category=1,text='Lost',new=False)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,self.runtime._services['support_note'])
        self.assertIn('error',self.service('SupportWrite',category=999,text='Lost',new=False));self.assertEqual(before,self.runtime._services['support_note'])

    def test_logging_original_flags_bounded_files_stop_and_no_duplicate_combat(self):
        root=self.presentation.client_tools.root();self.call('LoggingChat(true) LoggingCombat(true) SendChatMessage("Test line","SAY")')
        chat=root/'Logs/Chat.log';self.assertIn('Test line',chat.read_text())
        self.call('LoggingChat(false) SendChatMessage("Hidden line","SAY")');self.assertNotIn('Hidden line',chat.read_text())
        self.presentation.client_tools.snapshot(self.runtime.snapshot())
        with self.runtime._lock:self.runtime._append_event_locked('COMBAT_ATTACK','Actual attack',actor_id='player')
        self.publish();combat=root/'Logs/Combat.log';first=combat.read_bytes();self.publish();self.assertEqual(first,combat.read_bytes());self.assertIn(b'Actual attack',first)
        tools=self.presentation.client_tools
        for _ in range(3):tools.log('FrameXML.log',['x'*1024]*600)
        self.assertLessEqual((root/'Logs/FrameXML.log').stat().st_size,1024*1024)
        tools.log('FrameXML.log',['Only new load'],rewrite=True);self.assertEqual((root/'Logs/FrameXML.log').read_text(),'Only new load\n')

    def test_original_screenshot_without_window_reports_failure_and_never_success(self):
        self.ui.execute("shot={};f=CreateFrame('Frame');f:RegisterEvent('SCREENSHOT_SUCCEEDED');f:RegisterEvent('SCREENSHOT_FAILED');f:SetScript('OnEvent',function() table.insert(shot,event) end)")
        self.call('Screenshot()');QCoreApplication.processEvents()
        self.assertEqual(self.ui.evaluate('return shot[1]'),['SCREENSHOT_FAILED']);self.assertFalse(self.presentation.client_tools.capture_pending)

    def test_read_queries_work_when_disk_is_full_but_real_mutations_still_roll_back(self):
        from backend.game_engine_adapter_gameplay import identity
        self.service('MailOpen');before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state,self.runtime._services['mail']))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')) as save:
            self.assertIsNone(self.service('ItemInfo',id=identity('item.weapon_sword')).get('error'));save.assert_not_called()
            self.assertIsNone(self.service('SupportAsk').get('error'));save.assert_not_called()
            self.assertEqual(self.service('MailSend',target='player',subject='Must not land',money=5)['error'],'SERVICE_SAVE_FAILED')
            save.assert_called_once()
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._economy_state,self.runtime._services['mail']))

    def test_macro_client_tools_log_the_first_message_capture_failure_and_reload_vm(self):
        self.call('CreateMacro("Client tools",1,[[/script LoggingChat(true) SendChatMessage("Macro chat","SAY") Screenshot()]],nil,nil)')
        self.assertIsNone(self.presentation.run_macro(1).get('error'));QCoreApplication.processEvents()
        self.assertIn('Macro chat',(self.presentation.client_tools.root()/'Logs/Chat.log').read_text())
        self.assertFalse(self.presentation.client_tools.capture_pending)
        self.call('CreateMacro("Reload",1,[[/script ConsoleExec("reloadui")]],nil,nil)')
        original=self.presentation.lua;self.assertIsNone(self.presentation.run_macro(2).get('error'))
        self.assertIsNot(original,self.presentation.lua);self.assertTrue(original.closed)

if __name__=='__main__':unittest.main()
