// Skyrim Tracker Extreme - the desktop app.
// Shows the tracker page, opens a save picked by the user and passes the result to the page.
// Portable: the page and tables are inside the exe, settings go to data\ next to it.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{Map, Value};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::DialogExt;

const APP_NAME: &str = "Skyrim Tracker Extreme";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const SETTINGS_VERSION: i64 = 2;
const DEFAULT_SIZE: (f64, f64) = (1280.0, 860.0); // window size when not maximized
const MIN_SIZE: (f64, f64) = (480.0, 600.0);
const SHIM_JS: &str = include_str!(concat!(env!("OUT_DIR"), "/shim.js")); // comments removed by build.rs

/// start-up colour of each theme, close to its picture
fn theme_background(theme: Option<&str>) -> &'static str {
    match theme {
        Some("dark") => "#141a20",
        _ => "#d3bfa3",
    }
}

/// the tracker tables, built into the exe
const TABLES: [(&str, &[u8]); 11] = [
    ("locations_tracker.csv", include_bytes!("../../tables/locations_tracker.csv")),
    ("MapMarkerExport.csv", include_bytes!("../../tables/MapMarkerExport.csv")),
    ("quests_tracker.csv", include_bytes!("../../tables/quests_tracker.csv")),
    ("spells_tracker.csv", include_bytes!("../../tables/spells_tracker.csv")),
    ("shouts_tracker.csv", include_bytes!("../../tables/shouts_tracker.csv")),
    ("enchanting_tracker.csv", include_bytes!("../../tables/enchanting_tracker.csv")),
    ("ingredients_tracker.csv", include_bytes!("../../tables/ingredients_tracker.csv")),
    ("perks_tracker.csv", include_bytes!("../../tables/perks_tracker.csv")),
    ("collectibles_tracker.csv", include_bytes!("../../tables/collectibles_tracker.csv")),
    ("collectibles_houses.csv", include_bytes!("../../tables/collectibles_houses.csv")),
    ("books_tracker.csv", include_bytes!("../../tables/books_tracker.csv")),
];

fn tables() -> ste_core::Tables {
    TABLES.iter().map(|(n, b)| (n.to_string(), b.to_vec())).collect()
}

// ---------------------------------------------------------------------------
// folders and error log

fn app_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// data\ next to the exe, or %LOCALAPPDATA% if that folder is not writable
fn data_dir() -> PathBuf {
    let mut candidates = vec![app_dir().join("data")];
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        candidates.push(PathBuf::from(local).join(APP_NAME));
    }
    candidates.push(std::env::temp_dir().join(APP_NAME));
    for dir in candidates {
        if std::fs::create_dir_all(&dir).is_ok() {
            let probe = dir.join(".write_test");
            if std::fs::write(&probe, b"ok").is_ok() {
                let _ = std::fs::remove_file(&probe);
                return dir;
            }
        }
    }
    std::env::temp_dir()
}

/// local time for the log
fn timestamp() -> String {
    #[cfg(windows)]
    {
        #[repr(C)]
        struct SystemTime {
            year: u16,
            month: u16,
            day_of_week: u16,
            day: u16,
            hour: u16,
            minute: u16,
            second: u16,
            ms: u16,
        }
        #[link(name = "kernel32")]
        extern "system" {
            fn GetLocalTime(t: *mut SystemTime);
        }
        let mut t = SystemTime { year: 0, month: 0, day_of_week: 0, day: 0, hour: 0, minute: 0, second: 0, ms: 0 };
        unsafe { GetLocalTime(&mut t) };
        format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}", t.year, t.month, t.day, t.hour, t.minute, t.second)
    }
    #[cfg(not(windows))]
    {
        String::new()
    }
}

/// adds an entry to data\error.log
fn log_error(log: &Path, place: &str, details: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(log) {
        let _ = write!(f, "[{}] {APP_NAME} {APP_VERSION} - {place}\n{details}\n\n", timestamp());
    }
}

// ---------------------------------------------------------------------------
// settings (data\settings.json)

