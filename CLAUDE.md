# lucid

Architecture, stack decisions, and open questions live in [PLAN.md](PLAN.md).
The build order and the rationale behind it is PLAN.md § Direction and
order. The competitor/dependency survey behind those decisions is in
[PRIOR-ART.md](PRIOR-ART.md). The dated record of what shipped and what the
evidence said — including the first real video's findings — is
[HISTORY.md](HISTORY.md). The Daydream parity plan — the product observed,
its design system, the feature map and its build order — is
[DAYDREAM.md](DAYDREAM.md). Open-item status lives in the wiki, not here.

## Things that will bite you

Each is a case where the training prior is confidently wrong. Check the
installed package or the upstream repo, not your memory.

- **The MCP SDK is v2. `FastMCP` no longer exists** — it is `MCPServer`, from
  `mcp.server` (and there is no `mcp.server.fastmcp` module). Training priors
  overwhelmingly say `FastMCP`; check the installed package before writing
  server code, not your memory of the API.
- **auto-editor is Nim, and PyPI is stale.** `pip install auto-editor` gets
  29.3.1; upstream ships 31.x. There is no Python API — shell out to the binary,
  like ffmpeg.
  - **31.x gates multi-*source* timelines behind a paid key, and the render
    path degrades to 720x576 with a warning and **exit 0** rather than
    failing.** Track count is free; two distinct `src` files is the wall.
    HISTORY.md § The multi-track costing spike.
  - **That gate is auto-editor's, not this box's — don't design around it.**
    **Single-source goes through auto-editor; multi-source generates MLT and
    renders through `melt`**, which has no source-count gate. `melt`'s own
    three traps all produce output rather than an error: HISTORY.md § 4.
    PLAN.md § The layered timeline.
  - The writer is `mlt.py`, and `export` picks it **from the project** — a cue
    table, a second clip_id on the edit, or a `canvas` override — never from an
    argument, because the failure it routes around is silent. Positions in it are frame
    integers, `out` is the last frame *index*, and every declared length is
    read back off the finished document by `mlt.declared_frames` before it is
    returned: melt renders to the longest one it finds. HISTORY.md § The MLT
    writer.
- **Whisper is a subprocess, and it is not on PATH.** Do not `import whisper` —
  go through `asr.transcribe()`, which resolves the binary via `LUCID_WHISPER`
  → PATH → a sibling venv. It is openai-whisper, not faster-whisper, whatever
  PLAN.md's older tables say. Why it is not an import: `asr.py`'s docstring.
  - **`describe`'s vision model is the same shape, and lucid's venv has no
    torch either** — `LUCID_VLM` names an *interpreter*, and `_vlm_worker.py`
    ships in the package to be run by it, never imported. HISTORY.md
    § `describe`.
- **`claude -p` stream-json output requires `--verbose`, and the
  allow/disallow-tools flags do not gate built-in tools.** Without
  `--verbose`, 2.1.226 errors and **exits 0** with empty stdout; a built-in
  tool named in neither list just runs, unprompted — `--tools ''` is what
  actually confines the agent panel to lucid's MCP tools. Both verified by
  reproduction. PLAN.md § The agent panel, in mechanism.
- **OTIO's edit algorithms are C++ only.** `overwrite`/`insert`/`trim`/`slice`/
  `ripple`/`roll`/… have no Python bindings; `opentimelineio.algorithms` gives
  you only trimming, flattening, and transition expansion. Cutting means
  hand-rolled track surgery over Track/Clip/Gap and `source_range`.

## Conventions

- Every MCP tool gets a matching `lucid` CLI subcommand. The CLI is how the
  same operation gets scripted and debugged without an agent in the loop, so
  parity is a feature, not overhead.
  - **Register tools with `@_tool()`, never `@mcp.tool()`** — it is what
    routes `path` through the `-C` binding. A tool registered the way every
    prior expects works, advertises an identical schema, and is silently
    unconfined; a test asserts against it. HISTORY.md § Binding the agent's
    MCP server to its project.
