import "." as RuntimeTheme
import QtQuick

// Every desktop fact group remains visible. Only event rows scroll. Small
// drawers keep the same explicit group selector, never a whole-page scroller.
Item {
    id:layout;clip:true
    readonly property Item contentItem:layout
    readonly property real contentX:0
    readonly property real contentY:0
    property string prefix:"network"
    property list<Item> sections
    property var titles:[]
    property Item eventsPanel
    property int page:0
    property bool ready:false
    readonly property bool noPageScroll:true
    readonly property bool compactSelector:height<480
    readonly property bool showAll:page===0
    readonly property bool eventsOnly:page===sections.length+1
    readonly property real allHeight:{var total=0;for(var i=0;i<sections.length;i++)total+=(sections[i]?sections[i].implicitHeight:0);return total}
    readonly property int overviewCount:sections.length
    readonly property bool overviewFits:true
    // Stable geometry: deriving this from wrapped Flow heights feeds back into
    // their width and can oscillate. The two bounded desktop densities depend
    // only on viewport size and the fixed group count.
    readonly property real density:showAll?(height<480?.78:height<620?(sections.length>=6?.82:.92):1):1
    function attach(){
        if(!ready)return
        for(var i=0;i<sectionFrames.count;i++){
            var frame=sectionFrames.itemAt(i),item=sections[i]
            if(!frame||!item)continue
            item.parent=frame.slot;item.x=0;item.y=0;item.transformOrigin=Item.TopLeft
            item.width=Qt.binding(function(){return this.parent.width/layout.density})
            item.height=Qt.binding(function(){return this.implicitHeight})
            item.scale=Qt.binding(function(){return layout.density})
        }
        if(eventsPanel){eventsPanel.parent=eventSlot;eventsPanel.x=6;eventsPanel.y=4;eventsPanel.width=Qt.binding(function(){return Math.max(0,eventSlot.width-12)});eventsPanel.height=Qt.binding(function(){return Math.max(0,eventSlot.height-8)})}
    }
    onSectionsChanged:Qt.callLater(attach)
    onEventsPanelChanged:Qt.callLater(attach)
    Component.onCompleted:{ready=true;attach()}
    CryptoPick { property string uiColorScope: "ui.control.NetworkRailLayout.1";objectName:layout.prefix+"RailSection";width:parent.width;height:26;visible:layout.compactSelector;model:["Översikt"].concat(layout.titles).concat(["Händelser"]);currentIndex:layout.page;font.pixelSize:10;Accessible.name:"Välj informationsgrupp";onActivated:layout.page=currentIndex}
    Column {id:body;y:layout.compactSelector?32:0;width:parent.width;spacing:5
        Repeater {id:sectionFrames;model:layout.sections.length
            Item {id:frame;required property int index;property alias slot:slot
                width:body.width;height:visible?(layout.sections[index]?layout.sections[index].implicitHeight*layout.density+8:0):0
                visible:!layout.eventsOnly&&(layout.page===0||index===layout.page-1)
                Rectangle {anchors.fill:parent;color:"transparent";border.color:RuntimeTheme.GGTheme.line;border.width:1;antialiasing:false}
                Item {id:slot;x:6;y:4;width:Math.max(0,parent.width-12);height:Math.max(0,parent.height-8);clip:true}
                Component.onCompleted:Qt.callLater(layout.attach)
            }
        }
    }
    Item {id:eventSlot;x:0;y:layout.eventsOnly?(layout.compactSelector?32:0):body.y+body.height+5;width:parent.width;height:Math.max(0,parent.height-y);visible:layout.eventsOnly||layout.showAll;clip:true
        Rectangle {anchors.fill:parent;color:"transparent";border.color:RuntimeTheme.GGTheme.line;border.width:1;antialiasing:false}
    }
}
