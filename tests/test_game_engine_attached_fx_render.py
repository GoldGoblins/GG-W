"""GPU proof: two enchant clouds follow animated hierarchy without FX uploads."""
import math,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import game_client_main
from backend.game_engine_geometry import ParticleBatchGeometry
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PIL import Image


def main():
    app=QGuiApplication([]);engine=QQmlApplicationEngine();particles=ParticleBatchGeometry()
    rows=[dict(kind='ENCHANT',x=0,y=.65,z=0,size=.2,color=color,opacity=.8,
               attachment_local=True,attachment_index=index,attachment_bounds=[0,0,0])
          for index,color in enumerate(('#ff39dd','#39ffd9'))]
    particles.update(rows);original=bytes(particles.geometry.vertexData());captures=[]
    with tempfile.TemporaryDirectory(prefix='gg-attached-fx-') as folder:
        directory=Path(folder);qml=directory/'check.qml'
        qml.write_text('''import QtQuick
import QtQuick.Window
import QtQuick3D
import "'''+(ROOT/'qml/components').as_uri()+'''"
Window { id:window; width:600; height:400; visible:true
 property var particleGeometry;property bool moved:false
 View3D { anchors.fill:parent
  environment:SceneEnvironment { clearColor:"#102030";backgroundMode:SceneEnvironment.Color }
  PerspectiveCamera {position:Qt.vector3d(0,0,7);fieldOfView:45
                     fieldOfViewOrientation:PerspectiveCamera.Vertical;clipNear:.1;clipFar:100}
  Node {position:window.moved ? Qt.vector3d(.5,-.15,0) : Qt.vector3d(0,0,0)
   Node { id:mainHand;position:Qt.vector3d(-1,0,0)
          eulerRotation.z:window.moved ? -80 : 0 }
   Node { id:offHand;position:Qt.vector3d(1,0,0)
          eulerRotation.z:window.moved ? 110 : 0 }
  }
  Model {geometry:window.particleGeometry
   materials:AdventureFxMaterial {additive:true;uEnchantMatrix0:mainHand.sceneTransform
                                  uEnchantMatrix1:offHand.sceneTransform}
  }
 }
}''')
        engine.setInitialProperties({'particleGeometry':particles.geometry})
        engine.load(QUrl.fromLocalFile(str(qml)));assert engine.rootObjects()
        window=engine.rootObjects()[0]
        def capture(name,callback):
            result=game_client_main.capture_window_async(window,directory/(name+'.png'))
            captures.append(result);result.ready.connect(callback)
        def move():
            window.setProperty('moved',True)
            QTimer.singleShot(300,lambda:capture('moved',app.quit))
        QTimer.singleShot(500,lambda:capture('rest',move));QTimer.singleShot(5000,app.quit)
        app.exec()
        assert bytes(particles.geometry.vertexData())==original,'No CPU particle update is allowed in this test'
        scale=400/(2*math.tan(math.radians(22.5))*7)
        before=Image.open(directory/'rest.png').convert('RGB')
        after=Image.open(directory/'moved.png').convert('RGB')
        def pixel(image,x,y):return image.getpixel((round(300+x*scale),round(200-y*scale)))
        for index,(x,angle) in enumerate(((-1,-80),(1,110))):
            a=math.radians(angle);px=x+.5-math.sin(a)*.65;py=-.15+math.cos(a)*.65
            old=pixel(before,x,.65);new=pixel(after,px,py)
            assert old[index]>100 and new[index]>100,(index,old,new)
            assert max(pixel(after,x,.65))<60,'Cloud left behind at old world position'
        print('ATTACHED_FX_GPU=PASS both hands follow parent rotation/translation with frozen particle data')


if __name__=='__main__':main()
