import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Rectangle {
    id:root;objectName:"spaceActivityFeed"
    property var events:[]
    property bool paused:false
    property var frozen:[]
    readonly property var rows:paused ? frozen : events
    onRowsChanged:if(!paused)Qt.callLater(function(){log.positionViewAtEnd()})
    signal closeRequested()
    color:RuntimeTheme.GGTheme.canvas;border.color:RuntimeTheme.GGTheme.line;radius:3
    Row {id:head;x:10;y:8;width:parent.width-20;spacing:5
        GGText { colorKey: "ui.SpaceActivityFeed.1";width:Math.max(40,parent.width-76);height:28;verticalAlignment:Text.AlignVCenter;text:"HÄNDELSER";color:RuntimeTheme.GGTheme.accent;font.family:"monospace";font.pixelSize:10;font.letterSpacing:1}
        CryptoButton { property string uiColorScope: "ui.control.SpaceActivityFeed.1";text:root.paused ? "▶" : "Ⅱ";implicitWidth:28;tip:root.paused ? "Följ nya händelser" : "Frys vyn, jobben fortsätter";onClicked:{if(!root.paused)root.frozen=root.events.slice();root.paused=!root.paused}}
        CryptoButton { property string uiColorScope: "ui.control.SpaceActivityFeed.2";text:"×";implicitWidth:28;tip:"Stäng händelsepanelen";onClicked:root.closeRequested()}
    }
    ListView {
        id:log;objectName:"spaceEventLog";x:10;y:42;width:parent.width-20;height:parent.height-y-8;clip:true;model:root.rows;spacing:12
        ScrollBar.vertical:ScrollBar {}
        onCountChanged:if(!root.paused)Qt.callLater(function(){log.positionViewAtEnd()})
        delegate:Column {
            required property var modelData;width:log.width;spacing:4
            GGText { colorKey: "ui.SpaceActivityFeed.2";width:parent.width;text:(modelData.ts ? new Date(Number(modelData.ts)*1000).toLocaleTimeString(Qt.locale(),"HH:mm:ss") : "")+"  "+String(modelData.kind || modelData.status || "EVENT");color:/FAIL|ERROR|REJECT/.test(String(modelData.kind || modelData.status)) ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:9;elide:Text.ElideRight;textFormat:Text.PlainText}
            GGText { colorKey: "ui.SpaceActivityFeed.3";width:parent.width;text:String(modelData.message || modelData.hint || "");color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:10;wrapMode:Text.WrapAnywhere;textFormat:Text.PlainText}
        }
        GGText { colorKey: "ui.SpaceActivityFeed.4";anchors.centerIn:parent;width:parent.width;visible:log.count===0;text:"Inga händelser ännu.\nVerkliga jobb och svar visas här när de inträffar.";color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:10;wrapMode:Text.WordWrap}
    }
}
