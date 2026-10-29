import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

import "MarketFormat.js" as Format

Item {
    id:root;objectName:"marketCollectionPassport"
    property var collection:({})
    property var state:({})
    property bool busy:false
    readonly property bool hasCollection:!!collection.id
    readonly property bool matchingDetail:(state.selected || {}).id===collection.id
    readonly property bool detailFailed:!!collection.detail_error || matchingDetail && !!state.detail_error
    readonly property bool detailRead:collection.detail_state==="CURRENT" || collection.detail_state==="STALE"
    signal inspectRequested(var binding)
    signal copyRequested(string reference)
    implicitHeight:body.height+12;height:implicitHeight
    component PassLabel:GGText {width:parent.width;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;wrapMode:Text.WordWrap}
    component PassRule:Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    component Fact:Column {id:fact;property string label:"";property string value:"";width:parent.width;spacing:4
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.1";text:fact.label;color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.2";text:fact.value;color:RuntimeTheme.GGTheme.text;wrapMode:Text.WrapAnywhere}
    }
    Column {id:body;width:parent.width;spacing:10
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.3";height:22;text:"SAMLINGSPASS";font.pixelSize:11;font.letterSpacing:.7;color:RuntimeTheme.GGTheme.muted}
        PassRule { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.PassRule.1";}
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.4";text:root.collection.name || "Välj en samling";font.pixelSize:21;font.bold:true;color:RuntimeTheme.GGTheme.bright}
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.5";text:root.hasCollection ? String(root.collection.platform || "Okänt nätverk")+" · "+String(root.collection.source || "Publik källa") : "Utforska bilder och referenser från den publika katalogen.";color:RuntimeTheme.GGTheme.muted}
        Rectangle {width:parent.width;height:Math.max(130,Math.min(210,parent.width*.72));color:RuntimeTheme.GGTheme.canvas;clip:true
            Image {id:photo;objectName:"publicPassportImage";anchors.fill:parent;source:root.collection.image_url || "";sourceSize.width:640;sourceSize.height:480;fillMode:Image.PreserveAspectFit;asynchronous:true}
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.6";anchors.centerIn:parent;width:parent.width-24;visible:!root.collection.image_url || photo.status===Image.Loading || photo.status===Image.Error;text:photo.status===Image.Loading ? "Läser samlingsbild…" : photo.status===Image.Error || root.collection.image_error ? "Bilden kunde inte läsas" : root.busy ? "Läser samlingsdetaljer…" : root.detailRead ? "Källan saknar samlingsbild" : root.hasCollection ? "Samlingsbild ej hämtad\nVälj samlingen för att läsa detaljer." : "Samlingens bild visas här";horizontalAlignment:Text.AlignHCenter;color:RuntimeTheme.GGTheme.dim}
        }
        PassLabel { colorKey: "ui.MarketplaceCollectionPassport.7";visible:root.detailFailed;text:"Detaljerna kunde inte uppdateras. Sparade uppgifter kan vara äldre.";color:RuntimeTheme.GGTheme.accent}
        Column {width:parent.width;spacing:10;visible:root.hasCollection
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.8";text:"INNEHÅLL";font.pixelSize:11;font.letterSpacing:.6;color:RuntimeTheme.GGTheme.bright}
            PassRule { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.PassRule.2";}
            Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.3";label:"TYP";value:"NFT-samling · publik referens"}
            Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.4";label:"UTBUD";value:root.collection.total_supply!==null && root.collection.total_supply!==undefined && String(root.collection.total_supply)!=="" ? String(root.collection.total_supply) : "Ej hämtat"}
            Row {width:parent.width;spacing:10
                Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.5";width:(parent.width-10)/2;label:"GOLVPRIS";value:root.collection.floor_usd!==null && root.collection.floor_usd!==undefined ? Format.money(root.collection.floor_usd) : "Ej hämtat"}
                Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.6";width:(parent.width-10)/2;label:"VOLYM · 24 H";value:root.collection.volume_24h_usd!==null && root.collection.volume_24h_usd!==undefined ? Format.compact(root.collection.volume_24h_usd) : "Ej hämtad"}
            }
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.9";visible:!!root.collection.description;text:root.collection.description || "";color:RuntimeTheme.GGTheme.muted}
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.10";text:"URSPRUNG / REFERENS";font.pixelSize:11;font.letterSpacing:.6;color:RuntimeTheme.GGTheme.bright;topPadding:6}
            PassRule { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.PassRule.7";}
            Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.8";label:"NÄTVERK";value:root.collection.chain_id || root.collection.platform || "Ej identifierat"}
            Fact { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.Fact.9";label:root.collection.collection ? "KONTRAKT / SAMLING" : "SAMLINGS-ID";value:root.collection.collection || root.collection.provider_id || "Ej angivet"}
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.11";text:"KVITTO / ÄGANDE";font.pixelSize:11;font.letterSpacing:.6;color:RuntimeTheme.GGTheme.bright;topPadding:6}
            PassRule { property string uiColorScope: "ui.widget.MarketplaceCollectionPassport.PassRule.10";}
            PassLabel { colorKey: "ui.MarketplaceCollectionPassport.12";text:"Ingen säljorder, transaktion eller ägare verifieras av katalogen.";color:RuntimeTheme.GGTheme.muted}
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceCollectionPassport.1";objectName:"publicInspectCollection";width:parent.width;text:root.collection.can_inspect ? "Inspektera en token →" : "Inspektionsadapter saknas";font.pixelSize:11;enabled:!root.busy && root.collection.can_inspect===true;onClicked:root.inspectRequested({chain_id:root.collection.chain_id,standard:root.collection.standard || "erc721",collection:root.collection.collection,token_id:""})}
            CryptoButton { property string uiColorScope: "ui.control.MarketplaceCollectionPassport.2";objectName:"publicCopyCollection";width:parent.width;text:"Kopiera referens";font.pixelSize:11;quiet:true;enabled:!!(root.collection.collection || root.collection.provider_id);onClicked:root.copyRequested(root.collection.collection || root.collection.provider_id)}
        }
    }
}
