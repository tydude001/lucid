# lucid

Architecture, stack decisions, and open questions live in [PLAN.md](PLAN.md).
The build order and the rationale behind it is PLAN.md § Direction and
order. The competitor/dependency survey behind those decisions is in
[PRIOR-ART.md](PRIOR-ART.md). The dated record of what shipped and what the
evidence said — including the first real video's findings — is
[HISTORY.md](HISTORY.md). The Daydream parity plan — the product observed,
its design system, the feature map and its build order — is
[DAYDREAM.md](DAYDREAM.md). The Studio reshape — the workspace reorganized
around Home/Edit/Frame/Finish with direct manipulation and the truth strip —
is [STUDIO.md](STUDIO.md), which supersedes DAYDREAM.md § Build order where
they conflict. The full command walkthrough that was README.md's body is
[docs/MANUAL.md](docs/MANUAL.md) — moved verbatim 2026-08-19 when README.md
became a short newcomer-facing front door; nothing was deleted in the move.
Open-item status lives in the wiki, not here.

## Things that will bite you

Each is a case where the training prior is confidently wrong. Check the
installed package or the upstream repo, not your memory.

- **The MCP SDK is v2. `FastMCP` no longer exists** — it is `MCPServer`, from
  `mcp.server` (and there is no `mcp.server.fastmcp` module). Training priors
  overwhelmingly say `FastMCP`; check the installed package before writing
  server code, not your memory of the API.
  - **`MCPServer.run()`'s `transport` argument is `Literal["stdio", "sse",
    "streamable-http"]`, verified against the installed 2.0.0** — but calling
    it with `transport="streamable-http"` builds the Starlette app and the
    uvicorn `Config` internally, with no injection point for middleware and no
    way to learn a `port=0` ephemeral port before it blocks. `lucid mcp
    --transport http` builds `streamable_http_app()`'s pieces by hand instead
    — a Starlette app with its lifespan already wired — because the loopback
    guard needs to wrap the app and the bound port needs to be knowable before
    it blocks. HISTORY.md § MCP over HTTP, built.
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
    - **A container with two audio streams renders its first mic and drops
      the second, at exit 0** — the Edit lane's producer carries no
      `audio_index` (the writer emits one only as `-1`, to silence a picture
      node), so MLT picks, and it picks the first. Every check stays clean:
      they compare the render against the timeline, and the timeline never
      knew there was a second stream. **And `audio_index` is the container's
      absolute stream index, not the audio ordinal** — with video at 0 the
      first mic is `1` and the second is `2`, while ffmpeg's own `-map 0:a:1`
      means the second audio. The two numberings agree exactly on an
      audio-only file, which is every fixture anyone writes first. Measured by
      Goertzel readback of a real melt render. PLAN.md § The co-hosted
      recording.
      - **That trap is unreachable from a project now: `import` refuses a
        multi-stream container.** `--mix` sums, `--audio-stream k` keeps one
        (ffmpeg's audio ordinal, *not* `audio_index`), and either writes a
        derived copy to `cache/mixed/` that `media_path()` prefers the way it
        prefers `attenuated` — so **nothing downstream of import ever chooses
        a stream**, and a caller that does is the whole hole.
        `original_media_path` keeps the mixdown too: the untouched original
        of a two-mic container *is* the mixdown. **Judge any of it by tone
        power, never by counting streams** — auto-editor's half of the trap
        passes both tracks through, so the file holds two and everything that
        decodes it takes the first. HISTORY.md § The two mics survive import.
        - **`_reel_media`'s key tuple *is* `media_path()`'s preference
          chain** (`ops.py`, and again in `reel(plan=True)`'s `would_link`);
          a key in one and not the other hands the derived project a path
          with nothing at it. New import guards go **behind** the source
          dedup, or a retried import raises about a choice taken days ago.
        - **A long server message is a control that spends the pane's
          height** — this refusal renders 194px in the assets pane and took
          `#assets-list` from 129px to 0, hence `.asset-status`'s 60px cap.
          The pane complies with the refusal rather than only printing it:
          `media.MultiAudioError` carries `streams`, so nothing there
          string-matches a sentence.
        - **Both path resolvers prefer the mixdown, so the mics are
          reachable only through `media.container_path`** — one caller,
          `ops.attribute_speakers`, and that is the containment. Anything
          else asking for "the original file" wants the mixdown; asking
          `media_path()` for the mics compares it against itself and
          separates nobody, at exit 0.
          - **`attribute_speakers` is at chance on simultaneous speech**,
            measured on one synthetic voice, so `speakers.MARGIN_DB` is a
            reported default and never a threshold to trust — `apply` is
            off by `reframe_detect`'s precedent and keeps a label it
            refuses to replace. HISTORY.md § Speaker attribution, built.
      - **`transcript.Word` has a `speaker`, and it is a label, never an
        address** — `(clip_id, word_index)` still resolves every cue,
        description, mark, music anchor and caption. Additive and optional,
        so no schema bump, and **`Word.as_dict` omits it when unset**: an
        `asdict` would stamp `"speaker": null` onto every word of every
        transcript and rewrite each file on the next save for no change.
