"""The same retained ModelPane root, expressed in the native WoW basis."""
import math


def anchor(row, viewport=None):
    scale=float(row.get('model_scale',1))*float(row.get('scale',1))
    facing=float(row.get('facing',0));position=list(row.get('position',(0,0,0)))
    if len(position)!=3 or any(not math.isfinite(float(x)) for x in [scale,facing,*position]):
        raise ValueError('Invalid model pane root')
    # A hidden zero-scale pane cannot define an invertible coordinate space.
    # It has no visible trails; retain the last finite metric until shown.
    scale=math.copysign(max(.01,abs(scale)),scale or 1)
    if viewport is not None:
        width,height=viewport;diag=math.sqrt(1+(width/max(1,height))**2)
        if row.get('camera') is not None:
            scale*= (5/3)/diag
        else:
            layout=float(row.get('scale',1));factor=.6*diag*layout
            position=[float(position[0])*factor+float(row.get('x',0))/1280,
                      float(position[1])*factor-(float(row.get('y',0))+float(row.get('height',0)))/1280,
                      float(position[2])*factor]
    c,s=math.cos(facing)*scale,math.sin(facing)*scale
    return [c,s,0.,0.,-s,c,0.,0.,0.,0.,scale,0.,*map(float,position),1.]
