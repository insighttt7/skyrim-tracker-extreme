// Connects the tracker page to the app; runs before the page's own scripts.
// Settings go to data\settings.json, "Choose .ess file" opens the Windows dialog,
// and the app is told when the page is ready to be shown.
(function(){
  var S = window.__STE_SETTINGS__ || {};
  var KEYS = {'skyrim-tracker-theme':'theme','skyrim-tracker-tab':'tab','skyrim-tracker-dense':'dense'};
  var MARKS = 'skyrim-tracker-marks';
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

  // no browser context menu
  document.addEventListener('contextmenu', function(e){ e.preventDefault(); }, true);

  // a file dropped on the window must not replace the tracker page
  ['dragover', 'drop'].forEach(function(t){
    window.addEventListener(t, function(e){ e.preventDefault(); }, false);
  });
})();
