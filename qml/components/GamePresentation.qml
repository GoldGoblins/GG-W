pragma ComponentBehavior: Bound

import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: root
    required property var surfaceHost
    property bool paneLive: true
    property bool standalone: false
    property var worldSurface: null
    signal clientControls(var controls)
    readonly property var runtime: surfaceHost && surfaceHost.gameEnginePresentation
        ? surfaceHost.gameEnginePresentation() : null
    readonly property var frames: runtime ? JSON.parse(runtime.framesJson) : []
    readonly property var audio: runtime ? JSON.parse(runtime.audioJson) : ({})
    readonly property bool focused: Window.window ? Window.window.active : true
    function activity() { if (runtime) runtime.setActivity(paneLive,focused) }
    Connections {
        target: root.runtime
        function onClientControlsChanged() { root.clientControls(JSON.parse(root.runtime.clientControlsJson)) }
    }
    onPaneLiveChanged: activity()
    onFocusedChanged: activity()
    Component.onCompleted: { activity(); if(runtime) runtime.attachCanvas(root,standalone) }
    Timer {
        interval: 50;repeat:true;running:root.paneLive && !!root.runtime && root.runtime.nameplatesEnabled && !!root.worldSurface
        onTriggered: {
            var subjects=root.runtime.nameplateSubjects
            var rows=[]
            for(var i=0;i<subjects.length;i++) {
                var p=subjects[i]
                var point=root.worldSurface.nameplateProjection(p.x,p.y+1.85,p.z)
                if(point.visible) {
                    var local=root.mapFromItem(root.worldSurface,point.x,point.y)
                    local.x-=root.standalone ? 0 : 174
                    rows.push({guid:p.guid,x:local.x,y:local.y})
                }
            }
            root.runtime.updateNameplates(rows,root.worldSurface.mouseRightHeld,false)
        }
    }
    GameAddonsPanel { property string uiColorScope: "ui.widget.GamePresentation.GameAddonsPanel.1";
        z: 15
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 14
        anchors.topMargin: 66
        runtime: root.runtime
        paneLive: root.paneLive
    }
    GameWorldFeedback { property string uiColorScope: "ui.widget.GamePresentation.GameWorldFeedback.2";
        anchors.fill:parent
        z:0
        runtime:root.runtime
        worldSurface:root.worldSurface
        paneLive:root.paneLive
    }
    Repeater {
        model: root.runtime && !root.runtime.engineUiEnabled ? root.runtime.framesModel : null
        delegate: Rectangle {
            id: frame
            required property var frameData
            objectName: "gameLuaFrame_" + frameData.id
            x: frameData.x + (root.standalone ? 0 : 174); y: frameData.y
            width: frameData.width; height: frameData.height
            visible: root.paneLive && frameData.visible
            z: frameData.level
            radius: 4; color: frameData.background
            border.color: frameData.color; border.width: 1
            GGText { colorKey: "ui.GamePresentation.1"; anchors.fill: parent; anchors.margins: 8; text: frame.frameData.text
                color: "#f0e2c6"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            Rectangle { visible: frame.frameData.kind === "StatusBar"
                width: parent.width*frame.frameData.value; height: 3;anchors.bottom: parent.bottom;color: frame.frameData.color }
            MouseArea { anchors.fill: parent; enabled: frame.frameData.kind === "Button"
                onClicked: if(root.runtime) root.runtime.click(frame.frameData.id) }
        }
    }
    Rectangle {
        id: volume
        z: 10
        property bool expanded: false
        visible: root.paneLive && root.runtime
        anchors.right: parent.right;anchors.bottom: parent.bottom;anchors.margins: 14
        width: expanded ? 220 : 54; height: expanded ? 202 : 30
        radius: 4;color: "#ee19232b";border.color: RuntimeTheme.GGTheme.edge
        Button { property string uiColorScope: "ui.control.GamePresentation.1"; objectName: "gameAudioToggle";x: 4;y: 2;width: 46;height: 26;text: "Ljud"
            onClicked: volume.expanded=!volume.expanded 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Column { visible: volume.expanded;x: 10;y: 35;spacing: 2
            Repeater { model: [{id:"master",name:"Volym"},{id:"sfx",name:"Effekter"},{id:"music",name:"Musik"},{id:"ambience",name:"Omgivning"}]
                delegate: Row {
                    required property var modelData
                    GGText { colorKey: "ui.GamePresentation.2"; width: 78;height: 28;verticalAlignment: Text.AlignVCenter
                        color: RuntimeTheme.GGTheme.text;text: parent.modelData.name;font.pixelSize: 11 }
                    Slider { objectName: "gameAudioSlider_"+parent.modelData.id
                        width: 118;height: 28;from: 0;to: 1;value: root.audio[parent.modelData.id] || 0
                        onMoved: if(root.runtime) root.runtime.setVolume(parent.modelData.id,value) }
                }
            }
            CheckBox { property string uiColorScope: "ui.control.GamePresentation.2"; text: "Tyst";checked: Boolean(root.audio.muted);palette.windowText: RuntimeTheme.GGTheme.text
                onToggled: if(root.runtime) root.runtime.setMuted(checked) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft;withIndicator:true }
}
        }
    }
}
