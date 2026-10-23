//! Original service views and queues over the same local GG authority.
use engine_ui_core::script::{UiScript, ScriptValue, UnitState, MailState, MailInboxRow, MailInvoice,
    StationeryView, AuctionState, AuctionListState, AuctionItemRow, AuctionHighBidder,
    AuctionCategory, AuctionSubCategory, TradeState, TradeSlotItem, PartyState, PartyMemberInfo,
    RaidMemberInfo, PartyRequest, PetActionView, PetStats, PetBookState, SpellSlotView, StableState, StablePetSlot, StableIntent, ItemTextState};
use serde_json::{Value,json};
use crate::Host;

fn n(v:&Value,key:&str)->u32 {v[key].as_f64().filter(|v|v.is_finite()).unwrap_or(0.).clamp(0.,u32::MAX as f64) as u32}
fn s(v:&Value,key:&str)->String {v[key].as_str().unwrap_or("").to_owned()}
fn opt(v:&Value,key:&str)->Option<String>{v[key].as_str().filter(|s|!s.is_empty()).map(str::to_owned)}
fn rows<'a>(v:&'a Value,key:&str,cap:usize)->Result<&'a Vec<Value>,String>{
    v[key].as_array().filter(|v|v.len()<=cap).ok_or_else(||format!("invalid GG service {key}"))
}
fn unit(v:&Value)->UnitState{
    let online=v["online"].as_bool().unwrap_or(true);
    let mut unit=UnitState::default();unit.exists=true;unit.has_object=online;unit.is_connected=online;
    unit.guid=v["guid"].as_u64().unwrap_or(0);unit.name=opt(v,"name");unit.level=n(v,"level").max(1);
    unit.health=n(v,"health");unit.max_health=n(v,"max_health").max(1);unit.dead=online&&unit.health==0;
    unit.class=opt(v,"class_name");unit.class_file=opt(v,"class_file");
    unit.player_controlled=true;unit.can_attack=false;unit.reaction=5;unit.raid_target=n(v,"raid_target").min(8) as u8;unit
}
fn trade_item(v:&Value)->Option<TradeSlotItem>{
    if !v.is_object(){return None;}Some(TradeSlotItem{item_id:n(v,"item_id"),name:opt(v,"name"),
        texture:opt(v,"icon"),count:n(v,"quantity"),quality:Some(n(v,"quality")),link:opt(v,"link"),enchantment:opt(v,"enchantment")})
}

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let old=host.views.get("services").cloned().unwrap_or(Value::Null);
    let mail=&v["mail"];
    if old["mail"]!=*mail{
        let mut entries=Vec::new();
        for r in rows(mail,"rows",128)?{
            let item=&r["attachment"];let invoice=&r["invoice"];
            entries.push(MailInboxRow{sender:Some(s(r,"sender_name")),subject:s(r,"subject"),body:Some(s(r,"body")),
                money:n(r,"money"),cod:n(r,"cod"),days_left:r["days_left"].as_f64().unwrap_or(0.) as f32,
                item_count:if item.is_object(){1}else{0},was_read:r["read"]==true,was_returned:r["returned"]==true,
                text_created:r["permanent"]==true,has_body:!s(r,"body").is_empty(),can_reply:s(r,"sender")!="Auction House",
                item_id:n(item,"item_id"),item_name:opt(item,"name"),item_texture:opt(item,"icon"),item_quality:if item.is_object(){Some(n(item,"quality"))}else{None},
                can_delete:n(r,"money")==0&&!item.is_object(),stationery_texture:"Interface\\Stationery\\StationeryTest1".into(),
                is_invoice:invoice.is_object(),invoice:if invoice.is_object(){Some(MailInvoice{seller:invoice["seller"]==true,
                    item_name:s(invoice,"item_name"),player_name:s(invoice,"player_name"),bid:n(invoice,"bid"),buyout:n(invoice,"buyout"),
                    deposit:n(invoice,"deposit"),consignment:n(invoice,"consignment")})}else{None},..Default::default()});
        }
        host.ui.set_mail(if mail["open"]==true{Some(MailState{inbox:entries})}else{None});
        host.ui.set_mail_stationeries(vec![StationeryView{id:1,name:"GG Mail".into(),icon:"Interface\\Icons\\INV_Letter_15".into(),cost:Some(30),texture:"Interface\\Stationery\\StationeryTest1".into()}]);
        host.ui.set_mail_packages(vec![]);host.ui.set_has_new_mail(n(mail,"unread")>0);
        if mail["open"]==true && old["mail"]["open"]!=true{
            host.ui.reset_compose_tab();host.ui.eval::<()>("SelectStationery(1)").map_err(|e|e.to_string())?;
        }
        if mail["open"]==true{host.ui.fire_event(if old["mail"]["open"]==true{"MAIL_INBOX_UPDATE"}else{"MAIL_SHOW"},vec![]);}
        else if old["mail"]["open"]==true{host.ui.fire_event("MAIL_CLOSED",vec![]);}
        if old["mail"]["unread"]!=mail["unread"]{host.ui.fire_event("UPDATE_PENDING_MAIL",vec![]);}
    }
    let auction=&v["auction"];
    if old["auction"]!=*auction{
        let mut state=AuctionState{deposit_percent:5,..Default::default()};
        for (i,list) in rows(auction,"lists",3)?.iter().enumerate(){
            let mut entries=Vec::new();
            for r in rows(list,"rows",50)?{
                let item=&r["attachment"];
                entries.push(AuctionItemRow{auction_id:n(r,"id"),item_id:n(item,"item_id"),name:opt(item,"name"),texture:opt(item,"icon"),
                    count:n(item,"quantity"),quality:Some(n(item,"quality")),level:n(item,"level").max(1),min_bid:n(r,"min_bid"),
                    min_increment:(n(r,"bid").max(n(r,"min_bid"))/20).max(1),buyout_price:n(r,"buyout"),bid_amount:n(r,"bid"),
                    high_bidder:match r["bidder"].as_str().unwrap_or(""){""=>AuctionHighBidder::Nil,"player"=>AuctionHighBidder::Player,name=>AuctionHighBidder::Name(name.into())},
                    owner:Some(s(r,"owner_name")),time_left:n(r,"time_left"),link:opt(item,"link"),..Default::default()});
            }
            state.lists[i]=AuctionListState{rows:entries,total:n(list,"total"),sort:serde_json::from_value(list["sort"].clone()).map_err(|e|e.to_string())?};
        }
        host.ui.set_auction(if auction["open"]==true{Some(state)}else{None});host.ui.set_auction_can_query(auction["open"]==true);
        host.ui.set_auction_item_classes(vec![AuctionCategory{class_id:2,name:"Weapons".into(),has_subclass_filter:false,subclasses:Vec::<AuctionSubCategory>::new()},
            AuctionCategory{class_id:4,name:"Armor".into(),has_subclass_filter:false,subclasses:vec![]},
            AuctionCategory{class_id:7,name:"Materials".into(),has_subclass_filter:false,subclasses:vec![]}]);
        if auction["open"]==true{
            if old["auction"]["open"]!=true{host.ui.fire_event("AUCTION_HOUSE_SHOW",vec![]);}
            for event in ["AUCTION_ITEM_LIST_UPDATE","AUCTION_OWNED_LIST_UPDATE","AUCTION_BIDDER_LIST_UPDATE"]{host.ui.fire_event(event,vec![]);}
        }else if old["auction"]["open"]==true{host.ui.clear_auction_sell_item();host.ui.fire_event("AUCTION_HOUSE_CLOSED",vec![]);}
    }
    let offer=&v["trade"];
    if old["trade"]!=*offer{
        if offer["shared_trade"]==true && offer["open"]==true && offer["target_profile"].is_object(){
            let mut partner=unit(&offer["target_profile"]);partner.is_player=true;
            host.ui.set_unit("npc",Some(partner));
            host.unit_guids.npc=offer["target_profile"]["guid"].as_u64().unwrap_or(0);
            host.ui.set_unit_guids(&host.unit_guids);
        }else if old["trade"]["shared_trade"]==true{
            host.ui.set_unit("npc",None);
        }
        let mut state=TradeState::default();state.player.gold=n(offer,"money");state.target.gold=n(offer,"target_money");
        for i in 1..=7{state.player.slots[i-1]=trade_item(&offer["player_rows"][i.to_string()]);}
        if let Some(items)=offer["target_rows"].as_array(){for (i,r) in items.iter().take(7).enumerate(){state.target.slots[i]=trade_item(r);}}
        host.ui.set_trade(if offer["open"]==true{Some(state)}else{None});
        if offer["open"]==true{
            if old["trade"]["open"]!=true{host.ui.fire_event("TRADE_SHOW",vec![]);}
            for i in 1..=7{host.ui.fire_event("TRADE_PLAYER_ITEM_CHANGED",vec![ScriptValue::Int(i)]);host.ui.fire_event("TRADE_TARGET_ITEM_CHANGED",vec![ScriptValue::Int(i)]);}
            host.ui.fire_event("TRADE_MONEY_CHANGED",vec![]);
            if offer["shared_trade"]==true && (old["trade"]["open"]!=true || old["trade"]["player_accepted"]!=offer["player_accepted"] || old["trade"]["target_accepted"]!=offer["target_accepted"]){
                host.ui.fire_event("TRADE_ACCEPT_UPDATE",vec![ScriptValue::Int(if offer["player_accepted"]==true{1}else{0}),ScriptValue::Int(if offer["target_accepted"]==true{1}else{0})]);
            }
        }else if old["trade"]["open"]==true{host.ui.fire_event("TRADE_CLOSED",vec![]);}
    }
    let group=&v["group"];
    if old["group"]!=*group{
        let roster=rows(group,"roster",40)?;let leader=s(group,"leader");let own_sub=n(&group["subgroups"],"player").max(1);
        let mut party=PartyState{own_guid:1,loot_method:s(group,"loot_method"),loot_threshold:n(group,"threshold"),..Default::default()};
        let mut members=Vec::new();
        for r in roster{
            if s(r,"id")==leader{party.leader_guid=r["guid"].as_u64().unwrap_or(0);}
            let subgroup=n(&group["subgroups"],&s(r,"id")).max(1);
            if s(r,"id")!="player" && (group["raid"]!=true || subgroup==own_sub){members.push(r);}
            if group["raid"]==true{party.raid.push(RaidMemberInfo{name:s(r,"name"),guid:r["guid"].as_u64().unwrap_or(0),
                rank:if s(r,"id")==leader{2}else if group["assistants"].as_array().is_some_and(|a|a.contains(&r["id"])){1}else{0},
                subgroup:subgroup-1,level:n(r,"level"),class:opt(r,"class_name"),class_file:opt(r,"class_file"),zone:if r["zone"].is_string(){opt(r,"zone")}else{Some("GG Island".into())},online:r["online"]==true,ninth:r["online"]==true&&n(r,"health")==0});}
        }
        for i in 0..4{
            host.ui.set_unit(&format!("party{}",i+1),members.get(i).map(|r|unit(r)));
            if let Some(r)=members.get(i){party.members.push(PartyMemberInfo{name:s(r,"name"),guid:r["guid"].as_u64().unwrap_or(0)});
                if s(r,"id")==leader{party.leader_index=i as u32+1;}
                if r["id"]==group["master"]{party.master_looter=Some(i as u32+1);}}
        }
        if group["master"]=="player"{party.master_looter=Some(0);}
        for i in 0..40{host.ui.set_unit(&format!("raid{}",i+1),if group["raid"]==true{roster.get(i).map(unit)}else{None});}
        host.ui.set_party(party);
        let ready=&group["ready_check"];
        if ready.is_object(){
            let remaining=if ready["finished"]==true{None}else{ready["remaining"].as_f64()};
            let unanswered=roster.iter().filter(|r|r["id"]!="player"&&group["ready"][s(r,"id")].as_bool().is_none())
                .map(|r|r["guid"].as_u64().unwrap_or(0)).collect();
            host.ui.restore_ready_check(remaining,unanswered);
        }else if old["group"]["ready_check"].is_object(){host.ui.restore_ready_check(None,vec![]);}
        if !ready.is_object() && old["group"]["ready"]!=group["ready"]{
            for r in roster{if let Some(ready)=group["ready"][s(r,"id")].as_bool(){
                host.ui.ready_check_answered(r["guid"].as_u64().unwrap_or(0),ready);
            }}
        }
        host.ui.fire_event("PARTY_MEMBERS_CHANGED",vec![]);host.ui.fire_event("RAID_ROSTER_UPDATE",vec![]);
    }
    let pet=&v["pet"];
    if old["pet"]!=*pet{
        let mut actions=Vec::new();
        if pet.is_object(){
            for word in rows(pet,"slots",10)?{
                let word=word.as_u64().unwrap_or(0) as u32;let kind=word>>24;let value=word&0xffffff;
                let token=match (kind,value){(7,2)=>"PET_ACTION_ATTACK",(7,1)=>"PET_ACTION_FOLLOW",(7,0)=>"PET_ACTION_STAY",
                    (6,2)=>"PET_MODE_AGGRESSIVE",(6,1)=>"PET_MODE_DEFENSIVE",(6,0)=>"PET_MODE_PASSIVE",_=>""};
                let strike=value==0x800101&&matches!(kind,1|128|192);
                actions.push(PetActionView{name:if strike{Some("Strike".into())}else if token.is_empty(){None}else{Some(token.into())},
                    texture:if strike{Some("Interface\\Icons\\Ability_Druid_FerociousBite".into())}else if token.is_empty(){None}else{Some(token.into())},is_token:!strike,
                    spell_id:if strike{Some(value)}else{None},autocast_allowed:strike,autocast_enabled:strike&&pet["autocast"]==true,
                    packed:if strike{value|((if pet["autocast"]==true{192}else{128})<<24)}else{word},active:(kind==7&&value==n(pet,"command"))||(kind==6&&value==n(pet,"reaction")),attack_active:kind==7&&value==2&&!s(pet,"target").is_empty(),..Default::default()});
            }
        }
        let exists=pet.is_object();let alive=exists&&n(pet,"health")>0;
        host.ui.set_pet_actions(exists,alive,alive,actions);host.ui.set_pet_menu(exists,exists&&pet["renamed"]!=true);
        host.ui.set_pet_stats(exists,PetStats{hunter_pet:exists,damage_percentage:100.,experience:(n(pet,"xp"),100),family:opt(pet,"species"),..Default::default()});
        host.ui.set_pet_expiry(None);host.ui.set_unit("pet",if exists{Some(unit(pet))}else{None});
        host.ui.set_pet_book(PetBookState{token:if exists{Some("PET".into())}else{None},slots:if exists{vec![SpellSlotView{spell_id:0x800101,name:"Strike".into(),
            texture:Some("Interface\\Icons\\Ability_Druid_FerociousBite".into()),autocast:Some((true,pet["autocast"]==true)),packed:0x800101|((if pet["autocast"]==true{192}else{128})<<24),..Default::default()}]}else{vec![]}});
        host.ui.fire_event("UNIT_PET",vec![ScriptValue::Str("player".into())]);host.ui.fire_event("PET_BAR_UPDATE",vec![]);host.ui.fire_event("PET_UI_UPDATE",vec![]);
    }
    let stable=&v["stable"];
    if old["stable"]!=*stable{
        let mut state=StableState{num_stable_slots:n(stable,"bought"),next_slot_cost:if n(stable,"bought")<2{n(stable,"price")}else{0},has_live_pet:n(stable,"active")>0,..Default::default()};
        let mut next=1;
        for r in rows(stable,"pets",3)?{
            let index=if n(r,"number")==n(stable,"current"){0}else{let i=next;next+=1;i};
            if index>=3{return Err("GG stable capacity".into());}
            state.slots[index]=Some(StablePetSlot{pet_number:n(r,"number"),name:s(r,"name"),level:n(r,"level"),family:opt(r,"species"),..Default::default()});
        }
        host.ui.set_stable(if stable["open"]==true{Some(state)}else{None});
        if stable["open"]==true{host.ui.fire_event(if old["stable"]["open"]==true{"PET_STABLE_UPDATE"}else{"PET_STABLE_SHOW"},vec![]);}
        else if old["stable"]["open"]==true{host.ui.fire_event("PET_STABLE_CLOSED",vec![]);}
    }
    if old["text"]!=v["text"]{
        let t=&v["text"];
        host.ui.set_item_text(if t.is_object(){Some(ItemTextState{item:s(t,"item"),creator:opt(t,"creator"),text:s(t,"text"),page:1,has_next:false,..Default::default()})}else{None});
        if t.is_object(){host.ui.fire_event("ITEM_TEXT_BEGIN",vec![]);host.ui.fire_event("ITEM_TEXT_READY",vec![]);}
        else{host.ui.fire_event("ITEM_TEXT_CLOSED",vec![]);}
    }
    host.views.insert("services".into(),v.clone());Ok(())
}