struct AppState {
    settings: Mutex<Map<String, Value>>,
    settings_path: PathBuf,
    error_log: PathBuf,
    busy: AtomicBool,
    shown: AtomicBool,
}

impl AppState {
    fn load(data: &Path) -> AppState {
        let settings_path = data.join("settings.json");
        let error_log = data.join("error.log");
        let mut settings = Map::new();
        match std::fs::read_to_string(&settings_path) {
            Ok(text) => match serde_json::from_str::<Value>(&text) {
                Ok(Value::Object(m)) => settings = m,
                _ => log_error(&error_log, "settings.json could not be read, defaults are used", ""),
            },
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => log_error(&error_log, "settings.json could not be read, defaults are used", &e.to_string()),
        }
        // old theme names from 1.0.0
        let old = match settings.get("theme").and_then(Value::as_str) {
            Some("daedric") => Some("dark"),
            Some("parchment") => Some("light"),
            _ => None,
        };
        if let Some(t) = old {
            settings.insert("theme".into(), Value::from(t));
        }
        // Mark ticks from 1.0.0 no longer match the rows
        if settings.get("version").and_then(Value::as_i64).unwrap_or(1) < 2 {
            settings.remove("marks");
        }
        AppState { settings: Mutex::new(settings), settings_path, error_log, busy: AtomicBool::new(false), shown: AtomicBool::new(false) }
    }

    fn save(&self) {
        let mut s = self.settings.lock().unwrap();
        s.insert("version".into(), Value::from(SETTINGS_VERSION));
        let text = serde_json::to_string_pretty(&Value::Object(s.clone())).unwrap_or_default();
        drop(s);
        let tmp = self.settings_path.with_extension("json.tmp");
        let ok = std::fs::write(&tmp, text).and_then(|_| std::fs::rename(&tmp, &self.settings_path));
        if let Err(e) = ok {
            log_error(&self.error_log, "settings.json could not be written", &e.to_string());
        }
    }

    fn get_str(&self, key: &str) -> Option<String> {
        self.settings.lock().unwrap().get(key).and_then(Value::as_str).map(str::to_string)
    }
}

// ---------------------------------------------------------------------------
// commands called from the page (shim.js)

#[tauri::command]
fn set_setting(state: tauri::State<'_, AppState>, key: String, value: Value) -> bool {
    if !["theme", "tab", "dense", "marks"].contains(&key.as_str()) {
        return false;
    }
    {
        let mut s = state.settings.lock().unwrap();
        if value.is_null() {
            s.remove(&key);
        } else {
            s.insert(key, value);
        }
    }
    state.save();
    true
}

/// remembers the page zoom (ratio = zoom x display scale)
#[tauri::command]
fn zoom_changed(window: WebviewWindow, state: tauri::State<'_, AppState>, ratio: f64) -> bool {
    let scale = window.scale_factor().unwrap_or(1.0);
    if !(ratio.is_finite() && ratio > 0.0 && scale > 0.0) {
        return false;
    }
    let zoom = (ratio / scale * 100.0).round() / 100.0;
    {
        let mut s = state.settings.lock().unwrap();
        if (zoom - 1.0).abs() < 0.005 {
            s.remove("zoom");
        } else {
            s.insert("zoom".into(), Value::from(zoom));
        }
    }
    state.save();
    true
}

/// The window starts hidden from view while the page paints itself;
/// the page calls this when it is ready, and the finished page appears at once.
#[tauri::command]
fn page_ready(window: WebviewWindow) -> bool {
    show_window(&window);
    true
}

fn show_window(window: &WebviewWindow) {
    if window.state::<AppState>().shown.swap(true, Ordering::SeqCst) {
        return;
    }
    if let Ok(h) = window.hwnd() {
        let hwnd = h.0 as *mut core::ffi::c_void;
        cloak::set(hwnd, false);
        // the page's cursor shows only after the mouse moves, so move it a little
        let addr = hwnd as usize;
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(60));
            cloak::nudge_cursor(addr as *mut core::ffi::c_void);
        });
    }
    let _ = window.set_focus();
}

