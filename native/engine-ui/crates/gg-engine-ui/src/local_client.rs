//! Original local client queues, independent of a remote realm.
use engine_ui_core::script::{UiScript,SocialRequest,SocialState,FriendInfo,WhoInfo,WhoSortChain,ReputationSend,ReputationState,FactionEntry};
use serde_json::{Value,json};

#[derive(Default)]
struct TutorialOrder {rows:Vec<Value>,overflow:bool}
pub fn install(ui:&mut UiScript)->Result<(),String>{
    let lua=ui.lua();lua.set_app_data(TutorialOrder::default());lua.set_app_data(WhoSortChain::default());
    for (name,op) in [("FlagTutorial","TutorialFlag"),("ClearTutorials","TutorialClear"),("ResetTutorials","TutorialReset")]{
        let original:mlua::Function=lua.globals().get(name).map_err(|e|e.to_string())?;
        let key=lua.create_registry_value(original).map_err(|e|e.to_string())?;
        lua.globals().set(name,lua.create_function(move|lua,args:mlua::MultiValue|{
            let original:mlua::Function=lua.registry_value(&key)?;
            let index=if op=="TutorialFlag"{args.front().cloned().and_then(|v|lua.coerce_number(v).ok().flatten()).filter(|n|n.is_finite()&&(1.0..51.0).contains(n)).map(|n|n as i32-1)}else{None};
            let result=original.call::<mlua::MultiValue>(args)?;
            if op!="TutorialFlag"||index.is_some(){
                let mut order=lua.app_data_mut::<TutorialOrder>().expect("GG tutorial order");
                if order.rows.len()<128{order.rows.push(if let Some(index)=index{json!({"op":op,"index":index})}else{json!({"op":op})});}else{order.overflow=true;}
            }
            Ok(result)
        }).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    }Ok(())
}

pub fn feed(ui:&mut UiScript,row:&Value)->Result<(),String>{
    let Some(row)=row.as_object() else{return Ok(());};
    let row=Value::Object(row.clone());
    let bank:Vec<u8>=serde_json::from_value(row["tutorials"].clone()).map_err(|_|"invalid local tutorial bank")?;
    if bank.len()!=32{return Err("invalid tutorial bank length".into());}
    ui.set_tutorial_bank(Some(bank));ui.set_action_bar_toggles(row["action_bars"].as_u64().filter(|&v|v<=255).ok_or("invalid action bars")? as u8);
    let mut state=SocialState::default();
    let who=row["who"].as_array().ok_or("local Who required")?;
    if who.len()>50{return Err("local Who capacity".into());}
    for item in who{
        let name=item["name"].as_str().ok_or("local Who name")?;
        if name.len()>192{return Err("local Who name capacity".into());}
        state.who.push(WhoInfo{name:name.into(),guild:item["guild"].as_str().unwrap_or("").into(),level:item["level"].as_u64().unwrap_or(1) as u32,
            race:item["race"].as_str().unwrap_or("GG").into(),class:item["class_name"].as_str().unwrap_or("").into(),zone:item["zone"].as_str().unwrap_or("").into()});
    }
    state.who_total=row["who_total"].as_u64().unwrap_or(state.who.len() as u64).min(10000) as u32;
    state.who_sort=ui.lua().app_data_ref::<WhoSortChain>().expect("GG Who sort").clone();state.who_sort.sort(&mut state.who);
    let friends=row["friend_people"].as_array().filter(|p|p.len()<=50).ok_or("local friend people capacity")?;
    for name in row["friends"].as_array().ok_or("local friends required")?{
        let name=name.as_str().ok_or("local friend name")?;
        let person=friends.iter().find(|v|v["name"].as_str().is_some_and(|n|n.eq_ignore_ascii_case(name)));
        state.friends.push(FriendInfo{name:name.into(),level:person.and_then(|v|v["level"].as_u64()).unwrap_or(0) as u32,class:person.and_then(|v|v["class_name"].as_str()).unwrap_or("").into(),
            area:person.and_then(|v|v["zone"].as_str()).unwrap_or("").into(),connected:person.is_some(),status:String::new()});
    }
    state.ignores=serde_json::from_value(row["ignores"].clone()).map_err(|_|"invalid ignores")?;
    if state.friends.len()>50||state.ignores.len()>50{return Err("local social capacity".into());}
    state.selected_friend=row["selected_friend"].as_u64().unwrap_or(0) as u32;state.selected_ignore=row["selected_ignore"].as_u64().unwrap_or(0) as u32;
    ui.set_social(state);
    let mut reputation=ReputationState::default();
    let factions=row["factions"].as_array().ok_or("local factions required")?;
    if factions.len()>8{return Err("local faction capacity".into());}
    for (i,item) in factions.iter().enumerate(){
        let standing=item["standing"].as_i64().unwrap_or(0).clamp(-100000,100000) as i32;
        let flags=&row["faction_flags"][i.to_string()];
        reputation.entries.push(FactionEntry{faction_id:i as u32+1,rep_list_id:i as u32,parent_id:0,
            name:item["name"].as_str().unwrap_or("").into(),description:item["description"].as_str().unwrap_or("").into(),standing,
            standing_id:if standing<=-50{2}else if standing>=50{5}else{4},bar_min:-100000,bar_max:100000,
            visible:true,is_header:false,at_war:flags["at_war"].as_bool().unwrap_or(false),can_toggle_at_war:true,inactive:flags["inactive"].as_bool().unwrap_or(false)});
    }
    reputation.watched=row["watched"].as_u64().filter(|&v|v<factions.len() as u64).map(|v|v as u32);
    ui.set_reputation(reputation);Ok(())
}

pub fn requests(ui:&mut UiScript)->Value{
    let mut rows=Vec::<Value>::new();
    // Core queues remain unmodified, but independent counters cannot recover
    // Reset/Flag ordering. Wrappers retain the successful original call order.
    ui.take_tutorial_flag_requests();ui.take_tutorial_clears();ui.take_tutorial_resets();
    let mut order=ui.lua().app_data_mut::<TutorialOrder>().expect("GG tutorial order");
    let overflow=std::mem::take(&mut order.overflow);let ordered=std::mem::take(&mut order.rows);drop(order);
    if overflow{rows.push(json!({"op":"TutorialOverflow"}));}else{rows.extend(ordered);}
    for value in ui.take_action_bar_toggle_sends(){rows.push(json!({"op":"ActionBars","value":value}));}
    if ui.take_pvp_toggles()%2==1{rows.push(json!({"op":"Pvp"}));}
    if ui.take_played_time_asks()>0{rows.push(json!({"op":"Played"}));}
    for (low,high) in ui.take_roll_requests(){rows.push(json!({"op":"Roll","low":low,"high":high}));}
    for v in ui.take_chat_sends(){rows.push(json!({"op":"Chat","text":v.text,"chat_type":v.chat_type,"target":v.target,"language":v.language}));}
    for v in ui.take_addon_sends(){let (prefix,message)=v.text.split_once('\t').unwrap_or(("",v.text.as_str()));rows.push(json!({"op":"Addon","prefix":prefix,"message":message,"distribution":v.distribution.token()}));}
    for v in ui.take_social_requests(){
        if let SocialRequest::SortWho(ref key)=v{ui.lua().app_data_mut::<WhoSortChain>().expect("GG Who sort").promote(key);continue;}
        let row=match v{
        SocialRequest::RefreshFriends=>json!({"action":"RefreshFriends"}),SocialRequest::AddFriend(name)=>json!({"action":"AddFriend","name":name}),
        SocialRequest::RemoveFriendIndex(index)=>json!({"action":"RemoveFriendIndex","index":index}),SocialRequest::RemoveFriendName(name)=>json!({"action":"RemoveFriendName","name":name}),
        SocialRequest::AddIgnore(name)=>json!({"action":"AddIgnore","name":name}),SocialRequest::DelIgnore(name)=>json!({"action":"DelIgnore","name":name}),
        SocialRequest::ToggleIgnore(name)=>json!({"action":"ToggleIgnore","name":name}),SocialRequest::SelectFriend(index)=>json!({"action":"SelectFriend","index":index}),
        SocialRequest::SelectIgnore(index)=>json!({"action":"SelectIgnore","index":index}),SocialRequest::Who(query)=>json!({"action":"Who","query":query}),
        SocialRequest::SortWho(key)=>json!({"action":"SortWho","key":key}),SocialRequest::SetWhoToUi(value)=>json!({"action":"SetWhoToUi","value":value}),
        SocialRequest::SetLookingForGroup{slots,comment}=>json!({"action":"LookingForGroup","slots":slots,"comment":comment})};
        let mut row=row;row["op"]=json!("Social");rows.push(row);
    }
    for v in ui.take_reputation_sends(){let row=match v{
        ReputationSend::AtWar{rep_list_id,at_war}=>json!({"action":"AtWar","index":rep_list_id,"value":at_war}),
        ReputationSend::Inactive{rep_list_id,inactive}=>json!({"action":"Inactive","index":rep_list_id,"value":inactive}),
        ReputationSend::Watch(index)=>json!({"action":"Watch","index":index})};let mut row=row;row["op"]=json!("Reputation");rows.push(row);
    }
    if let Some((x,y))=ui.take_minimap_ping_request(){rows.push(json!({"op":"MinimapPing","position":[x,y]}));}
    json!({"local_client":rows})
}
