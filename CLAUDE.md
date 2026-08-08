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
    table or a second clip_id on the edit — never from an argument, because
    the failure it routes around is silent. Positions in it are frame
    integers, `out` is the last frame *index*, and every declared length is
    read back off the finished document by `mlt.declared_frames` before it is
    returned: melt renders to the longest one it finds. HISTORY.md § The MLT
    writer.
- **Whisper is a subprocess, and it is not on PATH.** Do not `import whisper` —
  go through `asr.transcribe()`, which resolves the binary via `LUCID_WHISPER`
  → PATH → a sibling venv. It is openai-whisper, not faster-whisper, whatever
  PLAN.md's older tables say. Why it is not an import: `asr.py`'s docstring.
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
  - **Timeline lanes are projections of one `Edit`, not tracks. Never draw a
    lane `export` cannot produce** — the multi-source render degrades silently
    (see auto-editor above), so the window would look right and the file would
    be wrong. The view widens when the model does, never ahead of it.
    PLAN.md § Tier 3 is the goal. The picture lane is **legal now and not yet
    drawn** — `export` renders a layered timeline as of step 5, which is what
    the rule was waiting on.
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
- Anything that emits times *for playback* maps through the edit, never
  straight off the transcript. The transcript indexes the source; the timeline
  is what plays. See HISTORY.md § Captions came out of the timeline.
  - Singular vs plural: `Edit.timeline_span` stops at the first survivor
    (right for captions — one span per word); `Edit.timeline_spans` returns
    every surviving piece. A range a cut split has more than one answer, and
    the singular reports one without saying so. HISTORY.md § `locate`.
