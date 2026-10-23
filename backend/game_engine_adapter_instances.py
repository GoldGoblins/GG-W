"""Retained RAM instance tables for Qt Quick 3D; no files or per-instance objects.

The table is the public QQuick3DInstancing five-vector ABI. Qt owns upload and
per-instance depth sorting. Updates publish an immutable buffer/count pair.
"""
import math,struct
from PySide6.QtCore import QObject,QByteArray
from PySide6.QtQuick3D import QQuick3DInstancing

STRIDE=80
class InstanceTable(QQuick3DInstancing):
    def __init__(self,capacity,parent,*,transparent=False):
        if type(capacity) is not int or not 0<capacity<=65536:raise ValueError('Invalid instance table capacity')
        super().__init__();QObject.setParent(self,parent)
        self.capacity=capacity;self._packet=(QByteArray(),0)
        self.setHasTransparency(transparent);self.setDepthSortingEnabled(transparent)
    def update(self,data,count):
        if type(count) is not int or not 0<=count<=self.capacity or len(data)!=count*STRIDE:raise ValueError('Invalid instance table data')
        if any(not math.isfinite(x) for row in struct.iter_unpack('<20f',data) for x in row):raise ValueError('Non-finite instance transform or color')
        self._publish(data,count)
    def update_native(self,data,count):
        """Only for GG native packets whose producer checked all twenty floats.

        Keep structural validation here. Repeating the native numeric check in
        Python for tens of thousands of weather instances stalls the GUI.
        """
        if type(count) is not int or not 0<=count<=self.capacity or len(data)!=count*STRIDE:raise ValueError('Invalid native instance table data')
        self._publish(data,count)
    def _publish(self,data,count):
        if self._packet[1]==count and bytes(self._packet[0])==data:return
        self._packet=(QByteArray(data),count);self.markDirty()
    def getInstanceBuffer(self):return self._packet
    # Newer bindings name the Python override explicitly; keep both entry points.
    def getInstanceBufferOverride(self):return self._packet
    @property
    def count(self):return self._packet[1]
