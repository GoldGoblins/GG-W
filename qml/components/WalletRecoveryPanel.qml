import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Window

// Private local return signal only. No phrase/password is emitted by this view.
Item {
    id:root;objectName:"walletRecoveryPanel";implicitWidth:520;implicitHeight:560
    property string pubkey:""
    property var surfaceHost:null
    property bool busy:false
    property bool approvalPending:false
    property string phase:"PASSWORD"
    property string errorText:""
    property string _requestId:""
    property string _expectedPubkey:""
    property var _words:[]
    readonly property int revealedCount:_words.length
    readonly property bool activeView:visible&&(!root.Window.window||root.Window.window.visible&&root.Window.window.visibility!==Window.Minimized)
    signal closeRequested()
    signal exportRequested(string pubkey)
    function parse(raw){try{return typeof raw==="string"?JSON.parse(raw):raw||{}}catch(_){return {}}}
    function clearWords(){for(var i=0;i<_words.length;i++)_words[i]="";_words=[]}
    function release(){
        // Clear UI references and the match key BEFORE releasing the guard.
        var previous=_requestId;_requestId="";clearWords();password.text="";phase="PASSWORD"
        if(previous&&surfaceHost&&surfaceHost.walletMnemonicCancelReveal){try{surfaceHost.walletMnemonicCancelReveal(previous)}catch(_){}}
    }
    function open(address){release();pubkey=String(address||"");_expectedPubkey=pubkey;errorText="";password.forceActiveFocus()}
    function cancel(){release();errorText="";closeRequested()}
    function reveal(){
        if(phase!=="PASSWORD"||busy||approvalPending||!pubkey||password.text.length<12)return
        if(!surfaceHost||!surfaceHost.walletMnemonicReveal){errorText="Privat upplåsning är inte tillgänglig i den här versionen.";return}
        var secret=password.text;password.text="";clearWords();errorText="";_expectedPubkey=pubkey
        var result={}
        try{result=parse(surfaceHost.walletMnemonicReveal(pubkey,secret))}catch(_){}
        secret=""
        if(result.state!=="approval_required"||typeof result.request_id!=="string"||!result.request_id){errorText="En upplåsningsbegäran kunde inte förberedas.";return}
        _requestId=result.request_id;phase="PENDING"
    }
    function acceptSecret(raw){
        var result=parse(raw)
        if(!_requestId||result.request_id!==_requestId)return
        if(!activeView||pubkey!==_expectedPubkey){release();return}
        if(result.state!=="REVEALED"||!Array.isArray(result.words)||[12,24].indexOf(result.words.length)<0||result.words.some(function(word){return typeof word!=="string"||!/^[a-z]{3,12}$/.test(word)})||(result.pubkey&&result.pubkey!==_expectedPubkey)){
            release();errorText="Frasen kunde inte låsas upp. Kontrollera lösenordet och begär en ny visning.";return
        }
        _words=result.words.slice();result.words=[];phase="REVEALED"
    }
    onPubkeyChanged: if(_requestId&&pubkey!==_expectedPubkey)release()
    onActiveViewChanged:if(!activeView)release()
    Component.onDestruction:release()
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true
        function onWalletMnemonicSecretReady(raw){root.acceptSecret(raw)}
    }
    component Copy:Text {font.family:"monospace";font.pixelSize:11;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;wrapMode:Text.WordWrap}
    component Action:CryptoButton {height:28;font.pixelSize:11}
    Column {id:header;x:12;y:8;width:Math.max(0,root.width-24);spacing:6
        Copy {width:parent.width;text:"DIN PORTABLA FRASE";font.pixelSize:13;font.bold:true;color:RuntimeTheme.GGTheme.bright}
        Copy {width:parent.width;text:root.pubkey;wrapMode:Text.WrapAnywhere;color:RuntimeTheme.GGTheme.dim}
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    Item {id:body;x:12;y:header.y+header.height+10;width:Math.max(0,root.width-24);height:Math.max(0,footer.y-y-8);clip:true
        Column {width:parent.width;spacing:12;visible:root.phase==="PASSWORD"
            Copy {width:parent.width;text:"Lås upp din lösenordskrypterade fras lokalt. Du kan flytta den krypterade kopian mellan dina egna enheter.";color:RuntimeTheme.GGTheme.muted}
            Copy {width:parent.width;text:"Visningen kräver ditt lösenord och ett nytt uttryckligt ja i chatten. Frasen skickas inte till chatten.";color:RuntimeTheme.GGTheme.warning}
            CryptoField {id:password;objectName:"recoveryPassword";width:parent.width;height:32;maximumLength:256;echoMode:TextInput.Password;selectByMouse:false
                property bool sensitiveInput:true
                inputMethodHints:Qt.ImhHiddenText|Qt.ImhSensitiveData|Qt.ImhNoPredictiveText|Qt.ImhNoAutoUppercase
                Accessible.name:"Ditt lösenord för den portabla frasen"
                Keys.onPressed:function(event){if((event.modifiers&Qt.ControlModifier)&&(event.key===Qt.Key_C||event.key===Qt.Key_X))event.accepted=true}
            }
            Action {objectName:"recoveryReveal";width:parent.width;text:"Begär privat frasvisning";enabled:!root.busy&&!root.approvalPending&&!!root.pubkey&&password.text.length>=12;onClicked:root.reveal()}
        }
        Column {width:parent.width;spacing:10;visible:root.phase==="PENDING"
            Copy {width:parent.width;text:"Begäran väntar på ditt ja eller nej i chatten.";color:RuntimeTheme.GGTheme.warning}
            Copy {width:parent.width;text:"Lösenordet är rensat ur fältet. Den fullständiga frasen visas bara här efter godkännandet.";color:RuntimeTheme.GGTheme.muted}
        }
        Column {width:parent.width;spacing:8;visible:root.phase==="REVEALED"
            Copy {id:notice;width:parent.width;text:"Privat visning. Skriv nummer och ord i rätt ordning. Ingen skärmbild, kopiering eller chatt.";color:RuntimeTheme.GGTheme.warning}
            Grid {id:grid;objectName:"recoveryWordGrid";width:parent.width;columns:width>=620?4:width>=460?3:2;columnSpacing:8;rowSpacing:4
                property bool privateSensitive:true
                readonly property int rowsNeeded:Math.ceil(root._words.length/columns)
                readonly property real rowHeight:Math.max(17,Math.min(28,(body.height-notice.implicitHeight-16-Math.max(0,rowsNeeded-1)*rowSpacing)/Math.max(1,rowsNeeded)))
                Repeater {model:root._words
                    Rectangle {required property int index;required property string modelData;objectName:"recoveryWordCell"
                        width:(grid.width-(grid.columns-1)*8)/grid.columns;height:grid.rowHeight;color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.line
                        Copy {x:6;width:24;height:parent.height;verticalAlignment:Text.AlignVCenter;text:String(parent.index+1);font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
                        Copy {x:32;width:parent.width-38;height:parent.height;verticalAlignment:Text.AlignVCenter;text:parent.modelData;wrapMode:Text.NoWrap}
                    }
                }
            }
        }
    }
    Column {id:footer;x:12;y:Math.max(header.y+header.height,root.height-height-8);width:Math.max(0,root.width-24);spacing:6
        Copy {width:parent.width;visible:!!root.errorText;text:root.errorText;color:RuntimeTheme.GGTheme.negative}
        Row {width:parent.width;spacing:6
            Action {objectName:"recoveryClose";text:root.phase==="REVEALED"?"Dölj och stäng":"Avbryt";width:Math.min(160,parent.width);onClicked:root.cancel()}
            Action {objectName:"recoveryExport";text:"Krypterad export";visible:root.phase==="PASSWORD";enabled:!root.busy&&!root.approvalPending&&!!root.pubkey;width:Math.max(0,parent.width-166);onClicked:root.exportRequested(root.pubkey)}
        }
    }
}
