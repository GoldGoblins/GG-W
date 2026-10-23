"""Pack authored mip pixels without filtering or inventing absent levels.

The model shader samples this level-zero atlas explicitly. That preserves a
partial authored chain and clamps its LOD instead of asking Qt to regenerate it.
"""
import json,struct
from PySide6.QtGui import QImage

def image_levels(image):
    """Validate atlas rectangles before publishing them to texelFetch shaders."""
    text=image.text('GG_MIP_LEVELS')
    if not text:return []
    if len(text)>4096:raise ValueError('Authored mip rectangle capacity exceeded')
    try:rows=json.loads(text)
    except (ValueError,TypeError) as exc:raise ValueError('Invalid authored mip rectangles') from exc
    if not isinstance(rows,list) or not 1<=len(rows)<=16:raise ValueError('Invalid authored mip rectangles')
    for row in rows:
        if not isinstance(row,list) or len(row)!=4 or any(type(v) is not int for v in row):raise ValueError('Invalid authored mip rectangle')
        x,y,w,h=row
        if min(x,y)<0 or min(w,h)<1 or x+w>image.width() or y+h>image.height():raise ValueError('Authored mip rectangle outside image')
    return rows

def table_key(chains):
    if not isinstance(chains,(list,tuple)) or not 1<=len(chains)<=4:raise ValueError('Invalid authored mip table layers')
    if any(not isinstance(rows,(list,tuple)) or len(rows)>16 for rows in chains):raise ValueError('Invalid authored mip table levels')
    return tuple(tuple(tuple(row) for row in rows) for rows in chains)

def install_table(batch,chains,shared=None):
    """Small exact float rectangle table; shared within its owning world page."""
    from PySide6.QtCore import QObject,QSize
    from PySide6.QtQuick3D import QQuick3DTextureData
    key=table_key(chains)
    if shared is not None and key in shared:batch.mip_lookup=shared[key]
    else:
        values=[]
        for chain in key:
            for i in range(16):
                row=chain[i] if i<len(chain) else (0,0,1,1)
                if len(row)!=4 or any(type(n) is not int or n<0 or n>32768 for n in row) or min(row[2:])<1:raise ValueError('Invalid authored mip table rectangle')
                values.extend(row)
        data=struct.pack('<'+str(len(values))+'f',*values)
        batch.owner.reserve(len(data)*2)
        texture=QQuick3DTextureData();QObject.setParent(texture,batch)
        texture.setSize(QSize(16,len(key)));texture.setFormat(QQuick3DTextureData.Format.RGBA32F)
        texture.setTextureData(data);batch.mip_lookup=texture
        if shared is not None:shared[key]=texture
    batch.row['mip_counts']=[len(rows) for rows in key]

def atlas(metadata,data):
    levels=metadata.get('levels')
    if not isinstance(levels,list) or not 1<=len(levels)<=16:raise ValueError('Invalid authored mip count')
    width=metadata.get('width');height=metadata.get('height')
    if type(width) is not int or type(height) is not int or min(width,height)<1 or width*height>2*1024*1024:raise ValueError('Authored mip dimensions exceeded')
    if len(data)>16*1024*1024:raise ValueError('Authored mip bytes exceeded')
    expected=0;rows=[];y=0
    for i,row in enumerate(levels):
        w,h=max(1,width>>i),max(1,height>>i)
        if any(type(row.get(k)) is not int for k in ('width','height','offset','bytes','mip')) or (row['width'],row['height'],row['mip'],row['offset'],row['bytes'])!=(w,h,i,expected,w*h*4):raise ValueError('Invalid authored mip layout')
        expected+=w*h*4;rows.append([0,y,w,h]);y+=h
    if expected!=len(data) or width*y*8>32*1024*1024:raise ValueError('Authored mip storage exceeded')
    output=bytearray(width*y*4)
    for level,rectangle in zip(levels,rows):
        _,top,w,h=rectangle
        for row in range(h):
            start=level['offset']+row*w*4;target=((top+row)*width)*4
            output[target:target+w*4]=data[start:start+w*4]
    image=QImage(bytes(output),width,y,width*4,QImage.Format_RGBA8888).copy()
    if image.isNull():raise ValueError('Authored mip atlas unavailable')
    image.setText('GG_MIP_LEVELS',json.dumps(rows,separators=(',',':')))
    return image,rows
