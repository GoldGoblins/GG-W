"""Retained Qt painter for the complete UI core's ordered draw list and input."""
from __future__ import annotations
import itertools,math,re,time
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QImage,QImageReader,QPainter,QPainterPath,QTransform,QPolygonF,QPixmap,QLinearGradient,QConicalGradient,QRadialGradient,QGuiApplication,QKeySequence,QCursor
from PySide6.QtQuick import QQuickPaintedItem,QQuickItem
from PySide6.QtQml import QQmlComponent,qmlEngine
from backend.game_engine_adapter_text import plain_text,paint_text,hyperlink_spans
from backend.game_engine_adapter_assets import asset_path,texture_path
from backend.game_engine_adapter_formats import AssetCache
from backend.game_engine_adapter_ime import Composition
from backend.game_engine_adapter_navigation import atlas_texture
PROJECT=Path(__file__).resolve().parents[1]
_MINIMAP_OWNERS=itertools.count(1)

def color(value,default='white'):
    if not value:return QColor(default)
    return QColor.fromRgbF(*(max(0.,min(1.,float(x))) for x in value))

class GgEngineCanvas(QQuickPaintedItem):
    def setCursorMode(self,mode):
        # GG's local pointer shapes; original installation cursor artwork is
        # a separate corpus. Native override/reset/repair state stays exact.
        shapes={'Point':Qt.CursorShape.ArrowCursor,'Buy':Qt.CursorShape.PointingHandCursor,
            'UnableBuy':Qt.CursorShape.ForbiddenCursor,'Inspect':Qt.CursorShape.WhatsThisCursor,
            'Cast':Qt.CursorShape.CrossCursor,'CastError':Qt.CursorShape.ForbiddenCursor,'Repair':Qt.CursorShape.CrossCursor}
        if mode not in shapes:raise ValueError('Unknown native cursor mode')
        self.setCursor(QCursor(shapes[mode]))

    def __init__(self,runtime,parent,offset=0):
        super().__init__(parent);self.runtime=runtime;self.offset=offset;self.rows=[];self.base_rows=[];self.layers=[];self.model_panes={};self._pane_component=None;self.images={};self.image_bytes=0;self.missing=set();self.unsupported=set()
        self.assets=AssetCache();self.destroyed.connect(self.assets.close);self._facts_vm=None;self._model_facts=set();self._live_panes={}
        # Model panes are portraits/previews. The explicit world consumer
        # ignores them, so their walk clips cannot double world footsteps.
        self.assets.model_event_sink=getattr(getattr(runtime,'entity_audio',None),'model_events',None)
        self.setObjectName('gameGgEngineCanvas');self.setAntialiasing(True);self.setAcceptedMouseButtons(Qt.LeftButton|Qt.RightButton|Qt.MiddleButton)
        self.setAcceptHoverEvents(True);self.setFlag(QQuickItem.Flag.ItemIsFocusScope,True);self.setX(offset);self.setZ(1)
        self._link_spans=[];self._link_vm=None
        self._last_minimap_refresh=0.
        self._minimap_scope=None;self._minimap_owner=next(_MINIMAP_OWNERS)
        self._minimap_plans={};self._minimap_hover=None;self._minimap_point=None
        self._minimap_render_rows=None;self._minimap_snapshot_view=None
        self._minimap_prepared_at=0.;self._minimap_shape=();self._minimap_closed=False
        self.destroyed.connect(self._retire_minimap)
        self.composition=Composition();self.setFlag(QQuickItem.Flag.ItemAcceptsInputMethod,True)
        parent.widthChanged.connect(self.resize);parent.heightChanged.connect(self.resize);self.resize()
    def resize(self):
        self._retire_minimap();self._minimap_plans={};self._minimap_point=None
        p=self.parentItem();self.setWidth(max(1,p.width()-self.offset));self.setHeight(max(1,p.height()))
        if self.runtime.lua and not self.runtime.lua.closed:
            try:self.runtime.lua.resize(self.width(),self.height());self.runtime._update_frames()
            except (ValueError,RuntimeError,TimeoutError) as exc:self.runtime._error(exc)
    def sync(self,rows):
        redraw=rows!=self.rows or self._link_vm is not self.runtime.lua or any(r['kind']=='ModelPane' for r in rows)
        self._sync_minimaps(rows,force=redraw)
        if redraw:
            self.rows=rows;blocks=[[]];panes=[]
            focused=next((row['id'] for row in rows if row.get('editbox')),None)
            if focused!=self.composition.target:self.composition.reset()
            QGuiApplication.inputMethod().update(Qt.ImQueryAll)
            spans=[]
            for row in rows:
                if row['kind']=='Text':spans.extend(hyperlink_spans(row))
                if len(spans)>2048:raise ValueError('Hyperlink span capacity exceeded')
            if (spans!=self._link_spans or self._link_vm is not self.runtime.lua) and self.runtime.lua and not self.runtime.lua.closed:
                self.runtime.lua.request('links',spans=spans);self._link_spans=spans;self._link_vm=self.runtime.lua
            for row in rows:
                if row['kind']=='ModelPane' and len(panes)<8:panes.append(row);blocks.append([])
                else:blocks[-1].append(row)
            self.base_rows=blocks[0]
            while len(self.layers)<len(panes):self.layers.append(PaintLayer(self))
            while len(self.layers)>len(panes):self.layers.pop().deleteLater()
            wanted={r['id'] for r in panes}
            for key in list(self.model_panes):
                if key not in wanted:self.model_panes.pop(key).deleteLater();self._live_panes.pop(key,None)
            self.assets.retain_live_panes(wanted)
            for index,row in enumerate(panes):
                self.sync_model(row,index*2+1);layer=self.layers[index];layer.setZ(index*2+2);layer.setWidth(self.width());layer.setHeight(self.height());layer.rows=blocks[index+1];layer.update()
            self.update()
        # A minimap also depends on world actors and the fading pinned ping,
        # which need not change the retained Lua draw rows. Use the existing
        # UI pump and dirty only its rectangles; no independent timer/thread.
        now=time.monotonic()
        if redraw:
            self._last_minimap_refresh=now
        elif now-self._last_minimap_refresh>=.05:
            self._last_minimap_refresh=now
            for layer,draw in [(self,self.base_rows),*((layer,layer.rows) for layer in self.layers)]:
                for row in draw:
                    if row.get('kind')=='Minimap':
                        layer.update(QRectF(row['x'],row['y'],row['width'],row['height']).toAlignedRect())
    def image(self,path):
        key=str(path or '').replace('\\','/')
        from backend.game_engine_adapter_navigation import navigation_texture_assets
        assets=navigation_texture_assets(self,key) or self.assets
        if key in self.images:return self.images[key]
        try:p=assets.texture_path(key)
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            self.missing.add(key);self.unsupported.add('Texture resolution: '+str(exc)[:200]);return QImage()
        if p.suffix.lower() in ('.blp','.tga'):
            try:image=assets.image(p)
            except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
                self.unsupported.add('Texture: '+str(exc)[:200]);self.missing.add(key);image=QImage()
            self._cache_image(key,image);return image
        if p.suffix.lower() not in ('.png','.jpg','.jpeg','.bmp','.svg'):
            self.missing.add(key);return QImage()
        reader=QImageReader(str(p));size=reader.size()
        if size.width()*size.height()>4*1024*1024:self.missing.add(key);return QImage()
        image=reader.read()
        if image.isNull():self.missing.add(key)
        self._cache_image(key,image)
        return image
    def _cache_image(self,key,image):
        if len(self.images)<256 and self.image_bytes+image.sizeInBytes()<=32*1024*1024:self.images[key]=image;self.image_bytes+=image.sizeInBytes()
    def tinted_image(self,path,tint,desaturated):
        tint=tuple(tint or (1,1,1,1));key=(str(path),tint,bool(desaturated))
        if key in self.images:return self.images[key]
        image=self.image(path)
        if image.isNull() or (tint==(1,1,1,1) and not desaturated):return image
        image=image.convertToFormat(QImage.Format_RGBA8888);data=bytearray(image.constBits())
        if desaturated:
            grey=bytes(round(.2126*r+.7152*g+.0722*b) for r,g,b in zip(data[0::4],data[1::4],data[2::4]))
            for channel in range(3):data[channel::4]=grey
        for channel,gain in enumerate(tint):data[channel::4]=bytes(data[channel::4]).translate(bytes(round(i*max(0,min(1,gain))) for i in range(256)))
        result=QImage(data,image.width(),image.height(),image.bytesPerLine(),QImage.Format_RGBA8888).copy();self._cache_image(key,result);return result
    def paint(self,painter):
        self.paint_rows(painter,self.base_rows)
    def paint_rows(self,painter,rows):
        painter.setRenderHint(QPainter.Antialiasing)
        for r in rows:
            kind=r['kind'];rect=QRectF(r['x'],r['y'],r['width'],r['height'])
            if kind=='Frame' or rect.isEmpty():continue
            painter.save();painter.setOpacity(max(0.,min(1.,r['alpha'])))
            if r.get('clip'):painter.setClipRect(QRectF(*r['clip']))
            if kind=='Text':
                if not self.composition.paint(painter,r):paint_text(painter,rect,r)
            elif kind=='Texture':
                if r.get('additive'):painter.setCompositionMode(QPainter.CompositionMode_Plus)
                if r.get('circular'):
                    clip=QPainterPath();clip.addEllipse(rect);painter.setClipPath(clip,Qt.IntersectClip)
                atlas=atlas_texture(self,r,painter.device().devicePixelRatioF())
                image=atlas if atlas is not None else self.tinted_image(r['path'],r.get('color'),r.get('desaturated')) if r.get('path') else QImage()
                if not image.isNull():
                    uv=([[0,0],[1,0],[1,1],[0,1]] if atlas is not None else r.get('uv')) or [[0,0],[1,0],[1,1],[0,1]]
                    source=QPolygonF([QPointF(u*image.width(),v*image.height()) for u,v in uv]);destination=QPolygonF([rect.topLeft(),rect.topRight(),rect.bottomRight(),rect.bottomLeft()]);transform=QTransform()
                    if QTransform.quadToQuad(source,destination,transform):
                        painter.setClipRect(rect,Qt.IntersectClip);painter.setTransform(transform,True)
                        if r.get('tile'):
                            region=source.boundingRect();painter.drawTiledPixmap(region,QPixmap.fromImage(image),region.topLeft())
                        else:painter.drawImage(QRectF(0,0,image.width(),image.height()),image)
                elif not r.get('path'):painter.fillRect(rect,color(r.get('color')))
            elif kind=='ColorValue':
                gradient=QLinearGradient(rect.bottomLeft(),rect.topLeft());gradient.setColorAt(0,QColor('black'));gradient.setColorAt(1,QColor.fromHsvF(r['hue']/360,r['sat'],1))
                painter.fillRect(rect,gradient)
            elif kind=='ColorWheel':
                gradient=QConicalGradient(rect.center(),180)
                for i in range(7):gradient.setColorAt(i/6,QColor.fromHsvF((i%6)/6,1,1))
                painter.setBrush(gradient);painter.setPen(Qt.NoPen);painter.drawEllipse(rect)
                white=QRadialGradient(rect.center(),min(rect.width(),rect.height())/2);white.setColorAt(0,QColor('white'));white.setColorAt(1,QColor('#00ffffff'))
                painter.setBrush(white);painter.drawEllipse(rect)
            elif kind=='Minimap':self.paint_minimap(painter,rect,r)
            elif kind=='ModelPane':self.unsupported.add('ModelPane: '+str(r.get('model') or r.get('name') or 'unit'))
            painter.restore()
    def sync_model(self,row,z):
        existing=self.model_panes.get(row['id'])
        if existing:existing.setVisible(False)
        source=row.get('model');binding={};display_scale=1.;display_alpha=1.
        if not source and row.get('unit'):
            from backend.game_engine_adapter_world import unit_asset
            binding=unit_asset(getattr(self.runtime,'snapshot',{}),row['unit'])
            source=binding.get('source')
            if isinstance(binding.get('appearance'),dict):row={**row,'appearance':{**binding['appearance'],**row.get('appearance',{})}}
        try:
            appearance=row.get('appearance') or {}
            display=appearance.get('display_id',binding.get('display_id'))
            if display is not None:
                resolved=self.assets.creature_display(display);source=resolved['source'];display_scale=resolved['scale'];display_alpha=resolved['alpha']
                row={**row,'appearance':{**resolved['appearance'],**appearance}}
            if not source:return
            try:path=self.assets.resolve(source)
            except ValueError as exc:
                if str(source).lower().endswith('.mdx') and 'not in patch chain' in str(exc):path=self.assets.resolve(str(source)[:-4]+'.m2')
                else:raise
            if path.suffix.lower()=='.mdx' and not path.is_file():path=self.assets.resolve(str(path.with_suffix('.m2')))
            row={**row,'particle_density':getattr(self.runtime,'particle_density',1.),'model_scale':row.get('model_scale',1)*display_scale}
            from backend.game_engine_adapter_pane_anchor import anchor
            row['pane_anchor']=anchor(row,(self.width(),self.height()))
            appearance=row.get('appearance')
            live=None
            if path.suffix.lower() in ('.m2','.mdx'):
                live=self.assets.live_model(path,row)
                if self._facts_vm is not self.runtime.lua:self._facts_vm=self.runtime.lua;self._model_facts.clear()
                stat=path.stat();host_name=row.get('name') if row.get('unit') or display is not None else None;facts_key=(source,stat.st_mtime_ns,stat.st_size,host_name)
                if facts_key not in self._model_facts or (host_name and row.get('host_model_source')!=source):
                    loaded=self.runtime.lua.request('model_facts',path=source,facts=live.facts,**({'name':host_name} if host_name else {}))
                    self._model_facts.add(facts_key)
                    current=next((r for r in loaded['quads'] if r['id']==row['id']),None)
                    if current:
                        row={**current,'particle_density':getattr(self.runtime,'particle_density',1.),'model_scale':current.get('model_scale',1)*display_scale}
                        if appearance is not None:row['appearance']={**appearance,**current.get('appearance',{})}
                        live=self.assets.live_model(path,row)
                # SetUnit clears the widget's file camera. Its GG-bound file is
                # resolved here, so choose the first authored portrait camera
                # when the addon has not requested a camera itself.
                if (row.get('unit') or display is not None) and row.get('camera') is None and live.facts.get('cameras',0):
                    row={**row,'camera':0};row['pane_anchor']=anchor(row,(self.width(),self.height()));live=self.assets.live_model(path,row)
            elif path.suffix.lower()=='.wmo':path=self.assets.model(path)
            elif path.suffix.lower() not in ('.gltf','.glb') or not path.is_file():raise ValueError('GG model asset unavailable')
            obj=self.model_panes.get(row['id'])
            if obj is None:
                engine=qmlEngine(self.parentItem())
                if engine is None:raise ValueError('Model pane needs an active QML engine')
                if self._pane_component is None:
                    from PySide6.QtCore import QUrl
                    self._pane_component=QQmlComponent(engine,QUrl.fromLocalFile(str(PROJECT/'qml/components/GgEngineModelPane.qml')))
                obj=self._pane_component.create()
                if obj is None:raise ValueError('Model pane QML: '+str(self._pane_component.errors()))
                obj.setParent(self);obj.setParentItem(self);self.model_panes[row['id']]=obj
                obj.setProperty('animationHost',self.runtime.parent())
                obj.setProperty('textureSettings',self.runtime)
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QVector3D
            region=QRectF(row['x'],row['y'],row['width'],row['height'])
            if row.get('clip'):region=region.intersected(QRectF(*row['clip']))
            obj.setVisible(True);obj.setZ(z);obj.setX(region.x());obj.setY(region.y());obj.setWidth(region.width());obj.setHeight(region.height());obj.setOpacity(row.get('own_alpha',row['alpha'])*display_alpha)
            for key,value in {'modelSource':QUrl() if live else QUrl.fromLocalFile(str(path)),'facing':row.get('facing',0),'modelScale':row.get('model_scale',1),'modelPosition':QVector3D(*row.get('position',(0,0,0))),'paneWidth':row['width'],'paneHeight':row['height'],'contentX':row['x']-region.x(),'contentY':row['y']-region.y()}.items():obj.setProperty(key,value)
            if self._live_panes.get(row['id']) is not live:
                obj.setProperty('originalRows',live.batches if live else []);self._live_panes[row['id']]=live
                if live:obj.setProperty('originalMinimum',QVector3D(*live.bounds[0]));obj.setProperty('originalMaximum',QVector3D(*live.bounds[1]))
            if live:
                live.appearance(row)
                batches=live.batches
                if obj.property('originalRows')!=batches:obj.setProperty('originalRows',batches)
                position=row.get('position',(0,0,0));obj.setProperty('modelPosition',QVector3D(position[0],position[2],-position[1]))
                layout=row.get('scale',1);diag=math.sqrt(1+(self.width()/max(1,self.height()))**2)
                pos_units=768*diag*layout
                obj.setProperty('originalPixelsPerUnit',1280*row.get('model_scale',1)*layout)
                obj.setProperty('originalScreenPosition',QVector3D(*(v*pos_units for v in position)))
                obj.setProperty('originalRootScale',(5/3)/diag*row.get('model_scale',1)*layout)
                obj.setProperty('originalCamera',live.camera or {});obj.setProperty('originalLight',row.get('light') or {});obj.setProperty('originalFog',row.get('fog') or {})
                if live.camera:
                    from PySide6.QtGui import QQuaternion
                    eye=QVector3D(*live.camera['position']);target=QVector3D(*live.camera['target']);roll=live.camera['roll']
                    obj.setProperty('originalCameraRotation',QQuaternion.fromDirection(eye-target,QVector3D(0,math.cos(roll),math.sin(roll))))
            if obj.property('modelError'):self.unsupported.add(str(obj.property('modelError'))[:200])
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:self.unsupported.add('ModelPane: '+str(exc)[:200])
    def _retire_minimap(self,*_args):
        pending=self._minimap_hover;self._minimap_hover=None
        if not pending:return
        lua=pending['lua']
        if lua.closed:return
        try:lua.request('minimap_hover',action='fade',owner=pending['owner'])
        except (ValueError,RuntimeError,TimeoutError) as exc:
            if hasattr(self.runtime,'_error'):self.runtime._error(exc)

    def _current_minimap_scope(self):
        from backend.game_engine_adapter_minimap import cached_atlas,imported_stream,map_identity
        snapshot=getattr(self.runtime,'snapshot',{});stream=imported_stream(self.runtime)
        cache=getattr(stream,'cache',None)
        return (self.runtime.lua,map_identity(snapshot,cached_atlas(self.runtime)),id(cache),
            str(getattr(cache,'archive_source','')),getattr(self.runtime,'character_key',None))

    def _sync_minimaps(self,rows,force=False):
        if self._minimap_closed:return
        from backend.game_engine_adapter_minimap import (cached_atlas,imported_stream,map_identity,
            overlay_geometry,painted_overlay)
        snapshot=getattr(self.runtime,'snapshot',{});atlas=cached_atlas(self.runtime)
        if not isinstance(snapshot.get('player'),dict):
            self._retire_minimap();self._minimap_plans={}
            return
        scope=self._current_minimap_scope()
        if scope!=self._minimap_scope:
            self._retire_minimap();self._minimap_scope=scope;self._minimap_point=None
            self._minimap_owner=next(_MINIMAP_OWNERS);self._minimap_plans={};self._minimap_shape=()
            self._minimap_render_rows=None
        render=snapshot.get('render')
        entities=render.get('entities') if isinstance(render,dict) else None
        if isinstance(entities,list):
            self._minimap_render_rows=tuple(r for r in entities[:512] if isinstance(r,dict))
            if not entities:self._minimap_prepared_at=0.
        # Inspector packets omit the render stream. Reuse only its latest
        # authoritative list in this exact scope; an explicit empty list is
        # authoritative too. Names/identity must travel with the real rows.
        snapshot={**snapshot,'render':{**(render if isinstance(render,dict) else {}),
            'entities':self._minimap_render_rows or ()}}
        self._minimap_snapshot_view=snapshot
        maps=[r for r in rows if r.get('kind')=='Minimap' and r.get('owner') and r.get('alpha',1)>0][:4]
        shape=tuple((r['id'],r['owner'],r['x'],r['y'],r['width'],r['height'],r.get('zoom'),
            r.get('inside_zoom'),tuple(r.get('clip') or ())) for r in maps)
        now=time.monotonic()
        if shape==self._minimap_shape and now-self._minimap_prepared_at<.05:return
        self._minimap_shape=shape;self._minimap_prepared_at=now
        plans={}
        for row in maps:
            rect=QRectF(row['x'],row['y'],row['width'],row['height'])
            if rect.isEmpty():continue
            records=overlay_geometry(self.runtime,snapshot,rect,row,atlas)
            hits=[]
            for record in records:
                name=record.get('name');subject=record['subject']
                if not isinstance(name,str) or not name.strip() or len(name.encode('utf-8'))>512 or any(ord(c)<32 or ord(c)==127 for c in name):continue
                if len(subject.encode('utf-8'))>256 or any(ord(c)<32 or ord(c)==127 for c in subject):continue
                if painted_overlay(self,record):hits.append(record)
            plans[row['id']]={'row':dict(row),'rect':rect,'records':tuple(records),'hits':tuple(hits)}
        self._minimap_plans=plans
        if self._minimap_point is not None:self._route_minimap(*self._minimap_point)
        elif not plans:self._retire_minimap()

    def _route_minimap(self,x,y):
        from backend.game_engine_adapter_minimap import hit_overlay
        lua=self.runtime.lua
        if not lua or lua.closed:self._retire_minimap();return
        found=None
        for plan in reversed(tuple(self._minimap_plans.values())):
            record=hit_overlay(plan['hits'],plan['rect'],plan['row'],x,y)
            if record is not None:
                found={'lua':lua,'owner':self._minimap_owner,'frame':plan['row']['owner'],
                    'subject':record['subject'],'text':record['name'],'grey':record['grey'],'x':x,'y':y}
                break
        if found is None:self._retire_minimap();return
        old=self._minimap_hover
        same=old is not None and all(old[k]==found[k] for k in ('lua','owner','frame','subject','text','grey'))
        if not same:self._retire_minimap()
        accepted=lua.request('minimap_hover',action='move' if same else 'show',
            **{key:value for key,value in found.items() if key!='lua'})
        if accepted:self._minimap_hover=found
        elif same:self._retire_minimap()

    def _minimap_pointer(self,action,x,y):
        if action=='leave':self._minimap_point=None;self._retire_minimap();return
        if action not in ('move','press','release'):return
        # Input reads already prepared geometry, with no texture/catalog IO.
        # An epoch arriving before the next UI pump cannot reuse its old hits.
        if self._current_minimap_scope()!=self._minimap_scope:
            self._retire_minimap();self._minimap_point=None;self._minimap_plans={}
            self._minimap_render_rows=None;self._minimap_snapshot_view=None;return
        self._minimap_point=(x,y);self._route_minimap(x,y)

    def close(self):
        self._minimap_closed=True
        self._retire_minimap();self._minimap_plans={};self._minimap_point=None
        self._minimap_render_rows=None;self._minimap_snapshot_view=None
        self.assets.close()
    def paint_minimap(self,painter,rect,row):
        from backend.game_engine_adapter_minimap import paint
        paint(self,painter,rect,row)
    def pointer(self,event,action,button='LeftButton',**kwargs):
        if not self.runtime.lua:return False
        try:
            p=event.position();mod=event.modifiers()
            handled=self.runtime.lua.pointer(action,p.x(),p.y(),button,shift=bool(mod&Qt.ShiftModifier),ctrl=bool(mod&Qt.ControlModifier),alt=bool(mod&Qt.AltModifier),**kwargs)
            self._minimap_pointer(action,p.x(),p.y())
            self.runtime._update_frames()
            if handled or action=='leave':self.runtime.queue_ui_input()
            return handled
        except (ValueError,RuntimeError,TimeoutError) as exc:self.runtime._error(exc);return False
    def mousePressEvent(self,event):
        button={Qt.RightButton:'RightButton',Qt.MiddleButton:'MiddleButton'}.get(event.button(),'LeftButton')
        handled=self.pointer(event,'press',button);event.setAccepted(handled)
        if handled:self.forceActiveFocus()
    def mouseReleaseEvent(self,event):
        button={Qt.RightButton:'RightButton',Qt.MiddleButton:'MiddleButton'}.get(event.button(),'LeftButton')
        event.setAccepted(self.pointer(event,'release',button))
    def mouseMoveEvent(self,event):event.setAccepted(self.pointer(event,'move'))
    def hoverMoveEvent(self,event):self.pointer(event,'move')
    def hoverLeaveEvent(self,event):self.pointer(event,'leave')
    def wheelEvent(self,event):event.setAccepted(self.pointer(event,'wheel',delta=event.angleDelta().y()/120))
    def keyPressEvent(self,event):
        try:
            text=event.text();ctrl=bool(event.modifiers()&Qt.ControlModifier);shift=bool(event.modifiers()&Qt.ShiftModifier)
            key={Qt.Key_Return:'ENTER',Qt.Key_Enter:'ENTER',Qt.Key_Escape:'ESCAPE',Qt.Key_Backspace:'BACKSPACE',Qt.Key_Tab:'TAB',Qt.Key_Left:'LEFT',Qt.Key_Right:'RIGHT',Qt.Key_Up:'UP',Qt.Key_Down:'DOWN',Qt.Key_Delete:'DELETE',Qt.Key_Home:'HOME',Qt.Key_End:'END'}.get(event.key())
            if ctrl and event.key()==Qt.Key_A:key='SELECT_ALL'
            if ctrl and event.key()==Qt.Key_V:handled=self.runtime.lua.request('paste',text=QGuiApplication.clipboard().text())
            elif ctrl and event.key() in (Qt.Key_C,Qt.Key_X):
                copied=self.runtime.lua.request('cut' if event.key()==Qt.Key_X else 'copy');handled=copied is not None
                if handled:QGuiApplication.clipboard().setText(copied)
            else:
                chord=key or QKeySequence(event.key()).toString(QKeySequence.PortableText).upper()
                handled=self.runtime.lua.request('key',key=chord,ctrl=ctrl,shift=shift,alt=bool(event.modifiers()&Qt.AltModifier)) if chord else False
                if not handled and text and not ctrl:handled=self.runtime.lua.request('text',text=text)
            event.setAccepted(handled);self.runtime._update_frames()
            if handled:self.runtime.queue_ui_input()
        except (ValueError,RuntimeError,TimeoutError) as exc:self.runtime._error(exc);event.setAccepted(False)
    def keyReleaseEvent(self,event):
        if not self.runtime.lua:return
        try:
            key=QKeySequence(event.key()).toString(QKeySequence.PortableText).upper();mod=event.modifiers()
            handled=self.runtime.lua.request('key_up',key=key,ctrl=bool(mod&Qt.ControlModifier),shift=bool(mod&Qt.ShiftModifier),alt=bool(mod&Qt.AltModifier))
            event.setAccepted(handled);self.runtime._update_frames()
            if handled:self.runtime.queue_ui_input()
        except (ValueError,RuntimeError,TimeoutError) as exc:self.runtime._error(exc);event.setAccepted(False)
    def inputMethodQuery(self,query):
        row=next((r for r in self.rows if r.get('editbox')),None)
        return self.composition.query(row,query)
    def inputMethodEvent(self,event):
        try:
            row=next((r for r in self.rows if r.get('editbox')),None)
            handled=self.runtime.lua is not None and self.composition.event(row,event,self.runtime.lua)
            event.setAccepted(handled)
            if handled:
                self.runtime._update_frames();self.update()
                self.runtime.queue_ui_input()
                for layer in self.layers:layer.update()
        except (ValueError,RuntimeError,TimeoutError) as exc:self.runtime._error(exc);event.setAccepted(False)

class PaintLayer(QQuickPaintedItem):
    def __init__(self,canvas):
        super().__init__(canvas);self.canvas=canvas;self.rows=[];self.setAcceptedMouseButtons(Qt.NoButton)
    def paint(self,painter):self.canvas.paint_rows(painter,self.rows)
