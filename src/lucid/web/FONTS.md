# Vendored typefaces

The three type voices of DAYDREAM.md § Typography, shipped inside the package
rather than fetched at load time. That is not a preference: this server sends
`default-src 'self'`, so a CDN `<link>` would be refused and the page would
silently fall back to a system font.

Flat filenames, beside `app.css`, because `webui.py`'s `_send_static` serves a
filename and never a path — a `fonts/` subdirectory would 404.

| file | family | role | licence |
|---|---|---|---|
| `geist-sans-{400,500,600,700}.woff2` | Geist Sans 1.0.1 | UI and body | OFL-1.1 — `LICENSE-geist-sans.txt` |
| `source-serif-4.woff2`, `source-serif-4-italic.woff2` | Source Serif 4 (variable, 200–900) | the italic accent voice | OFL-1.1 — `LICENSE-source-serif-4.txt` |
| `jetbrains-mono.woff2` | JetBrains Mono (variable, 100–800) | timecodes, word indices, keyboard hints | OFL-1.1 — `LICENSE-jetbrains-mono.txt` |

All fetched from Fontsource's jsDelivr mirror, latin subset:
`https://cdn.jsdelivr.net/fontsource/fonts/<id>@latest/<subset>.woff2` — the
package ids are `geist-sans`, `source-serif-4:vf`, `jetbrains-mono:vf`. Geist
Sans has no variable build, which is why it is four static weights and the
other two are one file per style.

`tests/test_webui_http.py::test_the_vendored_fonts_are_served_and_the_css_asks_for_them`
reads the `url("/static/…woff2")` declarations back out of `app.css` and
fetches each one, so adding a weight to the stylesheet without adding the file
fails the suite rather than the page.
