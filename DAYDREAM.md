# lucid × Daydream — the parity plan

**The direction, set by Tyler 2026-08-08: lucid copies Daydream — the full
feature set and the look/feel.** This is the one document for that work: what
Daydream actually is (observed, not recalled), the design system to copy, the
feature-by-feature map against lucid's shipped code, the detailed design notes
per feature, and the build order. PLAN.md and PRIOR-ART.md point
here rather than restating any of it.

Three lucid constraints do not move, and where a Daydream behaviour conflicts,
the constraint wins and the divergence is recorded in § What parity does not
import:

1. **No cloud, no accounts, no metering, no upload** (PLAN.md § Non-goals).
2. **The web UI draws and plays; it never decides** — every mutation goes
   through the same `ops` functions the CLI and MCP call, and **no lane is
   drawn that `export` cannot produce** (CLAUDE.md § Conventions).
3. **Cues address the source by word index, never the timeline** (PLAN.md
   § The property everything below defends).

## How this was captured, and the one limit

Captured 2026-08-08 without a browser: homepage HTML plus every subpage
(`/claude`, `/codex`, `/mcp`, `/download`, `/wall-of-love`), the three CSS
bundles (design tokens read from source), all sixteen homepage videos
downloaded and frame-sampled through ffmpeg, `hero.png` (a full-resolution
screenshot of the real editor), and the complete docs site via its Mintlify
markdown mirror (`docs.daydreamvideo.com/llms.txt` + per-page `.md`). The
limit: scroll choreography was reconstructed from DOM structure, `@keyframes`
and the videos, not watched live — close enough to copy from, not
pixel-testimony. The MCP tool schema remains unpublished anywhere on the site;
everything below about tools is workflow-level, from their docs' prose.

Older evidence — what Daydream is as a *competitor* (macOS-only, closed
source, pricing-vs-privacy tension) — stays in PRIOR-ART.md § Daydream.

---

## Daydream, observed

A macOS desktop editor (Pushie, Inc.) whose in-app chat **is Claude Code or
Codex run as a subprocess**, riding the user's existing Claude/ChatGPT
sign-in — no API key. The homepage title is "AI Video Editor for Claude Code
& Codex"; the product is positioned entirely around agents driving a real
timeline the user can still touch by hand. No Windows or Linux build exists,
which is the asymmetry that makes copying it worthwhile: on this box the
competitor cannot run at all.

### The editor, pane by pane

From `hero.png` (a real editor screenshot) and the four live HTML mocks on
the homepage. This is the anatomy the workspace copies.

**Top bar.** macOS traffic lights · `Projects / <project-name>` breadcrumb
(Projects is a link — there is a project list) · right side: `Agents` button,
aspect-ratio control showing `16:9`, `Export` button with download icon,
dark-mode toggle (moon), logo mark.

**Left pane — four tabs: `Editor · Assets · Templates · Properties`.**

* *Editor* is the transcript-as-document: project title as a heading, then
  the voiceover as flowing prose in soft highlighted blocks (rose-tinted
  background), word-level — each word is a span. Inline pause markers render
  between words as `[2.4s]` (docs show `[...0.4s]`). A **Show cuts** toggle
  reveals removed text with strikethrough; selecting struck text and pressing
  backspace (or a revert button) restores it. Selecting live text and
  pressing delete (or a scissors icon) cuts it, and the timeline updates.
  Below the script: `+ Add Video` and `+ Add Voiceover` buttons.
* *Assets* is import, **by role**: "Voiceover / Talking Head" (transcribed,
  becomes the script) vs "Footage / Images / Music" (watched and indexed for
  b-roll search — "the AI watches your video clips"). Multi-select import.
* *Templates* is a gallery of handcrafted motion-graphic templates; add one
  to the timeline, then customise by prompt or by hand.
* *Properties* edits the selected clip: text, font, colours, and transform —
  position, scale, rotation, opacity, crop.

