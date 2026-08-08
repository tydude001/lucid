/* dom.js — tiny DOM helpers and time formatting shared by every module.
 *
 * Nothing here talks to the network or to `ops` — see api.js for that. Kept
 * separate because every module needs `el`/`$`/`fmt` and only some of them
 * need `api`.
 */

/** `document.getElementById`, shortened — every id below is unique on the page. */
export function $(id) {
  return document.getElementById(id);
}

/** Build one element: tag, an optional class string, optional text content. */
export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** `m:ss.s` — the clock format used everywhere timeline seconds are drawn. */
export function fmt(t) {
  if (t === null || t === undefined || Number.isNaN(t)) return "–";
  const sign = t < 0 ? "-" : "";
  t = Math.abs(t);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${sign}${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** `12.345s` — the source-second format quoted in tooltips and echoes. */
export function secs(t) {
  return t === null || t === undefined ? "–" : `${t.toFixed(3)}s`;
}
