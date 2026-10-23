"""GPU proof: opaque objects and additive FX disappear into the same horizon."""
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
    particles=ParticleBatchGeometry()
    particles.update([dict(x=1.4,y=0,z=0,kind='FLAME',size=.6,color='#ffda77',opacity=1),
        dict(x=0,y=0,z=0,kind='LIGHT_BEACON',size=.3,color='#39ff91',opacity=1,through_fog=True)])
    failures=[];captures=[]
    with tempfile.TemporaryDirectory(prefix='gg-fog-gpu-') as folder:
        directory=Path(folder);qml=directory/'check.qml'
        qml.write_text('''import QtQuick
import QtQuick.Window
import QtQuick3D
import "'''+(ROOT/'qml/components').as_uri()+'''"
Window { id:window; width:600; height:400; visible:true
 property var particleGeometry; property bool testFog:false;property bool occluder:false
 View3D { anchors.fill:parent
  environment:SceneEnvironment {
   clearColor:"#244050"; backgroundMode:SceneEnvironment.Color
   fog:Fog { enabled:window.testFog; density:1; color:"#244050"
             depthEnabled:true; depthNear:3; depthFar:5 }
  }
  PerspectiveCamera { position:Qt.vector3d(0,0,7); clipNear:.1; clipFar:100 }
  DirectionalLight { eulerRotation:Qt.vector3d(-25,-10,0);brightness:1 }
  Model { source:"#Cube"; position:Qt.vector3d(-1.4,0,0);scale:Qt.vector3d(.012,.012,.012)
          materials:PrincipledMaterial { baseColor:"#ef4949";roughness:1 } }
  Model { visible:window.occluder; source:"#Cube";position:Qt.vector3d(0,0,1)
          scale:Qt.vector3d(.012,.012,.012)
          materials:PrincipledMaterial {baseColor:"#244050";roughness:1} }
  Model { geometry:window.particleGeometry
   materials:AdventureFxMaterial { additive:true;uCameraPosition:Qt.vector3d(0,0,7)
       uFogNear:window.testFog ? 3 : 1000;uFogFar:window.testFog ? 5 : 1001;uBeaconFar:10 }
  }
 }
}''')
        engine.setInitialProperties({'particleGeometry':particles.geometry})
        engine.load(QUrl.fromLocalFile(str(qml)));assert engine.rootObjects()
        window=engine.rootObjects()[0]
        def capture(name,callback):
            result=game_client_main.capture_window_async(window,directory/(name+'.png'))
            captures.append(result);result.ready.connect(callback)
        def hide():
            window.setProperty('testFog',True)
            QTimer.singleShot(450,lambda:capture('fog',occlude))
        def occlude():
            window.setProperty('occluder',True)
            QTimer.singleShot(450,lambda:capture('occluded',app.quit))
        QTimer.singleShot(500,lambda:capture('clear',hide))
        QTimer.singleShot(5000,app.quit);app.exec()
        clear=Image.open(directory/'clear.png').convert('RGB')
        fog=Image.open(directory/'fog.png').convert('RGB')
        background=fog.getpixel((10,10))
        for roi in ((90,130,260,270),(340,130,510,270)):
            assert ImageChops.difference(clear,fog).crop(roi).getbbox(),'Test object missing'
            error=max(max(abs(c-background[i]) for i,c in enumerate(pixel))
                      for pixel in fog.crop(roi).get_flattened_data())
            assert error<=3,(roi,error,background,'Cutoff remains visible through fog')
        center=fog.getpixel((300,200))
        assert center[1]-background[1]>25,'Beacon did not remain visible inside full fog'
        occluded=Image.open(directory/'occluded.png').convert('RGB')
        assert max(abs(c-background[i]) for i,c in enumerate(occluded.getpixel((300,200))))<=3,'Beacon shines through an opaque obstacle'
        print('FOG_GPU_CUTOFF=PASS opaque/normal FX hidden; beacon visible in fog and depth-occluded')


if __name__=='__main__':main()