- **Whisper is a subprocess, and it is not on PATH.** Do not `import whisper` —
  go through `asr.transcribe()`, which resolves the binary via `LUCID_WHISPER`
  → PATH → a sibling venv. It is openai-whisper, not faster-whisper, whatever
  PLAN.md's older tables say. Why it is not an import: `asr.py`'s docstring.
  - **Both passes hallucinate, and the two rules that catch it are not one
    rule.** `asr.clean` is the entry point and the reason it exists is that the
    windowed path called `_drop_stacked` inline for months while the ingest
    path had nothing. Identical-instant (`STACKED`) and dense-cluster
    (`CLUSTER_WINDOW`/`CLUSTER_WORDS`) each miss what the other catches — on
    the scale spike's own artifact the first drops 3 of 8. **The dense rule
    counts words in a window and never scores a rate**: real speech reaches 50
    w/s over three words, because whisper's durations are not to be trusted.
    Every drop is reported as `hallucinated_words`, never only applied.
    HISTORY.md § The ingest path's hallucination guard.
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
  - **A generated MCP config's `command` is resolved by `claude` against
    *its* PATH, never by lucid — so it names `sys.executable` and
    `-m lucid.cli`, never the string `lucid`.** A bare name is absent from
    PATH for every launch that skips an activated venv (`.venv/bin/lucid
    web`, a desktop entry, what `lucid open` spawns), and the failure is
    silent in the worst way: the harness reports the server `failed` with
    `tools: []`, `claude` runs anyway, exits 0, and answers the prompt in
    prose while the pane's banner still says it reaches the timeline through
    lucid's tools. Measured both ways — 0 tools against 68. `agent.js` now
    draws the init event's `mcp_servers` when lucid is not connected, because
    the next thing that breaks this will break it silently too. HISTORY.md
    § The agent panel had no tools at all.
- **OTIO's edit algorithms are C++ only.** `overwrite`/`insert`/`trim`/`slice`/
  `ripple`/`roll`/… have no Python bindings; `opentimelineio.algorithms` gives
  you only trimming, flattening, and transition expansion. Cutting means
  hand-rolled track surgery over Track/Clip/Gap and `source_range`.

## Conventions

- **A new spike/probe/scratch directory goes under `~/lucid-work/<name>`, and a
  finished one is archived to `~/lucid-archive/spikes/<name>`** — still `$HOME`,
  so melt's flatpak can see both. 29 finished spikes were corralled into that
  archive 2026-08-19 with their names unchanged, so a doc citation of
  `~/lucid-<name>` that no longer resolves is found there. What stays flat at
  `~/` is pinned and must not move: `lucid-render` (`picture.RENDER_SCRATCH` is
  a code literal), `lucid-final-cut` (six manifests point into `proj/`
  absolutely, and its own `reference` render is an absolute self-path),
  `lucid-a2-probe` (a2-build's media), `lucid-archive`, `lucid-cards-reauthor`,
  `lucid-scream-v2`, `lucid-kf-probe`, and the settle-against copies
  `lucid-brief-check` / `lucid-framing-detect` / `lucid-threshold` /
  `lucid-split-detect`. Manifests store absolute paths, so moving any project
  directory means rewriting them — grep its `*.json`/`*.otio` first.
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
  - **Off loopback it is opt-in, and `webui.remote_policy` is the only place
    that decision is made** — `lucid web --allow-remote`, or `--tailscale`,
    which fills its arguments in from this node. Loopback+Host is this
    server's *whole* credential, so widening it **replaces** that credential
    rather than dropping it: the Host allow-list grows to the names the
    operator says clients will present and **never to "anything"**, and a
    token rides every request. **Host is checked before the token**, or a
    leaked token buys a rebinding page in.
    - **The token travels as a cookie, and that is why `web/` has no idea it
      exists.** `?t=` is answered with
      `Set-Cookie: lucid_token=…; HttpOnly; SameSite=Strict` and the page's
      own fetches, media ranges and `EventSource` carry it unchanged — so
      **never thread a token through a JS request**, which is the obvious
      build and puts the credential in as many places as there are calls.
      `SameSite=Strict` is the CSRF half loopback was covering, which is why
      the `application/json` rule on mutations is untouched.
    - `--tailscale` binds the 100.x address itself, never a wildcard, so the
      socket is not on the LAN at all; it **refuses rather than falling
      back**, because one that quietly bound loopback looks like the feature
      working until a phone tries it. A wildcard bind refuses unless told
      what clients present — `server._serve_http`'s refusal, and
      `_WILDCARD_HOSTS` is stated once, in `webui.py`. HISTORY.md § The
      window, reachable from the tailnet.
  - **`_revision` watches the manifest as well as `project.otio`** — the cue
    table and the caption style live there and touch no timeline, so an otio-
    only revision leaves an open window drawing a stale lane.
    - **A job that writes only a transcript file trips neither watch.**
      `ops.transcribe` and `ops.attach_transcript` touch no `project.otio`
      and no manifest, so a finished transcription fires no `project-changed`
      at all — the job's own `done` bus event is the only reload signal a
      client has. Import is unaffected (`ops.import_media` writes the
      manifest). **Reload through the pane bus's `reload` event, never
      `location.reload()`**: the `done` event carries the op's whole return
      value and a page reload throws it away — on the first real
      transcription that was `4 suspect durations`, reported and then wiped
      off the screen. HISTORY.md § Import and transcribe became window
      operations.
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
    - **Where the answer is "which source second is this", build the source so
      every moment names itself** — colour-coded blocks and a burnt-in counter,
      and then one sampled pixel settles it. Used to prove a pinned cue's
      in-point survived into melt, where the *wrong* answer is the clip's own
      opening seconds and so passes every plausibility check there is.
  - **A browser pass driven at CDP's default zero dwell is not a pass** — a
    fix whose transition sits inside a real click's 60-150ms dwell reads green
    at 0ms and is dead at every real speed, which has already shipped here.
    Drive every click at 0ms *and* ~120ms. The harness is
    `.claude/skills/verify-live/` — dwell, hit-tested clicks, drags, viewport
    overflow probes — rather than a fifth hand-rolled one. The measurement and
    the mechanism: wiki `tooling.md` § Headless browser. HISTORY.md § The
    dwell-timing lesson.
    - **So redraw only the node a gesture owns while it is live** — rebuilding
      the container the mousedown landed in removes its target, and Chrome
      then drops the trailing `click` with nothing thrown, which is how a lane
      that re-rendered on mousedown silently stopped seeking. HISTORY.md § The
      cue-drag browser pass, and six defects.
      - **A gesture whose hit target is smaller than `snapTolerance()`
        resolves to nothing and no-ops silently** — a drag clamped to under
        one tolerance never reads as `moved`, so there is no preview, no
        popover, no toast, just a dead drag. Don't offer a gesture on a
        target too small to complete it; on the shipped film's own segments
        the median block was under the threshold that would have made this
        the common case, not the edge one. HISTORY.md § Direct manipulation
        on the timeline.
    - **And scope the probe to the page, never to where the bug is expected** —
      a sweep of `#workspace *` measured clean at every width while `#bar`
      overflowed at 700px with Export and the theme toggle off a hidden edge.
      The window a check looks through is a claim too, and it was wrong in the
      review *and* in the pass verifying its fix. Walk `body *` and compare
      `body.scrollWidth` against `innerWidth`. HISTORY.md § The web UI review.
  - **An author `display:` rule outranks the UA's `[hidden] { display: none }`,
    so `el.hidden = true` does nothing on its own.** Anything this file set
    toggles by `hidden` needs a companion `[hidden]` rule or it is drawn
    permanently — and it reads as deliberate, because a floating panel sits
    where a selection would have put it. It cost both toolbars and the pad
    popover at once, invisible until words became tabbable. `#picture` is the
    one element that already had the companion rule, which is the only reason
    a stray `*/` deleting its whole block was subtle rather than catastrophic.
    HISTORY.md § The web UI review.
  - **A floating panel is clamped by `dom.js`'s `clampFloating`, and there is
    exactly one copy.** The two callers hand it different spaces — the
    transcript toolbar is unscrolled, the cue toolbar has `scrollLeft` already
    folded in — so it takes bounds rather than a container. A second clamp is
    how the first fix reached one of the two toolbars and not the other.
    - **`clampFloating` MOVES a box; it cannot SHRINK one.** A panel taller
      than its container is pinned to the top with its own buttons hanging
      off the bottom — measured at 218px inside a 143px `overflow: hidden`
      box, Apply landing at y 920 of a 900px viewport, where
      `elementFromPoint` returns null. Hit-testable by a synthetic `.click()`
      and by nothing a person can do, which is exactly why nothing caught it
      first. Cap the panel's own height instead. HISTORY.md § Direct
      manipulation on the timeline.
      - **Its sibling: a new control spends the pane's height, out of the
        list below it.** The add-footage form left `#assets-list` 126px of
        613px, so the *second* clip's own button sat outside the scroll
        window — where a rect still reads on-page and `elementFromPoint`
        answers about whatever is painted there instead. Measure what a new
        control leaves the pane; fold away anything used once per asset.
        HISTORY.md § Import and transcribe became window operations.
  - **A `<video>` that cannot decode fires one contentless `error` and shows
    black**, which is exactly what a black frame the edit meant looks like.
    Never infer the reason in JS — `media.playability()` behind
    `/api/preview/<asset>` has it, and three of its four refusal classes pass a
    naive codec-name check.
- **`lucid review serve` (`reviewserver.py`) is a fourth client, on purpose
  not `webui.py`'s guard.** It exists to be reached off the machine (a phone
  on Tailscale), so loopback+Host is replaced by a token every request must
  carry (`?t=`). It is still the right tool for a review round rather than
  `lucid web --tailscale`: no edit surface at all, and a page that needs no
  JS, so the token rides the links rather than a cookie.
  `review add --kind control --baseline <name>` hashes both files and refuses
  the call on any mismatch — the byte-identical-control rule is enforced at
  registration, not left as a comment. Streaming reuses `webui._stream_file`
  (a standalone function, not a second copy of the Range math). PLAN.md § The
  completion queue, item 6. HISTORY.md § `lucid review`, built.
