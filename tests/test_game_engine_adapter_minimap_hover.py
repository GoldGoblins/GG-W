"""Actual retained Lua tooltips over the same Qt geometry that paints the map.

The named entities/atlas are explicitly authored test providers. No original
installation art, tracking aura or server entity data is claimed by them.
"""
import copy
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication,QEvent,QPointF,QRectF,Qt
from PySide6.QtGui import QGuiApplication,QHoverEvent,QImage,QPainter
from PySide6.QtQuick import QQuickItem

APP=QGuiApplication.instance() or QGuiApplication([])


class MinimapHover(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory(prefix='gg-minimap-hover-test-')
        self.addCleanup(self.scratch.cleanup)
        self.env=patch.dict(os.environ,{f'XDG_{kind}_HOME':str(Path(self.scratch.name)/kind.lower())
            for kind in ('STATE','DATA','CONFIG','CACHE')})
        self.env.start();self.addCleanup(self.env.stop)
        from backend.game_engine_adapter_ui import GgEngineUI
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        self.ui=GgEngineUI();self.addCleanup(self.ui.close)
        self.ui.resize(400,300)
        self.ui.execute("""
            Minimap=CreateFrame('Minimap','Minimap',UIParent)
            Minimap:SetPoint('TOPLEFT',UIParent,'TOPLEFT',50,-50)
            Minimap:SetWidth(160); Minimap:SetHeight(160); Minimap:EnableMouse(true)
            Minimap:SetZoom(0)
            GameTooltip=CreateFrame('GameTooltip','GameTooltip',UIParent)
            GameTooltip:SetFrameStrata('TOOLTIP'); GameTooltip:SetClampedToScreen(true)
            GameTooltip:Hide()
            cleared=0
            GameTooltip:SetScript('OnTooltipCleared',function() cleared=cleared+1 end)
        """)
        snapshot={'player':{'x':0.,'z':0.,'yaw':0.,'world_map':{'id':901,'instance_id':3},
            'client_controls':{'services':{}}},'render':{'entities':[
                {'id':'entity-a','kind':'NPC','x':0.,'z':100.,'map_id':901,'instance_id':3,
                 'individual':{'id':'giver-a','name':'Canonical Giver'}},
                {'id':'entity-b','kind':'NPC','x':80.,'z':0.,'map_id':901,'instance_id':3,
                 'individual':{'id':'giver-b','name':'Second Giver'}}]},
            'quests':{'catalog':[{'id':'quest-a','giver_id':'giver-a'}],
                'available':['quest-a'],'active':[]}}
        class Runtime:
            def __init__(self,ui,snapshot):
                self.lua=ui;self.snapshot=snapshot;self.errors=[];self.character_key='authored-test';self.canvas=None
            def _error(self,error):self.errors.append(str(error))
            def _update_frames(self):
                rows=self.lua.frames()
                if self.canvas is not None:self.canvas.sync(rows)
            def queue_ui_input(self):pass
        self.runtime=Runtime(self.ui,snapshot)
        self.parent=QQuickItem();self.parent.setWidth(400);self.parent.setHeight(300)
        self.canvas=GgEngineCanvas(self.runtime,self.parent);self.runtime.canvas=self.canvas
        self.addCleanup(self.retire)
        self.sync()
        self.point=(130.,130.-100*160/(233.3333*2))

    def retire(self):
        self.canvas.close();self.canvas.setParentItem(None);self.canvas.deleteLater()
        self.parent.deleteLater();APP.processEvents()

    def sync(self):
        self.canvas._minimap_prepared_at=0.
        self.runtime._update_frames()

    def hover(self,x=None,y=None,leave=False):
        if x is None:x,y=self.point
        event=QHoverEvent(QEvent.Type.HoverLeave if leave else QEvent.Type.HoverMove,
            QPointF(x,y),QPointF(x,y),QPointF(x,y),Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self.canvas,event)

    def tip(self):return self.ui.evaluate('return GameTooltip:IsShown(),GameTooltipTextLeft1 and GameTooltipTextLeft1:GetText()')

    def packet(self,**changes):
        value=dict(action='show',owner=900,frame='Minimap',subject='entity:giver-a',
            text='Canonical Giver',grey=False,x=self.point[0],y=self.point[1])
        value.update(changes);return value

    def test_real_qt_hover_names_the_actual_painted_quest_giver(self):
        before=copy.deepcopy(self.runtime.snapshot)
        image=QImage(400,300,QImage.Format_ARGB32_Premultiplied);image.fill(0)
        painter=QPainter(image);self.canvas.paint(painter);painter.end()
        self.assertEqual(image.pixelColor(round(self.point[0]),round(self.point[1])).name(),'#f0c75b')
        self.hover()
        self.assertEqual(self.tip(),[1,'Canonical Giver'])
        self.assertEqual(self.runtime.snapshot,before)
        point=self.ui.evaluate("local p,r,rp,x,y=GameTooltip:GetPoint();return p,r:GetName(),rp,x,y")
        self.assertEqual(point[:3],['BOTTOM','UIParent','BOTTOMLEFT'])
        self.assertAlmostEqual(point[3],self.point[0]);self.assertAlmostEqual(point[4],300-self.point[1],places=4)
        self.assertFalse(self.runtime.errors)

    def test_same_subject_move_preserves_content_and_original_leave_fades(self):
        self.hover();cleared=self.ui.evaluate('return cleared')[0]
        self.hover(self.point[0]+1,self.point[1])
        self.assertEqual(self.ui.evaluate('return cleared'),[cleared])
        self.assertEqual(self.tip(),[1,'Canonical Giver'])
        self.hover(leave=True)
        self.assertEqual(self.tip()[0],1)
        self.ui.tick(.6)
        self.assertEqual(self.tip()[0],None)
        self.assertIsNone(self.canvas._minimap_hover)

    def test_lua_owned_tooltip_survives_same_subject_move_and_disposal(self):
        self.hover()
        self.ui.execute("GameTooltip:SetOwner(UIParent,'ANCHOR_NONE');GameTooltip:ClearLines();GameTooltip:AddLine('Addon owns this');GameTooltip:Show()")
        cleared=self.ui.evaluate('return cleared')[0]
        self.hover(self.point[0]+1,self.point[1]);self.canvas.close();self.ui.tick(.6)
        self.assertEqual(self.tip(),[1,'Addon owns this'])
        self.assertEqual(self.ui.evaluate('return cleared'),[cleared])

    def test_navigation_bootstrap_preserves_an_existing_addon_owned_tooltip(self):
        from backend.game_engine_presentation import Presentation
        self.ui.execute("AddonTooltip=GameTooltip;GameTooltip:SetOwner(UIParent,'ANCHOR_NONE');GameTooltip:AddLine('Existing addon tooltip');GameTooltip:Show()")
        Presentation._prepare_world_frame(self.ui)
        self.assertEqual(self.ui.evaluate('return GameTooltip==AddonTooltip,GameTooltip:IsShown(),GameTooltipTextLeft1:GetText()'),
            [True,1,'Existing addon tooltip'])

    def test_dialog_and_native_scroll_clip_block_hover(self):
        self.ui.execute("D=CreateFrame('Frame','Dialog',UIParent);D:SetFrameStrata('DIALOG');D:SetAllPoints();D:EnableMouse(true)")
        self.sync();self.hover()
        self.assertEqual(self.tip()[0],None)
        self.ui.execute("D:Hide();S=CreateFrame('ScrollFrame','MapClip',UIParent);S:SetPoint('TOPLEFT',UIParent,'TOPLEFT',50,-50);S:SetWidth(40);S:SetHeight(160);S:SetScrollChild(Minimap)")
        self.sync();self.hover()
        self.assertEqual(self.tip()[0],None)
        self.assertFalse(self.ui.request('minimap_hover',**self.packet()))

    def test_removed_hidden_unknown_and_other_map_entities_never_leave_a_hit(self):
        self.hover();self.assertEqual(self.tip()[0],1)
        entities=self.runtime.snapshot['render']['entities']
        entities[0]['map_id']=902;entities[1]['hidden']=True
        entities.append({'id':'nameless','kind':'NPC','x':0.,'z':100.,'map_id':901,'instance_id':3})
        self.sync();self.ui.tick(.6)
        self.assertEqual(self.tip()[0],None)
        self.hover();self.assertEqual(self.tip()[0],None)

    def test_last_drawn_overlap_wins_and_outside_circle_cannot_hit(self):
        entity=copy.deepcopy(self.runtime.snapshot['render']['entities'][0])
        entity.update(id='later',individual={'id':'later','name':'Later painted giver'})
        self.runtime.snapshot['render']['entities'].append(entity);self.sync();self.hover()
        self.assertEqual(self.tip(),[1,'Later painted giver'])
        self.hover(51,51);self.ui.tick(.6)
        self.assertEqual(self.tip()[0],None)

    def test_map_and_archive_epochs_retire_before_reusing_geometry(self):
        stream=SimpleNamespace(cache=SimpleNamespace(archive_source='authored-before.mpq'))
        host=SimpleNamespace(_engine_world_stream=stream);self.runtime.parent=lambda:host
        self.sync();self.hover()
        owner=self.canvas._minimap_owner
        stream.cache.archive_source='authored-after.mpq';self.sync()
        self.assertIsNone(self.canvas._minimap_hover);self.assertIsNone(self.canvas._minimap_point)
        self.assertNotEqual(self.canvas._minimap_owner,owner)
        self.ui.tick(.6);self.assertEqual(self.tip()[0],None)
        self.hover();self.assertEqual(self.tip()[0],1)
        self.runtime.snapshot['player']['world_map']['instance_id']=4
        self.sync();self.ui.tick(.6);self.assertEqual(self.tip()[0],None)

    def test_old_canvas_owner_cannot_fade_a_new_owner(self):
        self.assertTrue(self.ui.request('minimap_hover',**self.packet(owner=900)))
        self.assertTrue(self.ui.request('minimap_hover',**self.packet(owner=901,text='New owner',subject='new')))
        self.assertFalse(self.ui.request('minimap_hover',action='fade',owner=900))
        self.assertFalse(self.ui.request('minimap_hover',**self.packet(owner=900)))
        self.ui.tick(.6);self.assertEqual(self.tip(),[1,'New owner'])
        self.assertTrue(self.ui.request('minimap_hover',action='fade',owner=901))
        self.assertFalse(self.ui.request('minimap_hover',**self.packet(owner=900)))

    def test_new_dialog_retires_an_existing_hover_without_pointer_motion(self):
        self.hover();self.assertEqual(self.tip(),[1,'Canonical Giver'])
        self.ui.execute("D=CreateFrame('Frame','Dialog',UIParent);D:SetFrameStrata('DIALOG');D:SetAllPoints();D:EnableMouse(true)")
        self.sync();self.ui.tick(.6)
        self.assertEqual(self.tip()[0],None)
        self.assertIsNone(self.canvas._minimap_hover)

    def test_ui_delta_retains_real_rows_but_explicit_empty_cannot_restore_them(self):
        self.hover();self.assertEqual(self.tip(),[1,'Canonical Giver'])
        snapshot=self.runtime.snapshot
        self.runtime.snapshot={k:v for k,v in snapshot.items() if k!='render'}
        self.sync();self.hover()
        self.assertEqual(self.tip(),[1,'Canonical Giver'])
        self.runtime.snapshot={**self.runtime.snapshot,'render':{'entities':[]}}
        self.sync();self.ui.tick(.6)
        self.assertEqual(self.tip()[0],None)
        self.runtime.snapshot={k:v for k,v in self.runtime.snapshot.items() if k!='render'}
        self.sync();self.hover()
        self.assertEqual(self.tip()[0],None)

    def test_nameless_replacement_of_the_same_pool_row_never_reuses_a_name(self):
        self.hover();self.assertEqual(self.tip(),[1,'Canonical Giver'])
        replacement={k:v for k,v in self.runtime.snapshot['render']['entities'][0].items() if k!='individual'}
        self.runtime.snapshot={**self.runtime.snapshot,'render':{'entities':[replacement]}}
        self.sync();self.ui.tick(.6);self.hover()
        self.assertEqual(self.tip()[0],None)

    def test_malformed_native_packets_cannot_mutate_the_current_subject(self):
        self.assertTrue(self.ui.request('minimap_hover',**self.packet()))
        for fields in ({'owner':0},{'text':'x'*513},{'text':'bad\nname'},{'grey':None},
                       {'x':None},{'action':'invented'},{'frame':'x'*129},{'subject':''}):
            with self.subTest(fields=fields):
                with self.assertRaises((ValueError,RuntimeError)):
                    self.ui.request('minimap_hover',**self.packet(**fields))
                self.assertEqual(self.tip(),[1,'Canonical Giver'])

    def test_vm_replacement_never_sends_old_fade_to_new_vm(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        self.hover();old=self.ui
        replacement=GgEngineUI();self.addCleanup(replacement.close)
        replacement.resize(400,300)
        replacement.execute("GameTooltip=CreateFrame('GameTooltip','GameTooltip',UIParent);GameTooltip:SetOwner(UIParent,'ANCHOR_NONE');GameTooltip:AddLine('New VM owns this');GameTooltip:Show()")
        self.runtime.lua=replacement;self.sync();replacement.tick(.6);old.tick(.6)
        self.assertEqual(old.evaluate('return GameTooltip:IsShown()'),[None])
        self.assertEqual(replacement.evaluate('return GameTooltip:IsShown(),GameTooltipTextLeft1:GetText()'),[1,'New VM owns this'])
        self.assertIsNone(self.canvas._minimap_hover)


class ActualHostMinimapFeed(unittest.TestCase):
    def test_actual_compact_render_and_presentation_ui_delta_keep_canonical_identity(self):
        with tempfile.TemporaryDirectory(prefix='gg-minimap-real-feed-') as isolated:
            root=Path(isolated)
            with patch.dict(os.environ,{f'XDG_{kind}_HOME':str(root/kind.lower())
                    for kind in ('STATE','DATA','CONFIG','CACHE')}):
                from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
                with patch.object(mmo,'DEFAULT_STASH_PATH',root/'stash.json'),patch.object(appearance,'STATE_PATH',root/'appearance.json'):
                    from backend.game_engine_host import GameEngineRuntime
                    from backend.game_engine_presentation import Presentation
                    from PySide6.QtCore import QObject
                    from backend.game_engine_adapter_minimap import hit_overlay
                    runtime=GameEngineRuntime();bridge=QObject();presentation=Presentation(bridge,device=False)
                    parent=QQuickItem();parent.setWidth(1024);parent.setHeight(768)
                    try:
                        full=runtime.pause()
                        presentation.last_update=0.;presentation.update(full)
                        self.assertTrue(presentation.full_ui)
                        self.assertEqual(presentation.lua.evaluate("return GameTooltip:GetName(),GameTooltip:IsShown()"),['GameTooltip',None])
                        presentation.attachCanvas(parent,True)
                        canvas=presentation._canvas
                        candidates=[(plan,record) for plan in canvas._minimap_plans.values() for record in plan['hits']
                            if record['kind']=='dot' and record['subject'].startswith('entity:npc-')
                            and hit_overlay(plan['hits'],plan['rect'],plan['row'],*record['point']) is record]
                        self.assertTrue(candidates,'Actual local canonical NPC must appear on its real minimap')
                        plan,record=max(candidates,key=lambda item:math.hypot(
                            item[1]['point'][0]-item[0]['rect'].center().x(),
                            item[1]['point'][1]-item[0]['rect'].center().y()))
                        source=next(row for row in full['render']['entities'] if isinstance(row.get('individual'),dict)
                            and 'entity:'+row['individual']['id']==record['subject'])
                        self.assertEqual(record['name'],source['individual']['name'])
                        def publish(snapshot):
                            presentation.last_update=0.;presentation.update(snapshot)
                            canvas._minimap_prepared_at=0.;presentation._update_frames()
                        def hover():
                            event=QHoverEvent(QEvent.Type.HoverMove,QPointF(*record['point']),
                                QPointF(*record['point']),QPointF(*record['point']),Qt.KeyboardModifier.NoModifier)
                            QCoreApplication.sendEvent(canvas,event)
                            return presentation.lua.evaluate('return GameTooltip:IsShown(),GameTooltipTextLeft1:GetText()')
                        compact=runtime.render_snapshot()
                        actual=next(row for row in compact['render']['entities'] if row['id']==source['id'])
                        self.assertEqual(actual['individual'],{key:source['individual'][key] for key in ('id','name')})
                        self.assertNotIn('inventory',actual['individual'])
                        with runtime._lock:
                            refreshed=runtime._render_entity_rows_locked(include_identity=False)[0]
                        refreshed_row=next(row for row in refreshed if row['id']==source['id'])
                        self.assertEqual(refreshed_row['individual'],actual['individual'])
                        refreshed_by_id={row['id']:row for row in refreshed}
                        for row in full['render']['entities']:
                            if isinstance(row.get('individual'),dict) and row['id'] in refreshed_by_id:
                                self.assertEqual(runtime._compact_render_entity_row(refreshed_by_id[row['id']])['individual'],
                                    runtime._compact_render_entity_row(row)['individual'])
                        publish(compact)
                        self.assertEqual(hover(),[1,source['individual']['name']])
                        ui_delta=runtime.ui_snapshot();self.assertNotIn('render',ui_delta)
                        publish(ui_delta)
                        self.assertEqual(hover(),[1,source['individual']['name']])
                        self.assertEqual(presentation.lua.evaluate("return GameTooltipTextLeft1:GetObjectType()"),['FontString'])
                        def pixels():
                            image=QImage(1024,768,QImage.Format_ARGB32_Premultiplied);image.fill(0)
                            painter=QPainter(image);canvas.paint(painter);painter.end();return image
                        before=pixels()
                        left,bottom,width,height=presentation.lua.evaluate('return GameTooltip:GetLeft(),GameTooltip:GetBottom(),GameTooltip:GetWidth(),GameTooltip:GetHeight()')
                        region=QRectF(left,768-bottom-height,width,height).toAlignedRect()
                        event=QHoverEvent(QEvent.Type.HoverLeave,QPointF(*record['point']),
                            QPointF(*record['point']),QPointF(*record['point']),Qt.KeyboardModifier.NoModifier)
                        QCoreApplication.sendEvent(canvas,event)
                        presentation.lua.tick(.6);presentation._update_frames()
                        self.assertEqual(presentation.lua.evaluate('return GameTooltip:IsShown()'),[None])
                        after=pixels()
                        changed=sum(before.pixelColor(x,y)!=after.pixelColor(x,y)
                            for y in range(max(0,region.top()),min(768,region.bottom()+1))
                            for x in range(max(0,region.left()),min(1024,region.right()+1)))
                        self.assertGreaterEqual(changed,20,'Original tooltip font text must actually paint and fade')
                        self.assertFalse(presentation.errors)
                    finally:
                        presentation.close();runtime.shutdown()
                        parent.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
