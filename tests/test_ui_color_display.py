"""Owned real-QML display selection; no user windows, wallet or app state."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]


def fixture(directory):
    sys.path.insert(0,str(ROOT))
    from PySide6.QtCore import QObject,QPoint,QUrl,Qt
    from PySide6.QtGui import QFont
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QSGRendererInterface
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from backend.ui_color_customization import UiColorController
    app=QApplication([])
    if os.name=='nt':QFont.insertSubstitution('monospace','Consolas')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'monospace',12))
    colors=UiColorController(path=Path(directory)/'colors.json')
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('fixtureColors',colors)
    engine.rootContext().setContextProperty('nativeProbe',os.environ.get('GG_COLOR_NATIVE')=='1')
    warnings=[];engine.warnings.connect(lambda errors:warnings.extend(error.toString() for error in errors))
    source='''import QtQuick
import QtQuick.Controls
import "'''+(ROOT/'qml/components').as_uri()+'''" as GG
ApplicationWindow {
 id:window;visible:true;width:660;height:550
 flags:nativeProbe?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint):Qt.Window
 property int actions:0
 property int nativeActions:0
 Component.onCompleted:{GG.GGColorContext.backend=fixtureColors;GG.GGColorContext.hostOverlay=window.contentItem}
 GG.GGText {id:word;objectName:"colorWord";x:20;y:20;width:500;height:30;text:"SOL 12:34:56";textFormat:Text.PlainText;colorKey:"ui.fixture.clock";font.family:"monospace";font.pixelSize:18}
 GG.GGText {id:spacing;objectName:"colorSpacing";x:20;y:65;text:"AA   BB < & >";textFormat:Text.PlainText;colorKey:"ui.fixture.spacing";font.family:"monospace";font.pixelSize:18}
 GG.CryptoButton {objectName:"buttonA";property string uiColorScope:"ui.fixture.buttonA";x:20;y:110;width:260;height:38;text:"Förhandsgranska överföring";onClicked:window.actions++}
 GG.CryptoButton {objectName:"buttonB";property string uiColorScope:"ui.fixture.buttonB";x:310;y:110;width:260;height:38;text:"Förhandsgranska överföring";onClicked:window.actions++}
 Item {objectName:"walletCreationWizard";x:20;y:170;width:300;height:35
  GG.GGText {objectName:"privateLabel";width:300;height:30;text:"private fixture only";colorKey:"ui.fixture.blocked"}
 }
 GG.GGText {objectName:"dynamicWord";x:20;y:230;width:300;height:30;text:"12:34:56";textFormat:Text.PlainText;colorKey:"ui.fixture.dynamic";font.pixelSize:18}
 Button {objectName:"nativeButton";property string uiColorScope:"ui.fixture.nativeButton";x:20;y:290;width:260;height:36;text:"Vanlig knapp";onClicked:window.nativeActions++
  contentItem:GG.GGControlCaption {objectName:"nativeCaption"}
 }
 CheckBox {objectName:"nativeCheck";property string uiColorScope:"ui.fixture.nativeCheck";x:20;y:340;width:260;height:36;text:"Val med indikator";onClicked:window.nativeActions++
  contentItem:GG.GGControlCaption {objectName:"checkCaption";withIndicator:true;horizontalAlignment:Text.AlignLeft}
 }
 GG.GgButton {objectName:"goblinButton";property string uiColorScope:"ui.fixture.goblinButton";x:310;y:290;width:280;height:36;text:"Gemensam knapp";onClicked:window.actions++}
 Button {id:nestedButton;objectName:"nestedButton";property string uiColorScope:"ui.fixture.nestedButton";x:310;y:340;width:280;height:36;text:"Nestlad vanlig knapp";onClicked:window.nativeActions++
  contentItem:Item {
   GG.GGText {objectName:"nestedButtonCaption";anchors.fill:parent;text:nestedButton.text;font:nestedButton.font;verticalAlignment:Text.AlignVCenter;colorKey:"ui.fixture.nestedButtonCaption"}
  }
 }
 ItemDelegate {id:nestedDelegate;objectName:"nestedDelegate";property string uiColorScope:"ui.fixture.nestedDelegate";x:20;y:390;width:280;height:36;text:"Nestlad listkontroll";onClicked:window.nativeActions++
  contentItem:Item {
   Rectangle {x:0;y:10;width:8;height:8;color:"#ff0000"}
   GG.GGText {objectName:"nestedDelegateCaption";x:16;width:parent.width-16;height:parent.height;text:nestedDelegate.text;font:nestedDelegate.font;verticalAlignment:Text.AlignVCenter;colorKey:"ui.fixture.nestedDelegateCaption"}
  }
 }
 ComboBox {id:combo;objectName:"nativeCombo";property string uiColorScope:"ui.fixture.nativeCombo";x:310;y:390;width:280;height:36;model:["Första valet","Andra valet","Tredje valet"]
  contentItem:Item {
   GG.GGText {objectName:"comboCaption";anchors.fill:parent;text:combo.displayText;font:combo.font;verticalAlignment:Text.AlignVCenter;colorKey:"ui.fixture.comboCaption"}
  }
 }
 component Fact:Item {
  property string value:"Samma värde"
  property alias valueItem:factValue
  GG.GGText {id:factValue;anchors.fill:parent;text:parent.value;colorKey:"ui.fixture.reusable.value"}
 }
 component Card:Item {
  property alias valueItem:innerFact.valueItem
  Fact {id:innerFact;property string uiColorScope:"ui.fixture.sameInnerFact";anchors.fill:parent}
 }
 Card {objectName:"factCardA";property string uiColorScope:"ui.fixture.outerFactA";x:20;y:445;width:280;height:30}
 Card {objectName:"factCardB";property string uiColorScope:"ui.fixture.outerFactB";x:330;y:445;width:280;height:30}
 GG.GGText {objectName:"fittedValue";x:20;y:490;width:260;height:28;text:"31 529 284.463525 GGHB";textFormat:Text.PlainText;colorKey:"ui.fixture.fit";font.family:"monospace";font.pixelSize:32;minimumPixelSize:10;fontSizeMode:Text.Fit}
}
'''
    engine.loadData(source.encode('utf-8'),QUrl.fromLocalFile(str(Path(directory)/'fixture.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0]
    def named(name):
        result=window.findChild(QObject,name)
        assert result is not None,name
        return result
    def js(item,code):
        expr=QQmlExpression(qmlContext(item),item,code);value=expr.evaluate()
        assert not expr.hasError(),expr.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def settle():QTest.qWait(40);app.processEvents()
    def click(item,x,y,button=Qt.MouseButton.LeftButton):
        point=item.mapToScene(QPoint(x,y));QTest.mouseClick(window,button,Qt.KeyboardModifier.NoModifier,QPoint(round(point.x()),round(point.y())));settle()
    try:
        if os.name=='nt' and os.environ.get('GG_COLOR_NATIVE')=='1':
            window.lower();assert QTest.qWaitForWindowExposed(window,3000)
            assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
        settle()
        button=named('nativeButton');point=button.mapToScene(QPoint(100,15))
        QTest.mousePress(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(point.x()),round(point.y())))
        held=button.property('pressed');QTest.qWait(30)
        QTest.mouseRelease(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(point.x()),round(point.y())));settle()
        assert window.property('nativeActions')==1,('initial native action',window.property('nativeActions'),warnings,held)
        window.setProperty('nativeActions',0)
        word=named('colorWord');native=word.findChild(QObject,'ggNativeText')
        assert word.property('text')=='SOL 12:34:56'
        assert word.findChild(QObject,'ggTransientTextSelection') is None
        click(word,12,15,Qt.MouseButton.RightButton)
        assert js(word,'GG.GGColorContext.popup.visible')
        assert js(word,'GG.GGColorContext.popup.rangeStart')==0
        assert js(word,'GG.GGColorContext.popup.rangeEnd')==3
        chosen=list(colors._registry.colors)[0] if hasattr(colors,'_registry') else '#88c0d0'
        # Use the actual popup's swatch list rather than inventing a colour.
        chosen=js(word,'GG.GGColorContext.popup.palette[0]')
        js(word,'GG.GGColorContext.popup.choose('+json.dumps(chosen)+')');settle()
        assert word.property('text')=='SOL 12:34:56'
        style=json.loads(colors.styleFor('ui.fixture.clock','SOL 12:34:56'))
        assert len(style['ranges'])==1 and style['ranges'][0]['start']==0 and style['ranges'][0]['end']==3,style
        assert '<font' in native.property('text') and '</font>' in native.property('text')
        assert word.findChild(QObject,'ggTransientTextSelection') is None
        # Exact selected characters take precedence over the word at right-click.
        js(word,'select(4,6)');settle();assert word.property('selectedText')=='12'
        click(word,100,15,Qt.MouseButton.RightButton)
        assert js(word,'GG.GGColorContext.popup.rangeStart')==4
        assert js(word,'GG.GGColorContext.popup.rangeEnd')==6
        assert js(word,'GG.GGColorContext.popup.selectedRange')
        js(word,'GG.GGColorContext.popup.choose(GG.GGColorContext.popup.palette[1])');settle()
        assert word.property('text')=='SOL 12:34:56'
        assert any(r['start']==4 and r['end']==6 for r in json.loads(colors.styleFor('ui.fixture.clock','SOL 12:34:56'))['ranges'])
        # Styling must preserve multiple spaces, symbols, and implicit geometry.
        spacing=named('colorSpacing');before=spacing.property('implicitWidth')
        assert colors.setRangeColor('ui.fixture.spacing',spacing.property('text'),0,2,chosen)
        settle();assert abs(spacing.property('implicitWidth')-before)<1.5,(before,spacing.property('implicitWidth'))
        assert spacing.property('text')=='AA   BB < & >'
        dynamic=named('dynamicWord')
        assert colors.setRangeColor('ui.fixture.dynamic','12:34:56',0,2,chosen)
        dynamic.setProperty('text','23:59:59');settle()
        dynamic_style=json.loads(colors.styleFor('ui.fixture.dynamic','23:59:59'))
        assert any(span['start']==0 and span['end']==2 for span in dynamic_style['ranges'])
        assert '23' in dynamic.findChild(QObject,'ggNativeText').property('text')
        # The reusable CryptoButton's two call sites have independent keys.
        a=named('buttonA');b=named('buttonB')
        labels=[child for child in a.findChildren(QObject) if child.property('colorKey')=='ui.CryptoButton.1']
        assert labels,[(str(child),child.property('colorKey')) for child in a.findChildren(QObject)]
        label=labels[0]
        assert label.property('effectiveColorKey').startswith('ui.slot.')
        other=[child for child in b.findChildren(QObject) if child.property('colorKey')=='ui.CryptoButton.1'][0]
        assert other.property('effectiveColorKey')!=label.property('effectiveColorKey')
        click(label,30,10,Qt.MouseButton.RightButton)
        assert window.property('actions')==0
        assert js(window,'GG.GGColorContext.popup.visible')
        assert js(window,'GG.GGColorContext.popup.targetKey')==label.property('effectiveColorKey')
        js(window,'GG.GGColorContext.popup.close()');QTest.qWait(160);settle()
        # A real left drag selects without firing the underlying transfer button.
        start=label.mapToScene(QPoint(5,10));end=label.mapToScene(QPoint(115,10))
        QTest.mousePress(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(start.x()),round(start.y())))
        for step in range(1,9):
            x=start.x()+(end.x()-start.x())*step/8
            QTest.mouseMove(window,QPoint(round(x),round(start.y())),15)
        QTest.mouseRelease(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(end.x()),round(end.y())))
        settle();assert label.property('selectionEnd')>label.property('selectionStart'),(label.property('selectionStart'),label.property('selectionEnd'))
        assert window.property('actions')==0
        js(label,'finishColorSelection()')
        # Default Qt controls keep their action and indicator behavior while
        # using the very same selectable caption as migrated production sites.
        caption=named('nativeCaption');check_caption=named('checkCaption')
        assert caption.property('text')=='Vanlig knapp'
        assert check_caption.property('leftPadding')>0
        click(caption,30,15,Qt.MouseButton.RightButton)
        assert js(window,'GG.GGColorContext.popup.visible') and window.property('nativeActions')==0
        js(window,'GG.GGColorContext.popup.close()');QTest.qWait(200);settle()
        click(named('nativeButton'),100,15)
        assert window.property('nativeActions')==1,(window.property('nativeActions'),named('nativeButton').property('enabled'),named('nativeButton').property('pressed'),js(window,'GG.GGColorContext.popup.visible'))
        click(named('nativeCheck'),12,15)
        assert named('nativeCheck').property('checked') and window.property('nativeActions')==2
        goblin=named('goblinButton')
        goblin_label=[child for child in goblin.findChildren(QObject) if child.property('colorKey')=='ui.GgButton.1'][0]
        start=goblin_label.mapToScene(QPoint(3,8));end=goblin_label.mapToScene(QPoint(100,8))
        QTest.mousePress(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(start.x()),round(start.y())))
        for step in range(1,9):QTest.mouseMove(window,QPoint(round(start.x()+(end.x()-start.x())*step/8),round(start.y())),15)
        QTest.mouseRelease(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(end.x()),round(end.y())))
        settle();assert goblin_label.property('selectedText') and window.property('actions')==0
        js(goblin_label,'finishColorSelection()')
        click(goblin,140,18);assert window.property('actions')==1
        # An intermediate contentItem must not steal the native control's
        # normal press. Both Button and ItemDelegate use the nearest ancestor.
        for control_name,caption_name in (('nestedButton','nestedButtonCaption'),('nestedDelegate','nestedDelegateCaption')):
            control=named(control_name);nested_caption=named(caption_name)
            assert nested_caption.property('interactionScope') is control
            count=window.property('nativeActions')
            click(nested_caption,50,15)
            assert window.property('nativeActions')==count+1,(control_name,'normal click')
            start=nested_caption.mapToScene(QPoint(4,14));end=nested_caption.mapToScene(QPoint(125,14))
            QTest.mousePress(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(start.x()),round(start.y())))
            for step in range(1,9):QTest.mouseMove(window,QPoint(round(start.x()+(end.x()-start.x())*step/8),round(start.y())),15)
            QTest.mouseRelease(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(end.x()),round(end.y())))
            settle();assert nested_caption.property('selectedText'),(control_name,'selection')
            assert window.property('nativeActions')==count+1,(control_name,'drag fired action')
            js(nested_caption,'finishColorSelection()')
        # ComboBox exposes activated/popup rather than clicked; its actual
        # caption must still open the dropdown, and an item must select.
        combo_caption=named('comboCaption');combo=named('nativeCombo')
        assert combo_caption.property('interactionScope') is combo
        click(combo_caption,55,15);assert js(combo,'popup.visible')
        QTest.qWait(100)
        option=js(combo,'popup.contentItem.itemAtIndex(1)')
        if hasattr(option,'toQObject'):option=option.toQObject()
        assert option is not None
        click(option,max(8,round(option.width()/2)),max(8,round(option.height()/2)))
        assert combo.property('currentIndex')==1 and not js(combo,'popup.visible')
        # Two outer reusable widget instances have identical inner scopes and
        # display source keys. All ancestor source scopes must distinguish them.
        first=[child for child in named('factCardA').findChildren(QObject) if child.property('colorKey')=='ui.fixture.reusable.value'][0]
        second=[child for child in named('factCardB').findChildren(QObject) if child.property('colorKey')=='ui.fixture.reusable.value'][0]
        assert first.property('effectiveColorKey')!=second.property('effectiveColorKey')
        assert len(first.property('effectiveColorKey'))<256
        assert colors.setColor(first.property('effectiveColorKey'),chosen)
        settle();assert first.property('effectiveColor').name()==chosen
        assert second.property('effectiveColor').name()!=chosen
        js(first,'select(0,3)');settle();assert first.property('selectionEditorActive')
        js(second,'select(0,3)');settle()
        assert not first.property('selectionEditorActive') and second.property('selectionEditorActive')
        js(second,'finishColorSelection()');settle()
        assert not first.property('selectionEditorActive') and not second.property('selectionEditorActive')
        assert js(window,'GG.GGColorContext.selectionOwner===null')
        fitted=named('fittedValue');window.grabWindow();settle();fitted_pixels=js(fitted,'fontInfo.pixelSize')
        js(fitted,'select(0,2)');settle()
        fitted_editor=fitted.findChild(QObject,'ggTransientTextSelection')
        if fitted_pixels>0:
            assert fitted_pixels<32
            assert fitted_editor.property('font').pixelSize()==fitted_pixels
        else:
            assert 0<fitted_editor.property('font').pixelSize()<32
            assert abs(fitted_editor.property('contentWidth')-fitted.property('contentWidth'))<=16,('bounded software font fallback',fitted_editor.property('contentWidth'),fitted.property('contentWidth'))
        assert fitted.property('selectedText')=='31' and fitted.property('text')=='31 529 284.463525 GGHB'
        js(fitted,'finishColorSelection()');settle()
        private=named('privateLabel');assert private.property('customizationAllowed') is False
        js(private,'openColorMenu(10,10)');settle();assert not js(word,'GG.GGColorContext.popup.visible')
        saved=(Path(directory)/'colors.json').read_text(encoding='utf-8')
        assert 'SOL' not in saved and 'private fixture only' not in saved and '12:34:56' not in saved
        output=Path(os.environ.get('GG_COLOR_CAPTURE_ROOT',str(ROOT/'.runtime/ui-color-display-v14')))
        output=output/('native' if os.environ.get('GG_COLOR_NATIVE')=='1' else 'software')
        output.mkdir(parents=True,exist_ok=True)
        js(word,'select(4,6)');click(word,80,15,Qt.MouseButton.RightButton);QTest.qWait(80)
        assert window.grabWindow().save(str(output/'selected-characters-palette.png'))
        js(window,'GG.GGColorContext.popup.close()');settle()
        assert not warnings,sorted(set(warnings))
        result={'status':'PASS','native_qml':True,'right_click_word':True,'selected_characters':True,'plain_text_preserved':True,'spaces_preserved':True,'slot_survives_clock_value_change':True,'selection_fires_no_action':True,'native_button_and_checkbox_actions_preserved':True,'nested_button_and_delegate_actions_preserved':True,'combobox_caption_opens_and_item_selects':True,'reusable_nested_fields_independent':True,'one_transient_selection_editor':True,'fitted_font_selection_matches_rendered_size':True,'lazy_selection':True,'private_excluded':True,'display_text_not_persisted':True,'warnings':0,'renderer':'Direct3D11' if os.environ.get('GG_COLOR_NATIVE')=='1' else 'software'}
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result))
    finally:
        window.close();engine.deleteLater();app.processEvents()


class DisplayTests(unittest.TestCase):
    def run_fixture(self,native):
        with tempfile.TemporaryDirectory(prefix='gg-ui-color-display-') as directory:
            env=os.environ.copy();env.update(QT_QUICK_CONTROLS_STYLE='Basic',PYTHONDONTWRITEBYTECODE='1')
            if native:env['GG_COLOR_NATIVE']='1';env.pop('QT_QPA_PLATFORM',None);env.pop('QT_QUICK_BACKEND',None)
            else:env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
            result=subprocess.run([sys.executable,'-X','utf8','-B',__file__,'--fixture',directory],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('"status": "PASS"',result.stdout)
    def test_software_native_text_selection(self):self.run_fixture(False)
    @unittest.skipUnless(os.name=='nt','Windows native renderer')
    def test_windows_native_text_selection(self):self.run_fixture(True)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fixture':fixture(sys.argv[2])
    else:unittest.main()
