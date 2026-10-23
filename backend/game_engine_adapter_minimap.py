"""Bounded north-up GG minimap drawing with original six zoom radii."""
import math,time,struct
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QColor,QPainterPath,QPolygonF,QImage
from backend.game_engine_adapter_navigation import catalog,project,UNRESOLVED_IMPORTED_MAP

OUTDOOR_RADII=(233.3333,200.,166.6667,133.3333,100.,66.6667)
INDOOR_RADII=(150.,120.,90.,60.,40.,25.)
INTERIOR_ALPHA_REF=struct.unpack('<f',struct.pack('<I',0x3F60E0E2))[0]
BLIP_BASIS=140.8
BLIP_EDGE=.8
LANDMARK_RANK_YARDS=694.444
RIM_ART={'landmark':'Interface/Minimap/Rotating-MinimapArrow',
    'group':'Interface/Minimap/Rotating-MinimapGroupArrow','corpse':'Interface/Minimap/Rotating-MinimapCorpseArrow'}


def radius(zoom=0,inside_zoom=0,indoors=False):
    value=inside_zoom if indoors else zoom
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):value=0
    return (INDOOR_RADII if indoors else OUTDOOR_RADII)[max(0,min(5,int(value)))]


def map_identity(snapshot,atlas=None):
    descriptor=snapshot.get('player',{}).get('world_map') or snapshot.get('world_map') or {}
    if not descriptor and isinstance(snapshot.get('player',{}).get('engine_world'),dict):
        if isinstance(atlas,dict) and atlas.get('selected_map'):return atlas['selected_map']['id'],int(snapshot['player']['engine_world'].get('instance_id',0))
        return UNRESOLVED_IMPORTED_MAP,0
    return descriptor.get('id',0),descriptor.get('instance_id',0)


def ping_position(snapshot,ping,zoom=0,inside_zoom=0,indoors=False,*,now=None,atlas=None):
    """One fixed world point, normalized against the current player/zoom."""
    if not isinstance(ping,dict) or (ping.get('map'),ping.get('instance'))!=map_identity(snapshot,atlas):return None
    age=(time.monotonic() if now is None else now)-ping.get('time',-1e12)
    if not 0<=age<=5.5:return None
    player=snapshot.get('player',{});diameter=radius(zoom,inside_zoom,indoors)*2
    dx=(ping['x']-float(player.get('x',0)))/diameter;dz=(ping['z']-float(player.get('z',0)))/diameter
    return [dz,dx] if player.get('engine_world') else [dx,dz]


def cached_atlas(runtime):
    parent=getattr(runtime,'parent',None);host=parent() if callable(parent) else None
    stream=getattr(host,'_engine_world_stream',None)
    return getattr(stream,'_gg_navigation_atlas',None)


def imported_stream(runtime):
    parent=getattr(runtime,'parent',None);host=parent() if callable(parent) else None
    return getattr(host,'_engine_world_stream',None)


def player_indoors(runtime,snapshot):
    from backend.game_engine_adapter_world import environment
    stream=imported_stream(runtime)
    if snapshot.get('player',{}).get('engine_world') and stream is not None and hasattr(stream,'pages'):
        from backend.game_engine_adapter_navigation import minimap_interior
        return minimap_interior(stream,snapshot) is not None
    return environment(snapshot).get('indoors',False)


def _linear_channel(channel):
    from PIL import ImageMath
    return ImageMath.lambda_eval(lambda d:(d['a']<=.04045)*(d['a']/12.92)+(d['a']>.04045)*((d['a']+.055)/1.055)**2.4,a=channel)


def _gamma_channel(channel):
    from PIL import ImageMath
    return ImageMath.lambda_eval(lambda d:d['convert'](((d['a']<=.0031308)*(d['a']*12.92)+(d['a']>.0031308)*(1.055*d['a']**(1/2.4)-.055))*255+.5,'L'),a=channel)