- Tests exercise the real server process over stdio (`tests/test_server_stdio.py`),
  not just the tool functions. Unit-testing a tool body proves nothing about
  whether it is registered or reachable. Same discipline for the web UI:
  `tests/test_webui_http.py` speaks HTTP to a real socket, because a handler
  called directly proves nothing about routing, Range, or the guards.
- **The web UI (`webui.py`, `web/`) is a third client, never a third
  implementation.** It draws and it plays; it never decides — every mutation
  posts to the same `ops` function the CLI and MCP call, and the panel renders
  that function's own return value. It also binds loopback **and** checks the
  `Host` header **and** requires `application/json` on mutations; loopback
  alone does not guard a server that can rewrite your edit. HISTORY.md § The
  preview/timeline web UI.
  - **`_revision` watches the manifest as well as `project.otio`** — the cue
    table and the caption style live there and touch no timeline, so an otio-
    only revision leaves an open window drawing a stale lane.
  - **Timeline lanes are projections of one `Edit`, not tracks. Never draw a
    lane `export` cannot produce** — the multi-source render degrades silently
    (see auto-editor above), so the window would look right and the file would
    be wrong. The view widens when the model does, never ahead of it.
    PLAN.md § Tier 3 is the goal. The picture lane (V2) is **drawn as of step
    6**, and only because step 5 made `export` able to render it.
  - **The palette lives once, as `light-dark()` in `app.css`'s `:root`, and
    JS must never read a colour token.** `getPropertyValue('--x')` returns
    literal `light-dark(…)` text, which `fillStyle` **silently ignores** —
    right in one theme, black-on-black in the other. Give the element a real
    `color` and read `getComputedStyle(el).color`; a canvas also needs
    `theme.js`'s `lucid:theme` event to know to repaint. HISTORY.md § The
    look pass.
  - **The picture lane draws `timeline_view`'s `shots` — the projection
    *already through `mlt.plan_picture`* — never `build_shots` directly.** The
    two disagree: `plan_picture` refuses a shot longer than its asset, so the
    raw projection would draw one `export` rejects. A refusal from either
    arrives as `shots_error` for the lane to draw, never as an exception.
    HISTORY.md § The picture lane.
    - The **preview** layer reads the same array, and one more field off it:
      `src_start` is where inside its asset the shot reads, so a clip used
      three times previews from three places. Reloading each asset from its
      head looks right and is a different film. `player.js` § the picture layer.
  - **`#frame` is the project canvas, and media is *placed* in it, never
    fitted.** Every layer draws inside that one rectangle, and each element
    goes at `timeline_view`'s `reframe[clip].dest` — the writer's own
    `dest_rect`, scaled — so the preview crops where the render crops. Fitting
    to the media's aspect draws footage `export` drops; so does `contain`ing
    it in the canvas, which adds bars the render has not got. A **still** is
    the exception and keeps `contain`, because that is what MLT does to one.
    Nothing in JS derives a crop. HISTORY.md § The viewer's frame.
  - **Verify the picture layer by canvas readback, never by screenshot** —
    headless Chrome does not composite `<video>` into a capture (wiki
    `tooling.md` § Headless browser). Compare against ffmpeg's frame at the
    source timestamp the page claims. HISTORY.md § The preview picture layer.
    - **A readback proves neither that the frame is current nor that anyone
      can see it** — `drawImage` obliges on a mid-seek and on a
      `visibility: hidden` element alike, and both cost this repo a day. What
      to gate on, and the calibration that catches it: wiki `tooling.md`
      § Headless browser. What they cost here: HISTORY.md § The viewer's frame.
  - **A `<video>` that cannot decode fires one contentless `error` and shows
    black**, which is exactly what a black frame the edit meant looks like.
    Never infer the reason in JS — `media.playability()` behind
    `/api/preview/<asset>` has it, and three of its four refusal classes pass a
    naive codec-name check.
- **Anything taking a word index echoes the words it resolved to, plus the
  three either side.** The neighbours are the point: an index one past the
  intended phrase reads correctly on its own. Mutating tools also take a
  `plan` that resolves without writing. HISTORY.md § `cut --plan`.
