/* Appearance before the page is drawn (no flash): the font and the text size chosen on this PC (Settings -> Appearance).
   Kept in this browser only; a wrong or missing value just means the normal look. */
(function () {
  'use strict';
  var FONTS = ['default', 'segoe', 'inter', 'source', 'plex', 'dm', 'nunito', 'serif'], SIZES = [0.85, 0.92, 1, 1.1, 1.2, 1.35];
  try {
    var p = JSON.parse(localStorage.getItem('bams_look') || '{}'), root = document.documentElement;
    if (FONTS.indexOf(p.font) > 0) root.setAttribute('data-font', p.font);
    if (SIZES.indexOf(p.size) >= 0) root.style.setProperty('--fs', String(p.size));
    if (localStorage.getItem('bams_nav') === 'mini') root.classList.add('nav-mini');
  } catch (e) { /* no storage: the normal look */ }
})();
