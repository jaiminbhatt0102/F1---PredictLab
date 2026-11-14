// Runs before the page paints so the chosen theme never flashes. Dark is the default; light only if the visitor chose it.
// Kept as a file because the page's security policy blocks inline scripts.
(function () {
  var t = 'dark';
  try { if (localStorage.getItem('f1-theme') === 'light') t = 'light'; } catch (e) { /* storage blocked: stay dark */ }
  document.documentElement.dataset.theme = t;
})();