#[cfg(windows)]
mod cloak {
    use core::ffi::c_void;
    #[link(name = "dwmapi")]
    extern "system" {
        fn DwmSetWindowAttribute(hwnd: *mut c_void, attribute: u32, value: *const c_void, size: u32) -> i32;
    }
    const DWMWA_CLOAK: u32 = 13;

    #[repr(C)]
    struct Point {
        x: i32,
        y: i32,
    }
    #[repr(C)]
    struct Rect {
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    }
    #[link(name = "user32")]
    extern "system" {
        fn GetCursorPos(p: *mut Point) -> i32;
        fn SetCursorPos(x: i32, y: i32) -> i32;
        fn GetWindowRect(hwnd: *mut c_void, r: *mut Rect) -> i32;
    }

    /// moves the pointer 1 px and back if it is over the window
    pub fn nudge_cursor(hwnd: *mut c_void) {
        unsafe {
            let mut p = Point { x: 0, y: 0 };
            let mut r = Rect { left: 0, top: 0, right: 0, bottom: 0 };
            if GetCursorPos(&mut p) == 0 || GetWindowRect(hwnd, &mut r) == 0 {
                return;
            }
            if p.x < r.left || p.x >= r.right || p.y < r.top || p.y >= r.bottom {
                return;
            }
            SetCursorPos(p.x + 1, p.y);
            std::thread::sleep(std::time::Duration::from_millis(20));
            SetCursorPos(p.x, p.y);
        }
    }

    pub fn set(hwnd: *mut c_void, cloaked: bool) {
        let v: i32 = cloaked as i32;
        unsafe {
            DwmSetWindowAttribute(hwnd, DWMWA_CLOAK, &v as *const i32 as *const c_void, 4);
        }
    }
}

#[tauri::command]
fn choose_save(window: WebviewWindow) -> bool {
    // the dialog waits for the user, so it runs on its own thread
    std::thread::spawn(move || {
        let state = window.state::<AppState>();
        if state.busy.swap(true, Ordering::SeqCst) {
            return;
        }
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| pick_and_load(&window)));
        if result.is_err() {
            js(&window, "TrackerLoader.fail('unknown', 0)");
        }
        state.busy.store(false, Ordering::SeqCst);
    });
    true
}

fn js(window: &WebviewWindow, code: &str) {
    if let Err(e) = window.eval(code) {
        let state = window.state::<AppState>();
        log_error(&state.error_log, "evaluating script failed", &format!("{e}\n{}", &code[..code.len().min(80)]));
    }
}

fn default_saves_dir(window: &WebviewWindow) -> Option<PathBuf> {
    let docs = window.path().document_dir().ok()?;
    for game in ["Skyrim Special Edition", "Skyrim Special Edition GOG"] {
        let p = docs.join("My Games").join(game).join("Saves");
        if p.is_dir() {
            return Some(p);
        }
    }
    [docs.join("My Games"), docs].into_iter().find(|p| p.is_dir())
}

fn pick_and_load(window: &WebviewWindow) {
    let state = window.state::<AppState>();
    let folder = state
        .get_str("saves_folder")
        .map(PathBuf::from)
        .filter(|p| p.is_dir())
        .or_else(|| default_saves_dir(window));
    let mut dialog = window
        .dialog()
        .file()
        .set_parent(window)
        .add_filter("Skyrim save (*.ess)", &["ess"])
        .add_filter("All files (*.*)", &["*"]);
    if let Some(f) = folder {
        dialog = dialog.set_directory(f);
    }
    let Some(picked) = dialog.blocking_pick_file() else { return };
    let Some(path) = picked.as_path().map(Path::to_path_buf) else { return };
    let path = std::path::absolute(&path).unwrap_or(path);
    if let Some(parent) = path.parent() {
        state.settings.lock().unwrap().insert("saves_folder".into(), Value::from(parent.to_string_lossy().into_owned()));
        state.save();
    }
    load(window, &path);
}

fn looks_like_save(path: &Path) -> bool {
    use std::io::Read;
    let mut magic = [0u8; 13];
    std::fs::File::open(path).and_then(|mut f| f.read_exact(&mut magic)).is_ok() && &magic == b"TESV_SAVEGAME"
}

