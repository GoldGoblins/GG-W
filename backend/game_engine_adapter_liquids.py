"""Original MCLQ/MLIQ wet grids and bounded animated texture atlases.

Grid interpolation and liquid claims follow GgEngine's liquid/query.rs. The Qt
atlas replaces its Bevy texture array; it never changes the grid's geometry.
"""
import json,math,struct,time
from PySide6.QtGui import QImage,QImageReader

KINDS={'STILL':('river','lake_a',30),'RAPIDS':('river','fast_a',16),
       'OCEAN':('ocean','ocean_h',30),'MAGMA':('lava','lava',30),'SLIME':('slime','slime',30)}
DEFAULT_SHALLOW=[.08,.42,.55,.25]
DEFAULT_DEEP=[.02,.15,.27,.85]

def validate_settings(settings,resolve):
    if not isinstance(settings,dict) or any(k not in KINDS for k in settings):raise ValueError('Invalid world liquid settings')
    for spec in settings.values():
        if not isinstance(spec,dict) or any(k not in ('frames','shallow','deep') for k in spec):raise ValueError('Invalid liquid material settings')
        if 'frames' in spec:
            frames=spec['frames']
            if not isinstance(frames,list) or not 1<=len(frames)<=30 or any(not isinstance(p,str) or not p or len(p.encode())>1024 for p in frames):raise ValueError('Liquid requires 1 to 30 local frames')
            for p in frames:resolve(p)
        for key in ('shallow','deep'):
            if key in spec:
                color=spec[key]
                if not isinstance(color,list) or len(color)!=4 or any(isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n) or not 0<=n<=1 for n in color):raise ValueError('Liquid swatch requires four values between 0 and 1')

