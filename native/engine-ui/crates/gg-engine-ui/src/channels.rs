//! Confirmed local channel slots and the original channel management intents.
use engine_ui_core::script::{UiScript,ChannelCommand,ZoneChannelRow};
use serde_json::{Value,json};

pub(super) fn feed(ui:&mut UiScript,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let slots:Vec<Option<String>>=serde_json::from_value(v["slots"].clone()).map_err(|_|"invalid channel slots")?;
    if slots.len()!=10||slots.iter().flatten().any(|s|s.len()>320){return Err("channel slot capacity".into());}
    ui.set_joined_channels(slots);
    ui.set_zone_channel_catalog(["General","Trade","LocalDefense","LookingForGroup","GuildRecruitment"].iter().enumerate().map(|(i,s)|ZoneChannelRow{id:i as u32+1,shortcut:(*s).into(),resolved:Some(format!("{} - GG Island",s)),listed:true}).collect());
    ui.set_guild_recruitment_mode(v["recruitment"].as_u64().filter(|n|*n<=1).ok_or("invalid recruitment mode")? as u8);
    Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    let mut rows=Vec::new();
    for request in ui.take_channel_commands(){rows.push(match request{
        ChannelCommand::Join{name,password}=>json!({"op":"ChannelJoin","name":name,"password":password}),
        ChannelCommand::Leave{name}=>json!({"op":"ChannelLeave","name":name}),ChannelCommand::List{name}=>json!({"op":"ChannelList","name":name}),
        ChannelCommand::ListAll=>json!({"op":"ChannelListAll"}),ChannelCommand::DisplayOwner{name}=>json!({"op":"ChannelDisplayOwner","name":name}),
        ChannelCommand::SetOwner{name,player}=>json!({"op":"ChannelSetOwner","name":name,"player":player}),
        ChannelCommand::SetPassword{name,password}=>json!({"op":"ChannelSetPassword","name":name,"password":password}),
        ChannelCommand::Ban{name,player}=>json!({"op":"ChannelBan","name":name,"player":player}),
        ChannelCommand::Invite{name,player}=>json!({"op":"ChannelInvite","name":name,"player":player}),
        ChannelCommand::Kick{name,player}=>json!({"op":"ChannelKick","name":name,"player":player}),
        ChannelCommand::Moderator{name,player}=>json!({"op":"ChannelModerator","name":name,"player":player}),
        ChannelCommand::Unmoderator{name,player}=>json!({"op":"ChannelUnmoderator","name":name,"player":player}),
        ChannelCommand::Mute{name,player}=>json!({"op":"ChannelMute","name":name,"player":player}),
        ChannelCommand::Unmute{name,player}=>json!({"op":"ChannelUnmute","name":name,"player":player}),
        ChannelCommand::Unban{name,player}=>json!({"op":"ChannelUnban","name":name,"player":player}),
        ChannelCommand::Moderate{name}=>json!({"op":"ChannelModerate","name":name}),
        ChannelCommand::ToggleAnnouncements{name}=>json!({"op":"ChannelToggleAnnouncements","name":name})});}
    let changed=ui.take_guild_recruitment_change();let cascade=ui.take_guild_recruitment_cascade();
    if changed||cascade{rows.push(json!({"op":"ChannelRecruitment","value":ui.guild_recruitment_mode()}));}
    rows
}