def _half_channel(channel):
    """IEEE binary16 target writes, retained in Pillow's Float32 storage."""
    from array import array
    from PIL import Image
    values=array('f');values.frombytes(channel.tobytes());count=len(values)
    half=struct.pack('='+str(count)+'e',*values)
    restored=array('f',struct.unpack('='+str(count)+'e',half))
    return Image.frombytes('F',channel.size,restored.tobytes())


def indoor_composite(canvas,stream,context,extent):
    """Opaque 256² linear composite, with bilinear alpha tested before replacement.

    Float planes keep alpha precision through the exact original GEQUAL cutoff;
    byte-alpha blending would discard room ordering and the one-texel gap rule.
    Each replacement is quantized through IEEE binary16, as on the original
    Rgba16Float target. No blend means final quantization commutes with writes.
    """
    from PIL import Image,ImageMath
    from backend.game_engine_adapter_navigation import minimap_indoor_tiles
    key=(id(stream),str(stream.cache.archive_source),getattr(stream,'revision',0),id(context['page']),context['body'],context['seed'],extent)
    cached=getattr(canvas,'_minimap_interior_composite',None)
    if cached and cached[0]==key:return cached[1]
    target=[Image.new('F',(256,256),0.) for _ in range(3)]
    tiles=minimap_indoor_tiles(stream,context,extent)
    for tile in tiles:
        image=canvas.image(tile['path'])
        if image.isNull():continue
        raw=image.convertToFormat(QImage.Format_RGBA8888)
        source=Image.frombytes('RGBA',(raw.width(),raw.height()),bytes(raw.constBits()),'raw','RGBA',raw.bytesPerLine())
        width,height=source.size;cx,cy=tile['center'];sx,sy=tile['size'];ux,uy=tile['direction'];vx,vy=-uy,ux
        # PIL affine maps output pixel centres to input pixel centres. UVs of
        # Bevy's Rectangle are top-left (0,0): U +modelX, V -modelY.
        coeffs=(width*ux/sx,width*uy/sx,width*(.5-(cx*ux+cy*uy)/sx),
            height*vx/sy,height*vy/sy,height*(.5-(cx*vx+cy*vy)/sy))
        filtered=[c.convert('F').point(lambda n:n/255).transform((256,256),Image.Transform.AFFINE,coeffs,Image.Resampling.BILINEAR,fillcolor=0.) for c in source.split()]
        mask=ImageMath.lambda_eval(lambda d:d['convert']((d['a']>=INTERIOR_ALPHA_REF)*255,'L'),a=filtered[3])
        for channel in range(3):target[channel].paste(_linear_channel(filtered[channel]),(0,0),mask)
    # One current placement/pose, not an accumulating room or image cache.
    target=[_half_channel(channel) for channel in target]
    canvas._minimap_interior_composite=(key,target);canvas._minimap_interior_blit=None
    stream._gg_minimap_interior_stats={'seed':context['seed'],'groups':sorted({t['group'] for t in tiles}),'tiles':len(tiles),'target':256,'alpha_ref':INTERIOR_ALPHA_REF}
    return target


def paint_indoor_tiles(canvas,painter,rect,stream,context,extent):
    from PIL import Image
    target=indoor_composite(canvas,stream,context,extent)
    # Original middle 2/3 blit, filtered in linear space before its sRGB encode.
    width=max(1,min(2048,math.ceil(rect.width())));height=max(1,min(2048,math.ceil(rect.height())))
    key=(id(target),width,height);cached=getattr(canvas,'_minimap_interior_blit',None)
    if not cached or cached[0]!=key:
        channels=[_gamma_channel(c.transform((width,height),Image.Transform.AFFINE,
            (256*2/3/width,0,256/6,0,256*2/3/height,256/6),Image.Resampling.BILINEAR)) for c in target]
        pixels=Image.merge('RGB',channels).tobytes();image=QImage(pixels,width,height,width*3,QImage.Format_RGB888).copy()
        canvas._minimap_interior_blit=(key,image)
    else:image=cached[1]
    painter.drawImage(rect,image)