def prepare_atlas(cache,path,kind,settings,*,staging_budget=32*1024*1024):
    """One immutable atlas per page/kind; no per-frame GPU uploads."""
    spec=settings.get(kind,{});directory,stem,count=KINDS[kind]
    sources=spec.get('frames',[f'XTextures/{directory}/{stem}.{i}.blp' for i in range(1,count+1)])
    from backend.game_engine_adapter_mips import atlas as mip_atlas,image_levels
    if type(staging_budget) is not int or not 0<staging_budget<=32*1024*1024:raise ValueError('Invalid liquid staging budget')
    images=[];size=0;notes=[];layout=None;authored=None;held_bytes=0;frame_bytes=0
    def check_capacity(number,width,shape,new_bytes):
        cols=min(6,number);rows=math.ceil(number/cols)
        atlas_bytes=cols*width*rows*sum(h for w,h in shape)*4
        if atlas_bytes>16*1024*1024:raise ValueError('Liquid atlas memory capacity exceeded')
        if held_bytes+new_bytes+atlas_bytes>staging_budget:raise ValueError('Liquid staging memory capacity exceeded')
    for source in sources:
        if time.monotonic()>cache.deadline:raise TimeoutError('Liquid frames exceeded world preparation deadline')
        try:texture=cache._texture(source,path)
        except ValueError as exc:
            if not str(exc).startswith('Model texture missing: '):raise
            if not images or 'frames' in spec:raise ValueError(f'Liquid {kind} frame unavailable: {source}')
            notes.append(f'{kind}: using {len(images)} of {len(sources)} animation frames');break
        # Resolve first: a missing default suffix is a valid shorter animation.
        # With a known layout, reject the next retained frame before decoding it.
        if images:check_capacity(len(images)+1,size,layout,frame_bytes)
        is_authored=texture.suffix.lower()=='.blp'
        if is_authored or texture.suffix.lower()=='.tga':
            metadata,pixels=cache.decode(texture,**({'mip_chain':True} if is_authored else {}))
            width=metadata.get('width');height=metadata.get('height')
            if type(width) is not int or type(height) is not int or not 1<=width<=512 or width!=height:raise ValueError('Invalid liquid frame dimensions')
            count=len(metadata['levels']) if is_authored and isinstance(metadata.get('levels'),list) else 1
            if not 1<=count<=16:raise ValueError('Invalid authored mip count')
            shape=[[max(1,width>>i),max(1,height>>i)] for i in range(count)]
            check_capacity(len(images)+1,width,shape,width*sum(h for w,h in shape)*4)
            if is_authored:image,levels=mip_atlas(metadata,pixels)
            else:
                from backend.game_engine_adapter_formats import image_from_rgba
                image=image_from_rgba(metadata,pixels);levels=[]
        else:
            reader=QImageReader(str(texture));dimensions=reader.size()
            if dimensions.width()<1 or dimensions.width()>512 or dimensions.width()!=dimensions.height():raise ValueError('Liquid frame must be square and at most 512 pixels')
            width=dimensions.width();check_capacity(len(images)+1,width,[[width,width]],width*width*4)
            image=reader.read();levels=[]
        if image.isNull():raise ValueError('Invalid liquid frame dimensions')
        levels=image_levels(image) if is_authored else [[0,0,image.width(),image.height()]]
        base=levels[0]
        if base[2]!=base[3] or not 1<=base[2]<=512:raise ValueError('Invalid liquid frame dimensions')
        shape=[row[2:] for row in levels]
        if size and (base[2]!=size or layout!=shape or authored!=is_authored):raise ValueError('Liquid animation frames differ in authored mip layout')
        size=base[2];layout=shape;authored=is_authored
        image=image.convertToFormat(QImage.Format_RGBA8888);frame_bytes=image.sizeInBytes()
        check_capacity(len(images)+1,size,layout,frame_bytes)
        images.append((image,levels));held_bytes+=frame_bytes
    cols=min(6,len(images));rows=math.ceil(len(images)/cols);sheets=[];height=0
    for w,h in layout:sheets.append([0,height,cols*w,rows*h]);height+=rows*h
    if cols*size*height*4>16*1024*1024:raise ValueError('Liquid atlas memory capacity exceeded')
    atlas=QImage(cols*size,height,QImage.Format_RGBA8888);atlas.fill(0)
    # The detail shader reads RGB and alpha independently. Alpha compositing
    # would erase RGB from transparent pixels and silently destroy animation.
    target=atlas.bits();pitch=atlas.bytesPerLine()
    for i,(image,levels) in enumerate(images):
        source=image.constBits();source_pitch=image.bytesPerLine()
        for rectangle,sheet in zip(levels,sheets):
            x,top,w,h=rectangle
            for y in range(h):
                offset=(sheet[1]+(i//cols)*h+y)*pitch+(i%cols)*w*4
                start=(top+y)*source_pitch+x*4
                target[offset:offset+w*4]=source[start:start+w*4]
    if authored:atlas.setText('GG_MIP_LEVELS',json.dumps(sheets,separators=(',',':')))
    return atlas,{'frames':len(images),'atlas_grid':[cols,rows],'atlas_size':[atlas.width(),atlas.height()],
                  'shallow':spec.get('shallow',DEFAULT_SHALLOW),'deep':spec.get('deep',DEFAULT_DEEP)},notes

class LiquidGrid:
    """Wet-cell bilinear, including recentered and rotated world placements."""
    def __init__(self,row,blob):
        self.row=row;self.cols,self.rows=row['grid'];self.wet=row['wet']
        if self.cols<2 or self.rows<2 or self.cols*self.rows!=row['vertices'] or len(self.wet)!=(self.cols-1)*(self.rows-1):raise ValueError('Invalid liquid dimensions')
        self.points=[struct.unpack_from('<3f',blob,row['offset']+i*row['stride']) for i in range(row['vertices'])]
        if any(not math.isfinite(v) for p in self.points for v in p):raise ValueError('Non-finite liquid grid')
        used=set()
        for cell,wet in enumerate(self.wet):
            if wet:
                j,i=divmod(cell,self.cols-1);a=j*self.cols+i;used.update((a,a+1,a+self.cols,a+self.cols+1))
        if not used:raise ValueError('Liquid grid has no wet cells')
        self.bounds=([min(self.points[i][k] for i in used) for k in range(3)],[max(self.points[i][k] for i in used) for k in range(3)])
        self.origin=self.points[0]
        self.u=[(self.points[self.cols-1][k]-self.origin[k])/(self.cols-1) for k in (0,2)]
        self.v=[(self.points[(self.rows-1)*self.cols][k]-self.origin[k])/(self.rows-1) for k in (0,2)]
        self.det=self.u[0]*self.v[1]-self.u[1]*self.v[0]
        self.bytes=len(self.points)*96+len(self.wet)*24+len(row['indices'])*36+1024
    def sample(self,x,z):
        lo,hi=self.bounds
        if x<lo[0]-.001 or x>hi[0]+.001 or z<lo[2]-.001 or z>hi[2]+.001:return None
        if abs(self.det)<1e-9:return hi[1],0.,0.
        dx,dz=x-self.origin[0],z-self.origin[2]
        a=(dx*self.v[1]-dz*self.v[0])/self.det;b=(self.u[0]*dz-self.u[1]*dx)/self.det
        if a<-.001 or b<-.001 or a>self.cols-1+.001 or b>self.rows-1+.001:return None
        i=min(self.cols-2,max(0,math.floor(a)));j=min(self.rows-2,max(0,math.floor(b)))
        if not self.wet[j*(self.cols-1)+i]:return None
        fx=max(0,min(1,a-i));fy=max(0,min(1,b-j));offset=j*self.cols+i
        h00,h10,h01,h11=(self.points[k][1] for k in (offset,offset+1,offset+self.cols,offset+self.cols+1))
        h0=h00+(h10-h00)*fx;h1=h01+(h11-h01)*fx;height=h0+(h1-h0)*fy
        da=(h10-h00)*(1-fy)+(h11-h01)*fy;db=h1-h0
        sx=(da*self.v[1]-db*self.u[1])/self.det;sz=(db*self.u[0]-da*self.v[0])/self.det
        return height,sx,sz

class LiquidIndex:
    def __init__(self,metadata,blob):
        self.grids=[];self.cells={};self.bytes=0
        for row in metadata['rows']:
            if row['kind']!='liquid':continue
            grid=LiquidGrid(row,blob);self.grids.append(grid);self.bytes+=grid.bytes
            lo,hi=grid.bounds;ax,az=math.floor(lo[0]/16),math.floor(lo[2]/16);bx,bz=math.floor(hi[0]/16),math.floor(hi[2]/16)
            if (bx-ax+1)*(bz-az+1)>4096:raise ValueError('Liquid footprint capacity exceeded')
            for cx in range(ax,bx+1):
                for cz in range(az,bz+1):self.cells.setdefault((cx,cz),[]).append(grid);self.bytes+=96
            if self.bytes>32*1024*1024:raise ValueError('Liquid CPU memory capacity exceeded')
    def sample(self,x,y,z,inside):
        result=None
        for grid in self.cells.get((math.floor(x/16),math.floor(z/16)),()):
            row=grid.row
            if inside!=(row.get('group') is not None):continue
            floor=row.get('pool_floor')
            if floor is not None and y<floor:continue
            sample=grid.sample(x,z)
            if sample is not None and (result is None or sample[0]<result[0][0]):result=(sample,row['liquid_kind'])
        return result