- **Cite roadmap items by name, never by number** — the numbers renumber on
  every ship, and four things once cited "item 1" meaning four different
  items. Point at the named PLAN.md or HISTORY.md `##` section instead. PLAN.md § Direction and order.
- `ruff check` is the lint gate. **Never run `ruff format`** — there is no
  ruff config, so it applies its own 88-column default against this repo's
  wider lines and rewrites 26 of 30 files, burying whatever you actually
  changed.
- **`Project.open` refuses an old manifest and must never migrate one** — it
  backs `info` and `status`, so a read would rewrite a project someone only
  looked at. Migration is explicit (`lucid migrate`), and a schema bump adds a
  step to `_MIGRATIONS` — keyed by the version it migrates *from* — rather
  than widening `open`. HISTORY.md § The schema migration. **The schema is at
  4**; v4 added `cards`.
  - **An additive *optional* key does not bump** — `caption_style` and `canvas`
    are absent-means-what-every-older-manifest-meant, and a bump would make
    `open` refuse every project on disk to gain nothing. Both bumps so far were
    for list keys another op would `setdefault` anyway, where the number is
    what makes the key true rather than incidentally survivable.
- **A footage description indexes the source, so no edit can invalidate one** —
  `(clip_id, src_start, src_end, text)` in *source* seconds, and there is
  deliberately no re-describe hook. Windows are never *widened* — a whole-clip
  pass described six frames as six people — so `plan_windows` rounds the count
  up, never to nearest. PLAN.md § B-roll by description.
  - **A cue's `src_start` pins the in-point: a pinned shot refuses rather than
    rewinds.** `plan_picture` rewinds an unpinned cursor that would overrun —
    right for a re-use, a silent wrong-video for a placement. In a shot dict
    the cue's ask is **`src_pin`** and the planner's answer is **`src_start`**;
    one key for both reads as correct in every test that has a pin in it.
    **A derivation is where this bites hardest, because it empties the
    cursor**: `reel` drops the cues it cut, so every survivor replays its asset
    from the head and the reel's picture is *not* the film's picture over the
    same seconds. Pin them to the film's own in-points to excerpt faithfully.
    HISTORY.md § The pinned cue, § The framing control.
  - **A description does not choose the clip — `synopsis` does, and lucid does
    not choose at all.** Which footage goes under a sentence is never a lexical
    match: measured against 25 human picks, the description index agreed 2
    times and the clips' own *filenames* 3, so a better `describe` prompt was
    the wrong fix. `synopsis` is one line per clip saying what the footage
    *is*, allowed to carry what no camera can see, and `broll_brief` hands it
    plus the narration to whatever is reading — which writes back through
    `cue_add`. **A second reviewing pass was measured and is worse (13 → 10);
    do not add one.** HISTORY.md § Choosing the b-roll.
- **A cut cannot invalidate a cue and can still orphan one, and `build_shots`
  refuses the whole projection on a single orphan.** Word-indexing is what
  keeps a cue *valid* across cuts; it does not keep the word on the timeline.
  Ordinarily that refusal is right — someone cut the line a picture hung on —
  but anything removing material wholesale hits it at scale: `reel` orphaned 34
  of 38 cues, and the derived project opened, passed `status` and rendered
  nothing. So a derivation prunes and **names** what it pruned (`cues_dropped`),
  each entry being a picture the result will not have. HISTORY.md § `lucid
  reel`.
  - Its sibling: **`cut_by_time` flags every suspect-duration word a removed
    span overlaps, not the ones at the boundary.** Right for an ordinary cut,
    noise for a wholesale one — 15 flags on a reel, none near either edge — so
    `reel` asks about the edges it *keeps* instead. A guard that has to be
    suppressed every time is the thing to fix, not to document.
- Resolve media through `media.media_path()`, never `root / clip["media"]`. A
  `media/` entry is optional — the NAS rejects symlinks, so import falls back to
  referencing the source in place (wiki `files.md`).
