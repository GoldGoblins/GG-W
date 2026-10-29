import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

import "MarketFormat.js" as Format

Item {
    id:root;objectName:"walletTelemetry"
    property var state:({})
    property var accounts:[]
    property string accountId:""
    property string chainId:""
    property bool showAccounts:true
    property bool accountsExpanded:true
    property bool protectionExpanded:true
    property bool networksExpanded:true
    property bool eventsExpanded:true
    readonly property var wallet:state.wallet_overview || ({})
    readonly property var selectedAccount:(wallet.accounts || []).filter(function(a){return a.id===root.accountId})[0] || ({})
    readonly property var localKey:(wallet.local_wallets || []).filter(function(a){return a.account_id===root.accountId && !!root.selectedAccount.address && a.pubkey===root.selectedAccount.address})[0] || ({})
    readonly property bool localVaultAvailable:!!localKey.pubkey && localKey.vault_available===true
    readonly property var networks:(wallet.networks || []).filter(function(n){return (root.selectedAccount.chain_id ? n.id===root.selectedAccount.chain_id : !root.chainId || n.id===root.chainId) && (wallet.accounts || []).some(function(a){return a.chain_id===n.id})})
    readonly property var events:(wallet.events || []).slice(-14).reverse()
    readonly property var operation:state.ui_operation || ({})
    readonly property bool operationVisible:operation.state==="running" || operation.state==="approval_required" || !!operation.error
    readonly property bool walletMode:!showAccounts && !!accountId
    readonly property bool compact:width<330
    readonly property real inset:compact ? 16 : 22
    signal accountRequested(string id)
    signal activityRequested()
    function summary(id){return (wallet.account_summaries || {})[id] || ({})}
    function networkName(id){var n=(wallet.networks || []).filter(function(n){return n.id===id})[0];return n ? n.name : id}
    function readText(v){return v.failed_count ? v.failed_count+" läsfel" : v.stale_count ? "Äldre saldo" : v.unread_count ? "Ej hämtat" : v.last_read_at ? "Saldo läst" : "Ej hämtat"}
    function readColor(v){return v.failed_count ? RuntimeTheme.GGTheme.negative : v.stale_count ? RuntimeTheme.GGTheme.accent : v.unread_count || !v.last_read_at ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.positive}
    function timeText(value){return value ? new Date(Number(value)*1000).toLocaleTimeString(Qt.locale(),"HH:mm:ss") : "\u2014"}
    function assetSymbol(id){var a=(state.assets || []).filter(function(a){return a.id===id})[0];return a ? a.symbol : "System"}
    function eventTitle(kind){return ({BALANCE_READ:"LÄST",TRANSFER_PREPARED:"SIMULERING KLAR",TRANSFER_CONFIRMED:"BEKRÄFTAD",TRANSFER_FINALIZED:"SLUTLIGT BEKRÄFTAD",TRANSFER_SUBMITTED:"SÄND",TRANSFER_UNCERTAIN:"UTFALL OKÄNT",OVERVIEW_READ_COMPLETED:"SALDON LÄSTA",OVERVIEW_READ_PARTIAL:"DELVIS LÄST",ENCRYPTED_BACKUP_READY:"BACKUP REGISTRERAD",LOCAL_WALLET_READY:"LOKALT VALV REGISTRERAT"})[kind] || String(kind || "HÄNDELSE").replace(/_/g," ")}
    function eventColor(kind){var value=String(kind || "");return /FAIL|ERROR|REJECT/.test(value) ? RuntimeTheme.GGTheme.negative : /UNCERTAIN|PARTIAL|PREPARED|SUBMITTED|APPROVAL|STARTED/.test(value) ? RuntimeTheme.GGTheme.accent : /CONFIRMED|FINALIZED|COMPLETED|BALANCE_READ/.test(value) ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.muted}
    function endpointText(value){
        var endpoint=String(value || "").trim()
        if(!endpoint)return "Ej angiven"
        // Public RPC registration rejects auth, queries and fragments. A stale
        // UI snapshot must not make a credential-bearing endpoint visible.
        if(!/^https:\/\/[^\s/?#@]+(?:\/[^\s?#]*)?$/.test(endpoint))return "Skyddad eller ogiltig endpoint"
        return endpoint.replace(/\/(?:v[23]|key|token|api[-_]?key)\/[^/]+/ig,"/…").replace(/\/[A-Za-z0-9_-]{32,}(?=\/|$)/g,"/…")
    }
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:12;textFormat:Text.PlainText;elide:Text.ElideRight}
    component Rule:Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    component SectionHead:Item {
        id:section
        property string title:""
        property string count:""
        property bool expanded:true
        property bool activity:false
        signal toggleRequested()
        width:parent.width;height:36
        CryptoButton { property string uiColorScope: "ui.control.WalletTelemetry.1";objectName:section.objectName+"Toggle";anchors.left:parent.left;anchors.right:section.activity ? allEvents.left : parent.right;anchors.rightMargin:section.activity ? 4 : 0;height:35;flat:true;quiet:false;leftPadding:0;rightPadding:0;horizontalAlignment:Text.AlignLeft;text:(section.expanded ? "⌄  " : "›  ")+section.title;font.pixelSize:12;tip:(section.expanded ? "Fäll ihop " : "Visa ")+section.title.toLowerCase();Accessible.name:tip;onClicked:section.toggleRequested()}
        Label { colorKey: "ui.WalletTelemetry.1";anchors.right:parent.right;height:35;verticalAlignment:Text.AlignVCenter;visible:!section.activity;text:section.count;color:RuntimeTheme.GGTheme.dim;font.pixelSize:11}
        CryptoButton { property string uiColorScope: "ui.control.WalletTelemetry.2";id:allEvents;objectName:section.activity ? "walletRailAllEvents" : "";anchors.right:parent.right;width:62;implicitWidth:62;height:32;visible:section.activity;flat:true;text:"Visa alla";font.pixelSize:11;leftPadding:0;rightPadding:0;onClicked:root.activityRequested()}
        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    component Fact:Item {
        id:fact
        property string name:""
        property string value:""
        property string iconName:""
        property color valueColor:RuntimeTheme.GGTheme.muted
        width:parent.width;height:Math.max(44,Math.max(factName.implicitHeight,factValue.implicitHeight)+20)
        LedgerGlyph { property string uiColorScope: "ui.widget.WalletTelemetry.LedgerGlyph.3";x:0;y:12;width:18;height:18;viewport:telemetryScroll;name:fact.iconName}
        Label { colorKey: "ui.WalletTelemetry.2";id:factName;x:28;y:12;width:parent.width*.51-32;text:fact.name;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone;font.pixelSize:11}
        Label { colorKey: "ui.WalletTelemetry.3";id:factValue;objectName:"walletFactValue";property string factName:fact.name;x:parent.width*.51;y:12;width:parent.width-x;text:fact.value;horizontalAlignment:Text.AlignRight;color:fact.valueColor;wrapMode:Text.WordWrap;elide:Text.ElideNone;font.pixelSize:11}
        Accessible.role:Accessible.StaticText;Accessible.name:fact.name+": "+fact.value
    }
    Rectangle {width:1;height:parent.height;color:RuntimeTheme.GGTheme.line}
    Flickable {id:telemetryScroll;objectName:"walletTelemetryScroll";x:root.inset;y:14;width:Math.max(0,parent.width-2*root.inset);height:Math.max(0,parent.height-y-12);clip:true;contentWidth:width;contentHeight:body.height;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
        Column {id:body;width:parent.width;spacing:22
            Column {width:parent.width;spacing:0;visible:root.showAccounts
                SectionHead { property string uiColorScope: "ui.widget.WalletTelemetry.SectionHead.4";objectName:"walletAccountsSection";title:"KONTON";count:String(root.accounts.length);expanded:root.accountsExpanded;onToggleRequested:root.accountsExpanded=!root.accountsExpanded}
                Column {width:parent.width;visible:root.accountsExpanded
                    Repeater {model:root.accounts
                        Item {id:accountRow;required property var modelData;readonly property var facts:root.summary(modelData.id);objectName:"walletRailAccount";property string targetAccountId:modelData.id;width:parent.width;height:Math.max(72,accountName.implicitHeight+accountAddress.implicitHeight+30)
                            Rectangle {x:-6;y:4;width:parent.width+12;height:parent.height-8;radius:2;color:RuntimeTheme.GGTheme.hover;visible:accountMouse.containsMouse || accountRow.activeFocus}
                            Rectangle {x:0;y:20;width:7;height:7;radius:4;color:root.readColor(parent.facts)}
                            Label { colorKey: "ui.WalletTelemetry.4";id:accountName;x:18;y:15;width:parent.width*.60-22;text:accountRow.modelData.label || "Konto";font.pixelSize:12;color:RuntimeTheme.GGTheme.bright;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                            Label { colorKey: "ui.WalletTelemetry.5";x:parent.width*.60;y:15;width:parent.width*.40;text:accountRow.facts.known_value_usd===null || accountRow.facts.known_value_usd===undefined ? "\u2014" : Format.exactMoney(accountRow.facts.known_value_usd);horizontalAlignment:Text.AlignRight;font.pixelSize:12;color:RuntimeTheme.GGTheme.bright}
                            Label { colorKey: "ui.WalletTelemetry.6";id:accountAddress;x:18;y:accountName.y+accountName.implicitHeight+7;width:parent.width-18;text:Format.shortAddress(accountRow.modelData.address)+"  "+root.networkName(accountRow.modelData.chain_id);font.pixelSize:11;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                            Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.55}
                            MouseArea {id:accountMouse;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.accountRequested(accountRow.targetAccountId)}
                            ToolTip.visible:accountMouse.containsMouse;ToolTip.delay:600;ToolTip.text:accountRow.modelData.label+"\n"+accountRow.modelData.address+"\n"+root.readText(accountRow.facts)+(accountRow.facts.known_value_usd===null || accountRow.facts.known_value_usd===undefined ? "" : "\n"+Format.exactMoney(accountRow.facts.known_value_usd))
                            activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:modelData.label+" · "+modelData.address+" · "+root.readText(facts);Keys.onReturnPressed:root.accountRequested(targetAccountId);Keys.onSpacePressed:root.accountRequested(targetAccountId)
                        }
                    }
                    Label { colorKey: "ui.WalletTelemetry.7";width:parent.width;topPadding:18;bottomPadding:12;visible:!root.accounts.length;text:"Inga konton tillagda.";color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                }
            }
            Column {width:parent.width;spacing:0;visible:root.walletMode
                SectionHead { property string uiColorScope: "ui.widget.WalletTelemetry.SectionHead.5";objectName:"walletProtectionSection";title:"SKYDD";expanded:root.protectionExpanded;onToggleRequested:root.protectionExpanded=!root.protectionExpanded}
                Column {width:parent.width;visible:root.protectionExpanded
                    Fact { property string uiColorScope: "ui.widget.WalletTelemetry.Fact.6";name:"Krypterad nyckel";iconName:"lock";value:root.localVaultAvailable ? "Windows DPAPI" : root.localKey.pubkey ? "Valv saknas" : "Extern wallet";valueColor:root.localVaultAvailable ? RuntimeTheme.GGTheme.positive : root.localKey.pubkey ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted}
                    Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.7";}
                    Fact { property string uiColorScope: "ui.widget.WalletTelemetry.Fact.8";name:"Lokalt valv";iconName:"vault";value:root.localVaultAvailable ? "Registrerat" : root.localKey.pubkey ? "Saknas" : "Ej lokalt";valueColor:root.localVaultAvailable ? RuntimeTheme.GGTheme.positive : root.localKey.pubkey ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted}
                    Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.9";}
                    Fact { property string uiColorScope: "ui.widget.WalletTelemetry.Fact.10";name:"Krypterad backup";iconName:"backup";value:root.localKey.pubkey ? root.localKey.backed_up===true ? "Registrerad" : "Saknas" : "Extern wallet";valueColor:root.localKey.pubkey ? root.localKey.backed_up===true ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted}
                    Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.11";}
                    Fact { property string uiColorScope: "ui.widget.WalletTelemetry.Fact.12";name:"Signering";iconName:"shield";value:root.localVaultAvailable ? "Kräver godkännande" : root.localKey.pubkey ? "Ej tillgänglig" : "Extern wallet";valueColor:root.localKey.pubkey && !root.localVaultAvailable ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted}
                    Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.13";}
                }
            }
            Column {width:parent.width;spacing:0
                SectionHead { property string uiColorScope: "ui.widget.WalletTelemetry.SectionHead.14";objectName:"walletNetworksSection";title:root.walletMode ? "NÄTVERK" : "KÄLLSTATUS";count:String(root.networks.length);expanded:root.networksExpanded;onToggleRequested:root.networksExpanded=!root.networksExpanded}
                Column {width:parent.width;visible:root.networksExpanded
                    Repeater {model:root.networks
                        Column {id:networkRow;required property var modelData;readonly property var facts:root.accountId ? root.summary(root.accountId) : (root.wallet.network_summaries || {})[modelData.id] || ({});width:parent.width;spacing:0
                            Item {width:parent.width;height:Math.max(66,networkName.implicitHeight+readState.implicitHeight+36)
                                Rectangle {y:19;width:7;height:7;radius:4;color:root.readColor(networkRow.facts)}
                                Label { colorKey: "ui.WalletTelemetry.8";id:networkName;x:18;y:14;width:parent.width*.55-22;text:networkRow.modelData.name;font.pixelSize:12;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                                Label { colorKey: "ui.WalletTelemetry.9";id:readState;x:parent.width*.55;y:14;width:parent.width*.45;text:root.readText(networkRow.facts);color:root.readColor(networkRow.facts);font.pixelSize:11;horizontalAlignment:Text.AlignRight;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                                Label { colorKey: "ui.WalletTelemetry.10";x:18;y:Math.max(networkName.implicitHeight,readState.implicitHeight)+22;width:parent.width-18;text:networkRow.facts.last_read_at ? "Avläst "+root.timeText(networkRow.facts.last_read_at) : "Ingen avläsning registrerad";font.pixelSize:10;color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                            }
                            Column {objectName:"walletNetworkEndpoint";width:parent.width;spacing:6;bottomPadding:14;visible:root.walletMode
                                Row {width:parent.width;spacing:10
                                    LedgerGlyph { property string uiColorScope: "ui.widget.WalletTelemetry.LedgerGlyph.15";width:16;height:16;viewport:telemetryScroll;name:"endpoint"}
                                    Label { colorKey: "ui.WalletTelemetry.11";text:"RPC-ENDPOINT";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10;font.letterSpacing:.5}
                                }
                                Label { colorKey: "ui.WalletTelemetry.12";objectName:"walletEndpointValue";width:parent.width;text:root.endpointText(networkRow.modelData.endpoint);font.pixelSize:11;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WrapAnywhere;elide:Text.ElideNone;Accessible.name:"RPC-endpoint: "+text}
                            }
                            Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.16";}
                        }
                    }
                    Label { colorKey: "ui.WalletTelemetry.13";width:parent.width;topPadding:18;bottomPadding:12;visible:!root.networks.length;text:"Inga saldokällor registrerade.";color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                }
            }
            Column {objectName:"walletCurrentOperation";width:parent.width;spacing:10;visible:root.operationVisible
                Label { colorKey: "ui.WalletTelemetry.14";width:parent.width;text:root.operation.state==="running" ? "PÅGÅENDE" : root.operation.state==="approval_required" ? "VÄNTAR PÅ GODKÄNNANDE" : "SENASTE ÅTGÄRD";font.pixelSize:11;color:root.operation.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Rule { property string uiColorScope: "ui.widget.WalletTelemetry.Rule.17";}
                Label { colorKey: "ui.WalletTelemetry.15";width:parent.width;text:({refresh_wallet:"Saldon och priser",refresh_balance:"Saldokontroll",prepare_transfer:"Överföring · förberedelse",send_transfer:"Överföring · sändning",check_transfer:"Transaktionskontroll",create_wallet:"Ny lokal wallet",backup_wallet:"Krypterad säkerhetskopia",restore_wallet:"Återställning av wallet"})[root.operation.name] || String(root.operation.name || "Walletåtgärd").replace(/_/g," ");color:RuntimeTheme.GGTheme.text;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Label { colorKey: "ui.WalletTelemetry.16";objectName:"walletCurrentOperationState";width:parent.width;text:root.operation.error ? String(root.operation.error) : root.operation.state==="approval_required" ? "Godkänn eller avvisa i chatten för att fortsätta." : "Åtgärden körs. Status visas när svaret kommer.";color:root.operation.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone;font.pixelSize:11}
            }
            Column {width:parent.width;spacing:0
                SectionHead { property string uiColorScope: "ui.widget.WalletTelemetry.SectionHead.18";objectName:"walletEventsSection";title:root.walletMode ? "HÄNDELSEFLÖDE" : "HÄNDELSER";activity:true;expanded:root.eventsExpanded;onToggleRequested:root.eventsExpanded=!root.eventsExpanded}
                Column {width:parent.width;visible:root.eventsExpanded
                    Label { colorKey: "ui.WalletTelemetry.17";width:parent.width;topPadding:10;bottomPadding:14;text:"Alla konton · lokalt registrerade";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                    Repeater {model:root.events
                        Item {id:eventRow;required property var modelData;objectName:"walletRailEvent";width:parent.width;height:eventBody.height+(root.walletMode ? 20 : 14)
                            Rectangle {x:3;y:0;width:1;height:parent.height;visible:root.walletMode;color:RuntimeTheme.GGTheme.line}
                            Rectangle {x:0;y:5;width:7;height:7;radius:4;visible:root.walletMode;color:root.eventColor(eventRow.modelData.kind)}
                            Column {id:eventBody;x:root.walletMode ? 20 : 0;width:parent.width-x;spacing:6
                                Item {width:parent.width;height:Math.max(eventTime.implicitHeight,eventTitle.implicitHeight)
                                    Label { colorKey: "ui.WalletTelemetry.18";id:eventTime;width:62;text:root.timeText(eventRow.modelData.ts);font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
                                    Label { colorKey: "ui.WalletTelemetry.19";id:eventTitle;x:70;width:parent.width-x;text:root.walletMode ? root.eventTitle(eventRow.modelData.kind) : root.assetSymbol(eventRow.modelData.asset_id);font.pixelSize:10;color:root.eventColor(eventRow.modelData.kind);wrapMode:Text.WordWrap;elide:Text.ElideNone}
                                }
                                Label { colorKey: "ui.WalletTelemetry.20";objectName:"walletEventMessage";width:parent.width;text:eventRow.modelData.message || root.eventTitle(eventRow.modelData.kind);font.pixelSize:11;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                            }
                            Accessible.role:Accessible.StaticText;Accessible.name:root.timeText(modelData.ts)+" "+root.eventTitle(modelData.kind)+": "+(modelData.message || "")
                        }
                    }
                    Label { colorKey: "ui.WalletTelemetry.21";width:parent.width;visible:!root.events.length;text:"Inga händelser registrerade.";color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                }
            }
        }
    }
}
