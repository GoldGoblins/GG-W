import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window

import "MarketFormat.js" as Format

Item {
    id:root;objectName:"walletActions"
    property var surfaceHost:null
    property string creationPublicAddress:""
    property var state:({})
    property string page:""
    property string accountId:""
    property string assetId:""
    property string actionMode:"receive"
    property string internalAccountId:""
    property var accountRoles:({})
    property string ownTargetRole:""
    property bool previewSuppressed:false
    property var preparingIntent:({})
    property bool watching:false
    property int checks:0
    property string baselineAtomic:""
    property bool reviewed:false
    property string reviewedDigest:""
    property string reviewedTransferId:""
    property string pendingAction:""
    property string requestedTransferId:""
    property real watchDeadline:0
    property real now:Date.now()/1000
    readonly property var wallet:state.wallet_overview || ({})
    readonly property var accounts:wallet.accounts || []
    readonly property var account:accounts.filter(function(a){return a.id===root.accountId})[0] || ({})
    readonly property var localKey:(wallet.local_wallets || []).filter(function(k){return k.account_id===root.accountId})[0] || ({})
    readonly property var assets:(state.assets || []).filter(function(a){return a.chain_id===root.account.chain_id})
    readonly property var asset:assets.filter(function(a){return a.id===root.assetId})[0] || ({})
    readonly property var balance:(wallet.rows || []).filter(function(r){return r.account_id===root.accountId && r.asset_id===root.assetId})[0] || ({})
    readonly property var network:(wallet.networks || []).filter(function(n){return n.id===root.account.chain_id})[0] || ({})
    readonly property var operation:state.ui_operation || ({})
    readonly property bool busy:operation.state==="running"
    readonly property bool approvalPending:operation.state==="approval_required"
    readonly property bool editingLocked:busy || approvalPending
    readonly property bool activeView:visible && (!root.Window.window || root.Window.window.visible && root.Window.window.visibility!==Window.Minimized)
    readonly property var transfer:state.wallet_transfer || ({})
    readonly property var transfers:state.wallet_transfers || []
    readonly property var draft:transfer.body || ({})
    readonly property bool expired:now>Number(draft.expires_at || 0)
    readonly property real accountLaneWidth:Math.min(344,Math.max(260,width*.32))
    readonly property bool tokenWorkspace:["receive","send","review"].indexOf(page)>=0
    readonly property bool matchingPreview:!previewSuppressed && !!transfer.id && draft.account_id===accountId && draft.asset_id===assetId
    readonly property string sourceRole:accountRoles[accountId] || ""
    readonly property var sourceAccounts:accounts.filter(function(a){return !root.ownTargetRole || root.accountRoles[a.id]===(root.ownTargetRole==="STORAGE" ? "TRADING" : "STORAGE")})
    readonly property var internalAccounts:accounts.filter(function(a){return a.chain_id===root.account.chain_id && a.id!==root.accountId && a.address!==root.account.address && (!root.ownTargetRole || root.accountRoles[a.id]===root.ownTargetRole)})
    readonly property var internalAccount:internalAccounts.filter(function(a){return a.id===root.internalAccountId})[0] || ({})
    readonly property bool sourceKeyMatches:!!account.address && localKey.pubkey===account.address
    readonly property bool adapterSupported:account.chain_id==="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp" && asset.chain_id===account.chain_id && ["native","token"].indexOf(asset.namespace)>=0
    readonly property bool pendingForSource:transfers.some(function(t){return (t.body || {}).account_id===root.accountId && ["SIGNING","SUBMITTING","SUBMITTED","UNCERTAIN"].indexOf(t.state)>=0})
    readonly property string destination:actionMode==="internal" ? internalAccount.address || "" : recipient.text.trim()
    readonly property bool ownSourceRoleMatches:!ownTargetRole || sourceRole===(ownTargetRole==="STORAGE" ? "TRADING" : "STORAGE")
    readonly property bool ownDestinationMatches:!ownTargetRole || !!internalAccount.id && accountRoles[internalAccount.id]===ownTargetRole
    readonly property bool canPrepare:!editingLocked && !pendingForSource && sourceKeyMatches && localKey.vault_available===true && localKey.backed_up===true && adapterSupported && ownSourceRoleMatches && ownDestinationMatches && !!destination && !!amount.text.trim()
    readonly property bool accountLaneVisible:width>=900 && ["receive","send","backup","review"].indexOf(page)>=0
    signal toolsRequested()
    signal externalWalletRequested(string method,string purpose)
    signal factsRequested()
    signal assetRequested(string assetId)
    signal closeRequested()
    signal actionRequested(string name,var args)
    function invalidateReview(){reviewed=false;reviewedDigest="";reviewedTransferId="";previewSuppressed=true}
    function resetForm(){invalidateReview();internalAccountId="";recipient.text="";amount.text="";watching=false;baselineAtomic=""}
    function open(mode,account,asset){ownTargetRole="";resetForm();checks=0;requestedTransferId="";preparingIntent=({});accountId=account || (accounts.length===1 ? accounts[0].id : "");assetId=asset || "";actionMode=mode==="internal" ? "internal" : mode==="send" ? "send" : "receive";page=mode==="internal" ? "send" : mode;previewSuppressed=false}
    function openOwnMove(role,account,asset){if(["TRADING","STORAGE"].indexOf(role)<0)return;open("internal",account,asset);ownTargetRole=role}
    function setMode(mode){if(editingLocked || !tokenWorkspace)return;ownTargetRole="";resetForm();actionMode=mode;page=mode==="receive" ? "receive" : "send"}
    function roleName(role){return role==="TRADING" ? "Trading" : role==="STORAGE" ? "Förvaring" : "Ej tilldelat"}
    function assetInfo(row){return (state.assets || []).filter(function(a){return a.id===row.asset_id})[0] || ({})}
    function keyFor(id){return (wallet.local_wallets || []).filter(function(k){return k.account_id===id})[0] || ({})}
    function nativeFor(chain){return (state.assets || []).filter(function(a){return a.chain_id===chain && a.namespace==="native"})[0] || ({})}
    function selectPosition(row){if(editingLocked || page==="review")return;accountId=row.account_id;assetId=row.asset_id;resetForm()}
    function reviewAddress(address){var a=accounts.filter(function(a){return a.address===address && a.chain_id===root.draft.chain_id})[0];return a ? a.label+" \u00b7 "+address : address}
    function reviewNetworkName(){var network=(wallet.networks || []).filter(function(n){return n.id===root.draft.chain_id})[0];return network ? network.name : String(draft.chain_id || "")}
    function copy(text){if(text && surfaceHost && surfaceHost.tmogCopy)surfaceHost.tmogCopy(text)}
    function run(name,args){if(name==="prepare_transfer" && !canPrepare)return;if(!editingLocked){if(name==="prepare_transfer")preparingIntent={account_id:accountId,asset_id:assetId,to:destination,amount:amount.text.trim(),mode:actionMode};pendingAction=name;actionRequested(name,args || {})}}
    function selectTransfer(id){if(busy || !id)return;requestedTransferId=id;run("select_transfer",{id:id})}
    function accountLabel(id){var account=accounts.filter(function(a){return a.id===id})[0];return account ? account.label : "Konto"}
    function transferFailure(row){return ({WALLET_TRANSACTION_EXPIRED:"Giltighetstiden har passerat och signaturen saknas i den kontrollerade RPC-källans historik. Ingen omsändning har gjorts.",WALLET_INTERRUPTED_BEFORE_BROADCAST:"Signeringen avbröts före sändning.",WALLET_ONCHAIN_FAILED:"Nätverket rapporterar att transaktionen misslyckades."})[row.error] || ""}
    function transferLabel(row){return ({PREPARED:row.expired ? "Utgånget utkast" : "Förberedd · osignerad",SIGNING:"Signeringssteg · kontroll krävs",SUBMITTING:"Sändningssteg · utfall okänt",SUBMITTED:"Sänd · väntar på bekräftelse",UNCERTAIN:"Okänt utfall · kontrollera signaturen",CONFIRMED:"Bekräftad av Solana",FINALIZED:"Slutligt bekräftad av Solana",FAILED:"Misslyckad",CANCELLED:"Avbruten"})[row.state] || row.state || "Status saknas"}
    function completed(){
        if(operation.state!=="done" || operation.name!==pendingAction)return
        if(operation.name==="select_transfer" && (state.wallet_transfer || {}).id!==requestedTransferId)return
        pendingAction=""
        if(operation.name==="create_wallet" && creationPublicAddress){
            var created=accounts.filter(function(a){return a.address===root.creationPublicAddress && a.chain_id==="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"})
            if(created.length){creationWizard.complete();accountId=created[0].id;assetId=nativeFor(created[0].chain_id).id || "";page="receive";creationPublicAddress=""}
        }else if(operation.name==="create_wallet" || operation.name==="restore_wallet"){
            var keys=wallet.local_wallets || [];if(keys.length){accountId=keys[keys.length-1].account_id;page=operation.name==="create_wallet" ? "backup" : "receive"}
        }else if(operation.name==="prepare_transfer"){
            if(accountId!==preparingIntent.account_id || assetId!==preparingIntent.asset_id || destination!==preparingIntent.to || amount.text.trim()!==preparingIntent.amount || actionMode!==preparingIntent.mode || draft.account_id!==preparingIntent.account_id || draft.asset_id!==preparingIntent.asset_id || draft.to!==preparingIntent.to || Format.compareExact(draft.amount,preparingIntent.amount)!==0)return
            invalidateReview();previewSuppressed=false;page="review"
        }
        else if(operation.name==="select_transfer"){accountId=draft.account_id || "";assetId=draft.asset_id || "";invalidateReview();previewSuppressed=false;page="review"}
        else if(operation.name==="send_transfer" || operation.name==="check_transfer")page="review"
        else if(operation.name==="backup_wallet"){backupPassword.text="";backupConfirm.text="";page="receive"}
    }
    onStateChanged:Qt.callLater(root.completed)
    onPageChanged:{now=Date.now()/1000;watching=false;backupPassword.text="";backupConfirm.text="";restorePassword.text="";if(page==="create")creationWizard.open(root.sourceRole || "TRADING");if(page==="recovery")recoveryPanel.open(root.localKey.pubkey || root.account.address || "")}
    onVisibleChanged:if(!visible)watching=false
    onActiveViewChanged:if(!activeView)watching=false
    onAccountIdChanged:{assetId="";resetForm()}
    onAssetIdChanged:resetForm()
    onActionModeChanged:invalidateReview()
    onInternalAccountIdChanged:invalidateReview()
    onOwnTargetRoleChanged:invalidateReview()
    onAccountRolesChanged:invalidateReview()
    Timer {interval:1000;repeat:true;running:root.activeView && (root.page==="review" || root.page==="receive" && root.matchingPreview);onTriggered:root.now=Date.now()/1000}
    Timer {interval:15000;repeat:true;running:root.activeView && root.watching && root.page==="receive";onTriggered:{if(root.checks>=40 || Date.now()>=root.watchDeadline){root.watching=false;return}if(!root.editingLocked && root.accountId && root.assetId){root.checks++;root.run("refresh_balance",{account_id:root.accountId,asset_id:root.assetId})}}}
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;wrapMode:Text.WordWrap}
    component WalletAction:CryptoButton {font.pixelSize:11;height:28;enabled:!root.editingLocked}
    component GlyphAction:WalletAction {id:glyphButton;property string glyphName:"copy"
        contentItem:Item {implicitWidth:glyphText.implicitWidth+20
            LedgerGlyph { property string uiColorScope: "ui.widget.WalletActions.LedgerGlyph.1";width:14;height:14;anchors.verticalCenter:parent.verticalCenter;viewport:actionScroll;name:glyphButton.glyphName;color:glyphButton.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim}
            GGText { colorKey: "ui.WalletActions.1";id:glyphText;x:20;width:Math.max(0,parent.width-20);height:parent.height;verticalAlignment:Text.AlignVCenter;text:glyphButton.text;font:glyphButton.font;color:glyphButton.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim;elide:Text.ElideRight;textFormat:Text.PlainText}
        }
    }
    Flickable {objectName:"walletAccountLane";width:root.accountLaneWidth;height:parent.height;visible:root.accountLaneVisible;clip:true;contentWidth:width;contentHeight:accountBody.height;ScrollBar.vertical:ScrollBar {}
        Column {id:accountBody;width:parent.width-20;spacing:18
            Label { colorKey: "ui.WalletActions.2";width:parent.width;text:"KONTON / TILLGÅNGAR";color:RuntimeTheme.GGTheme.text;font.pixelSize:13;font.letterSpacing:.6}
            Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
            Repeater {model:root.accounts.slice().sort(function(a,b){return Number(!!root.keyFor(a.id).pubkey)-Number(!!root.keyFor(b.id).pubkey)})
                Rectangle {id:accountGroup;required property var modelData;readonly property var key:root.keyFor(modelData.id);readonly property var nativeAsset:root.nativeFor(modelData.chain_id);objectName:"walletAccountGroup";width:parent.width;height:groupBody.height+20;color:"transparent";radius:3;border.color:!!key.pubkey && modelData.id===root.accountId ? RuntimeTheme.GGTheme.accent : "transparent"
                    Column {id:groupBody;x:10;y:10;width:parent.width-20;spacing:0
                        Item {width:parent.width;height:76
                            AssetIcon { property string uiColorScope: "ui.widget.WalletActions.AssetIcon.2";x:4;y:10;width:36;height:36;symbol:accountGroup.key.pubkey ? "GG" : accountGroup.nativeAsset.symbol || "?";assetId:accountGroup.key.pubkey ? "" : accountGroup.nativeAsset.id || "";chainId:accountGroup.modelData.chain_id}
                            Label { colorKey: "ui.WalletActions.3";x:56;y:8;width:parent.width-56;text:accountGroup.modelData.label || "Konto";font.pixelSize:15;color:RuntimeTheme.GGTheme.bright}
                            Label { colorKey: "ui.WalletActions.4";x:56;y:34;width:parent.width-56;text:accountGroup.key.pubkey ? "Krypterad nyckel" : "Bevakningskonto";font.pixelSize:12;color:RuntimeTheme.GGTheme.muted}
                            Label { colorKey: "ui.WalletActions.5";x:56;y:55;width:parent.width-56;text:Format.shortAddress(accountGroup.modelData.address);font.pixelSize:11;color:RuntimeTheme.GGTheme.dim}
                            MouseArea {anchors.fill:parent;enabled:!root.editingLocked && root.page!=="review";cursorShape:Qt.PointingHandCursor;onClicked:root.accountId=accountGroup.modelData.id}
                        }
                        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                        Repeater {model:(root.wallet.rows || []).filter(function(r){return r.account_id===accountGroup.modelData.id}).sort(function(a,b){var first=root.assetInfo(a).namespace==="native",second=root.assetInfo(b).namespace==="native";return first!==second ? first ? -1 : 1 : String(a.symbol).localeCompare(String(b.symbol))})
                            Item {id:accountAsset;required property var modelData;readonly property var identity:root.assetInfo(modelData);objectName:"walletGroupedAsset";property string accountTarget:modelData.account_id;property string assetTarget:modelData.asset_id;width:parent.width;height:66
                                AssetIcon { property string uiColorScope: "ui.widget.WalletActions.AssetIcon.3";x:4;y:15;width:36;height:36;symbol:accountAsset.modelData.symbol;assetId:accountAsset.modelData.asset_id;chainId:accountAsset.modelData.chain_id;assetNamespace:accountAsset.identity.namespace || "";assetReference:accountAsset.identity.reference || ""}
                                Label { colorKey: "ui.WalletActions.6";x:56;y:18;width:parent.width*.42-56;text:accountAsset.modelData.symbol;font.pixelSize:15;color:root.accountId===accountTarget && root.assetId===assetTarget ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.text}
                                Label { colorKey: "ui.WalletActions.7";x:parent.width*.42;y:15;width:parent.width*.58-6;text:Format.exactQuantity(accountAsset.modelData.quantity);horizontalAlignment:Text.AlignRight;font.pixelSize:14}
                                Label { colorKey: "ui.WalletActions.8";x:56;y:40;width:parent.width-62;text:accountAsset.modelData.value_usd===null || accountAsset.modelData.value_usd===undefined ? "Ej värderat" : Format.exactMoney(accountAsset.modelData.value_usd);horizontalAlignment:Text.AlignRight;font.pixelSize:12;color:RuntimeTheme.GGTheme.muted}
                                Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                                MouseArea {anchors.fill:parent;enabled:!root.editingLocked && root.page!=="review";cursorShape:Qt.PointingHandCursor;onClicked:root.selectPosition(accountAsset.modelData)}
                            }
                        }
                        WalletAction { property string uiColorScope: "ui.control.WalletActions.1";width:parent.width;height:48;text:"＋ Lägg till tillgång";flat:true;horizontalAlignment:Text.AlignLeft;onClicked:root.toolsRequested()}
                    }
                }
            }
        }
    }
    Rectangle {x:root.accountLaneWidth;width:1;height:parent.height;visible:root.accountLaneVisible;color:RuntimeTheme.GGTheme.line}
    WalletCreationWizard {id:creationWizard;anchors.fill:parent;visible:root.page==="create";surfaceHost:root.surfaceHost;state:root.state;busy:root.busy;approvalPending:root.approvalPending
        onReady:function(publicSummary){root.creationPublicAddress=publicSummary.address || ""}
        onActionRequested:function(name,args){root.run(name,args)}
        onCloseRequested:root.closeRequested()
        onExternalRequested:function(method,purpose){root.externalWalletRequested(method,purpose)}
    }
    WalletRecoveryPanel {id:recoveryPanel;anchors.fill:parent;visible:root.page==="recovery";surfaceHost:root.surfaceHost;busy:root.busy;approvalPending:root.approvalPending
        onCloseRequested:root.closeRequested()
        onExportRequested:function(pubkey){recoveryExportFile.open()}
    }
    Flickable {id:actionScroll;objectName:"walletActionScroll";visible:root.page!=="create" && root.page!=="recovery";x:root.accountLaneVisible ? root.accountLaneWidth+24 : 0;width:Math.max(0,parent.width-x);height:parent.height;clip:true;contentWidth:width;contentHeight:body.height;ScrollBar.vertical:ScrollBar {}
        Column {id:body;width:parent.width;spacing:9
            Column {width:parent.width;spacing:5
                Row {width:parent.width;height:24
                    Label { colorKey: "ui.WalletActions.9";width:Math.max(0,parent.width-150);height:24;verticalAlignment:Text.AlignVCenter;text:"WALLET · "+String(root.network.name || "KONTON").toUpperCase();font.pixelSize:10;color:RuntimeTheme.GGTheme.bright;wrapMode:Text.NoWrap;elide:Text.ElideRight}
                    WalletAction { property string uiColorScope: "ui.control.WalletActions.2";objectName:"walletFactsButton";width:58;height:24;text:"Skydd";flat:true;font.pixelSize:10;enabled:true;onClicked:root.factsRequested()}
                    WalletAction { property string uiColorScope: "ui.control.WalletActions.3";width:92;height:24;text:"← Översikt";flat:true;font.pixelSize:10;enabled:true;onClicked:{root.watching=false;root.closeRequested()}}
                }
                Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
            }
            Label { colorKey: "ui.WalletActions.10";objectName:"walletApprovalPending";width:parent.width;visible:root.approvalPending;text:"Väntar på godkännande i chatten. Det granskade underlaget är låst tills du svarar ja eller nej. Att lämna vyn avbryter inte förfrågan.";color:RuntimeTheme.GGTheme.accent}
            Flow {objectName:"walletActionModes";width:parent.width;spacing:6;visible:root.tokenWorkspace
                WalletAction { property string uiColorScope: "ui.control.WalletActions.4";objectName:"walletModeReceive";width:(parent.width-12)/3;height:28;text:"Ta emot";checked:root.actionMode==="receive" && root.page!=="review";onClicked:root.setMode("receive")}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.5";objectName:"walletModeSend";width:(parent.width-12)/3;height:28;text:"Skicka";checked:root.actionMode==="send" && root.page!=="review";onClicked:root.setMode("send")}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.6";objectName:"walletModeInternal";width:(parent.width-12)/3;height:28;text:parent.width<520 ? "Egna konton" : "Mellan egna konton";tip:"Mellan egna konton · vanlig överföring på samma nätverk";checked:root.actionMode==="internal" && root.page!=="review";onClicked:root.setMode("internal")}
            }
            Flow {width:parent.width;spacing:6;visible:root.tokenWorkspace && !!root.accountId && !!root.assetId && !!root.sourceRole
                WalletAction { property string uiColorScope: "ui.control.WalletActions.7";objectName:"walletMoveToStorage";height:28;font.pixelSize:11;text:"Flytta till förvaring";visible:root.sourceRole==="TRADING";onClicked:root.openOwnMove("STORAGE",root.accountId,root.assetId)}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.8";objectName:"walletMoveToTrading";height:28;font.pixelSize:11;text:"Till trading";visible:root.sourceRole==="STORAGE";onClicked:root.openOwnMove("TRADING",root.accountId,root.assetId)}
            }
            Row {width:parent.width;height:20;visible:root.tokenWorkspace
                Label { colorKey: "ui.WalletActions.11";width:Math.max(0,parent.width-158);height:20;verticalAlignment:Text.AlignVCenter;text:root.assetId ? root.asset.symbol+" · "+String(root.account.label || "Konto") : "Välj konto och tillgång";font.pixelSize:10;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.NoWrap;elide:Text.ElideRight}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.9";objectName:"walletShowAssetMarket";width:72;height:20;text:"Marknad ↗";flat:true;font.pixelSize:10;enabled:!root.editingLocked && !!root.assetId;onClicked:root.assetRequested(root.assetId)}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.10";objectName:"walletActionHistory";width:86;height:20;text:"Historik";flat:true;font.pixelSize:10;enabled:!root.editingLocked;onClicked:{root.invalidateReview();root.page="history"}}
            }
            Label { colorKey: "ui.WalletActions.12";width:parent.width;visible:root.page!=="receive";text:({create:"Skapa GG-wallet · Solana",backup:"Säkerhetskopiera wallet",restore:"Återställ krypterad wallet",send:root.actionMode==="internal" ? "Mellan egna konton" : "Skicka / uttag",review:"Granska överföring",history:"Överföringar"})[root.page] || "Wallet";font.pixelSize:17;color:RuntimeTheme.GGTheme.bright}
            Column {width:parent.width;spacing:12;visible:root.page==="history"
                Label { colorKey: "ui.WalletActions.13";width:parent.width;text:"Öppna en sparad överföring för att granska den eller kontrollera utfallet på nätverket.";color:RuntimeTheme.GGTheme.muted}
                Repeater {model:root.transfers
                    Rectangle {required property var modelData;objectName:"walletTransferHistoryRow";width:parent.width;height:transferBody.height+20;color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.line;radius:3
                        Column {id:transferBody;x:10;y:10;width:parent.width-20;spacing:8
                            Label { colorKey: "ui.WalletActions.14";width:parent.width;text:(modelData.body.amount || "—")+" "+(modelData.body.symbol || "")+" · "+root.transferLabel(modelData);color:RuntimeTheme.GGTheme.bright}
                            Label { colorKey: "ui.WalletActions.15";width:parent.width;text:root.accountLabel(modelData.body.account_id)+"\nFrån: "+(modelData.body.from || "")+"\nTill: "+(modelData.body.to || "");wrapMode:Text.WrapAnywhere;color:RuntimeTheme.GGTheme.muted}
                            WalletAction { property string uiColorScope: "ui.control.WalletActions.11";objectName:"walletOpenTransferReceipt";property string transferId:modelData.id;text:modelData.state==="PREPARED" ? "Granska utkast" : "Öppna överföring";onClicked:root.selectTransfer(transferId)}
                        }
                    }
                }
                Label { colorKey: "ui.WalletActions.16";width:parent.width;visible:!root.transfers.length;text:"Inga sparade överföringar.";color:RuntimeTheme.GGTheme.muted}
            }
            WalletAction { property string uiColorScope: "ui.control.WalletActions.12";objectName:"walletRevealRecovery";text:"Visa återställningsord";visible:!!root.localKey.recovery_available && ["receive","backup"].indexOf(root.page)>=0;onClicked:root.page="recovery"}
            WalletAction { property string uiColorScope: "ui.control.WalletActions.13";objectName:"walletRestoreWords";text:"Återställ med 12 / 24 ord";visible:root.page==="restore";onClicked:{root.page="create";creationWizard.openRestore(root.sourceRole || "TRADING")}}
            Column {width:parent.width;spacing:7;visible:["receive","send","backup"].indexOf(root.page)>=0
                CryptoPick { property string uiColorScope: "ui.control.WalletActions.14";objectName:"walletActionAccount";width:parent.width;height:28;font.pixelSize:11;enabled:!root.editingLocked;visible:!root.accountLaneVisible || !root.accountId;model:[{id:"",name:"Välj konto"}].concat(root.sourceAccounts.map(function(a){return {id:a.id,name:a.label+" · "+Format.shortAddress(a.address)}}));textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.accountId)return i;return 0} onActivated:root.accountId=model[currentIndex].id}
                Row {width:parent.width;spacing:8
                    Item {width:Math.min(108,parent.width*.36);height:28
                        AssetIcon { property string uiColorScope: "ui.widget.WalletActions.AssetIcon.18";x:0;y:5;width:18;height:18;symbol:(root.nativeFor(root.account.chain_id).symbol || "");assetId:root.nativeFor(root.account.chain_id).id || "";chainId:root.account.chain_id || ""}
                        Label { colorKey: "ui.WalletActions.17";x:24;width:parent.width-24;height:28;verticalAlignment:Text.AlignVCenter;text:root.network.name || "Nätverk";font.pixelSize:10;wrapMode:Text.NoWrap;elide:Text.ElideRight;color:RuntimeTheme.GGTheme.muted}
                    }
                    CryptoPick { property string uiColorScope: "ui.control.WalletActions.15";objectName:"walletActionAsset";width:Math.max(0,parent.width-Math.min(108,parent.width*.36)-8);height:28;font.pixelSize:11;visible:root.page!=="backup";enabled:!root.editingLocked;model:[{id:"",name:"Välj tillgång"}].concat(root.assets.map(function(a){return {id:a.id,name:a.symbol+" · "+a.name}}));textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.assetId)return i;return 0} onActivated:{root.assetId=model[currentIndex].id;root.watching=false;root.baselineAtomic=""}}
                }
            }
            Column {width:parent.width;spacing:10;visible:root.page==="receive" && !!root.accountId
                Label { colorKey: "ui.WalletActions.18";width:parent.width;visible:!!root.localKey.pubkey && !root.localKey.backed_up;text:"Säkerhetskopiera nyckeln innan du sätter in tillgångar.";color:RuntimeTheme.GGTheme.accent}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.16";text:"Säkerhetskopiera först";visible:!!root.localKey.pubkey && !root.localKey.backed_up;onClicked:root.page="backup"}
                GgFrame { property string uiColorScope: "ui.widget.WalletActions.GgFrame.21";objectName:"walletReceiveAddressBox";width:parent.width;height:54;leftLegend:"MOTTAGNINGSADRESS";rightLegend:String(root.asset.symbol || "");backgroundColor:"transparent";borderColor:RuntimeTheme.GGTheme.edge;radius:1;compact:true
                    Row {width:parent.width;spacing:6
                        CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.22";objectName:"walletReceiveAddress";width:Math.max(0,parent.width-copyReceive.width-6);height:28;readOnly:true;selectByMouse:true;text:root.account.address || "";font.pixelSize:11;Accessible.name:"Din fullständiga mottagningsadress"}
                        GlyphAction { property string uiColorScope: "ui.control.WalletActions.17";id:copyReceive;objectName:"walletCopyReceive";width:34;height:28;text:"";tip:"Kopiera fullständig mottagningsadress";Accessible.name:tip;enabled:!!root.account.address && (!root.localKey.pubkey || root.localKey.backed_up);onClicked:root.copy(root.account.address)}
                    }
                }
                GgFrame { property string uiColorScope: "ui.widget.WalletActions.GgFrame.24";objectName:"walletReceiveMintBox";width:parent.width;height:54;visible:!!root.asset.namespace && root.asset.namespace!=="native";leftLegend:"MINT / KONTRAKT";backgroundColor:"transparent";borderColor:RuntimeTheme.GGTheme.line;radius:1;compact:true
                    Row {width:parent.width;spacing:6
                        CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.25";objectName:"walletReceiveMint";width:Math.max(0,parent.width-40);height:28;readOnly:true;selectByMouse:true;text:root.asset.reference || "";font.pixelSize:11;Accessible.name:"Fullständig tokenadress"}
                        GlyphAction { property string uiColorScope: "ui.control.WalletActions.18";width:34;height:28;text:"";tip:"Kopiera fullständig tokenadress";Accessible.name:tip;onClicked:root.copy(root.asset.reference)}
                    }
                }
                GgFrame { property string uiColorScope: "ui.widget.WalletActions.GgFrame.27";objectName:"walletReceiveBalanceBox";width:parent.width;height:78;leftLegend:"SALDO · "+String(root.asset.symbol || "");rightLegend:root.sourceKeyMatches ? "LOKAL NYCKEL" : "BEVAKNING";backgroundColor:"transparent";borderColor:RuntimeTheme.GGTheme.line;radius:1;compact:true
                    Column {width:parent.width;spacing:4
                        Label { colorKey: "ui.WalletActions.19";objectName:"walletReceiveExactQuantity";width:parent.width;height:28;text:root.assetId ? Format.exactQuantity(root.balance.quantity) : "—";font.pixelSize:22;minimumPixelSize:10;fontSizeMode:Text.Fit;wrapMode:Text.NoWrap;font.bold:true;color:RuntimeTheme.GGTheme.bright;Accessible.name:text+" "+String(root.asset.symbol || "")}
                        Row {width:parent.width;height:18
                            Label { colorKey: "ui.WalletActions.20";objectName:"walletReceiveValuation";width:parent.width*.53;height:18;text:root.balance.value_usd===null || root.balance.value_usd===undefined ? "Ej prissatt" : Format.exactMoney(root.balance.value_usd);font.pixelSize:12;wrapMode:Text.NoWrap;elide:Text.ElideRight;color:root.balance.value_usd===null || root.balance.value_usd===undefined ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.cyan}
                            Label { colorKey: "ui.WalletActions.21";width:parent.width*.47;height:18;text:root.balance.balance_state==="READ_FAILED" ? "Läsfel" : root.balance.observed_at ? new Date(root.balance.observed_at*1000).toLocaleTimeString(Qt.locale(),"HH:mm:ss") : "Ej avläst";horizontalAlignment:Text.AlignRight;font.pixelSize:10;color:root.balance.balance_state==="READ_FAILED" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.dim;wrapMode:Text.NoWrap}
                        }
                    }
                }
                Row {width:parent.width;height:28;spacing:8
                    GlyphAction { property string uiColorScope: "ui.control.WalletActions.19";objectName:"walletReadReceive";glyphName:"refresh";width:Math.min(142,parent.width*.52);height:28;text:"Uppdatera";tip:"Läs valt saldo och pris";enabled:!root.editingLocked && !!root.assetId;onClicked:root.run("refresh_balance",{account_id:root.accountId,asset_id:root.assetId})}
                    CryptoToggle { property string uiColorScope: "ui.control.WalletActions.20";objectName:"walletWatchReceive";width:Math.max(0,parent.width-Math.min(142,parent.width*.52)-8);height:28;text:"Bevaka · 15 s";font.pixelSize:10;enabled:!root.editingLocked && !!root.assetId;checked:root.watching;onClicked:{root.watching=checked;root.checks=0;root.watchDeadline=Date.now()+600000;root.baselineAtomic=root.balance.atomic===null || root.balance.atomic===undefined ? "" : String(root.balance.atomic)}}
                }
                Column {width:parent.width;spacing:5
                    Label { colorKey: "ui.WalletActions.22";objectName:"walletReceivePriceSource";width:parent.width;visible:!!root.balance.price_source;text:"Pris · "+String(root.balance.price_source || "")+(root.balance.price_quality==="BONDING_CURVE_SPOT" ? " · indikativt" : "")+(root.balance.price_stale ? " · äldre" : "");color:root.balance.price_stale || root.balance.price_quality==="BONDING_CURVE_SPOT" ? RuntimeTheme.GGTheme.warning : RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    Label { colorKey: "ui.WalletActions.23";objectName:"walletPendingBalance";width:parent.width;visible:!!root.balance.pending_atomic && root.balance.pending_atomic!=="0";text:"Väntande förändring: "+String(root.balance.pending_atomic || "")+" basenheter. Bekräftat saldo visas ovan.";color:RuntimeTheme.GGTheme.accent;wrapMode:Text.WrapAnywhere}
                    Label { colorKey: "ui.WalletActions.24";width:parent.width;visible:root.baselineAtomic!=="" && root.balance.atomic!==undefined && String(root.balance.atomic)!==root.baselineAtomic;text:"Saldot har ändrats. Kontrollera faktisk transaktion i avsändarwalleten.";color:RuntimeTheme.GGTheme.positive}
                }
            }
            Column {width:parent.width;spacing:10;visible:root.page==="backup"
                Label { colorKey: "ui.WalletActions.25";width:parent.width;text:"Backupen är krypterad med ett separat lösenord. Utan lösenordet kan den inte återställas. Den lokala Windows-nyckeln är bunden till denna användare och dator.";color:RuntimeTheme.GGTheme.muted}
                CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.30";id:backupPassword;objectName:"walletBackupPassword";width:parent.width;placeholderText:"Backuplösenord · minst 12 tecken";echoMode:TextInput.Password;maximumLength:256}
                CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.31";id:backupConfirm;width:parent.width;placeholderText:"Upprepa lösenord";echoMode:TextInput.Password;maximumLength:256}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.21";text:"Spara krypterad backup…";enabled:!root.busy && !!root.localKey.pubkey && backupPassword.text.length>=12 && backupPassword.text===backupConfirm.text;onClicked:backupFile.open()}
            }
            Column {width:parent.width;spacing:10;visible:root.page==="restore"
                Label { colorKey: "ui.WalletActions.26";width:parent.width;text:"Välj en krypterad .ggwallet-backup. Ange lösenordet här i appen, aldrig i chatten.";color:RuntimeTheme.GGTheme.muted}
                CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.33";id:restorePassword;width:parent.width;placeholderText:"Backuplösenord";echoMode:TextInput.Password;maximumLength:256}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.22";text:"Öppna krypterad backup…";enabled:!root.busy && restorePassword.text.length>=12;onClicked:restoreFile.open()}
            }
            Column {width:parent.width;spacing:10;visible:root.page==="send"
                Label { colorKey: "ui.WalletActions.27";objectName:"walletSendExactQuantity";width:parent.width;height:28;text:Format.exactQuantity(root.balance.quantity)+" "+String(root.asset.symbol || "");font.pixelSize:20;minimumPixelSize:10;fontSizeMode:Text.Fit;wrapMode:Text.NoWrap;color:RuntimeTheme.GGTheme.bright}
                Label { colorKey: "ui.WalletActions.28";width:parent.width;text:(root.balance.value_usd===null || root.balance.value_usd===undefined ? "Värdering saknas" : Format.exactMoney(root.balance.value_usd))+" · "+(root.balance.balance_state==="READ_FAILED" ? "Saldoläsning misslyckades" : root.balance.observed_at ? "Avläst "+new Date(root.balance.observed_at*1000).toLocaleTimeString(Qt.locale(),"HH:mm:ss") : "Saldo ej läst");color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.WalletActions.29";width:parent.width;text:"Från: "+String(root.account.address || "");color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WrapAnywhere}
                Label { colorKey: "ui.WalletActions.30";objectName:"walletSourceRoleStatus";width:parent.width;visible:!!root.sourceRole;text:root.roleName(root.sourceRole)+" · "+(root.sourceKeyMatches ? root.localKey.vault_available===true ? "lokal krypterad nyckel · online" : "lokal nyckel otillgänglig" : "extern signering / bevakning");color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.WalletActions.31";objectName:"walletOwnMoveRoleStatus";width:parent.width;visible:!!root.ownTargetRole;text:"Flytta från "+root.roleName(root.ownTargetRole==="STORAGE" ? "TRADING" : "STORAGE")+" till "+root.roleName(root.ownTargetRole)+" på samma nätverk. Välj mottagarkontot och beloppet; sedan granskas vanlig överföring med nätverksavgift.";color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.WalletActions.32";width:parent.width;visible:!!root.balance.pending_atomic && root.balance.pending_atomic!=="0";text:"Väntande förändring: "+String(root.balance.pending_atomic || "")+" basenheter.";color:RuntimeTheme.GGTheme.accent;wrapMode:Text.WrapAnywhere}
                Label { colorKey: "ui.WalletActions.33";objectName:"walletSourceSigningStatus";width:parent.width;visible:!root.sourceKeyMatches || !root.localKey.vault_available || !root.localKey.backed_up;text:!root.sourceKeyMatches ? "Bevakningskonto: signera i din externa wallet. För sändning här, välj en GG-wallet med lokal krypterad nyckel." : !root.localKey.vault_available ? "Den lokala nyckeln är inte tillgänglig på den här enheten." : "Säkerhetskopiera den krypterade nyckeln innan du skickar.";color:RuntimeTheme.GGTheme.accent}
                Label { colorKey: "ui.WalletActions.34";objectName:"walletTransferAdapterStatus";width:parent.width;visible:!!root.assetId && !root.adapterSupported;text:"Ingen verifierad sändningsadapter för denna tillgång och detta nätverk. Ta emot, kopiera adress och läs saldo är tillgängligt.";color:RuntimeTheme.GGTheme.accent}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.23";visible:root.sourceKeyMatches && !root.localKey.backed_up;text:"Säkerhetskopiera nyckeln";onClicked:root.page="backup"}
                Label { colorKey: "ui.WalletActions.35";width:parent.width;visible:root.actionMode==="internal";text:"En vanlig överföring på samma nätverk, med avgift och eventuell kontohyra. Bevakningskontons ägarskap är inte verifierat.";color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.WalletActions.36";width:parent.width;text:root.actionMode==="internal" ? "Till konto" : "Till · mottagaradress";color:RuntimeTheme.GGTheme.muted}
                CryptoPick { property string uiColorScope: "ui.control.WalletActions.24";objectName:"walletInternalRecipient";width:parent.width;visible:root.actionMode==="internal";enabled:!root.editingLocked;model:[{id:"",name:"Välj mottagarkonto"}].concat(root.internalAccounts.map(function(a){return {id:a.id,name:a.label+" · "+Format.shortAddress(a.address)+(root.keyFor(a.id).pubkey===a.address ? "" : " · bevakning")}}));textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.internalAccountId)return i;return 0} onActivated:root.internalAccountId=model[currentIndex].id}
                Label { colorKey: "ui.WalletActions.37";objectName:"walletNoInternalRecipient";width:parent.width;visible:root.actionMode==="internal" && !root.internalAccounts.length;text:root.ownTargetRole ? "Inget registrerat "+root.roleName(root.ownTargetRole)+"-konto på samma nätverk. Lägg till ett konto och tilldela rollen först. Ingen brygga används." : "Inget annat registrerat konto på samma nätverk. Lägg till mottagarens offentliga konto via Konton / token.";color:RuntimeTheme.GGTheme.accent}
                Label { colorKey: "ui.WalletActions.38";objectName:"walletInternalAddress";width:parent.width;visible:root.actionMode==="internal" && !!root.destination;text:"Till: "+root.destination;wrapMode:Text.WrapAnywhere;color:RuntimeTheme.GGTheme.muted}
                CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.37";id:recipient;objectName:"walletSendRecipient";width:parent.width;visible:root.actionMode!=="internal";enabled:!root.editingLocked;placeholderText:"Mottagaradress"+(root.network.name ? " på "+root.network.name : "");maximumLength:180;onTextChanged:root.invalidateReview()}
                Label { colorKey: "ui.WalletActions.39";width:parent.width;text:"Belopp"+(root.asset.symbol ? " · "+root.asset.symbol : "");color:RuntimeTheme.GGTheme.muted}
                CryptoField { property string uiColorScope: "ui.widget.WalletActions.CryptoField.38";id:amount;objectName:"walletSendAmount";width:parent.width;enabled:!root.editingLocked;placeholderText:"Belopp";maximumLength:100;onTextChanged:root.invalidateReview()}
                Label { colorKey: "ui.WalletActions.40";width:parent.width;visible:root.pendingForSource;text:"En tidigare överföring från kontot har ännu inte ett känt slutligt utfall. Öppna Överföringar och kontrollera signaturen innan du förbereder en ny.";color:RuntimeTheme.GGTheme.accent}
                WalletAction { property string uiColorScope: "ui.control.WalletActions.25";objectName:"walletPrepareTransfer";text:"Förbered & simulera";enabled:root.canPrepare;onClicked:root.run("prepare_transfer",{account_id:root.accountId,asset_id:root.assetId,recipient:root.destination,amount:amount.text.trim()})}
                Label { colorKey: "ui.WalletActions.41";width:parent.width;text:"SOL och vanliga SPL-token stöds för förberedelse. Token-2022 med särskilda överföringsregler kräver en separat verifierad adapter.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
            }
            Column {objectName:"walletTransferPreview";width:parent.width;spacing:12;visible:root.page==="review" || root.page==="receive" && root.matchingPreview
                Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                Row {width:parent.width;height:24
                    Label { colorKey: "ui.WalletActions.42";width:parent.width-150;text:"FÖRHANDSGRANSKNING";font.pixelSize:13;color:RuntimeTheme.GGTheme.text}
                    WalletAction { property string uiColorScope: "ui.control.WalletActions.26";width:150;height:24;text:"Överföringar →";flat:true;font.pixelSize:12;visible:root.transfers.length>0;enabled:!root.editingLocked;onClicked:{root.invalidateReview();root.page="history"}}
                }
                Rectangle {width:parent.width;height:reviewBody.height+20;color:"transparent";border.color:RuntimeTheme.GGTheme.line;radius:1
                    Column {id:reviewBody;x:10;y:10;width:parent.width-20;spacing:8
                        Repeater {model:[{label:"Belopp",value:(root.draft.amount || "\u2014")+" "+(root.draft.symbol || "")},{label:"Från",value:root.reviewAddress(String(root.draft.from || ""))},{label:"Till",value:root.reviewAddress(String(root.draft.to || ""))},{label:"Nätverk",value:root.reviewNetworkName()},{label:"Mint",value:String(root.draft.mint || "SOL · native")},{label:"Avgift + kontohyra",value:String(root.draft.cost_sol || "\u2014")+" SOL"},{label:"Simulering",value:root.draft.simulation==="PASSED" ? "Godkänd" : String(root.draft.simulation || "Ej genomförd")}]
                            Row {required property var modelData;width:parent.width;spacing:12
                                Label { colorKey: "ui.WalletActions.43";width:Math.min(150,parent.width*.33);text:modelData.label;color:RuntimeTheme.GGTheme.muted;font.pixelSize:13}
                                Label { colorKey: "ui.WalletActions.44";width:parent.width-Math.min(150,parent.width*.33)-12;text:modelData.value;wrapMode:Text.WrapAnywhere;font.pixelSize:13;color:RuntimeTheme.GGTheme.text}
                            }
                        }
                        Label { colorKey: "ui.WalletActions.45";width:parent.width;text:String(root.draft.chain_id || "");font.pixelSize:11;color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WrapAnywhere}
                        Label { colorKey: "ui.WalletActions.46";width:parent.width;text:({PREPARED:root.expired ? "Offerten har löpt ut. Förbered på nytt." : "Förberedd · osignerad",SIGNING:root.busy ? "Signerar" : "Signeringssteget behöver kontrolleras",SUBMITTING:"Sändningssteg registrerat · utfall ännu okänt",SUBMITTED:"Sänd · väntar på bekräftelse",UNCERTAIN:"Utfallet är okänt. Kontrollera signaturen; skicka inte igen.",CONFIRMED:"Bekräftad av Solana",FINALIZED:"Slutligt bekräftad av Solana",FAILED:"Transaktionen misslyckades",CANCELLED:"Avbruten"})[root.transfer.state] || "Ingen förberedd överföring";color:["CONFIRMED","FINALIZED"].indexOf(root.transfer.state)>=0 ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.accent;font.pixelSize:13}
                        Label { colorKey: "ui.WalletActions.47";width:parent.width;visible:!!root.transfer.txid;text:"Signatur: "+String(root.transfer.txid || "");wrapMode:Text.WrapAnywhere;font.pixelSize:11}
                        Label { colorKey: "ui.WalletActions.48";objectName:"walletTransferOutcomeDetail";width:parent.width;visible:root.transfer.state==="FAILED" && !!root.transferFailure(root.transfer);text:root.transferFailure(root.transfer);color:RuntimeTheme.GGTheme.muted}
                        CryptoToggle { property string uiColorScope: "ui.control.WalletActions.27";objectName:"walletReviewConsent";visible:root.transfer.state==="PREPARED";enabled:!root.editingLocked && root.matchingPreview;width:parent.width;text:"Jag har kontrollerat belopp, mottagare och nätverk";checked:root.reviewed && root.reviewedDigest===root.draft.review_digest && root.reviewedTransferId===root.transfer.id;onClicked:{var accept=checked;root.reviewedDigest=accept ? root.draft.review_digest : "";root.reviewedTransferId=accept ? root.transfer.id : "";root.reviewed=accept}}
                        Row {width:parent.width;spacing:8;visible:root.transfer.state==="PREPARED"
                            WalletAction { property string uiColorScope: "ui.control.WalletActions.28";objectName:"walletSendTransfer";width:(parent.width-8)*.65;height:28;text:"Signera & skicka";enabled:!root.editingLocked && root.matchingPreview && root.sourceKeyMatches && root.localKey.vault_available===true && root.localKey.backed_up===true && root.ownSourceRoleMatches && root.ownDestinationMatches && root.reviewed && root.reviewedDigest===root.draft.review_digest && root.reviewedTransferId===root.transfer.id && !root.expired;onClicked:root.run("send_transfer",{id:root.transfer.id,review_digest:root.draft.review_digest})}
                            WalletAction { property string uiColorScope: "ui.control.WalletActions.29";width:(parent.width-8)*.35;height:28;text:"Avbryt";onClicked:root.run("cancel_transfer",{id:root.transfer.id})}
                        }
                        Flow {width:parent.width;spacing:10
                            WalletAction { property string uiColorScope: "ui.control.WalletActions.30";objectName:"walletCheckTransfer";text:"Kontrollera på nätverket";visible:["SUBMITTED","SUBMITTING","UNCERTAIN","CONFIRMED"].indexOf(root.transfer.state)>=0;onClicked:root.run("check_transfer",{id:root.transfer.id})}
                            WalletAction { property string uiColorScope: "ui.control.WalletActions.31";text:"Kopiera signatur";visible:!!root.transfer.txid;onClicked:root.copy(root.transfer.txid)}
                        }
                    }
                }
            }
            Label { colorKey: "ui.WalletActions.49";width:parent.width;visible:root.page==="receive";text:root.localKey.pubkey ? "Saldoändring är inget kvitto. Bevakning avslutas efter 10 minuter." : "Bevakningskonto · signering sker i din externa wallet. Saldoändring är inget kvitto.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
            Label { colorKey: "ui.WalletActions.50";width:parent.width;visible:root.busy;text:"Arbete pågår…";color:RuntimeTheme.GGTheme.muted}
        }
    }
    FileDialog {id:backupFile;title:"Spara krypterad walletbackup";fileMode:FileDialog.SaveFile;nameFilters:["GG walletbackup (*.ggwallet)"];onAccepted:{root.run("backup_wallet",{pubkey:root.localKey.pubkey,path:selectedFile.toString(),password:backupPassword.text});backupPassword.text="";backupConfirm.text=""}}
    FileDialog {id:recoveryExportFile;title:"Spara krypterad återställningsfras";fileMode:FileDialog.SaveFile;nameFilters:["GG krypterad återställning (*.ggmnemonic)"];onAccepted:{if(root.surfaceHost && root.surfaceHost.walletMnemonicExport){var result=JSON.parse(root.surfaceHost.walletMnemonicExport(recoveryPanel.pubkey,selectedFile.toString()));if(result.error)recoveryPanel.errorText="Exporten kunde inte förberedas."}}}
    FileDialog {id:restoreFile;title:"Återställ krypterad walletbackup";fileMode:FileDialog.OpenFile;nameFilters:["GG walletbackup (*.ggwallet)"];onAccepted:{root.run("restore_wallet",{path:selectedFile.toString(),password:restorePassword.text});restorePassword.text=""}}
}
