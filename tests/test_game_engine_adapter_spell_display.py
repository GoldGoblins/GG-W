"""Independent real Presentation/native Lua public spell-view regressions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

APP = None


class SpellDisplay(unittest.TestCase):
    def setUp(self):
        isolated = tempfile.TemporaryDirectory(prefix='gg-spell-display-')
        self.addCleanup(isolated.cleanup)
        root = Path(isolated.name)
        self.root = root
        env = {'XDG_' + kind + '_HOME': str(root / kind.lower()) for kind in ('STATE', 'CONFIG', 'CACHE', 'DATA')}
        env['QT_QPA_PLATFORM'] = 'offscreen'
        context = patch.dict(os.environ, env)
        context.start()
        self.addCleanup(context.stop)
        from backend import game_engine_mmo as mmo, game_engine_character_creation as appearance
        for context in (patch.object(mmo, 'DEFAULT_STASH_PATH', root / 'stash.json'),
                        patch.object(appearance, 'STATE_PATH', root / 'appearance.json')):
            context.start()
            self.addCleanup(context.stop)
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QObject
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_presentation import Presentation
        global APP
        APP = QGuiApplication.instance() or QGuiApplication([])
        self.runtime = GameEngineRuntime()
        self.addCleanup(self.runtime.shutdown)
        runtime = self.runtime

        class Bridge(QObject):
            def gameEngineAbility(self, ref):
                return json.dumps(runtime.activate_ability(ref))

            def gameEngineClientControl(self, raw):
                return json.dumps(runtime.client_control(raw))

        self.bridge = Bridge()
        self.presentation = Presentation(self.bridge, device=False)
        self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui)
        self.publish()

    def publish(self, snapshot=None):
        p = self.presentation
        p.last_update = 0.
        p.update(snapshot if snapshot is not None else self.runtime.snapshot())
        # Drive the real addon OnUpdate deterministically, without a window.
        p.lua.tick(.016)
        p._update_frames()
        self.assertFalse(p.errors, p.errors)
        self.assertFalse(p.lua.errors, p.lua.errors)

    def call(self, source):
        p = self.presentation
        p.lua.execute(source)
        p._ui_requests(p.lua.request('requests'))
        self.publish()

    def visible(self, name):
        return self.presentation.lua.evaluate(f'return {name}:IsVisible()') == [1]

    def armor(self):
        return self.presentation.lua.evaluate("local _,a=UnitArmor('player');return a")[0]

    def fresh_presentation(self):
        from backend.game_engine_presentation import Presentation
        self.presentation.close()
        self.presentation = Presentation(self.bridge, device=False)
        self.addCleanup(self.presentation.close)

    def advance_steps(self, steps):
        from backend.game_engine_host import FIXED_DT
        with self.runtime._lock:
            self.runtime._running = True
            try:
                for _ in range(steps):
                    self.runtime._tick_locked(FIXED_DT)
            finally:
                self.runtime._running = False

    def test_actual_public_packet_shows_four_buttons_and_authoritative_pending_bar(self):
        p = self.presentation
        self.assertTrue(all(self.visible('GGSpellControl' + str(i)) for i in range(1, 5)))
        self.assertFalse(self.visible('GGSpellCastBar'))
        self.call("CastSpell(5,'spell')")
        self.assertEqual(self.runtime._spell_state['pending']['ref'], 'ability.tide_mend')
        self.assertTrue(self.visible('GGSpellCastBar'))
        self.assertEqual(p.lua.evaluate('return GGSnapshot.client_controls.spells.casting,GGSnapshot.client_controls.spells.pending.name,GGSnapshot.client_controls.spells.pending.remaining_s'),
                         [True, 'Tide Mend', 3])
        self.assertEqual(p.lua.evaluate('return GGSnapshot.client_controls.spells.events,GGSnapshot.client_controls.spells.target_guids,GGSnapshot.client_controls.services,GGSnapshot.event_journal'),
                         [None, None, None, None])
        self.assertEqual(p.lua.evaluate('return GGSnapshot.client_controls.spells.pending.definition'), [None])
        self.call('SpellStopCasting()')
        self.assertIsNone(self.runtime._spell_state['pending'])
        self.assertFalse(self.visible('GGSpellCastBar'))
        self.assertEqual(p.lua.evaluate('return GGSnapshot.client_controls.spells.casting,GGSnapshot.client_controls.spells.pending'), [False, None])

    def test_native_armor_reflects_real_guard_and_free_cancellation_without_stale_missing_stats(self):
        r = self.runtime
        before = r.snapshot()['combat_live']['profile']['armor']
        self.assertEqual(self.armor(), int(before))
        self.call("CastSpell(7,'spell')")
        self.assertEqual(r._spell_state['form'], 'ability.reef_guard')
        self.assertEqual(r.snapshot()['combat_live']['profile']['armor'], before + 20.)
        self.assertEqual(self.armor(), int(before) + 20)
        with r._lock:
            r._resource = 0.
        self.publish()
        self.assertEqual(self.presentation.lua.evaluate('local _,_,a,c=GetShapeshiftFormInfo(1);return a,c'), [1, 1])
        self.call("CastSpell(7,'spell')")
        self.assertIsNone(r._spell_state['form'])
        self.assertEqual(r._resource, 0.)
        self.assertEqual(self.armor(), int(before))
        snapshot = r.snapshot()
        del snapshot['combat_live']['profile']
        self.publish(snapshot)
        self.assertEqual(self.armor(), 0, 'An absent armor provider must retire the previous retained stats')
        self.publish()
        self.assertEqual(self.armor(), int(before))

    def test_real_state_load_clears_public_pending_and_bar_in_the_same_retained_vm(self):
        p = self.presentation
        self.call("CastSpell(5,'spell')")
        self.assertTrue(self.visible('GGSpellCastBar'))
        previous_ui = p.lua
        epoch = self.runtime._spell_state['epoch']
        self.assertIsNone(self.runtime.save_state().get('error'))
        self.assertIsNone(self.runtime.load_state().get('error'))
        self.assertGreater(self.runtime._spell_state['epoch'], epoch)
        self.publish()
        self.assertIs(p.lua, previous_ui)
        self.assertFalse(self.visible('GGSpellCastBar'))
        self.assertEqual(p.lua.evaluate('return GGSnapshot.client_controls.spells.casting,GGSnapshot.client_controls.spells.pending,SpellStopCasting()'),
                         [False, None, None])
        self.publish()
        self.assertFalse(self.visible('GGSpellCastBar'))
        self.assertTrue(all(self.visible('GGSpellControl' + str(i)) for i in range(1, 5)))

    def test_initial_compact_ui_and_fresh_midchannel_vm_keep_complete_spellbook_and_live_armor(self):
        self.fresh_presentation()
        self.publish(self.runtime.ui_snapshot())
        self.assertEqual(self.presentation.lua.evaluate("return GetSpellName(7,'spell')")[0], 'Reef Guard')
        self.assertEqual(self.presentation.lua.evaluate('return GetNumShapeshiftForms()'), [1])
        self.assertTrue(all(self.visible('GGSpellControl' + str(i)) for i in range(1, 5)))
        self.call("CastSpell(5,'spell')")
        self.advance_steps(75)
        self.fresh_presentation()
        self.publish(self.runtime.ui_snapshot())
        self.assertTrue(self.visible('GGSpellCastBar'))
        self.assertAlmostEqual(self.presentation.lua.evaluate('return GGSnapshot.client_controls.spells.pending.remaining_s')[0], 1.75)
        self.assertEqual(self.presentation.lua.evaluate("return GetSpellName(7,'spell')")[0], 'Reef Guard')
        self.call('SpellStopCasting()')
        before = self.armor()
        self.call("CastSpell(7,'spell')")
        self.publish(self.runtime.ui_snapshot())
        self.assertEqual(self.armor(), before + 20)
        self.assertEqual(self.presentation.lua.evaluate('local _,_,a=GetShapeshiftFormInfo(1);return a'), [1])

    def test_authored_shared_invite_provider_emits_once_per_vm_after_current_getters(self):
        # This provider is a test-only authored local invitation, not an
        # external player. The real native Lua listener observes publication.
        snapshot = self.runtime.snapshot()
        controls = snapshot['player']['client_controls']['services']
        snapshot['player']['name'] = 'Authored Invite Recipient'
        controls['shared_pending_events'] = [{'key': 'authored-invite-one',
            'event': 'GUILD_INVITE_REQUEST', 'args': ['Authored Local Inviter', 'Authored Test Guild']}]
        script = "INVITE_PROOF={};I=CreateFrame('Frame');I:RegisterEvent('GUILD_INVITE_REQUEST');I:SetScript('OnEvent',function() table.insert(INVITE_PROOF,tostring(arg1)..'|'..tostring(arg2)..'|'..UnitName('player')) end)"
        expected = 'Authored Local Inviter|Authored Test Guild|Authored Invite Recipient'
        self.presentation.lua.execute(script)
        self.publish(snapshot)
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(INVITE_PROOF,',')"), [expected])
        self.fresh_presentation()
        self.presentation.lua.execute(script)
        self.publish(snapshot)
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(INVITE_PROOF,',')"), [expected])
        controls['shared_pending_events'] = []
        self.publish(snapshot)
        controls['shared_pending_events'] = [{'key': 'authored-invite-two',
            'event': 'GUILD_INVITE_REQUEST', 'args': ['Authored Second Inviter', 'Authored Second Guild']}]
        snapshot['player']['name'] = 'Authored Current Recipient'
        self.publish(snapshot)
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(INVITE_PROOF,',')"),
            [expected + ',Authored Second Inviter|Authored Second Guild|Authored Current Recipient'])

    def test_real_character_bootstrap_delivers_pending_invite_after_loaded_addon_and_failed_candidate_does_not_consume(self):
        import shutil
        import uuid
        from backend.game_engine_adapter_ui import GgEngineUI, PROJECT
        authored_root = self.root / 'authored-addons'
        shutil.copytree(PROJECT / 'qml/game/framexml', authored_root)
        addon = authored_root / 'GGInviteProbe'
        addon.mkdir()
        (addon / 'GGInviteProbe.toc').write_text('## Interface: 11200\n## Title: Authored local bootstrap proof\nInvite.lua\n')
        (addon / 'Invite.lua').write_text("BOOT_INVITES={};BOOT_CHAT={};GGInviteProbe=CreateFrame('Frame','GGInviteProbe');GGInviteProbe:Hide();GGInviteProbe:RegisterEvent('GUILD_INVITE_REQUEST');GGInviteProbe:RegisterEvent('CHAT_MSG_GUILD');GGInviteProbe:SetScript('OnEvent',function() if event=='GUILD_INVITE_REQUEST' then table.insert(BOOT_INVITES,tostring(arg1)..'|'..tostring(arg2)..'|'..UnitName('player'));GGInviteProbe:Show() else table.insert(BOOT_CHAT,tostring(arg1)) end end)")
        original_load = GgEngineUI.load_addons

        def loaded_probe(ui, root, *args, **kwargs):
            return original_load(ui, authored_root, *args, **kwargs)

        snapshot = self.runtime.snapshot()
        snapshot['player']['name'] = 'Authored Bootstrap Recipient'
        services = snapshot['player']['client_controls']['services']
        services['shared_pending_events'] = [{'key': 'authored-login-invite', 'event': 'GUILD_INVITE_REQUEST',
            'args': ['Authored Login Inviter', 'Authored Login Guild']}]
        first_key = uuid.UUID(int=101).hex
        with patch.object(GgEngineUI, 'load_addons', loaded_probe):
            self.assertTrue(self.presentation.set_character(first_key, initial_snapshot=snapshot))
        self.assertEqual(self.presentation.character_key, first_key)
        expected = 'Authored Login Inviter|Authored Login Guild|Authored Bootstrap Recipient'
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(BOOT_INVITES,','),GGInviteProbe:IsShown()"), [expected, 1])
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate('return table.getn(BOOT_INVITES)'), [1])
        previous_vm = self.presentation.lua
        previous_seen = set(self.presentation._shared_events_seen)
        services['shared_pending_events'] = [{'key': 'authored-rejected-chat', 'event': 'CHAT_MSG_GUILD',
            'ack_id': 'authored-test-only-durable-id', 'args': ['Authored durable message', 'Authored Local Speaker']}]

        def rejected_after_real_addons(ui, root, *args, **kwargs):
            original_load(ui, authored_root, *args, **kwargs)
            raise RuntimeError('Authored candidate load rejection')

        second_key = uuid.UUID(int=102).hex
        with patch.object(GgEngineUI, 'load_addons', rejected_after_real_addons):
            self.assertFalse(self.presentation.set_character(second_key, initial_snapshot=snapshot))
        self.assertIs(self.presentation.lua, previous_vm)
        self.assertEqual(self.presentation.character_key, first_key)
        self.assertEqual(self.presentation._shared_events_seen, previous_seen)
        self.assertFalse(getattr(self.presentation, '_shared_chat_ack_scheduled', False),
                         'A rejected candidate cannot acknowledge an unshown durable message')
        self.assertEqual(self.presentation.lua.evaluate('return table.getn(BOOT_CHAT)'), [0])
        self.presentation.errors.clear()  # The deliberately rejected fixture is expected.
        services['shared_pending_events'][0].pop('ack_id')
        with patch.object(GgEngineUI, 'load_addons', loaded_probe):
            self.assertTrue(self.presentation.set_character(second_key, initial_snapshot=snapshot))
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(BOOT_CHAT,',')"), ['Authored durable message'])
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate('return table.getn(BOOT_CHAT)'), [1])

    def test_postcommit_real_worker_retirement_cannot_roll_back_character_or_ack_unshown_chat(self):
        import uuid
        from backend.game_engine_adapter_ui import GgEngineUI
        previous = self.presentation.lua
        snapshot = self.runtime.snapshot()
        snapshot['player']['client_controls']['services']['shared_pending_events'] = [
            {'key': 'authored-postcommit-chat', 'event': 'CHAT_MSG_GUILD',
             'ack_id': 'authored-undelivered-message', 'args': ['Authored pending text', 'Authored Local Speaker']}]
        original_event = GgEngineUI.event
        retired = []

        def timed_out_event(ui, event, *args):
            if ui is not previous and event == 'CHAT_MSG_GUILD':
                # A real request timeout retires the worker. Retire the actual
                # native subprocess here as the deterministic fault fixture.
                ui.close()
                retired.append(ui)
                raise TimeoutError('Authored postcommit native event timeout')
            return original_event(ui, event, *args)

        key = uuid.UUID(int=103).hex
        with patch.object(GgEngineUI, 'event', timed_out_event):
            self.assertTrue(self.presentation.set_character(key, initial_snapshot=snapshot))
        self.assertEqual(retired, [self.presentation.lua])
        self.assertTrue(self.presentation.lua.closed)
        self.assertTrue(previous.closed)
        self.assertEqual(self.presentation.character_key, key,
                         'Postcommit display failure cannot roll back the accepted local character')
        self.assertNotIn('authored-postcommit-chat', self.presentation._shared_events_seen)
        self.assertFalse(getattr(self.presentation, '_shared_chat_ack_scheduled', False))
        with self.assertRaises(RuntimeError):
            self.presentation.lua.frames()
        self.assertTrue(any('postcommit native event timeout' in value for value in self.presentation.errors))
        # Recover the same accepted scope from the genuinely dead worker.
        # A real authored addon registers its native listener before pending
        # durable events are replayed into the replacement VM.
        import shutil
        from backend.game_engine_adapter_ui import PROJECT
        root = self.root / 'authored-recovery-addons'
        shutil.copytree(PROJECT / 'qml/game/framexml', root)
        addon = root / 'GGRecoveryProbe'
        addon.mkdir()
        (addon / 'GGRecoveryProbe.toc').write_text('## Interface: 11200\nRecovery.lua\n')
        (addon / 'Recovery.lua').write_text("RECOVERY_CHAT={};R=CreateFrame('Frame');R:RegisterEvent('CHAT_MSG_GUILD');R:SetScript('OnEvent',function() table.insert(RECOVERY_CHAT,arg1..'|'..UnitName('player')) end)")
        original_load = GgEngineUI.load_addons

        def load_recovery(ui, ignored, *args, **kwargs):
            return original_load(ui, root, *args, **kwargs)

        dead_vm = self.presentation.lua
        with patch.object(GgEngineUI, 'load_addons', load_recovery):
            self.assertTrue(self.presentation._reload_ui())
        self.assertIsNot(self.presentation.lua, dead_vm)
        self.assertFalse(self.presentation.lua.closed)
        self.assertEqual(self.presentation.character_key, key)
        name = snapshot['player'].get('name', 'Gold Goblin')
        self.assertEqual(self.presentation.lua.evaluate("return table.concat(RECOVERY_CHAT,',')"),
                         ['Authored pending text|' + name])
        self.assertIn('authored-postcommit-chat', self.presentation._shared_events_seen)
        self.assertTrue(self.presentation._shared_chat_ack_scheduled,
                        'Only the replacement that actually showed the message can schedule its ack')
        self.presentation.errors.clear()  # Both deliberately injected faults were handled.
        self.publish(snapshot)
        self.assertEqual(self.presentation.lua.evaluate('return table.getn(RECOVERY_CHAT)'), [1])

    def test_native_lifecycle_listeners_read_current_public_pending_and_armor_notifications_once(self):
        p = self.presentation
        p.lua.execute("DISPLAY_EVENTS={};RESIST_EVENTS={};D=CreateFrame('Frame');D:RegisterEvent('SPELLCAST_CHANNEL_START');D:RegisterEvent('SPELLCAST_CHANNEL_STOP');D:RegisterEvent('UNIT_RESISTANCES');D:SetScript('OnEvent',function() if event=='UNIT_RESISTANCES' then local _,armor=UnitArmor(arg1);table.insert(RESIST_EVENTS,tostring(arg1)..'|'..tostring(armor)) else local s=GGSnapshot.client_controls.spells;table.insert(DISPLAY_EVENTS,event..'|'..tostring(s.casting)..'|'..tostring(s.pending and s.pending.name)) end end)")
        self.call("CastSpell(5,'spell')")
        self.call('SpellStopCasting()')
        self.assertEqual(p.lua.evaluate("return table.concat(DISPLAY_EVENTS,',')"),
                         ['SPELLCAST_CHANNEL_START|true|Tide Mend,SPELLCAST_CHANNEL_STOP|false|nil'])
        self.advance_steps(75)
        self.publish()
        before = self.armor()
        self.call("CastSpell(7,'spell')")
        self.assertEqual(p.lua.evaluate("return table.concat(RESIST_EVENTS,',')"), ['player|' + str(before + 20)])
        self.publish()
        self.assertEqual(p.lua.evaluate('return table.getn(RESIST_EVENTS)'), [1])


if __name__ == '__main__':
    unittest.main()
