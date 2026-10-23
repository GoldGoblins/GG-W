//! All inventoried original queues now have explicit GG bridge consumers.
//! Behavioral equivalence is evaluated separately from this empty reject lane.
use engine_ui_core::script::UiScript;
use serde_json::Value;
pub fn requests(_ui:&mut UiScript)->Vec<Value>{
    Vec::new()
}
