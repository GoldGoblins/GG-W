//! GG host feeds over the unchanged original gossip and quest model.
use crate::{number,string,Host};
use engine_ui_core::script::{GossipMenu,GossipOptionView,GossipQuestRow,QuestPanel,QuestState,QuestItemView,QuestLogState,QuestLogEntryView,QuestLogObjectiveView,QuestLogDetail};
use serde_json::Value;
use engine_ui_core::script::{UiScript,QuestAction};

fn uint(v:&Value,key:&str,default:u32)->Result<u32,String>{
    if v[key].is_null(){return Ok(default)}
    v[key].as_u64().and_then(|n|n.try_into().ok()).ok_or_else(||format!("invalid GG quest {key}"))
}
fn text(v:&Value,key:&str,limit:usize)->Result<String,String>{
    let value=v[key].as_str().unwrap_or("");
    if value.len()>limit{return Err("GG quest text capacity exceeded".into())}Ok(value.into())
}
fn rows<'a>(v:&'a Value,key:&str,limit:usize)->Result<&'a [Value],String>{
    let rows=v[key].as_array().map(Vec::as_slice).unwrap_or(&[]);
    if rows.len()>limit{return Err("GG quest row capacity exceeded".into())}Ok(rows)
}
fn item(v:&Value)->Result<QuestItemView,String>{
    Ok(QuestItemView{name:Some(text(v,"name",512)?),texture:v["texture"].as_str().map(str::to_owned),
        count:uint(v,"count",1)?,quality:uint(v,"quality",1)?.min(6),item_id:uint(v,"item_id",0)?,
        usable:v["usable"]==true,link:v["link"].as_str().map(str::to_owned)})
}
pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    let list=&v["quests"];
    if list.is_array() && host.views.get("quests")!=Some(list){
        let selected=host.ui.quest_log_selection().checked_sub(1)
            .and_then(|i|host.views.get("quests")?.as_array()?.get(i as usize)?.get("quest_id"))
            .and_then(Value::as_u64);
        let mut log=QuestLogState::default();
        for quest in rows(v,"quests",20)?{
            let cur=uint(quest,"current",0)?;let req=uint(quest,"required",1)?;
            log.entries.push(QuestLogEntryView{quest_id:uint(quest,"quest_id",0)?,title:string(quest,"title")?.into(),
                level:number(quest,"level",0.)?.max(0.) as u32,pushable:quest["pushable"]==true,complete:if quest["complete"]==true{1}else{0},
                objectives:vec![QuestLogObjectiveView{text:format!("{}: {cur}/{req}",quest["objective"].as_str().filter(|s|!s.is_empty()).unwrap_or(string(quest,"title")?)),
                    kind:quest["kind"].as_str().unwrap_or("object").into(),finished:cur>=req,cur,req}],
                detail:Some(QuestLogDetail{description:text(quest,"description",16384)?,objectives_text:text(quest,"objective",4096)?,
                    reward_money:uint(quest,"reward_copper",0)?,..Default::default()}),..Default::default()});
        }
        let selection=selected.and_then(|id|log.entries.iter().position(|row|u64::from(row.quest_id)==id)).map(|i|i as u32+1).unwrap_or(0);
        log.num_quests=log.entries.len() as u32;host.ui.set_quest_log(log);host.ui.set_quest_log_selection(selection);
        host.views.insert("quests".into(),list.clone());host.ui.fire_event("QUEST_LOG_UPDATE",vec![]);
    }
    for kind in ["gossip","quest_dialog"]{
        let state=&v[kind];if !state.is_object() || host.views.get(kind)==Some(state){continue}
        let opened=state["open"]==true;let was_open=host.views.get(kind).is_some_and(|old|old["open"]==true);
        let event;
        if kind=="gossip"{
            let menu=if opened{
                Some(GossipMenu{greeting:text(state,"greeting",16384)?,
                    quests:rows(state,"quests",32)?.iter().map(|row|Ok(GossipQuestRow{title:text(row,"title",1024)?,level:uint(row,"level",1)?,active:row["active"]==true})).collect::<Result<_,String>>()?,
                    options:rows(state,"options",32)?.iter().map(|row|Ok(GossipOptionView{label:text(row,"label",2048)?,icon_type:text(row,"icon_type",32)?})).collect::<Result<_,String>>()?})
            }else{None};
            host.ui.set_gossip(menu);event=if opened{"GOSSIP_SHOW"}else{"GOSSIP_CLOSED"};
        }else{
            let (panel,panel_event)=match state["panel"].as_str(){
                Some("DETAIL")=>(QuestPanel::Detail,"QUEST_DETAIL"),Some("PROGRESS")=>(QuestPanel::Progress,"QUEST_PROGRESS"),
                Some("REWARD")=>(QuestPanel::Reward,"QUEST_COMPLETE"),_ if !opened=>(QuestPanel::Detail,"QUEST_FINISHED"),
                _=>return Err("invalid GG quest panel".into())};
            host.ui.set_quest(if opened{Some(QuestState{panel,title:text(state,"title",1024)?,body:text(state,"body",16384)?,
                objectives:text(state,"objectives",4096)?,reward_money:uint(state,"reward_money",0)?,completable:state["completable"]==true,
                rewards:rows(state,"rewards",16)?.iter().map(item).collect::<Result<_,_>>()?,..Default::default()})}else{None});
            event=if opened{panel_event}else{"QUEST_FINISHED"};
        }
        host.views.insert(kind.into(),state.clone());
        if opened||was_open{host.ui.fire_event(event,vec![])}
    }
    Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Value{
    let actions:Vec<_>=ui.take_quest_actions().into_iter().map(|action|match action{
        QuestAction::Accept=>serde_json::json!({"op":"ACCEPT"}),QuestAction::Continue=>serde_json::json!({"op":"CONTINUE"}),
        QuestAction::Reward(choice)=>serde_json::json!({"op":"REWARD","choice":choice}),
        QuestAction::Decline=>serde_json::json!({"op":"DECLINE"}),QuestAction::Close=>serde_json::json!({"op":"CLOSE"})}).collect();
    let selects:Vec<_>=ui.take_quest_selects().into_iter().map(|row|serde_json::json!({"active":row.active,"index":row.index})).collect();
    serde_json::json!({"gossip_selects":ui.take_gossip_selects(),"gossip_quests":ui.take_gossip_quest_selects(),"gossip_close":ui.take_gossip_close(),
        "quest_selects":selects,"quest_actions":actions,"quest_abandons":ui.take_quest_log_abandons(),"quest_shares":ui.take_quest_log_pushes(),
        "quest_confirms":ui.take_quest_confirms(),"quest_collapses":ui.take_quest_log_collapses()})
}
