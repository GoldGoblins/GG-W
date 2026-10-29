import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id:root
    property var receipt:({})
    property var listings:[]
    property bool busy:false
    property string shownId:""
    readonly property bool hasReceipt:!!receipt.id
    readonly property var transaction:(receipt.transaction_receipt || {}).body || ({})
    readonly property var parts:receipt.composition || []
    readonly property var materialNames:({WOOD:"Trä",METAL:"Metall",STONE:"Sten",FABRIC:"Textil",DIGITAL:"Digitalt",MIXED:"Blandat",UNKNOWN:"Material ej angivet",GOLD:"Guld",SILVER:"Silver",COPPER:"Koppar"})
    readonly property var treeNodes:buildTree()
    signal objectRequested(string id)
    signal nftRequested(var binding)
    signal registerRequested()
    implicitHeight:body.height+18;height:implicitHeight
    function labelMaterial(value){return Object.prototype.hasOwnProperty.call(materialNames,value) ? materialNames[value] : value || "Material ej angivet"}
    function find(id){for(var i=0;i<listings.length;i++)if(listings[i].id===id)return listings[i];return null}
    function leaf(label,extra){return Object.assign({label:label},extra || {})}
    function buildTree(){
        if(!hasReceipt)return [
            {key:"contents",heading:true,icon:"▧",label:"INNEHÅLL",children:[leaf("Beskriv föremålet eller tjänsten och dess delar.",{muted:true})]},
            {key:"origin",heading:true,icon:"♧",label:"URSPRUNG",children:[leaf("Lägg till producent, plats och tidigare liv.",{muted:true})]},
            {key:"receipt",heading:true,icon:"▤",label:"KVITTO",children:[leaf("Transaktion och kvittoreferens visas när de registreras.",{muted:true})]}
        ]
        var composition=parts.map(function(part,index){var source=find(part.id);return {key:"part-"+index,label:String(part.title || part.symbol || "Del")+(part.mass_g>0 ? " · "+part.mass_g+" g" : ""),children:[leaf("Material: "+labelMaterial(part.symbol)),source ? leaf("Öppna delens pass",{objectId:source.id}) : leaf(part.id ? "Referens: "+part.id+" · pass ej i biblioteket" : "Eget delkvitto saknas",{muted:true})]}})
        if(!composition.length)composition=[leaf(receipt.kind==="SERVICE" ? "Omfattning: "+String(receipt.description || "ej angiven") : "Inga delar registrerade.",{muted:true})]
        var contents=[{key:"object-content",label:String(receipt.title || "Objekt")+(receipt.mass_g>0 ? " · "+receipt.mass_g+" g" : ""),children:[leaf(labelMaterial(receipt.material))].concat(composition)}]
        var origin=[{key:"object-origin",label:String(receipt.title || "Objekt"),children:[leaf("Lokalt registrerat"),leaf("Ursprung: "+String(receipt.origin || "ej angivet")),leaf("Producent: "+String(receipt.maker || "ej angiven")),leaf("Deklarerade uppgifter · ej oberoende verifierade",{muted:true})]}]
        parts.forEach(function(part,index){var source=find(part.id);if(source)origin.push({key:"part-origin-"+index,label:String(part.title || source.title),children:[leaf("Ursprung: "+String(source.origin || "ej angivet")),leaf("Producent: "+String(source.maker || "ej angiven")),leaf("Öppna delens pass",{objectId:source.id})]})})
        var history=(receipt.previous_lives || []).map(function(id){var source=find(id);return source ? leaf(source.title,{objectId:id}) : leaf("Referens: "+id+" · pass ej i biblioteket",{muted:true})})
        if(!history.length)history=[leaf("Inga tidigare liv kopplade.",{muted:true})]
        var acquisition=transaction.schema ? [leaf("Registrerat: "+new Date(transaction.recorded_at*1000).toLocaleString()),leaf("Pris: "+String(receipt.price_label || "ej angivet")),leaf("Från: "+String(transaction.seller || "ej angivet")),leaf("Till: "+String(transaction.buyer || "ej angivet")),leaf("Betalning simulerad · inga medel flyttade",{accent:true}),leaf("Leverans ej verifierad",{muted:true})] : [leaf("Ingen transaktion registrerad.",{muted:true}),leaf("Begärt pris: "+String(receipt.price_label || "ej angivet"))]
        var receiptNodes=[leaf("Status: "+({LISTED:"Till salu",SOLD:"Dokumenterat paperköp",DELISTED:"Avpublicerat"}[receipt.status] || "Lokalt registrerat")),{key:"owner",label:"Ägare / kvittoroll",children:[leaf(String(receipt.owner || "Ägare ej angiven"))]},{key:"acquisition",label:"Förvärv",children:acquisition},{key:"lives",label:"Tidigare liv",children:history},{key:"technical",label:"Tekniska referenser",children:[leaf("GG-721 · lokalt paper"),leaf("Objekt: "+String(receipt.id || "ej angivet")),leaf("Nätverk: "+String(receipt.network || "ej angivet")),leaf("Kvittoreferens: "+String(receipt.receipt || "ej angiven"))]}]
        return [{key:"contents",heading:true,icon:"▧",label:"INNEHÅLL",children:contents},{key:"origin",heading:true,icon:"♧",label:"URSPRUNG",children:origin},{key:"receipt",heading:true,icon:"▤",label:"KVITTO",children:receiptNodes}]
    }
    onReceiptChanged:if(String(receipt.id || "")!==shownId){shownId=String(receipt.id || "");if(tree)tree.collapsed=({technical:true})}
    component Label:GGText {width:parent.width;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:12;textFormat:Text.PlainText;wrapMode:Text.WordWrap}
    Column {id:body;width:parent.width;spacing:6
        Row {width:parent.width;height:22;spacing:6
            Label { colorKey: "ui.MarketplaceObjectPassport.1";width:Math.max(70,parent.width-ref.width-6);text:"FÖREMÅLSPASS";font.pixelSize:13;font.letterSpacing:.7;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.MarketplaceObjectPassport.2";id:ref;width:76;text:root.receipt.id ? String(root.receipt.id).slice(-6) : "";font.pixelSize:12;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
        }
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        Label { colorKey: "ui.MarketplaceObjectPassport.3";text:String(root.receipt.title || "Välj ett objekt");font.pixelSize:20;font.bold:true;color:RuntimeTheme.GGTheme.bright}
        Label { colorKey: "ui.MarketplaceObjectPassport.4";visible:root.hasReceipt;text:(root.receipt.kind==="SERVICE" ? "Tjänst" : root.labelMaterial(root.receipt.material))+(root.receipt.collection_name ? " · "+root.receipt.collection_name : "");color:RuntimeTheme.GGTheme.muted;font.pixelSize:13}
        Label { colorKey: "ui.MarketplaceObjectPassport.5";text:root.hasReceipt ? "Lokalt dokumenterat · deklarerade uppgifter" : "Här samlas bild, innehåll, ursprung och kvitto för det objekt du väljer.";color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
        Rectangle {width:parent.width;height:Math.min(root.hasReceipt ? 215 : 140,parent.width*.62);color:RuntimeTheme.GGTheme.canvas;clip:true
            Image {id:photo;anchors.fill:parent;source:root.receipt.image_url || "";sourceSize.width:800;sourceSize.height:600;fillMode:Image.PreserveAspectFit;asynchronous:true}
            Label { colorKey: "ui.MarketplaceObjectPassport.6";anchors.centerIn:parent;width:parent.width-28;visible:!root.receipt.image_url || photo.status===Image.Error || photo.status===Image.Loading;text:!root.hasReceipt ? "Objektets bild visas här" : photo.status===Image.Loading ? "Läser lokal objektbild…" : "Ingen objektbild tillgänglig\nPassets registrerade uppgifter visas nedan.";horizontalAlignment:Text.AlignHCenter;color:RuntimeTheme.GGTheme.dim;font.pixelSize:13}
        }
        MarketplaceReceiptTree { property string uiColorScope: "ui.widget.MarketplaceObjectPassport.MarketplaceReceiptTree.1";id:tree;width:parent.width;nodes:root.treeNodes;busy:root.busy;onObjectRequested:function(id){root.objectRequested(id)}}
        Label { colorKey: "ui.MarketplaceObjectPassport.7";visible:!!root.receipt.description;text:String(root.receipt.description || "");color:RuntimeTheme.GGTheme.muted;font.pixelSize:13}
        CryptoButton { property string uiColorScope: "ui.control.MarketplaceObjectPassport.1";objectName:"marketRegisterFromPass";visible:!root.hasReceipt;width:parent.width;text:"+ Registrera objekt med bild";quiet:true;enabled:!root.busy;onClicked:root.registerRequested()}
        CryptoButton { property string uiColorScope: "ui.control.MarketplaceObjectPassport.2";objectName:"marketOpenObjectPass";visible:root.hasReceipt;width:parent.width;text:"Öppna hela passet / kvittot →";quiet:true;enabled:!root.busy && root.hasReceipt;onClicked:root.objectRequested(root.receipt.id)}
        CryptoButton { property string uiColorScope: "ui.control.MarketplaceObjectPassport.3";visible:!!root.receipt.nft_binding;width:parent.width;text:"Kontrollera NFT-referens";quiet:true;enabled:!root.busy;onClicked:root.nftRequested(root.receipt.nft_binding)}
    }
}
