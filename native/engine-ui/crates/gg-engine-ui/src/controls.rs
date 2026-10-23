//! Original UiScript intent streams; GG handles the rig on its fixed-step host.
use engine_ui_core::script::{UiScript,CameraViewRequest,BindingInput,FiredInput,FollowRequest};
use serde_json::{Value,json};

pub fn install(ui:&mut UiScript){
    ui.register_cvars([("cameraView","1"),("cameraDistance","0.0"),("cameraPitch","0.0"),("cameraYaw","0.0"),
        ("cameraDistanceA","5.55"),("cameraPitchA","10.0"),("cameraYawA","0.0"),
        ("cameraDistanceB","5.55"),("cameraPitchB","20.0"),("cameraYawB","0.0"),
        ("cameraDistanceC","13.88"),("cameraPitchC","30.0"),("cameraYawC","0.0"),
        ("cameraDistanceD","13.88"),("cameraPitchD","10.0"),("cameraYawD","0.0")]);
}

pub fn publish(ui:&mut UiScript,row:&Value)->Result<(),String>{
    if row.is_null() || row.as_object().is_some_and(|o|o.is_empty()){return Ok(());}
    let views=row["views"].as_array().filter(|v|v.len()==5).ok_or("camera requires five views")?;
    let index=row["current"].as_u64().filter(|&i|i<5).ok_or("invalid current camera view")?;
    let mut poses=Vec::new();
    for view in views{
        let view=view.as_array().filter(|v|v.len()==3).ok_or("invalid camera pose")?;
        let mut pose=[0.;3];for (out,v) in pose.iter_mut().zip(view){*out=v.as_f64().filter(|v|v.is_finite()&&v.abs()<=1e9).ok_or("invalid camera value")?;}poses.push(pose);
    }
    let display=&row["display"];
    let helm=display["helm"].as_bool().ok_or("invalid helm visibility")?;
    let cloak=display["cloak"].as_bool().ok_or("invalid cloak visibility")?;
    ui.set_worn_display(helm,cloak);
    ui.set_cvar_host("cameraView",&index.to_string());
    for (suffix,pose) in ["","A","B","C","D"].iter().zip(poses){
        for (key,value) in [("Distance",pose[0]),("Pitch",-pose[1]),("Yaw",pose[2])]{ui.set_cvar_host(&format!("camera{key}{suffix}"),&format!("{value:.6}"));}
    }
    Ok(())
}

pub fn requests(ui:&mut UiScript)->Value{
    let cameras:Vec<Value>=ui.take_camera_view_requests().into_iter().map(|v|match v{
        CameraViewRequest::Set(i)=>json!({"op":"Set","index":i}),CameraViewRequest::Save(i)=>json!({"op":"Save","index":i}),
        CameraViewRequest::Reset(i)=>json!({"op":"Reset","index":i}),CameraViewRequest::Next=>json!({"op":"Next"}),
        CameraViewRequest::Prev=>json!({"op":"Prev"}),CameraViewRequest::FlipYaw(n)=>json!({"op":"FlipYaw","value":n}),
    }).collect();
    let mut inputs:Vec<Value>=ui.take_binding_input().into_iter().map(|v|match v{
        BindingInput::Start(key)=>json!({"op":"Start","key":format!("{key:?}")}),
        BindingInput::Stop(key)=>json!({"op":"Stop","key":format!("{key:?}")}),
        BindingInput::Fire(FiredInput::CameraZoomIn(n))=>json!({"op":"Fire","key":"CameraZoomIn","value":n}),
        BindingInput::Fire(FiredInput::CameraZoomOut(n))=>json!({"op":"Fire","key":"CameraZoomOut","value":n}),
        BindingInput::Fire(key)=>json!({"op":"Fire","key":format!("{key:?}")}),
    }).collect();
    for held in ui.take_mouselook_calls(){inputs.push(json!({"op":if held{"Start"}else{"Stop"},"key":"TurnOrAction"}));}
    let worn:Vec<String>=ui.take_worn_display_toggles().into_iter().map(|v|format!("{v:?}")).collect();
    let follow:Vec<Value>=ui.take_follow_requests().into_iter().map(|v|match v{
        FollowRequest::ByUnit(unit)=>json!({"op":"Follow","unit":unit}),
        FollowRequest::ByName{name,exact}=>json!({"op":"FollowByName","name":name,"exact":exact})}).collect();
    let emotes:Vec<Value>=ui.take_emote_requests().into_iter().map(|v|json!({"token":v.token,"target":v.target})).collect();
    json!({"camera_views":cameras,"binding_input":inputs,"worn_display":worn,"follows":follow,"emotes":emotes})
}
