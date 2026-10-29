import QtQuick
import QtQuick.Controls
import "." as Shared

// Native retained Text remains the normal renderer. The public text property
// is always the original plain/source string; styling never changes data used
// by copy actions, accessibility or model bindings. TextEdit exists only while
// the user explicitly selects or opens a text colour menu.
Item {
    id:root
    property string text:""
    property color color:Shared.GGTheme.text
    property string colorKey:""
    property bool colorCustomizable:true
    property int textFormat:Text.AutoText
    property int padding:0
    property int leftPadding:padding
    property int rightPadding:padding
    property int topPadding:padding
    property int bottomPadding:padding
    property alias font:display.font
    property alias horizontalAlignment:display.horizontalAlignment
    property alias verticalAlignment:display.verticalAlignment
    property alias wrapMode:display.wrapMode
    property alias elide:display.elide
    property alias maximumLineCount:display.maximumLineCount
    property alias lineHeight:display.lineHeight
    property alias lineHeightMode:display.lineHeightMode
    property alias fontSizeMode:display.fontSizeMode
    property alias minimumPixelSize:display.minimumPixelSize
    property alias minimumPointSize:display.minimumPointSize
    property alias style:display.style
    property alias styleColor:display.styleColor
    property alias renderType:display.renderType
    property alias textType:display.textFormat
    readonly property bool truncated:display.truncated
    readonly property int lineCount:display.lineCount
    readonly property real contentWidth:display.contentWidth
    readonly property real contentHeight:display.contentHeight
    readonly property real paintedWidth:display.paintedWidth
    readonly property real paintedHeight:display.paintedHeight
    readonly property int effectiveHorizontalAlignment:display.effectiveHorizontalAlignment
    readonly property var fontInfo:display.fontInfo
    readonly property int selectionStart:selectionLoader.item?selectionLoader.item.selectionStart:0
    readonly property int selectionEnd:selectionLoader.item?selectionLoader.item.selectionEnd:0
    readonly property string selectedText:selectionLoader.item?selectionLoader.item.selectedText:""
    readonly property bool selectionEditorActive:selectionLoader.active
    readonly property string effectiveColorKey: {
        if(colorKey.indexOf("ui.type.")===0)return colorKey
        var scopes=[]
        for(var ancestor=root.parent,depth=0;ancestor&&depth<48;ancestor=ancestor.parent,depth++){
            if(typeof ancestor.uiColorScope==="string"&&ancestor.uiColorScope.length>0)
                scopes.push(ancestor.uiColorScope)
        }
        if(scopes.length){
            // Source-site scopes only: no text, object names, addresses, row
            // indices or data enter this bounded presentation identity.
            var source=(colorKey||"text")+"\u0000"+scopes.join("\u0000"),first=2166136261,second=2246822519
            for(var index=0;index<source.length;index++){
                first=Math.imul(first^source.charCodeAt(index),16777619)>>>0
                second=Math.imul(second^source.charCodeAt(index),3266489917)>>>0
            }
            return "ui.slot."+first.toString(16)+"."+second.toString(16)
        }
        return colorKey||Shared.GGColorContext.keyFor(root)
    }
    readonly property bool customizationHierarchyAllowed: {
        if(!colorCustomizable||!visible||!Shared.GGColorContext.permittedFor(root))return false
        for(var ancestor=root;ancestor;ancestor=ancestor.parent){
            var name=String(ancestor.objectName||"")
            if(name==="walletCreationWizard"||name==="walletRecoveryPanel"||ancestor.ggColorExcluded===true)return false
        }
        return true
    }
    readonly property bool customizationAllowed: customizationHierarchyAllowed && text.length<=16384
    readonly property bool plainSource:textFormat===Text.PlainText||(textFormat===Text.AutoText&&!/<[A-Za-z][^>]*>/.test(text))
    readonly property bool rangeStylePresent: customizationHierarchyAllowed && Shared.GGColorContext.hasRangeStyle(effectiveColorKey)
    readonly property bool hasCustomRanges: {
        Shared.GGColorContext.revision
        return rangeStylePresent&&customizationAllowed&&plainSource&&Shared.GGColorContext.hasRanges(effectiveColorKey,text)
    }
    readonly property color effectiveColor: {
        Shared.GGColorContext.revision
        return customizationAllowed?Shared.GGColorContext.colorFor(effectiveColorKey,color):color
    }
    property bool showingSelection:false
    property int selectionPixelSize:-1
    // Keep a control's native press/release path on the control itself. A
    // left-button handler on its contentItem would intercept ordinary clicks.
    readonly property Item interactionScope: {
        // Captions can sit inside an Item/Row used by a delegate's contentItem.
        // Keep the press handler on the nearest actual clickable control, not
        // on an intermediate caption container or a distant window signal.
        for(var ancestor=root.parent,depth=0;ancestor&&depth<48;ancestor=ancestor.parent,depth++){
            var control=typeof ancestor.pressed==="boolean"||typeof ancestor.down==="boolean"
                ||(typeof ancestor.uiColorScope==="string"&&ancestor.uiColorScope.length>0)
            var combo=typeof ancestor.activated==="function"&&typeof ancestor.popup!=="undefined"
            if(combo||(control&&typeof ancestor.clicked==="function"))return ancestor
        }
        return root
    }
    implicitWidth:display.implicitWidth+leftPadding+rightPadding
    implicitHeight:display.implicitHeight+topPadding+bottomPadding
    baselineOffset:display.baselineOffset+topPadding
    Accessible.role:Accessible.StaticText
    Accessible.name:text
    signal linkActivated(string link)
    signal linkHovered(string link)

    function ensureSelection(){
        if(!customizationAllowed||!plainSource)return null
        var old=Shared.GGColorContext.selectionOwner
        if(old&&old!==root&&typeof old.finishColorSelection==="function")old.finishColorSelection()
        Shared.GGColorContext.selectionOwner=root
        selectionLoader.active=true
        if(selectionLoader.item&&selectionPixelSize<0&&display.fontInfo.pixelSize<=0
                &&display.fontSizeMode!==Text.FixedSize&&display.wrapMode===Text.NoWrap)
            selectionLoader.item.calibrateFittedFont()
        return selectionLoader.item
    }
    function positionAt(px,py){
        var editor=ensureSelection()
        return editor?editor.positionAt(px-leftPadding,py-topPadding):0
    }
    function select(start,end){
        var editor=ensureSelection()
        if(editor){editor.select(start,end);showingSelection=start!==end}
    }
    function selectAll(){select(0,text.length)}
    function deselect(){if(selectionLoader.item)selectionLoader.item.deselect();showingSelection=false}
    function finishColorSelection(){
        showingSelection=false;selectionLoader.active=false;selectionPixelSize=-1
        if(Shared.GGColorContext.selectionOwner===root)Shared.GGColorContext.selectionOwner=null
    }
    function linkAt(px,py){return display.linkAt(px-leftPadding,py-topPadding)}
    function gesturePosition(point){
        var local=interactionScope===root?point:root.mapFromItem(interactionScope,point.x,point.y)
        return positionAt(local.x,local.y)
    }
    function selectionFont(pixelOverride){
        var info=display.fontInfo
        var pixels=typeof pixelOverride==="number"&&pixelOverride>0?pixelOverride
            :selectionPixelSize>0?selectionPixelSize
            :info.pixelSize>0?info.pixelSize:root.font.pixelSize>0?root.font.pixelSize:12
        return Qt.font({family:info.family||root.font.family,pixelSize:pixels,
            weight:root.font.weight,italic:root.font.italic,underline:root.font.underline,
            strikeout:root.font.strikeout,capitalization:root.font.capitalization,
            letterSpacing:root.font.letterSpacing,wordSpacing:root.font.wordSpacing,
            kerning:root.font.kerning,hintingPreference:root.font.hintingPreference,
            preferShaping:root.font.preferShaping})
    }
    function openColorMenu(px,py){
        if(!customizationAllowed)return
        var chosen=plainSource&&selectionStart!==selectionEnd
        var range=!plainSource?[-1,-1]:chosen?[selectionStart,selectionEnd]:Shared.GGColorContext.wordRange(text,positionAt(px,py))
        var point=Shared.GGColorContext.hostOverlay?root.mapToItem(Shared.GGColorContext.hostOverlay,px,py):root.mapToItem(null,px,py)
        Shared.GGColorContext.openFor(root,effectiveColorKey,text,range[0],range[1],point.x,point.y,chosen)
    }
    onTextChanged:finishColorSelection()
    onVisibleChanged:if(!visible)finishColorSelection()
    onColorCustomizableChanged:if(!colorCustomizable)finishColorSelection()
    Component.onDestruction:finishColorSelection()

    Text {
        id:display;objectName:"ggNativeText"
        x:root.leftPadding;y:root.topPadding
        width:Math.max(0,root.width-root.leftPadding-root.rightPadding)
        height:Math.max(0,root.height-root.topPadding-root.bottomPadding)
        visible:!root.showingSelection
        color:root.effectiveColor
        text: {
            Shared.GGColorContext.revision
            return root.hasCustomRanges?Shared.GGColorContext.formatted(root.effectiveColorKey,root.text):root.text
        }
        textFormat:root.hasCustomRanges?Text.StyledText:root.textFormat
        onLinkActivated:function(link){root.linkActivated(link)}
        onLinkHovered:function(link){root.linkHovered(link)}
    }
    Loader {
        id:selectionLoader
        x:root.leftPadding;y:root.topPadding
        width:Math.max(0,root.width-root.leftPadding-root.rightPadding)
        height:Math.max(0,root.height-root.topPadding-root.bottomPadding)
        active:false
        sourceComponent:TextEdit {
            id:selectionEditor
            objectName:"ggTransientTextSelection"
            visible:root.showingSelection
            readOnly:true;selectByMouse:false;activeFocusOnPress:false
            text:root.text;textFormat:TextEdit.PlainText
            color:root.effectiveColor;font:root.selectionFont()
            wrapMode:display.wrapMode
            horizontalAlignment:display.horizontalAlignment
            verticalAlignment:display.verticalAlignment
            renderType:display.renderType
            selectionColor:Shared.GGTheme.line
            selectedTextColor:Shared.GGTheme.bright
            clip:true
            property int probePixel:1
            readonly property real calibratedAdvance:fitMetrics.advanceWidth
            TextMetrics {id:fitMetrics;text:root.text;font:root.selectionFont(selectionEditor.probePixel)}
            function calibrateFittedFont(){
                // Some software renderers leave Text.fontInfo unpopulated.
                // Match the already rendered single-line advance with at most
                // sixteen native metric probes; never poll or create a second
                // document. This is a bounded fallback, not fontInfo evidence.
                var low=Math.max(1,display.minimumPixelSize),high=Math.max(low,Math.min(65535,root.font.pixelSize>0?root.font.pixelSize:Math.ceil(root.font.pointSize*96/72)))
                var best=low,bestDifference=Number.POSITIVE_INFINITY,targetWidth=display.contentWidth
                for(var probes=0;probes<16&&low<=high;probes++){
                    var candidate=Math.floor((low+high)/2);probePixel=candidate
                    var width=fitMetrics.advanceWidth,difference=Math.abs(width-targetWidth)
                    if(difference<bestDifference){bestDifference=difference;best=candidate}
                    if(width<targetWidth)low=candidate+1;else high=candidate-1
                }
                probePixel=best;root.selectionPixelSize=best
                font=root.selectionFont(best)
            }
        }
    }
    DragHandler {
        id:selector
        objectName:"ggTextDragSelector"
        parent:root.interactionScope
        target:null
        acceptedButtons:Qt.LeftButton
        enabled:root.customizationAllowed&&root.plainSource
        grabPermissions:PointerHandler.CanTakeOverFromAnything|PointerHandler.ApprovesTakeOverByAnything
        onActiveChanged: {
            if(active){
                var start=root.gesturePosition(centroid.pressPosition)
                root.select(start,root.gesturePosition(centroid.position))
                if(selectionLoader.item)selectionLoader.item.forceActiveFocus()
            }
        }
        onCentroidChanged:if(active)root.select(root.gesturePosition(centroid.pressPosition),root.gesturePosition(centroid.position))
    }
    TapHandler {
        acceptedButtons:Qt.RightButton
        enabled:root.customizationAllowed
        onTapped:function(point,button){root.openColorMenu(point.position.x,point.position.y)}
    }
}
