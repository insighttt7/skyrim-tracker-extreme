"""Skyrim Tracker Extreme - desktop app.

Opens the tracker page (Skyrim_Tracker_vNN.html) in a maximized pywebview
window, lets the user pick a .ess save with the Windows file dialog, parses
it with parse_ess.run() and hands the result to the page
(TrackerData.load + TrackerLoader.done).

The page file itself is not modified: a small script is added to it in
memory at start-up. It
  - routes the "Choose .ess file" button (and "Choose another save" on the
    error card) to the native dialog instead of the browser file picker;
  - keeps theme / tab / compact rows / Mark ticks in data\\settings.json
    instead of browser storage (Mark ticks are stored as row keys, data-key);
  - stops a file dropped on the window from replacing the page.

Portable layout (everything lives next to the exe):
  Skyrim Tracker Extreme.exe
  libs\\              Python runtime, pywebview, the embedded page and CSVs
  data\\settings.json  created on first run
  data\\error.log      only written when something goes wrong

Run from source (for testing): py app.py  - the page and the 12 CSVs are then
read from this folder instead of the embedded bundle.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

import webview

import parse_ess

APP_NAME = 'Skyrim Tracker Extreme'
APP_VERSION = '1.1.0'
HTML_FILE = 'Skyrim_Tracker_v13.html'
SETTINGS_VERSION = 2              # 2 = Mark ticks stored as row keys (1.1.0)
DEFAULT_SIZE = (1280, 860)      # restored (not maximized) window size, logical px
MIN_SIZE = (480, 600)
# page background of each theme (body background in the tracker page); the
# window starts in the colour of the theme that was last picked, or of the
# light theme (the page default) when none was picked yet
THEME_BACKGROUND = {'dark': '#0c1316', 'light': '#d8c59c'}
STAGE_NAMES = ['Reading save', 'Decompressing', 'Plugins', 'Change forms', 'Quests',
               'Locations', 'Spells', 'Shouts', 'Enchanting', 'Ingredients', 'Perks',
               'Collectibles', 'Books', 'Building tracker']


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """data\\ next to the exe; if that folder is not writable (for example the
    app was put into Program Files) fall back to %LOCALAPPDATA%."""
    for base in (app_dir(), os.path.join(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir(), APP_NAME)):
        path = os.path.join(base, 'data') if base == app_dir() else base
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, '.write_test')
            with open(probe, 'w') as fh:
                fh.write('ok')
            os.remove(probe)
            return path
        except OSError:
            continue
    return tempfile.gettempdir()


DATA_DIR = data_dir()
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
ERROR_LOG = os.path.join(DATA_DIR, 'error.log')


def log_error(where, exc_info=None):
    """Appends a timestamped entry to data\\error.log (the file only appears
    when there is something to report)."""
    try:
        text = ''.join(traceback.format_exception(*(exc_info or sys.exc_info())))
        with open(ERROR_LOG, 'a', encoding='utf-8') as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {APP_NAME} {APP_VERSION} - {where}\n{text}\n")
    except Exception:
        pass


def documents_dir():
    """The real Documents folder (follows OneDrive / a moved Documents folder)."""
    try:
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [('d1', wintypes.DWORD), ('d2', wintypes.WORD), ('d3', wintypes.WORD), ('d4', ctypes.c_ubyte * 8)]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def default_saves_dir():
    docs = documents_dir()
    for game in ('Skyrim Special Edition', 'Skyrim Special Edition GOG'):
        path = os.path.join(docs, 'My Games', game, 'Saves')
        if os.path.isdir(path):
            return path
    for path in (os.path.join(docs, 'My Games'), docs):
        if os.path.isdir(path):
            return path
    return ''


# ---------------------------------------------------------------------------
# Settings (data\settings.json)
# ---------------------------------------------------------------------------
_settings_lock = threading.Lock()


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception:
        log_error('settings.json could not be read, defaults are used')
    return {}


SETTINGS = load_settings()
# 1.0.0 stored the theme under its old internal names
_OLD_THEME = {'daedric': 'dark', 'parchment': 'light'}
if SETTINGS.get('theme') in _OLD_THEME:
    SETTINGS['theme'] = _OLD_THEME[SETTINGS['theme']]
# 1.0.0 (settings version 1) stored Mark ticks as row Order numbers; rows are
# found by key now, so those numbers mean nothing and are dropped once
if SETTINGS.get('version', 1) < 2:
    SETTINGS.pop('marks', None)


def save_settings():
    with _settings_lock:
        SETTINGS['version'] = SETTINGS_VERSION
        tmp = SETTINGS_PATH + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(SETTINGS, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, SETTINGS_PATH)
        except Exception:
            log_error('settings.json could not be written')


# ---------------------------------------------------------------------------
# Embedded page and CSVs
# ---------------------------------------------------------------------------
def load_bundle():
    """{'html': bytes, 'csv': {name: bytes}} - from the bundle built by
    pack.py, or from this folder when running from source."""
    try:
        import bundle_data
        return bundle_data.load()
    except ImportError:
        def source(name, folder):
            # repository layout (src\\, web\\, tables\\) or everything in one folder
            for d in (os.path.join(app_dir(), os.pardir, folder), app_dir()):
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path
            raise FileNotFoundError(name)
        with open(source(HTML_FILE, 'web'), 'rb') as fh:
            html = fh.read()
        csv = {}
        for name in parse_ess.CSV_ORDER:
            with open(source(name, 'tables'), 'rb') as fh:
                csv[name] = fh.read()
        return {'html': html, 'csv': csv}


# Runs before the page's own script (inserted right after <head>).
SHIM_JS = r"""
(function(){
  var S = window.__STE_SETTINGS__ || {};
  var KEYS = {'skyrim-tracker-theme':'theme','skyrim-tracker-tab':'tab','skyrim-tracker-dense':'dense'};
  var MARKS = 'skyrim-tracker-marks';
  var other = {}, queue = [], ready = false;

  function send(key, value){
    if (ready) { try { window.pywebview.api.set_setting(key, value); } catch(e){} }
    else queue.push([key, value]);
  }
  window.addEventListener('pywebviewready', function(){
    ready = true;
    queue.splice(0).forEach(function(a){ send(a[0], a[1]); });
  });

  // Mark ticks: the page and settings.json both keep row keys (data-key) per character
  function cleanMarks(obj){
    var out = {};
    Object.keys(obj || {}).forEach(function(owner){
      var list = (obj[owner] || []).filter(function(id){ return typeof id === 'string' && id; });
      if (list.length) out[owner] = list;
    });
    return out;
  }

  var store = {
    getItem: function(k){
      k = String(k);
      if (KEYS[k]) { var v = S[KEYS[k]]; return (v === undefined || v === null) ? null : String(v); }
      if (k === MARKS) return S.marks ? JSON.stringify(cleanMarks(S.marks)) : null;
      return Object.prototype.hasOwnProperty.call(other, k) ? other[k] : null;
    },
    setItem: function(k, v){
      k = String(k); v = String(v);
      if (KEYS[k]) { S[KEYS[k]] = v; send(KEYS[k], v); return; }
      if (k === MARKS) {
        var parsed = {}; try { parsed = JSON.parse(v) || {}; } catch(e){}
        S.marks = cleanMarks(parsed); send('marks', S.marks); return;
      }
      other[k] = v;
    },
    removeItem: function(k){
      k = String(k);
      if (KEYS[k]) { delete S[KEYS[k]]; send(KEYS[k], null); return; }
      if (k === MARKS) { delete S.marks; send('marks', null); return; }
      delete other[k];
    },
    clear: function(){ other = {}; },
    key: function(i){ return Object.keys(other)[i] || null; },
    get length(){ return Object.keys(other).length; }
  };
  try { Object.defineProperty(window, 'localStorage', {value: store, configurable: true}); } catch(e){}

  // "Choose .ess file" (and "Choose another save" on the error card) open the
  // native Windows dialog: the browser picker cannot give the full file path
  document.addEventListener('click', function(e){
    if (e.target && e.target.id === 'essInput') {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (window.pywebview && window.pywebview.api) window.pywebview.api.choose_save();
    }
  }, true);

  // start-up cover: report back once the page has been painted (load event,
  // fonts ready, then two animation frames), so the cover is removed only
  // when the finished tracker is already on screen
  var pageLoaded = false, apiReady = false, reported = false;
  function reportPainted(){
    if (reported || !pageLoaded || !apiReady) return;
    reported = true;
    var fonts = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
    fonts.then(function(){
      requestAnimationFrame(function(){ requestAnimationFrame(function(){
        try { window.pywebview.api.page_ready(); } catch(e){}
      }); });
    });
  }
  window.addEventListener('load', function(){ pageLoaded = true; reportPainted(); });
  window.addEventListener('pywebviewready', function(){ apiReady = true; reportPainted(); });

  // a file dropped on the window must not replace the tracker page
  ['dragover', 'drop'].forEach(function(t){
    window.addEventListener(t, function(e){ e.preventDefault(); }, false);
  });
})();
"""


def build_page(html_bytes):
    html = html_bytes.decode('utf-8')
    settings = {k: SETTINGS[k] for k in ('theme', 'tab', 'dense', 'marks') if k in SETTINGS}
    boot = ('<script>window.__STE_SETTINGS__=' + json.dumps(settings, ensure_ascii=False)
            .replace('</', '<\\/') + ';' + SHIM_JS + '</script>')
    pos = html.find('<head>')
    if pos < 0:
        raise RuntimeError('The tracker page has no <head> tag')
    pos += len('<head>')
    return html[:pos] + boot + html[pos:]


# ---------------------------------------------------------------------------
# Window and JS API
# ---------------------------------------------------------------------------
WINDOW = None
BUNDLE = None
_busy = threading.Lock()
_window_state = {'maximized': True}


def js(code):
    try:
        return WINDOW.evaluate_js(code)
    except Exception:
        log_error('evaluate_js failed: ' + code[:80])


def looks_like_save(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read(13) == b'TESV_SAVEGAME'
    except OSError:
        return False


class Api:
    """Methods callable from the page as window.pywebview.api.<name>()."""

    def set_setting(self, key, value):
        if key not in ('theme', 'tab', 'dense', 'marks'):
            return False
        if value is None:
            SETTINGS.pop(key, None)
        else:
            SETTINGS[key] = value
        save_settings()
        return True

    def page_ready(self):
        _later(0.05, remove_cover)
        return True

    def choose_save(self):
        if not _busy.acquire(blocking=False):
            return False
        try:
            folder = SETTINGS.get('saves_folder') or ''
            if not os.path.isdir(folder):
                folder = default_saves_dir()
            picked = WINDOW.create_file_dialog(webview.FileDialog.OPEN, directory=folder,
                                               allow_multiple=False,
                                               file_types=('Skyrim save (*.ess)', 'All files (*.*)'))
            if not picked:
                return False
            path = picked[0] if isinstance(picked, (list, tuple)) else picked
            SETTINGS['saves_folder'] = os.path.dirname(os.path.abspath(path))
            save_settings()
            self._load(path)
            return True
        except Exception:
            log_error('choose_save')
            return False
        finally:
            _busy.release()

    def _load(self, path):
        name = os.path.basename(path)
        js('TrackerLoader.start(%s)' % json.dumps(name))
        if not looks_like_save(path):
            js("TrackerLoader.fail('not_save')")
            return
        stage = {'i': 0}

        def progress(i):
            stage['i'] = i
            js('TrackerLoader.stage(%d)' % i)

        try:
            result = parse_ess.run(path, BUNDLE['csv'], progress=progress)
            if not result:
                raise RuntimeError('The parser returned no data')
        except Exception:
            i = stage['i']
            log_error(f'parsing {path} failed at stage {i} ({STAGE_NAMES[i]})')
            if i <= 1:
                js("TrackerLoader.fail('corrupt', %d)" % i)
            elif 4 <= i <= 12:
                js("TrackerLoader.fail('category', %d)" % i)
            else:
                js("TrackerLoader.fail('unknown', %d)" % i)
            return
        payload = json.dumps(result, ensure_ascii=False)
        js('TrackerData.load(%s);TrackerLoader.done();' % payload)


def on_resized(width, height):
    if not _window_state['maximized'] and width > 0 and height > 0:
        SETTINGS['window'] = {'width': int(width), 'height': int(height)}


def on_maximized():
    _window_state['maximized'] = True


def on_restored():
    _window_state['maximized'] = False


def on_closing():
    save_settings()


# ---------------------------------------------------------------------------
# Start-up cover: WebView2 shows its own grey canvas for about a second while
# it starts and parses the page. A plain panel in the theme colour covers the
# browser until the page has loaded, then it is removed.
# ---------------------------------------------------------------------------
_cover = {'panel': None}
COVER_TIMEOUT = 10.0            # seconds; the cover never stays longer than this


def _later(seconds, fn):
    t = threading.Timer(seconds, fn)
    t.daemon = True             # never keeps the app alive after the window closes
    t.start()


def _on_ui(fn):
    from System import Action
    form = WINDOW.native
    form.Invoke(Action(fn))


def add_cover(color):
    try:
        import clr
        clr.AddReference('System.Windows.Forms')
        clr.AddReference('System.Drawing')
        from System.Windows.Forms import Panel, DockStyle
        from System.Drawing import ColorTranslator

        def make():
            panel = Panel()
            panel.Dock = DockStyle.Fill
            panel.BackColor = ColorTranslator.FromHtml(color)
            WINDOW.native.Controls.Add(panel)
            panel.BringToFront()
            _cover['panel'] = panel

        _on_ui(make)
        _later(COVER_TIMEOUT, remove_cover)
    except Exception:
        log_error('start-up cover could not be added')


def remove_cover():
    panel = _cover['panel']
    if panel is None:
        return
    _cover['panel'] = None

    def drop():
        panel.Parent.Controls.Remove(panel)
        panel.Dispose()

    try:
        _on_ui(drop)
    except Exception:
        log_error('start-up cover could not be removed')


def on_loaded():
    # normally the page itself reports that it is painted (Api.page_ready);
    # this is only a fallback in case that report never arrives
    _later(3.0, remove_cover)


def serve_page(page):
    """Serves the page from memory on 127.0.0.1 (only used when the page is
    too big for WebView2 NavigateToString, which is limited to 2 MB).
    Returns the URL."""
    import http.server
    body = page.encode('utf-8')

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_port}/'


def main():
    global WINDOW, BUNDLE
    sys.excepthook = lambda *e: log_error('unhandled error', e)
    threading.excepthook = lambda a: log_error('unhandled error in a thread', (a.exc_type, a.exc_value, a.exc_traceback))
    BUNDLE = load_bundle()
    page = build_page(BUNDLE['html'])
    # NavigateToString accepts at most 2 MB (UTF-16); bigger pages are served locally
    source = {'html': page}
    if len(page.encode('utf-16-le')) > 1_900_000:
        source = {'url': serve_page(page)}

    # start-up colour = background of the saved theme; the environment variable
    # is the WebView2 way to avoid the grey flash before the page is painted
    background = THEME_BACKGROUND.get(SETTINGS.get('theme'), THEME_BACKGROUND['light'])
    os.environ['WEBVIEW2_DEFAULT_BACKGROUND_COLOR'] = 'FF' + background.lstrip('#').upper()

    size = SETTINGS.get('window') or {}
    width = int(size.get('width') or DEFAULT_SIZE[0])
    height = int(size.get('height') or DEFAULT_SIZE[1])

    WINDOW = webview.create_window(f'{APP_NAME} v{APP_VERSION}', js_api=Api(),
                                   width=max(width, MIN_SIZE[0]), height=max(height, MIN_SIZE[1]),
                                   min_size=MIN_SIZE, maximized=True, text_select=True, zoomable=True,
                                   shadow=False,     # keep the standard Windows frame: pywebview's default
                                                     # shadow extends the frame 1 px into the page, which shows as
                                                     # a light line on the edges and a step at the title bar corners
                                   background_color=background, **source)
    WINDOW.events.resized += on_resized
    WINDOW.events.maximized += on_maximized
    WINDOW.events.restored += on_restored
    WINDOW.events.closing += on_closing
    WINDOW.events.before_show += lambda: add_cover(background)
    WINDOW.events.loaded += on_loaded

    # browser cache lives in a temporary folder and is removed on exit
    cache = tempfile.mkdtemp(prefix='SkyrimTrackerExtreme_')
    try:
        webview.start(gui='edgechromium', private_mode=True, storage_path=cache, debug=False)
    finally:
        save_settings()
        shutil.rmtree(cache, ignore_errors=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log_error('start-up failed')
        try:
            ctypes.windll.user32.MessageBoxW(None, 'Skyrim Tracker Extreme could not start.\n'
                                             f'Details were written to:\n{ERROR_LOG}', APP_NAME, 0x10)
        except Exception:
            pass
