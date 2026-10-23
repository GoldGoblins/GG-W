"""Real GPU check: a batch born empty must become visible after publication."""
import sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import game_client_main
from backend.game_engine_geometry import ParticleBatchGeometry
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PIL import Image,ImageChops

def main():
    app=QGuiApplication([]);engine=QQmlApplicationEngine()
    alpha=ParticleBatchGeometry();additive=ParticleBatchGeometry()
    with tempfile.TemporaryDirectory(prefix='gg-fx-gpu-') as folder:
        directory=Path(folder);qml=directory/'check.qml'
        qml.write_text('''import QtQuick
import QtQuick.Window
import QtQuick3D
import "'''+(ROOT/'qml/components').as_uri()+'''"
Window { id:window; width:600; height:400; visible:true
 property var alphaGeometry; property var additiveGeometry
 View3D { anchors.fill:parent
  environment:SceneEnvironment { clearColor:"#102030"; backgroundMode:SceneEnvironment.Color }
  PerspectiveCamera { position:Qt.vector3d(0,0,7); clipNear:.1; clipFar:100 }
  Model { geometry:window.alphaGeometry; materials:AdventureFxMaterial { uEnergy:.72 } }
  Model { geometry:window.additiveGeometry; materials:AdventureFxMaterial { additive:true } }
 }
}''')
        engine.setInitialProperties({'alphaGeometry':alpha.geometry,'additiveGeometry':additive.geometry})
        engine.load(QUrl.fromLocalFile(str(qml)));assert engine.rootObjects()
        window=engine.rootObjects()[0];captures=[]
        def capture(name,callback):
            result=game_client_main.capture_window_async(window,directory/(name+'.png'))
            captures.append(result);result.ready.connect(callback)
        def publish():
            alpha.update([dict(x=-1.5,y=0,z=0,kind='SMOKE',size=.8,color='#8a8380',opacity=.6)])
            additive.update([dict(x=1.5,y=0,z=0,kind='FLAME',size=.8,color='#ff9e39',opacity=1)])
            QTimer.singleShot(300,lambda:capture('after',app.quit))
        QTimer.singleShot(300,lambda:capture('before',publish))
        QTimer.singleShot(4000,app.quit)
        app.exec()
        before=Image.open(directory/'before.png').convert('RGB');after=Image.open(directory/'after.png').convert('RGB')
        difference=ImageChops.difference(before,after)
        # Both independent materials must produce actual pixels, not just counts.
        assert difference.crop((100,80,290,320)).getbbox(),'Alpha batch remained invisible'
        assert difference.crop((310,80,500,320)).getbbox(),'Additive batch remained invisible'
        assert sum(max(pixel)>25 for pixel in difference.get_flattened_data())>1000,'FX output too small'
        print('FX_GPU_PUBLICATION=PASS alpha/additive visible after empty-batch update')

if __name__=='__main__':main()
