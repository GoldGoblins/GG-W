//! The install engine's resolver finds, or every place it looked; exits 1 when there is none.
//! `scripts/gates.sh` asks this rather than repeating the rule.
//! `cargo run -p engine-formats-core --example where`

fn main() -> std::process::ExitCode {
    match engine_formats_core::wow_data() {
        Some(data) => {
            println!("{}", data.display());
            std::process::ExitCode::SUCCESS
        }
        None => {
            eprintln!("no WoW install found. Looked in, in order:");
            for c in engine_formats_core::candidates() {
                eprintln!("  {}", c.display());
            }
            eprintln!("Set $WOW_DATA, or put a WoW folder beside the binary.");
            std::process::ExitCode::FAILURE
        }
    }
}
