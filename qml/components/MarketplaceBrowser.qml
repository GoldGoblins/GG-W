import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id:root;objectName:"marketVisualBrowser"
    property var rows:[]
    property var sourceRows:rows
    property var fullRows:sourceRows
    property var events:[]
    property var receipt:({})
    property string focusedId:""
    property string kind:""
    property string category:""
    property string material:""
    property string collection:""
    property string origin:""
    property string maker:""
    property string mode:"ATLAS"
    property string sort:"recent"
    property bool priceSortAvailable:false
    property bool busy:false
    property Component categoryComponent:null
    property Component passportComponent:null
    property Component catalogToolsComponent:null
    property string emptyTitle:"Ett pass för varje objekt."
    property string emptyMessage:"Inga lokala objekt har registrerats här. Lägg till en verklig vara eller tjänst med bild, innehåll och ursprung."
    property string eventScopeLabel:"Lokala kvittohändelser"
    property string eventEmptyMessage:"Inga lokala kvittohändelser ännu."
    property bool timelineExpanded:width>=860
    readonly property bool showCategories:width>=720
    readonly property bool showPassport:mode==="ATLAS" && width>=860
    readonly property real railWidth:Math.min(226,Math.max(132,width*.15))
    readonly property var preview:{for(var i=0;i<rows.length;i++)if(rows[i].id===focusedId)return receipt && receipt.id===focusedId ? receipt : rows[i];return rows.length ? rows[0] : ({})}
    readonly property var categoryRows:facets.categoryRows
    readonly property var materialRows:facets.materialRows
    signal facetRequested(string field,string value,string kind)
    signal sortRequested(string sort)
    signal modeRequested(string mode)
    signal objectFocused(string id)
    signal objectOpened(string id)
    signal nftRequested(var binding)
    signal registerRequested()
    function openPassport(){if(!showPassport && passportComponent)passportPopup.open()}
    function openCategories(){facetPopup.open()}
    onVisibleChanged:if(!visible){passportPopup.close();facetPopup.close()}
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;elide:Text.ElideRight}
    MarketplaceFacetTree { property string uiColorScope: "ui.widget.MarketplaceBrowser.MarketplaceFacetTree.1";
        id:facets;visible:root.showCategories && !root.categoryComponent;width:root.railWidth-12;height:parent.height-timeline.height-8
        rows:root.sourceRows;kind:root.kind;category:root.category;material:root.material;collection:root.collection;origin:root.origin;maker:root.maker;busy:root.busy
        onFilterRequested:function(field,value,kind){root.facetRequested(field,value,kind)}
    }
    Loader {visible:root.showCategories && !!root.categoryComponent;width:root.railWidth-12;height:Math.max(0,parent.height-timeline.height-8);sourceComponent:root.categoryComponent}
    Rectangle {x:root.railWidth;y:0;width:1;height:parent.height-timeline.height;visible:root.showCategories;color:RuntimeTheme.GGTheme.line}
    Item {
        id:catalog;objectName:"marketVisualCatalog";x:root.showCategories ? root.railWidth+12 : 0;width:parent.width-x-(root.showPassport ? pass.width+12 : 0);height:parent.height-timeline.height-8
        Column {id:catalogBar;width:parent.width;spacing:0
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceBrowser.1";objectName:"marketCompactCategory";visible:!root.showCategories;text:"☷  Kategorier & material";quiet:true;enabled:!root.busy;onClicked:facetPopup.open()}
            Loader {width:parent.width;sourceComponent:root.catalogToolsComponent;visible:!!root.catalogToolsComponent}
            Row {width:parent.width;height:30;spacing:8;visible:!root.catalogToolsComponent
                Label { colorKey: "ui.MarketplaceBrowser.1";width:Math.max(70,parent.width-sorter.width-modeButton.width-16);height:28;verticalAlignment:Text.AlignVCenter;text:"VISAR "+root.rows.length+" AV "+root.sourceRows.length;color:RuntimeTheme.GGTheme.muted;font.pixelSize:10;font.letterSpacing:.3}
                CryptoPick { property string uiColorScope: "ui.control.MarketplaceBrowser.2";id:sorter;objectName:"marketCatalogSort";width:130;height:26;font.pixelSize:10;model:[{id:"recent",name:"Senast tillagd"},{id:"name",name:"Namn"}].concat(root.priceSortAvailable ? [{id:"price",name:"Lägst begärt pris"}] : []);textRole:"name";currentIndex:root.sort==="name" ? 1 : root.sort==="price" ? 2 : 0;enabled:!root.busy;Accessible.name:"Sortera katalogen";onActivated:root.sortRequested(model[currentIndex].id)}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceBrowser.3";id:modeButton;objectName:"marketPassportToggle";width:26;implicitWidth:26;height:26;text:root.mode==="ATLAS" ? "▦" : "◧";quiet:true;visible:root.width>=860;checked:root.showPassport;tip:"Visa eller dölj passet bredvid katalogen";Accessible.name:"Visa eller dölj pass";onClicked:root.modeRequested(root.mode==="ATLAS" ? "GRID" : "ATLAS")}
            }
            Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        }
        MarketplaceGrid { property string uiColorScope: "ui.widget.MarketplaceBrowser.MarketplaceGrid.5";id:grid;anchors.top:catalogBar.bottom;anchors.topMargin:8;anchors.bottom:parent.bottom;width:parent.width;visible:root.sourceRows.length>0;rows:root.rows;columns:root.width>=860 ? 3 : width>=390 ? 2 : 1;selectedId:root.preview.id || "";busy:root.busy;previewEnabled:root.showPassport || !!root.passportComponent
            onObjectFocused:function(id){root.objectFocused(id);root.openPassport()}
            onObjectOpened:function(id){root.objectOpened(id);root.openPassport()}
        }
        Column {x:12;y:catalogBar.height+40;width:Math.max(80,parent.width-24);spacing:14;visible:root.sourceRows.length===0
            Label { colorKey: "ui.MarketplaceBrowser.2";width:parent.width;text:root.emptyTitle;color:RuntimeTheme.GGTheme.bright;font.pixelSize:23;wrapMode:Text.WordWrap;elide:Text.ElideNone}
            Label { colorKey: "ui.MarketplaceBrowser.3";width:parent.width;text:root.emptyMessage;color:RuntimeTheme.GGTheme.muted;font.pixelSize:12;wrapMode:Text.WordWrap;elide:Text.ElideNone}
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceBrowser.4";text:"+ Registrera objekt";visible:!root.passportComponent;enabled:!root.busy;onClicked:root.registerRequested()}
        }
    }
    Flickable {
        id:pass;objectName:"marketAdjacentObjectPass";visible:root.showPassport;anchors.right:parent.right;width:Math.min(410,Math.max(238,root.width*.265));height:parent.height;clip:true;contentWidth:width;contentHeight:root.passportComponent ? customPass.height : passport.height;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
        Rectangle {width:1;height:Math.max(parent.height,parent.contentHeight);color:RuntimeTheme.GGTheme.line}
        Loader {id:customPass;x:12;width:parent.width-12;sourceComponent:root.passportComponent;visible:!!root.passportComponent}
        MarketplaceObjectPassport { property string uiColorScope: "ui.widget.MarketplaceBrowser.MarketplaceObjectPassport.7";id:passport;objectName:"marketBrowserPassport";visible:!root.passportComponent;x:12;width:parent.width-12;receipt:root.preview;listings:root.fullRows;busy:root.busy
            onObjectRequested:function(id){root.objectOpened(id)}
            onNftRequested:function(binding){root.nftRequested(binding)}
            onRegisterRequested:root.registerRequested()
        }
    }
    MarketplaceTimeline { property string uiColorScope: "ui.widget.MarketplaceBrowser.MarketplaceTimeline.8";id:timeline;anchors.left:parent.left;anchors.bottom:parent.bottom;width:parent.width-(root.showPassport ? pass.width+12 : 0);height:desiredHeight;expanded:root.timelineExpanded;events:root.events;listings:root.fullRows;scopeLabel:root.eventScopeLabel;emptyText:root.eventEmptyMessage}
    Popup {id:passportPopup;objectName:"marketCompactPassport";x:Math.max(0,root.width-width);y:0;width:Math.min(420,root.width);height:root.height;padding:14;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.base;border.color:RuntimeTheme.GGTheme.edge}
        contentItem:Column {spacing:10
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceBrowser.5";height:28;text:"← Till katalogen";flat:true;onClicked:passportPopup.close()}
            Flickable {width:parent.width;height:passportPopup.availableHeight-38;contentWidth:width;contentHeight:compactPass.height;clip:true;ScrollBar.vertical:ScrollBar{}
                Loader {id:compactPass;width:parent.width;sourceComponent:root.passportComponent}
            }
        }
    }
    Popup {id:facetPopup;objectName:"marketFacetPopup";parent:root;x:0;y:0;width:Math.min(340,root.width);height:Math.min(580,root.height);padding:14;focus:true;closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge}
        contentItem:Column {spacing:8
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceBrowser.6";text:"← Till katalogen";quiet:true;onClicked:facetPopup.close()}
            Loader {visible:!!root.categoryComponent;width:parent.width;height:facetPopup.height-78;sourceComponent:root.categoryComponent}
            MarketplaceFacetTree { property string uiColorScope: "ui.widget.MarketplaceBrowser.MarketplaceFacetTree.11";objectName:"marketCompactFacetTree";visible:!root.categoryComponent;width:parent.width;height:facetPopup.height-78;rows:root.sourceRows;kind:root.kind;category:root.category;material:root.material;collection:root.collection;origin:root.origin;maker:root.maker;busy:root.busy;onFilterRequested:function(field,value,kind){root.facetRequested(field,value,kind)}}
        }
    }
}
