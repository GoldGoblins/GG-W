import QtQuick
import QtQuick.Controls
import "." as Shared

Popup {
    id: root
    objectName: "ggColorPopup"
    property string targetKey: ""
    property string targetText: ""
    property string targetLabel: ""
    property string fallbackColor: "#d8dee9"
    property int rangeStart: -1
    property int rangeEnd: -1
    property bool selectedRange: false
    property var selectionTarget: null
    property bool showDeadlineEditor: false
    readonly property bool percentageCapable: !!selectionTarget && selectionTarget.percentageCapable===true
    readonly property string scaleMode: Shared.GGColorContext.scaleFor(targetKey,"solid")
    readonly property bool hasRange: rangeStart>=0 && rangeEnd>rangeStart
    readonly property var palette: Shared.GGTheme.swatches(64)
    readonly property string currentColor: selectedColor()
    width: Math.max(232,Math.min(400,parent ? parent.width-16 : 400))
    padding: 10
    height: contentColumn.implicitHeight+20
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onHeightChanged:if(visible && parent)y=Math.max(8,Math.min(y,parent.height-height-8))
    background: Rectangle {color:Shared.GGTheme.panel;border.width:1;border.color:Shared.GGTheme.line;radius:0}
    function openTarget(key,text,start,end,fallback,selected,sceneX,sceneY) {
        targetKey=key;targetText=text;rangeStart=start;rangeEnd=end;fallbackColor=fallback;selectedRange=selected
        wholeType.checked=!hasRange
        showDeadlineEditor=false
        var now=new Date(),pad=function(value){return String(value).padStart(2,"0")}
        deadlineDate.text=now.getFullYear()+"-"+pad(now.getMonth()+1)+"-"+pad(now.getDate())
        deadlineTime.text=pad(now.getHours())+":"+pad(now.getMinutes())+":"+pad(now.getSeconds())
        deadlineError.text=""
        x=Math.max(8,Math.min(sceneX,(parent ? parent.width : 416)-width-8))
        y=Math.max(8,Math.min(sceneY,(parent ? parent.height : height+16)-height-8))
        open()
    }
    function choose(color) {
        if(Shared.GGColorContext.choose(targetKey,targetText,rangeStart,rangeEnd,color,wholeType.checked))close()
    }
    function resetTarget() {
        if(Shared.GGColorContext.reset(targetKey))close()
    }
    function selectedColor() {
        var style=Shared.GGColorContext.styleFor(targetKey,targetText)
        if(hasRange && !wholeType.checked) {
            for(var index=0;index<style.ranges.length;index++)if(style.ranges[index].start<=rangeStart && style.ranges[index].end>=rangeEnd)return String(style.ranges[index].color).toLowerCase()
        }
        return String(style.color || fallbackColor).toLowerCase()
    }
    function darkInk(value) {
        var r=parseInt(value.slice(1,3),16),g=parseInt(value.slice(3,5),16),b=parseInt(value.slice(5,7),16)
        return (r*299+g*587+b*114)>145000
    }
    function saveDeadline() {
        var date=/^(\d{4})-(\d{2})-(\d{2})$/.exec(deadlineDate.text)
        var time=/^(\d{2}):(\d{2}):(\d{2})$/.exec(deadlineTime.text)
        if(!date || !time){deadlineError.text="Ange datum och HH:mm:ss.";return false}
        var year=Number(date[1]),month=Number(date[2]),day=Number(date[3]),hour=Number(time[1]),minute=Number(time[2]),second=Number(time[3])
        var end=new Date(0);end.setFullYear(year,month-1,day);end.setHours(hour,minute,second,0)
        var start=Date.now(),value=end.getTime()
        if(year<1970 || end.getFullYear()!==year || end.getMonth()!==month-1 || end.getDate()!==day || end.getHours()!==hour || end.getMinutes()!==minute || end.getSeconds()!==second || !isFinite(value) || value<=start){deadlineError.text="Välj en giltig framtida tid.";return false}
        if(Shared.GGColorContext.setDeadline(targetKey,start,value)){root.close();return true}
        deadlineError.text="Kunde inte spara tidsgränsen.";return false
    }
    Column {
        id:contentColumn
        property bool colorCustomizationExcluded: true
        width:root.availableWidth
        spacing:8
        Text {text:root.targetLabel || (root.hasRange ? root.selectedRange ? "FÄRG FÖR MARKERADE TECKEN" : "FÄRG FÖR ORDET" : "FÄRG FÖR UI-ELEMENT");color:Shared.GGTheme.bright;font.family:"monospace";font.pixelSize:11;font.bold:true}
        Text {text:"64 färger · ändringen sparas lokalt";color:Shared.GGTheme.dim;font.family:"monospace";font.pixelSize:10}
        Row {
            width:parent.width;spacing:4;visible:root.percentageCapable;height:visible?26:0
            Repeater {
                model:[{key:"solid",title:"Fast färg"},{key:"risk",title:"Belastning"},{key:"progress",title:"Framsteg"}]
                delegate:GgButton {
                    required property var modelData
                    objectName:"uiColorScale_"+modelData.key
                    width:(parent.width-8)/3;height:26;text:modelData.title
                    checked:root.scaleMode===modelData.key
                    onClicked:if(Shared.GGColorContext.setScale(root.targetKey,modelData.key))root.close()
                }
            }
        }
        Grid {
            id:swatchGrid
            width:parent.width
            columns:8;columnSpacing:4;rowSpacing:4
            Repeater {
                id:swatchRepeater
                model:root.palette
                delegate:Item {
                    id:cell
                    required property int index
                    required property string modelData
                    objectName:"uiColorSwatch"
                    width:(swatchGrid.width-7*4)/8;height:24
                    activeFocusOnTab:true
                    Rectangle {anchors.fill:parent;color:cell.modelData;border.width:1;border.color:cell.activeFocus?Shared.GGTheme.bright:Shared.GGTheme.line}
                    Text {anchors.centerIn:parent;text:root.currentColor===cell.modelData?"✓":"";font.family:"monospace";font.pixelSize:12;color:root.darkInk(cell.modelData)?"#000000":"#ffffff"}
                    TapHandler {onTapped:root.choose(cell.modelData)}
                    HoverHandler {id:hover}
                    ToolTip.visible:hover.hovered;ToolTip.delay:300;ToolTip.text:cell.modelData
                    Accessible.role:Accessible.Button;Accessible.name:"Välj färg "+cell.modelData
                    Keys.onPressed:function(event) {
                        if([Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space].indexOf(event.key)>=0){root.choose(cell.modelData);event.accepted=true}
                        else if([Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down].indexOf(event.key)>=0){
                            var offset=event.key===Qt.Key_Left?-1:event.key===Qt.Key_Right?1:event.key===Qt.Key_Up?-8:8
                            var next=swatchRepeater.itemAt((cell.index+offset+64)%64);if(next)next.forceActiveFocus();event.accepted=true
                        }
                    }
                }
            }
        }
        CheckBox {
            id:wholeType;objectName:"uiColorWholeType";visible:root.hasRange;height:visible?26:0
            text:"Hela informationstypen";font.family:"monospace";font.pixelSize:10
            contentItem:Text {text:wholeType.text;color:Shared.GGTheme.text;font:wholeType.font;leftPadding:wholeType.indicator.width+wholeType.spacing;verticalAlignment:Text.AlignVCenter}
        }
        GgButton {
            objectName:"uiColorDeadlineOption";width:parent.width;height:26;text:"Tidsgräns / deadline…"
            checked:root.showDeadlineEditor
            onClicked:{wholeType.checked=true;root.showDeadlineEditor=!root.showDeadlineEditor}
        }
        Column {
            id:deadlineEditor;visible:root.showDeadlineEditor;width:parent.width;spacing:5
            Text {text:"Lokal tid · blå/grön → röd vid tidsgränsen";color:Shared.GGTheme.muted;font.family:"monospace";font.pixelSize:9}
            Row {
                width:parent.width;spacing:5
                TextField {id:deadlineDate;objectName:"uiColorDeadlineDate";width:(parent.width-10)*0.48;height:27;font.family:"monospace";font.pixelSize:11;color:Shared.GGTheme.text;placeholderText:"ÅÅÅÅ-MM-DD";background:Rectangle{color:Shared.GGTheme.canvas;border.width:1;border.color:Shared.GGTheme.line}}
                TextField {id:deadlineTime;objectName:"uiColorDeadlineTime";width:(parent.width-10)*0.32;height:27;font.family:"monospace";font.pixelSize:11;color:Shared.GGTheme.text;placeholderText:"HH:mm:ss";background:Rectangle{color:Shared.GGTheme.canvas;border.width:1;border.color:Shared.GGTheme.line}}
                GgButton {objectName:"uiColorSaveDeadline";width:(parent.width-10)*0.20;height:27;text:"Spara";onClicked:root.saveDeadline()}
            }
            Text {id:deadlineError;width:parent.width;visible:text.length>0;color:Shared.GGTheme.negative;font.family:"monospace";font.pixelSize:10}
        }
        Row {
            width:parent.width;spacing:6
            GgButton {objectName:"uiColorReset";width:(parent.width-6)/2;height:26;text:"Återställ";onClicked:root.resetTarget()}
            GgButton {width:(parent.width-6)/2;height:26;text:"Stäng";onClicked:root.close()}
        }
        Text {width:parent.width;visible:Shared.GGColorContext.backend && Shared.GGColorContext.backend.error.length>0;text:"Kunde inte spara färgen.";color:Shared.GGTheme.negative;font.family:"monospace";font.pixelSize:10}
    }
    onClosed: {
        if(selectionTarget && typeof selectionTarget.finishColorSelection==="function")selectionTarget.finishColorSelection()
        selectionTarget=null;targetText="";rangeStart=-1;rangeEnd=-1
    }
}
