"""Retained original cloud dome and native cloud tile; GUI-thread ownership."""
import math,struct
from PySide6.QtCore import QObject,QSize
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry,QQuick3DTextureData

class CloudLayer:
    def __init__(self,stream):
        self.stream=stream;self.closed=False;self.geometry=None;self.texture=None;self.data=None
        colat=(0,.025,.05,.075,.1,.125,.15,.175,.205,.23,.245,.25)
        alpha=(1,1,1,1,1,1,1,1,1,128/255,0,0);vertices=bytearray();indices=[]
        for ring,(angle,a) in enumerate(zip(colat,alpha)):
            p=angle*math.pi
            for j in range(16):
                az=j/16*math.tau;sa,ca=math.sin(az),math.cos(az)
                point=(-math.sin(p)*ca,math.cos(p)-math.cos(math.pi/4),math.sin(p)*sa)
                length=math.sqrt(sum(v*v for v in point));point=tuple(v/length for v in point)
                vertices.extend(struct.pack('<12f',*point,*point,sa*ring/24+.5,ca*ring/24+.5,1,1,1,a))
        for ring in range(11):
            for j in range(16):
                a=ring*16+j;b=a+16;c=ring*16+(j+1)%16;d=c+16;indices.extend((a,b,c,c,b,d))
        index=struct.pack('<'+str(len(indices))+'I',*indices)
        self.bytes=(len(vertices)+len(index))*2+128*128*4*3
        if stream.bytes+self.bytes>stream.budget_limit:raise ValueError('Cloud layer exceeds world residency budget')
        self.geometry=QQuick3DGeometry();self.texture=QQuick3DTextureData();QObject.setParent(self.geometry,stream);QObject.setParent(self.texture,stream);g=self.geometry
        g.setStride(48);g.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles);A=QQuick3DGeometry.Attribute
        for semantic,offset,kind in ((A.PositionSemantic,0,A.F32Type),(A.NormalSemantic,12,A.F32Type),(A.TexCoord0Semantic,24,A.F32Type),(A.ColorSemantic,32,A.F32Type),(A.IndexSemantic,0,A.U32Type)):g.addAttribute(semantic,offset,kind)
        g.setVertexData(vertices);g.setIndexData(index);g.setBounds(QVector3D(-1,0,-1),QVector3D(1,1,1))
        stream.bytes+=self.bytes;self.texture.setSize(QSize(128,128));self.texture.setFormat(QQuick3DTextureData.Format.RGBA8);self.texture.setHasTransparency(True)
    def update(self,data):
        if len(data)!=128*128*4:raise ValueError('Invalid native cloud image')
        if data!=self.data:self.texture.setTextureData(data);self.data=data
    def close(self):
        if self.closed:return
        self.closed=True;self.stream.bytes-=self.bytes;self.geometry.deleteLater();self.texture.deleteLater();self.data=None
