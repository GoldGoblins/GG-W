"""Public Qt table ABI, immutable publication and bounded bad-input rejection."""
import math,os,struct,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication,QVector3D,QColor,QQuaternion,QVector4D
from PySide6.QtQuick3D import QQuick3DInstancing
from backend.game_engine_adapter_instances import InstanceTable
APP=QGuiApplication.instance() or QGuiApplication([])
def encoded(entry):
    values=[]
    for name in ('row0','row1','row2','color','instanceData'):
        v=getattr(entry,name);values.extend((v.x(),v.y(),v.z(),v.w()))
    return struct.pack('<20f',*values)
class Instances(unittest.TestCase):
    def test_native_qt_reads_same_transform_color_and_custom_data(self):
        parent=QObject();table=InstanceTable(2,parent,transparent=True)
        entry=QQuick3DInstancing.calculateTableEntryFromQuaternion(QVector3D(3,4,5),QVector3D(2,3,4),QQuaternion.fromAxisAndAngle(QVector3D(0,1,0),37),QColor.fromRgbF(.2,.4,.6,.5),QVector4D(1,2,3,4))
        table.update(encoded(entry),1)
        self.assertEqual(table.instancePosition(0),entry.getPosition())
        self.assertLess((table.instanceScale(0)-entry.getScale()).length(),1e-5)
        self.assertLess(table.instanceRotation(0).toEulerAngles().distanceToPoint(entry.getRotation().toEulerAngles()),1e-4)
        self.assertEqual(table.instanceColor(0),entry.getColor());self.assertEqual(table.instanceCustomData(0),entry.instanceData)
        self.assertTrue(table.depthSortingEnabled());self.assertTrue(table.hasTransparency())
    def test_publication_keeps_buffer_and_count_paired_and_reuses_equal_data(self):
        parent=QObject();table=InstanceTable(2,parent);row=encoded(QQuick3DInstancing.calculateTableEntry(QVector3D(),QVector3D(1,1,1),QVector3D(),QColor('white')))
        table.update(row,1);packet=table.getInstanceBuffer();table.update(row,1)
        self.assertIs(table.getInstanceBuffer(),packet)
        table.update(row*2,2);self.assertEqual(packet[1],1);self.assertEqual(len(packet[0]),80)
        self.assertEqual(table.count,2);self.assertEqual(table.getInstanceBufferOverride(),table.getInstanceBuffer())
        table.update(b'',0);self.assertEqual(table.count,0)
    def test_bad_packet_cannot_mutate_published_buffer(self):
        parent=QObject();table=InstanceTable(1,parent);row=encoded(QQuick3DInstancing.calculateTableEntry(QVector3D(),QVector3D(1,1,1),QVector3D(),QColor('white')));table.update(row,1);packet=table.getInstanceBuffer()
        for data,count in ((row*2,2),(row[:-1],1),(row,-1),(row,True),(struct.pack('<20f',math.nan,*([0]*19)),1)):
            with self.assertRaises(ValueError):table.update(data,count)
            self.assertIs(table.getInstanceBuffer(),packet)
        for capacity in (0,65537,True):
            with self.assertRaises(ValueError):InstanceTable(capacity,parent)
if __name__=='__main__':unittest.main()
