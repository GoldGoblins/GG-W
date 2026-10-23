pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    objectName: "gameWorldFeedback"
    required property var runtime
    required property var worldSurface
    property bool paneLive: true
    property var projected: []
    function project() {
        if (!root.runtime || !root.worldSurface || !root.paneLive) {root.projected=[];return}
        var subjects=root.runtime.worldFeedbackSubjects, rows=[]
        for (var i=0;i<subjects.length;i++) {
            var item=subjects[i],point=root.worldSurface.nameplateProjection(item.x,item.y,item.z)
            if (!point.visible) continue
            var p=root.mapFromItem(root.worldSurface,point.x,point.y)
            rows.push(Object.assign({},item,{screenX:p.x,screenY:p.y}))
        }
        root.projected=rows
    }
    Timer {interval:50;repeat:true;running:root.paneLive && !!root.runtime && !!root.worldSurface;onTriggered:root.project()}
    Repeater {
        model:root.projected
        delegate:Item {
            id:mark
            required property var modelData
            objectName:'gameWorldFeedback_'+modelData.id
            readonly property bool bubble:modelData.kind==='BUBBLE'
            readonly property bool quest:modelData.kind==='QUEST'
            x:modelData.screenX-width/2
            y:modelData.screenY-height-(bubble || quest ? 0 : modelData.age*32)
            width:bubble ? Math.min(280,label.implicitWidth+24) : label.implicitWidth+8
            height:bubble ? label.implicitHeight+16 : label.implicitHeight+4
            opacity:modelData.alpha
            z:bubble ? 2 : quest ? 3 : 1
            Rectangle {anchors.fill:parent;visible:mark.bubble;radius:8;color:'#ef172720';border.color:'#b9aa78';border.width:1}
            Text {
                id:label
                anchors.centerIn:parent
                width:mark.bubble ? Math.min(256,implicitWidth) : implicitWidth
                text:mark.modelData.text
                textFormat:Text.PlainText
                wrapMode:mark.bubble ? Text.WordWrap : Text.NoWrap
                horizontalAlignment:Text.AlignHCenter
                font.pixelSize:mark.quest ? 30 : mark.bubble ? 13 : mark.modelData.critical ? 23 : 18
                font.bold:!mark.bubble
                color:mark.modelData.kind==='HEAL' ? '#65df93' : mark.modelData.kind==='DAMAGE' ? '#ffb378' : '#eed494'
                style:Text.Outline;styleColor:'#1a211c'
            }
        }
    }
}
