import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: panel
    objectName: "gameLocalServices"
    required property var surfaceHost
    property var game: null
    property var services: ({})
    property var inventory: []
    property var people: []
    property string playerName: "Gold Goblin"
    property string targetId: ""
    property string message: ""
    property var skillForgetRequest: ({})
    property var lootSelectionMemory: ({})
    property string enchantReviewKey: JSON.stringify([
        services.session,
        (services.trade || {}).shared_trade_id,
        ((services.trade || {}).target_enchant_target_reference || {}).asset,
        ((services.trade || {}).target_enchant_target_reference || {}).item_hash,
        enchantScroll.selectedId,
        (((services.trade || {}).scroll_references || {})[enchantScroll.selectedId] || {}).asset,
        (((services.trade || {}).scroll_references || {})[enchantScroll.selectedId] || {}).item_hash
    ])
    onEnchantReviewKeyChanged: {
        if (enchantReplace) enchantReplace.checked = false
        if (enchantBind) enchantBind.checked = false
    }
    onServicesChanged: {
        var retained = ({})
        for (var roll of (services.loot_rolls || []).slice(0, 128))
            if (Object.prototype.hasOwnProperty.call(lootSelectionMemory, roll.id)) retained[roll.id] = lootSelectionMemory[roll.id]
        lootSelectionMemory = retained
    }
    signal serviceUpdated(var snapshot)
    title: "GG · Världens tjänster"
    modal: true
    width: Math.min(940, parent ? parent.width - 24 : 940)
    height: Math.min(640, parent ? parent.height - 24 : 640)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    closePolicy: Popup.CloseOnEscape
    footer: DialogButtonBox {
        Button { text:"Stäng";DialogButtonBox.buttonRole:DialogButtonBox.RejectRole }
        onRejected:panel.close()
    }
    palette.window: "#202126"
    palette.windowText: "#e9e3d6"
    palette.text: "#e9e3d6"
    palette.base: "#15171b"
    palette.button: "#303137"
    palette.buttonText: "#e9e3d6"
    palette.placeholderText: "#a29e97"
    palette.highlight: "#95743d"
    background: Rectangle { color: "#202126"; border.color: "#92794b"; radius: 5 }

    function money(copper) {
        var n = Math.max(0, Number(copper || 0))
        return Math.floor(n / 10000) + " g " + Math.floor(n / 100) % 100 + " s " + n % 100 + " k"
    }
    function tradeGear(partner) {
        var trade = services.trade || {}
        return partner ? (trade.target_rows || [])[6] || null : (trade.player_rows || {})["7"] || null
    }
    function enchantNames(gear) {
        return ((gear || {}).enchantments || []).map(function(row) {
            return row.name || row.id
        }).join(", ") || "ingen"
    }
    function tradeGearText(row) {
        if (!row) return "Ingen utrustning vald"
        return row.name + " · " + (row.location === "EQUIPPED" ? "utrustad: "+row.equipped_slot : "ryggsäck") +
            " · nuvarande förtrollning: " + enchantNames(row.gear) + (row.bound ? " · redan bunden" : "")
    }
    function tradeGearChoices() {
        var trade = services.trade || {}
        var rows = trade.shared_trade === true ? trade.gear_items || [] : inventory.filter(function(row) { return !!row.gear })
        return rows.map(function(row) { return Object.assign({}, row, {choice_name:row.name +
            (row.location === "EQUIPPED" ? " · utrustad: "+row.equipped_slot : " · ryggsäck")}) })
    }
    function tradeScrollChoices() {
        return ((services.trade || {}).enchant_scrolls || []).map(function(row) {
            return Object.assign({}, row, {choice_name:row.name+" · "+row.id+" · antal "+(row.quantity || 1)})
        })
    }
    function enchantServiceText(service) {
        if (!service) return "Ingen förtrollning erbjuden"
        var stats = (service.preview || {}).stats || {}
        return service.name+" · scroll "+service.scroll+" × "+service.quantity+
            " · nivå "+service.required_level+
            (service.replace ? " · ersätter "+(service.old_enchant || "ingen") : " · läggs till utan ersättning")+
            (service.bind ? " · binder utrustningen till ägaren" : " · ingen ny bindning")+
            " · efter: "+enchantNames(service.preview)+
            " · egenskaper: "+Object.keys(stats).sort().map(function(key) { return key+" "+stats[key] }).join(", ")
    }
    function channelRows() {
        return ((services.channels || {}).rows || []).map(function(row) {
            return Object.assign({}, row, {selection_id:row.channel_id || "local:"+row.name.toLowerCase()})
        })
    }
    function channelFields(channel, fields) {
        var row = Object.assign({name:channel.name}, fields || {})
        row.shared_channel = channel.shared_channel === true
        if (row.shared_channel) {
            row.channel_id = channel.channel_id
            row.channel_revision = channel.channel_revision
        }
        return row
    }
    function joinChannel() {
        var name = channelName.text.trim()
        var known = ((services.channels || {}).rows || []).find(function(row) {
            return row.name.toLowerCase() === name.toLowerCase() ||
                row.builtin && row.name.toLowerCase() === name.toLowerCase()+" - gg island"
        })
        var offer = (services.channels || {}).shared_invite
        if (!known && offer && offer.name.toLowerCase() === name.toLowerCase()) known = offer
        var fields = known ? channelFields(known, {password:channelPassword.text}) :
            {name:name, password:channelPassword.text, shared_channel:sharedChannel.checked}
        if (command("ChannelJoin", fields)) channelPassword.clear()
    }
    function channelSelf(channel) {
        if (!channel || channel.shared_channel !== true) return "player"
        if (channel.player_id !== undefined) return channel.player_id
        var index = (channel.member_names || []).indexOf(playerName)
        return index >= 0 ? channel.members[index] : ""
    }
    function channelOwner(channel) {
        if (!channel) return false
        if (channel.is_owner !== undefined) return channel.is_owner === true
        var self = channelSelf(channel)
        return !!self && channel.owner === self
    }
    function channelManager(channel) {
        if (!channel || channel.builtin) return false
        if (channel.can_manage !== undefined) return channel.can_manage === true
        var self = channelSelf(channel)
        return !!self && (channelOwner(channel) || (channel.moderators || []).indexOf(self) >= 0)
    }
    function command(op, fields) {
        if (!surfaceHost || !surfaceHost.gameEngineClientControl) return false
        var row = Object.assign({kind:"service", op:op, session:services.session}, fields || {})
        if (["PetitionOffer","PetitionRename","PetitionSign","PetitionClose","PetitionTurnIn"].indexOf(op) >= 0) {
            var petition = services.petition || {}
            var record = op === "PetitionTurnIn" ? ((petition.owned || [])[0] || {}) : (petition.record || {})
            for (var key of ["petition_owner","petition_asset","petition_terms"])
                if (record[key] !== undefined) row[key] = record[key]
            if ((op === "PetitionSign" || op === "PetitionClose") && record.petition_offer !== undefined)
                row.petition_offer = record.petition_offer
        }
        if (op === "TradeAccept") row.offer_revision = (services.trade || {}).offer_revision
        var trade = services.trade || {}
        if (trade.shared_trade === true && op.indexOf("Trade") === 0 && op !== "TradeOpen") {
            row.shared_trade = true
            for (var tradeKey of ["id","owner","recipient","revision","terms"])
                row["shared_trade_"+tradeKey] = trade["shared_trade_"+tradeKey]
            if (op === "TradeSet") row.shared_trade_item =
                (row.slot === 7 ? trade.gear_references || {} : trade.inventory_references || {})[row.item]
            if (op === "TradeEnchant") row.shared_trade_scroll = (trade.scroll_references || {})[row.scroll]
        }
        try {
            var result = JSON.parse(surfaceHost.gameEngineClientControl(JSON.stringify(row)))
            if (result.error) {
                var errors = {SERVICE_WINDOW_CHANGED_OR_CLOSED:"Fönstret har ändrats. Öppna tjänsten igen.",
                    SERVICE_INSUFFICIENT_MONEY:"Pengarna räcker inte.", ITEM_INVENTORY_FULL:"Ryggsäcken är full.",
                    TRADE_OFFER_CHANGED_ACCEPT_AGAIN:"Avtalet ändrades. Kontrollera det och acceptera igen.",
                    PET_LIVE_LAND_ANIMAL_IN_REACH_REQUIRED:"Gå närmare ett levande landdjur.",
                    SERVICE_PERSON_OUT_OF_REACH:"Gå närmare din handelspartner.",
                    CORPSE_RECOVERY_DELAY:"Vänta tills kroppen kan återhämtas.",
                    CORPSE_OUT_OF_REACH:"Gå till din kropp innan du återhämtar den.",
                    SPIRIT_HEALER_OUT_OF_REACH:"Gå närmare personen som återupplivar dig.",
                    PLAYER_DEFEATED:"Handlingen kräver att karaktären lever.",
                    PROFESSION_NOT_KNOWN:"Du behöver lära dig yrket innan du kan tillverka detta.",
                    PROFESSION_TRAINER_REQUIRED:"Mira Saltwake kan lära ut yrken. Gå fram till henne.",
                    GUILD_REGISTRAR_REQUIRED:"Mira Saltwake registrerar guildkontrakt. Gå fram till henne.",
                    PETITION_NEEDS_SIGNATURES:"Kontraktet behöver tre underskrifter.",
                    PETITION_ALREADY_OWNED:"Du har redan ett guildkontrakt i ryggsäcken.",
                    PETITION_ALREADY_SIGNED_OR_FULL:"Personen har redan skrivit under, eller kontraktet är fullt.",
                    PETITION_OFFER_PENDING:"En invånare överväger fortfarande din förfrågan.",
                    PETITION_CANNOT_SIGN:"Du kan inte skriva under detta kontrakt.",
                    GUILD_NAME_INVALID:"Skriv ett guildnamn utan dubbla eller inledande/avslutande blanksteg.",
                    GUILD_EMBLEM_UNCHANGED:"Emblemet är redan sparat; ingen ny avgift tas ut.",
                    GUILD_PERMISSION_DENIED:"Den här ändringen kräver guildledarens rättigheter.",
                    SELF_RESURRECT_ITEM_REQUIRED:"Du saknar ett föremål för egen återupplivning.",
                    BATTLEFIELD_RECOVERY_REQUIRED:"Vänta tills återhämtningen efter förra kampen är klar.",
                    BATTLEFIELD_QUEUE_CHANGED:"Köplatsen har ändrats. Kontrollera den aktuella kön.",
                    BATTLEFIELD_IN_PROGRESS:"Avsluta kampen innan du reser vidare.",
                    INSTANCE_ENTRANCE_OUT_OF_REACH:"Gå fram till expeditionens entré.",
                    INSTANCE_OUT_OF_COMBAT_REQUIRED:"Avsluta striden innan du går tillbaka till entrén.",
                    INSTANCE_OCCUPIED:"Alla deltagare behöver lämna området innan expeditionen återställs.",
                    INSTANCE_RESET_LIMIT:"Du har återställt fem expeditioner den senaste timmen. Vänta innan du återställer igen.",
                    INSTANCE_RAID_LOCKED:"Raidens sparade tillstånd gäller tills återställningstiden har gått ut.",
                    CHANNEL_CHANGED:"Kanalen har ändrats. Granska dess aktuella tillstånd och försök igen.",
                    CHANNEL_PASSWORD_INVALID:"Kanalens lösenord stämmer inte.",
                    CHANNEL_SAVED_CHARACTER_REQUIRED:"Välj en sparad karaktär för den delade kanalen.",
                    CHANNEL_CUSTOM_NAME_REQUIRED:"Skriv ett eget kanalnamn. Världens standardkanaler väljs utan delning.",
                    CHANNEL_MUTED:"Du kan inte skriva i den här kanalen just nu.",
                    CHANNEL_MODERATOR_REQUIRED:"Ändringen kräver kanalens ägare eller moderator.",
                    CHANNEL_OWNER_REQUIRED:"Ändringen kräver kanalens ägare.",
                    MEETINGSTONE_OUT_OF_REACH:"Gå närmare expeditionens entré för att söka kompanjoner.",
                    MEETINGSTONE_REQUEST_EXPIRED:"Gruppförfrågan har gått ut. Sök kompanjoner igen.",
                    MEETINGSTONE_OFFER_REQUIRED:"Vänta tills kompanjonerna är redo innan du bildar gruppen.",
                    MEETINGSTONE_SOLO_REQUIRED:"Lämna din nuvarande grupp innan du söker en ny.",
                    MAIL_MUST_COLLECT_ASSETS_FIRST:"Hämta föremål och pengar innan du tar bort brevet."}
                message = errors[result.error] || "Åtgärden kunde inte genomföras. Kontrollera mottagare, föremål och saldo."
            } else message = ""
            serviceUpdated(result)
            return !result.error
        } catch (_) { message = "Tjänsten kunde inte nås."; return false }
    }
    function selectTab(index) {
        tabs.currentIndex = index
        if (index === 0) command("MailOpen")
        if (index === 1) command("AuctionOpen")
        if (index === 2 && targetId && (services.trade || {}).shared_trade !== true) command("TradeOpen", {target:targetId})
        if (index === 4) command("StableOpen")
    }
    function openLifecycle() { tabs.currentIndex = 7;panel.open() }
    onOpened: selectTab(tabs.currentIndex)
    Timer {
        interval:500;repeat:true;running:panel.visible
        onTriggered: {
            if (!panel.surfaceHost || !panel.surfaceHost.gameEngineStatus) return
            try { panel.serviceUpdated(JSON.parse(panel.surfaceHost.gameEngineStatus())) }
            catch (_) { panel.message="Tjänstens aktuella tillstånd kunde inte läsas." }
        }
    }
    onClosed: {
        forgetSkill.close()
        tabardDesigner.close()
        for (var key of ["mail","auction","trade","stable","trainer"]) {
            if (key === "trade" && (services.trade || {}).shared_trade === true) continue
            if ((services[key] || {}).open) command(key[0].toUpperCase()+key.slice(1)+"Close")
        }
        if ((services.petition || {}).open) command("PetitionClose")
        if ((services.petition || {}).registrar_open) command("PetitionRegistrarClose")
    }

    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Label { text: "Lokal värld"; color: "#c9ad72"; Layout.fillWidth: true }
            Label { objectName:"localServiceWallet"; text: panel.money(panel.services.money); color:"#ebcf84" }
        }
        TabBar {
            id: tabs
            Layout.fillWidth: true
            Repeater {
                model: ["Post", "Auktioner", "Handel", "Grupp", "Pets", "Guild", "Loot", "Karaktär", "Chatt", "Resor", "Yrken", "Spel"]
                TabButton {
                    id:serviceTab
                    required property string modelData
                    required property int index
                    objectName:"localServiceTab"+index
                    text:modelData
                    implicitHeight:40
                    contentItem:Label { text:serviceTab.text;color:serviceTab.checked ? "#fff0cf" : "#d5cbb8";horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter }
                    background:Rectangle { color:serviceTab.checked ? "#695330" : serviceTab.hovered ? "#3b3b3e" : "#2b2d32";border.color:serviceTab.checked ? "#b5955d" : "#414044";radius:2 }
                    onClicked:panel.selectTab(index)
                }
            }
        }
        Label { text:panel.message; color:"#f0a58a"; visible:text.length>0; wrapMode:Text.WordWrap; Layout.fillWidth:true }
        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            // One item instance remains in mail custody until collection.
            RowLayout {
                ScrollView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                    ColumnLayout {
                        width:parent.width;spacing:8
                        Label { text:"Inkorg · "+((panel.services.mail || {}).rows || []).length+" brev";color:"#d8bd83" }
                        Repeater {
                            model:(panel.services.mail || {}).rows || []
                            delegate:Frame {
                                required property var modelData
                                Layout.fillWidth:true
                                ColumnLayout {
                                    anchors.fill:parent
                                    Label { text:modelData.subject; font.bold:true; Layout.fillWidth:true; wrapMode:Text.WordWrap }
                                    Label { text:modelData.sender_name+" · "+panel.money(modelData.money); color:"#b8b2a6" }
                                    Label { text:modelData.body;Layout.fillWidth:true;wrapMode:Text.WordWrap;maximumLineCount:4;elide:Text.ElideRight }
                                    Label { visible:!!modelData.attachment;text:modelData.attachment ? modelData.attachment.name+" × "+modelData.attachment.quantity : "";color:"#c6b3df" }
                                    Label { visible:modelData.cod>0;text:"Postförskott: "+panel.money(modelData.cod);color:"#e0b471" }
                                    RowLayout {
                                        Button { text:"Läs";onClicked:panel.command("MailRead",{id:modelData.id}) }
                                        Button { objectName:"localMailItem";text:"Hämta";enabled:!!modelData.attachment;onClicked:panel.command("MailItem",{id:modelData.id}) }
                                        Button { objectName:"localMailMoney";text:"Pengar";enabled:modelData.money>0;onClicked:panel.command("MailMoney",{id:modelData.id}) }
                                        Button { text:"Ta bort";enabled:!modelData.attachment&&!modelData.money;onClicked:panel.command("MailDelete",{id:modelData.id}) }
                                    }
                                }
                            }
                        }
                        Label { visible:!((panel.services.mail || {}).rows || []).length;text:"Inkorgen är tom.";color:"#9e9b94" }
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth:320;Layout.maximumWidth:340;Layout.minimumWidth:280;Layout.fillHeight:true
                    Label { text:"Skicka ett brev";color:"#d8bd83" }
                    TextField { id:recipient;objectName:"localMailRecipient";Layout.fillWidth:true;placeholderText:"Ditt namn eller en lokal handlare";text:panel.playerName }
                    TextField { id:subject;objectName:"localMailSubject";Layout.fillWidth:true;placeholderText:"Ämne";maximumLength:128 }
                    ScrollView { Layout.fillWidth:true;Layout.preferredHeight:110;TextArea { id:body;objectName:"localMailBody";placeholderText:"Meddelande";wrapMode:TextEdit.Wrap } }
                    LocalServiceComboBox { id:attachment;valueRole:"instance_id";objectName:"localMailAttachment";Layout.fillWidth:true;textRole:"name";entries:[{name:"Inget föremål",instance_id:""}].concat(panel.inventory);displayText:currentIndex < 0 ? "Inget föremål" : currentText }
                    Label { text:"Pengar / postförskott (koppar)";color:"#a6a198" }
                    RowLayout {
                        SpinBox { id:mailMoney;objectName:"localMailSendMoney";from:0;to:2000000000;editable:true;Layout.fillWidth:true }
                        SpinBox { id:cod;from:0;to:2000000000;editable:true;Layout.fillWidth:true }
                    }
                    Label { text:"Porto: 30 koppar";color:"#a6a198" }
                    Button {
                        text:"Skicka";objectName:"localMailSend";enabled:recipient.text.trim().length>0&&subject.text.trim().length>0
                        onClicked:if(panel.command("MailSend",{target:recipient.text,subject:subject.text,body:body.text,money:mailMoney.value,cod:cod.value,
                            item:(attachment.selectedId || "")})) {subject.clear();body.clear();mailMoney.value=0;cod.value=0;attachment.currentIndex=0}
                    }
                    Item { Layout.fillHeight:true }
                }
            }

            ColumnLayout {
                RowLayout {
                    TextField { id:auctionSearch;Layout.fillWidth:true;placeholderText:"Sök föremål";onAccepted:panel.command("AuctionQuery",{query:{name:text,page:0}}) }
                    Button { text:"Sök";onClicked:panel.command("AuctionQuery",{query:{name:auctionSearch.text,page:0}}) }
                    Label { text:"Köp och bud levereras med post.";color:"#a6a198" }
                }
                ScrollView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                    ColumnLayout {
                        width:parent.width
                        Repeater {
                            model:((panel.services.auction || {}).lists || [{rows:[]}])[0].rows
                            delegate:Frame {
                                required property var modelData
                                Layout.fillWidth:true
                                RowLayout {
                                    anchors.fill:parent
                                    ColumnLayout {
                                        Layout.fillWidth:true
                                        Label { text:modelData.attachment ? modelData.attachment.name+" × "+modelData.attachment.quantity : "";font.bold:true }
                                        Label { text:modelData.owner_name+" · Bud "+panel.money(modelData.bid || modelData.min_bid);color:"#b8b2a6" }
                                    }
                                    Button { text:"Bjud";enabled:modelData.owner!=="player";onClicked:panel.command("AuctionBid",{id:modelData.id,amount:modelData.bid ? modelData.bid+Math.max(1,Math.floor(modelData.bid/20)) : modelData.min_bid}) }
                                    Button { objectName:"localAuctionBuyout";text:"Köp "+panel.money(modelData.buyout);enabled:modelData.buyout>0&&modelData.owner!=="player";onClicked:panel.command("AuctionBid",{id:modelData.id,amount:modelData.buyout}) }
                                    Button { text:"Avbryt";visible:modelData.owner==="player";onClicked:panel.command("AuctionCancel",{id:modelData.id}) }
                                }
                            }
                        }
                    }
                }
                Label { text:"Lägg ut ett föremål · priser i koppar · deposition 5 % per två timmar";color:"#d8bd83" }
                RowLayout {
                    LocalServiceComboBox { id:saleItem;objectName:"localAuctionSaleItem";valueRole:"instance_id";Layout.fillWidth:true;entries:panel.inventory;textRole:"name" }
                    SpinBox { id:minBid;from:1;to:100000000;value:10000;editable:true }
                    SpinBox { id:buyout;from:0;to:100000000;value:20000;editable:true }
                    ComboBox { id:duration;model:["2 timmar","8 timmar","24 timmar"] }
                    Button { text:"Lägg ut";objectName:"localAuctionPost";enabled:saleItem.currentIndex>=0;onClicked:panel.command("AuctionStart",{item:saleItem.selectedId,min_bid:minBid.value,buyout:buyout.value,duration:[120,480,1440][duration.currentIndex]}) }
                }
            }

            ColumnLayout {
                ScrollView {
                    id: tradeReviewScroll
                    objectName:"localTradeReviewScroll"
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                    ColumnLayout {
                    width:tradeReviewScroll.availableWidth
                Label { text:(panel.services.trade || {}).pending ? "Handelserbjudande från "+panel.services.trade.target_name : (panel.services.trade || {}).open ? "Handel med "+panel.services.trade.target_name : "Välj en person i världen och gå närmare för att handla.";color:"#d8bd83" }
                Button { text:"Öppna handel med ditt mål";enabled:panel.targetId.length>0;onClicked:panel.command("TradeOpen",{target:panel.targetId}) }
                Button { objectName:"localTradeClose";text:"Avsluta NPC-handeln";visible:(panel.services.trade || {}).open===true && (panel.services.trade || {}).shared_trade!==true;onClicked:panel.command("TradeCancel") }
                RowLayout {
                    LocalServiceComboBox { id:savedTradePerson;valueRole:"id";objectName:"localSavedTradePerson";entries:panel.services.saved_recipients || [];textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localSavedTradeOpen";text:"Erbjud handel till sparad karaktär";enabled:!!savedTradePerson.selectedRow;onClicked:{if(savedTradePerson.selectedRow)panel.command("TradeOpen",{target:savedTradePerson.selectedRow.id,shared_trade:true})} }
                }
                Label { visible:(panel.services.trade || {}).shared_trade===true;text:"Båda karaktärerna granskar och accepterar efter karaktärsbyte. Ändringar kräver nytt samtycke.";wrapMode:Text.WordWrap;Layout.fillWidth:true;color:"#a6a198" }
                Button { objectName:"localSavedTradeJoin";text:"Svara på handelserbjudandet";visible:(panel.services.trade || {}).shared_trade===true && (panel.services.trade || {}).pending===true;onClicked:panel.command("TradeBegin") }
                RowLayout {
                    Label { text:"Du ger" }
                    LocalServiceComboBox { id:give;objectName:"localTradeGive";valueRole:"instance_id";entries:panel.inventory;textRole:"name";Layout.fillWidth:true }
                    Button { text:"Lägg till";enabled:(panel.services.trade || {}).open&&!!give.selectedRow;onClicked:{if(!give.selectedRow)return;var slots=panel.services.trade.slots || {};for(var i=1;i<=6;i++)if(!slots[String(i)]){panel.command("TradeSet",{slot:i,item:give.selectedId});break}} }
                }
                Repeater {
                    model:Object.keys((panel.services.trade || {}).player_rows || {}).filter(function(slot) { return Number(slot)>=1 && Number(slot)<=6 })
                    delegate:RowLayout {
                        required property string modelData
                        Label { objectName:"localTradeGiveRow"+modelData;text:(panel.services.trade.player_rows[modelData] || {}).name ? panel.services.trade.player_rows[modelData].name+" × "+panel.services.trade.player_rows[modelData].quantity : "";Layout.fillWidth:true }
                        Button { text:"Ta bort";onClicked:panel.command("TradeClear",{slot:Number(modelData)}) }
                    }
                }
                RowLayout {
                    visible:(panel.services.trade || {}).shared_trade!==true
                    Label { text:"Du får" }
                    LocalServiceComboBox { id:receive;objectName:"localTradeReceive";valueRole:"instance_id";entries:(panel.services.trade || {}).stock || [];textRole:"name";Layout.fillWidth:true }
                    Button { text:"Välj";enabled:!!receive.selectedRow;onClicked:{if(receive.selectedRow)panel.command("TradeTarget",{item:receive.selectedRow.instance_id})} }
                }
                Label { objectName:"localTradeReceiveSummary";text:"Du får: "+((panel.services.trade || {}).target_rows || []).slice(0,6).filter(function(r){return !!r}).map(function(r){return r.name+" × "+r.quantity}).join(", ")+((panel.services.trade || {}).shared_trade===true ? " · "+panel.money((panel.services.trade || {}).target_money) : "");color:"#c6b3df";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Label { text:"Förtrollningsplats 7 · utrustningen stannar hos sin ägare";color:"#d8bd83";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Label { objectName:"localTradeOwnGear";text:"Din utrustning: "+panel.tradeGearText(panel.tradeGear(false));wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    LocalServiceComboBox { id:enchantGear;objectName:"localTradeEnchantGear";valueRole:"instance_id";entries:panel.tradeGearChoices();textRole:"choice_name";Layout.fillWidth:true }
                    Button { objectName:"localTradeSetEnchantGear";text:"Välj plats 7";enabled:!!enchantGear.selectedRow&&(panel.services.trade || {}).open && ((panel.services.trade || {}).shared_trade!==true || !!((panel.services.trade || {}).gear_references || {})[enchantGear.selectedId]);onClicked:{if(enchantGear.selectedRow)panel.command("TradeSet",{slot:7,item:enchantGear.selectedId})} }
                    Button { objectName:"localTradeClearEnchantGear";text:"Töm plats 7";enabled:!!panel.tradeGear(false)&&(panel.services.trade || {}).open;onClicked:panel.command("TradeClear",{slot:7}) }
                }
                Label { objectName:"localTradePartnerGear";visible:(panel.services.trade || {}).shared_trade===true;text:"Motpartens utrustning: "+panel.tradeGearText(panel.tradeGear(true));wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    LocalServiceComboBox { id:enchantScroll;objectName:"localTradeEnchantScroll";valueRole:"id";entries:panel.tradeScrollChoices();textRole:"choice_name";Layout.fillWidth:true }
                    Button {
                        objectName:"localTradeSetEnchant";text:(panel.services.trade || {}).shared_trade===true ? "Erbjud förtrollning till motparten" : "Välj förtrollning"
                        enabled:!!enchantScroll.selectedRow&&(panel.services.trade || {}).open &&
                            ((panel.services.trade || {}).shared_trade!==true || !!panel.tradeGear(true) &&
                             enchantScroll.selectedRow.instance_id === enchantScroll.selectedRow.id &&
                             !!((panel.services.trade || {}).scroll_references || {})[enchantScroll.selectedId] &&
                             typeof enchantScroll.selectedRow.binds === "boolean" &&
                             (((panel.tradeGear(true).gear || {}).enchantments || []).length===0 || enchantReplace.checked) &&
                             (!enchantScroll.selectedRow.binds || panel.tradeGear(true).bound || enchantBind.checked))
                        onClicked: {
                            var selected = enchantScroll.selectedRow
                            if (!selected) return
                            var fields = {enchant_id:selected.enchant_id}
                            if ((panel.services.trade || {}).shared_trade===true) {
                                if (!panel.tradeGear(true)) return
                                fields.scroll = selected.instance_id
                                fields.replace = ((panel.tradeGear(true).gear || {}).enchantments || []).length>0 && enchantReplace.checked
                                fields.bind = selected.binds === true && !panel.tradeGear(true).bound && enchantBind.checked
                            }
                            panel.command("TradeEnchant", fields)
                        }
                    }
                    Button { objectName:"localTradeClearEnchant";text:"Ta bort erbjuden förtrollning";visible:(panel.services.trade || {}).shared_trade===true;enabled:!!(panel.services.trade || {}).enchant_service&&(panel.services.trade || {}).open;onClicked:panel.command("TradeEnchantClear") }
                }
                RowLayout {
                    visible:(panel.services.trade || {}).shared_trade===true
                    CheckBox { id:enchantReplace;objectName:"localTradeEnchantReplace";text:"Bekräfta ersättning av motpartens första förtrollning";enabled:!!panel.tradeGear(true) && ((panel.tradeGear(true).gear || {}).enchantments || []).length>0 }
                    CheckBox { id:enchantBind;objectName:"localTradeEnchantBind";text:"Bekräfta bindning till motpartens ägare";enabled:!!enchantScroll.selectedRow && enchantScroll.selectedRow.binds===true && !!panel.tradeGear(true) && !panel.tradeGear(true).bound }
                }
                Label { objectName:"localTradeEnchantCandidate";visible:(panel.services.trade || {}).shared_trade===true && !!enchantScroll.selectedRow;text:enchantScroll.selectedRow ? "Vald scroll: "+enchantScroll.selectedRow.name+" · "+enchantScroll.selectedId+" × 1 · kräver nivå "+enchantScroll.selectedRow.required_level+(typeof enchantScroll.selectedRow.binds!=="boolean" ? " · bindningsvillkor saknas" : enchantScroll.selectedRow.binds ? " · binder obunden utrustning" : " · ingen ny bindning") : "";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Label { objectName:"localTradeOutgoingEnchant";visible:(panel.services.trade || {}).shared_trade===true;text:"Du erbjuder på motpartens utrustning: "+panel.enchantServiceText((panel.services.trade || {}).enchant_service);wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Label { objectName:"localTradeIncomingEnchant";visible:(panel.services.trade || {}).shared_trade===true;text:"Motparten erbjuder på din utrustning: "+panel.enchantServiceText((panel.services.trade || {}).target_enchant_service);wrapMode:Text.WordWrap;Layout.fillWidth:true }
                    }
                }
                RowLayout {
                    Label { text:"Pengar (koppar)" }
                    SpinBox { id:tradeMoney;from:0;to:2000000000;editable:true }
                    Button { text:"Sätt summa";enabled:(panel.services.trade || {}).open;onClicked:panel.command("TradeMoney",{money:tradeMoney.value}) }
                    Label { text:panel.money((panel.services.trade || {}).money) }
                }
                Label { text:"Granska båda sidor innan du accepterar.";color:"#a6a198" }
                Button { text:"Acceptera handel";objectName:"localTradeAccept";enabled:(panel.services.trade || {}).open;onClicked:panel.command("TradeAccept") }
                Label { visible:(panel.services.trade || {}).shared_trade===true;text:((panel.services.trade || {}).player_accepted ? "Du har accepterat" : "Ditt svar väntar")+" · "+((panel.services.trade || {}).target_accepted ? "Motparten har accepterat" : "Motpartens svar väntar");color:"#a6a198";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Button { objectName:"localSavedTradeCancel";text:"Avbryt handelserbjudandet";visible:(panel.services.trade || {}).shared_trade===true;onClicked:panel.command("TradeCancel") }
            }

            ColumnLayout {
                RowLayout {
                    LocalServiceComboBox { id:crew;objectName:"localGroupPerson";valueRole:"id";entries:panel.people.filter(function(p){return p.id!=="player"});textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localGroupInvite";text:"Bjud in";enabled:crew.currentIndex>=0;onClicked:panel.command("GroupInvite",{target:crew.selectedRow.id}) }
                    Button { text:"Raid";onClicked:panel.command("GroupRaid") }
                    Button { text:"Redo?";onClicked:panel.command("GroupReady") }
                    Button { text:"Lämna";onClicked:panel.command("GroupLeave") }
                }
                RowLayout {
                    LocalServiceComboBox { id:savedCrew;valueRole:"id";objectName:"localSavedGroupPerson";entries:panel.services.saved_recipients || [];textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localSavedGroupInvite";text:"Bjud in sparad karaktär";enabled:savedCrew.currentIndex>=0;onClicked:panel.command("GroupInvite",{target:savedCrew.selectedRow.id}) }
                }
                Label { text:(panel.services.group || {}).shared_id ? "Sparad grupp · byt karaktär för att svara på inbjudan." : "Invånare i gruppen följer dig i världen.";color:"#a6a198";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    Button { text:"Be om inbjudan";enabled:crew.currentIndex>=0;onClicked:panel.command("GroupRequestInvite",{target:crew.selectedRow.id}) }
                    Button { text:"Acceptera";visible:!!panel.services.group_invite;onClicked:panel.command("GroupAccept") }
                    Button { text:"Avböj";visible:!!panel.services.group_invite;onClicked:panel.command("GroupDecline") }
                }
                Repeater {
                    model:(panel.services.group || {}).roster || []
                    delegate:RowLayout {
                        required property var modelData
                        Label { text:modelData.name;Layout.preferredWidth:160 }
                        ProgressBar { visible:modelData.online!==false;from:0;to:modelData.max_health;value:modelData.health;Layout.fillWidth:true }
                        Label { text:modelData.online===false ? "Utloggad" : Math.round(modelData.health)+" / "+Math.round(modelData.max_health);Layout.fillWidth:modelData.online===false }
                        Button { text:"Ta bort";visible:modelData.id!=="player";onClicked:panel.command("GroupKick",{target:modelData.id}) }
                    }
                }
                Item { Layout.fillHeight:true }
            }

            ColumnLayout {
                Label { text:panel.services.pet ? panel.services.pet.name+" · nivå "+panel.services.pet.level : "Ingen aktiv följeslagare";color:"#d8bd83" }
                RowLayout {
                    LocalServiceComboBox { id:animals;objectName:"localPetAnimal";valueRole:"id";entries:panel.services.nearby_animals || [];textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localPetTame";text:"Tämj";enabled:animals.currentIndex>=0&&!panel.services.pet;onClicked:panel.command("PetTame",{id:animals.selectedRow.id}) }
                    Button { text:"Följ";enabled:!!panel.services.pet;onClicked:panel.command("PetOrder",{word:117440513}) }
                    Button { text:"Stanna";enabled:!!panel.services.pet;onClicked:panel.command("PetOrder",{word:117440512}) }
                    Button { text:"Attack";enabled:!!panel.services.pet&&panel.targetId.length>0;onClicked:panel.command("PetOrder",{word:117440514}) }
                }
                RowLayout {
                    TextField { id:petName;placeholderText:"Nytt namn";maximumLength:32;Layout.fillWidth:true }
                    Button { text:"Byt namn";enabled:!!panel.services.pet&&!panel.services.pet.renamed;onClicked:panel.command("PetRename",{name:petName.text}) }
                    Button { text:"Stalla";enabled:!!panel.services.pet;onClicked:panel.command("StableStore") }
                    Button { text:"Köp stallplats";enabled:(panel.services.stable || {}).bought<2;onClicked:panel.command("StableBuy") }
                    Button { text:"Återuppliva · 10 g";enabled:!!panel.services.pet&&panel.services.pet.health<=0;onClicked:panel.command("PetRevive") }
                }
                Repeater {
                    model:(panel.services.stable || {}).pets || []
                    delegate:RowLayout {
                        required property var modelData
                        Label { text:modelData.name+" · "+modelData.species;Layout.fillWidth:true }
                        Button { text:panel.services.pet ? "Byt" : "Hämta";enabled:modelData.number!==(panel.services.stable || {}).active;onClicked:panel.command(panel.services.pet ? "StableSwap" : "StableTake",{number:modelData.number}) }
                    }
                }
                Label { text:"Du kan hålla ett aktivt djur och köpa två stallplatser.";color:"#a6a198" }
                Label { visible:!!panel.services.pet;text:panel.services.pet ? "Humör "+panel.services.pet.happiness+" / 3 · lojalitet "+panel.services.pet.loyalty+" · träningspoäng "+(panel.services.pet.training_total-panel.services.pet.training_spent) : "" }
                RowLayout {
                    LocalServiceComboBox { id:petFood;objectName:"localPetFood";valueRole:"instance_id";entries:panel.inventory.filter(function(i){return i.kind==="CONSUMABLE"});textRole:"name";Layout.fillWidth:true }
                    Button { text:"Mata";enabled:!!panel.services.pet&&petFood.currentIndex>=0;onClicked:panel.command("PetFeed",{item:petFood.selectedRow.instance_id}) }
                    LocalServiceComboBox { id:petTrainer;valueRole:"id";objectName:"localPetTrainerSelect";entries:panel.people;textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localPetTrainerOpen";text:"Tränare";enabled:!!panel.services.pet&&petTrainer.currentIndex>=0;onClicked:panel.command("TrainerOpen",{target:petTrainer.selectedRow.id}) }
                }
                Repeater {
                    model:(panel.services.trainer || {}).rows || []
                    delegate:RowLayout {
                        required property var modelData
                        Label { text:modelData.name+" · nivå "+modelData.level+" · "+modelData.points+" poäng";Layout.fillWidth:true }
                        Button { objectName:"localTrainerLearn"+modelData.id;text:modelData.category==="used" ? "Inlärd" : "Lär · "+panel.money(modelData.cost);enabled:modelData.category==="available";onClicked:panel.command("TrainerBuy",{spell_id:modelData.id}) }
                    }
                }
                Item { Layout.fillHeight:true }
            }

            ColumnLayout {
                RowLayout {
                    TextField { id:guildName;objectName:"localGuildName";placeholderText:"Guildens namn";maximumLength:48;Layout.fillWidth:true }
                    Button { objectName:"localGuildCreate";text:"Skapa · 1 g";enabled:!panel.services.guild&&guildName.text.length>0;onClicked:panel.command("GuildCreate",{name:guildName.text}) }
                    Button { text:"Lämna";enabled:!!panel.services.guild;onClicked:panel.command("GuildLeave") }
                }
                Label { text:panel.services.guild ? panel.services.guild.name : "Ingen lokal guild";font.bold:true }
                Button { objectName:"localTabardOpen";text:"Guildemblem och tabard";visible:!!panel.services.guild;onClicked:if(panel.command("TabardOpen"))tabardDesigner.open() }
                RowLayout {
                    visible:!panel.services.guild
                    Button { objectName:"localGuildRegistrar";text:"Guildregistrator";onClicked:panel.command("PetitionRegistrarOpen",{target:"npc-wanderer-01"}) }
                    Button { objectName:"localCharterBuy";text:"Köp kontrakt · "+panel.money((panel.services.petition || {}).cost);enabled:(panel.services.petition || {}).registrar_open&&guildName.text.trim().length>0;onClicked:panel.command("PetitionBuy",{name:guildName.text}) }
                    LocalServiceComboBox { id:ownedCharter;objectName:"localOwnedCharter";valueRole:"item";entries:(panel.services.petition || {}).owned || [];textRole:"title";Layout.fillWidth:true }
                    Button { objectName:"localCharterOpen";text:"Läs kontrakt";enabled:ownedCharter.currentIndex>=0;onClicked:panel.command("PetitionOpen",{item:ownedCharter.selectedRow.item}) }
                    Button { objectName:"localCharterTurnIn";text:"Lämna in";enabled:ownedCharter.currentIndex>=0&&(panel.services.petition || {}).registrar_open===true;onClicked:panel.command("PetitionTurnIn") }
                }
                Label { visible:(panel.services.petition || {}).open===true;text:((panel.services.petition || {}).record || {}).title || "";font.bold:true }
                Label { visible:(panel.services.petition || {}).open===true;Layout.fillWidth:true;wrapMode:Text.WordWrap;text:"Underskrifter: "+((((panel.services.petition || {}).record || {}).signer_names || []).join(", ") || "inga")+" · "+((((panel.services.petition || {}).record || {}).signers || []).length)+"/"+(((panel.services.petition || {}).record || {}).max_signatures || 3) }
                RowLayout {
                    visible:(panel.services.petition || {}).open===true
                    LocalServiceComboBox { id:petitionPerson;valueRole:"id";objectName:"localCharterPerson";entries:panel.people;textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localCharterOffer";text:"Be om underskrift";enabled:((panel.services.petition || {}).record || {}).is_originator===true&&petitionPerson.currentIndex>=0&&!(panel.services.petition || {}).offer;onClicked:panel.command("PetitionOffer",{target:petitionPerson.selectedRow.id}) }
                    Button { text:"Byt namn";enabled:((panel.services.petition || {}).record || {}).is_originator===true&&guildName.text.trim().length>0;onClicked:panel.command("PetitionRename",{name:guildName.text}) }
                    Button { objectName:"localCharterSign";text:"Skriv under";visible:(panel.services.petition || {}).can_sign===true;onClicked:panel.command("PetitionSign") }
                    Button { text:"Stäng kontrakt";onClicked:panel.command("PetitionClose") }
                }
                Label { visible:!!(panel.services.petition || {}).offer;text:"Invånaren överväger din förfrågan. Stanna i närheten.";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    visible:(panel.services.petition || {}).open===true && ((panel.services.petition || {}).record || {}).is_originator===true
                    LocalServiceComboBox { id:savedPetitionPerson;valueRole:"id";objectName:"localSavedCharterPerson";entries:panel.services.saved_recipients || [];textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localSavedCharterOffer";text:"Be sparad karaktär skriva under";enabled:savedPetitionPerson.currentIndex>=0;onClicked:panel.command("PetitionOffer",{target:savedPetitionPerson.selectedRow.id}) }
                }
                Label { visible:(panel.services.petition || {}).open===true && ((panel.services.petition || {}).record || {}).is_originator===true;text:"Sparade karaktärer svarar efter karaktärsbyte.";color:"#a6a198";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    LocalServiceComboBox { id:guildPerson;valueRole:"id";entries:panel.people;textRole:"name";Layout.fillWidth:true }
                    Button { text:"Bjud in";enabled:!!panel.services.guild&&guildPerson.currentIndex>=0;onClicked:panel.command("GuildInvite",{target:guildPerson.selectedRow.id}) }
                    Button { text:"Be om inbjudan";enabled:!panel.services.guild&&guildPerson.currentIndex>=0&&guildName.text.length>0;onClicked:panel.command("GuildRequestInvite",{target:guildPerson.selectedRow.id,name:guildName.text}) }
                    TextField { id:guildMotd;placeholderText:"Dagens meddelande";maximumLength:255;Layout.fillWidth:true }
                    Button { text:"Spara";enabled:!!panel.services.guild;onClicked:panel.command("GuildMotd",{text:guildMotd.text}) }
                }
                Label { text:(panel.services.guild || {}).motd || "";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                RowLayout {
                    visible:!!panel.services.guild_invite
                    Label { text:panel.services.guild_invite ? "Inbjudan till "+panel.services.guild_invite.name : "";Layout.fillWidth:true }
                    Button { text:"Acceptera";onClicked:panel.command("GuildAccept") }
                    Button { text:"Avböj";onClicked:panel.command("GuildDecline") }
                }
                ScrollView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                    ColumnLayout {
                        width:parent.width
                        Repeater {
                            model:(panel.services.guild || {}).roster || []
                            delegate:RowLayout {
                                required property var modelData
                                Label { text:modelData.name+" · "+modelData.rank_name;Layout.fillWidth:true }
                                Button { text:"Befordra";visible:modelData.id!=="player";onClicked:panel.command("GuildPromote",{target:modelData.id}) }
                                Button { text:"Ta bort";visible:modelData.id!=="player";onClicked:panel.command("GuildUninvite",{target:modelData.id}) }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                RowLayout {
                    ComboBox { id:lootMethod;model:["freeforall","roundrobin","master","group","needbeforegreed"];Layout.fillWidth:true }
                    Button { text:"Välj fördelning";onClicked:panel.command("GroupLoot",{method:lootMethod.currentText,master:"player",threshold:2}) }
                }
                Label { text:"Aktiv metod: "+((panel.services.group || {}).loot_method || "freeforall") }
                ScrollView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                    ColumnLayout {
                        width:parent.width
                        Repeater {
                            model:panel.services.loot_rolls || []
                            delegate:Frame {
                                required property var modelData
                                Layout.fillWidth:true
                                ColumnLayout {
                                    anchors.fill:parent
                                    Label { text:modelData.attachment ? modelData.attachment.name : "Föremål";font.bold:true }
                                    RowLayout {
                                        visible:modelData.method!=="master"
                                        Button { objectName:"localLootNeed";text:"Need";enabled:!modelData.confirmation;onClicked:panel.command(modelData.bind ? "LootRollConfirm" : "LootRollVote",{id:modelData.id,vote:1}) }
                                        Button { text:"Greed";enabled:!modelData.confirmation;onClicked:panel.command(modelData.bind ? "LootRollConfirm" : "LootRollVote",{id:modelData.id,vote:2}) }
                                        Button { text:"Pass";onClicked:panel.command("LootRollVote",{id:modelData.id,vote:0}) }
                                    }
                                    Label { visible:!!modelData.confirmation;text:"Föremålet blir bundet om du vinner det. Bekräfta ditt val.";Layout.fillWidth:true;wrapMode:Text.WordWrap }
                                    RowLayout {
                                        visible:!!modelData.confirmation
                                        Button { objectName:"localLootBindAccept";text:"Bekräfta bindning";onClicked:panel.command("LootRollVote",{id:modelData.id,vote:(modelData.confirmation || {}).vote}) }
                                        Button { objectName:"localLootBindCancel";text:"Avbryt valet";onClicked:panel.command("LootRollCancelConfirm",{id:modelData.id}) }
                                    }
                                    RowLayout {
                                        visible:modelData.method==="master"
                                        LocalServiceComboBox { id:lootRecipient;objectName:"localLootRecipient"+modelData.id;valueRole:"id";entries:modelData.candidates || [];textRole:"name";Layout.fillWidth:true;selectionMemory:panel.lootSelectionMemory;selectionKey:modelData.id }
                                        Button { text:"Tilldela";enabled:lootRecipient.currentIndex>=0;onClicked:panel.command("LootMasterGive",{id:modelData.id,target:lootRecipient.selectedRow.id}) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                property var life: panel.services.lifecycle || ({})
                Label { text:parent.life.dead ? (parent.life.ghost ? "Ande · återvänd till din kropp" : "Karaktären har dött") : "Karaktären lever";font.bold:true;Layout.fillWidth:true }
                Label { text:parent.life.position ? "Kropp: "+Number(parent.life.position.x).toFixed(1)+", "+Number(parent.life.position.z).toFixed(1)+" · väntetid "+Math.ceil(parent.life.recovery_delay || 0)+" s" : "";visible:text.length>0 }
                RowLayout {
                    visible:parent.life.dead === true
                    Button { objectName:"localReleaseSpirit";text:"Släpp anden";enabled:!parent.parent.life.ghost;onClicked:panel.command("DeathRepop") }
                    Button { objectName:"localRecoverCorpse";text:"Återhämta kroppen";enabled:parent.parent.life.ghost && !(parent.parent.life.recovery_delay>0);onClicked:panel.command("DeathRetrieveCorpse") }
                    Button { text:"Egen återupplivning";enabled:!!parent.parent.life.self_res_label;onClicked:panel.command("DeathUseSoulstone") }
                }
                LocalServiceComboBox { id:lifecyclePerson;valueRole:"id";entries:panel.people;textRole:"name";Layout.fillWidth:true }
                RowLayout {
                    Button { text:"Bind hemort";enabled:lifecyclePerson.currentIndex>=0&&!parent.parent.life.dead;onClicked:panel.command("BinderOpen",{target:lifecyclePerson.selectedRow.id}) }
                    Button { objectName:"localBinderConfirm";text:"Bekräfta hemort";enabled:parent.parent.life.binder_pending || false;onClicked:panel.command("BinderConfirm") }
                    Button { text:"Be om återupplivning";enabled:lifecyclePerson.currentIndex>=0&&parent.parent.life.dead;onClicked:panel.command("DeathOfferResurrect",{target:lifecyclePerson.selectedRow.id}) }
                }
                RowLayout {
                    visible:parent.life.dead === true
                    Button { text:"Acceptera återupplivning";enabled:parent.parent.life.resurrection_pending || false;onClicked:panel.command("DeathAcceptResurrect") }
                    Button { text:"Avböj";enabled:parent.parent.life.resurrection_pending || false;onClicked:panel.command("DeathDeclineResurrect") }
                    Button { text:"Spirit healer";enabled:lifecyclePerson.currentIndex>=0&&parent.parent.life.ghost;onClicked:panel.command("DeathHealerOpen",{target:lifecyclePerson.selectedRow.id}) }
                    Button { text:"Bekräfta · 25% hållbarhet";enabled:parent.parent.life.healer_in_range || false;onClicked:panel.command("DeathAcceptXpLoss") }
                }
                Label { text:"Hemort: "+(parent.life.bind ? parent.life.bind.name : "Öns utgångspunkt");Layout.fillWidth:true }
                RowLayout {
                    visible:!parent.life.dead
                    Button { objectName:"localDuelStart";text:"Utmaning till duell";enabled:lifecyclePerson.currentIndex>=0&&!parent.parent.life.duel;onClicked:panel.command("DuelStart",{target:lifecyclePerson.selectedRow.id}) }
                    Button { text:"Acceptera duell";enabled:!!parent.parent.life.duel && parent.parent.life.duel.state==="REQUESTED";onClicked:panel.command("DuelAccept") }
                    Button { text:"Ge upp / avböj";enabled:!!parent.parent.life.duel;onClicked:panel.command("DuelCancel") }
                }
                Label { text:parent.life.duel ? "Duell: "+parent.life.duel.state : "Dueller ger inga föremål eller XP.";Layout.fillWidth:true }
                Label { text:"Återupplivningssjukdom: "+Math.ceil((parent.life.sickness_remaining || 0)/60)+" min";visible:parent.life.sickness_remaining>0;Layout.fillWidth:true }
                Item { Layout.fillHeight:true }
            }
            ColumnLayout {
                id:channelPage
                readonly property var selected: chatChannel.selectedRow
                readonly property bool manages: panel.channelManager(selected)
                readonly property bool owns: panel.channelOwner(selected)
                RowLayout {
                    TextField { id:channelName;objectName:"localChannelName";placeholderText:"Kanalnamn";maximumLength:80;Layout.fillWidth:true }
                    Button { objectName:"localChannelJoin";text:"Gå med";enabled:channelName.text.trim().length>0;onClicked:panel.joinChannel() }
                    Button { text:"Lista kanaler";onClicked:panel.command("ChannelListAll") }
                }
                RowLayout {
                    CheckBox { id:sharedChannel;objectName:"localChannelShared";text:"Ny kanal för sparade karaktärer";enabled:(panel.services.channels || {}).shared_available === true }
                    TextField { id:channelPassword;objectName:"localChannelPassword";placeholderText:"Lösenord (valfritt)";echoMode:TextInput.Password;maximumLength:128;Layout.fillWidth:true }
                }
                RowLayout {
                    visible:!!(panel.services.channels || {}).shared_invite
                    Label { text:(panel.services.channels || {}).shared_invite ? "Inbjudan till "+panel.services.channels.shared_invite.name+" från "+panel.services.channels.shared_invite.sender_name : "";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                    Button { objectName:"localChannelInviteSelect";text:"Välj inbjudan";onClicked:{channelName.text=panel.services.channels.shared_invite.name;sharedChannel.checked=true;channelPassword.forceActiveFocus()} }
                }
                LocalServiceComboBox { id:chatChannel;valueRole:"selection_id";objectName:"localChannelSelect";entries:panel.channelRows();textRole:"name";Layout.fillWidth:true }
                RowLayout {
                    TextField { id:channelMessage;objectName:"localChannelMessage";placeholderText:"Skriv till kanalen";maximumLength:255;Layout.fillWidth:true;onAccepted:channelSend.clicked() }
                    Button { id:channelSend;objectName:"localChannelSend";text:"Skicka";enabled:!!channelPage.selected&&channelMessage.text.trim().length>0;onClicked:if(panel.command("ChannelMessage",panel.channelFields(channelPage.selected,{text:channelMessage.text})))channelMessage.clear() }
                    Button { text:"Lämna";enabled:!!channelPage.selected;onClicked:panel.command("ChannelLeave",panel.channelFields(channelPage.selected)) }
                    Button { text:"Medlemmar";enabled:!!channelPage.selected;onClicked:panel.command("ChannelList",panel.channelFields(channelPage.selected)) }
                }
                Label { text:!channelPage.selected ? "Välj en kanal." : channelPage.selected.shared_channel ? "Delad kanal · ägare "+channelPage.selected.owner_name+" · "+(channelPage.selected.member_names || []).join(", ") : "Kanal för invånarna i den lokala världen.";color:"#c9ad72";Layout.fillWidth:true;wrapMode:Text.WordWrap }
                RowLayout {
                    LocalServiceComboBox { id:channelPerson;valueRole:"id";objectName:"localChannelPerson";entries:channelPage.selected && channelPage.selected.shared_channel ? (panel.services.saved_recipients || []) : panel.people;textRole:"name";Layout.fillWidth:true }
                    Button { objectName:"localChannelInvite";text:"Bjud in";enabled:channelPage.manages&&channelPerson.hasSelection;onClicked:panel.command("ChannelInvite",panel.channelFields(channelPage.selected,{player:channelPerson.selectedId})) }
                    Button { objectName:"localChannelKick";text:"Ta bort";enabled:channelPage.manages&&channelPerson.hasSelection;onClicked:panel.command("ChannelKick",panel.channelFields(channelPage.selected,{player:channelPerson.selectedId})) }
                }
                Flow {
                    Layout.fillWidth:true;spacing:5
                    Repeater {
                        model:[{op:"ChannelModerator",label:"Moderator",owner:true},{op:"ChannelUnmoderator",label:"Ta bort moderator",owner:true},
                            {op:"ChannelMute",label:"Tysta"},{op:"ChannelUnmute",label:"Tillåt tal"},{op:"ChannelBan",label:"Banna"},
                            {op:"ChannelUnban",label:"Häv bann"},{op:"ChannelSetOwner",label:"Överlåt kanal",owner:true}]
                        Button {
                            required property var modelData
                            objectName:"local"+modelData.op;text:modelData.label
                            enabled:(modelData.owner ? channelPage.owns : channelPage.manages)&&channelPerson.hasSelection
                            onClicked:panel.command(modelData.op,panel.channelFields(channelPage.selected,{player:channelPerson.selectedId}))
                        }
                    }
                }
                RowLayout {
                    Button { objectName:"localChannelModerate";text:channelPage.selected && channelPage.selected.moderated ? "Fri chatt" : "Moderera";enabled:channelPage.selected && channelPage.selected.shared_channel ? channelPage.owns : channelPage.manages;onClicked:panel.command("ChannelModerate",panel.channelFields(channelPage.selected)) }
                    Button { objectName:"localChannelAnnouncements";text:channelPage.selected && channelPage.selected.announcements ? "Dölj meddelanden" : "Visa meddelanden";enabled:channelPage.manages;onClicked:panel.command("ChannelToggleAnnouncements",panel.channelFields(channelPage.selected)) }
                    Button { objectName:"localChannelSetPassword";text:"Spara lösenord";enabled:channelPage.owns;onClicked:if(panel.command("ChannelSetPassword",panel.channelFields(channelPage.selected,{password:channelPassword.text})))channelPassword.clear() }
                }
                Item { Layout.fillHeight:true }
            }
            ColumnLayout {
                property var trip:panel.services.travel || {}
                property var life:panel.services.lifecycle || {}
                LocalServiceComboBox { id:travelPerson;valueRole:"id";objectName:"localTravelPerson";entries:panel.people;textRole:"name";Layout.fillWidth:true;enabled:!parent.trip.riding&&!parent.life.dead }
                RowLayout {
                    Button { objectName:"localTaxiOpen";text:"Visa resmål";enabled:travelPerson.currentIndex>=0&&!parent.parent.trip.riding&&!parent.parent.life.dead;onClicked:panel.command("TaxiOpen",{target:travelPerson.selectedRow.id}) }
                    Button { text:"Stäng resmålen";enabled:parent.parent.trip.open || false;onClicked:panel.command("TaxiClose") }
                }
                LocalServiceComboBox { id:taxiDestination;valueRole:"id";objectName:"localTaxiDestination";entries:parent.trip.nodes || [];textRole:"name";Layout.fillWidth:true;visible:parent.trip.open || false }
                Label { text:parent.trip.riding ? "Resan pågår. Du får tillbaka kontrollen vid ankomst." : taxiDestination.selectedRow ? "Pris: "+panel.money(taxiDestination.selectedRow.cost) : "Välj en person i närheten och öppna resmålen.";Layout.fillWidth:true;wrapMode:Text.WordWrap }
                Button { objectName:"localTaxiTake";text:"Res till staden";enabled:!!taxiDestination.selectedRow&&!parent.trip.riding&&!taxiDestination.selectedRow.current;onClicked:if(taxiDestination.selectedRow)panel.command("TaxiTake",{destination:taxiDestination.selectedRow.id}) }
                Label { text:"På väg · "+Math.ceil(parent.trip.remaining || 0)+" s kvar";visible:parent.trip.riding || false }
                RowLayout {
                    Button { text:"Be gruppmedlem kalla hit mig";enabled:travelPerson.currentIndex>=0&&!parent.parent.life.dead&&!parent.parent.trip.riding;onClicked:panel.command("SummonOffer",{target:travelPerson.selectedRow.id}) }
                    Button { text:"Acceptera summon";enabled:(parent.parent.trip.summon || {}).remaining_ms>0;onClicked:panel.command("SummonConfirm") }
                }
                Label { text:"Kallelse från "+((parent.trip.summon || {}).summoner || "")+" · "+Math.ceil(((parent.trip.summon || {}).remaining_ms || 0)/1000)+" s";visible:(parent.trip.summon || {}).remaining_ms>0;Layout.fillWidth:true }
                Button { text:"Fastnat? Återvänd till hemorten";enabled:!parent.life.dead&&!parent.trip.riding&&!(parent.trip.stuck_remaining>0);onClicked:panel.command("StuckStart") }
                Label { text:"Återhämtning · "+Math.ceil(parent.trip.stuck_remaining || 0)+" s kvar. Rörelse avbryter.";visible:parent.trip.stuck_remaining>0;Layout.fillWidth:true }
                Item { Layout.fillHeight:true }
            }
            ColumnLayout {
                Label { text:"Yrken · din karaktärs färdigheter";color:"#d8bd83" }
                Repeater {
                    model:(panel.services.skills || {}).rows || []
                    delegate:RowLayout {
                        required property var modelData
                        Label { text:modelData.name+" · "+modelData.level+" / "+modelData.max_level+" · "+modelData.xp+" XP";Layout.fillWidth:true }
                        Button { objectName:"localSkillForget"+modelData.key;text:"Glöm yrket";onClicked:{panel.skillForgetRequest={skill_id:modelData.id,session:panel.services.session,name:modelData.name};forgetSkill.open()} }
                    }
                }
                Label { text:"Ett glömt yrke förlorar sin nivå och kan inte användas för crafting. Mira Saltwake kan lära ut det igen från nivå 1.";wrapMode:Text.WordWrap;Layout.fillWidth:true;color:"#c9ad72" }
                RowLayout {
                    Button { objectName:"localProfessionTrainerOpen";text:"Träna yrken hos Mira";onClicked:panel.command("TrainerOpen",{target:"npc-wanderer-01",mode:"PROFESSION"}) }
                    Button { text:"Stäng tränaren";enabled:(panel.services.trainer || {}).open || false;onClicked:panel.command("TrainerClose") }
                }
                Repeater {
                    model:(panel.services.trainer || {}).kind==="PROFESSION" ? panel.services.trainer.rows || [] : []
                    delegate:RowLayout {
                        required property var modelData
                        Label { text:modelData.name;Layout.fillWidth:true }
                        Button { objectName:"localProfessionLearn"+modelData.key;text:modelData.category==="used" ? "Inlärt" : "Lär · "+panel.money(modelData.cost);enabled:modelData.category==="available";onClicked:panel.command("TrainerBuy",{spell_id:modelData.id}) }
                    }
                }
                Item { Layout.fillHeight:true }
            }
            LocalGameSessions {
                services: panel.services
                onRequested: function(operation,fields) { panel.command(operation,fields) }
            }
        }
    }
    Dialog {
        id:tabardDesigner
        objectName:"localTabardDesigner"
        parent:panel.parent
        modal:true;title:"GG · Guildens emblem"
        width:Math.min(780,parent ? parent.width-24 : 780)
        height:Math.min(500,parent ? parent.height-24 : 500)
        palette:panel.palette
        background:Rectangle { color:"#202126";border.color:"#92794b";radius:5 }
        x:parent ? (parent.width-width)/2 : 0;y:parent ? (parent.height-height)/2 : 0
        readonly property var state:panel.services.tabard || ({})
        function changeDesign(index,value) {
            var design=(state.preview || [0,4,0,4,10]).slice()
            design[index]=value
            panel.command("TabardPreview",{design:design})
        }
        onClosed:if(state.open)panel.command("TabardClose")
        footer:DialogButtonBox { standardButtons:DialogButtonBox.Close;onRejected:tabardDesigner.close() }
        contentItem:RowLayout {
            Loader {
                active:tabardDesigner.visible
                Layout.minimumWidth:200;Layout.preferredWidth:340
                Layout.fillWidth:true;Layout.fillHeight:true
                sourceComponent:GameCharacterPreview {
                    objectName:"localTabardPreview"
                    game:panel.game
                    equipment: {
                        var rows=panel.game && panel.game.items ? (panel.game.items.equipment || []).filter(function(r){return r.equipped_slot!=="TABARD"}) : []
                        return tabardDesigner.state.cloth ? rows.concat([tabardDesigner.state.cloth]) : rows
                    }
                }
            }
            ColumnLayout {
                Layout.minimumWidth:300;Layout.preferredWidth:340;Layout.maximumWidth:340
                Repeater {
                    model:["Symbol","Symbolfärg","Kant","Kantfärg","Bakgrund"]
                    delegate:RowLayout {
                        required property int index
                        required property string modelData
                        Label { text:modelData;Layout.fillWidth:true }
                        SpinBox { Layout.preferredWidth:140;objectName:"localTabardField"+parent.index;from:0;to:[169,16,5,16,50][parent.index];value:(tabardDesigner.state.preview || [0,4,0,4,10])[parent.index];onValueModified:tabardDesigner.changeDesign(parent.index,value) }
                    }
                }
                Label { text:"Förhandsvisning på din karaktär";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Button { objectName:"localTabardSave";text:"Spara · "+panel.money(tabardDesigner.state.cost);enabled:tabardDesigner.state.open&&tabardDesigner.state.can_save;onClicked:panel.command("TabardSave",{design:tabardDesigner.state.preview}) }
                Button { objectName:"localTabardBuy";text:"Köp extra tabard · "+panel.money(tabardDesigner.state.cloth_cost);enabled:tabardDesigner.state.open;onClicked:panel.command("TabardBuy") }
                Label { text:"Första sparningen inkluderar en tabard i ryggsäcken.";wrapMode:Text.WordWrap;Layout.fillWidth:true }
                Label { text:panel.message;color:"#ef9c82";wrapMode:Text.WordWrap;Layout.fillWidth:true }
            }
        }
    }

    Dialog {
        id:forgetSkill
        objectName:"localSkillForgetDialog"
        title:"Glöm "+(panel.skillForgetRequest.name || "yrket")+"?"
        modal:true
        anchors.centerIn:parent
        standardButtons:Dialog.Yes | Dialog.No
        onOpened:{standardButton(Dialog.Yes).objectName="localSkillForgetConfirm";standardButton(Dialog.Yes).text="Glöm";standardButton(Dialog.No).text="Avbryt"}
        Label { text:"Nivå och erfarenhet i yrket försvinner. Du kan lära dig det igen hos tränaren.";width:360;wrapMode:Text.WordWrap }
        onAccepted:panel.command("SkillAbandon",panel.skillForgetRequest)
    }
}
