import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

GridView {
    id:root;objectName:"marketCatalogGrid"
    property var rows:[]
    property string selectedId:""
    property bool busy:false
    property bool previewEnabled:false
    property int columns:Math.max(1,Math.floor(width/200))
    readonly property var materialNames:({WOOD:"Trä",METAL:"Metall",STONE:"Sten",FABRIC:"Textil",DIGITAL:"Digitalt",MIXED:"Blandat",UNKNOWN:"Material ej angivet",GOLD:"Guld",SILVER:"Silver",COPPER:"Koppar"})
    signal objectFocused(string id)
    signal objectOpened(string id)
    function activate(id){if(busy)return;if(previewEnabled)objectFocused(id);else objectOpened(id)}
    model:visible ? rows : []
    clip:true;boundsBehavior:Flickable.StopAtBounds;cacheBuffer:140
    cellWidth:width/Math.max(1,columns)
    cellHeight:cellWidth+24
    ScrollBar.vertical:ScrollBar {}
    delegate:Rectangle {
        id:tile;required property var modelData;required property int index
        readonly property var row:modelData
        objectName:"marketReceiptTile";width:root.cellWidth-12;height:root.cellHeight-12
        color:hover.containsMouse ? RuntimeTheme.GGTheme.hover : RuntimeTheme.GGTheme.base
        border.width:1
        border.color:root.selectedId===row.id ? RuntimeTheme.GGTheme.accent : hover.containsMouse ? RuntimeTheme.GGTheme.edge : RuntimeTheme.GGTheme.line
        enabled:!root.busy
        Rectangle {x:1;y:1;width:parent.width-2;height:parent.height-44;color:RuntimeTheme.GGTheme.canvas;clip:true
            Image {id:cardImage;objectName:"marketCardImage";anchors.fill:parent;source:tile.row.image_url || "";sourceSize.width:640;sourceSize.height:640;fillMode:Image.PreserveAspectCrop;asynchronous:true}
            Column {anchors.centerIn:parent;spacing:8;visible:!tile.row.image_url || cardImage.status===Image.Error || cardImage.status===Image.Loading
                GGText { colorKey: "ui.MarketplaceGrid.1";anchors.horizontalCenter:parent.horizontalCenter;text:cardImage.status===Image.Error ? "!" : cardImage.status===Image.Loading ? "…" : tile.row.kind==="SERVICE" ? "◇" : String(tile.row.title || "?").slice(0,2).toUpperCase();color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:34}
                GGText { colorKey: "ui.MarketplaceGrid.2";objectName:"marketImagePlaceholder";anchors.horizontalCenter:parent.horizontalCenter;text:cardImage.status===Image.Error ? "Bild kunde inte läsas" : cardImage.status===Image.Loading ? "Läser bild…" : tile.row.image_caption || (tile.row.kind==="COLLECTION" ? "Bild ej hämtad" : "Ingen objektbild");color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:10}
            }
        }
        GGText { colorKey: "ui.MarketplaceGrid.3";x:7;y:parent.height-38;width:parent.width-21;text:row.title || "Objekt";color:RuntimeTheme.GGTheme.bright;font.family:"monospace";font.pixelSize:root.cellWidth>=240 ? 14 : 12;font.bold:true;elide:Text.ElideRight;textFormat:Text.PlainText}
        GGText { colorKey: "ui.MarketplaceGrid.4";x:7;y:parent.height-20;width:parent.width-14;text:row.subtitle || (row.kind==="SERVICE" ? "Tjänst" : root.materialNames[row.material] || row.material || "Objekt")+(row.collection_name ? " · "+row.collection_name : "");color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:root.cellWidth>=240 ? 12 : 10;elide:Text.ElideRight;textFormat:Text.PlainText}
        GGText { colorKey: "ui.MarketplaceGrid.5";anchors.right:parent.right;anchors.rightMargin:7;y:parent.height-40;text:"›";font.pixelSize:15;color:RuntimeTheme.GGTheme.muted}
        MouseArea {id:hover;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.activate(tile.row.id);onDoubleClicked:if(!root.busy)root.objectOpened(tile.row.id)}
        activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:row.title || "Objekt"
        Keys.onReturnPressed:root.activate(row.id)
        ToolTip {id:cardTip;visible:hover.containsMouse;delay:650;width:Math.min(320,root.width);padding:10
            text:(tile.row.title || "Objekt")+(tile.row.price_label ? "\n"+tile.row.price_label : "")+(tile.row.reference_label ? "\n"+tile.row.reference_label : "")
            background:Rectangle {color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge;radius:2}
            contentItem:GGText { colorKey: "ui.MarketplaceGrid.6";text:cardTip.text;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;wrapMode:Text.WrapAnywhere;textFormat:Text.PlainText}
        }
    }
    GGText { colorKey: "ui.MarketplaceGrid.7";anchors.centerIn:parent;width:Math.min(parent.width-30,400);visible:root.count===0;text:"Inga objekt matchar. Justera kategorin, materialet eller sökningen.";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:12;wrapMode:Text.WordWrap}
}
