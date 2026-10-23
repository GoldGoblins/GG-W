"""Original Lua calls against real local state, including repeat/save guards."""
import copy,json,math,unittest
import test_game_engine_adapter_controls as control_tests

class LocalClient(unittest.TestCase):
    setUp=control_tests.Controls.setUp
    publish=control_tests.Controls.publish
    call=control_tests.Controls.call
    control=control_tests.Controls.control
    def local(self,op,**fields):return self.control('local',op,**fields)
    def test_sit_render_stow_movement_jump_and_dead_gate(self):
        self.control('input','Fire',key='SitOrStand')
        self.assertEqual(self.runtime._stand_state,1);self.assertEqual(self.runtime._player_display['sheath'],0)
        with self.runtime._lock:
            self.runtime._grounded=True;self.runtime._vx[0]=self.runtime._vz[0]=0.
        entity=next(r for r in self.runtime.render_snapshot()['render']['entities'] if r['kind']=='PLAYER')
        self.assertEqual(entity['animation']['locomotion'],'SIT');self.assertEqual(entity['asset']['runtime_clip'],'Sit')
        self.control('input','Start',key='TurnOrAction');self.control('input','Start',key='TurnRight')
        self.runtime._client_tick_input_locked({});self.assertEqual(self.runtime._stand_state,0)
        self.control('input','Cancel');self.control('input','Fire',key='SitOrStand')
        self.control('input','Fire',key='Jump');self.assertEqual(self.runtime._stand_state,0)
        self.runtime._combat_state['actors']['player'].update(alive=False,health=0)
        self.control('input','Fire',key='SitOrStand');self.assertEqual(self.runtime._stand_state,0)
    def test_posture_refuses_motion_and_lua_emotes_use_same_setter(self):
        self.control('input','Start',key='MoveForward');self.call("DoEmote('SIT')")
        self.assertEqual(self.runtime._stand_state,0)
        self.control('input','Cancel');self.call("DoEmote('SLEEP')")
        self.assertEqual(self.runtime._stand_state,3)
        self.call("DoEmote('KNEEL')");self.assertEqual(self.runtime._stand_state,8)
        self.control('player','Stand',state=0);self.assertEqual(self.runtime._stand_state,0)
    def test_selection_order_last_target_and_player_identity(self):
        target=self.runtime._target_rows_locked(require_sight=True)[0]
        self.call('TargetByName('+json.dumps(target['name'])+',true)')
        self.assertEqual(self.runtime._combat_target_id,target['id'])
        self.call("TargetUnit('player')");self.assertEqual(self.runtime._combat_target_id,'player')
        self.assertEqual(self.ui.evaluate("return UnitIsUnit('target','player'),UnitCanAttack('player','target')"),[1,None])
        self.call('TargetLastTarget()');self.assertEqual(self.runtime._combat_target_id,target['id'])
        self.call('ClearTarget()');self.assertEqual(self.runtime._combat_target_id,'')
        self.assertEqual(self.ui.evaluate("return UnitExists('target')"),[None])
        self.call('TargetLastEnemy()');self.assertEqual(self.runtime._combat_target_id,target['id'])
    def test_follow_moves_real_body_cancel_and_save_drops_follow(self):
        target=self.runtime._target_rows_locked(require_sight=True)[0]
        self.call('FollowByName('+json.dumps(target['name'])+',true)');self.assertEqual(self.runtime._follow_id,target['id'])
        with self.runtime._lock:
            before=(self.runtime._x[0],self.runtime._z[0]);self.runtime._running=True
            try:
                for _ in range(30):self.runtime._tick_locked(1/60)
            finally:self.runtime._running=False
        self.assertGreater(math.hypot(self.runtime._x[0]-before[0],self.runtime._z[0]-before[1]),.2)
        self.control('input','Start',key='MoveBackward');self.runtime._client_tick_input_locked({});self.assertFalse(self.runtime._follow_id)
        self.control('input','Cancel');self.call('FollowByName('+json.dumps(target['name'])+',true)')
        self.runtime.save_state();self.runtime.load_state();self.assertFalse(self.runtime._follow_id)
    def test_tutorial_bank_original_flags_and_character_save(self):
        self.call('ClearTutorials()');self.assertEqual(self.ui.evaluate('return TutorialsEnabled()'),[None])
        self.assertEqual(self.runtime._local_client['tutorials'],[255]*32)
        self.call('ResetTutorials() FlagTutorial(1) FlagTutorial(50)')
        self.assertEqual(self.runtime._local_client['tutorials'][0],1);self.assertEqual(self.runtime._local_client['tutorials'][6],2)
        saved=copy.deepcopy(self.runtime._local_client);self.runtime.save_state();self.call('ClearTutorials()');self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._local_client,saved);self.assertEqual(self.ui.evaluate('return TutorialsEnabled()'),[1])
        self.call('FlagTutorial(2) ResetTutorials()');self.assertEqual(self.runtime._local_client['tutorials'],[0]*32)
        self.call('for i=1,200 do FlagTutorial(1) end');self.assertEqual(self.runtime._local_client['tutorials'],[0]*32)
    def test_friend_ignore_repeat_bounds_and_original_lua_views(self):
        self.call("AddFriend('Ava') AddFriend('ava') AddIgnore('Rune')")
        self.assertEqual(self.runtime._local_client['friends'],['Ava']);self.assertEqual(self.ui.evaluate('return GetNumFriends(),GetNumIgnores()'),[1,1])
        self.call("RemoveFriend('AVA') DelIgnore('Rune')");self.assertEqual(self.ui.evaluate('return GetNumFriends(),GetNumIgnores()'),[0,0])
        before=copy.deepcopy(self.runtime._local_client)
        for row in ({'op':'Social','action':'AddFriend','name':'x\nsecret'},{'op':'ActionBars','value':True},{'op':'TutorialFlag','index':50},{'op':'MinimapPing','position':[float('nan'),0]}):
            self.assertIn('error',self.local(row.pop('op'),**row))
        self.assertEqual(before,self.runtime._local_client)
    def test_talent_refund_repeat_and_actual_save(self):
        ranks=self.runtime._progression['talents'];expected=self.runtime._progression['talent_points']+sum(ranks.values())
        self.call('ConfirmTalentWipe()');self.assertEqual(self.runtime._progression['talent_points'],expected);self.assertTrue(all(v==0 for v in self.runtime._progression['talents'].values()))
        self.call('ConfirmTalentWipe()');self.assertEqual(self.runtime._progression['talent_points'],expected)
        self.runtime.save_state();self.runtime.load_state();self.assertEqual(self.runtime._progression['talent_points'],expected)
    def test_chat_roll_played_events_and_failed_delivery_no_journal_write(self):
        self.ui.execute("CreateFrame('Frame','LocalObserver') LocalEvents={} LocalObserver:RegisterEvent('CHAT_MSG_SAY') LocalObserver:RegisterEvent('TIME_PLAYED_MSG') LocalObserver:SetScript('OnEvent',function() table.insert(LocalEvents,event) end)")
        self.call("SendChatMessage('Local hello','SAY') RequestTimePlayed()")
        self.assertEqual(self.ui.evaluate('return table.getn(LocalEvents)'),[2])
        self.assertTrue(any('Local hello' in e.get('text','') for e in self.runtime.snapshot()['event_journal']['events']))
        roll=self.local('Roll',low=13,high=13);self.assertIn('13 (13-13)',roll['client_events'][0]['args'][0])
        before=copy.deepcopy(self.runtime.snapshot()['event_journal']['events'])
        self.assertIn('error',self.local('Chat',text='Never delivered',chat_type='WHISPER',target='Missing Recipient'))
        self.assertEqual(self.runtime.snapshot()['event_journal']['events'],before)

    def test_missing_graphics_window_reports_error_drains_requests_and_keeps_cursor(self):
        self.ui.execute("MissingErrors=0 local f=CreateFrame('Frame');f:RegisterEvent('UI_ERROR_MESSAGE');f:SetScript('OnEvent',function() MissingErrors=MissingErrors+1 end)")
        before=self.runtime.snapshot();self.ui.execute("RestartGx()")
        requests=self.ui.request('requests');rows=requests['unimplemented']
        self.assertFalse(rows)
        self.assertEqual(requests['client_tools']['graphics_restarts'],1)
        self.presentation._ui_requests(requests)
        self.assertEqual(self.ui.evaluate('return MissingErrors'),[1]);self.assertEqual(self.presentation.graphics.error,'GRAPHICS_WINDOW_UNAVAILABLE')
        self.assertEqual(self.ui.request('requests')['client_tools']['graphics_restarts'],0)
        after=self.runtime.snapshot();self.assertEqual(before['items'],after['items']);self.assertEqual(before['economy'],after['economy'])
        # A contextual sale consumer is not a request queue. Ordinary request
        # draining must leave a real held item available for its next drop.
        self.ui.execute('PickupContainerItem(0,1)');held=self.ui.evaluate('return CursorHasItem()')
        self.assertEqual(held,[1]);self.ui.request('requests');self.assertEqual(self.ui.evaluate('return CursorHasItem()'),held)

    def test_who_filters_actual_local_people_preserves_sort_and_friend_presence(self):
        with self.runtime._lock:people=self.runtime._local_people_locked();person=people[1]
        self.call('AddFriend('+json.dumps(person['name'])+') SetWhoToUI(true) SendWho('+json.dumps('n-"'+person['name']+'" '+str(person['level']))+')')
        self.assertEqual(self.ui.evaluate('return GetNumWhoResults()'),[1,1]);self.assertEqual(self.ui.evaluate('return GetWhoInfo(1)')[0],person['name'])
        self.call("SendWho('n-no-such-local-person')")
        self.assertEqual(self.ui.evaluate('return GetNumWhoResults()'),[0,0]);self.assertEqual(self.ui.evaluate('return GetFriendInfo(1)')[4],1)
        self.call("SendWho('') SortWho('name') SortWho('name')")
        first=self.ui.evaluate('return GetWhoInfo(1)')[0]
        self.publish();self.assertEqual(self.ui.evaluate('return GetWhoInfo(1)')[0],first)
        names=[p['name'] for p in people[:49]];self.assertEqual(first,sorted(names,key=str.lower,reverse=True)[0])
        before=self.runtime._who_filter;self.assertIn('error',self.local('Social',action='Who',query='bad\nquery'))
        self.assertEqual(self.runtime._who_filter,before)

    def test_original_cursor_override_and_reset_reach_actual_qt_item(self):
        from PySide6.QtCore import Qt
        from PySide6.QtQuick import QQuickItem
        item=QQuickItem();item.setWidth(800);item.setHeight(600)
        self.presentation.attachCanvas(item,True);canvas=self.presentation._canvas
        self.call("SetCursor('CAST_CURSOR')")
        self.assertEqual(canvas.cursor().shape(),Qt.CursorShape.CrossCursor)
        self.call("SetCursor('CAST_ERROR_CURSOR')")
        self.assertEqual(canvas.cursor().shape(),Qt.CursorShape.ForbiddenCursor)
        self.call('ResetCursor()');self.assertEqual(canvas.cursor().shape(),Qt.CursorShape.ArrowCursor)
        self.assertFalse(any('take_cursor_write' in r for r in self.presentation.unsupported_requests))
        canvas.close();self.presentation._canvas=None

if __name__=='__main__':unittest.main()
