/* theme.js — the light/dark switch, and the only file that runs before paint.
 *
 * Deliberately a CLASSIC script, not a module, and loaded in <head>: a module
 * is deferred, so it would run after the page had already painted in the
 * wrong theme and the toggle would announce itself with a flash on every
 * load. This is also why it cannot be part of app.js.
 *
 * It sets `data-theme` on <html> and nothing else. Every colour in app.css is
 * `light-dark(...)`, so flipping `color-scheme` — which is all the attribute
 * does — re-resolves the whole palette, plus the browser's own scrollbars and
 * form widgets. There is no palette here and there must never be one: one
 * home for the tokens is the point (app.css § TOKENS AND THEME).
 *
 * Three states, not two. "auto" is a real answer — most people want the OS
 * preference — and a two-state toggle silently makes the first click a
 * permanent opt-out of it with no way back short of clearing storage.
 */

(function () {
  "use strict";

  var KEY = "proofcut.theme";
  var ORDER = ["auto", "light", "dark"];
  var FACE = {
    auto: { glyph: "◐", title: "theme: following the system — click for light" },
    light: { glyph: "☀", title: "theme: light — click for dark" },
    dark: { glyph: "☾", title: "theme: dark — click to follow the system" },
  };

  function stored() {
    try {
      var value = window.localStorage.getItem(KEY);
      return ORDER.indexOf(value) === -1 ? "auto" : value;
    } catch (err) {
      // Private mode, or storage disabled. Following the OS is the right
      // fallback: it is what the CSS does with no attribute set at all.
      return "auto";
    }
  }

  /* CSS repaints itself; a <canvas> does not — it holds whatever ink it was
   * drawn with. So the switch has to say it moved, and both canvases in the
   * page (the waveform lane, the audio level display) listen for this and
   * re-read their colour. Raised on an OS preference change too, because in
   * "auto" that is a theme change with no click behind it. */
  function announce(mode) {
    window.dispatchEvent(new CustomEvent("proofcut:theme", { detail: { mode: mode } }));
  }

  function apply(mode) {
    if (mode === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
  }

  // Held in memory as well as in storage, so the cycle still advances when
  // storage refuses the write.
  var current = stored();

  // Before paint — the whole reason this file is separate.
  apply(current);

  function paintButton(button, mode) {
    button.textContent = FACE[mode].glyph;
    button.title = FACE[mode].title;
    button.setAttribute("aria-label", FACE[mode].title);
  }

  function wire() {
    var button = document.getElementById("theme");
    if (!button) return;
    paintButton(button, current);
    button.addEventListener("click", function () {
      current = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
      try {
        window.localStorage.setItem(KEY, current);
      } catch (err) {
        // Unstorable: the choice still applies to this page, it just will
        // not survive a reload. Better than refusing to switch.
      }
      apply(current);
      paintButton(button, current);
      announce(current);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if (current === "auto") announce(current);
    });
  }
})();
