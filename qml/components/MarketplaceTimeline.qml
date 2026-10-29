import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id:root;objectName:"marketLocalTimeline"
    property var events:[]
    property var listings:[]
    property string scopeLabel:"Lokala kvittohändelser"
    property string emptyText:"Inga lokala kvittohändelser ännu."
    property bool expanded:width>=700
    readonly property var recent:events.slice(-12)
    readonly property real desiredHeight:expanded ? Math.min(172,Math.max(94,root.parent.height*.19)) : 28
    function title(event){if(event.message)return event.message;for(var i=0;i<listings.length;i++)if(listings[i].id===event.listing_id)return listings[i].title;return event.listing_id || "Lokalt kvitto"}
    function timeLabel(stamp){return stamp ? new Date(stamp*1000).toLocaleTimeString(Qt.locale(),"HH:mm:ss") : "—"}
    Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    Row {id:head;x:2;y:6;width:parent.width-4;height:22;spacing:8
        GGText { colorKey: "ui.MarketplaceTimeline.1";width:Math.max(90,parent.width-counter.width-8);text:(root.expanded ? "⌄ " : "› ")+"HÄNDELSELOGG";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:11;font.letterSpacing:.5}
        GGText { colorKey: "ui.MarketplaceTimeline.2";id:counter;visible:root.width>=550;text:root.scopeLabel+" · "+root.events.length;color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:10}
    }
    MouseArea {objectName:"marketTimelineToggle";x:0;y:0;width:parent.width;height:32;cursorShape:Qt.PointingHandCursor;onClicked:root.expanded=!root.expanded;activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:"Visa eller dölj lokal händelselogg";Keys.onReturnPressed:root.expanded=!root.expanded}
    ListView {objectName:"marketTimelineRows";x:2;y:30;width:parent.width-4;height:parent.height-y;visible:root.expanded;clip:true;model:root.recent;spacing:2;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
        delegate:Row {required property var modelData;width:ListView.view.width;height:17;spacing:10
            GGText { colorKey: "ui.MarketplaceTimeline.3";width:64;text:root.timeLabel(modelData.ts);font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
            GGText { colorKey: "ui.MarketplaceTimeline.4";width:root.width<500 ? 66 : 116;text:({LIST:"REGISTRERAT",BUY:"PAPERKÖP",DELIST:"AVPUBLICERAT",REBIRTH:"ÅTERBRUK"})[modelData.kind] || modelData.kind;font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.muted;elide:Text.ElideRight}
            GGText { colorKey: "ui.MarketplaceTimeline.5";width:Math.max(20,parent.width-x);text:root.title(modelData);font.family:"monospace";font.pixelSize:11;color:RuntimeTheme.GGTheme.text;elide:Text.ElideRight;textFormat:Text.PlainText}
        }
        GGText { colorKey: "ui.MarketplaceTimeline.6";width:parent.width;visible:root.recent.length===0;text:root.emptyText;font.family:"monospace";font.pixelSize:11;color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap}
    }
}