def paint_imported_tiles(canvas,painter,rect,snapshot,extent):
    """Original mounted hashed tiles, including the WMO room composite."""
    stream=imported_stream(canvas.runtime)
    if stream is None:return False
    from backend.game_engine_adapter_navigation import minimap_translate,minimap_tiles,minimap_interior
    context=minimap_interior(stream,snapshot)
    if context is not None:
        painter.fillRect(rect,QColor('black'));stream._gg_minimap_mode='ORIGINAL_INTERIOR_HASH_TILES'
        if minimap_translate(stream) is None:
            stream._gg_minimap_mode='UNAVAILABLE_ORIGINAL_INTERIOR_TILES';stream._gg_minimap_interior_error=getattr(stream,'_gg_minimap_translate_error','Original interior hash catalog unavailable')
            return True
        try:paint_indoor_tiles(canvas,painter,rect,stream,context,extent);stream._gg_minimap_interior_error=''
        except (ImportError,OSError,ValueError,RuntimeError,TimeoutError) as exc:
            stream._gg_minimap_mode='UNAVAILABLE_ORIGINAL_INTERIOR_TILES';stream._gg_minimap_interior_error=str(exc)[:240]
        return True
    table=minimap_translate(stream)
    if table is None:return False
    from backend.game_engine_adapter_world import environment
    if player_indoors(canvas.runtime,snapshot):
        stream._gg_minimap_mode='UNSUPPORTED_ORIGINAL_INTERIOR_TILES';return True
    stream._gg_minimap_mode='ORIGINAL_OUTDOOR_HASH_TILES'
    lighting=getattr(getattr(stream,'light',None),'state',{})
    tint=None
    if lighting.get('source')!='GG_MANIFEST_DEFAULTS' and all(isinstance(lighting.get(k),list) and len(lighting[k])==3 for k in ('ambient','diffuse')):
        ambient,diffuse=lighting['ambient'],lighting['diffuse']
        blend=min(255*(77*ambient[0]+151*ambient[1]+28*ambient[2])/256+96,255)/256
        tint=[max(0.,min(1.,diffuse[c]*.25+(ambient[c]+(1-ambient[c])*blend)*.75)) for c in range(3)]
    for tile in minimap_tiles(stream,snapshot,extent):
        image=canvas.image(tile['path'])
        if image.isNull() or image.width()!=256 or image.height()!=256:continue
        left,top,width,height=tile['rect'];target=QRectF(rect.x()+left*rect.width(),rect.y()+top*rect.height(),width*rect.width(),height*rect.height())
        painter.drawImage(target,image)
        if tint and tint!=[1.,1.,1.]:
            from PySide6.QtGui import QPainter
            painter.save();painter.setCompositionMode(QPainter.CompositionMode_Multiply);painter.fillRect(target,QColor.fromRgbF(*tint,1.));painter.restore()
    return True


def route_ping(runtime,row,dispatch):
    """Convert original pixel/UI-unit offsets before the host announces a ping."""
    import json
    point=row.get('position')
    if not isinstance(point,list) or len(point)!=2 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in point):
        runtime.lua.event('UI_ERROR_MESSAGE','Ogiltig kartposition.');return
    width,height,zoom=runtime.lua.evaluate('return Minimap and Minimap:GetWidth() or 130,Minimap and Minimap:GetHeight() or 130,Minimap and Minimap:GetZoom() or 0')
    if width<=0 or height<=0:return
    nx,ny=point[0]/width,point[1]/height
    if math.hypot(nx,ny)>=.5:return
    snapshot=runtime.snapshot;player=snapshot.get('player',{})
    from backend.game_engine_adapter_world import environment
    diameter=radius(zoom,zoom,player_indoors(runtime,snapshot))*2
    atlas=cached_atlas(runtime);map_id,instance=map_identity(snapshot,atlas);previous=getattr(runtime,'_minimap_ping',None)
    east,north=(ny,nx) if player.get('engine_world') else (nx,ny)
    runtime._minimap_ping={'map':map_id,'instance':instance,'x':float(player.get('x',0))+east*diameter,
        'z':float(player.get('z',0))+north*diameter,'time':time.monotonic(),'owner':runtime.lua}
    result=dispatch('gameEngineClientControl',json.dumps(dict(row,position=[nx,ny],kind='local')))
    if not isinstance(result,dict) or result.get('error'):runtime._minimap_ping=previous
    return result


