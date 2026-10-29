import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id:root;objectName:"marketPublicCategories"
    property var rows:[]
    property string networkFilter:""
    property string provider:"coingecko"
    property string sourceState:"NOT_FETCHED"
    property real observedAt:0
    property bool busy:false
    property var previewJob:({})
    readonly property var networks:{var found={};rows.forEach(function(row){var key=row.network_key || row.chain_id || "platform:"+String(row.platform || "Okänt nätverk");if(!found[key])found[key]={id:key,name:String(row.platform || "Okänt nätverk"),count:0};found[key].count++});return Object.keys(found).map(function(key){return found[key]}).sort(function(a,b){return a.name.localeCompare(b.name)})}
    signal networkRequested(string network)
    component NetworkLabel:GGText {width:parent.width;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;elide:Text.ElideRight}
    Flickable {anchors.fill:parent;clip:true;contentWidth:width;contentHeight:body.height;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
        Column {id:body;width:parent.width;spacing:20
            NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.1";height:28;text:"KATEGORIER";color:RuntimeTheme.GGTheme.muted;font.pixelSize:11;font.letterSpacing:.7}
            Column {width:parent.width;spacing:4
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.2";height:25;text:"SAMLINGAR";color:RuntimeTheme.GGTheme.bright;font.pixelSize:12;font.letterSpacing:.5}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceNetworkTree.1";objectName:"publicAllCollections";width:parent.width;height:34;flat:true;leftPadding:8;rightPadding:26;horizontalAlignment:Text.AlignLeft;checked:!root.networkFilter;enabled:!root.busy;text:"Alla samlingar";font.pixelSize:10;color:checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text;onClicked:root.networkRequested("")
                    NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.3";anchors.right:parent.right;anchors.rightMargin:5;width:34;height:parent.height;verticalAlignment:Text.AlignVCenter;horizontalAlignment:Text.AlignRight;text:String(root.rows.length);font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
                    Rectangle { GGColorTarget { colorKey: "ui.fill.MarketplaceNetworkTree.1"; }width:2;height:parent.height-10;y:5;visible:parent.checked;color:RuntimeTheme.GGTheme.accent}
                }
            }
            Column {width:parent.width;spacing:4
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.4";height:25;text:"NÄTVERK";color:RuntimeTheme.GGTheme.bright;font.pixelSize:12;font.letterSpacing:.5}
                Repeater {model:root.networks
                    CryptoButton { property string uiColorScope: "ui.control.MarketplaceNetworkTree.2";required property var modelData;objectName:"publicNetworkCategory";property string networkId:modelData.id;width:parent.width;height:34;flat:true;leftPadding:10;rightPadding:38;horizontalAlignment:Text.AlignLeft;checked:root.networkFilter===modelData.id;enabled:!root.busy;text:modelData.name;font.pixelSize:11;color:checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text;tip:modelData.name+" · "+modelData.count+" samlingar på sidan";onClicked:root.networkRequested(modelData.id)
                        NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.5";anchors.right:parent.right;anchors.rightMargin:5;width:32;height:parent.height;verticalAlignment:Text.AlignVCenter;horizontalAlignment:Text.AlignRight;text:String(parent.modelData.count);font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
                        Rectangle { GGColorTarget { colorKey: "ui.fill.MarketplaceNetworkTree.2"; }width:2;height:parent.height-10;y:5;visible:parent.checked;color:RuntimeTheme.GGTheme.accent}
                    }
                }
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.6";visible:root.networks.length===0;text:"Inga nätverk i katalogen.";height:40;wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.dim}
            }
            Column {width:parent.width;spacing:8
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.7";height:25;text:"KÄLLA";color:RuntimeTheme.GGTheme.bright;font.pixelSize:12;font.letterSpacing:.5}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.8";text:root.provider==="kat" ? "KAT · KRC-721" : "CoinGecko NFT-katalog";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.9";text:({CURRENT:"Avläst katalog",STALE:"Äldre katalog",FAILED:"Källan kunde inte läsas",NOT_FETCHED:"Inte hämtad"})[root.sourceState] || "Status saknas";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:root.sourceState==="FAILED" ? RuntimeTheme.GGTheme.negative : root.sourceState==="CURRENT" ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.accent}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.10";visible:root.observedAt>0;text:root.observedAt>0 ? new Date(root.observedAt*1000).toLocaleString() : "";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.11";text:"Antal gäller den inlästa katalogsidan.";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.12";visible:Number(root.previewJob.total || 0)>0;text:"BILDLÄSNING · "+({running:"PÅGÅR",done:"KLAR",partial:"DELVIS KLAR",cancelled:"STOPPAD",failed:"MISSLYCKAD"}[root.previewJob.state] || "STATUS SAKNAS");wrapMode:Text.WordWrap;elide:Text.ElideNone;color:root.previewJob.failed || root.previewJob.error ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted;font.pixelSize:10;topPadding:10}
                NetworkLabel { colorKey: "ui.MarketplaceNetworkTree.13";visible:Number(root.previewJob.total || 0)>0;text:String(root.previewJob.completed || 0)+" av "+String(root.previewJob.total || 0)+" kontrollerade\n"+String(root.previewJob.images || 0)+" bilder · "+String(root.previewJob.failed || 0)+" fel";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
            }
        }
    }
}