- **Trust a transcript's word order, never its word durations.** Whisper hides
  a whole retake inside the duration of the word after it. So "did this word
  survive?" is an *overlap* test against the kept ranges, never containment —
  partial survival is normal. HISTORY.md § 2.
  - The trap when *masking audio* with a word map: an inflated duration covers
    the retake it swallowed, so believing it hides exactly the hole you are
    looking for. Trim spans through `energy.believable` first. HISTORY.md § `verify --windowed`.
  - **A retake seam also *adds* words** — whisper reads across the splice and
    interleaves both takes — **and the tell is that the word starts before the
    one ahead of it ends, never that it reads wrong.** Reading for sense removes
    the nonsense ones and leaves every grammatical one standing; nine were in
    44s of the Scream VO, and `transcript.find_overlaps` finds **40 seams in the
    whole film**. Overlap-scan anything derived from a transcript before it is
    drawn. HISTORY.md § The hand-framed teaser, watched.
    - It rides both attach paths as `overlaps`; a finding is computed at attach
      and returned once, so `transcript-checks` is how an older project asks
      again. **Seams, never pairs, and deliberately unthresholded** — a floor is
      the obvious improvement and it is wrong twice over. HISTORY.md § The
      overlap scan.
- **A frame count comes from `autoeditor.frame_layout`, never from the
  duration.** Each segment edge quantises on its own, so `sum(dur)` and
  `round(edit.duration * fps)` are different numbers and the first one is the
  timeline that gets exported. Related, and measured rather than assumed:
  auto-editor's `--export kdenlive` output is **one frame longer than your
  edit, and the frame is black** — MLT's `out` is frame-inclusive and
  auto-editor writes a frame count into it. `export --render` does not have it.
  HISTORY.md § `check_frames`.
- **`melt` is inside the Kdenlive flatpak, and that flatpak cannot see
  `/tmp`.** It has no host package here; resolve it through
  `picture.melt_command()`. Pointed at a project under `/tmp` it prints
  `Failed to load` and **exits 0**, so its exit code proves nothing — check its
  output. Anything writing a project for melt to read puts it under `$HOME`,
  and that includes what it *writes*: `picture.render` stages into
  `~/lucid-render/` and copies out only after the file agrees with the timeline.
  - **`WAYLAND_DISPLAY` alone is not a display.** It names a socket that Qt
    resolves under `XDG_RUNTIME_DIR`; with only the name, melt aborts printing
    nothing and the empty output reads as an unloadable project. Go through
    `picture.display_env()`, which exports both — and note the environment it
    is compensating for is the **MCP stdio transport's**, which passes HOME,
    PATH and little else. HISTORY.md § Rendering through `melt`.
- **A caption's look is project state (`caption_style`), and ASS is never
  written by hand** — three of its fields mean the opposite of what they read
  as, `\k` is a left-to-right fill rather than a per-word step, and grouping
  is part of the look, so it is stored with it. `captions.resolve` is the only
  translation and `ops._caption_cues` the only derivation. HISTORY.md § Caption
  styling has each trap and the measurement behind it.
  - **`caption_style` says what a burn *would* draw, never that one happened.**
    `export --render` does not burn captions; `captions --burn` is a separate
    opt-in step and nothing reports a render made without it. So a manifest,
    `caption-view`, `verify` and `check_frames` can all agree about captions
    that are not in the file — the finished cut carried none for three days on
    the strength of a status line. Settle it by reading the render's pixels.
    HISTORY.md § The film had no captions in it.
    - And a legible one is a further question: over the light cards white
      captions measure **1.10:1**, held together only by the outline, while
      `verify` stays clean because the render does match the timeline. A box
      (`--box`) buys 20.87:1 and costs clean edges, since libass draws one box
      per override block and `\k` makes one block per word.
  - **The font named in a style may not be installed** — libass substitutes
    silently and ffmpeg still exits 0, and **a card's SVG has the same hole**:
    it rasterises pixel-identically whether the face exists or not.
    `captions.font_match` reports both; nothing prevents either. Which fonts
    this box has: wiki `tooling.md` § Fonts.
    - **CSS weights are not fontconfig weights** (its Bold is 200), so an
      unmapped CSS value is above every real one and every query answers the
      heaviest face installed — go through `CSS_TO_FC_WEIGHT`, and escape the
      family, because `fc-match 'Foo-24'` reads the tail as a point size and
      calls a missing face installed. `font_report` does both and reports
      `drawn_style`, since two faces of one family share a family name;
      `captions.font_match` asked bare does neither, deliberately (libass takes
      a bold *flag*, unmeasured here). **Settle which face draws by measuring a
      render, never by `fc-match`.** HISTORY.md § The emphasis-capable quote
      slot.