fn load(window: &WebviewWindow, path: &Path) {
    let state = window.state::<AppState>();
    let name = path.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    js(window, &format!("TrackerLoader.start({})", Value::from(name.clone())));
    if !looks_like_save(path) {
        js(window, "TrackerLoader.fail('not_save')");
        return;
    }
    let stage = Arc::new(AtomicUsize::new(0));
    let fail = |i: usize| {
        if i <= 1 {
            format!("TrackerLoader.fail('corrupt', {i})")
        } else if (4..=12).contains(&i) {
            format!("TrackerLoader.fail('category', {i})")
        } else {
            format!("TrackerLoader.fail('unknown', {i})")
        }
    };
    let raw = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => {
            log_error(&state.error_log, &format!("reading {} failed", path.display()), &e.to_string());
            js(window, &fail(0));
            return;
        }
    };
    let st = stage.clone();
    let mut progress = |i: usize| {
        st.store(i, Ordering::SeqCst);
        js(window, &format!("TrackerLoader.stage({i})"));
    };
    let tables = tables();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        ste_core::parse_save(&raw, &name, &tables, &mut progress)
    }));
    match result {
        Ok(Ok(json)) => js(window, &format!("TrackerData.load({json});TrackerLoader.done();")),
        Ok(Err(e)) => {
            let place = format!(
                "parsing {} failed at stage {} ({})",
                path.display(),
                e.stage,
                ste_core::STAGE_NAMES[e.stage.min(13)]
            );
            log_error(&state.error_log, &place, &e.message);
            js(window, &fail(e.stage));
        }
        Err(panic) => {
            let i = stage.load(Ordering::SeqCst);
            let msg = panic
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| panic.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_default();
            let place = format!("parsing {} failed at stage {i} ({})", path.display(), ste_core::STAGE_NAMES[i.min(13)]);
            log_error(&state.error_log, &place, &format!("panic: {msg}"));
            js(window, &fail(i));
        }
    }
}

// ---------------------------------------------------------------------------
// window

fn hex_color(c: &str) -> (u8, u8, u8) {
    let v = u32::from_str_radix(c.trim_start_matches('#'), 16).unwrap_or(0);
    ((v >> 16) as u8, (v >> 8) as u8, v as u8)
}

/// browser data: one folder in %TEMP%, reused by every run
fn webview_data_dir() -> PathBuf {
    let base = std::env::temp_dir();
    // old per-run folders
    if let Ok(entries) = std::fs::read_dir(&base) {
        for e in entries.flatten() {
            if e.file_name().to_string_lossy().starts_with("SkyrimTrackerExtreme_") {
                let _ = std::fs::remove_dir_all(e.path());
            }
        }
    }
    base.join("SkyrimTrackerExtreme")
}

