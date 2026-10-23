"""GPU regression: metre-based enchant falloff cannot recolour distant scenery."""
import math,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import game_client_main
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PIL import Image,ImageChops


def main():
    app=QGuiApplication([]);engine=QQmlApplicationEngine();captures=[]
    roots=[];engine.objectCreated.connect(lambda obj,_:roots.append(obj))
    with tempfile.TemporaryDirectory(prefix='gg-light-radius-') as folder:
        directory=Path(folder);qml=directory/'check.qml'
        qml.write_text('''import QtQuick
import QtQuick.Window
import QtQuick3D
import "'''+(ROOT/'qml/components/engine/WorldFx.js').as_uri()+'''" as WorldFx
Window {id:window;width:600;height:400;visible:true;property bool lightOn:false
 View3D {anchors.fill:parent
  environment:SceneEnvironment {clearColor:"#102030";backgroundMode:SceneEnvironment.Color}
  PerspectiveCamera {position:Qt.vector3d(0,0,12);fieldOfView:45
   fieldOfViewOrientation:PerspectiveCamera.Vertical;clipNear:.1;clipFar:100}
  DirectionalLight {brightness:.4}
  PointLight {visible:window.lightOn;position:Qt.vector3d(0,0,.8);brightness:1.1
   color:"#ff30cc";constantFade:1;linearFade:0
   quadraticFade:WorldFx.pointLightQuadraticFade(WorldFx.LIGHT_PROFILES.ENCHANT[0])}
  Repeater3D {model:[0,3,6]
   delegate:Model {required property var modelData;source:"#Cube"
    position:Qt.vector3d(modelData,0,0);scale:Qt.vector3d(.006,.006,.006)
    materials:PrincipledMaterial {baseColor:"#808080";roughness:1;metalness:0}
   }
  }
 }
}''')
        engine.load(QUrl.fromLocalFile(str(qml)));assert engine.rootObjects()
        window=roots[0]
        def capture(name,callback):
            result=game_client_main.capture_window_async(window,directory/(name+'.png'))
            captures.append(result);result.ready.connect(callback)
        def light():
            window.setProperty('lightOn',True)
            QTimer.singleShot(300,lambda:capture('on',app.quit))
        QTimer.singleShot(500,lambda:capture('off',light));QTimer.singleShot(5000,app.quit)
        app.exec()
        off=Image.open(directory/'off.png').convert('RGB');on=Image.open(directory/'on.png').convert('RGB')
        delta=ImageChops.difference(off,on);scale=400/(2*math.tan(math.radians(22.5))*11.7)
        def maximum(x):
            px=round(300+x*scale)
            return max(max(pixel) for pixel in delta.crop((px-4,196,px+4,204)).get_flattened_data())
        near=maximum(0);far=[maximum(6)]
        assert near>=8,('Nearby enchant illumination missing',near)
        assert max(far)<=3,('Enchant recolours distant scenery',far)
        print('LIGHT_RADIUS_GPU=PASS local illumination; 6m scenery changes <=3/255',near,far)


if __name__=='__main__':main()