- **`lucid mcp` can serve over HTTP, and the guard is loopback+Host, not a
  token — `webui.py`'s model, not `reviewserver.py`'s.** `--transport http`
  (default stays `stdio`; every existing client spawns the server that way
  unchanged) adds `--host`/`--port`/`--allow-remote`/`--allow-remote-host`.
  `_LoopbackGuard` is real ASGI middleware mirroring
  `webui.Handler._host_is_loopback`, importing `webui._LOOPBACK_NAMES` rather
  than re-stating the fact; it refuses a non-loopback `Host` at startup unless
  opted in, and `-C` confinement holds identically over HTTP.
  - **A wildcard bind's own host string is not a client identity** — for
    `0.0.0.0`/`::` it is backwards in both directions, refusing the real client
    (which sends the address it dialed) and admitting the attacker who sends
    the banner's own `Host: 0.0.0.0`. A wildcard bind refuses under
    `--allow-remote` unless `--allow-remote-host` names the addresses real
    clients will present. HISTORY.md § MCP over HTTP, built.
- **`lucid web --root DIR` serves a picker over many projects, but the process
  still binds to exactly one.** `POST /api/open` is a *one-way* bind — the
  first project picked calls the same `_bind_singletons` that `-C` already
  calls, deferred under a lock, so `bus`/`agent`/`render_job`/`proxy_job` are
  never more than one project's. Two projects at once is still two processes;
  `--root` widens what a picker can list, never what one server can serve.
  `-C` together with `--root` is refused before either binds a socket, and MCP
  is untouched — a client already spawns its own server per project. HISTORY.md
  § The multi-project picker, built.
  - **A picker that raises on one broken project hides every other one.** The
    scan called `ops.status` with no handler, so one init-but-not-seeded
    project 400'd all of `GET /api/projects`; there are now four scan outcomes
    (`ok`/`needs_migration`/`unreadable`/`error`), never an exception that
    takes the rest of the listing down with it.
  - **`Path.is_dir()` follows symlinks, and open-time confinement is too late
    for a listing that already leaked one** — a symlink under `--root`
    pointing outside it was scanned and its metadata returned before anyone
    tried to open it.
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
- **The version is a hand-typed literal in two places and is bumped
  deliberately, never derived.** `pyproject.toml` and `lucid/__init__.py`,
  held together by `tests/test_version.py` — a VCS-derived or
  `importlib.metadata` version reads the *installed* dist-info, so an
  editable checkout reports whatever the last `uv sync` wrote. Bump the minor
  when something new becomes callable, `uv sync` behind it, tag, and name the
  HISTORY.md `##` section in the annotation. There is no `CHANGELOG.md` on
  purpose. HISTORY.md § The version caught up.