def quest_signals(snapshot):
    """Only canonical available/active quest providers receive a quest marker."""
    quests=snapshot.get('quests',{});active=quests.get('active',[])[:8]
    active_ids={q.get('id') for q in active};available=set(quests.get('available',[])[:32]);result={}
    for quest in quests.get('catalog',[])[:32]:
        if quest.get('id') in available and quest.get('id') not in active_ids and quest.get('giver_id'):
            result[quest['giver_id']]='!'
    for quest in active:
        if quest.get('giver_id') and quest.get('progress',{}).get('status')=='READY':result[quest['giver_id']]='?'
    return result


def landmark_selection(snapshot,atlas,extent):
    """Original AreaPOI minimap candidacy, signed rank and three rim slots."""
    if not isinstance(atlas,dict) or not 0<extent<=233.334:return [],[]
    player=snapshot.get('player',{});map_id,_=map_identity(snapshot,atlas)
    origin=atlas.get('origin',[0.,0.,0.]);x=float(player.get('x',0))+origin[0];y=origin[1]-float(player.get('z',0))
    icons=[];arrows=[]
    for poi in atlas.get('pois',[])[:2048]:
        if poi.get('map')!=map_id or not poi.get('flags',0)&1:continue
        point=poi.get('position')
        if not isinstance(point,list) or len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):continue
        distance=math.hypot(point[0]-x,point[1]-y)
        if distance/extent<=BLIP_EDGE:
            if poi.get('flags',0)&2 and 0<=poi.get('icon',64)<64:icons.append(poi)
        elif distance<=LANDMARK_RANK_YARDS:arrows.append((distance,poi))
    def rank(row):
        importance=int(row[1].get('importance',0))&0xffffffff
        return (importance-2**32 if importance>=2**31 else importance,row[0])
    arrows.sort(key=rank)
    return icons,[poi for _,poi in arrows[:3]]


def canonical_rim_targets(snapshot,extent,atlas=None,*,with_names=False):
    """Existing online party and corpse points, with actual map ownership."""
    if not 0<extent<=233.334:return []
    player=snapshot.get('player',{});services=player.get('client_controls',{}).get('services',{})
    map_id,instance=map_identity(snapshot,atlas);x=float(player.get('x',0));z=float(player.get('z',0));targets=[]
    roster=services.get('group',{}).get('roster',[])
    members=[member for member in roster[:40] if member.get('id')!='player'][:4]
    life=services.get('lifecycle',{});corpse=life.get('position',{})
    sources=[('group',member) for member in members if member.get('online')]
    if life.get('dead'):sources.append(('corpse',corpse))
    for kind,point in sources:
        if (point.get('map_id',0),point.get('instance_id',0))!=(map_id,instance):continue
        px,pz=point.get('x'),point.get('z')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (px,pz)):continue
        if math.hypot(px-x,pz-z)/extent>BLIP_EDGE:
            target=dict(kind=kind,x=px,z=pz)
            if with_names:target.update(id=point.get('id'),name=point.get('name'))
            targets.append(target)
    return targets


