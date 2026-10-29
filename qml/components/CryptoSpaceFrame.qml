import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// Native tab navigation and content geometry. The workspace owns the outer frame.
Item {
    id:root;objectName:"cryptoSpaceFrame"
    property string section:"MARKET"
    property string title:"Marknad"
    property string context:"Publik data · läsläge"
    property bool collapsed:false
    property bool activityVisible:false
    property bool detailsAvailable:false
    property bool detailsChecked:false
    property var events:[]
    property var surfaceHost:null
    property var operation:({})
    property var liveEvents:[]
    property string activityRaw:""
    readonly property bool compact:collapsed || width<480
    readonly property real navigationWidth:128
    readonly property Item navigationItem:navigation
    readonly property Item contentItem:body
    signal navigate(string section)
    signal detailsToggleRequested()
    readonly property var destinations:[
        {id:"WALLET",label:"Översikt",short:"Översikt",glyph:"▣"},
        {id:"MARKET",label:"Marknad",short:"Marknad",glyph:"◎"},
        {id:"MARKETPLACE",label:"MARKETPLACE",short:"MARKETPLACE",glyph:"◇"},
        {id:"BOTS",label:"Botar",short:"Botar",glyph:"◫"},
        {id:"NETWORK",label:"Nätverk",short:"Nätverk",glyph:"⌘"}
    ]
    function operationTitle(name) {
        return ({refresh:"läser marknad",select:"läser tillgång",open_asset:"läser tillgång",chart:"läser historik",search:"söker",configure:"uppdaterar urval",market_discover:"läser samlingar",market_list:"registrerar objekt",market_image:"läser bild",market_select:"öppnar objekt",connect_watch:"läser kontot",refresh_balance:"läser saldo",refresh_account:"läser kontot",refresh_wallet:"uppdaterar kontoöversikten",discover_assets:"läser tokenkonton",create_wallet:"skapar wallet",backup_wallet:"krypterar backup",restore_wallet:"återställer wallet",prepare_transfer:"simulerar överföring",send_transfer:"signerar och sänder",check_transfer:"kontrollerar bekräftelse",select_transfer:"öppnar överföring",lab_send:"förbereder labböverföring",lab_commit:"finaliserar labbblock",bot_step:"analyserar",bot_reset:"återställer paperkonto"})[name] || "utför jobb"
    }
    function applyActivity(raw){if(raw===activityRaw)return;try{var value=JSON.parse(raw);if(value.schema==="gg.space-activity.v1"){activityRaw=raw;liveEvents=value.events}}catch(e){}}
    function pullActivity(){if(visible && activityVisible && surfaceHost && surfaceHost.spaceActivityStatus)applyActivity(surfaceHost.spaceActivityStatus())}
    onActivityVisibleChanged:if(activityVisible)pullActivity()
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onSpaceActivityUpdated(raw){if(root.visible && root.activityVisible)root.applyActivity(raw)}}
    Timer {interval:root.operation.state==="running" ? 500 : 2000;repeat:true;running:root.visible && root.activityVisible && !!root.surfaceHost && !!root.surfaceHost.spaceActivityStatus;onTriggered:root.pullActivity()}

    Flickable {
        id:navViewport;objectName:"spaceNavigationViewport";x:root.compact ? 6 : 18;y:0;height:44;width:Math.max(0,parent.width-x-actions.width-12)
        contentWidth:navigation.width;contentHeight:height;clip:true;flickableDirection:Flickable.HorizontalFlick;boundsBehavior:Flickable.StopAtBounds
        Row {id:navigation;height:44;spacing:root.compact ? 2 : 8
            Repeater {model:root.destinations
                CryptoButton { property string uiColorScope: "ui.control.CryptoSpaceFrame.1";
                    id:navButton;required property var modelData
                    objectName:"spaceNav"+modelData.id
                    width:(root.width<360 || root.collapsed) && modelData.id!=="MARKETPLACE" ? 36 : contentItem.implicitWidth+(root.compact ? 14 : 24);height:44
                    text:(root.width<360 || root.collapsed) && modelData.id!=="MARKETPLACE" ? modelData.glyph : (root.compact ? modelData.short : modelData.label).toUpperCase()
                    flat:true;checked:root.section===modelData.id;tip:modelData.id==="MARKETPLACE" ? "Marketplace" : modelData.id==="NETWORK" ? "Nätverk och labb" : modelData.label;font.pixelSize:root.compact ? 11 : root.width>=1000 ? 16 : 13
                    leftPadding:root.compact ? 3 : 8;rightPadding:root.compact ? 3 : 8
                    color:checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text
                    Accessible.name:modelData.label
                    background:Rectangle {
                        color:navButton.hovered ? RuntimeTheme.GGTheme.raised : "transparent"
                        Rectangle { GGColorTarget { colorKey: "ui.navigation.crypto."+String(navButton.modelData.id); }anchors.bottom:parent.bottom;anchors.horizontalCenter:parent.horizontalCenter;width:parent.width-(root.compact ? 8 : 16);height:2;visible:navButton.checked;color:RuntimeTheme.GGTheme.accent}
                    }
                    onClicked:root.navigate(modelData.id)
                }
            }
        }
    }
    Row {id:actions;anchors.right:parent.right;anchors.rightMargin:8;anchors.top:parent.top;height:44;spacing:6
        GGText { colorKey: "ui.CryptoSpaceFrame.1";
            visible:root.width>=1100;width:visible ? 200 : 0;height:44;verticalAlignment:Text.AlignVCenter;horizontalAlignment:Text.AlignRight
            text:root.operation.state==="running" ? "◌ "+root.operationTitle(root.operation.name) : root.operation.state==="error" ? "FEL · "+root.operationTitle(root.operation.name) : root.operation.state==="approval_required" ? "VÄNTAR PÅ GODKÄNNANDE" : root.context
            color:root.operation.state==="error" ? RuntimeTheme.GGTheme.negative : root.operation.state==="running" || root.operation.state==="approval_required" ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted
            font.family:"monospace";font.pixelSize:11;elide:Text.ElideRight;textFormat:Text.PlainText
        }
        CryptoButton { property string uiColorScope: "ui.control.CryptoSpaceFrame.2";id:toolsButton;anchors.verticalCenter:parent.verticalCenter;width:30;implicitWidth:30;height:30;text:"⋯";flat:true;quiet:true;tip:"Analys och avancerade verktyg";onClicked:tools.open()}
        CryptoButton { property string uiColorScope: "ui.control.CryptoSpaceFrame.3";objectName:"spaceDetailsToggle";anchors.verticalCenter:parent.verticalCenter;visible:root.detailsAvailable;width:root.width<600 ? 32 : 104;implicitWidth:width;height:30;text:root.width<600 ? "◧" : "Sidopanel";flat:true;quiet:true;tip:"Konton, skydd, källstatus och händelser";Accessible.name:"Visa eller dölj sidopanel";font.pixelSize:12;checked:root.detailsChecked;onClicked:root.detailsToggleRequested()}
        CryptoButton { property string uiColorScope: "ui.control.CryptoSpaceFrame.4";objectName:"spaceActivityToggle";anchors.verticalCenter:parent.verticalCenter;width:30;implicitWidth:30;height:30;text:"≡";flat:true;quiet:true;tip:"Verkliga händelser";checked:root.activityVisible;onClicked:root.activityVisible=!root.activityVisible}
    }
    Rectangle {y:44;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    Item {
        id:body;objectName:"spaceContent";x:0;y:48
        width:Math.max(0,parent.width-(root.activityVisible && root.width>=900 ? 280 : 0))
        height:Math.max(0,parent.height-y);clip:true
    }
    SpaceActivityFeed { property string uiColorScope: "ui.widget.CryptoSpaceFrame.SpaceActivityFeed.5";x:parent.width-width;y:48;width:Math.min(280,parent.width);height:Math.max(0,parent.height-y);visible:root.activityVisible;z:30;events:root.surfaceHost && root.surfaceHost.spaceActivityStatus ? root.liveEvents : root.events;onCloseRequested:root.activityVisible=false}
    Popup {
        id:tools;objectName:"spaceToolsMenu";x:Math.max(0,root.width-width-8);y:44;width:Math.min(260,root.width-16);padding:10;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:3}
        contentItem:Column {spacing:3
            GGText { colorKey: "ui.CryptoSpaceFrame.2";text:root.title+" · AVANCERAT";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:10;textFormat:Text.PlainText}
            Repeater {model:[{id:"PORTFOLIO",name:"SOL / KAS-labb"},{id:"BACKTEST",name:"Backtest"},{id:"TRADER",name:"Trader"},{id:"PUMP",name:"Tokenanalys / Pump"},{id:"SIGNAL",name:"Signaler"},{id:"ARB",name:"Arbitrage"},{id:"ACTIVITY",name:"Fills / aktivitet"},{id:"FACTORY",name:"Strategifabrik"},{id:"DESK",name:"Research desk"},{id:"POLY",name:"Polymarket"},{id:"OMNI",name:"Alla nätverksverktyg"}]
                CryptoButton { property string uiColorScope: "ui.control.CryptoSpaceFrame.5";required property var modelData;width:parent.width;flat:true;text:modelData.name;horizontalAlignment:Text.AlignLeft;onClicked:{root.navigate(modelData.id);tools.close()}}
            }
        }
    }
}
