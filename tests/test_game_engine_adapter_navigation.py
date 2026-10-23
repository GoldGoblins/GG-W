"""Map positions must represent actual body/corpse/group locations and maps."""
import copy, math, os, unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from backend.game_engine_adapter_navigation import catalog, navigation, project, install


class NavigationGeometry(unittest.TestCase):
    def snapshot(self,x=0,z=0):
        return {'player':{'x':x,'z':z,'yaw':math.pi,'client_controls':{'services':{}}}}

    def test_authored_geography_contains_all_regions_towns_and_finite_bounds(self):
        data=catalog();self.assertEqual(len(data['continents']),9)
        self.assertEqual(len(data['landmarks']),48)
        self.assertEqual(sum(len(c['zones']) for c in data['continents']),57)
        for continent in data['continents']:
            for zone in continent['zones']:
                left,right,top,bottom=zone['rect']
                self.assertLess(left,right);self.assertLess(bottom,top)
                self.assertTrue(all(math.isfinite(n) for n in zone['rect']))
        self.assertEqual(navigation(self.snapshot())['player_zone'],[1,1])

    def test_projection_north_is_up_and_outside_is_absent(self):
        rect=[-10,10,20,-20]
        self.assertEqual(project(rect,0,0),[.5,.5])
        self.assertEqual(project(rect,-10,20),[0.,0.])
        self.assertEqual(project(rect,10,-20),[1.,1.])
        self.assertIsNone(project(rect,11,0))
        for bad in (float('nan'),float('inf'),True,'0'):
            with self.assertRaises(ValueError):project(rect,bad,0)

    def test_live_corpse_party_and_raid_share_canonical_positions_without_mutation(self):
        snapshot=self.snapshot(10,20)
        services=snapshot['player']['client_controls']['services']
        services['lifecycle']={'dead':True,'position':{'x':3,'z':9}}
        services['group']={'raid':True,'roster':[{'id':'player'}, {'id':'a','online':True,'x':1,'z':2}, {'id':'b','online':False,'x':4,'z':5}]}
        before=copy.deepcopy(snapshot);feed=navigation(snapshot)
        self.assertEqual(feed['corpse']['position'],[3.,9.])
        self.assertEqual(feed['party'][0]['position'],[1.,2.]);self.assertIsNone(feed['party'][1])
        self.assertEqual(feed['raid'][0]['position'],[10.,20.]);self.assertEqual(snapshot,before)
        self.assertAlmostEqual(feed['facing'],-math.pi)

    def test_instance_descriptor_normalizes_bounds_and_retains_other_map_identity(self):
        snapshot=self.snapshot(100,200)
        snapshot['player']['world_map']={'id':0x4800,'name':'GG Ruins','kind':'INSTANCE','instance_id':12,
            'bounds':{'left':76,'right':124,'top':176,'bottom':224}}
        snapshot['player']['client_controls']['services']['lifecycle']={'dead':True,'position':{'x':100,'z':200,'map_id':0,'instance_id':0}}
        feed=navigation(snapshot)
        self.assertEqual(feed['map'],0x4800);self.assertEqual(feed['instance'],12)
        self.assertEqual(feed['direct'][0]['rect'],[76.,124.,224.,176.])
        self.assertEqual(feed['corpse']['map'],0)
        self.assertEqual(project(feed['direct'][0]['rect'],100,200),[.5,.5])

    def test_imported_world_without_atlas_is_never_projected_as_sandover(self):
        from backend.game_engine_adapter_navigation import UNRESOLVED_IMPORTED_MAP
        from backend.game_engine_adapter_minimap import map_identity
        snapshot=self.snapshot()
        snapshot['player']['engine_world']={'region_id':'ImportedFixture','zone':'Original map'}
        feed=navigation(snapshot)
        self.assertEqual(feed['map'],UNRESOLVED_IMPORTED_MAP)
        self.assertEqual(feed['player_zone'],[0,0])
        self.assertEqual(map_identity(snapshot),(UNRESOLVED_IMPORTED_MAP,0))