fn main() {
    let data = data_dir();
    let state = AppState::load(&data);
    {
        let log = state.error_log.clone();
        std::panic::set_hook(Box::new(move |info| log_error(&log, "unhandled error", &info.to_string())));
    }

    let theme = state.get_str("theme");
    let background = theme_background(theme.as_deref());
    // no grey flash before the page appears
    std::env::set_var("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", format!("FF{}", background.trim_start_matches('#').to_uppercase()));
    let webdata_setup = webview_data_dir();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![set_setting, choose_save, zoom_changed, page_ready])
        .setup(move |app| {
            let state = app.state::<AppState>();
            let (settings_js, size, zoom) = {
                let s = state.settings.lock().unwrap();
                let mut page = Map::new();
                for k in ["theme", "tab", "dense", "marks"] {
                    if let Some(v) = s.get(k) {
                        page.insert(k.to_string(), v.clone());
                    }
                }
                let w = s.get("window").and_then(|w| w.get("width")).and_then(Value::as_f64).unwrap_or(DEFAULT_SIZE.0);
                let h = s.get("window").and_then(|w| w.get("height")).and_then(Value::as_f64).unwrap_or(DEFAULT_SIZE.1);
                let zoom = s.get("zoom").and_then(Value::as_f64).filter(|z| (0.25..=5.0).contains(z));
                (Value::Object(page).to_string(), (w.max(MIN_SIZE.0), h.max(MIN_SIZE.1)), zoom)
            };
            // the page builds its rows from the same tables
            let mut page_tables = Map::new();
            for (name, bytes) in TABLES.iter() {
                if name.ends_with("_tracker.csv") {
                    page_tables.insert(name.to_string(), Value::from(String::from_utf8_lossy(bytes).into_owned()));
                }
            }
            let scale = app.primary_monitor().ok().flatten().map(|m| m.scale_factor()).unwrap_or(1.0);
            let init = format!(
                "window.__STE_SETTINGS__={settings_js};window.__STE_TABLES__={};\
                 window.__STE_SCALE__={scale};window.__STE_ZOOM__={};\n{SHIM_JS}",
                Value::Object(page_tables),
                zoom.unwrap_or(1.0)
            );
            let (r, g, b) = hex_color(background);
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title(format!("{APP_NAME} v{APP_VERSION}"))
                .inner_size(size.0, size.1)
                .min_inner_size(MIN_SIZE.0, MIN_SIZE.1)
                .center()
                .maximized(true)
                .visible(false)
                .background_color(tauri::utils::config::Color(r, g, b, 255))
                .initialization_script(&init)
                .incognito(true)
                .data_directory(webdata_setup.clone())
                .zoom_hotkeys_enabled(true)
                // Tauri's defaults, plus: keep painting while the window is hidden from view
                .additional_browser_args(
                    "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection,CalculateNativeWinOcclusion",
                )
                .build()?;
            // hidden from view until the page is ready
            if let Ok(h) = window.hwnd() {
                cloak::set(h.0 as *mut core::ffi::c_void, true);
            }
            let _ = window.show();
            // just in case the page never reports back
            let w_late = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(8));
                show_window(&w_late);
            });
            if let Some(z) = zoom {
                let _ = window.set_zoom(z);
            }
            // remember the window size when not maximized
            let w2 = window.clone();
            window.on_window_event(move |event| match event {
                WindowEvent::Resized(size) => {
                    let maximized = w2.is_maximized().unwrap_or(false);
                    let minimized = w2.is_minimized().unwrap_or(false);
                    if !maximized && !minimized && size.width > 0 && size.height > 0 {
                        let scale = w2.scale_factor().unwrap_or(1.0);
                        let logical = size.to_logical::<f64>(scale);
                        let st = w2.state::<AppState>();
                        let mut s = st.settings.lock().unwrap();
                        let mut win = Map::new();
                        win.insert("width".into(), Value::from(logical.width.round() as i64));
                        win.insert("height".into(), Value::from(logical.height.round() as i64));
                        s.insert("window".into(), Value::Object(win));
                    }
                }
                WindowEvent::CloseRequested { .. } => w2.state::<AppState>().save(),
                // moved to a screen with another scale
                WindowEvent::ScaleFactorChanged { scale_factor, .. } => {
                    let _ = w2.eval(&format!("window.__STE_SCALE__={scale_factor}"));
                }
                _ => {}
            });
            Ok(())
        })
        .build(tauri::generate_context!());

    let app = match app {
        Ok(a) => a,
        Err(e) => {
            let log = data.join("error.log");
            log_error(&log, "start-up failed", &e.to_string());
            message_box(&format!("{APP_NAME} could not start.\nDetails were written to:\n{}", log.display()));
            return;
        }
    };
    app.run(move |handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<AppState>().save();
        }
    });
}

/// a plain Windows message box for start-up failures (no window exists yet)
fn message_box(text: &str) {
    #[cfg(windows)]
    {
        #[link(name = "user32")]
        extern "system" {
            fn MessageBoxW(hwnd: *mut core::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
        }
        let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
        let (t, c) = (wide(text), wide(APP_NAME));
        unsafe {
            MessageBoxW(std::ptr::null_mut(), t.as_ptr(), c.as_ptr(), 0x10);
        }
    }
    #[cfg(not(windows))]
    eprintln!("{text}");
}