- **`Project.open` refuses an old manifest and must never migrate one** — it
  backs `info` and `status`, so a read would rewrite a project someone only
  looked at. Migration is explicit (`lucid migrate`), and a schema bump adds a
  step to `_MIGRATIONS` — keyed by the version it migrates *from* — rather
  than widening `open`. HISTORY.md § The schema migration. **The schema is at
  4**; v4 added `cards`.
  - **An additive *optional* key does not bump** — `caption_style`, `canvas`,
    `tail`, `reference` and a window's `interp` are all
    absent-means-what-every-older-manifest-meant, and a bump would make
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
    cursor**: `reel` drops the cues it cut, so every survivor would replay its
    asset from the head and the reel's picture would *not* be the film's
    picture over the same seconds. So **`reel` pins every survivor** to the
    in-point the film's own plan gave it (`cues_pinned`, and `pins_error`
    where the film cannot project) — 2 of the teaser's 4 survivors needed one,
    and hand-derived reels before this did not have them. HISTORY.md § The
    pinned cue, § The framing control, § The three gaps, closed.
  - **A shot's addressing clip is not its footage.** In a shot dict,
    `clip_id` is the cue's own addressing clip — the transcript track, `"vo"`
    on an audio-only project — and `asset` is the footage actually shown.
    Anything that reaches into a shot by `clip_id` to fetch or thumbnail
    footage reaches the wrong file, or none: the first filmstrip draft
    thumbnailed `shot.clip_id` and every V2 request would have 400'd on this
    project. Caught by reading real `/api/view` data before wiring the
    harness, guarded now by a test named for exactly this trap. HISTORY.md
    § The assets, properties and filmstrip backend, and its panes.
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
  - **Read that list for the cue nearest the head first.** One pruned from the
    far end trims the result; one pruned just outside the *kept* span opens the
    reel on no picture at all — 11 seconds of it on the teaser, reported as one
    line among 35. Move the edge to keep it. The other half of that watch —
    every survivor replaying its asset from the head — is `reel`'s own job as
    of § The three gaps, closed; **a reel derived before it has unpinned cues
    and is a different film**, so check `cues_pinned` on anything older.
    HISTORY.md § The teaser, re-cut.
  - Its sibling: **`cut_by_time` flags every suspect-duration word a removed
    span overlaps, not the ones at the boundary.** Right for an ordinary cut,
    noise for a wholesale one — 15 flags on a reel, none near either edge — so
    `reel` asks about the edges it *keeps* instead. A guard that has to be
    suppressed every time is the thing to fix, not to document.
  - **A bumper or end card is project state (`TAIL_KEY`), and a derivation
    inherits nothing — it reports `tail_dropped`.** That is the fix for what
    used to happen: applied downstream of `export`, re-cutting dropped it at
    exit 0 with `status`, `verify` and `check_frames` all silent, because
    nothing in the project ever knew. A cue is the wrong mechanism for it — a
    cue addresses a moment *inside* the film and a tail is after it, so that
    route needs appended silence first and `vo_extend` for the teaser. A tail
    is two ordinary MLT entries and **no new writer concept**; what it costs is
    that `Edit` stops being the single answer to "how long is this", which is
    why `status`, `check_frames` and `film_check` read `expected_duration`
    rather than the edit — `film_check` is the one that did not, and read
    `agrees: false` on the real film by exactly its end card until 2026-08-18. HISTORY.md § Tail time, built; § The end card and the bumper became
    templates.
  - **`vo_extend` is built, and it is the one op authorized to grow `Edit`
    rather than only cut it.** `Edit.insert` splices a real generated-silence
    clip in — never a clip_id widened past its registered duration — and
    `restore`/export routing need no changes of their own: `restore` already
    refuses once a clip's segments stop being contiguous, and `_is_layered`
    already routes to melt on a second `clip_id`, both permanently once a
    hold lands. **The one thing to check is `covered_by`** — `build_shots`
    runs each shot to the next cue, so a hold with no cue of its own gets
    whichever picture was already playing frozen across it by default, with
    `shots_error`/`verify`/`check_frames` all staying clean. HISTORY.md
    § `vo_extend`, built.
  - **The A2 music bed is project state too (`MUSIC_KEY`), and no field in it
    is a timeline second or a frame count** — `(clip_id, word_index_start,
    word_index_end | None)`, duration derived live through
    `Edit.timeline_span` on every build (`_music_plan`), never stored and
    never cached: a stored length was measured drifting onto live material,
    and a cached one is two facts kept in step only by a hook nobody has
    forgotten yet. No end word means "to the end of the `Edit`" — a tail is
    after the film, so the end card holds over silence. The bed's lane is
    padded/trimmed to the document's exact total by construction (real
    silent-WAV entries, never a `<blank>`), so `mlt.declared_frames` still
    takes no exceptions. **`MUSIC_KEY` is `_is_layered`'s fifth trigger and
    must never lag the writer** — a bed recorded but routed through
    auto-editor renders with no music at exit 0, invisible to every check
    but listening; the export reply's `music` field is where a caller sees
    the render carried it, and `timeline_view`'s `music`/`music_error` is
    what the web UI's A2 lane gates on (`timeline.js` `buildMusicRow` — no
    bed, no lane). `reel` drops the bed and names it
    (`music_dropped`) — the tail's rule, because a bed re-opened from its
    head mid-film is the `cues_pinned` shape with no pin to give it.
    HISTORY.md § The A2 music lane, built.
    - **A `volume` filter's `level` keyframes are dB, positioned relative to
      the entry the filter is attached to — never gain factors.** Keys of
      0..1 render as a 1 dB wiggle at exit 0: a fade correct in the XML and
      absent from the audio. `level=0` is exactly unity. Both measured
      (`~/lucid-a2-probe/fade_probe.py`); the fades ride the bed's entry so
      a fade-out ends where the music *audibly* ends, and a fade pair the
      bed cannot hold refuses at `_music_plan` ("shorten the fades"), never
      clamps. HISTORY.md § The A2 fades and the lane, drawn.
    - **The window sets the bed too (`POST /api/music`), and both traps in
      that are general to any editor over a projection.** A **refusal is
      sent instead of the state** — `music_error` means `state.music` is
      null, so a panel filled from the view says "no bed yet" over a bed
      that exists; read the stored cue back through the op's no-argument
      read, never by adding a view field. And **`clip_id` rides the word
      index and never travels alone**: it is the transcript the index
      indexes, so sending the view's current clip on a fades-only change
      re-addresses the bed, and reads as correct in every call that happens
      to be a first set. HISTORY.md § The A2 lane became settable.