def overlay_geometry(runtime,snapshot,rect,row,atlas=None):
    """One bounded plan for both actual drawing and minimap hit rectangles.

    Positions and names come only from the existing map/entity providers. No
    tracking aura or original entity classification is inferred here.
    """
    player=snapshot.get('player',{});imported=bool(player.get('engine_world'))
    extent=radius(row.get('zoom',0),row.get('inside_zoom',0),player_indoors(runtime,snapshot))
    x,z=float(player.get('x',0)),float(player.get('z',0));center=rect.center()
    def pos(px,pz):
        dx,dz=float(px)-x,float(pz)-z
        return QPointF(center.x()+(dz if imported else dx)*rect.width()/(extent*2),
            center.y()-(dx if imported else dz)*rect.height()/(extent*2))
    records=[]
    def add(kind,point,size,subject,name=None,**fields):
        records.append(dict(kind=kind,point=(point.x(),point.y()),
            rect=(point.x()-size/2,point.y()-size/2,size,size),subject=subject,
            name=name,grey=False,**fields))
    icons,arrows=landmark_selection(snapshot,atlas,extent) if snapshot.get('player',{}).get('engine_world') else ([],[])
    origin=atlas.get('origin',[0.,0.,0.]) if atlas else [0.,0.,0.]
    for poi in icons:
        add('poi',pos(poi['position'][0]-origin[0],origin[1]-poi['position'][1]),
            min(rect.width(),rect.height())*16/BLIP_BASIS,'poi:'+str(poi['id']),poi.get('name'),
            path='Interface/Minimap/POIIcons',icon=poi['icon'])
    targets=[dict(kind='landmark',x=poi['position'][0]-origin[0],z=origin[1]-poi['position'][1],
        id=poi['id'],name=poi.get('name')) for poi in arrows]
    targets+=canonical_rim_targets(snapshot,extent,atlas,with_names=True)
    side=min(rect.width(),rect.height());size=side*38.4/BLIP_BASIS
    for target in targets:
        delta=pos(target['x'],target['z'])-center;length=math.hypot(delta.x(),delta.y())
        if not length:continue
        direction=delta/length;point=center+direction*(side*.5*BLIP_EDGE)
        add('rim',point,size,'rim:'+target['kind']+':'+str(target.get('id')),target.get('name'),
            path=RIM_ART[target['kind']] if imported_stream(runtime) is not None else None,
            rotation=math.degrees(math.atan2(direction.x(),-direction.y())),
            fallback=not imported,color='#83b4ff' if target['kind']=='group' else '#f4eeee')
    services=player.get('client_controls',{}).get('services',{})
    group={r['id'] for r in services.get('group',{}).get('roster',[])[:40] if r.get('id')}
    signals=quest_signals(snapshot);map_id,instance_id=map_identity(snapshot,atlas)
    for entity in snapshot.get('render',{}).get('entities',[])[:512]:
        if entity.get('kind')=='PLAYER' or entity.get('hidden') or entity.get('id')=='corpse-player':continue
        if entity.get('map_id',0)!=map_id or entity.get('instance_id',0)!=instance_id:continue
        px,pz=entity.get('x'),entity.get('z')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (px,pz)):continue
        individual=entity.get('individual',{});individual=individual if isinstance(individual,dict) else {}
        identity=individual.get('id',entity.get('id'))
        if math.hypot(px-x,pz-z)>extent*(BLIP_EDGE if identity in group else 1):continue
        add('dot',pos(px,pz),5,'entity:'+str(identity),entity.get('name') or individual.get('name'),
            color='#83b4ff' if identity in group else '#f0c75b' if entity.get('kind') in ('NPC','ACTOR') else '#69b983',
            signal=signals.get(identity))
    if map_id==0:
        for index,landmark in enumerate(catalog()['landmarks'][:256]):
            px,pz=landmark['position']
            if math.hypot(px-x,pz-z)<=extent:
                add('landmark',pos(px,pz),8,'landmark:'+str(index),landmark['name'])
    return records


def painted_overlay(canvas,record):
    """Whether a planned record has the real art or its existing GG drawing."""
    if record['kind'] not in ('poi','rim'):return True
    path=record.get('path');art=bool(path and not canvas.image(path).isNull())
    if not art and record.get('fallback'):
        angle=math.radians(record['rotation']);c,s=math.cos(angle),math.sin(angle)
        px,py=record['point']
        points=[(px+c*x-s*y,py+s*x+c*y) for x,y in ((0,-6),(4,4),(0,2),(-4,4))]
        left,top=min(x for x,y in points),min(y for x,y in points)
        record['hit_rect']=(left,top,max(x for x,y in points)-left,max(y for x,y in points)-top)
    return bool(art or record.get('fallback'))


