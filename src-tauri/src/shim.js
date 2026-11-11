// Connects the tracker page to the app; runs before the page's own scripts.
// Settings go to data\settings.json, "Choose .ess file" opens the Windows dialog, SteApp serves the
// Settings box tools, and the app is told when the page is ready to be shown.
// The languages from lang\ come in __STE_LANGS__ (main.rs), the chosen one is the "lang" setting.
(function(){
  var S = window.__STE_SETTINGS__ || {};
  var KEYS = {'skyrim-tracker-theme':'theme','skyrim-tracker-tab':'tab','skyrim-tracker-dense':'dense','skyrim-tracker-lang':'lang',
              'skyrim-tracker-eid':'eid'};
  var MARKS = 'skyrim-tracker-marks';
  var FILTERS = 'skyrim-tracker-filters';
  var other = {};

  // Tauri may not be ready on the very first calls: wait a moment and try again
  function invoke(cmd, args, tries){
    var core = window.__TAURI__ && window.__TAURI__.core;
    if (core && core.invoke) {
      try { core.invoke(cmd, args || {}).catch(function(){}); } catch(e){}
      return;
    }
    tries = tries || 0;
    if (tries < 200) setTimeout(function(){ invoke(cmd, args, tries + 1); }, 25);
  }
  function send(key, value){ invoke('set_setting', {key: key, value: value === undefined ? null : value}); }

  // Mark ticks per character
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
      if (k === FILTERS) return S.filters ? JSON.stringify(S.filters) : null;
      return Object.prototype.hasOwnProperty.call(other, k) ? other[k] : null;
    },
    setItem: function(k, v){
      k = String(k); v = String(v);
      if (KEYS[k]) { S[KEYS[k]] = v; send(KEYS[k], v); return; }
      if (k === MARKS) {
        var parsed = {}; try { parsed = JSON.parse(v) || {}; } catch(e){}
        S.marks = cleanMarks(parsed); send('marks', S.marks); return;
      }
      if (k === FILTERS) {
        var f = {}; try { f = JSON.parse(v) || {}; } catch(e){}
        S.filters = f; send('filters', Object.keys(f).length ? f : null); return;
      }
      other[k] = v;
    },
    removeItem: function(k){
      k = String(k);
      if (KEYS[k]) { delete S[KEYS[k]]; send(KEYS[k], null); return; }
      if (k === MARKS) { delete S.marks; send('marks', null); return; }
      if (k === FILTERS) { delete S.filters; send('filters', null); return; }
      delete other[k];
    },
    clear: function(){ other = {}; },
    key: function(i){ return Object.keys(other)[i] || null; },
    get length(){ return Object.keys(other).length; }
  };
  try { Object.defineProperty(window, 'localStorage', {value: store, configurable: true}); } catch(e){}

  // Settings - Tools: the data folder in Explorer; the CSV export asks where to save (the answer comes back
  // through exported(), see export_csv in main.rs)
  var exportDone = null;
  window.SteApp = {
    openData: function(){ invoke('open_data_folder'); },
    exportCsv: function(name, text){
      if (exportDone) return Promise.resolve(false);
      return new Promise(function(r){ exportDone = r; invoke('export_csv', {name: name, text: text}); });
    },
    exported: function(ok){ var r = exportDone; exportDone = null; if (r) r(!!ok); }
  };

  // "Choose .ess file" opens the Windows dialog
  document.addEventListener('click', function(e){
    if (e.target && e.target.id === 'essInput') {
      e.preventDefault();
      e.stopImmediatePropagation();
      invoke('choose_save');
    }
  }, true);

  // start-up: the window stays hidden from view until fonts and pictures are ready
  // and the page is painted, so the first thing on screen is the finished tracker
  var revealed = false;
  function reveal(){
    if (revealed) return;
    revealed = true;
    invoke('page_ready');
  }
  var started = false;
  function whenPainted(){
    if (started) return;
    started = true;
    var fonts = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
    var theme = document.body && document.body.classList.contains('theme-parchment') ? 'light' : 'dark';
    // both theme pictures, not only the current one
    var picture = window.STE_BG_READY || (window.steBgReady ? window.steBgReady(theme) : Promise.resolve());
    function frames(){
      requestAnimationFrame(function(){ requestAnimationFrame(function(){ requestAnimationFrame(function(){
        setTimeout(reveal, 120);
      }); }); });
      setTimeout(reveal, 600);   // in case animation frames are held back
    }
    Promise.all([fonts, picture]).then(warmUp).then(frames, frames);
  }

  // warm-up while hidden: the first hidden quest tab drawn is slow, so one of
  // them is drawn once now, where nobody sees it (the other is then fast too)
  function warmUp(){
    var b = document.body;
    if (!b) return;
    var panels = [].slice.call(document.querySelectorAll('.panel'));
    var start = panels.filter(function(p){ return p.classList.contains('active'); });
    var pre = b.classList.contains('app-pre');
    function show(n){ panels.forEach(function(p){ p.classList.toggle('active', p.dataset.panel === n); }); }
    function twoFrames(){ return new Promise(function(r){ requestAnimationFrame(function(){ requestAnimationFrame(r); }); }); }
    var chain = Promise.resolve();
    b.classList.remove('app-pre');
    ['bosses'].forEach(function(n){ chain = chain.then(function(){ show(n); return twoFrames(); }); });
    function restore(){
      panels.forEach(function(p){ p.classList.toggle('active', start.indexOf(p) >= 0); });
      if (pre) b.classList.add('app-pre');
    }
    // never hold the window back for long
    var cap = new Promise(function(r){ setTimeout(r, 1500); });
    return Promise.race([chain, cap]).then(function(){ restore(); return twoFrames(); });
  }

  window.addEventListener('load', function(){
    whenPainted();
    setTimeout(reveal, 3000);   // fallbacks
  });
  setTimeout(reveal, 6000);

  // page zoom (Ctrl+wheel, Ctrl +/-), remembered for the next start
  var lastRatio = window.devicePixelRatio || 1;
  window.addEventListener('resize', function(){
    var r = window.devicePixelRatio || 1;
    if (r !== lastRatio) { lastRatio = r; invoke('zoom_changed', {ratio: r}); }
  });
  // Ctrl +/-/0 by hand: the browser's own keys are off; same steps as the browser
  var STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5];
  document.addEventListener('keydown', function(e){
    if (!(e.ctrlKey || e.metaKey) || e.altKey || !window.__TAURI__) return;
    var k = e.code, dir = (k === 'Equal' || k === 'NumpadAdd') ? 1 : (k === 'Minus' || k === 'NumpadSubtract') ? -1 : (k === 'Digit0' || k === 'Numpad0') ? 0 : null;
    if (dir === null) return;
    e.preventDefault();
    var z = (window.devicePixelRatio || 1) / (window.__STE_SCALE__ || 1), next = 1;
    if (dir > 0) next = STEPS.find(function(s){ return s > z + 0.005; }) || 5;
    if (dir < 0) next = STEPS.slice().reverse().find(function(s){ return s < z - 0.005; }) || 0.25;
    invoke('set_zoom', {zoom: next});
  });

  // no browser context menu
  document.addEventListener('contextmenu', function(e){ e.preventDefault(); }, true);

  // a file dropped on the window must not replace the tracker page
  ['dragover', 'drop'].forEach(function(t){
    window.addEventListener(t, function(e){ e.preventDefault(); }, false);
  });
})();