- Resolve media through `media.media_path()`, never `root / clip["media"]`. A
  `media/` entry is optional — the NAS rejects symlinks, so import falls back to
  referencing the source in place (wiki `files.md`).
  - **The preview resolves through `media.preview_path()`, and that split is
    the containment.** A proxy never enters the manifest and `media_path()` has
    no branch for it, so `export` cannot reach one because it never calls
    `preview_path` — whose only callers are `ops.preview_source` and
    `webui._send_media`. **Adding a third is the whole hole**; a manifest key
    would inherit `media_path()`'s reach and deliver a preview encode as the
    film. A proxy is also **downscaled** (`media.PROXY_HEIGHT`), safe only
    because `player.js`'s `place()` positions by canvas-coord `dest` and never
    reads `videoWidth`. Its size claim holds on real footage only — a
    `testsrc` fixture proxies *larger* than its hevc source, so never assert a
    reduction. HISTORY.md § The preview proxy.
  - **`GET /api/output` is the only route that serves `renders/`, and it
    resolves through `renderlog.last` — never the manifest and never
    `preview_path()`.** It streams the one file the last pipeline run
    recorded: not a listing, not a path the client names, and confined inside
    the project anyway, because lucid writing that log itself is the argument
    for not letting one hand-edited line turn a loopback server into a file
    server. The window still plays the *project* everywhere else; this is the
    single place it plays an artifact, and widening it is a new decision.
    PLAN.md § Open questions, *Should the workspace play its own output*.
    HISTORY.md § The window plays its own render.
  - **A thumbnail is a preview artifact and keeps the same containment rather
    than adding a caller to it.** `ops.thumbnail` never enters the manifest
    and never calls `preview_path()` — it resolves media through
    `media.media_path()` and cuts one frame with `picture.extract_frame`,
    cached under `cache/thumbs/<clip_id>/<ms>.jpg`. Adding a third caller to
    `preview_path` is the whole hole this containment exists to prevent; a
    filmstrip route earns its keep by not needing one. HISTORY.md § The
    assets, properties and filmstrip backend, built.
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
    - **What removes one is `unspoken`, and the witness is the render — never
      the seam and never a reading.** A mark is `(clip_id, word_index, text)`
      and **never touches the transcript file**: renumbering would move every
      cue. `_spoken_transcripts` is the one derivation, feeding captions,
      `caption_view` **and `verify`** — which reports the count beside its
      diff, or a mark becomes a way to make a real miss disappear.
      - **The seam scan sees only one of the two mechanisms.** The other is a
        *fragment*, a cut that left a sliver of a real word — drawn whole,
        inaudible, no overlap to find. `unspoken_detect` takes candidates from
        both and lets the render decide, so its kept-share floor **asks and
        never decides**; `apply` is off by default, like `reframe_detect`.
      - **A stale mark is kept, never applied** — recorded text ≠ current text
        means the transcript was replaced under it, and a word wrongly drawn is
        visible to anyone watching while a real word dropped is invisible to
        every check lucid has. HISTORY.md § The teaser, re-cut.
- **A frame count comes from `autoeditor.frame_layout`, never from the
  duration.** Each segment edge quantises on its own, so `sum(dur)` and
  `round(edit.duration * fps)` are different numbers and the first one is the
  timeline that gets exported. Related, and measured rather than assumed:
  auto-editor's `--export kdenlive` output is **one frame longer than your
  edit, and the frame is black** — MLT's `out` is frame-inclusive and
  auto-editor writes a frame count into it. `export --render` does not have it.
  HISTORY.md § `check_frames`.
  - **Read back, `out` is the last frame *index*, so a range's exclusive end is
    `out + 1`** — and getting this wrong is invisible on any one range. The
    hand-parse that brought the Scream retake cut in read it as exclusive and
    lost a frame off the end of all 63, shipping a film 2.098s shorter than the
    `.kdenlive` says it is. `mlt.read_ranges` is the only reader; `import_edit`
    is the only caller, and it checks its own total against
    `mlt.declared_length` — a Kdenlive document states its length in three
    places and a misread disagrees with all three at once. **A multi-track
    `.kdenlive` is refused, not preferred-down to one track**: four of the
    Scream project's fourteen are assemblies with a real picture track, and
    picking a playlist would import half an edit at exit 0. HISTORY.md § The
    import that was one frame short, sixty-three times.