class NativeNavigation(unittest.TestCase):
    def setUp(self):
        from PySide6.QtGui import QGuiApplication
        from backend.game_engine_adapter_ui import GgEngineUI
        self.app=QGuiApplication.instance() or QGuiApplication([])
        self.ui=GgEngineUI();self.addCleanup(self.ui.close);install(self.ui)
        self.snapshot={'player':{'x':0.,'z':0.,'yaw':math.pi,'client_controls':{'services':{}}}}
        self.publish()

    def publish(self):
        self.ui.publish(self.snapshot['player'],False,100,100,navigation=navigation(self.snapshot))

    def test_original_catalog_selection_map_info_and_live_position(self):
        self.assertEqual(self.ui.evaluate('return table.getn({GetMapContinents()}),table.getn({GetMapZones(2)})'),[9,9])
        self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone(),GetMapInfo()')[:3],[1,1,'GGSTART_ISLAND'])
        self.assertTrue(all(abs(n-.5)<.02 for n in self.ui.evaluate('return GetPlayerMapPosition("player")')))
        self.ui.execute('SetMapZoom(0)');self.publish()
        self.assertEqual(self.ui.evaluate('return GetPlayerMapPosition("player")'),[.5,.5])
        self.ui.execute('SetMapZoom(2,0)');self.publish()
        self.assertEqual(self.ui.evaluate('return GetPlayerMapPosition("player")'),[0.,0.])
        self.ui.execute('SetMapToCurrentZone()');self.publish()
        self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone()'),[1,1])

    def test_original_landmarks_party_corpse_and_world_loc_projection(self):
        services=self.snapshot['player']['client_controls']['services']
        services['group']={'raid':False,'roster':[{'id':'player'}, {'id':'a','online':True,'x':10,'z':10}]}
        services['lifecycle']={'dead':True,'position':{'x':20,'z':20}}
        self.publish();self.ui.execute('SetMapZoom(0)');self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumMapLandmarks()'),[48])
        expected=project(catalog()['world_rect'],10,10)
        for actual,wanted in zip(self.ui.evaluate('return GetPlayerMapPosition("party1")'),expected):self.assertAlmostEqual(actual,wanted,places=6)
        self.assertEqual(self.ui.evaluate('return GetWorldLocMapPosition(999,0,0)'),[0.,0.])
        self.assertEqual(self.ui.evaluate('return GetWorldLocMapPosition(0,0,0)'),[.5,.5])
        self.assertTrue(all(n>0 for n in self.ui.evaluate('return GetCorpseMapPosition()')))

    def test_visible_map_controls_and_native_minimap_zoom(self):
        self.ui.execute('ToggleWorldMap()');self.ui.frames()
        self.assertEqual(self.ui.evaluate('return WorldMapFrame:IsShown()'),[1])
        self.assertTrue(any(row.get('owner')=='WorldMapButton' and row.get('path','').endswith('gg-first-planet-map.svg') for row in self.ui.rows))
        self.ui.click('GGMapWorld');self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent()'),[0])
        self.ui.click('GGMapHere');self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent()'),[1])
        self.ui.click('GGMapClose');self.assertEqual(self.ui.evaluate('return WorldMapFrame:IsShown()'),[None])
        self.ui.execute('Minimap:SetZoom(5)');self.assertEqual(self.ui.evaluate('return Minimap:GetZoom()'),[5])
        self.assertTrue(any(row.get('kind')=='Minimap' for row in self.ui.frames()))

    def test_actual_lua_region_uv_renders_destination_sized_vector_crop(self):
        from types import SimpleNamespace
        from backend.game_engine_adapter_navigation import atlas_texture
        self.ui.execute('ToggleWorldMap()');self.ui.click('GGMapWorld');self.ui.click('GGMapContinentNext')
        row=next(row for row in self.ui.frames() if row.get('owner')=='WorldMapButton' and row.get('path','').endswith('gg-first-planet-map.svg'))
        self.assertLess(row['uv'][2][0]-row['uv'][0][0],.02)
        canvas=SimpleNamespace();image=atlas_texture(canvas,row)
        self.assertEqual((image.width(),image.height()),(math.ceil(row['width']),math.ceil(row['height'])))
        self.assertIs(atlas_texture(canvas,row),image)
        high_dpi=atlas_texture(canvas,row,2)
        self.assertEqual((high_dpi.width(),high_dpi.height()),(math.ceil(row['width']*2),math.ceil(row['height']*2)))

    def test_original_map_click_and_real_m_key_follow_existing_selection(self):
        self.ui.request('key',key='M');self.assertEqual(self.ui.evaluate('return WorldMapFrame:IsShown()'),[1])
        self.ui.request('key_up',key='M');self.assertEqual(self.ui.evaluate('return WorldMapFrame:IsShown()'),[1])
        self.ui.execute('SetMapZoom(0)')
        r=catalog()['continents'][1]['world_rect'];x,y=(r[0]+r[2])/2,(r[1]+r[3])/2
        self.ui.execute(f'ProcessMapClick({x},{y})')
        self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone()'),[2,0])
        self.ui.execute('SetMapToCurrentZone()');self.publish()
        self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone()'),[1,1])

    def test_direct_instance_map_and_stale_overworld_points_are_separate(self):
        self.snapshot['player']['world_map']={'id':0x4800,'name':'GG Ruins','kind':'INSTANCE','instance_id':12,
            'bounds':{'left':-24,'right':24,'top':-24,'bottom':24}}
        self.snapshot['player']['client_controls']['services']['lifecycle']={'dead':True,'position':{'x':0,'z':0,'map_id':0,'instance_id':0}}
        self.publish()
        self.assertEqual(self.ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone()'),[-1,0])
        self.assertEqual(self.ui.evaluate('return GetPlayerMapPosition("player"),GetCorpseMapPosition()'),[.5,0.,0.])
        self.assertEqual(self.ui.evaluate('return GetWorldLocMapPosition(0,0,0)'),[0.,0.])
        self.assertEqual(self.ui.evaluate('return GetWorldLocMapPosition(18432,0,0)'),[.5,.5])
        self.assertEqual(self.ui.evaluate('return GetNumMapLandmarks()'),[0])

    def test_original_pixel_ping_is_pinned_to_world_and_follows_pan_zoom(self):
        import json
        from types import SimpleNamespace
        from backend.game_engine_adapter_minimap import route_ping
        runtime=SimpleNamespace(lua=self.ui,snapshot=self.snapshot)
        rows=[]
        def dispatch(method,raw):
            row=json.loads(raw);rows.append(row)
            self.ui.publish(self.snapshot['player'],False,100,100,navigation=navigation(self.snapshot,ui=self.ui,ping=runtime._minimap_ping))
            self.ui.event('MINIMAP_PING','player',*row['position'])
            return {'ok':True}
        self.ui.execute('Minimap:PingLocation(20,10)')
        requests=self.ui.request('requests')['local_client'];row=next(r for r in requests if r['op']=='MinimapPing')
        route_ping(runtime,row,dispatch)
        self.assertEqual(rows[0]['position'],[20/130,10/130])
        old=copy.deepcopy({k:v for k,v in runtime._minimap_ping.items() if k!='owner'})
        for actual,wanted in zip(self.ui.evaluate('return Minimap:GetPingPosition()'),[20/130,10/130]):self.assertAlmostEqual(actual,wanted,places=6)
        self.snapshot['player']['x']=10;self.ui.execute('Minimap:SetZoom(5)')
        self.ui.publish(self.snapshot['player'],False,100,100,navigation=navigation(self.snapshot,ui=self.ui,ping=runtime._minimap_ping))
        changed=self.ui.evaluate('return Minimap:GetPingPosition()')
        self.assertNotAlmostEqual(changed[0],20/130)
        self.assertEqual(old,{k:v for k,v in runtime._minimap_ping.items() if k!='owner'})


class MinimapDrawing(unittest.TestCase):
    def test_original_zoom_radii_are_separate_indoors_and_outdoors(self):
        from backend.game_engine_adapter_minimap import radius
        self.assertAlmostEqual(radius(0),233.3333)
        self.assertAlmostEqual(radius(5),66.6667)
        self.assertEqual(radius(0,5,True),25.)
        self.assertEqual(radius(5,0,True),150.)
        self.assertEqual(radius(float('nan')),radius(0))

    def test_ping_world_point_is_stable_and_expires_or_changes_instance(self):
        from backend.game_engine_adapter_minimap import ping_position
        snapshot={'player':{'x':0,'z':0}}
        ping={'x':20,'z':30,'map':0,'instance':0,'time':100}
        before=copy.deepcopy(ping)
        self.assertEqual(ping_position(snapshot,ping,0,now=100),[20/466.6666,30/466.6666])
        snapshot['player']['x']=10
        self.assertEqual(ping_position(snapshot,ping,5,now=105),[10/133.3334,30/133.3334])
        self.assertIsNone(ping_position(snapshot,ping,5,now=106))
        snapshot['player']['world_map']={'id':1,'instance_id':2}
        self.assertIsNone(ping_position(snapshot,ping,5,now=100))
        self.assertEqual(ping,before)

    def test_quest_signals_use_eligibility_ready_state_and_canonical_givers(self):
        from backend.game_engine_adapter_minimap import quest_signals
        snapshot={'quests':{'catalog':[{'id':'a','giver_id':'npc-1'},{'id':'b','giver_id':'npc-2'}],
            'available':['a','b'],'active':[{'id':'b','giver_id':'npc-2','progress':{'status':'ACTIVE'}}]}}
        self.assertEqual(quest_signals(snapshot),{'npc-1':'!'})
        snapshot['quests']['active'][0]['progress']['status']='READY'
        self.assertEqual(quest_signals(snapshot),{'npc-1':'!','npc-2':'?'})

    def test_actual_north_entity_draws_above_player_and_other_maps_are_absent(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QGuiApplication,QImage,QPainter
        from backend.game_engine_adapter_minimap import paint
        app=QGuiApplication.instance() or QGuiApplication([])
        snapshot={'player':{'x':0,'y':0,'z':0,'yaw':0},'render':{'entities':[
            {'id':'north','kind':'NPC','x':0,'z':100},
            {'id':'other-map','kind':'NPC','x':100,'z':0,'map_id':999}]}}
        canvas=SimpleNamespace(runtime=SimpleNamespace(snapshot=snapshot),image=lambda path:QImage())
        image=QImage(128,128,QImage.Format_ARGB32);image.fill(0)
        painter=QPainter(image)
        try:paint(canvas,painter,QRectF(0,0,128,128),{'zoom':0})
        finally:painter.end()
        self.assertEqual(image.pixelColor(64,37).name(),'#f0c75b')
        self.assertEqual(image.pixelColor(91,64).name(),'#15232b')


class AtlasDrawing(unittest.TestCase):
    def setUp(self):
        from PySide6.QtGui import QGuiApplication
        self.app=QGuiApplication.instance() or QGuiApplication([])

    @staticmethod
    def row(u0=60/1440,u1=68/1440,v0=400/1020,v1=408/1020,width=400,height=400):
        return dict(path='assets/authored/world/gg-first-planet-map.svg',uv=[[u0,v0],[u1,v0],[u1,v1],[u0,v1]],width=width,height=height)

    def test_actual_authored_svg_border_keeps_vector_edge_at_region_zoom(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage,QPainter
        from backend.game_engine_adapter_assets import asset_path
        from backend.game_engine_adapter_navigation import atlas_texture
        vector=atlas_texture(SimpleNamespace(),self.row())
        self.assertEqual(vector.pixelColor(100,200).alpha(),0)
        self.assertEqual(vector.pixelColor(151,200).name(),'#9eb7ab')
        full=QImage(str(asset_path(self.row()['path'])))
        legacy=QImage(400,400,QImage.Format_RGBA8888);legacy.fill(0)
        painter=QPainter(legacy)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(QRectF(0,0,400,400),full,QRectF(60,400,8,8))
        finally:painter.end()
        def edge(image):return max(abs(image.pixelColor(x+1,200).alpha()-image.pixelColor(x,200).alpha()) for x in range(120,175))
        self.assertGreater(edge(vector),80)
        self.assertLess(edge(legacy),15)

    def test_vector_cache_is_bounded_by_count_and_actual_pixel_bytes(self):
        from types import SimpleNamespace
        from backend.game_engine_adapter_navigation import atlas_texture
        from backend.game_engine_adapter_navigation_art import ATLAS_CACHE_BYTES
        canvas=SimpleNamespace()
        for i in range(20):atlas_texture(canvas,self.row(v0=(400+i)/1020,v1=(408+i)/1020,width=64,height=64))
        self.assertEqual(len(canvas._gg_atlas_images),16)
        first=next(iter(canvas._gg_atlas_images));image=atlas_texture(canvas,self.row(v0=(400+4)/1020,v1=(408+4)/1020,width=64,height=64))
        self.assertIs(canvas._gg_atlas_images[first],image)
        self.assertEqual(next(reversed(canvas._gg_atlas_images)),first)
        for i in range(5):atlas_texture(canvas,self.row(v0=(400+i)/1020,v1=(408+i)/1020,width=1024,height=1024))
        self.assertLessEqual(len(canvas._gg_atlas_images),16)
        self.assertLessEqual(canvas._gg_atlas_bytes,ATLAS_CACHE_BYTES)
        self.assertEqual(canvas._gg_atlas_bytes,sum(image.sizeInBytes() for image in canvas._gg_atlas_images.values()))

    def test_generic_imported_tinted_and_nonrectangular_textures_keep_original_path(self):
        from types import SimpleNamespace
        from backend.game_engine_adapter_navigation import atlas_texture
        for change in ({'path':'Interface/WorldMap/GGAtlas/GGAtlas1'},{'color':[.5,1,1,1]},
                       {'tile':True},{'desaturated':True},{'width':float('inf')},{'width':4096},
                       {'uv':[[0,0],[1,1],[1,0],[0,1]]}):
            canvas=SimpleNamespace();self.assertIsNone(atlas_texture(canvas,{**self.row(),**change}))
            self.assertFalse(hasattr(canvas,'_gg_atlas_images'))


if __name__=='__main__':unittest.main()
