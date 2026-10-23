"""Original mounted atlas rows, exact axes and trusted durable discovery."""
import copy,json,math,os,tempfile,time,unittest,struct,hashlib
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_navigation import navigation,install,imported_atlas,explore_area,presentation_imported_navigation
from tools.world.engine_navigation_fixtures import entries,hashed_minimap_entries
from tools.world.engine_format_fixtures import mpq,blp,chunk
APP=QGuiApplication.instance() or QGuiApplication([])


def indoor_minimap_entries():
    """Own genuine WMO/portal/TRS/BLP layouts, with overlapping storeys."""
    from tools.world.engine_world_fixtures import dungeon_wdt
    path='World/WMO/GG/Rooms/Room';files=entries(art=True)
    groups=[(-8.,-8.,0.,8.,8.,3.),(-8.,-8.,-12.,8.,8.,-9.),(-8.,-8.,9.,8.,8.,12.)]
    header=bytearray(64);struct.pack_into('<II',header,0,1,len(groups));struct.pack_into('<I',header,32,73)
    material=bytearray(64);struct.pack_into('<III',material,0,4,0,0)
    infos=b''.join(struct.pack('<I6fI',0,*bounds,0) for bounds in groups)
    polys=[(-2,-2,0),(2,-2,0),(2,2,0),(-2,2,0),(-2,-2,9),(2,-2,9),(2,2,9),(-2,2,9)]
    portals=struct.pack('<HH4f',0,4,0,0,1,0)+struct.pack('<HH4f',4,4,0,0,1,-9)
    refs=struct.pack('<HHhH',0,1,1,0)+struct.pack('<HHhH',1,2,-1,0)+struct.pack('<HHhH',0,0,-1,0)+struct.pack('<HHhH',1,0,1,0)
    files[path+'.wmo']=chunk('MVER',struct.pack('<I',17))+chunk('MOHD',header)+chunk('MOTX',b'white.blp\0')+chunk('MOMT',material)+chunk('MOGI',infos)+chunk('MOPV',struct.pack('<24f',*(n for p in polys for n in p)))+chunk('MOPT',portals)+chunk('MOPR',refs)
    for gi,bounds in enumerate(groups):
        x0,y0,z0,x1,y1,z1=bounds;points=[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)]
        group=bytearray(68);struct.pack_into('<I',group,8,0x40 if gi==0 else 0);struct.pack_into('<HH',group,36,(0,2,3)[gi],2 if gi==0 else 1);struct.pack_into('<I',group,56,1000+gi)
        group.extend(chunk('MOVT',struct.pack('<24f',*(n for p in points for n in p))))
        group.extend(chunk('MONR',struct.pack('<24f',*([0,0,1]*8))));group.extend(chunk('MOTV',struct.pack('<16f',*([0,0,1,0,1,1,0,1]*2))))
        group.extend(chunk('MOVI',struct.pack('<12H',0,1,2,0,2,3,4,5,6,4,6,7)));group.extend(chunk('MOPY',bytes((0x20,0))*4))
        batch=bytearray(24);struct.pack_into('<H',batch,16,12);group.extend(chunk('MOBA',batch))
        files[path+f'_{gi:03}.wmo']=chunk('MVER',struct.pack('<I',17))+chunk('MOGP',group)
    files['World/WMO/GG/Rooms/white.blp']=blp()
    files['World/Maps/GGFixture/GGFixture.wdt']=dungeon_wdt(path+'.wmo')
    table=[]
    for gi in range(3):
        pixels=bytearray()
        for y in range(32):
            for x in range(32):
                if gi==0:rgba=((180,20,20,255),(180,150,20,225),(180,20,180,224),(20,180,180,0))[(y//16)*2+x//16]
                else:rgba=(20,20,180,255) if gi==1 else (20,180,20,255)
                r,g,b,a=rgba;pixels.extend((b,g,r,a))
        blob=blp(width=32,height=32,levels=[pixels]);hashed=hashlib.md5(blob).hexdigest()+'.blp'
        files['textures/Minimap/'+hashed]=blob;table.append(f'WMO\\GG\\Rooms\\Room_{gi:03}_00_00.blp\t{hashed}')
    files['textures/Minimap/md5translate.trs']=('dir: WMO\\GG\\Rooms\r\n'+'\r\n'.join(table)+'\r\n').encode()
    return files


def blip_entries():
    """Authored real AreaPOI/MPQ/BLP layouts with unequal signed rim ranks."""
    from tools.world.engine_format_fixtures import table_dbc
    files=hashed_minimap_entries()
    def poi(ident,x,y,flags=1,importance=0,icon=0,map_id=901):
        row=[0]*29;row[:3]=[ident,importance&0xffffffff,icon];row[4:7]=[float(x),float(y),0.]
        row[7:11]=[map_id,flags,0,f'GG POI {ident}'];return row
    files['DBFilesClient/AreaPOI.dbc']=table_dbc([
        poi(1,0,-40,3,icon=9),poi(2,0,-80,3,icon=10),
        poi(3,81,0,importance=-1),poi(4,0,200),poi(5,-300,0,importance=1),poi(6,0,-400,importance=2),
        poi(7,695,0,importance=-2),poi(8,0,-40,2,icon=1),poi(9,0,-40,3,icon=1,map_id=902),
        poi(10,0,50),poi(11,0,80,1),poi(12,0,-70,3,icon=64)],29)
    cells=bytearray()
    for y in range(64):
        for x in range(64):
            r,g,b=40+(y//8*8+x//8)*2,60,100;cells.extend((b,g,r,255))
    files['Interface/Minimap/POIIcons.blp']=blp(width=64,height=64,levels=[cells])
    for name,rgb in (('Rotating-MinimapArrow',(220,220,220)),('Rotating-MinimapGroupArrow',(70,120,240)),('Rotating-MinimapCorpseArrow',(230,80,80))):
        r,g,b=rgb;pixels=bytearray()
        for y in range(32):
            for x in range(32):pixels.extend((b,g,r,255) if 14<=x<18 and 8<=y<16 else (0,0,0,0))
        files['Interface/Minimap/'+name+'.blp']=blp(width=32,height=32,levels=[pixels])
    return files


class ImportedAtlas(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=self.root/'Data';self.data.mkdir();self.write(entries())
        self.reader=NativeFormats();self.addCleanup(self.reader.close);self.reader.request('mount_chain',path=str(self.data))
        self.atlas=self.reader.request('world_navigation',map_name='GGFixture',timeout=3)
    def write(self,files):
        (self.data/'model.MPQ').write_bytes(mpq(entries=files))
    def ui(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        ui=GgEngineUI();self.addCleanup(ui.close);install(ui);return ui
    def snapshot(self,area=8):
        return {'player':{'x':400.,'z':400.,'yaw':math.pi/2,'engine_world':{'region_id':'GGFixture','area_id':area,'world_loaded':True},
            'client_controls':{'local_client':{'explored_zones':[0]*64},'services':{}}}}
    def publish(self,ui,snapshot):
        ui.publish(snapshot['player'],False,100,100,navigation=navigation(snapshot,atlas=self.atlas))
    def test_actual_table_ids_names_zone_order_and_parent_grid(self):
        self.assertEqual([r['id'] for r in self.atlas['maps']],[901,902,903]);self.assertEqual(self.atlas['selected_map']['loading_screen'],17)
        continent=self.atlas['catalog']['continents'][0]
        self.assertEqual([z['name'] for z in continent['zones']],['GG Alpha','GG Zulu'])
        self.assertEqual(set(continent['zone_grid']),{1});self.assertEqual(len(continent['zone_grid']),16384)
        self.assertEqual(self.atlas['direct'][0]['id'],4);self.assertEqual(self.atlas['direct'][0]['map'],902)
    def test_original_native_player_axes_world_projection_and_unrelated_maps(self):
        ui=self.ui();snapshot=self.snapshot();self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetMapContinents(),GetMapInfo()'),['GG Atlas','GGAlpha',0,0])
        self.assertEqual(ui.evaluate('return GetPlayerMapPosition("player")'),[.75,.25])
        ui.execute('SetMapZoom(0)');self.publish(ui,snapshot)
        expected=[.5+400/(62.625*533.3333),.5-400/(41.75*533.3333)]
        for a,b in zip(ui.evaluate('return GetPlayerMapPosition("player")'),expected):self.assertAlmostEqual(a,b,places=6)
        self.assertEqual(ui.evaluate('return GetWorldLocMapPosition(903,0,0)'),[0.,0.])
        ui.execute('SetMapZoom(1,0) ProcessMapClick(.5,.5)')
        self.assertEqual(ui.evaluate('return GetCurrentMapContinent(),GetCurrentMapZone()'),[1,1])
    def test_original_overlay_and_poi_discovery_world_state_gates(self):
        ui=self.ui();snapshot=self.snapshot();self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetNumMapOverlays(),GetNumMapLandmarks()'),[0,1])
        snapshot['player']['client_controls']['local_client']['explored_zones'][1]=2;self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetNumMapOverlays(),GetNumMapLandmarks()'),[1,2])
        self.assertEqual(ui.evaluate('return GetMapOverlayInfo(1)')[:5],['Interface\\WorldMap\\GGAlpha\\GGOverlay',512,256,8,12])
        snapshot['player']['client_controls']['world_states']={'7':1};self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetNumMapLandmarks()'),[3])
    def test_recentered_stream_origin_restores_original_world_coordinates(self):
        ui=self.ui();snapshot=self.snapshot();self.atlas['origin']=[100.,200.,1.];self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetPlayerMapPosition("player")'),[.625,.1875])
    def test_imported_missing_catalog_hides_authored_overworld_art(self):
        ui=self.ui();snapshot=self.snapshot();ui.publish(snapshot['player'],False,100,100,navigation=navigation(snapshot))
        ui.execute('ToggleWorldMap()');ui.frames()
        self.assertEqual(ui.evaluate('return table.getn({GetMapContinents()}),GetPlayerMapPosition("player")'),[0,0.,0.])
        self.assertFalse(any((r.get('path') or '').endswith('gg-first-planet-map.svg') for r in ui.rows))
    def test_direct_original_map_is_not_the_world_sheet(self):
        self.atlas=self.reader.request('world_navigation',map_name='GGDungeon');ui=self.ui();snapshot=self.snapshot(300)
        snapshot['player'].update(x=50.,z=50.);self.publish(ui,snapshot)
        self.assertEqual(ui.evaluate('return GetCurrentMapContinent(),GetMapInfo()'),[-1,'GGDungeon',0,0])
        self.assertEqual(ui.evaluate('return GetPlayerMapPosition("player")'),[.75,.25])
        self.assertEqual(ui.evaluate('return GetWorldLocMapPosition(901,0,0)'),[0.,0.])
    def test_imported_map_installs_original_twelve_art_pieces_and_overlay(self):
        ui=self.ui();snapshot=self.snapshot();snapshot['player']['client_controls']['local_client']['explored_zones'][1]=2
        self.publish(ui,snapshot);ui.execute('ToggleWorldMap()');ui.frames()
        paths=[r.get('path') or '' for r in ui.rows if r.get('owner')=='WorldMapButton']
        self.assertEqual(len([p for p in paths if 'GGAlpha\\GGAlpha' in p]),12)
        self.assertEqual(len([p for p in paths if 'GGOverlay' in p]),2)
        self.assertFalse(any(p.endswith('gg-first-planet-map.svg') for p in paths))
    def test_mount_change_invalidates_native_cached_catalog(self):
        other=self.root/'Other';other.mkdir();(other/'model.MPQ').write_bytes(mpq(entries=entries(map_name='GGOther')))
        self.reader.request('mount_chain',path=str(other));atlas=self.reader.request('world_navigation',map_name='GGOther')
        self.assertEqual(atlas['selected_map']['directory'],'GGOther')
        self.assertIsNone(self.reader.request('world_navigation',map_name='GGFixture')['selected_map'])
    def test_malformed_bounds_missing_bitmap_and_oversize_sources(self):
        for files,expected in ((entries(broken_bounds=True),'bounds'),({**entries(),'DBFilesClient/AreaPOI.dbc':b'x'*(8*1024*1024+1)},'capacity')):
            with self.subTest(expected=expected):
                self.write(files);self.reader.request('mount_chain',path=str(self.data))
                with self.assertRaisesRegex(ValueError,expected):self.reader.request('world_navigation',timeout=3)
        self.write(entries(bitmap=False));self.reader.request('mount_chain',path=str(self.data))
        atlas=self.reader.request('world_navigation',map_name='GGFixture')
        self.assertEqual(atlas['catalog']['continents'][0]['zone_grid'],[]);self.assertTrue(atlas['notes'])
    def test_bounded_python_cache_reads_once_per_stream_configuration(self):
        calls=[];reader=self.reader
        class Cache:
            archive_source=self.data
            def _reader(self):calls.append(True);return reader
        stream=SimpleNamespace(config={'map':'GGFixture'},cache=Cache())
        for _ in range(15):self.assertEqual(imported_atlas(stream)['selected_map']['id'],901)
        self.assertEqual(len(calls),1)
        stream.config={'map':'GGAbsent'};self.assertIsNone(imported_atlas(stream));self.assertIsNone(imported_atlas(stream));self.assertEqual(len(calls),2)
    def test_imported_minimap_axes_ping_and_map_partition(self):
        from backend.game_engine_adapter_minimap import map_identity,ping_position
        snapshot=self.snapshot();ping={'map':901,'instance':0,'x':410.,'z':420.,'time':10.}
        self.assertEqual(map_identity(snapshot,self.atlas),(901,0))
        value=ping_position(snapshot,ping,now=10,atlas=self.atlas)
        self.assertAlmostEqual(value[0],20/466.6666);self.assertAlmostEqual(value[1],10/466.6666)
        self.assertIsNone(ping_position(snapshot,ping,now=10))
    def test_canvas_reads_real_mounted_art_once_and_bounds_missing_texture_io(self):
        from PySide6.QtQuick import QQuickItem
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        from backend.game_engine_adapter_formats import AssetCache
        self.write(entries(art=True));cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(str(self.data))
        stream=SimpleNamespace(cache=cache);host=SimpleNamespace(_engine_world_stream=stream);ui=self.ui()
        runtime=SimpleNamespace(lua=ui,parent=lambda:host,_update_frames=lambda:None,_error=lambda error:None,snapshot=self.snapshot())
        parent=QQuickItem();parent.setWidth(800);parent.setHeight(600);canvas=GgEngineCanvas(runtime,parent);self.addCleanup(canvas.close)
        image=canvas.image('Interface/WorldMap/GGAlpha/GGAlpha1')
        self.assertFalse(image.isNull());self.assertEqual(image.pixelColor(0,0).red(),38)
        self.assertIs(canvas._navigation_textures.cache,cache)
        with patch.object(cache.reader,'request',wraps=cache.reader.request) as request:
            for _ in range(10):self.assertTrue(canvas.image('Interface/WorldMap/GGAlpha/GGMissing').isNull())
            self.assertEqual(request.call_count,5)
        for name in ('World','GGZulu'):self.assertFalse(canvas.image(f'Interface/WorldMap/{name}/{name}1').isNull())
        self.assertEqual(len(canvas._navigation_textures.folders),2)
        self.assertFalse(any(name.startswith('interface/worldmap/ggalpha/') for name in cache.archive_entries))
    def test_original_hash_table_grammar_lookup_capacity_and_safe_filenames(self):
        from backend.game_engine_adapter_navigation import parse_minimap_translate
        files=hashed_minimap_entries();table=parse_minimap_translate(files['textures/Minimap/md5translate.trs'])
        self.assertEqual(len(table),5);self.assertIn('ggfixture\\map32_32.blp',table);self.assertIn('wmo\\gg\\rooms\\room_001_00_00.blp',table)
        for bad in (b'GG\\map1_1.blp\t../escape.blp',b'..\\map1_1.blp\t'+b'a'*32+b'.blp',b'x'*(4*1024*1024+1)):
            with self.assertRaises(ValueError):parse_minimap_translate(bad)
        many='\n'.join(f'GG\\map{i}_1.blp\t'+('a'*32)+'.blp' for i in range(16385)).encode()
        with self.assertRaisesRegex(ValueError,'row capacity'):parse_minimap_translate(many)
    def test_original_hashed_tile_selection_axes_origin_and_indoor_separation(self):
        from backend.game_engine_adapter_navigation import minimap_translate,minimap_tiles
        from backend.game_engine_adapter_formats import AssetCache
        self.write(hashed_minimap_entries());cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(str(self.data))
        stream=SimpleNamespace(cache=cache,config={'map':'GGFixture','origin':[0.,0.,0.]});snapshot=self.snapshot();snapshot['player'].update(x=0.,z=0.);snapshot['player']['engine_world']['indoors']=False
        with patch.object(cache.reader,'request',wraps=cache.reader.request) as request:
            for _ in range(10):self.assertEqual(len(minimap_translate(stream)),5)
            self.assertEqual(request.call_count,1)
        tiles=minimap_tiles(stream,snapshot,233.3333);self.assertEqual([t['tile'] for t in tiles],[[31,31],[32,31],[31,32],[32,32]])
        self.assertEqual(tiles[-1]['rect'][:2],[.5,.5]);self.assertLess(tiles[0]['rect'][0],0);self.assertLess(tiles[0]['rect'][1],0)
        stream.config['origin']=[100.,200.,1.];snapshot['player'].update(x=-100.,z=200.)
        self.assertEqual(minimap_tiles(stream,snapshot,233.3333),tiles)
        snapshot['player']['engine_world']['indoors']=True;self.assertEqual(minimap_tiles(stream,snapshot,150.),[])
    def test_native_blp_hash_tiles_draw_correct_quadrants_on_actual_qt_minimap(self):
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtGui import QImage,QPainter,QColor
        from PySide6.QtCore import QRectF
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        from backend.game_engine_adapter_formats import AssetCache
        from backend.game_engine_adapter_minimap import paint
        self.write(hashed_minimap_entries());cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(str(self.data))
        stream=SimpleNamespace(cache=cache,config={'map':'GGFixture','origin':[0.,0.,0.]},_gg_navigation_atlas=self.atlas)
        host=SimpleNamespace(_engine_world_stream=stream);snapshot=self.snapshot();snapshot['player'].update(x=0.,z=0.);snapshot['player']['engine_world']['indoors']=False
        runtime=SimpleNamespace(lua=None,parent=lambda:host,snapshot=snapshot);parent=QQuickItem();parent.setWidth(240);parent.setHeight(240)
        canvas=GgEngineCanvas(runtime,parent);self.addCleanup(canvas.close)
        def capture():
            image=QImage(240,240,QImage.Format_RGBA8888);image.fill(QColor('#15232b'));painter=QPainter(image)
            try:paint(canvas,painter,QRectF(20,20,200,200),{'zoom':0})
            finally:painter.end()
            return image
        first=capture();self.assertIs(canvas._navigation_textures.cache,cache)
        self.assertEqual([first.pixelColor(x,y).getRgb()[:3] for x,y in ((75,75),(165,75),(75,165),(165,165))],[(180,20,20),(20,180,20),(20,20,180),(180,150,20)])
        with patch.object(cache.reader,'request',wraps=cache.reader.request) as request:
            for _ in range(5):self.assertEqual(capture(),first)
            self.assertEqual(request.call_count,0)
        # A full generic UI cache must not turn minimap painting into frame IO.
        for key in list(canvas.images):
            if isinstance(key,str) and key.casefold().startswith('textures/minimap/'):del canvas.images[key]
        canvas.image_bytes=32*1024*1024
        with patch.object(cache.reader,'request',wraps=cache.reader.request) as request:
            for _ in range(5):self.assertEqual(capture(),first)
            self.assertEqual(request.call_count,0)
        self.assertEqual(len(canvas._navigation_textures.minimap_images),4)
        self.assertEqual(stream._gg_minimap_mode,'ORIGINAL_OUTDOOR_HASH_TILES');self.assertEqual(len(canvas._navigation_textures.minimap),4)
        snapshot['player']['engine_world']['indoors']=True;inside=capture();self.assertEqual(inside.pixelColor(75,75).name(),'#15232b')
        self.assertEqual(stream._gg_minimap_mode,'UNSUPPORTED_ORIGINAL_INTERIOR_TILES')
    def test_missing_original_hash_catalog_is_cached_without_repeated_mpq_io(self):
        from backend.game_engine_adapter_navigation import minimap_translate
        from backend.game_engine_adapter_formats import AssetCache
        cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(str(self.data));stream=SimpleNamespace(cache=cache,config={'map':'GGFixture'})
        with patch.object(cache.reader,'request',wraps=cache.reader.request) as request:
            for _ in range(10):self.assertIsNone(minimap_translate(stream))
            self.assertEqual(request.call_count,1)
        self.assertTrue(stream._gg_minimap_translate_error)


class OriginalBlips(unittest.TestCase):
    def setUp(self):
        from PySide6.QtQuick import QQuickItem
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        from backend.game_engine_adapter_formats import AssetCache
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=self.root/'Data';self.data.mkdir();(self.data/'model.MPQ').write_bytes(mpq(entries=blip_entries()))
        self.cache=AssetCache();self.addCleanup(self.cache.close);self.cache.mount_chain(str(self.data))
        self.stream=SimpleNamespace(cache=self.cache,config={'map':'GGFixture','origin':[0.,0.,0.]})
        self.atlas=imported_atlas(self.stream)
        self.snapshot={'player':{'x':0.,'y':0.,'z':0.,'yaw':0.,'engine_world':{'region_id':'GGFixture','indoors':False},
            'client_controls':{'services':{}}}}
        self.host=SimpleNamespace(_engine_world_stream=self.stream)
        runtime=SimpleNamespace(lua=None,parent=lambda:self.host,snapshot=self.snapshot)
        self.parent=QQuickItem();self.parent.setWidth(240);self.parent.setHeight(240)
        self.canvas=GgEngineCanvas(runtime,self.parent);self.addCleanup(self.canvas.close)

    def capture(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage,QPainter,QColor
        from backend.game_engine_adapter_minimap import paint
        image=QImage(240,240,QImage.Format_RGBA8888);image.fill(QColor('#15232b'));painter=QPainter(image)
        try:paint(self.canvas,painter,QRectF(20,20,200,200),{'zoom':4})
        finally:painter.end()
        return image

    def test_original_signed_rim_rank_edge_candidate_map_and_distance_laws(self):
        from backend.game_engine_adapter_minimap import landmark_selection
        icons,arrows=landmark_selection(self.snapshot,self.atlas,100.)
        self.assertEqual([row['id'] for row in icons],[1,2])
        self.assertEqual([row['id'] for row in arrows],[3,4,5])
        self.atlas['origin']=[100.,200.,0.];self.snapshot['player'].update(x=-100.,z=200.)
        self.assertEqual(landmark_selection(self.snapshot,self.atlas,100.),(icons,arrows))
        self.snapshot['player']['world_map']={'id':902}
        self.assertEqual([row['id'] for row in landmark_selection(self.snapshot,self.atlas,100.)[0]],[9])

    def test_actual_mounted_poi_cells_three_rotated_rim_arrows_and_cached_redraw(self):
        first=self.capture()
        self.assertEqual(first.pixelColor(160,120).getRgb()[:3],(58,60,100))
        self.assertEqual(first.pixelColor(200,120).getRgb()[:3],(60,60,100))
        for point in ((120,30),(30,120),(120,210)):self.assertEqual(first.pixelColor(*point).getRgb()[:3],(220,220,220))
        self.assertNotEqual(first.pixelColor(210,120).getRgb()[:3],(220,220,220))
        self.assertIs(self.canvas._navigation_textures.cache,self.cache)
        with patch.object(self.cache.reader,'request',wraps=self.cache.reader.request) as request:
            for _ in range(5):self.assertEqual(self.capture(),first)
            self.assertEqual(request.call_count,0)
        self.assertEqual(len(self.canvas._navigation_textures.blip_images),2)

    def test_party_and_corpse_rims_use_actual_ownership_and_never_clamp_wrong_worlds(self):
        from backend.game_engine_adapter_minimap import canonical_rim_targets
        self.atlas['pois']=[]
        services=self.snapshot['player']['client_controls']['services']
        services['group']={'roster':[{'id':'player'},
            {'id':'east','online':True,'map_id':901,'x':0.,'z':500.},
            {'id':'wrong','online':True,'map_id':902,'x':0.,'z':500.},
            {'id':'offline','online':False,'map_id':901,'x':0.,'z':500.},
            {'id':'near','online':True,'map_id':901,'x':80.,'z':0.}]}
        services['lifecycle']={'dead':True,'position':{'map_id':901,'x':-2000.,'z':0.}}
        self.assertEqual(canonical_rim_targets(self.snapshot,100.,self.atlas),[
            {'kind':'group','x':0.,'z':500.},{'kind':'corpse','x':-2000.,'z':0.}])
        image=self.capture()
        self.assertEqual(image.pixelColor(210,120).getRgb()[:3],(70,120,240))
        self.assertEqual(image.pixelColor(120,210).getRgb()[:3],(230,80,80))
        services['lifecycle']['position']['instance_id']=9
        self.assertEqual(len(canonical_rim_targets(self.snapshot,100.,self.atlas)),1)

    def test_missing_original_icon_art_is_not_replaced_by_an_unrelated_sprite(self):
        files=blip_entries()
        for key in list(files):
            if key.startswith('Interface/Minimap/'):del files[key]
        other=self.root/'Missing';other.mkdir();(other/'model.MPQ').write_bytes(mpq(entries=files))
        from backend.game_engine_adapter_formats import AssetCache
        self.capture();self.cache.close();self.cache=AssetCache();self.addCleanup(self.cache.close)
        self.cache.mount_chain(str(other));self.stream.cache=self.cache;self.stream.config=dict(self.stream.config);self.atlas=imported_atlas(self.stream)
        image=self.capture()
        self.assertNotEqual(image.pixelColor(160,120).getRgb()[:3],(58,60,100))
        self.assertNotEqual(image.pixelColor(120,30).getRgb()[:3],(220,220,220))
        with patch.object(self.cache.reader,'request',wraps=self.cache.reader.request) as request:
            for _ in range(3):self.capture()
            self.assertEqual(request.call_count,0)
        self.assertTrue(any('POIIcons' in path for path in self.canvas.missing))


class TrustedDiscovery(unittest.TestCase):
    def setUp(self):
        import test_game_engine_adapter_controls as controls
        controls.Controls.setUp(self)
        from tools.world.engine_world_fixtures import make
        from backend.game_engine_adapter_streaming import WorldStream
        temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(temp.cleanup);root=Path(temp.name)
        self.manifest=make(root,wmos=False);data=root/'Data';data.mkdir();(data/'model.MPQ').write_bytes(mpq(entries=entries(map_name='Test')))
        cfg=json.loads(self.manifest.read_text());cfg['archive_directory']=str(data);self.manifest.write_text(json.dumps(cfg))
        self.stream=WorldStream();self.addCleanup(self.stream.close);self.stream.configure(str(self.manifest))
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.stream.update(-2,2.65,20)
            if self.stream.pages and self.stream.pending is None:break
            if self.stream.last_error:self.fail(self.stream.last_error)
            time.sleep(.005)
        self.assertEqual(self.stream.query(-2,2.65,20)['area_id'],700)
        self.assertIsNotNone(imported_atlas(self.stream));self.runtime._engine_world=self.stream
        self.addCleanup(setattr,self.runtime,'_engine_world',None)
        self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]=-2,2.65,20
        self.bridge._engine_world_stream=self.stream
    def publish(self):self.presentation.last_update=0;self.presentation.update(self.runtime.snapshot())
    def control(self,area,**extra):return self.runtime.client_control(json.dumps({'kind':'local','op':'ExploreArea','area_id':area,**extra}))
    def test_actual_loaded_terrain_awards_only_catalog_bit_and_repeats_safely(self):
        result=self.control(700,explore_bit=2047);self.assertNotIn('error',result)
        self.assertEqual(result['client_events'],[{'event':'WORLD_MAP_UPDATE','args':[]}])
        self.assertEqual(self.runtime._local_client['explored_zones'][1],4)
        self.assertEqual(sum(self.runtime._local_client['explored_zones']),4)
        self.assertNotIn('client_events',self.control(700))
        self.runtime.save_state();self.runtime._local_client['explored_zones']=[0]*64;self.runtime.load_state()
        self.assertEqual(self.runtime._local_client['explored_zones'][1],4)
    def test_wrong_area_unloaded_page_and_changed_map_never_award(self):
        for area in (8,True,-1,2**32):self.assertIn('error',self.control(area))
        self.runtime._x[0]=4000.;self.assertIn('error',self.control(700));self.runtime._x[0]=-2.
        self.stream.config['map']='Changed';self.assertIn('error',self.control(700))
        self.assertFalse(any(self.runtime._local_client['explored_zones']))
    def test_presentation_schedules_one_verified_area_command(self):
        before=self.runtime._local_client['explored_zones'][1]
        snapshot=self.runtime.snapshot()
        for _ in range(3):presentation_imported_navigation(self.presentation,snapshot,self.ui)
        self.assertEqual(self.runtime._local_client['explored_zones'][1],before)
        APP.processEvents();self.assertEqual(self.runtime._local_client['explored_zones'][1],4)
        self.assertFalse(self.presentation.errors)
    def test_restore_rejects_invalid_exploration_words(self):
        from backend.game_engine_adapter_local_client import defaults,restored
        for bad in ([0]*63,[0]*63+[True],[0]*63+[-1],[0]*63+[2**32]):
            self.assertEqual(restored({'explored_zones':bad}),defaults())


class ImportedInteriorMinimap(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.data=self.root/'Data';self.data.mkdir();(self.data/'model.MPQ').write_bytes(mpq(entries=indoor_minimap_entries()))
    def stream(self,rotation=(0,180,0),origin=(0,0,0),position=None):
        from backend.game_engine_adapter_streaming import WorldStream
        path='World/WMO/GG/Rooms/Room.wmo'
        cfg={'schema':'gg.engine-world.v1','map':'GGFixture','directory':'World/Maps/GGFixture','archive_directory':str(self.data),
            'origin':list(origin),'spawn':[0,.01,0],'radius':0,'wmos':[{'model':path,'rotation':list(rotation),'position':list(origin if position is None else position)}]}
        manifest=self.root/('world'+str(len(list(self.root.glob('world*.json'))))+'.json');manifest.write_text(json.dumps(cfg))
        stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest))
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            stream.update(0,.01,0)
            if stream.pages and stream.pending is None:break
            if stream.last_error:self.fail(stream.last_error)
            time.sleep(.005)
        self.assertTrue(stream.pages);self.assertFalse(stream.last_error);self.assertEqual(next(iter(stream.pages.values())).metadata['groups'][0]['wmo_id'],73)
        return stream
    def snapshot(self):
        return {'player':{'x':0.,'y':.01,'z':0.,'yaw':math.pi/2,'engine_world':{'world_loaded':True,'area_id':1000,'indoors':False},'client_controls':{'services':{}}}}
    def canvas(self,stream,snapshot):
        from PySide6.QtQuick import QQuickItem
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        host=SimpleNamespace(_engine_world_stream=stream);runtime=SimpleNamespace(lua=None,parent=lambda:host,snapshot=snapshot)
        parent=QQuickItem();parent.setWidth(240);parent.setHeight(240);canvas=GgEngineCanvas(runtime,parent);self.addCleanup(canvas.close)
        return canvas
    def capture(self,canvas):
        from PySide6.QtGui import QImage,QPainter,QColor
        from PySide6.QtCore import QRectF
        from backend.game_engine_adapter_minimap import paint
        image=QImage(240,240,QImage.Format_RGBA8888);image.fill(QColor('#15232b'));painter=QPainter(image)
        try:paint(canvas,painter,QRectF(20,20,200,200),{'zoom':0,'inside_zoom':5})
        finally:painter.end()
        return image
    def test_real_faces_seed_original_flag_gate_grid_and_height_order(self):
        from backend.game_engine_adapter_navigation import minimap_interior,minimap_indoor_tiles,minimap_group_selection
        from backend.game_engine_adapter_minimap import player_indoors
        stream=self.stream();snapshot=self.snapshot();context=minimap_interior(stream,snapshot)
        self.assertIsNotNone(context);self.assertEqual(context['seed'],0);self.assertEqual(context['stem'],'wmo\\gg\\rooms\\room')
        self.assertFalse(stream.query(0,.01,0)['indoors']) # 0x40 is nevertheless original map indoors.
        self.assertEqual(set(minimap_group_selection(context,25)),{0,1,2})
        tiles=minimap_indoor_tiles(stream,context,25);self.assertEqual([t['group'] for t in tiles],[1,2,0])
        self.assertAlmostEqual(tiles[-1]['direction'][0],0.,places=6);self.assertAlmostEqual(tiles[-1]['direction'][1],-1.,places=6)
        self.assertAlmostEqual(tiles[-1]['center'][0],128,places=5)
        self.assertAlmostEqual(tiles[-1]['size'][0],18*128/37.5*32/31,places=5)
        canvas=self.canvas(stream,snapshot);self.assertTrue(player_indoors(canvas.runtime,snapshot))
        self.assertIs(minimap_interior(stream,snapshot),context)
        body=copy.deepcopy(snapshot);body['player']['y']=20
        self.assertEqual(minimap_interior(stream,body)['seed'],2)
    def test_native_hashes_qt_rotation_linear_alpha_and_seed_last_composition(self):
        stream=self.stream();canvas=self.canvas(stream,self.snapshot());image=self.capture(canvas)
        self.assertEqual(stream._gg_minimap_mode,'ORIGINAL_INTERIOR_HASH_TILES',getattr(stream,'_gg_minimap_interior_error',''))
        self.assertFalse(stream._gg_minimap_interior_error)
        # U goes north and V east at this placement. 224 fails the exact f32
        # cutoff, 225 passes; discarded seed pixels retain the higher green room.
        self.assertEqual([image.pixelColor(x,y).getRgb()[:3] for x,y in ((104,104),(136,104),(104,136),(136,136))],
            [(180,150,20),(20,180,20),(180,20,20),(20,180,20)])
        self.assertEqual(image.pixelColor(75,75).getRgb()[:3],(0,0,0))
        self.assertEqual(stream._gg_minimap_interior_stats['tiles'],3);self.assertEqual(len(canvas._navigation_textures.minimap_images),3)
        planes=canvas._minimap_interior_composite[1]
        self.assertEqual([channel.getpixel((112,112)) for channel in planes],
            [0.456298828125,0.304931640625,0.00699615478515625]) # Rgba16Float target writes.
        with patch.object(stream.cache.reader,'request',wraps=stream.cache.reader.request) as request:
            for _ in range(5):self.assertEqual(self.capture(canvas),image)
            self.assertEqual(request.call_count,0)
        rotated=self.stream(rotation=(0,270,0));rot_canvas=self.canvas(rotated,self.snapshot());rot_image=self.capture(rot_canvas)
        self.assertEqual(rotated._gg_minimap_mode,'ORIGINAL_INTERIOR_HASH_TILES',getattr(rotated,'_gg_minimap_interior_error',''))
        self.assertEqual([rot_image.pixelColor(x,y).getRgb()[:3] for x,y in ((104,104),(136,104),(104,136),(136,136))],
            [(20,180,20),(20,180,20),(180,150,20),(180,20,20)])
        recentered=self.stream(origin=(100,200,300));re_image=self.capture(self.canvas(recentered,self.snapshot()))
        self.assertEqual([re_image.pixelColor(x,y).getRgb()[:3] for x,y in ((104,104),(136,104),(104,136),(136,136))],
            [(180,150,20),(20,180,20),(180,20,20),(20,180,20)])
    def test_flood_xy_blocks_recursion_vertical_door_exterior_and_no_emit(self):
        from backend.game_engine_adapter_navigation import minimap_group_selection
        def group(i,x=0,y=0,flags=0,start=0,count=0):
            corners=[[x+(-5 if not mask&1 else 5),y+(0 if not mask&4 else 3),-(-5 if not mask&2 else 5)] for mask in range(8)]
            return dict(id=i,corners=corners,flags=flags,portal_start=start,portal_count=count)
        def poly(x=0,y=0):return [[x,y-.5,-.5],[x,y+.5,-.5],[x,y+.5,.5],[x,y-.5,.5]]
        groups=[group(0,start=0,count=4),group(1,y=-10,start=4,count=1),group(2,x=1000,start=5,count=1),group(3),group(4,y=-300),group(5,flags=0x80,start=6,count=1),group(6,flags=8),group(7)]
        groups[5]['corners']=[[0.,0.,0.] for _ in range(8)] # Empty no-emit connector still floods.
        refs=[dict(portal=0,group=1),dict(portal=1,group=2),dict(portal=2,group=4),dict(portal=1,group=5),dict(portal=0,group=0),dict(portal=1,group=3),dict(portal=1,group=7)]
        page=SimpleNamespace(metadata={'groups':groups,'portals':{'infos':[{'points':poly()},{'points':poly(4)},{'points':poly(y=-300)}],'refs':refs}})
        context={'page':page,'seed':0,'body':(0,0,0)}
        self.assertEqual(set(minimap_group_selection(context,25)),{0,1,7})
        groups[5]['flags']=8;self.assertEqual(set(minimap_group_selection(context,25)),{0,1})
    def test_terrain_race_and_missing_original_path_do_not_invent_room_tiles(self):
        from backend.game_engine_adapter_navigation import minimap_interior
        stream=self.stream();snapshot=self.snapshot();page=next(iter(stream.pages.values()))
        surface=SimpleNamespace(down_ray=lambda *args,**kwargs:(.05,None));terrain=SimpleNamespace(metadata={'groups':[]},surface=surface,closed=False)
        stream.pages['terrain-proof']=terrain;stream.revision+=1
        self.assertIsNone(minimap_interior(stream,snapshot))
        del stream.pages['terrain-proof'];stream.revision+=1;self.assertIsNotNone(minimap_interior(stream,snapshot))
        original=page.path;page.path=self.root/'room.wmo';stream.revision+=1
        self.assertIsNone(minimap_interior(stream,snapshot));page.path=original
        snapshot['player']['x']=1000;self.assertIsNone(minimap_interior(stream,snapshot))
    def test_original_raw_mogi_grid_survives_transformed_corner_threshold_roundoff(self):
        from backend.game_engine_adapter_navigation import minimap_interior,minimap_indoor_tiles
        stream=self.stream();context=minimap_interior(stream,self.snapshot());group=context['page'].metadata['groups'][0]
        # A translated/rotated Float32 edge can land just above 16 yd, selecting
        # 64 texels from transformed corners instead of the authored 32 texels.
        for i in range(8):
            if i&1:group['corners'][i][0]+=.0002
        original=Path.read_bytes;calls=[]
        def read(path):calls.append(path);return original(path)
        from backend.game_engine_adapter_navigation import minimap_translate
        minimap_translate(stream)
        with patch.object(Path,'read_bytes',autospec=True,side_effect=read):
            for _ in range(5):
                tiles=minimap_indoor_tiles(stream,context,25)
                seed=next(t for t in tiles if t['group']==0)
                self.assertEqual(seed['tile'],[0,0]);self.assertAlmostEqual(seed['size'][0],18*128/37.5*32/31,places=5)
        self.assertEqual(calls,[context['page'].path])
    def test_raw_mogi_missing_and_capacity_failures_are_memoized(self):
        from backend.game_engine_adapter_navigation import minimap_model_bounds
        path=self.root/'invalid.wmo';path.write_bytes(chunk('MVER',struct.pack('<I',17)))
        page=SimpleNamespace(path=path,metadata={'groups':[{}]});original=Path.read_bytes;calls=[]
        def read(path):calls.append(path);return original(path)
        with patch.object(Path,'read_bytes',autospec=True,side_effect=read):
            for _ in range(5):
                with self.assertRaisesRegex(ValueError,'bounds unavailable'):minimap_model_bounds(page)
        self.assertEqual(calls,[path])
        path.write_bytes(chunk('MOGI',bytes(31)))
        with self.assertRaisesRegex(ValueError,'Incomplete'):minimap_model_bounds(SimpleNamespace(path=path,metadata={'groups':[{}]}))
    def test_original_atan2_accepts_a_pitched_wmo_with_vertical_model_x(self):
        from backend.game_engine_adapter_navigation import minimap_interior,minimap_indoor_tiles
        stream=self.stream(rotation=(90,180,0),position=(1000,0,0));snapshot=self.snapshot();snapshot['player']['x']=1001.5
        context=minimap_interior(stream,snapshot);self.assertIsNotNone(context)
        self.assertEqual(context['seed'],0)
        tiles=minimap_indoor_tiles(stream,context,25);self.assertEqual(len(tiles),3)
        self.assertEqual(tiles[-1]['direction'],[1.,-0.])
        self.assertAlmostEqual(sum(n*n for n in tiles[-1]['direction']),1.,places=6)
        image=self.capture(self.canvas(stream,snapshot));self.assertFalse(image.isNull())
        self.assertEqual(stream._gg_minimap_mode,'ORIGINAL_INTERIOR_HASH_TILES',getattr(stream,'_gg_minimap_interior_error',''))


if __name__=='__main__':unittest.main()
