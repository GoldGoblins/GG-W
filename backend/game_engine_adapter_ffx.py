"""Bounded Qt adaptation of GgEngine's FFXGlow/Death/Wave laws (MIT)."""
import math,struct
from PySide6.QtCore import QSize,QObject
from PySide6.QtQuick3D import QQuick3DTextureData

def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def wave_bytes():
    # Preserve the original f32 sine inputs and ftol/truncating byte pack.
    row=[]
    for i in range(128):
        phase=f32(f32(f32(math.tau)*i)/128.)
        sine=f32(math.sin(phase));value=f32(f32(f32(sine*.5)+.5)*255.)
        row.append(max(0,min(255,int(value))))
    return bytes(channel for y in range(128) for x in range(128) for channel in (row[x],row[y],0,255))

class WaveTexture(QQuick3DTextureData):
    def __init__(self,parent=None):
        super().__init__();QObject.setParent(self,parent);self.setSize(QSize(128,128));self.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.setHasTransparency(False);self.setTextureData(wave_bytes())

def wave_for(host):
    texture=getattr(host,'_engine_ffx_wave',None)
    if texture is None:texture=WaveTexture(host);host._engine_ffx_wave=texture
    return texture

def state(lighting,switches,drunk=0):
    ghost=lighting.get('ghost',False) is True;wet=lighting.get('submersion','DRY')!='DRY'
    enabled=switches.get('ffx',True) and switches.get('ffxDeath' if ghost else 'ffxGlow',True)
    glow=float(lighting.get('glow',.5));drunk=float(drunk)
    if not math.isfinite(glow) or not 0<=glow<=4 or not math.isfinite(drunk):raise ValueError('Invalid original FFX inputs')
    return {'gain':glow if enabled else 0.,'ghost':ghost and enabled,
        'haze':max(max(0,min(100,drunk))/100,84/255 if wet else 0) if enabled and not ghost else 0.,
        'wave':wet and enabled and not ghost,'source':lighting.get('source','GG_MANIFEST_DEFAULTS')}
