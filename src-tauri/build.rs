// Build script: prepares the page (comments removed) with its fonts and pictures
// in gen-web, which gets built into the exe, and shim.js without comments;
// then runs the usual Tauri build.
#[path = "build_support/strip.rs"]
mod strip;

use std::path::Path;

const PAGE: &str = "../web/Skyrim_Tracker_v15.html";
const SHIM: &str = "src/shim.js";
const ASSET_DIRS: [&str; 2] = ["fonts", "bg"];

/// writes only if the content changed
fn write_if_changed(path: &Path, data: &[u8]) {
    if std::fs::read(path).ok().as_deref() != Some(data) {
        std::fs::write(path, data).unwrap_or_else(|e| panic!("cannot write {}: {e}", path.display()));
    }
}

fn main() {
    println!("cargo:rerun-if-changed={PAGE}");
    println!("cargo:rerun-if-changed=build_support/strip.rs");
    let html = std::fs::read_to_string(PAGE).expect("tracker page not found");
    let clean = strip::strip_html(&html).unwrap_or_else(|e| panic!("cannot strip comments from the page: {e}"));
    std::fs::create_dir_all("gen-web").unwrap();
    write_if_changed(Path::new("gen-web/index.html"), clean.as_bytes());

    // shim.js goes into the exe through main.rs, also without comments
    println!("cargo:rerun-if-changed={SHIM}");
    let shim = std::fs::read_to_string(SHIM).expect("shim.js not found");
    let shim = strip::strip_js(&shim).unwrap_or_else(|e| panic!("cannot strip comments from shim.js: {e}"));
    let out = std::env::var("OUT_DIR").expect("OUT_DIR not set");
    write_if_changed(&Path::new(&out).join("shim.js"), shim.as_bytes());

    for dir in ASSET_DIRS {
        let src = Path::new("../web").join(dir);
        let dst = Path::new("gen-web").join(dir);
        println!("cargo:rerun-if-changed={}", src.display());
        // remove files that are gone from web/
        let _ = std::fs::remove_dir_all(&dst);
        std::fs::create_dir_all(&dst).unwrap();
        for entry in std::fs::read_dir(&src).unwrap_or_else(|e| panic!("{}: {e}", src.display())) {
            let entry = entry.unwrap();
            if entry.file_type().unwrap().is_file() {
                println!("cargo:rerun-if-changed={}", entry.path().display());
                write_if_changed(&dst.join(entry.file_name()), &std::fs::read(entry.path()).unwrap());
            }
        }
    }
    tauri_build::build()
}