pub fn requests(ui:&mut UiScript)->Value{
    let mut out=Vec::<Value>::new();
    if ui.take_item_text_close(){out.push(json!({"op":"ItemTextClose"}));}
    for delta in ui.take_item_text_page_turns(){out.push(json!({"op":"ItemTextPage","delta":delta}));}
    if ui.take_mail_check_inbox(){out.push(json!({"op":"MailCheck"}));}
    for (op,indices) in [("MailRead",ui.take_mail_opens()),("MailItem",ui.take_mail_take_items()),("MailMoney",ui.take_mail_take_money()),
        ("MailDelete",ui.take_mail_deletes()),("MailReturn",ui.take_mail_returns()),("MailText",ui.take_mail_take_texts())]{for index in indices{out.push(json!({"op":op,"index":index}));}}
    if let Some(r)=ui.take_mail_send(){out.push(json!({"op":"MailSend","target":r.target,"subject":r.subject,"body":r.body,"money":r.money,"cod":r.cod,"source":r.item}));}
    if ui.take_mail_close(){out.push(json!({"op":"MailClose"}));}
    if let Some(r)=ui.take_auction_query(){out.push(json!({"op":"AuctionQuery","query":{"name":r.name,"min_level":r.min_level,"max_level":r.max_level,"inv_type":r.inv_type,
        "class":r.class,"sub_class":r.sub_class,"quality":r.quality,"page":r.page,"usable_only":r.usable_only}}));}
    if let Some(page)=ui.take_auction_owner_query(){out.push(json!({"op":"AuctionPage","list":2,"page":page}));}
    if let Some(page)=ui.take_auction_bidder_query(){out.push(json!({"op":"AuctionPage","list":1,"page":page}));}
    for (list,key) in ui.take_auction_sorts(){out.push(json!({"op":"AuctionSort","list":list,"key":key}));}
    for r in ui.take_auction_bids(){out.push(json!({"op":"AuctionBid","list":r.list,"index":r.index,"amount":r.amount}));}
    for index in ui.take_auction_cancels(){out.push(json!({"op":"AuctionCancel","index":index}));}
    if let Some(r)=ui.take_auction_start(){out.push(json!({"op":"AuctionStart","min_bid":r.min_bid,"buyout":r.buyout,"duration":r.duration,"source":ui.auction_sell_item()}));}
    if ui.take_auction_close(){out.push(json!({"op":"AuctionClose"}));}
    for target in ui.take_trade_initiates(){out.push(json!({"op":"TradeOpen","target":target}));}
    let sets=ui.take_trade_set_items();let clears=ui.take_trade_clear_items();let money=ui.take_trade_money();
    let enchants=ui.take_trade_enchant_picks();
    let changed=!sets.is_empty()||!clears.is_empty()||money.is_some()||!enchants.is_empty();
    for (slot,bag,index) in sets{out.push(json!({"op":"TradeSet","slot":slot,"source":[bag,index]}));}
    for slot in clears{out.push(json!({"op":"TradeClear","slot":slot}));}
    for slot in enchants{out.push(json!({"op":"TradeEnchantPick","slot":slot}));}
    if let Some(money)=money{out.push(json!({"op":"TradeMoney","money":money}));}
    if ui.take_trade_begin(){out.push(json!({"op":"TradeBegin"}));}
    if ui.take_trade_unaccept(){out.push(json!({"op":"TradeUnaccept"}));}
    // Coalesced original setters cannot prove the accept's position in the
    // same drain. Require another explicit confirmation after edits.
    if ui.take_trade_accept(){out.push(json!({"op":if changed{"TradeConfirmChanged"}else{"TradeAccept"}}));}
    if ui.take_trade_cancel(){out.push(json!({"op":"TradeCancel"}));}
    if ui.take_trade_close(){out.push(json!({"op":"TradeClose"}));}
    for r in ui.take_party_requests(){out.push(match r{
        PartyRequest::Accept=>json!({"op":"GroupAccept"}),PartyRequest::Decline=>json!({"op":"GroupDecline"}),PartyRequest::Leave=>json!({"op":"GroupLeave"}),
        PartyRequest::InviteName(target)|PartyRequest::InviteUnit(target)=>json!({"op":"GroupInvite","target":target}),
        PartyRequest::UninviteUnit(target)=>json!({"op":"GroupKick","target":target}),
        PartyRequest::PromoteUnit(target)|PartyRequest::PromoteName(target)=>json!({"op":"GroupLeader","target":target}),
        PartyRequest::LootMethod{method,master_name,threshold}=>json!({"op":"GroupLoot","method":method,"master":master_name,"threshold":threshold}),
        PartyRequest::LootThreshold(threshold)=>json!({"op":"GroupThreshold","threshold":threshold}),
        PartyRequest::SetRaidTarget{unit,index}=>json!({"op":"GroupMark","target":unit,"index":index}),
        PartyRequest::ConvertToRaid=>json!({"op":"GroupRaid"}),PartyRequest::SetSubgroup{index,group}=>json!({"op":"GroupSubgroup","index":index,"subgroup":group}),
        PartyRequest::SwapSubgroup{index,other}=>json!({"op":"GroupSwap","index":index,"other":other}),
        PartyRequest::AssistantLeader{name,grant}=>json!({"op":"GroupAssistant","target":name,"grant":grant}),
        PartyRequest::UninviteRaid(index)=>json!({"op":"GroupKickRaid","index":index}),PartyRequest::ReadyCheckStart=>json!({"op":"GroupReady"}),
        PartyRequest::ReadyCheckAnswer(ready)=>json!({"op":"GroupReadyAnswer","ready":ready}),PartyRequest::RequestRaidInfo=>json!({"op":"GroupRaidInfo"})});}
    // Ready-check timeout lines are real local system chat, not an ignored queue.
    for text in ui.take_ready_check_lines(){out.push(json!({"op":"GroupReadyLine","text":text}));}
    for slot in ui.take_pet_autocast_toggles(){out.push(json!({"op":"PetAutocast","slot":slot}));}
    if ui.take_pet_stop_attacks()>0{out.push(json!({"op":"PetStop"}));}
    for slots in ui.take_pet_set_actions(){out.push(json!({"op":"PetSlots","slots":slots}));}
    let (abandon,dismiss)=ui.take_pet_gives_up();
    if abandon>0{out.push(json!({"op":"PetAbandon"}));}if dismiss>0{out.push(json!({"op":"PetDismiss"}));}
    for name in ui.take_pet_renames(){out.push(json!({"op":"PetRename","name":name}));}
    for spell_id in ui.take_pet_spell_autocasts(){out.push(json!({"op":"PetAutocast","spell_id":spell_id}));}
    for r in ui.take_stable_intents(){out.push(match r{StableIntent::Stable=>json!({"op":"StableStore"}),StableIntent::Unstable(number)=>json!({"op":"StableTake","number":number}),
        StableIntent::Swap(number)=>json!({"op":"StableSwap","number":number}),StableIntent::BuySlot=>json!({"op":"StableBuy"})});}
    if ui.take_stable_close(){out.push(json!({"op":"StableClose"}));}
    json!({"services":out})
}