- **`melt` is inside the Kdenlive flatpak, and that flatpak cannot see
  `/tmp`.** It has no host package here; resolve it through
  `picture.melt_command()`. Pointed at a project under `/tmp` it prints
  `Failed to load` and **exits 0**, so its exit code proves nothing — check its
  output. Anything writing a project for melt to read puts it under `$HOME`,
  and that includes what it *writes*: `picture.render` stages into
  `~/lucid-render/` and copies out only after the file agrees with the timeline.
  - **A *failed* render's staging directory survives on purpose, and
    `sweep_scratch` drops it after `SCRATCH_RETENTION_DAYS`.** It sweeps by
    name (`_SCRATCH_NAME`), never by age alone — a hand-placed directory in
    that root would otherwise go — so **a new `scratch()` prefix that is not in
    that pattern is never swept**, which is the unbounded growth this replaced.
    HISTORY.md § The staging directories nobody swept.
  - **`WAYLAND_DISPLAY` alone is not a display.** It names a socket that Qt
    resolves under `XDG_RUNTIME_DIR`; with only the name, melt aborts printing
    nothing and the empty output reads as an unloadable project. Go through
    `picture.display_env()`, which exports both — and note the environment it
    is compensating for is the **MCP stdio transport's**, which passes HOME,
    PATH and little else. HISTORY.md § Rendering through `melt`.
    - So **a session with no desktop behind it cannot run the four
      melt-rendering tests in `test_server_stdio.py`** — `export` refuses with
      "no display for MLT's Qt module to open", correctly, and they fail as a
      `JSONDecodeError` on the refusal text. Four failures there and nowhere
      else is the environment, not a regression; confirm by stashing `src/`
      and re-running, rather than by hunting.
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
    - That rule is not a caution, it is a **disagreement**: `font_match` asks
      fontconfig and libass asks something else, so a clean `resolves_to` is
      not a claim about the burn. Two styles `fc-match` calls identical render
      3593 RMSE apart here, because libass's first pick for `Noto Sans` on this
      box is a **Nerd Font symbol face** and it only reaches the real one by
      failing to find `E` — the Latin glyphs then agree and the primary font
      still supplies the space advance. `ffmpeg -v verbose` prints every
      `fontselect` line; a caption font that resolves in one pick with no
      fallback is the only kind that has been settled. HISTORY.md § The
      approvals round, answered.
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
    - **Every placed text slot is measured too, and the unit is the `<text>`
      element rather than the slot** — a placed slot declares `kind: "line"`
      or it is named in another slot's `parts`, there is no third state, and
      a test holds every template to it. The element is the unit because a
      title is drawn beside things that take width: the year is a flat 229 of
      `receipt`'s 1640-unit box, so a title measured alone is measured against
      a box something else is standing in. A line has no wrap to fail, so an
      unmeasured one runs off the frame at `magick` exit 0 — measured, the ink
      of one such render spans the full 1920 with both margins gone. The box
      is derived from the anchor (`1920 - 2x`, `2x - 1920`, or the margins),
      never declared free-hand. HISTORY.md § The measured line.
  - **Per-run `<tspan>`s eat the whitespace between them**, so `the
    [em]perfect[/em] horror` draws as `theperfecthorror` at exit 0.
    `xml:space="preserve"`, once per line — it inherits. Both:
    HISTORY.md § The emphasis-capable quote slot.
    - **A `line` slot takes the same vocabulary, and its two rules are the
      opposite of a flowing slot's**: a value with no marker takes the plain
      path byte-for-byte (or a sweep reports every card redrawn), and an
      unmarked run inside a marked value declares nothing, because the
      `<text>` element already sets fill and weight. Emit no positional
      `x`/`dy` — half of them are `text-anchor="end"`, where an `x` opens a
      second chunk and moves the line. And **`line_parts` carries the run's
      weight into the measurement**: `[em]` is a weight change too, so
      stripping markers without it under-measures the emphasised fragment,
      which is a line slot's only guard. HISTORY.md § The brand mark on a
      line slot.
  - **A per-aspect layout is a variant *file*, resolved from the canvas —
    never a second template name.** `receipt` at a tall canvas draws
    `receipt.portrait.svg`; a `receipt-portrait` template would make an aspect
    swap rewrite the recorded template, and the record would stop saying what
    the card is. A variant declared with no file refuses rather than falling
    back — the fallback is the pillarboxed card the variant exists to remove,
    at exit 0 — and a variant file the manifest does not declare refuses too,
    because nothing would ever draw it and nothing would say so. Its geometry
    is declared beside it and reaches both the drift guard and the wrap
    through `_declared_slots`: a portrait file measured against landscape
    declarations overruns its box at `magick` exit 0. HISTORY.md § Variant
    resolution.
    - **Every slot fitting its box says nothing about whether the layout
      reads, so a variant is watched before it is called done**, and the
      measurement is an ink-band profile down the frame, not the slot table.
      The portrait reveal passed every budget and drew its year alone in the
      724px under the note — a cluster and an orphan, where the receipt is a
      cluster and a margin. **The reserved edges are the bottom fifth *and*
      the right side**, which is why the portrait wordmark is bottom *left*
      and the landscape one is not; the platform numbers are in
      `BASE_GEOMETRY`'s comment. HISTORY.md § The orphaned year.
  - So **a card is re-authored, never resized**: `card_new` records
    `(template, slots, canvas, variant)` and `card_reauthor` fills the template
    again at the project canvas. **The variant is on the record because a
    variant shipping changes what a canvas draws without changing the canvas**
    — a canvas-only sweep answered `redrawn: 0` over twelve cards that were all
    still the old layout, and reported the project up to date. It is additive
    and optional, so absent means none, which is what every older record meant.
    HISTORY.md § The portrait cards. A card with files but no record cannot be
    re-authored by anything — it is reported, never guessed at. The twelve in
    `~/lucid-final-cut/proj` **are recorded** (all thirteen with the outro, at
    1920x816 — verified in the manifest 2026-08-17); `~/lucid-cards-reauthor/`
    keeps the slot tables and `reauthor.py`, the recovery route if a copy
    without records ever resurfaces. All twelve author at 9:16; the two that
    refuse at 2.35:1 are a 16:9-only content fit. HISTORY.md § The card record,
    § Step 6 of the aspect swap, watched.