- **Cards rasterise through `magick`, and the size knob goes *before* the
  input.** `-size` is a vector render and **fits, never distorts**; `-resize`
  after the input resamples the pixels and wrecks text, so `render_svg` has no
  resize path and a card is *authored* at the canvas — which is why `card_new`
  defaults its canvas to `_mlt_resolution`. Never hand melt the SVG: it goes
  through Qt, not librsvg, and the two disagree with no error on either side.
  Templates escape every user value and insert only lucid's own markup raw.
  HISTORY.md § The card renderer, § Card templates.
  - **A wrap is measured or there is no wrap** — `fill_template(flow=True)`
    renders each candidate through `render_svg`'s own coder, `flow=False` is
    the older newline-only contract, and a character count is unsafe in the
    one direction that overflows. The two traps are in the *measuring*: the
    scratch canvas is the entire cost of it, and it **clips rather than
    errors** when too small — a clipped line measures narrower and ends the
    wrap early. A slot that overruns its box is **refused; the card never
    grows to fit it.**
  - **Per-run `<tspan>`s eat the whitespace between them**, so `the
    [em]perfect[/em] horror` draws as `theperfecthorror` at exit 0.
    `xml:space="preserve"`, once per line — it inherits. Both:
    HISTORY.md § The emphasis-capable quote slot.
  - So **a card is re-authored, never resized**: `card_new` records
    `(template, slots, canvas)` and `card_reauthor` fills the template again
    at the project canvas. A card with files but no record cannot be
    re-authored by anything — it is reported, never guessed at. The twelve in
    `~/lucid-final-cut/proj` have no record, **but their slot tables survive in
    `~/lucid-cards-reauthor/`** — look there before concluding a card is
    unrecoverable. All twelve author at 9:16; the two that refuse are a
    16:9-only content fit. HISTORY.md § The card record, § Step 6 of the aspect
    swap, watched.
