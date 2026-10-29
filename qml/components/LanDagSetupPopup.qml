import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window
import "."
import "." as RuntimeTheme

// Explicit pairing controls. Public documents never include producer/wallet keys.
Popup {
    id:root;objectName:"lanDagSetupPopup"
    property var state:({})
    property var surfaceHost:null
    property bool canAct:true
    property bool localRunning:false
    property bool stopPending:false
    readonly property var lan:state.lan||({})
    readonly property var setup:state.lan_setup||({})
    readonly property bool owned:setup.active===true
    readonly property bool coordinator:setup.coordinator===true
    readonly property bool ready:lan.state==="READY"
    readonly property bool producing:!!state.live&&state.live.enabled===true
    readonly property var candidates:setup.invites||[]
    readonly property var tokens:state.test_tokens||({})
    readonly property var circle:state.token_circle||({})
    readonly property bool circleRunning:["RUNNING","STOPPING"].indexOf(String(circle.state||""))>=0
    readonly property bool allTokenOptedIn:candidates.length===3&&candidates.every(function(peer){return peer.allow_test_tokens===true})
    readonly property bool canStart:root.canAct&&!root.owned&&!root.localRunning&&labelField.text.trim().length>0&&/^[0-9]{4,5}$/.test(portField.text)&&Number(portField.text)>=1024&&Number(portField.text)<=65535
    property string formError:""
    property string operationError:""
    signal actionRequested(string name,var args)
    signal priorityStopRequested()
    signal refreshRequested()
    width:Math.min(720,parent?parent.width-16:720)
    height:Math.min(650,parent?parent.height-16:650)
    x:parent?(parent.width-width)/2:0;y:parent?(parent.height-height)/2:0
    modal:true;focus:true;padding:12
    closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
    background:Rectangle {color:RuntimeTheme.GGTheme.base;border.color:RuntimeTheme.GGTheme.line;border.width:1;radius:3}
    function run(name,args){if(!canAct)return;formError="";actionRequested(name,args||{})}
    function copy(value){if(surfaceHost&&surfaceHost.tmogCopy)surfaceHost.tmogCopy(String(value||""))}
    function wholeTokenAtomic(){var d=Number(root.tokens.decimals);return Number.isInteger(d)&&d>=0&&d<=18?"1"+"0".repeat(d):""}
    function tokenAmount(value){
        var text=String(value===undefined?"":value),d=Number(root.tokens.decimals)
        if(!/^[0-9]+$/.test(text)||!Number.isInteger(d)||d<0||d>18)return "—"
        if(d===0)return text
        while(text.length<=d)text="0"+text
        var fraction=text.slice(-d).replace(/0+$/,"")
        return text.slice(0,-d)+(fraction?"."+fraction:"")
    }
    function command(label){return (label==="Termux"?'python':'python3')+' gg-cli.py --foreground --command "lan.start label='+label+(root.setup.allow_test_tokens===true?' allow_test_tokens=true':'')+'" --bootstrap-file gg-lan-bootstrap.json'}
    function addPasted(){try{var value=JSON.parse(inviteInput.text);run("lan_peer_add",{invite:value});inviteInput.text=""}catch(error){formError="Klistra in en signerad publik inbjudan som JSON."}}
    function joinBootstrap(path){if(root.canStart)root.run("lan_join_file",{path:String(path),label:labelField.text.trim(),port:Number(portField.text),bind_host:"auto",allow_test_tokens:tokenOptIn.checked})}
    component Label:GGText {font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;wrapMode:Text.Wrap}
    component Action:CryptoButton {height:27;font.pixelSize:10;enabled:root.canAct}
    component Section:Rectangle {color:"transparent";border.width:1;border.color:RuntimeTheme.GGTheme.line;width:body.width;radius:2}
    component Line:Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    contentItem:Item {
        Label {id:title;objectName:"lanSetupTitle";colorKey:"ui.lan.title";width:parent.width-36;text:"DAGoblin · privat LAN-session";font.pixelSize:14;font.bold:true}
        Action {anchors.right:parent.right;y:-3;width:28;text:"×";enabled:true;onClicked:root.close()}
        ScrollView {y:32;width:parent.width;height:Math.max(0,parent.height-y);clip:true;contentWidth:availableWidth
            Column {id:body;width:parent.width;spacing:8
                Label {colorKey:"ui.lan.scope";width:parent.width;text:"Tre parade peers · två egna producenter per apparat. Riktiga signerade förslag över TCP; ingen kanonisk finalitet eller finansiell handel.";color:RuntimeTheme.GGTheme.dim}
                Row {width:parent.width;spacing:8
                    Label {objectName:"lanSetupStatus";colorKey:"ui.lan.status";width:parent.width-146;text:root.owned?String(root.lan.state||"STARTING")+" · "+String(root.lan.endpoint?root.lan.endpoint.host+":"+root.lan.endpoint.port:"")+" · "+(root.lan.authenticated_peers||[]).length+" autentiserade peers":"Ingen LAN-peer startad";color:root.ready?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.dim}
                    Action {width:30;text:"↻";enabled:root.canAct;onClicked:root.refreshRequested()}
                    Action {objectName:"lanPriorityStop";width:100;text:root.stopPending?"Stoppar…":"■ Stoppa";enabled:root.owned&&!root.stopPending;onClicked:root.priorityStopRequested()}
                }
                Label {objectName:"lanSetupError";colorKey:"ui.lan.error";width:parent.width;visible:text.length>0;text:root.formError||root.operationError||String(root.setup.announcement_error||root.lan.last_error||"");color:RuntimeTheme.GGTheme.negative}
                Section {height:startBody.height+18
                    Column {id:startBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.start";text:"1 · Starta koordinator eller anslut den här datorn";font.bold:true}
                        Row {width:parent.width;spacing:7
                            CryptoField {id:labelField;objectName:"lanLabel";property string uiColorScope:"ui.lan.field.label";width:Math.max(70,parent.width-229);height:27;text:Qt.platform.os==="linux"?"GG Linux":"GG Windows";maximumLength:64;enabled:root.canAct&&!root.owned&&!root.localRunning;placeholderText:"Nodnamn"}
                            CryptoField {id:portField;objectName:"lanPort";property string uiColorScope:"ui.lan.field.port";width:75;height:27;text:"16120";maximumLength:5;enabled:labelField.enabled;inputMethodHints:Qt.ImhDigitsOnly;Accessible.name:"Privat TCP-port"}
                            Action {objectName:"lanStart";width:140;text:"Starta LAN · auto";enabled:root.canStart;onClicked:root.run("lan_start",{label:labelField.text.trim(),port:Number(portField.text),bind_host:"auto",allow_test_tokens:tokenOptIn.checked})}
                        }
                        CryptoToggle {id:tokenOptIn;objectName:"lanAllowTestTokens";property string uiColorScope:"ui.lan.token.optin";width:parent.width;text:"Tillåt privata GG-LAN-testtokens och koordinatorstyrt cirkelprov";enabled:labelField.enabled;checked:false}
                        Action {objectName:"lanBootstrapJoin";text:"Anslut med publik bootstrap…";enabled:root.canStart;onClicked:bootstrapJoinFile.open()}
                        Label {colorKey:"ui.lan.join.note";width:parent.width;text:"Har Windows redan startat koordinatorn? Läs dess delade gg-lan-bootstrap.json här för att ansluta. Koordinatorn godkänner sedan de tre apparaterna.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {colorKey:"ui.lan.start.note";width:parent.width;text:root.localRunning&&!root.owned?"Stoppa den lokala DAG-sessionen före LAN-start.":"Lokal privat IPv4 väljs automatiskt först när du startar. Ingenting ansluts vid vanlig statusvisning.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:bootstrapBody.height+18
                    Column {id:bootstrapBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.bootstrap";text:"2 · Dela publik bootstrap till Linux och Termux";font.bold:true}
                        Row {spacing:7
                            Action {objectName:"lanBootstrapSave";text:"Spara bootstrap…";enabled:root.canAct&&root.owned&&root.coordinator&&!!root.setup.bootstrap;onClicked:bootstrapFile.open()}
                            Action {objectName:"lanBootstrapCopy";text:"Kopiera publik JSON";enabled:root.owned&&!!root.setup.bootstrap;onClicked:root.copy(JSON.stringify(root.setup.bootstrap,null,2))}
                            Action {text:"Spara egen inbjudan…";enabled:root.canAct&&root.owned;onClicked:inviteExport.open()}
                            Action {objectName:"lanAnnounce";text:"Annonsera igen";visible:root.owned&&!root.coordinator;enabled:root.canAct&&!root.ready;onClicked:root.run("lan_announce",{})}
                        }
                        Label {colorKey:"ui.lan.bootstrap.note";width:parent.width;text:"I Linux Desktop: välj Anslut med publik bootstrap i steg 1 och läs filen. I Termux: lägg gg-lan-bootstrap.json bredvid gg-cli.py och kör telefonkommandot. Egen adress hittas automatiskt och signerad inbjudan återannonseras till koordinatorn.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Row {width:parent.width;spacing:7
                            Action {objectName:"lanLinuxCommand";text:"Linux CLI (valfritt)";enabled:root.owned&&root.coordinator;onClicked:root.copy(root.command("Linux"))}
                            Action {objectName:"lanTermuxCommand";text:"Kopiera Termux-kommando";enabled:root.owned&&root.coordinator;onClicked:root.copy(root.command("Termux"))}
                        }
                        Label {colorKey:"ui.lan.bootstrap.keys";width:parent.width;text:"Endast publika inbjudningar och konfiguration delas. Varje peer behåller sina egna två producentnycklar i RAM. Omstart kräver ny parning; walletnycklar berörs inte.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:peersBody.height+18
                    Column {id:peersBody;x:9;y:9;width:parent.width-18;spacing:7
                        Row {width:parent.width
                            Label {colorKey:"ui.lan.step.roster";width:parent.width-100;text:"3 · Granska och godkänn de tre apparaterna";font.bold:true}
                            Label {colorKey:"ui.lan.roster.count";width:100;text:root.candidates.length+" / 3 inbjudna";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.cyan}
                        }
                        Repeater {model:root.candidates
                            Column {required property var modelData;width:peersBody.width;spacing:3
                                Row {width:parent.width;spacing:6
                                    Rectangle {width:5;height:5;radius:3;y:4;color:RuntimeTheme.GGTheme.cyan}
                                    Label {colorKey:"ui.lan.peer.label";width:Math.max(40,parent.width-160);text:String(modelData.label)+(modelData.local?" · den här apparaten":" · kandidat")+(modelData.allow_test_tokens===true?" · testtokens":"")}
                                    Label {colorKey:"ui.lan.peer.endpoint";width:148;text:String(modelData.host)+":"+String(modelData.port);horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.dim}
                                }
                                Line {}
                            }
                        }
                        Row {spacing:7
                            Action {objectName:"lanInviteOpen";text:"Läs publik inbjudan…";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready;onClicked:inviteFile.open()}
                            Action {objectName:"lanCreateSession";text:root.setup.allow_test_tokens===true&&!root.allTokenOptedIn?"Väntar på 3 testtokenval":"Godkänn 3 · skapa och distribuera";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready&&root.candidates.length===3&&(root.setup.allow_test_tokens!==true||root.allTokenOptedIn);onClicked:root.run("lan_session_create",{label:"GG LAN",distribute:true,enable_test_tokens:root.allTokenOptedIn})}
                            Action {objectName:"lanDistribute";text:"Distribuera igen";enabled:root.canAct&&root.coordinator&&root.ready&&root.setup.bundle_available===true;onClicked:root.run("lan_distribute",{})}
                        }
                        Label {colorKey:"ui.lan.roster.trust";width:parent.width;text:"En annonserad inbjudan är en kandidat. Sessionens roster binds först när koordinatorn uttryckligen godkänner alla tre. Fysiskt skilda apparater är ännu inte verifierade.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        TextArea {id:inviteInput;objectName:"lanInvitePaste";property string uiColorScope:"ui.lan.field.invite";width:parent.width;height:48;wrapMode:TextEdit.Wrap;font.family:"monospace";font.pixelSize:9;placeholderText:"Valfritt: klistra in signerad publik inbjudan som JSON";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready;selectByMouse:true;color:RuntimeTheme.GGTheme.text;background:Rectangle {color:RuntimeTheme.GGTheme.canvas;border.width:1;border.color:RuntimeTheme.GGTheme.line}}
                        Action {objectName:"lanInviteAdd";text:"Lägg till publik inbjudan";enabled:inviteInput.enabled&&inviteInput.text.length>0&&inviteInput.length<=4096;onClicked:root.addPasted()}
                    }
                }
                Section {height:produceBody.height+18
                    Column {id:produceBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.produce";text:"4 · Kör den här apparatens två producenter";font.bold:true}
                        Row {spacing:7
                            CryptoField {id:cadence;objectName:"lanInterval";property string uiColorScope:"ui.lan.field.interval";width:80;height:27;text:"250";maximumLength:5;inputMethodHints:Qt.ImhDigitsOnly;enabled:root.canAct&&root.ready&&!root.producing;Accessible.name:"Producentintervall i millisekunder"}
                            Action {objectName:"lanProduce";text:"▷ Producera lokalt";enabled:cadence.enabled&&/^[0-9]{2,5}$/.test(cadence.text)&&Number(cadence.text)>=10&&Number(cadence.text)<=60000;onClicked:root.run("lan_produce",{interval_ms:Number(cadence.text)})}
                            Action {objectName:"lanPause";text:"Ⅱ Pausa lokalt";enabled:root.canAct&&root.ready&&root.producing;onClicked:root.run("lan_pause",{})}
                        }
                        Label {colorKey:"ui.lan.produce.note";width:parent.width;text:"Paus stoppar bara lokal produktion; verifiering och relä fortsätter. Stoppa avslutar denna ägda peer. MAINNET är inte aktiverat, trafiken är inte krypterad och protokollet är ännu ett privat LAN-experiment.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:tokenBody.height+18;visible:root.tokens.enabled===true
                    Column {id:tokenBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.token.title";text:"5 · GG-LAN(TEST) · verkliga signerade testöverföringar";font.bold:true}
                        Label {colorKey:"ui.lan.token.trust";width:parent.width;text:"Koordinatorn ordnar och kvitterar testöverföringarna. Varje apparat signerar själv och verifierar kvitton och saldon. Testtillgång utan ekonomiskt värde; DAG-slutlighet är fortfarande 0.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Repeater {model:root.tokens.accounts||[]
                            Row {required property var modelData;width:tokenBody.width;spacing:7
                                Label {colorKey:"ui.lan.token.account";width:Math.max(50,parent.width-230);text:String(modelData.label||"Peer")}
                                Label {colorKey:"ui.lan.token.balance";width:120;text:root.tokenAmount(modelData.balance_atomic);horizontalAlignment:Text.AlignRight}
                                Action {width:95;text:"Skicka 1";enabled:root.canAct&&root.ready&&!root.circleRunning&&root.wholeTokenAtomic().length>0&&String(modelData.peer_key)!==String(root.lan.public_key);onClicked:root.run("lan_token_send",{recipient_peer_key:String(modelData.peer_key),amount_atomic:root.wholeTokenAtomic()})}
                            }
                        }
                        Row {spacing:7
                            Action {objectName:"lanCircleStart";text:"▷ Cirkulera 10 s · batch 16";enabled:root.canAct&&root.ready&&root.coordinator&&!root.circleRunning&&root.wholeTokenAtomic().length>0;onClicked:root.run("lan_circle_start",{duration_ms:10000,batch:16,amount_atomic:root.wholeTokenAtomic()})}
                            Action {objectName:"lanCircleStop";text:"■ Stoppa prov";enabled:root.canAct&&root.circleRunning;onClicked:root.run("lan_circle_stop",{})}
                        }
                        Label {objectName:"lanCircleStatus";colorKey:"ui.lan.token.circle";width:parent.width;text:String(root.circle.state||"Redo")+" · "+String(root.circle.transactions===undefined?"—":root.circle.transactions)+" TX · "+(typeof root.circle.tps==="number"?root.circle.tps.toFixed(1):"—")+" TX/s · "+String(root.circle.completed_rounds===undefined?"—":root.circle.completed_rounds)+" varv";color:root.circle.last_error?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.cyan}
                        Label {colorKey:"ui.lan.token.synced";width:parent.width;text:root.circle.all_peers_synced===true?"Alla tre peers har bekräftat samma kvittokedja.":"Gemensamt kvitto verifieras när provet avslutas.";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    }
                }
            }
        }
    }
    FileDialog {id:bootstrapFile;objectName:"lanBootstrapFileDialog";title:"Spara publik LAN-bootstrap som gg-lan-bootstrap.json (ny fil)";fileMode:FileDialog.SaveFile;defaultSuffix:"json";nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_export_bootstrap",{path:String(selectedFile)})}
    FileDialog {id:bootstrapJoinFile;objectName:"lanBootstrapJoinFileDialog";title:"Anslut med koordinatorns publika gg-lan-bootstrap.json";fileMode:FileDialog.OpenFile;nameFilters:["JSON (*.json)"];onAccepted:root.joinBootstrap(selectedFile)}
    FileDialog {id:inviteExport;objectName:"lanInviteExportDialog";title:"Spara egen publik LAN-inbjudan (ny fil)";fileMode:FileDialog.SaveFile;defaultSuffix:"json";nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_export_invite",{path:String(selectedFile)})}
    FileDialog {id:inviteFile;objectName:"lanInviteFileDialog";title:"Läs signerad publik LAN-inbjudan";fileMode:FileDialog.OpenFile;nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_peer_file",{path:String(selectedFile)})}
}
