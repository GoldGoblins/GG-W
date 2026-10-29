import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Rectangle {
    id:root
    objectName:"marketplaceVisualPassport"
    property var receipt:({})
    property string section:"identity"
    property bool technical:false
    property var selectedPart:null
    property string shownId:""
    readonly property bool narrow:width<620
    readonly property var parts:receipt.composition || []
    readonly property real partsMass:parts.reduce(function(total,p){return total+Number(p.mass_g || 0)},0)
    readonly property var transaction:(receipt.transaction_receipt || {}).body || ({})
    readonly property var nodes:[
        {id:"identity",label:"Översikt",detail:String(receipt.title || "Välj ett objekt"),hint:String(receipt.collection_name || "Enskilt objekt")},
        {id:"materials",label:"Innehåll",detail:receipt.kind==="SERVICE" ? "Tjänstens omfattning" : receipt.material==="UNKNOWN" ? "Material ej angivet" : String(receipt.material || "Material ej angivet"),hint:parts.length+" registrerade delar"},
        {id:"origin",label:"Ursprung",detail:String(receipt.origin || "Ej angivet"),hint:String(receipt.maker || "Producent ej angiven")},
        {id:"history",label:"Tidigare liv",detail:String((receipt.previous_lives || []).length)+" kopplade objekt",hint:"Följ objektet och dess delar bakåt"},
        {id:"transaction",label:"Kvitto",detail:transaction.schema ? "Dokumenterat paperköp" : "Ingen transaktion ännu",hint:transaction.schema ? "Betalning simulerad" : "Objektet är registrerat"}
    ]
    readonly property var detail:nodes.filter(function(n){return n.id===root.section})[0] || nodes[0]
    signal objectRequested(string objectId)
    signal nftRequested(var binding)
    onReceiptChanged:if(String(receipt.id || "")!==shownId){shownId=String(receipt.id || "");section="identity";selectedPart=null;Qt.callLater(function(){photo.resetView()})}
    width:parent ? parent.width : 760
    height:implicitHeight;implicitHeight:body.height+28
    radius:5;color:RuntimeTheme.GGTheme.base;border.color:RuntimeTheme.GGTheme.line
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:12;textFormat:Text.PlainText;wrapMode:Text.WordWrap}
    Column {
        id:body;x:14;y:14;width:parent.width-28;spacing:12
        Label { colorKey: "ui.MarketplacePassport.1";width:parent.width;text:"OBJEKTPASS / GG-721";color:RuntimeTheme.GGTheme.accent;font.pixelSize:10;font.letterSpacing:1.8}
        Label { colorKey: "ui.MarketplacePassport.2";width:parent.width;text:String(root.receipt.title || "Objektets pass");font.pixelSize:22;font.bold:true;color:RuntimeTheme.GGTheme.bright}
        Label { colorKey: "ui.MarketplacePassport.3";width:parent.width;text:String(root.receipt.price_label || "Pris ej angivet")+"  ·  "+({LISTED:"Till salu",SOLD:"Dokumenterat köp",DELISTED:"Avpublicerat"}[root.receipt.status] || "Registrerat objekt");color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
        Item {
            id:exploration;width:parent.width
            height:root.narrow ? imageStage.height+inspector.height+12 : Math.max(imageStage.height,inspector.height)
            Rectangle {
                id:imageStage;objectName:"marketObjectStage";width:root.narrow ? parent.width : parent.width-Math.min(248,parent.width*.36)-12
                height:root.narrow ? 290 : 385;radius:4;color:RuntimeTheme.GGTheme.canvas;border.color:RuntimeTheme.GGTheme.line;clip:true
                KnowledgeRasterView { property string uiColorScope: "ui.widget.MarketplacePassport.KnowledgeRasterView.1";
                    id:photo;objectName:"marketObjectImage";anchors.fill:parent;anchors.margins:8;anchors.topMargin:40;anchors.bottomMargin:50
                    imageSource:root.receipt.image_url || "";visible:!!root.receipt.image_url;hotspots:[]
                }
                Label { colorKey: "ui.MarketplacePassport.4";anchors.centerIn:parent;width:parent.width-48;visible:!root.receipt.image_url;text:"Bild saknas\n\n"+(root.receipt.kind==="SERVICE" ? "Tjänst" : String(root.receipt.material || "Objekt"));font.pixelSize:18;color:RuntimeTheme.GGTheme.muted;horizontalAlignment:Text.AlignHCenter}
                Row {x:10;y:8;spacing:4
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.1";text:"Översikt";quiet:true;checked:root.section==="identity";onClicked:root.section="identity"}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.2";text:"−";implicitWidth:26;quiet:true;enabled:photo.imageReady;tip:"Zooma ut";onClicked:photo.zoomAt(.8,photo.width/2,photo.height/2)}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.3";text:"+";implicitWidth:26;quiet:true;enabled:photo.imageReady;tip:"Zooma in";onClicked:photo.zoomAt(1.25,photo.width/2,photo.height/2)}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.4";text:"↺";implicitWidth:26;quiet:true;enabled:photo.imageReady;tip:"Återställ bilden";onClicked:photo.resetView()}
                }
                Repeater {
                    model:root.nodes.slice(1)
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.5";
                        required property int index;required property var modelData
                        objectName:"marketObjectPoint";width:Math.min(125,(imageStage.width-28)/2);height:30
                        x:index%2===0 ? 10 : imageStage.width-width-10;y:index<2 ? 53 : imageStage.height-height-10
                        text:modelData.label;quiet:true;checked:root.section===modelData.id;tip:modelData.hint
                        onClicked:root.section=modelData.id
                    }
                }
            }
            Rectangle {
                id:inspector;x:root.narrow ? 0 : imageStage.width+12;y:root.narrow ? imageStage.height+12 : 0
                width:root.narrow ? parent.width : parent.width-x;height:inspectorBody.height+28;radius:4;color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.line
                Column {
                    id:inspectorBody;x:14;y:14;width:parent.width-28;spacing:12
                    Label { colorKey: "ui.MarketplacePassport.5";width:parent.width;text:root.detail.label.toUpperCase();color:RuntimeTheme.GGTheme.accent;font.pixelSize:10;font.letterSpacing:1.5}
                    Label { colorKey: "ui.MarketplacePassport.6";width:parent.width;text:root.detail.detail;font.pixelSize:15;font.bold:true;color:RuntimeTheme.GGTheme.bright}
                    Label { colorKey: "ui.MarketplacePassport.7";width:parent.width;text:root.detail.hint;color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
                    Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                    Label { colorKey: "ui.MarketplacePassport.8";width:parent.width;visible:root.section==="identity";text:String(root.receipt.description || "Beskrivning saknas.")}
                    Label { colorKey: "ui.MarketplacePassport.9";width:parent.width;visible:root.section==="origin";text:"Ursprung och producent är registrerade uppgifter, inte oberoende verifierade.";color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
                    Label { colorKey: "ui.MarketplacePassport.10";width:parent.width;visible:root.section==="materials";text:root.receipt.kind==="SERVICE" ? "Omfattning och leverans beskrivs i tjänstens uppgifter." : (root.receipt.mass_g>0 ? "Angiven massa: "+root.receipt.mass_g+" g. " : "Totalmassa ej angiven. ")+"Deklarerade delar: "+root.partsMass+" g. Uppgifterna är inte en fullständig materialanalys.";color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
                    Flow {width:parent.width;spacing:6;visible:root.section==="materials"
                        Repeater {model:root.parts
                            CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.6";required property var modelData;objectName:"marketMaterialPart";text:String(modelData.symbol || modelData.title || "Del")+" · "+String(modelData.mass_g || 0)+" g";quiet:true;onClicked:{root.selectedPart=modelData;if(modelData.id)root.objectRequested(modelData.id)}}
                        }
                    }
                    Label { colorKey: "ui.MarketplacePassport.11";width:parent.width;visible:root.section==="materials" && !!root.selectedPart;text:root.selectedPart ? String(root.selectedPart.title || root.selectedPart.symbol)+" · "+(root.selectedPart.id ? "Länkat objekt" : "Deklarerad del, eget kvitto saknas") : "";color:RuntimeTheme.GGTheme.accent}
                    Label { colorKey: "ui.MarketplacePassport.12";width:parent.width;visible:root.section==="history" && !(root.receipt.previous_lives || []).length;text:"Inga tidigare objekt har kopplats till detta pass.";color:RuntimeTheme.GGTheme.muted}
                    Flow {width:parent.width;spacing:6;visible:root.section==="history"
                        Repeater {model:root.receipt.previous_lives || []
                            CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.7";required property string modelData;quiet:true;text:"Öppna "+modelData.slice(0,14);onClicked:root.objectRequested(modelData)}
                        }
                    }
                    Label { colorKey: "ui.MarketplacePassport.13";width:parent.width;visible:root.section==="transaction";text:root.transaction.schema ? "Från: "+String(root.transaction.seller || "Ej angivet")+"\nTill: "+String(root.transaction.buyer || "Ej angivet")+"\nRegistrerat: "+new Date(root.transaction.recorded_at*1000).toLocaleString()+"\nPris: "+String(root.receipt.price_label || "—")+"\n\nBetalning simulerad. Leverans ej verifierad." : "Ett separat transaktionskvitto skapas när ett paperköp dokumenteras."}
                    Label { colorKey: "ui.MarketplacePassport.14";width:parent.width;visible:!!root.receipt.nft_binding && (root.section==="identity" || root.section==="origin");text:root.receipt.nft_binding ? "NFT-referens · "+root.receipt.nft_binding.standard+"\n"+root.receipt.nft_binding.chain_id+"\nÄgande kontrolleras separat." : "";font.pixelSize:10;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WrapAnywhere}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplacePassport.8";visible:!!root.receipt.nft_binding && (root.section==="identity" || root.section==="origin");text:"Kontrollera NFT";quiet:true;onClicked:root.nftRequested(root.receipt.nft_binding)}
                }
            }
        }
        Label { colorKey: "ui.MarketplacePassport.15";width:parent.width;text:root.receipt.image_url ? "Objektbild · zooma och dra för att utforska. Markeringarna öppnar passets registrerade uppgifter." : "Lägg till en objektbild vid registrering för att göra passet lättare att känna igen.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
        CryptoToggle { property string uiColorScope: "ui.control.MarketplacePassport.9";text:"Tekniska kvittodetaljer";checked:root.technical;onClicked:root.technical=checked}
        Label { colorKey: "ui.MarketplacePassport.16";width:parent.width;visible:root.technical;font.pixelSize:10;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WrapAnywhere;text:"GG-721 · lokalt paper\nObjekt: "+String(root.receipt.id || "")+"\nNätverk: "+String(root.receipt.network || "")+"\nTillgång: "+String(root.receipt.settlement_asset_id || "SOL legacy")+"\nBildens innehåll och uppgifter binds till objektets identitet."}
    }
}