**Centre — the preview.** The video, largest element on screen. Under it a
seek bar, `current / total` timecode, transport (jump-to-start · prev · play
· next · jump-to-end), volume slider. Captions render on the video with the
active word highlighted.

**Right pane — the agent.** Chat feed: the user's prompt in a bordered
rounded bubble; the agent's tool activity as a **checklist of green-check
lines** (observed labels: Reading timeline · Reading transcript · Checking
available footage · Surveying video content · Analyzing specific clips ·
Adding clips · Creating custom animation · Updating animation); then the
result as plain prose; **thumbs up/down** under each turn. Composer at the
bottom: placeholder "Ask AI to edit your video...", a `Start New Task`
affordance, `@` to mention assets, and muted hints — `Enter to send ·
Sonnet 4.6` (the model, named) and `⌘L to toggle` (panel show/hide).

**Bottom — the timeline, full width.** Toolbar: drag handle, undo/redo,
pointer tool, scissors/razor, and what read as snap and link toggles; on the
right a zoom `− slider +`. Large current timecode at left of the ruler; ruler
ticks every 10 s. Tracks, top to bottom, each with a header holding an icon,
**lock** and **visibility** toggles: `CC` (captions) · `V2` (graphics —
lavender blocks labelled "Two Line Title", "Image…") · `V1` (video — clips
carry **filmstrip thumbnails** and their source filename, e.g.
`lighthouse.mp4`, `sunset_DSCF0332.mov`) · `A1` (voiceover audio, e.g.
`hawaii_voiceover.wav`) · `A2` (short accent blocks — music/sfx). Clips are
pastel colour-coded (rose / mint / lavender / powder-blue). A thin blue
playhead runs the full height. **Right-click-drag on the timeline selects a
range** — used to place b-roll over that duration. Horizontal scrollbar
along the bottom.

### The workflows, as their docs specify them

1. **Connect an agent.** First launch shows a welcome screen with a status
   card per agent (Claude Code / Codex). `▷ Log in` opens the browser;
   Claude may ask to paste a login code back into the app. Card flips to
   "Connected — signed in as … · plan". Auto-setup installs the CLI in the
   background; on restrictive networks the fallback is installing the CLI
   yourself, and Daydream picks it up. Work/SSO accounts supported. States
   handled: Connected / Not connected / setup-failed (Retry) / status-check
   failed (refresh).
2. **Import and transcribe.** Import by role (above). In Editor, `Transcribe
   Video` / `Transcribe Voiceover` (multi-select allowed) transcribes and
   places the result on the timeline. 30+ languages.
3. **Cut by transcript.** Agent prompts their docs give as canonical: "Cut
   the filler words and long pauses", "Remove the second take of the intro
   and keep the best one", "Remove the section where I was talking about…".
   Or by hand: select text → delete/scissors; pauses are cuttable inline
   markers; Show cuts to review; backspace/revert on struck text restores.