- **A channel preset pack is a snapshot, never a live reference to a sibling
  repo's file.** `pack.load_pack` resolves one external JSON file (palette,
  fonts, mark, caption presets, weights) once; `pack_apply` writes the fully-
  resolved payload into the manifest's `pack` key and hashes it — `pack_hash`
  is sha256 of the *resolved* payload, not the file's bytes, so a whitespace
  reformat upstream cannot trigger a spurious re-author sweep. No schema bump —
  `pack` and a card's
  `pack_hash` are both additive-optional, the `CANVAS_KEY`/`CAPTION_STYLE_KEY`/
  `TAIL_KEY` precedent. `pack_apply_captions` is a separate op from
  `pack_apply` on purpose, so activating a pack never silently overwrites a
  hand-edited `caption_style` underneath it. HISTORY.md § The channel preset
  pack, built.
  - **A font that draws correctly and a font that is vendored are two
    different findings, and only one of them refuses.** `fonts.probe`
    reporting `drew: False` refuses unless `allow_fallback` (which then
    records the fallback rather than applying it silently); `drew: True` on an
    unvendored face is *not* refused — the render on this box is genuinely
    correct — but is permanently marked `font_provenance: "unvendored"`, so a
    project depending on a font nobody ships can say so without re-probing.
    Zilla Slab is exactly that case. Treating either check as standing in for
    the other misses what it alone catches.
  - **Safe zones are report-only, on `SCENE_THRESHOLD`'s own precedent.**
    `graphics.SAFE_ZONES` is `BASE_GEOMETRY`'s comment turned into data (the
    per-platform bottom bands, worst case 384px — the bottom fifth of 1920 —
    each with the right-hand action rail), and `card_safe_zones` reports ink
    inside the band **and**
    in a same-area sample outside it **and** against the card's own recorded
    background — three numbers, never one, because a brightness bbox has
    already misread a black source as a black bar twice in this repo (see the
    auto-framing detector below). No floor, no `--strict`: a threshold gets
    pinned by looking at real output, not picked cold.
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
  - **A sheet row is a window shown, not a placement** — sampling placements at
    three fixed fractions never looked at 14 of the vertical's 55 windows,
    eight of them hand-approved. Each placement is split at the boundaries it
    crosses and `moments` are fractions of the stretch showing that window, so
    `count` is windows (58 on the vertical against 25 placements, and all 55
    stored windows drawn) and `placements` is placements. **The edges take a
    frame of tolerance, never an epsilon** — the same rule `steps` needs below,
    for the same 30µs. `windows` on a row is
    still the *placement's* count (the preview/render tell); `window` is the
    address `reframe --src-start` takes. HISTORY.md § The thirty-nine windows,
    reviewed; § The three gaps, closed.
    - **And a window it *does* sample can still pass while badly wrong**, so a
      clean sheet is not an approval of the span: a rect is a claim about a
      stretch, a tile is evidence about one instant, and a static rect over a
      moving subject has a best instant. HISTORY.md § The tile that made a
      wrong window look right.
      - **`--extremes` is the answer, and it is opt-in**: the rect does not
        move inside a stretch, so the worst moment is at the subject's own
        leftmost or rightmost by construction — three tiles, worst first. It
        costs `LUCID_FACE` and ~0.5s a probe. **Its probe grid contains the
        fixed fractions deliberately**: probing at a rate finds the extreme of
        the *sample*, and without them it was worse than the default on 5 rows
        of 16. **Read `worst_offset` beside `multi_face`, never after it** —
        the subject is area-weighted over every face, so a two-face frame puts
        it between them where nobody is, and the teaser's largest offset (608px)
        is exactly that. HISTORY.md § The sheet samples where the subject is.
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
  - **A window can hold a second rect (`pane`), and then it draws as a stacked
    split** — two half-height panes, a second node of the same resource,
    nothing new in MLT. **Both rects are grown to the *full source height*,
    never merely to the pane's aspect**: nothing masks a pane, so a crop
    shorter than the source scales the frame past its own pane and into the
    other one at exit 0. That full height is the only thing holding the halves
    apart. The pane node is switched off by **opacity 0 keyed at every window
    boundary** — a step not written is a value that carries on — and the sheet
    draws the lower rect dashed, which is where a split gets judged. It fires
    on 10 of the film's 79 windows at the 0.15 floor — **a count like that
    moves with the floor rather than describing the film**, since three moments
    spanning 8s agree far less often than three spanning 2s, and six of the ten
    sit on windows the old floor also had. **`reframe_detect`'s `faces` is
    detections summed over the sampled frames and is not a subject count** (33
    is eleven people), `subjects` is. HISTORY.md § The stacked split, built;
    § What the re-pin did to the detector.
    - **Judge a split on how much its panes overlap each other**, and the
      number is `pane_overlap` — on the proposal and on the sheet row, where it
      used to be worked out by hand off the two rects. The film's separate at
      23–24% (distinct groups) against 52–63%, where the same face is in both
      halves and stacking shows it twice; **4 of its 10 proposals are the
      duplicating kind**, 3 of them predating the 0.15 floor. Reported, never
      enforced. HISTORY.md § The thirty-nine windows, reviewed; § What the
      re-pin did to the detector.
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
    `_face_worker.py` shipped to be run and never imported). Its placement rule
    is sound — reviewed one window at a time, all 39 on the film are right for
    the shot they were placed on — and **every defect found is coverage**:
    - **"Is this window already framed?" is a frame, never an epsilon.** ffmpeg
      reports a cut at 0.834167 where the manifest holds 0.8342, so exact match
      called 15 of 16 hand windows unframed *and printed both as `0.8342`*.
    - **A refused window is not a centre-cropped one.** Nothing is written for
      it, so whatever is in force carries over — at a clip's head the centre
      crop, anywhere else **the previous shot's framing**, which is worse than
      the default because a stale window looks deliberate. Not an edge: it is
      13.6s of `cold-open`, one rect held across four camera setups, Casey's
      framing sitting over trees and a stovetop. `falls_back_to` names which;
      never infer it from `refused`.
      - **`reframe_detect` answers that of a proposal, `reframe_coverage` of
        the project on disk** — scene cuts against stored geometry, so it needs
        no face detector. **Its unit is the placement, not the cut**: a
        placement can *begin* downstream of the cut that stranded it and hold
        no cut at all, so walking each placement's own cuts misses exactly
        those — 6.0 of `cold-open`'s 13.6 stale seconds. Read `stale_seconds`
        (an override held across a cut), never `default_seconds` beside it (the
        centre crop, a different thing). HISTORY.md § `reframe_coverage`.
        - **"Needs no face detector" is not "cheap."** `reframe_coverage`
          decodes placed footage for its scene-cut scan — 5.7s wall, 46s of
          CPU on the film, uncached, every call — so nothing re-read on every
          `project-changed` may compose it in. `finish_report`'s `framing` is
          opt-in for exactly that (`framing=True`, `?framing=1`,
          `--framing`), and `None` when unasked, distinct from a measured
          zero: "nobody scanned" reading as "nothing stale" is the
          captionless-film shape again. HISTORY.md § Frame mode.
          **`frame.js` broke this rule from the other side** — its own
          `update()` runs on every `project-changed`, so every cut paid 5.5s
          of decoding for a hidden pane. A pane's work rides being *looked
          at*: `app.js`'s `setMode` emits `mode` for that. HISTORY.md § The
          two console 400s.
        - **A blank chip where a warning would go reads as "nothing to
          report."** Frame mode's coverage chips drew empty for the ~4s the
          sheet job takes, which is indistinguishable from a clean project —
          the one thing this view must never say by accident. A slow check
          has to say it is running ("scanning for cuts…") or its silence
          reads as the answer. HISTORY.md § Frame mode.
        - **It also asks which windows have no cut (`steps`), and that is the
          one a viewer notices** — a boundary inside a continuous take reads as
          an edit that is not there, while the stale walk answers clean because
          nothing was held *across* a cut. Three rules, each measured: the two
          directions score against **different cut lists** (a cut must reach
          `threshold` to *demand* a window, only be detected to *explain*
          one); "interior" takes **a frame of tolerance**, a window placed at a
          shot boundary being the normal case and sitting ~1e-7 from the
          placement's own start; and **a near sub-threshold cut is not evidence
          of a missed one** — score the boundary itself. The first two are 13
          false findings of 15 apiece. HISTORY.md § The three gaps, closed.
    - **`SCENE_THRESHOLD` is 0.15, re-pinned 2026-08-12 by judging detections
      rather than by agreeing with the hand table.** The old 0.20 called a real
      cut in an unframed shot a false positive, which measured fifteen windows
      over three clips of nine. Every candidate the film shows was looked at on
      the frames either side: **all 31 from 0.141 to 0.244 are cuts, the first
      non-cut is 0.137**, so 0.20 was discarding 21 real cuts and buying
      nothing. A cut with no window is framing walked through, so the film's
      stale share going 6.3% → 28.0% is the reporting starting, not a
      regression. `tests/test_scene_threshold.py` pins it from both sides.
      HISTORY.md § The scene threshold, re-pinned.
    HISTORY.md § The auto-framing detector, built; § The thirty-nine windows,
    reviewed.
