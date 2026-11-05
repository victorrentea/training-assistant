// The theme of every page on this origin. Loaded first, in <head>, so the page never
// paints in the wrong colours. Nothing stored = follow the OS, the default for everyone.
// html.dark / html.light drive all the CSS; the wiki reads the same key in
// daemon/wiki/quartz/darkmode.inline.ts.
(function () {
  var KEY = 'interact-theme';
  var root = document.documentElement;
  var os = window.matchMedia('(prefers-color-scheme: dark)');

  function choice() {
    try {
      var saved = localStorage.getItem(KEY);
      return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch (e) {
      return 'system';
    }
  }

  function apply() {
    var picked = choice();
    var dark = picked === 'dark' || (picked === 'system' && os.matches);
    root.classList.toggle('dark', dark);
    root.classList.toggle('light', !dark);
    root.style.colorScheme = dark ? 'dark' : 'light';
    document.dispatchEvent(new CustomEvent('theme-change', { detail: { choice: picked } }));
  }

  function set(picked) {
    try {
      if (picked === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, picked);
    } catch (e) { /* private mode: lasts until the page reloads */ }
    apply();
  }

  window.Theme = { choice: choice, set: set };
  os.addEventListener('change', apply);
  // Another tab of the same browser changed it.
  window.addEventListener('storage', function (e) { if (e.key === KEY || e.key === null) apply(); });
  apply();
})();
