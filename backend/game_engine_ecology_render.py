"""Qt-side mesh and instance caches. No Qt objects enter the simulation."""
from __future__ import annotations
import struct,math
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry, QQuick3DInstancing

def instance_bytes(row):
    """Qt's Ry * Rx * Rz matrix and linear colour, packed without Qt wrappers."""
    p,y,r=(math.radians(row.get(k,0)) for k in ('pitch','yaw','roll'))
    sx,cx=math.sin(p),math.cos(p);sy,cy=math.sin(y),math.cos(y);sz,cz=math.sin(r),math.cos(r)
    scale=row['scale'];t=max(0,min(1,row.get('tint',1)))
    # QColor stores RGB16, then calculateTableEntry converts sRGB to linear.
    t=round(t*65535)/65535
    colour=t*(t*(t*.305306011+.682171111)+.012522878)
    rgb = (colour, colour, colour)
    if row.get('editor_color'):
        from PySide6.QtGui import QColor
        tint = QColor(row['editor_color'])
        rgb = tuple(v*(v*(v*.305306011+.682171111)+.012522878) * colour
                    for v in (tint.redF(), tint.greenF(), tint.blueF()))
    return struct.pack('<20f',
        (cy*cz+sy*sx*sz)*scale,(-cy*sz+sy*sx*cz)*scale,sy*cx*scale,row['x'],
        cx*sz*scale,cx*cz*scale,-sx*scale,row['y'],
        (-sy*cz+cy*sx*sz)*scale,(sy*sz+cy*sx*cz)*scale,cy*cx*scale,row['z'],
        *rgb,row.get("alpha",1),0,0,0,0)

ASSETS = Path(__file__).resolve().parents[1]/"qml/assets/authored/flora"


class FloraInstances(QQuick3DInstancing):
    def __init__(self, parent=None):
        super().__init__()
        if parent is not None:
            self.setParent(parent)
        self._buffer = QByteArray()
        self._count = 0
        self.revision = -1
        self._signature = None
        self.identities = ()
        self.pack_backend = "NOT_PACKED"
        self.pack_calls = 0

    def replace(self, rows: list[dict], revision: int):
        if self.revision == revision:
            return
        signature = tuple((r["id"],r["x"],r["y"],r["z"],r["scale"],r["yaw"],r.get("pitch",0),r.get("roll",0),r.get('tint',1),r.get('editor_color'),r.get('alpha',1)) for r in rows)
        if signature == self._signature:
            self.revision = revision
            return
        from backend.game_engine_native_presentation import pack_instances
        data = pack_instances(rows)
        backend = "CPP"
        if data is None:
            data = b"".join(instance_bytes(row) for row in rows)
            backend = "PYTHON"
        self.revision = revision
        self._signature = signature
        self.identities = tuple(r["id"] for r in rows)
        self.pack_backend = backend
        self.pack_calls += 1
        transparent = any(row.get("alpha",1) < 1 for row in rows)
        self.setHasTransparency(transparent)
        self.setDepthSortingEnabled(transparent)
        self._buffer = QByteArray(bytes(data))
        self._count = len(rows)
        self.markDirty()

    def getInstanceBuffer(self):
        # PySide's virtual out-parameter is returned alongside QByteArray.
        return self._buffer, self._count


class FloraRenderCache(QObject):
    def __init__(self, parent=None, *, assets=ASSETS, keys=None,max_vertices=12000):
        super().__init__(parent)
        self.meshes = {}
        self.tables = {}
        from backend.game_engine_ecology import GROUP_KEYS
        self.assets = assets
        self.max_vertices=max_vertices
        self.keys = GROUP_KEYS if keys is None else keys

    def geometry(self, key: str):
        if key in self.meshes:
            return self.meshes[key]
        # The asset compiler emits only these fixed native formats and keys.
        if key not in self.keys:
            return None
        filename = key.replace(":", "-lod") if self.assets == ASSETS else key.replace(":", "-")
        path = self.assets / (filename + ".ggmesh")
        if not path.is_file() and self.assets.name=='nature' and '-v' in filename:
            path=self.assets.parent/'variants/nature'/(filename+'.ggmesh')
        if not path.is_file():
            return None
        data = path.read_bytes()
        magic, stride, nv, ni = struct.unpack_from("<8sIII", data)
        if magic != b"GGFLORA1" or stride != 40 or nv > self.max_vertices or ni > self.max_vertices*3:
            raise ValueError("invalid compiled flora mesh")
        split = 20 + nv*stride
        if len(data) != split + ni*4:
            raise ValueError("truncated compiled flora mesh")
        geometry = QQuick3DGeometry()
        geometry.setParent(self)
        geometry.setObjectName("gameFloraMesh_"+key)
        geometry.setStride(stride)
        geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        for semantic, offset in ((QQuick3DGeometry.Attribute.PositionSemantic, 0),
                                  (QQuick3DGeometry.Attribute.NormalSemantic, 12),
                                  (QQuick3DGeometry.Attribute.ColorSemantic, 24)):
            geometry.addAttribute(semantic, offset, QQuick3DGeometry.Attribute.F32Type)
        geometry.addAttribute(QQuick3DGeometry.Attribute.IndexSemantic, 0,
                              QQuick3DGeometry.Attribute.U32Type)
        geometry.setVertexData(data[20:split])
        geometry.setIndexData(data[split:])
        points = [struct.unpack_from("<3f", data, 20+i*stride) for i in range(nv)]
        geometry.setBounds(QVector3D(*(min(p[i] for p in points) for i in range(3))),
                           QVector3D(*(max(p[i] for p in points) for i in range(3))))
        self.meshes[key] = geometry
        return geometry

    def table(self, key: str, rows: list[dict], revision: int):
        if key not in self.keys:
            return None
        if key not in self.tables:
            self.tables[key] = FloraInstances(self)
        self.tables[key].replace(rows, revision)
        return self.tables[key]