def hit_overlay(records,rect,row,x,y):
    if not rect.contains(x,y) or rect.width()<=0 or rect.height()<=0:return None
    center=rect.center()
    if ((x-center.x())/(rect.width()/2))**2+((y-center.y())/(rect.height()/2))**2>1:return None
    if row.get('clip') and not QRectF(*row['clip']).contains(x,y):return None
    for record in reversed(records):
        if QRectF(*record.get('hit_rect',record['rect'])).contains(x,y):return record
        if record.get('signal'):
            px,py=record['point']
            if QRectF(px-6,py-16,12,12).contains(x,y):return record
    return None


def paint_overlays(canvas,painter,records):
    """Draw the same ordered geometry the main-thread hover consumer sees."""
    for record in records:
        point=QPointF(*record['point']);kind=record['kind']
        painter.setPen(Qt.NoPen)
        if kind=='poi':
            image=canvas.image(record['path'])
            if not image.isNull():
                icon=record['icon'];painter.drawImage(QRectF(*record['rect']),image,
                    QRectF(icon%8*image.width()/8,icon//8*image.height()/8,image.width()/8,image.height()/8))
        elif kind=='rim':
            image=canvas.image(record['path']) if record.get('path') else QImage()
            painter.save();painter.translate(point);painter.rotate(record['rotation'])
            size=record['rect'][2]
            if not image.isNull():painter.drawImage(QRectF(-size/2,-size/2,size,size),image)
            elif record['fallback']:
                painter.setBrush(QColor(record['color']))
                painter.drawPolygon(QPolygonF([QPointF(0,-6),QPointF(4,4),QPointF(0,2),QPointF(-4,4)]))
            painter.restore()
        elif kind=='dot':
            painter.setBrush(QColor(record['color']));painter.drawEllipse(QRectF(*record['rect']))
            if record.get('signal'):
                painter.setPen(QColor('#ffe393'))
                painter.drawText(QRectF(point.x()-6,point.y()-16,12,12),Qt.AlignCenter,record['signal'])
        elif kind=='landmark':
            painter.setBrush(QColor('#d6b372'));painter.drawPolygon(QPolygonF([
                point+QPointF(0,-4),point+QPointF(4,0),point+QPointF(0,4),point+QPointF(-4,0)]))


def paint(canvas,painter,rect,row):
    snapshot=getattr(canvas,'_minimap_snapshot_view',None)
    if snapshot is None:snapshot=getattr(canvas.runtime,'snapshot',{})
    player=snapshot.get('player',{})
    # The QML canvas can paint before its first world snapshot is published.
    # A pending world has no position or environment to project yet.
    if not isinstance(player,dict) or not player:
        painter.fillRect(rect,QColor('#15232b'))
        return
    from backend.game_engine_adapter_world import environment
    world=environment(snapshot) if player else {}
    inside=player_indoors(canvas.runtime,snapshot)
    extent=radius(row.get('zoom',0),row.get('inside_zoom',0),inside)
    x,z=float(player.get('x',0)),float(player.get('z',0));centre=rect.center()
    clip=QPainterPath();clip.addEllipse(rect);painter.setClipPath(clip,Qt.IntersectClip)
    painter.fillRect(rect,QColor('#15232b'))
    image=canvas.image('assets/authored/world/gg-first-planet-map.svg')
    bounds=catalog()['world_rect'];nw=project(bounds,x-extent,z+extent);se=project(bounds,x+extent,z-extent)
    if not player.get('engine_world') and nw is not None and se is not None and not image.isNull():
        source=QRectF((64+nw[0]*840)/1440*image.width(),(82+nw[1]*840)/1020*image.height(),
                      (se[0]-nw[0])*840/1440*image.width(),(se[1]-nw[1])*840/1020*image.height())
        painter.drawImage(rect,image,source)
    imported=bool(player.get('engine_world'));atlas=cached_atlas(canvas.runtime)
    hashed=paint_imported_tiles(canvas,painter,rect,snapshot,extent) if imported else False
    if imported and not hashed and atlas and atlas.get('selected_map'):
        area_id=player['engine_world'].get('area_id')
        area=next((a for a in atlas['areas'] if a['id']==area_id),{})
        continent=next((c for c in atlas['catalog']['continents'] if c['map']==atlas['selected_map']['id']),{})
        zone=next((a for a in continent.get('zones',[]) if a['area_id']==area.get('top_zone')),None)
        if zone is None:zone=next((a for a in atlas['direct'] if a['map']==atlas['selected_map']['id']),None)
        if zone:
            left,right,top,bottom=zone['rect'];span_x=left-right;span_y=top-bottom
            if span_x>0 and span_y>0:
                origin=atlas.get('origin',[0.,0.,0.]);u=1-(origin[1]-z-right)/span_x;v=1-(x+origin[0]-bottom)/span_y
                crop=QRectF((u-extent/span_x)*1002,(v-extent/span_y)*668,extent*2/span_x*1002,extent*2/span_y*668)
                for i in range(12):
                    tile=QRectF(i%4*256,i//4*256,min(256,1002-i%4*256),min(256,668-i//4*256));visible=tile.intersected(crop)
                    if visible.isEmpty():continue
                    art=canvas.image('Interface\\WorldMap\\'+zone['map_file']+'\\'+zone['map_file']+str(i+1))
                    if art.isNull():continue
                    target=QRectF(rect.x()+(visible.x()-crop.x())/crop.width()*rect.width(),rect.y()+(visible.y()-crop.y())/crop.height()*rect.height(),visible.width()/crop.width()*rect.width(),visible.height()/crop.height()*rect.height())
                    source=QRectF((visible.x()-tile.x())/256*art.width(),(visible.y()-tile.y())/256*art.height(),visible.width()/256*art.width(),visible.height()/256*art.height())
                    painter.drawImage(target,art,source)
    def pos(px,pz):
        dx,dz=float(px)-x,float(pz)-z
        return QPointF(centre.x()+(dz if imported else dx)*rect.width()/(extent*2),centre.y()-(dx if imported else dz)*rect.height()/(extent*2))
    services=player.get('client_controls',{}).get('services',{})
    map_id,instance_id=map_identity(snapshot,atlas)
    prepared=getattr(canvas,'_minimap_plans',{}).get(row.get('id'))
    records=prepared['records'] if prepared is not None else overlay_geometry(canvas.runtime,snapshot,rect,row,atlas)
    paint_overlays(canvas,painter,records)
    life=services.get('lifecycle',{});corpse=life.get('position',{})
    if life.get('dead') and corpse.get('map_id',0)==map_id and corpse.get('instance_id',0)==instance_id and 'x' in corpse and 'z' in corpse:
        if math.hypot(corpse['x']-x,corpse['z']-z)<=extent*BLIP_EDGE:
            point=pos(corpse['x'],corpse['z']);painter.setPen(QColor('#f4eeee'))
            painter.drawLine(point+QPointF(-4,0),point+QPointF(4,0));painter.drawLine(point+QPointF(0,-4),point+QPointF(0,4))
    ping=getattr(canvas.runtime,'_minimap_ping',None)
    if isinstance(ping,dict) and ping.get('owner') is getattr(canvas.runtime,'lua',None):
        offset=ping_position(snapshot,ping,row.get('zoom',0),row.get('inside_zoom',0),inside,atlas=atlas)
        if offset is not None:
            age=time.monotonic()-ping['time'];point=pos(ping['x'],ping['z']);fade=min(1.,max(0.,(5.5-age)/.5))
            painter.save();painter.setOpacity(fade);painter.setPen(QColor('#ffd768'));painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point,5+(age%1)*6,5+(age%1)*6);painter.restore()
    yaw=float(player.get('yaw',0));direction=QPointF(math.cos(yaw),-math.sin(yaw)) if imported else QPointF(math.sin(yaw),-math.cos(yaw));side=QPointF(-direction.y(),direction.x())
    painter.setPen(QColor('#123c36'));painter.setBrush(QColor('#72dec3'))
    painter.drawPolygon(QPolygonF([centre+direction*9,centre-direction*4+side*4,centre-direction*4-side*4]))
