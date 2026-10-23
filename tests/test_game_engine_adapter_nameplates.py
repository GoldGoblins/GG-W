"""Original pooled widgets obey canonical health/party and actual host selection."""
import unittest
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_assets import texture_path
from backend.game_engine_adapter_formats import AssetCache
from backend import game_engine_combat as combat


class Nameplates(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def project(self,person,x=400.,y=200.,**fields):
        row=next(p for p in self.view()['people'] if p['id']==person)
        result=self.ui.request('nameplates',rows=[dict(guid=row['guid'],x=x,y=y)],**fields);self.ui.frames();return result

    def test_toggle_party_health_geometry_and_same_widget_reuse(self):
        person=self.move_near_npc();self.publish();self.runtime._running=True;self.addCleanup(setattr,self.runtime,'_running',False);self.publish()
        self.call('ShowNameplates()');self.assertEqual(self.project(person)['shown'],1)
        self.ui.execute("plate=nil; for _,f in ipairs({WorldFrame:GetChildren()}) do if f:GetObjectType()=='Button' and not f:GetName() then plate=f end end")
        visible,alpha=self.ui.evaluate('return plate:IsShown(),plate:GetAlpha()');self.assertEqual(visible,1);self.assertAlmostEqual(alpha,178/255,places=6)
        self.ui.execute('bar=plate:GetChildren(); plateId=plate')
        row=next(p for p in self.view()['people'] if p['id']==person)
        self.assertEqual(self.ui.evaluate('return bar:GetValue()'),[row['health']])
        self.call('HideNameplates()');self.assertEqual(self.project(person)['shown'],0);self.assertEqual(self.ui.evaluate('return plate:IsShown()'),[None])
        self.call('ShowNameplates()');self.assertEqual(self.project(person)['pooled'],1);self.assertEqual(self.ui.evaluate('return plate==plateId'),[True])
        self.service('GroupInvite',target=person);self.publish();self.assertEqual(self.project(person)['shown'],0)
        self.call('ShowFriendNameplates()');self.assertEqual(self.project(person)['shown'],1)
        self.call('HideFriendNameplates() ShowFriendNameplates() HideFriendNameplates()');self.assertEqual(self.project(person)['shown'],0)

    def test_physical_click_selects_real_actor_and_freelook_disables_clicks(self):
        person=self.move_near_npc();self.runtime._running=True;self.addCleanup(setattr,self.runtime,'_running',False);self.publish();self.call('ShowNameplates()');self.project(person)
        self.ui.pointer('move',400,218);self.ui.pointer('press',400,218);self.ui.pointer('release',400,218)
        self.presentation._ui_requests(self.ui.request('requests'));self.assertEqual(self.runtime._combat_target_id,person)
        self.publish();self.project(person);self.ui.execute("plate=nil; for _,f in ipairs({WorldFrame:GetChildren()}) do if f:GetObjectType()=='Button' and not f:GetName() then plate=f end end")
        self.assertEqual(self.ui.evaluate('return plate:GetAlpha()'),[1])
        self.control('player','Clear');self.project(person,freelook=True)
        self.ui.pointer('press',400,218);self.ui.pointer('release',400,218);self.presentation._ui_requests(self.ui.request('requests'));self.assertEqual(self.runtime._combat_target_id,'')

    def test_departed_dead_offscreen_and_unknown_entities_do_not_leave_live_widgets(self):
        person=self.move_near_npc();self.runtime._running=True;self.addCleanup(setattr,self.runtime,'_running',False);self.publish();self.call('ShowNameplates()');self.assertEqual(self.project(person)['shown'],1)
        self.assertEqual(self.project(person,x=-1)['shown'],0)
        self.assertEqual(self.ui.request('nameplates',rows=[dict(guid=999999,x=400,y=200)])['shown'],0)
        self.assertEqual(self.project(person)['shown'],1)
        with self.runtime._lock:self.runtime._x[0]+=100
        self.publish();self.assertEqual(self.project(person)['shown'],0)
        cache=AssetCache();self.addCleanup(cache.close)
        for path in ('Interface/Tooltips/Nameplate-Border','Interface/TargetingFrame/UI-TargetingFrame-BarFill','Interface/TargetingFrame/UI-TargetingFrame-Skull','Interface/TargetingFrame/UI-RaidTargetingIcons'):
            self.assertTrue(texture_path(path).is_file());self.assertTrue(cache.texture_path(path).is_file())

    def test_ui_replacement_preserves_actual_viewport_and_creates_world_root(self):
        self.ui.resize(1440,900)
        self.call('ShowNameplates()');self.assertTrue(self.presentation.nameplatesEnabled)
        previous=self.ui
        self.assertTrue(self.presentation._reload_ui())
        self.ui=self.presentation.lua;self.assertTrue(previous.closed)
        self.assertEqual(self.ui._size,(1440.,900.))
        self.assertEqual(self.ui.evaluate('return WorldFrame:GetFrameStrata(),WorldFrame:IsVisible(),GetScreenWidth(),GetScreenHeight()'),['WORLD',1,1440,900])
        self.assertFalse(self.presentation.nameplatesEnabled)

    def test_mouseover_resolves_same_guid_reach_auras_and_clears_on_leave(self):
        person=self.move_near_npc();self.service('GroupInvite',target=person)
        with self.runtime._lock:
            actor=self.runtime._combat_state['actors'][person]
            actor['engaged_target']='player'
            combat.apply_status(actor,dict(kind='ward',amount=10.,duration_s=12.,source_id='enchant.hover'),person,self.runtime._sim_time)
        self.runtime._running=True;self.addCleanup(setattr,self.runtime,'_running',False);self.publish()
        self.call('ShowFriendNameplates()')
        self.project(person);self.ui.execute("hoverEvents=0; H=CreateFrame('Frame'); H:RegisterEvent('UPDATE_MOUSEOVER_UNIT'); H:SetScript('OnEvent',function() hoverEvents=hoverEvents+1 end)")
        self.ui.pointer('move',400,218)
        self.assertEqual(self.ui.evaluate('return UnitIsUnit("mouseover","party1"),UnitIsUnit("mouseovertarget","player"),CanInspect("mouseover"),CheckInteractDistance("mouseover",1),(UnitBuff("mouseover",1)),hoverEvents'),[1,1,1,1,'Interface\\Icons\\Spell_Nature_Rejuvenation',1])
        self.publish()
        self.assertEqual(self.ui.evaluate('return (UnitBuff("mouseover",1)),hoverEvents'),['Interface\\Icons\\Spell_Nature_Rejuvenation',1])
        self.ui.pointer('leave',0,0)
        self.assertEqual(self.ui.evaluate('return UnitExists("mouseover"),(UnitBuff("mouseover",1)),hoverEvents'),[None,None,2])

if __name__=='__main__':unittest.main()