- **Footage follows a canvas change by cropping, and the crop is a rect in
  *source* pixels stored as asked** — refit whenever the canvas moves, so
  neither a cut nor a swap can invalidate one. **A rect is addressed
  `(clip_id, src_start, rect)`, so framing is per *shot*, not per clip** —
  `src_start` absent is the window from the head of the file, which is what
  every older rect meant, so it is not a schema bump. It renders as **discrete
  (`|=`) keyframes on one `qtblend` filter, numbered in the producer's own
  source frames** — one node per resource per role still, measured. And the
  reviewing tool is not optional: a wrong window **reads as framing in
  motion** (2 of 15 hand numbers, twice now), so judge one on
  `reframe_sheet`'s drawn-on-the-source-frame tiles, never on a watch.
  HISTORY.md § Per-shot framing.
  - Its two asymmetries: the **preview** places a shot by the window at its
    `src_start`, so a boundary *inside* a placement previews as the first of
    the two while the render steps mid-shot correctly (`reframe_sheet`'s
    `windows` count is the tell); and `timeline_view`'s `reframe[clip].dest`
    is the **head** window, which is the edit track's answer — the picture
    layer draws the shot's own `dest` and reading the clip entry there is the
    bug. An override is a **floor**: a
  rect that is not the canvas's shape is grown to it, never shrunk into it,
  because shrinking cuts the subject in half. **A still is never cropped** (a
  card is re-authored) and no filter is emitted where MLT's own placement
  already matches — which is what keeps an unswapped project's document
  byte-identical. The trap is that `mlt.py` writes one node per resource **per
  role**, so a reframe applied per resource crops a file on one track and
  letterboxes it on the other, in the same frame, at exit 0. HISTORY.md § The
  MLT reframe.
  - **An export preset never sets the canvas — `tiktok-reels` *checks* it and
    refuses.** The obvious build is the wrong one: a flag that reshapes the
    project is an export argument rewriting project state, the same failure as
    picking the writer from an argument, and it leaves a swapped manifest
    behind after a render nobody kept. `PRESET_ASPECT` is a claim a preset's
    *name* makes, tested cross-multiplied against `_mlt_resolution` (a float
    ratio refuses the one shape that is exactly right), and an audio-only
    project is refused *before* it, or the message quotes the 1080p fallback
    as if it were the project's frame. HISTORY.md § `tiktok-reels`.
  - **A brightness bbox answers "where is the bright part", never "where is
    the frame."** It has now misread the same render twice — once as worse
    than a pillarbox, once as a pillarbox — because the footage sampled was a
    dark scene and then opening credits on black, and a black *source* reads
    exactly like a black *bar*. Settle frame geometry by comparing against
    ffmpeg's own crop of the source, and against the wrong hypothesis too:
    0.9 vs 20.8 of 255 is an answer, either number alone is not. **As a
    *framing* signal it is worse than not asking** — scored against the
    approved windows the luma centroid loses to the centre crop it would
    replace (0.545 against 0.568), and loses a subject too. Faces are what
    beats it. PLAN.md § The auto-framing detector.
  - **`reframe_detect` proposes and never frames**: `apply` is off by default,
    the opposite of `cut --plan`, because the pass is 114px out on a 459px
    window and 2 of 15 hand numbers were wrong invisibly — judge it on
    `reframe_sheet`. It never writes over an existing override, and it is the
    *third* subprocess-behind-an-interpreter (`LUCID_FACE`, with
    `_face_worker.py` shipped to be run and never imported). Two traps, both
    found by running it on the film rather than by a test:
    - **"Is this window already framed?" is a frame, never an epsilon.** ffmpeg
      reports a cut at 0.834167 where the manifest holds 0.8342, so exact match
      called 15 of 16 hand windows unframed *and printed both as `0.8342`*.
    - **A refused window is not a centre-cropped one.** Nothing is written for
      it, so whatever is in force carries over — at a clip's head the centre
      crop, anywhere else **the previous shot's framing**, which is worse than
      the default because a stale window looks deliberate (4 of the film's 8).
      `falls_back_to` names which; never infer it from `refused`.
    HISTORY.md § The auto-framing detector, built.
- Anything that emits times *for playback* maps through the edit, never
  straight off the transcript. The transcript indexes the source; the timeline
  is what plays. See HISTORY.md § Captions came out of the timeline.
  - Singular vs plural: `Edit.timeline_span` stops at the first survivor
    (right for captions — one span per word); `Edit.timeline_spans` returns
    every surviving piece. A range a cut split has more than one answer, and
    the singular reports one without saying so. HISTORY.md § `locate`.
  - **Segments are half-open `[start, end)`, and that is wrong for exactly one
    thing: a zero-width word.** Whisper emits `start == end` often, and the
    last word of a transcript lands on the last segment's own end — where the
    half-open test says "cut" about material plainly still there. `closed_end=`
    on `timeline_time` is for *instants* only; passing it for one edge of a
    range double-counts the join between two segments. HISTORY.md § The head
    of the parity queue.
- **`Edit` never stored what it removed** — it is surviving segments and
  nothing else, so "what was cut" is derived (`Edit.gaps` against the clip's
  registered duration), never read back. `restore` is bounded by those gaps,
  which is what keeps the timeline a subset of the source and separates it
  from the parked `vo_extend`. PLAN.md § Parked.
  - **A dogfood project can be the wrong cut while every check passes.** The
    Scream project held the *silence-cut* VO, not the shipped one — 411s
    against 351s, 72s of retakes — and the render, `verify`, the cue table and
    the shot plan all agreed with it. Before building anything for review on
    one, compare its `timeline_duration` against the film it is meant to be.
    **And carry derived state back off a scratch copy** — the ten card records
    were written on the 411s copy, so the film's own project read as having
    none. Three instances now. HISTORY.md § The VO the project was holding.
