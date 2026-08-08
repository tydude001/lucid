# lucid

Architecture, stack decisions, and open questions live in [PLAN.md](PLAN.md).
The competitor/dependency survey behind those decisions is in
[PRIOR-ART.md](PRIOR-ART.md). What the first real video exposed, and the four
things it said to build next, is in [DOGFOOD.md](DOGFOOD.md). The build order
and the rationale behind it is [ROADMAP.md](ROADMAP.md). Open-item status
lives in the wiki, not here.

## Things that will bite you

All four are cases where the training prior is confidently wrong. Check the
installed package or the upstream repo, not your memory.

- **The MCP SDK is v2. `FastMCP` no longer exists** — it is `MCPServer`, from
  `mcp.server` (and there is no `mcp.server.fastmcp` module). Training priors
  overwhelmingly say `FastMCP`; check the installed package before writing
  server code, not your memory of the API.
- **auto-editor is Nim, and PyPI is stale.** `pip install auto-editor` gets
  29.3.1; upstream ships 31.x. There is no Python API — shell out to the binary,
  like ffmpeg.
- **Whisper is a subprocess, and it is not on PATH.** Do not `import whisper` —
  go through `asr.transcribe()`, which resolves the binary via `LUCID_WHISPER`
  → PATH → a sibling venv. It is openai-whisper, not faster-whisper, whatever
  PLAN.md's older tables say. Why it is not an import: `asr.py`'s docstring.
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
  whether it is registered or reachable.
- **Anything taking a word index echoes the words it resolved to, plus the
  three either side.** The neighbours are the point: an index one past the
  intended phrase reads correctly on its own. Mutating tools also take a
  `plan` that resolves without writing. PLAN.md § `cut --plan`.
- **Cite roadmap items by name, never by number** — the numbers renumber on
  every ship, and four things once cited "item 1" meaning four different
  items. Point at the named PLAN.md `##` section instead. ROADMAP.md header.
- Resolve media through `media.media_path()`, never `root / clip["media"]`. A
  `media/` entry is optional — the NAS rejects symlinks, so import falls back to
  referencing the source in place (wiki `files.md`).
- **Trust a transcript's word order, never its word durations.** Whisper hides
  a whole retake inside the duration of the word after it. So "did this word
  survive?" is an *overlap* test against the kept ranges, never containment —
  partial survival is normal. DOGFOOD.md § 2.
  - The trap when *masking audio* with a word map: an inflated duration covers
    the retake it swallowed, so believing it hides exactly the hole you are
    looking for. Trim spans through `energy.believable` first. PLAN.md
    § `verify --windowed`.
- **A frame count comes from `autoeditor.frame_layout`, never from the
  duration.** Each segment edge quantises on its own, so `sum(dur)` and
  `round(edit.duration * fps)` are different numbers and the first one is the
  timeline that gets exported. Related, and measured rather than assumed:
  auto-editor's `--export kdenlive` output is **one frame longer than your
  edit, and the frame is black** — MLT's `out` is frame-inclusive and
  auto-editor writes a frame count into it. `export --render` does not have it.
  PLAN.md § `check_frames`.
- **`melt` is inside the Kdenlive flatpak, and that flatpak cannot see
  `/tmp`.** It has no host package here; resolve it through
  `picture.melt_command()`. Pointed at a project under `/tmp` it prints
  `Failed to load` and **exits 0**, so its exit code proves nothing — check its
  output. Anything writing a project for melt to read puts it under `$HOME`.
- Anything that emits times *for playback* maps through the edit, never
  straight off the transcript. The transcript indexes the source; the timeline
  is what plays. See PLAN.md § Captions came out of the timeline.
  - Which mapping depends on whether one answer is enough.
    `Edit.timeline_span` stops at the first survivor — right for captions, one
    span per word — while `Edit.timeline_spans` returns a `Placement` per
    surviving piece. A range a cut split has more than one answer, and the
    singular form reports one of them without saying so. PLAN.md § `locate`.
