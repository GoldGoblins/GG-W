"""Original equipment placement through the actual catalog, ABI and retained Qt models."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,AssetCache,PROJECT
from backend.game_engine_adapter_ui import GgEngineUI
from tools.world import engine_format_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])

class EquipmentState(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(f.mpq(entries=f.ranged_equipment_entries()))
        self.cache=AssetCache();self.addCleanup(self.cache.close);self.cache.mount_chain(data)
        self.reader=self.cache._reader();self.body=self.root/'body.m2';self.body.write_bytes(f.attachment_m2(full_equipment=True))
        (self.root/'gold.blp').write_bytes(f.blp())
    def character(self,**fields):
        meta,_=NativeFormats._unpack(self.reader.request('character',character={'race':1,**fields}));return meta
    def test_melee_stow_types_and_shield_are_original_joint_ids(self):
        expected={0:None,1:26,2:30,3:32,4:28}
        for sheath,joint in expected.items():
            rows=self.character(mainhand=82,sheath=0,mainhand_sheath=sheath)['attachments']
            self.assertEqual([r['id'] for r in rows],[] if joint is None else [joint])
        self.assertEqual([r['id'] for r in self.character(offhand=83,offhand_is_shield=True,sheath=0)['attachments']],[28])
        self.assertEqual([r['id'] for r in self.character(mainhand=82,offhand=83,offhand_is_shield=True,sheath=1)['attachments']],[1,0])
        self.assertEqual([r['id'] for r in self.character(offhand=82,offhand_inv_type=13,sheath=0,offhand_sheath=2)['attachments']],[31])
    def test_ranged_bow_gun_thrown_wand_and_stowed_visibility(self):
        for inv,joint in ((15,2),(26,1),(25,1)):
            self.assertEqual([r['id'] for r in self.character(ranged=84,ranged_inv_type=inv,sheath=2)['attachments']],[joint])
            for state in (0,1):self.assertFalse(self.character(ranged=84,ranged_inv_type=inv,sheath=state)['attachments'])
    def test_two_arm_visual_state_places_each_weapon_independently(self):
        fields=dict(mainhand=82,mainhand_sheath=1,ranged=84,sheath=2)
        self.assertEqual([r['id'] for r in self.character(**fields,visual_sheath=[1,0])['attachments']],[1])
        self.assertEqual([r['id'] for r in self.character(**fields,visual_sheath=[0,2])['attachments']],[26,2])
        fields['ranged_inv_type']=26
        self.assertEqual([r['id'] for r in self.character(**fields,visual_sheath=[2,1])['attachments']],[26,1])
    def test_ammo_column_directory_nock_gate_and_quiver_shared_anchor(self):
        fields=dict(mainhand=82,mainhand_sheath=1,ranged=84,ranged_inv_type=15,ammo=85,quiver=86,sheath=2,nocked=True)
        rows=self.character(**fields)['attachments'];self.assertEqual([r['id'] for r in rows],[26,2,35,26])
        self.assertIn('ammo\\gg_arrow.m2',rows[2]['model'].lower());self.assertEqual(rows[-1]['key'],'quiver')
        self.assertIn('weapon\\gg_arrowweapon.m2',self.character(**{**fields,'ammo':87})['attachments'][2]['model'].lower())
        self.assertNotIn(35,[r['id'] for r in self.character(**{**fields,'nocked':False})['attachments']])
        self.assertNotIn(35,[r['id'] for r in self.character(**{**fields,'ranged_inv_type':26})['attachments']])
        self.assertFalse(any(r.get('key')=='quiver' for r in self.character(**{**fields,'sheath':1})['attachments']))
        model=self.cache.live_model(self.body,{'id':'player','clock_ms':0,'play':{'anim_id':7,'cursor_ms':0}})
        model.appearance({'appearance':{'character':{'race':1,**fields}}})
        self.assertEqual(set(model.children),{26,2,35,'quiver'})
        self.assertFalse(model.attachment_limitations)
        size=self.cache.live_bytes
        for clock in (100,200,300):
            self.cache.live_model(self.body,{'id':'player','clock_ms':clock,'play':{'anim_id':7,'cursor_ms':clock}}).appearance({'appearance':{'character':{'race':1,**fields}}})
        self.assertEqual(self.cache.live_bytes,size)
        model.appearance({});self.assertFalse(self.cache.attachment_models)
        self.cache.close();self.assertEqual(self.cache.live_bytes,0)
    def test_hidden_helm_and_cloak_apply_to_composite_and_attachment(self):
        self.assertTrue(self.character(helmet=80)['attachments'])
        self.assertFalse(self.character(helmet=80,show_helm=False)['attachments'])
        self.assertIsNotNone(self.character(cloak=74)['object'])
        self.assertIsNone(self.character(cloak=74,show_cloak=False)['object'])
        for field,value in (('sheath',3),('mainhand_sheath',5),('ranged_inv_type',29),('visual_sheath',[0]),('visual_sheath',[False,2]),('nocked',1),('show_helm',0),('ranged',999)):
            with self.subTest(field=field),self.assertRaises(ValueError):self.character(**{field:value})
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_eight_full_outfits_and_atomic_eight_part_replacement_fit_the_pools(self):
        fields=dict(race=1,helmet=80,shoulders=81,mainhand=82,mainhand_sheath=1,offhand=83,offhand_is_shield=True,
                    ranged=84,ranged_inv_type=15,ammo=85,quiver=86,sheath=2,nocked=True)
        models=[]
        catalog=self.character(**fields)['attachments']
        for index in range(8):
            body=self.root/('body_'+str(index)+'.m2');body.write_bytes(self.body.read_bytes());parts=[]
            for part,row in enumerate(catalog):
                source=self.cache.attachment_path(row['model'],self.body);path=self.root/('part_'+str(index)+'_'+str(part)+'.m2');path.write_bytes(source.read_bytes())
                parts.append({'id':row['id'],'key':row.get('key',row['id']),'model':str(path)})
            model=self.cache.live_model(body,{'id':'pane'+str(index),'clock_ms':0,'play':{'anim_id':7,'cursor_ms':0}})
            model.appearance({'appearance':{'attachments':parts}});self.assertEqual(len(model.children),8);models.append(model)
        self.assertEqual(len(self.cache.attachment_models),64)
        self.assertEqual(self.reader.request('stats')['models'],72)
        specs=[]
        for index,row in enumerate(catalog):
            path=self.root/('replacement_'+str(index)+'.m2');path.write_bytes(f.animated_m2(camera=False))
            specs.append({'id':row['id'],'key':row.get('key',row['id']),'model':str(path)})
        old=set(id(child) for child in models[0].children.values())
        peaks=[];create=self.cache.create_attachment
        def staged(*args,**kwargs):
            child=create(*args,**kwargs);peaks.append(self.reader.request('stats')['models']);return child
        with patch.object(self.cache,'create_attachment',side_effect=staged):models[0].appearance({'appearance':{'attachments':specs}})
        self.assertEqual(max(peaks),80)
        self.assertEqual(len(self.cache.attachment_models),64);self.assertEqual(len(models[0].children),8)
        self.assertFalse(old&{id(child) for child in models[0].children.values()});self.assertEqual(len(models[-1].children),8)
        self.assertEqual(self.reader.request('stats')['effect_instances'],72)
        self.cache.close();self.assertEqual(self.cache.live_bytes,0);self.assertFalse(self.cache.attachment_models)
    def test_lua_appearance_bridge_keeps_all_equipment_state(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("m=CreateFrame('PlayerModel','Armed',UIParent) m:SetAllPoints() GG_SetCharacterAppearance('Armed',{race=1,ranged=84,ammo=85,quiver=86,sheath=2,visual_sheath={0,2},ranged_inv_type=15,mainhand_sheath=1,nocked=true,show_helm=false,show_cloak=false})")
        row=next(r for r in ui.frames() if r.get('name')=='Armed')['appearance']['character']
        self.assertEqual(row['visual_sheath'],[0,2]);self.assertEqual(row['ranged'],84);self.assertTrue(row['nocked']);self.assertFalse(row['show_cloak'])