4. **B-roll by description.** Only footage imported under the footage role is
   searchable ("only footage you import here is searchable; your voiceover is
   not used as b-roll"). Three entry points: ask the agent ("Add b-roll of a
   city skyline over the intro"); select transcript text → `Add B-roll` →
   describe; right-click-drag a timeline range → describe, clip fills that
   duration.
5. **Motion graphics.** Prompt the agent ("Create a title card that says
   'Chapter One'", "Make a lower-third with my name and role", "Fade in this
   logo in the bottom-left corner") — it designs the graphic and places it on
   the timeline. Graphics can embed the user's own imported images/video,
   full-frame or overlay. Their docs advise iterating on **one graphic at a
   time**. Or start from a Template and tweak. Manual editing via Properties.
6. **Captions.** Generated from the transcript; a Captions button toggles
   them; default style highlights each word as spoken. **Regenerate Captions
   after a transcript edit preserves custom styling.** Agent restyling is
   open-ended: "single-word captions", "like movie subtitles", "move to the
   top", "add my image of Mario so it jumps on the active word".
7. **Export.** `Export to Video` → presets **YouTube / TikTok-Reels / Web /
   Custom** (custom = resolution + quality), watermark-free. Or hand off:
   XML for Premiere, XML for Resolve, FCPXML for Final Cut — files reference
   original footage rather than bundling it ("you may need to relink").
8. **MCP.** Local HTTP server at `http://127.0.0.1:7433/mcp`, running only
   while the app runs. Auto-registers into Claude Code/Codex on each app
   start, toggleable per agent (Agent Settings → MCP Integrations in
   Terminal). Manual: `claude mcp add daydream --transport http
   http://127.0.0.1:7433/mcp --scope user`. Any HTTP-capable MCP client can
   drive it; external agents get the same toolkit as the built-in chat, and
   the open window stays in sync while they edit.

### The business shell (observed so it can be explicitly not copied)

Free: 1 hr/mo transcription, 1 hr/mo "video processing for search", 100 MCP
tool calls/mo, full editing, unlimited watermark-free exports. Pro $16/mo
annual ($19 monthly): 10 hr / 20 hr / 1M. The metering sits against their own
"your footage stays on your device and is never uploaded" — either the caps
are a pure subscription gate on local work, or derived data (transcripts,
embeddings) leaves for inference. Closed source; not checkable. **The b-roll
metering is a design signal lucid must not copy blind**: hour-metered "video
processing" smells like cloud inference, and lucid's search has to run on
this box instead.

---

## The design system, specified — copy the system, not the assets

The name, logo, and copy text are not copied. Every typeface involved is
open (Geist: OFL; Source Serif 4: OFL; JetBrains Mono: OFL; Inter Tight,
Poppins, PT Mono: OFL), so the system is reproducible by vendoring files, not
borrowing theirs.

### Tokens

Warm paper, from their shipped CSS (`--landing-*`, HSL triplets verbatim):

| token | light | dark |
|---|---|---|
| background | `48 27% 98%` | `48 6% 7%` |
| panel stripe / bg-2 | `48 20% 95%` · `41 19% 93%` | `48 5% 11%` |
| text | `48 14% 7%` | `48 27% 97%` |
| text-2 | `42 5% 27%` | `42 9% 80%` |
| text-muted | `42 4% 51%` | `42 4% 55%` |
| border (hairline) | `42 12% 83%` | `42 6% 18%` |
| border-2 | `42 14% 91%` | `42 6% 14%` |

Radius `0.5rem` everywhere. The app chrome layer under those is stock
shadcn/Tailwind zinc (`240 x% x%` neutrals) — the *warmth lives in the
surfaces, not the widgets*. Accent colours are functional, not brand: one
blue for selection/playhead, green checks, red destructive.

The current page's cool slate (`--bg: #14161a`, `--ink: #dfe3ea` in
`src/lucid/web/app.css`) is what this replaces. **The warmth is the look.**

### Typography — three voices, six families observed

Roles, which is what gets copied:

* **UI and body:** Geist Sans (fallback: `ui-sans-serif, system-ui`).
* **The accent voice:** an *italic serif* for exactly one emphasized word or
  phrase per heading — Source Serif 4 ("polished *video*.", "Questions,
  *answered*.", "collaborating"). This single move carries most of the brand.
* **Numeric/mono:** JetBrains Mono (they also load PT Mono) for timecodes,
  word indices, keyboard hints, and the editorial numbering — capability
  cards `01`–`07`, FAQ items `Q.01`–`Q.07`, step numbers `0 1 / 0 2 / 0 3`
  on the SEO pages.
* In-app graphics additionally load Inter Tight and Poppins — template/
  caption fonts, not chrome; irrelevant until the graphics work.

Vendor the three main families as woff2 under `/static/` — the web UI has no
build step and a `default-src 'self'` CSP, both of which vendored files
satisfy; no CDN.

### Component language

* Buttons: pill or 0.5rem-rounded, near-black fill with white text for the
  one primary action; everything else quiet outline/ghost on paper.
* Cards and panels: hairline borders, generous whitespace, very low-contrast
  section stripes; subtle backdrop blur on the sticky nav.
* Numbered labels in mono ahead of section titles (the editorial voice).
* Agent feed: prompt in a bordered rounded bubble; tool progress as
  checklist lines with green checks; result as plain prose; muted mono
  keyboard hints in the composer.
* Timeline: pastel clip blocks (rose / mint / lavender / powder-blue at low
  saturation), filmstrip thumbnails on video clips, clip filename labels,
  sticky track headers with lock/visibility, thin ruler, single accent-blue
  playhead.

### Motion

In-app motion is restrained to the point of austerity: a blinking cursor
(`steps(2)` at 1 s), a 0.5 s linear spinner, accordion open/close — that is
essentially the observed inventory (`hero-anim-blink`, `hero-anim-spin`,
`accordion-*`, `wall-rise`/`wall-scroll` for the testimonial wall). The
spectacle lives on the marketing page as scroll-driven choreography of mock
app panes. **Do not import marketing motion into the tool** — in the app, the
moving element is the edit itself.

### The marketing pattern worth stealing, the day lucid wants a page

The homepage hero is not a video: it is a **live HTML replica of the editor
performing an edit as you watch** — words type in, the agent checklist ticks,
the playhead moves, the duration drops 06:10 → 04:52 as cuts land. Three more
section-sized mocks repeat the trick (a terminal wired to the timeline, the
Show-cuts sequence, a motion-graphics prompt becoming the finished graphic),
then numbered capability cards, an examples wall, testimonials, pricing, FAQ.
lucid's workspace is already HTML: **a scripted demo mode of the real page
beats a mock** — the replica would be the product, not a copy of it.

---

## The parity map

"Built" is grounded in shipped code (`src/lucid/web/`, `ops.py`), not in the
sections that planned it. Order of work is § Build order at the end; this map
is the inventory with design detail per row. Cite rows by feature name.

### Workspace shell — built; the gap is the look

Three panes over a full-width timeline: built (PLAN.md § Tier 3 is the
goal). The retheme is § The design system above, applied to
`src/lucid/web/app.css`'s existing custom properties — the variables are
already the single point of change (`--bg`, `--ink`, `--panel`, `--line`,
lane colours). Work items: the warm token set in light **and** dark (the
page is dark-only today; the token rework makes the second theme a media
query plus a toggle), vendored fonts, the three type voices applied
(mono for every timecode and word index, serif accent available for any
future headings), top-bar layout to match (project name left, Export right,
theme toggle).

### Agent panel — built, same mechanism; cosmetics remain

The mechanism is already identical by convergence: a local `claude`
subprocess with tool-use streamed to a checklist (PLAN.md § The agent panel,
in mechanism — the security flags there are settled and do not reopen here).
Remaining, all cosmetic, none touching the boundary:

* **Model label** in the composer — read from the stream-json `init`
  message's model field; no new endpoint.
* **Per-turn thumbs** — a small POST that appends to a project-local log.
  Useful only if something reads it; build the log, defer any use.
* **`@`-mentions of assets** — completion over the project's `media/`
  entries; inserts the media name into the prompt text. Pure composer sugar;
  the agent already reaches media through the tools.
* `Start New Task` = clear conversation (fresh subprocess turn), which
  exists conceptually; needs only the affordance.

### Transcript document — built; two gaps

Paragraphs, show-cuts with strikethrough, selection → floating toolbar: all
shipped. Missing against Daydream:

* **Inline pause markers.** Render `[1.2s]` between word spans where the gap
  between one word's end and the next word's start exceeds a threshold
  (theirs show down to 0.4 s). The CLAUDE.md duration rule applies exactly
  here: whisper inflates a word's duration to swallow a retake, which makes
  a *gap* computed from word boundaries **under**-report, never over-report
  — a suppressed marker is cosmetic, an invented one would be a lie. Same
  logic as the `paragraph` field's silence arm; derive both from the same
  place. Markers must be selectable-with-text so cutting a phrase cuts its
  trailing pause, which is what Daydream's docs show.
* **Restore one cut.** Today only `undo` walks the stack. `Edit` stores its
  removed ranges, so un-removing a *specific* range is a real op
  (`restore`?) with CLI + MCP parity and the standard `plan=True` echo.
  Show-cuts already renders the struck text to anchor it on. Small, and it
  completes the loop their docs call "review and restore your cuts".

### Timeline — V1/A1/CC built; polish now, lanes later

Shipped: lanes as projections, waveform canvas, zoom, ruler. Rides the look
pass: pastel clip palette, clip filename labels, sticky headers. Two items
with real (small) machinery:

* **Filmstrip thumbnails** on V1 clips: ffmpeg frame-samples per clip,
  cached like waveforms (`cache/thumbs/`, keyed media size+mtime); drawn
  through the edit the same way the waveform maps timeline→source slices.
  Waits on a project with real footage — same gate as the preview proxy.
* **Snap and link toggles, lock/visibility per lane**: deferred until there
  is more than one *real* track to lock or link — meaningful post-layered
  timeline, decorative before it.

V2/A2 and everything that fills them: **gated on the layered timeline**
(PLAN.md § The layered timeline), whose build-order step *the picture lane in
the web UI* is the single legal point where the view widens. That gate is
absolute — the export degrades silently rather than failing, so a lane drawn
early produces a beautiful window and a wrong file.

### B-roll by description — the biggest new subsystem, design before build

Daydream's flow to copy: imported footage is indexed ("watched"), then
searched by natural-language description, placed by the agent or from a
transcript selection / timeline range. lucid has the placement substrate
coming (cues) and one primitive (`spot_frames` samples frames); it has **no
indexing and no search**, and Daydream's own metering suggests theirs is
cloud inference — the one part that must not be copied blind.

The local design space, to be costed in its own note before any build:
frame-sample each imported clip (the `spot_frames` machinery generalises) →
describe or embed frames **on this box** → store per-clip descriptions in
the project → search is either embedding similarity or, simpler and very
lucid-shaped, *the agent reads the descriptions* — they are text, and the
agent is already in the window. The second option needs no model runtime at
all beyond whatever wrote the descriptions (which could itself be the agent,
once, at import — "watching" as a tool call rather than a subsystem).
Options, costs, and the pick belong in that design note; the wiki's homebase
encoder service (port 8765) is on the checklist as possibly-relevant compute.
Strictly after the picture lane — placing b-roll the export can't render is
the standing trap.

### Motion graphics + templates — after the picture lane, design first

The worked prior is already in the repo's history: the Scream assembly's 13
cards are pre-rendered stills placed as cues and rendered by `melt`. Motion
graphics generalise exactly that mechanism: **the agent authors an asset
(SVG/HTML → rendered still or short clip), the asset lands as a cue on the
picture track, `melt` composites it** — full-frame or overlay. Templates are
a starter library of those assets with editable text/colour slots, which is
also what makes a Properties pane meaningful later. Their docs' advice
("iterate one graphic at a time") is a prompt-guidance line, free to adopt.
Needs a short design note (asset format, where generated assets live in the
project, animation — static cards first; animated later via melt affine/
kdenlivetitle or ffmpeg-rendered clips).

### Captions — generation built; styling is the gap

lucid generates timeline-mapped captions (HISTORY.md § Captions came out of the
timeline). Daydream adds: word-highlight as the default style, agent-driven
restyling (font, colour, position, per-word animation), regenerate that
**preserves styling** across transcript edits. Design: a caption-style object
in the project (separate from caption *content*, which is derived — that
separation is what makes regenerate-preserving-style true by construction),
settable via an op the agent calls, rendered in the preview overlay, burned
in at export (ASS subtitle styling through ffmpeg covers font/colour/
position; per-word animation is an export question to cost in the same
note).

### Aspect swap 16:9 ↔ 9:16 — after the layered timeline

Touches the model (a project aspect/resolution property), both render paths
(auto-editor args on the single-source path, the MLT profile on the
multi-source path), and the preview letterbox. Small design note first;
mechanically modest after the MLT writer exists.

### Export presets — cheap, anytime

YouTube / TikTok-Reels / Web / Custom map onto `ops.export`'s existing
arguments as named bundles surfaced in the window's Export flow and the CLI.
An afternoon; rides any pass that touches the export dialog.

### MCP over HTTP — optional, unranked

Daydream's always-on local HTTP server is what lets an *already-running*
editor be driven from outside. lucid's MCP is stdio (a client spawns its own
server). The MCP SDK v2 supports HTTP transport; `lucid web` already owns a
port and the Host-header guard. Worth doing the day two clients need the
same live project; not before.

### Import roles + assets pane — rides the b-roll design

`import` and `attach-transcript` exist; the role split (transcribe-me vs
index-me) only means something once indexing exists, so it lands with the
b-roll design, as does any assets pane in the left rail.

### Multi-project — late, small

`lucid web` serves one project per process; Daydream's breadcrumb implies a
project list. A picker page over a `--root` scan covers it. Nothing blocks
on it.

### Properties pane — only when graphics exist

Deliberately removed from the workspace in favour of the agent feed; returns
when there are graphics with text/colour/transform to inspect, i.e. after
motion graphics.

### Languages — expected free, verify once

Whisper is already multilingual; run one non-English clip through the full
path (transcribe → cut → captions) before claiming the row.

### Local & private — already stronger; hold the line

No metering, no account, nothing leaves the box, and the b-roll design above
is constrained to keep it that way. This is the row where lucid is ahead,
and the README's pitch depends on it staying asterisk-free.

---

## What parity does not import

* **Metering, accounts, sign-up, cloud.** PLAN.md § Non-goals holds.
* **The desktop shell.** PLAN.md § Not a desktop app — unchanged; wrap the
  finished page in `--app`/Tauri later if chrome is ever wanted.
* **Premiere / Resolve / FCP XML exports.** No such apps exist on a Linux
  box; the OpenChatCut trial measured the handoff ceiling (HISTORY.md § First
  milestones). Kdenlive MLT stays the handoff.
* **Codex as a second agent.** The panel speaks the installed `claude`; a
  second CLI is a config problem for the day someone has one.
* **Cloud-shaped inference for b-roll search.** Local design or nothing.
* **Marketing motion in the tool.** The replica-hero pattern is for a future
  landing page, not the workspace.

## Build order

Governed by two facts: **the layered timeline is the enabler for most of the
map** (b-roll, graphics, V2 — all illegal to draw before its picture lane),
and **the look pass is the one big item gated on nothing**. PLAN.md § Direction and order owns
where this queue sits against non-parity work; the verified bar for every UI
item is unchanged — real Scream VO, real browser (wiki `tooling.md`
§ Headless browser).

1. **The look/feel pass** — warm tokens light+dark, vendored fonts, three
   type voices, pastel timeline, top-bar parity; plus the small items that
   ride it: model label, thumbs, `@`-mentions, inline pause markers,
   `restore`, export presets.
2. **The layered timeline, steps 1–6** (PLAN.md § The layered timeline) —
   already Next; ends with the picture lane, the legal gate for the rest.
3. **Caption styling** — the style object, agent-settable, burn-in at
   export.
4. **Motion graphics + templates** — design note, then agent-authored assets
   as cues; Properties pane follows once there is something to inspect.
5. **B-roll by description** — costed local design note first, then
   indexing, search, and the placement flows (agent / transcript selection /
   timeline range).
6. **The long tail** — aspect swap, import roles + assets pane,
   multi-project picker, HTTP MCP transport, thumbnails/snapping/lock as
   their gates clear.
