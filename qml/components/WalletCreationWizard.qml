import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// Secret words travel only between this local view and the dedicated local host
// methods. They never enter an action signal, public status, clipboard or file.
Item {
    id: root
    objectName: "walletCreationWizard"
    implicitWidth:520
    implicitHeight:560
    property var surfaceHost: null
    property var state: ({})
    property bool busy: false
    property bool approvalPending: false
    property string phase: "SETUP"
    property string purpose: "TRADING"
    property string accountMode: "SELF_CUSTODY"
    property string method: "PAPER"
    property int wordCount: 24
    readonly property bool storeLocally: method==="AI"
    property string errorText: ""
    property var _words: []
    property var _indices: []
    property string _sessionId: ""
    property string _sessionLabel: ""
    property string _sessionPurpose: ""
    property int _sessionCount: 0
    property string _sessionMethod: "PAPER"
    property bool _sessionStoreLocally: true
    property int _attempts: 0
    property bool _submitted: false
    property var _publicResult: ({})
    readonly property int revealedCount: _words.length
    readonly property bool editingLocked: busy || approvalPending || _submitted
    readonly property bool localPhrase: method === "PAPER" || method === "AI"
    readonly property int restoreWordCount:restorePhrase.text.trim()?restorePhrase.text.trim().split(/\s+/).length:0
    readonly property int step: ["SETUP","RESTORE","WARNING","REVEAL","CHALLENGE","PASSWORD","READY","APPROVAL"].indexOf(phase)
    signal actionRequested(string name, var args)
    signal closeRequested()
    signal ready(var publicSummary)
    signal externalRequested(string method,string purpose)
    onAccountModeChanged: if(phase==="SETUP")method=accountMode==="AI_ASSISTED"?"AI":"PAPER"

    function parse(raw) { try { return typeof raw === "string" ? JSON.parse(raw) : raw || {} } catch (_) { return {} } }
    function clearWords() {
        for (var i=0;i<_words.length;i++) _words[i]=""
        _words=[]
    }
    function clearAnswers() { answer1.text="";answer2.text="";answer3.text="" }
    function clearPasswords() { vaultPassword.text="";vaultPasswordAgain.text="" }
    function cancelSession() {
        clearWords();clearAnswers();clearPasswords();restorePhrase.text="";_indices=[]
        if (_sessionId && surfaceHost && surfaceHost.walletMnemonicCancel) {
            var result={}
            try { result=parse(surfaceHost.walletMnemonicCancel(_sessionId)) } catch (_) {}
            if(result.state==="CLAIMED" || /CLAIM|BUSY/.test(String(result.error || ""))){
                errorText="Det granskade kontot håller på att sparas. Vänta tills åtgärden är klar."
                return false
            }
        }
        _sessionId="";_publicResult=({})
        return true
    }
    function open(initialPurpose) {
        if (_submitted || approvalPending) return
        cancelSession();purpose=initialPurpose==="STORAGE" ? "STORAGE" : "TRADING"
        accountMode="SELF_CUSTODY";method="PAPER";wordCount=24;phase="SETUP";errorText="";_attempts=0
        warningAck.checked=false;writtenAck.checked=false
    }
    function complete(){cancelSession();clearWords();clearAnswers();clearPasswords();_submitted=false;phase="SETUP";errorText=""}
    function reconcileOperation(){
        var operation=(root.state||{}).ui_operation||{}
        if(phase!=="APPROVAL"||operation.name!=="create_wallet"||["error","rejected","cancelled","expired","failed"].indexOf(String(operation.state||"").toLowerCase())<0)return
        cancelSession();_sessionId="";clearWords();clearAnswers();clearPasswords();restorePhrase.text="";_submitted=false;phase="SETUP"
        errorText="Begäran avslutades utan att denna frassession kan återanvändas. Återställ med orden på ditt papper för att behålla samma adress."
    }
    onStateChanged:reconcileOperation()
    function openRestore(initialPurpose){
        if(_submitted||approvalPending)return
        cancelSession();if(initialPurpose==="STORAGE"||initialPurpose==="TRADING")purpose=initialPurpose
        method=accountMode==="AI_ASSISTED"?"AI":"PAPER";restoreLabel.text=labelField.text
        phase="RESTORE";errorText="";_attempts=0
    }
    function restore(){
        if(phase!=="RESTORE"||editingLocked||!localPhrase||[12,24].indexOf(restoreWordCount)<0||!restoreLabel.text.trim())return
        if(!surfaceHost||!surfaceHost.walletMnemonicRestore){errorText="Privat frasåterställning är inte tillgänglig i den här versionen.";return}
        var phrase=restorePhrase.text;var count=restoreWordCount;restorePhrase.text="";clearWords();errorText=""
        var result={}
        try{result=parse(surfaceHost.walletMnemonicRestore(phrase,restoreLabel.text.trim(),purpose,method))}catch(_){}
        phrase=""
        if(!result.session_id||!(result.address||result.pubkey)||["READY","VERIFIED_NEEDS_PASSWORD"].indexOf(result.state)<0){errorText="Frasen kunde inte återställas. Kontrollera orden och deras ordning. Inget har sparats.";return}
        _sessionId=String(result.session_id);_sessionLabel=restoreLabel.text.trim();_sessionPurpose=purpose;_sessionMethod=method;_sessionStoreLocally=method==="AI";_sessionCount=[12,24].indexOf(result.word_count)>=0?result.word_count:count
        _publicResult={address:String(result.address||result.pubkey),path:String(result.derivation_path||"m/44'/501'/0'/0'"),purpose:_sessionPurpose,word_count:_sessionCount,method:_sessionMethod,store_locally:_sessionStoreLocally}
        if(_sessionMethod==="AI"&&result.state==="VERIFIED_NEEDS_PASSWORD"){clearPasswords();phase="PASSWORD"}
        else if(_sessionMethod==="PAPER"&&result.state==="READY"){phase="READY";ready(_publicResult)}
        else{cancelSession();phase="RESTORE";errorText="Återställningens nyckelmetod stämde inte med ditt val."}
    }
    function cancel() {
        if(!cancelSession())return
        _submitted=false;phase="SETUP";errorText="";closeRequested()
    }
    function showWarning() {
        if (editingLocked || !localPhrase || !labelField.text.trim()) return
        errorText="";warningAck.checked=false;phase="WARNING"
    }
    function reveal() {
        if (phase!=="WARNING" || !warningAck.checked || editingLocked || !localPhrase) return
        if (!surfaceHost || !surfaceHost.walletMnemonicBegin) {errorText="Frasfunktionen är inte tillgänglig i den här versionen.";return}
        clearWords();clearAnswers();errorText=""
        var result={}
        try { result=parse(surfaceHost.walletMnemonicBegin(labelField.text.trim(),purpose,wordCount,method)) } catch (_) {}
        if (typeof result.session_id!=="string" || !result.session_id || !Array.isArray(result.words) || result.words.length!==wordCount || result.words.some(function(word){return typeof word!=="string"||!/^[a-z]{3,12}$/.test(word)})) {
            if(result.session_id && surfaceHost.walletMnemonicCancel)surfaceHost.walletMnemonicCancel(String(result.session_id))
            errorText="Frasen kunde inte skapas. Inga nycklar har sparats.";return
        }
        _sessionId=String(result.session_id);_sessionLabel=labelField.text.trim();_sessionPurpose=purpose;_sessionCount=wordCount
        _sessionStoreLocally=storeLocally
        _sessionMethod=method
        _words=result.words.slice();result.words=[];_attempts=0;writtenAck.checked=false;phase="REVEAL"
    }
    function challenge() {
        if (phase!=="REVEAL" || !writtenAck.checked || !_sessionId || editingLocked) return
        // Drop every UI reference before requesting random challenge positions.
        clearWords();clearAnswers();errorText=""
        var result={}
        try { result=parse(surfaceHost.walletMnemonicChallenge(_sessionId)) } catch (_) {}
        if (!Array.isArray(result.indices) || result.indices.length!==3 || result.indices.some(function(n,i,all){return !Number.isInteger(n)||n<1||n>root._sessionCount||all.indexOf(n)!==i})) {
            cancelSession();phase="SETUP";errorText="Kontrollen kunde inte startas. Skapa en ny fras.";return
        }
        _indices=result.indices.slice();phase="CHALLENGE";answer1.forceActiveFocus()
    }
    function verify() {
        if (phase!=="CHALLENGE" || !_sessionId || editingLocked || !answer1.text.trim() || !answer2.text.trim() || !answer3.text.trim()) return
        var answers={}
        answers[String(_indices[0])]=answer1.text.trim().toLowerCase()
        answers[String(_indices[1])]=answer2.text.trim().toLowerCase()
        answers[String(_indices[2])]=answer3.text.trim().toLowerCase()
        clearAnswers();errorText=""
        var result={}
        try { result=parse(surfaceHost.walletMnemonicVerify(_sessionId,JSON.stringify(answers))) } catch (_) {}
        answers=({})
        var needsPassword=_sessionMethod==="AI"&&result.state==="VERIFIED_NEEDS_PASSWORD"
        if ((!needsPassword&&result.state!=="READY") || !(result.address || result.pubkey)) {
            _attempts++
            if(_attempts>=3){cancelSession();phase="SETUP";errorText="Tre kontroller misslyckades. Frasen är avbruten; skapa en ny för att fortsätta."}
            else errorText="Orden stämde inte med de efterfrågade numren. Läs från ditt papper och försök igen."
            return
        }
        _publicResult={address:String(result.address || result.pubkey),path:String(result.path || result.derivation_path || "m/44'/501'/0'/0'"),purpose:_sessionPurpose,word_count:_sessionCount,method:_sessionMethod,store_locally:_sessionStoreLocally}
        _indices=[]
        if(needsPassword){clearPasswords();phase="PASSWORD"}
        else{phase="READY";ready(_publicResult)}
    }
    function setPassword() {
        if(phase!=="PASSWORD"||_sessionMethod!=="AI"||editingLocked||vaultPassword.text.length<12||vaultPassword.text!==vaultPasswordAgain.text)return
        if(!surfaceHost||!surfaceHost.walletMnemonicSetPassword){errorText="Lösenordskryptering är inte tillgänglig i den här versionen.";return}
        var password=vaultPassword.text;clearPasswords();errorText=""
        var result={}
        try{result=parse(surfaceHost.walletMnemonicSetPassword(_sessionId,password))}catch(_){}
        password=""
        if(result.state!=="READY"){errorText="Lösenordet kunde inte förberedas. Inget har sparats. Försök igen.";return}
        phase="READY";ready(_publicResult)
    }
    function finish() {
        if (phase!=="READY" || !_sessionId || !_publicResult.address || editingLocked) return
        clearWords();clearAnswers();clearPasswords();_submitted=true;phase="APPROVAL"
        actionRequested("create_wallet",{label:_sessionLabel,mnemonic_session:_sessionId})
    }
    Component.onDestruction: {clearWords();clearAnswers();clearPasswords();cancelSession()}

    component Copy: Text { color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;wrapMode:Text.WordWrap }
    component Action: CryptoButton {height:28;font.pixelSize:11;enabled:!root.editingLocked}
    component Answer: CryptoField {
        property bool sensitiveInput:true
        height:30;maximumLength:16;echoMode:TextInput.Password;selectByMouse:false
        inputMethodHints:Qt.ImhHiddenText|Qt.ImhSensitiveData|Qt.ImhNoPredictiveText|Qt.ImhNoAutoUppercase
        Keys.onPressed:function(event){if((event.modifiers&Qt.ControlModifier)&&(event.key===Qt.Key_C||event.key===Qt.Key_X))event.accepted=true}
    }

    Column {
        id: heading;x:12;y:8;width:Math.max(0,root.width-24);spacing:5
        Copy {width:parent.width;text:"SKAPA WALLET · SOLANA";font.pixelSize:13;color:RuntimeTheme.GGTheme.bright;font.bold:true}
        Copy {width:parent.width;text:({SETUP:"1 · Välj användning och nyckelmetod",RESTORE:"Återställ med dina egna ord",WARNING:"2 · Läs innan frasen visas",REVEAL:"3 · Skriv numrerade ord på papper",CHALLENGE:"4 · Kontrollera din papperskopia",PASSWORD:"5 · Kryptera din portabla fras",READY:(root._sessionMethod==="AI"?"6":"5")+" · Granska offentlig adress",APPROVAL:"Väntar på godkännande"})[root.phase] || "";color:RuntimeTheme.GGTheme.cyan}
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    Item {
        id: body;x:12;y:heading.y+heading.height+10;width:Math.max(0,root.width-24)
        height:Math.max(0,footer.y-y-8);clip:true
        Column {width:parent.width;spacing:8;visible:root.phase==="SETUP"
            Row {width:parent.width;spacing:6
                Action {objectName:"mnemonicSelfCustody";width:(parent.width-6)/2;text:"Eget konto";checked:root.accountMode==="SELF_CUSTODY";onClicked:root.accountMode="SELF_CUSTODY"}
                Action {objectName:"mnemonicAiAssisted";width:(parent.width-6)/2;text:"AI-assisterat";checked:root.accountMode==="AI_ASSISTED";onClicked:root.accountMode="AI_ASSISTED"}
            }
            Copy {width:parent.width;text:"Trading och förvaring är användningsområden. Båda kan ha en egen pappersfras.";color:RuntimeTheme.GGTheme.muted}
            Row {width:parent.width;spacing:6
                Action {objectName:"mnemonicPurposeTrading";width:(parent.width-6)/2;text:"Trading";checked:root.purpose==="TRADING";onClicked:root.purpose="TRADING"}
                Action {objectName:"mnemonicPurposeStorage";width:(parent.width-6)/2;text:"Förvaring";checked:root.purpose==="STORAGE";onClicked:root.purpose="STORAGE"}
            }
            Copy {text:"Nyckelmetod";color:RuntimeTheme.GGTheme.muted;visible:root.accountMode==="SELF_CUSTODY"}
            CryptoPick {objectName:"mnemonicMethod";width:parent.width;height:28;visible:root.accountMode==="SELF_CUSTODY";model:["Papperswallet · egen nyckel","Ledger · extern enhet","Tangem · extern enhet","Annan extern signerare"]
                currentIndex:["PAPER","LEDGER","TANGEM","EXTERNAL"].indexOf(root.method)
                onActivated:root.method=["PAPER","LEDGER","TANGEM","EXTERNAL"][currentIndex]
            }
            Copy {width:parent.width;visible:!root.localPhrase;text:"Direktanslutning till denna externa signerare är inte implementerad här. Ingen lokal fras skapas för en extern enhet. Lägg till dess offentliga adress genom befintlig bevakning.";color:RuntimeTheme.GGTheme.warning}
            Action {objectName:"mnemonicExternalConnect";width:parent.width;visible:!root.localPhrase;text:"Anslut offentlig adress";onClicked:root.externalRequested(root.method,root.purpose)}
            Copy {text:"Antal ord · engelska BIP39";color:RuntimeTheme.GGTheme.muted;visible:root.localPhrase}
            Row {width:parent.width;spacing:6;visible:root.localPhrase
                Action {objectName:"mnemonicWords12";width:(parent.width-6)/2;text:"12 ord";checked:root.wordCount===12;onClicked:root.wordCount=12}
                Action {objectName:"mnemonicWords24";width:(parent.width-6)/2;text:"24 ord";checked:root.wordCount===24;onClicked:root.wordCount=24}
            }
            CryptoField {id:labelField;objectName:"mnemonicLabel";width:parent.width;height:28;maximumLength:64;text:"GG · Solana";placeholderText:"Kontonamn";Accessible.name:"Namn på ny wallet"}
            Action {objectName:"mnemonicOpenRestore";width:parent.width;height:24;flat:true;text:"Återställ med ord";visible:root.localPhrase;onClicked:root.openRestore(root.purpose)}
            Copy {width:parent.width;visible:root.localPhrase;text:"Solana · m/44'/501'/0'/0'\n"+(root.storeLocally?"AI-assisterat: frasen blir lösenordskrypterad och portabel. Den lokala signeringsnyckeln följer programmets godkännanden. Kontot är ditt.":"Eget konto: endast offentlig bevakningsadress sparas. Ingen privat nyckel lagras i GG. Du signerar med en egen wallet.");color:RuntimeTheme.GGTheme.dim}
        }
        Column {width:parent.width;spacing:10;visible:root.phase==="RESTORE"
            Copy {width:parent.width;text:"Ange 12 eller 24 engelska BIP39-ord lokalt. Frasen skickas inte till chatten och visas inte som en fullständig ordlista här.";color:RuntimeTheme.GGTheme.warning}
            Row {width:parent.width;spacing:6
                Action {width:(parent.width-6)/2;text:"Eget konto";checked:root.method==="PAPER";onClicked:{root.accountMode="SELF_CUSTODY";root.method="PAPER"}}
                Action {width:(parent.width-6)/2;text:"AI-assisterat";checked:root.method==="AI";onClicked:{root.accountMode="AI_ASSISTED";root.method="AI"}}
            }
            Row {width:parent.width;spacing:6
                Action {width:(parent.width-6)/2;text:"Trading";checked:root.purpose==="TRADING";onClicked:root.purpose="TRADING"}
                Action {width:(parent.width-6)/2;text:"Förvaring";checked:root.purpose==="STORAGE";onClicked:root.purpose="STORAGE"}
            }
            CryptoField {id:restoreLabel;objectName:"mnemonicRestoreLabel";width:parent.width;height:28;maximumLength:64;placeholderText:"Kontonamn"}
            Copy {text:"Din privata fras";color:RuntimeTheme.GGTheme.muted}
            Answer {id:restorePhrase;objectName:"mnemonicRestorePhrase";width:parent.width;maximumLength:512;height:34;Accessible.name:"Din privata återställningsfras"}
            Copy {width:parent.width;text:root.restoreWordCount+" ord · kräver 12 eller 24";color:[12,24].indexOf(root.restoreWordCount)>=0?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.dim}
            Copy {width:parent.width;text:root.method==="AI"?"Du väljer sedan ett eget lösenord för en portabel krypterad kopia. Sparandet kräver ditt godkännande.":"GG sparar endast den offentliga adressen. Ingen privat nyckel eller fras behålls för ditt papperskonto.";color:RuntimeTheme.GGTheme.muted}
        }
        Column {width:parent.width;spacing:12;visible:root.phase==="WARNING"
            Copy {width:parent.width;text:"Frasen ger full kontroll över din wallet.";font.bold:true;color:RuntimeTheme.GGTheme.warning;font.pixelSize:13}
            Copy {width:parent.width;text:"Skriv varje ord tillsammans med sitt nummer, från 1 till "+root.wordCount+", på papper. Ordningen måste vara exakt."}
            Copy {width:parent.width;text:"Ta ingen skärmbild. Lägg inte frasen i chatten, en fil eller urklipp. Ingen från GG behöver se orden.";color:RuntimeTheme.GGTheme.muted}
            Copy {width:parent.width;text:"Nästa steg visar frasen en gång. Därefter döljs den och du får skriva tre efterfrågade ord från ditt papper.";color:RuntimeTheme.GGTheme.muted}
            Copy {width:parent.width;text:root.method==="PAPER"?"Efter kontrollsteget kan GG inte visa denna pappersfras igen. GG sparar den inte.":"Du väljer sedan ett eget lösenord för en krypterad, portabel fras. Du kan själv låsa upp den igen med ditt lösenord.";color:RuntimeTheme.GGTheme.muted}
            CryptoToggle {id:warningAck;objectName:"mnemonicWarningAck";width:parent.width;text:"Jag har papper redo och förstår att orden måste hållas privata."}
        }
        Column {width:parent.width;spacing:6;visible:root.phase==="REVEAL"
            Copy {id:revealNotice;width:parent.width;text:"Skriv numret och ordet exakt som det visas. Ingen kopiering eller skärmbild.";color:RuntimeTheme.GGTheme.warning}
            Grid {id:wordsGrid;objectName:"mnemonicWordsGrid";width:parent.width;columns:width>=620?4:width>=460?3:2;columnSpacing:8;rowSpacing:4
                property bool privateSensitive:true
                readonly property int rowsNeeded:Math.ceil(root._sessionCount/columns)
                readonly property real rowHeight:Math.max(17,Math.min(28,(body.height-revealNotice.implicitHeight-writtenAck.implicitHeight-12-Math.max(0,rowsNeeded-1)*rowSpacing)/Math.max(1,rowsNeeded)))
                Repeater {model:root._words
                    Rectangle {required property string modelData;required property int index;objectName:"mnemonicWordCell"
                        width:(wordsGrid.width-(wordsGrid.columns-1)*8)/wordsGrid.columns;height:wordsGrid.rowHeight;color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.line
                        Copy {x:6;width:24;height:parent.height;verticalAlignment:Text.AlignVCenter;text:String(parent.index+1);color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
                        Copy {x:32;width:parent.width-38;height:parent.height;verticalAlignment:Text.AlignVCenter;text:parent.modelData;wrapMode:Text.NoWrap;font.pixelSize:11}
                    }
                }
            }
            CryptoToggle {id:writtenAck;objectName:"mnemonicWrittenAck";width:parent.width;text:"Jag har skrivit alla "+root._sessionCount+" numrerade ord på papper."}
        }
        Column {width:parent.width;spacing:10;visible:root.phase==="CHALLENGE"
            Copy {width:parent.width;text:"Frasen är dold. Fyll i orden för dessa tre nummer från din papperskopia.";color:RuntimeTheme.GGTheme.muted}
            Copy {text:"Ord "+String(root._indices[0] || "—");color:RuntimeTheme.GGTheme.cyan}
            Answer {id:answer1;objectName:"mnemonicAnswer1";width:parent.width;Accessible.name:"Första efterfrågade ordet"}
            Copy {text:"Ord "+String(root._indices[1] || "—");color:RuntimeTheme.GGTheme.cyan}
            Answer {id:answer2;objectName:"mnemonicAnswer2";width:parent.width;Accessible.name:"Andra efterfrågade ordet"}
            Copy {text:"Ord "+String(root._indices[2] || "—");color:RuntimeTheme.GGTheme.cyan}
            Answer {id:answer3;objectName:"mnemonicAnswer3";width:parent.width;Accessible.name:"Tredje efterfrågade ordet"}
        }
        Column {width:parent.width;spacing:10;visible:root.phase==="PASSWORD"
            Copy {width:parent.width;text:"Välj ett eget lösenord för den portabla frasen. Den krypterade kopian tillhör dig och kan flyttas mellan dina enheter.";color:RuntimeTheme.GGTheme.muted}
            Copy {text:"Lösenord · minst 12 tecken";color:RuntimeTheme.GGTheme.muted}
            Answer {id:vaultPassword;objectName:"mnemonicVaultPassword";width:parent.width;maximumLength:256;Accessible.name:"Lösenord för portabel fras"}
            Copy {text:"Skriv samma lösenord igen";color:RuntimeTheme.GGTheme.muted}
            Answer {id:vaultPasswordAgain;objectName:"mnemonicVaultPasswordAgain";width:parent.width;maximumLength:256;Accessible.name:"Bekräfta lösenord för portabel fras"}
            Copy {width:parent.width;visible:!!vaultPasswordAgain.text&&vaultPassword.text!==vaultPasswordAgain.text;text:"Lösenorden stämmer inte överens.";color:RuntimeTheme.GGTheme.negative}
            Copy {width:parent.width;text:"GG sparar inte lösenordet i kontoinformationen. Fras och signeringsnyckel sparas först efter ditt godkännande.";color:RuntimeTheme.GGTheme.dim}
        }
        Column {width:parent.width;spacing:10;visible:root.phase==="READY"||root.phase==="APPROVAL"
            Copy {width:parent.width;text:"Papperskopian är kontrollerad. Inget har ännu sparats.";color:RuntimeTheme.GGTheme.positive}
            Copy {width:parent.width;text:"Användning: "+(root._sessionPurpose==="STORAGE"?"Förvaring":"Trading")+"\nMetod: "+(root._sessionMethod==="AI"?"AI-assisterat konto":"Egen papperswallet")+" · "+root._sessionCount+" ord\n"+(root._sessionStoreLocally?"Portabel lösenordskrypterad fras · lokal signeringsnyckel":"Endast offentlig bevakning · egen signering")}
            Copy {width:parent.width;text:"Solana-adress";color:RuntimeTheme.GGTheme.muted}
            Copy {objectName:"mnemonicPublicAddress";width:parent.width;text:root._publicResult.address || "";wrapMode:Text.WrapAnywhere;color:RuntimeTheme.GGTheme.bright}
            Copy {width:parent.width;text:root._publicResult.path || "";color:RuntimeTheme.GGTheme.dim}
            Copy {width:parent.width;text:root.phase==="APPROVAL"?"Den granskade begäran är skickad till chatten. Svara ja eller nej där. Frasen skickas inte till chatten.":"Nästa knapp begär godkännande av denna adress. Frasen skickas inte till chatten.";color:RuntimeTheme.GGTheme.warning}
        }
    }
    Column {
        id:footer;x:12;y:Math.max(heading.y+heading.height,root.height-height-8);width:Math.max(0,root.width-24);spacing:6
        Copy {objectName:"mnemonicError";width:parent.width;visible:!!root.errorText;text:root.errorText;color:RuntimeTheme.GGTheme.negative}
        Row {width:parent.width;spacing:6
            Action {objectName:"mnemonicCancel";width:92;text:"Avbryt";enabled:true;onClicked:root.cancel()}
            Action {objectName:"mnemonicNext";width:Math.max(0,parent.width-98)
                text:({SETUP:"Fortsätt",RESTORE:"Kontrollera fras lokalt",WARNING:"Visa frasen lokalt",REVEAL:"Dölj och kontrollera",CHALLENGE:"Kontrollera ord",PASSWORD:"Förbered kryptering",READY:"Begär godkännande",APPROVAL:"Väntar på godkännande"})[root.phase] || "Fortsätt"
                enabled:!root.editingLocked&&(root.phase==="SETUP"?root.localPhrase&&!!labelField.text.trim():root.phase==="RESTORE"?root.localPhrase&&[12,24].indexOf(root.restoreWordCount)>=0&&!!restoreLabel.text.trim():root.phase==="WARNING"?warningAck.checked:root.phase==="REVEAL"?writtenAck.checked:root.phase==="CHALLENGE"?!!answer1.text.trim()&&!!answer2.text.trim()&&!!answer3.text.trim():root.phase==="PASSWORD"?vaultPassword.text.length>=12&&vaultPassword.text===vaultPasswordAgain.text:root.phase==="READY")
                onClicked:{if(root.phase==="SETUP")root.showWarning();else if(root.phase==="RESTORE")root.restore();else if(root.phase==="WARNING")root.reveal();else if(root.phase==="REVEAL")root.challenge();else if(root.phase==="CHALLENGE")root.verify();else if(root.phase==="PASSWORD")root.setPassword();else if(root.phase==="READY")root.finish()}
            }
        }
    }
}
