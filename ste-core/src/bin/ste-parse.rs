//! ste-parse <save.ess> <tables folder> [out.json]
//! Reads a save and writes its tracker.json (next to the save by default).

use std::path::Path;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: ste-parse <save.ess> <tables folder> [out.json]");
        std::process::exit(1);
    }
    let save = Path::new(&args[1]);
    let dir = Path::new(&args[2]);
    let mut tables = ste_core::Tables::new();
    for name in ste_core::CSV_ORDER {
        match std::fs::read(dir.join(name)) {
            Ok(b) => {
                tables.insert(name.to_string(), b);
            }
            Err(e) => {
                eprintln!("{}: {e}", dir.join(name).display());
                std::process::exit(1);
            }
        }
    }
    let raw = match std::fs::read(save) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("{}: {e}", save.display());
            std::process::exit(1);
        }
    };
    let file_name = save.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let t0 = std::time::Instant::now();
    match ste_core::parse_save(&raw, &file_name, &tables, &mut |_| {}) {
        Ok(json) => {
            let out = args.get(3).map(std::path::PathBuf::from).unwrap_or_else(|| save.with_extension("tracker.json"));
            std::fs::write(&out, json).expect("cannot write tracker.json");
            println!("Done: {} ({} ms)", out.display(), t0.elapsed().as_millis());
        }
        Err(e) => {
            eprintln!("Parse failed at {e}");
            std::process::exit(2);
        }
    }
}