- **A clip being registered is not a clip being on the timeline, and
  `timeline_view` answers for one anyway — read `off_timeline`.** It reports
  rather than raises (`transcript_missing`'s policy), handing back the
  timeline's own segments under the `clip_id` asked for; a transcribed clip
  that is off the edit has every word `present: false`, indistinguishable from
  one cut in its entirety. The flag is the only thing separating them, and a
  front end must never re-derive it from `segments[].clip_id`. HISTORY.md
  § `off_timeline`, and the advice that made it worse.
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
- **`Edit`'s addressing reads a cached `_SpanIndex`, so never mutate
  `edit.segments` in place** — assigning the attribute is what drops the index,
  and a stale one answers every lookup confidently and wrongly. All four
  mutators rebind (`remove`/`keep_only`/`restore`/`insert`); `restore` used to
  splice and no longer does. Its bisect's
  precondition is sorted **and disjoint** (an import can place the same source
  twice), and a clip failing it gets the exact walk. HISTORY.md § The scan the
  spike named was not the one that costs.
- **`Edit` never stored what it removed** — it is surviving segments and
  nothing else, so "what was cut" is derived (`Edit.gaps` against the clip's
  registered duration), never read back. `restore` is bounded by those gaps,
  which is what keeps the timeline a subset of the source and separates it
  from `vo_extend` (built — see the `TAIL_KEY` bullet above), the one
  mutator allowed to add source the recording never had.
  - **A dogfood project can be the wrong cut while every check passes.** The
    Scream project held the *silence-cut* VO, not the shipped one — 410.96s/73
    segments against 336.27s/63 — and the render, `verify`, the cue table and
    the shot plan all agreed with it. That was `~/lucid-final-cut/proj`, and it
    is **restored as of 2026-08-18** — 63 segments, all 38 shots projecting,
    `essay-flashfix.mp4` declared as its `reference` so `film_check` re-asks
    with no argument. `~/lucid-scream-v2` still holds the same stale edit,
    byte-identical; the shipped one is also in `brief-check`, `framing-detect`,
    `threshold` and `split-detect`. Settle any copy against the renders, which
    are 336.34s (`essay-cards-fixed.mp4`) and 342.36s with the 6s endcard,
    before building anything for review on it.
    - **The right edit is not the right film — `brief-check`'s cue table is
      not the film's, 27 of its 38 cues naming a different asset.** It is
      where § Choosing the b-roll was measured and the experiment stayed in
      it, and it is the *only* 336s project at the film's own 1920x816
      canvas, so it is exactly what a rebuild reaches for. Every check passes
      on it. **Diff a cue table against more than one project before trusting
      it**: the three vertical projects agree with `final-cut` 38/38.
      HISTORY.md § The film's project, restored.
    **And carry derived state back off a scratch copy** — the ten card records
    were written on the 411s copy, so the film's own project read as having
    none. Four instances now — the newest is `~/lucid-kf-probe`, which is
    `framed-teaser` rather than the shipped teaser, so its two renders are an
    A/B of each other and **neither is a control**. `film_check` is the cheap
    way to ask. HISTORY.md § The VO the project was holding, § The keyframed
    move.
