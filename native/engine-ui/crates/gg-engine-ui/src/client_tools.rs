//! Original local client requests. GG performs the actual disk/UI operations.
use engine_ui_core::{script::{UiScript,GmTicketIntent},status::LogWrite};
use serde_json::{Value,json};

pub(super) fn feed(ui:&mut UiScript){
    ui.set_gm_ticket_categories(vec![(1,"Local issue note (no remote GM)".into())]);
}

pub(super) fn requests(ui:&mut UiScript)->Value{
    let mut services=Vec::new();
    for intent in ui.take_gm_ticket_intents(){services.push(match intent{
        GmTicketIntent::Ask=>json!({"op":"SupportAsk"}),GmTicketIntent::AskStatus=>json!({"op":"SupportStatus"}),
        GmTicketIntent::Delete=>json!({"op":"SupportDelete"}),
        GmTicketIntent::Write(w)=>json!({"op":"SupportWrite","category":w.category,"text":w.text,"new":w.is_new})
    });}
    let logging=if ui.take_logging_changes(){let (chat,combat)=ui.logging_flags();json!({"chat":chat,"combat":combat})}else{Value::Null};
    let logs:Vec<Value>=ui.take_load_log_writes().into_iter().map(|w|match w{
        LogWrite::Rewrite(lines)=>json!({"rewrite":true,"lines":lines}),LogWrite::Append(lines)=>json!({"rewrite":false,"lines":lines})
    }).collect();
    json!({"services":services,"client_tools":{"console":ui.take_console_lines(),"logging":logging,"load_logs":logs,"screenshots":ui.take_screenshot_asks(),"graphics_restarts":ui.take_restart_gx_asks()}})
}
