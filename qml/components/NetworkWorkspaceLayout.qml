import "." as RuntimeTheme
import QtQuick

// Retained fixed desktop instruments; only account/history/event books scroll.
Item {
    id: layout
    clip: true
    readonly property Item contentItem: layout
    readonly property real contentX: 0
    readonly property real contentY: 0
    property string prefix: "network"
    property var bookTitles: ["Konton", "Skicka", "Historik", "Mätning"]
    property Item summaryPanel
    property Item measurementPanel
    property Item relationsPanel
    property Item accountsPanel
    property Item transferPanel
    property Item historyPanel
    property int page: 0
    property int chartPage: 0
    property bool ready: false
    readonly property bool desktop: width >= 620 && height >= 500
    readonly property bool split: desktop
    readonly property bool compact: !desktop
    readonly property bool veryShort: height < 420
    readonly property bool formFocused: compact && (page === 1 || (veryShort && page !== 3))
    readonly property bool stacked: desktop
    readonly property bool noPageScroll: true
    readonly property real inset: 8
    readonly property real gap: 6
    readonly property real innerWidth: Math.max(0,width-inset*2)
    readonly property real summaryHeight: desktop ? Math.max(64,Math.min(108,summaryPanel ? summaryPanel.implicitHeight+8 : 64)) : summaryPanel ? summaryPanel.implicitHeight+8 : 0
    readonly property real barHeight: desktop ? Math.max(82,Math.min(124,height*.16)) : veryShort ? 72 : 90
    readonly property real graphHeight: desktop ? Math.max(108,Math.min(148,height*.20)) : 116
    readonly property real formHeight: desktop ? Math.max(102,Math.min(144,transferPanel ? transferPanel.implicitHeight+8 : 102)) : 0
    function place(item,panel) {
        if(!ready||!item||!panel)return
        item.parent=panel.content;item.x=0;item.y=0
        item.width=Qt.binding(function(){return panel.content.width})
        item.height=Qt.binding(function(){return panel.content.height})
    }
    function attach(){place(summaryPanel,summary);place(measurementPanel,measurement);place(relationsPanel,relations);place(accountsPanel,accounts);place(transferPanel,transfer);place(historyPanel,history)}
    onSummaryPanelChanged:attach()
    onMeasurementPanelChanged:attach()
    onRelationsPanelChanged:attach()
    onAccountsPanelChanged:attach()
    onTransferPanelChanged:attach()
    onHistoryPanelChanged:attach()
    Component.onCompleted:{ready=true;attach()}
    component Panel:Item {
        id:frame
        property alias content:slot
        Rectangle {anchors.fill:parent;color:"transparent";border.color:RuntimeTheme.GGTheme.line;border.width:1;antialiasing:false}
        Item {id:slot;x:6;y:4;width:Math.max(0,parent.width-12);height:Math.max(0,parent.height-8);clip:true}
    }
    Item {id:mainColumn;objectName:layout.prefix+"MainColumn";anchors.fill:parent}
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.1";id:summary;objectName:layout.prefix+"SummaryViewport";x:layout.inset;y:layout.veryShort?38:layout.inset;width:layout.innerWidth;height:visible?layout.summaryHeight:0;visible:!layout.formFocused&&!(layout.veryShort&&layout.chartPage===1)}
    Row {id:chartTabs;x:layout.inset;y:summary.visible?summary.y+summary.height+layout.gap:layout.veryShort?38:layout.inset;width:layout.innerWidth;height:24;spacing:4;visible:layout.compact&&!layout.formFocused
        CryptoButton { property string uiColorScope: "ui.control.NetworkWorkspaceLayout.1";text:"Latens";height:24;checked:layout.chartPage===0;flat:true;font.pixelSize:10;onClicked:layout.chartPage=0}
        CryptoButton { property string uiColorScope: "ui.control.NetworkWorkspaceLayout.2";text:"Blockrelationer";height:24;checked:layout.chartPage===1;flat:true;font.pixelSize:10;onClicked:layout.chartPage=1}
    }
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.4";id:measurement;objectName:layout.prefix+"MeasurementsViewport";x:layout.inset;y:layout.desktop?summary.y+summary.height+layout.gap:chartTabs.y+chartTabs.height+layout.gap;width:layout.innerWidth;height:visible?layout.barHeight:0;visible:!layout.formFocused&&(layout.desktop||layout.chartPage===0)}
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.5";id:relations;objectName:layout.prefix+"RelationsViewport";x:layout.inset;y:layout.desktop?measurement.y+measurement.height+layout.gap:chartTabs.y+chartTabs.height+layout.gap;width:layout.innerWidth;height:visible?layout.graphHeight:0;visible:!layout.formFocused&&(layout.desktop||layout.chartPage===1)}
    Item {
        id:bottom;objectName:layout.prefix+"BooksArea";x:layout.inset;width:layout.innerWidth
        y:layout.desktop?relations.y+relations.height+layout.gap:layout.formFocused?(layout.veryShort?38:34):Math.max(measurement.visible?measurement.y+measurement.height:0,relations.visible?relations.y+relations.height:0)+layout.gap
        height:Math.max(0,layout.height-y-layout.inset-(layout.desktop?layout.formHeight+layout.gap:0));clip:true
        Row {id:tabs;parent:layout.veryShort?layout:bottom;x:layout.veryShort?layout.inset:0;y:layout.veryShort?6:0;width:layout.veryShort?layout.innerWidth:bottom.width;height:24;visible:layout.compact;spacing:4
            Repeater {model:layout.bookTitles.slice(0,layout.veryShort?4:3)
                CryptoButton { property string uiColorScope: "ui.control.NetworkWorkspaceLayout.3";required property int index;required property string modelData;objectName:layout.prefix+["AccountsTab","TransferTab","HistoryTab","MetricsTab"][index];text:modelData;height:24;font.pixelSize:10;flat:true;checked:layout.page===index;onClicked:layout.page=index}
            }
        }
    }
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.7";id:accounts;objectName:layout.prefix+"AccountsViewport";x:layout.inset;y:bottom.y+(layout.desktop||layout.veryShort?0:24);width:layout.desktop?(layout.innerWidth-layout.gap)*.54:layout.innerWidth;height:Math.max(0,bottom.height-(layout.desktop||layout.veryShort?0:24));visible:layout.desktop||layout.page===0}
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.8";id:history;objectName:layout.prefix+"HistoryViewport";x:layout.desktop?accounts.x+accounts.width+layout.gap:layout.inset;y:accounts.y;width:layout.desktop?layout.width-layout.inset-x:layout.innerWidth;height:accounts.height;visible:layout.desktop||layout.page===2}
    Panel { property string uiColorScope: "ui.widget.NetworkWorkspaceLayout.Panel.9";id:transfer;objectName:layout.prefix+"TransferViewport";x:layout.inset;y:layout.desktop?layout.height-layout.inset-layout.formHeight:accounts.y;width:layout.innerWidth;height:layout.desktop?layout.formHeight:accounts.height;visible:layout.desktop||layout.page===1}
}
