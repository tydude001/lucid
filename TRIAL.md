# TRIAL — the closed loop, measured, and the queue it produced — 2026-08-25

NEXT.md § 1 asked for the one measurement lucid has never made: hand an agent a
brief and watch it drive `claude -p` against the MCP server from import to
export, unattended, then score the result. This file is that run's evidence and
the queue its failures became. **Status of anything here lives in the wiki's
Open items table, never in this file** (root conventions § Knowledge stores).

The instrument is `scripts/agent_trial.py`. What shipped and what it cost is
HISTORY.md § The closed-loop trial. What NEXT.md recommended, and why, stays
NEXT.md's.

## What was run

One brief, on the generated demo project — `make_demo.py`'s voiceover with its
deliberate retake, and two b-roll clips whose every second names itself. The
project began at `lucid init` and nothing else: no import, no transcript, no
seeded timeline, because "import to export" is the loop being measured and a
pre-seeded project quietly measures the back half of it.

The client is the agent panel's, imported from `webui.py` rather than retyped:
`--tools ""` (the built-in set gone, so lucid's 87 tools are the agent's whole
reach), `--strict-mcp-config` against a generated one-server config, and that
config naming this interpreter with `-m lucid.cli`, never the name `lucid`.

The whole run is kept at `~/lucid-work/agent-trial/runs/20260825-165027/` —
`events.jsonl` verbatim, the brief it was given, the argv and MCP config it was
spawned with, and `report.md`/`report.json`. `--score-only` re-scores it
without spawning anything.

The brief names the goal and never the steps — the fluffed take gone and
nothing else the narrator meant, b-roll under the lines it belongs to, captions
burned in, rendered to a named path, and the render checked rather than merely
produced. A brief listing the commands would measure the brief's author.

## The result

**The agent met the brief. 9 of 9 checks pass.** 31 turns, 30 tool calls across
22 distinct tools, one refusal, 4 images returned, 184s, $1.31 on Opus 5.

| check | verdict |
|---|---|
| `timeline_seeded` | 2 segments, 12.968s |
| `media_imported` | 4 clips |
| `picture_hung` | 3 shots over 2 assets |
| `retake_removed` | 0 of 6 retake words survive |
| `good_take_kept` | 6 of 6 words of the good take's own tail survive |
| `render_exists` | 2 of 2 claimed paths on disk |
| `frames_agree` | delta 0 — 311 expected, 311 in the file |
| `verify_similarity` | 1.0, 34 heard against 34 expected |
| `captions_burned` | burned into the delivered file |

The edit is not the walkthrough's. It seeded with silence removal **off** and
made exactly one cut, reading "nothing else that the narrator meant to say" as
a reason not to let auto-editor find its own; it hung three shots rather than
two, one per surviving sentence; and it pinned the third shot 6s into the blue
clip so the two blue shots draw different material rather than replaying the
head — the `src_start` pin, reached for unprompted. It escalated to
`verify --windowed` on its own, naming the reason (a single pass collapses an
immediate repeat, so a surviving retake can read clean).

**The control run passes the same 9 checks in 11.6s and no money.**
`--control` meets the brief by script — `docs/DEMO.md`'s own commands plus the
caption burn — and is scored by the identical `score()`. It is not there for
comparison: it is there because a check that fails on the agent because it is
wrong about lucid reads exactly like a check that fails because the agent is.
Every check in the table above has been seen to pass on a known-good edit.

## The queue — where the agent stalled, guessed, or reached for something absent

Each row is evidence-backed, ordered by what it costs a real run.

**All seven are closed** — six on 2026-08-25 (HISTORY.md § The trial's queue,
closed — six of seven) and the last on 2026-08-26 (§ The seventh queue item,
decided and built). The rows below are kept as the run's evidence and are
written in the tense of the run, so **read a "Fix:" as what was proposed, and
every claim about lucid's surface as it stood that day**; each row ends with a
pointer to what actually landed. Status, as ever, is the wiki's.

### 1. `path` is a required argument on every tool, and under `-C` its only legal value is the one the server already knows

29 of the agent's 30 calls carried `"path": "/var/…/proj"` — the thirtieth was
`ping`, which takes none. It had been told outright that it would never need
one, and it passed one anyway on every call, and it was right to: measured
against a `-C`-bound server, omitting `path` is a **pydantic validation error**
(`Field required`), and passing a *different* project's path is refused by
`_confine`. Under `-C` the parameter is ceremony with exactly one accepted
value.

The brief's own wording is the rest of the evidence. It said *"Every tool call
is bound to it, so you never pass a project path"* — false, as the run proved —
and named the project directory anyway in the sentence before. That named path
is the only reason this agent could call anything at all, because it has no
shell and no `Read` with which to find one. The shipped panel does not even
have that: `_handle_agent_prompt` sends the person's prompt verbatim and
nothing injects the project root, so a panel agent is relying on `claude`
reporting its own cwd, which `webui.py` happens to set on the Popen. Either way
the agent must supply a filesystem path it has no tool to discover. (The
default brief now says that every tool takes the project as `path`; the run's
own copy is in its `brief.txt`, unchanged.)

Fix: make `path` optional when `_BOUND_ROOT` is set, defaulting to the binding.
`_confine` already resolves and refuses; the decorator would fill an absent
selector instead of the caller. Unbound servers are unaffected.
`server.py` § `_tool`, § `_confine`.

**Closed 2026-08-25**, as proposed, across all 82 tools — plus
`projectless=True` for `fonts`/`pack_show`, which already meant `path=None` as
"no project" rather than "which one".

### 2. `spot_frames` is the tool for looking at a delivered render, and it hands back paths the agent cannot open

Nothing numeric can say whether the captions are actually on screen or the
right card is under the right line — the repo's own hardest-won caption lesson.
The agent knew that. It registered `cut.mp4` into the project as a clip called
`delivered` so `footage_sheet` would draw it, and said so unprompted: *"That
leaves a fourth clip in the project manifest that is not on the timeline and
not cued… I'd remove it if lucid had a tool for it."*

The tool it wanted already exists. `spot_frames` takes an arbitrary `target`
file, samples frames as PNGs into `cache/frames/`, and ranks them
darkest-first — and it is annotated `-> dict[str, Any]`, so it returns their
**paths**. Under `--tools ""` there is no `Read`, so a path is unreachable;
this is precisely the defect HISTORY.md § The two sheets an agent could not see
fixed for `shot_sheet` and `footage_sheet`, still standing one tool over. The
agent's workaround is a client routing around that hole using the two tools
that were fixed.

Fix: `spot_frames` returns its montage the way the sheets do — same
`ImageContent` route, same `-> Any` annotation (a concrete return type makes
the SDK build an output schema and validate an `Image` against it, which
answers `is_error` from a correct body). Then check the rest of the surface for
the same shape rather than one tool at a time.

Second, smaller gap it exposed: **no way to un-register a clip.** There is
`cue_rm`, `hold_rm`, `unspoken_rm`, and no `clip_rm`. `undo` un-registers an
import but is positional — undoing this one would take every mutation after it.
The polluted state is quiet: `delivered` shows up in `assets`, is cue-able, and
counts toward `media_imported`.

**Both closed 2026-08-25.** `spot_frames` returns its montage the way the
sheets do, and `clip_rm` deregisters a clip — refusing, and naming every
reason, when the timeline, a cue, a hold, the bed, a mark or a transcript still
depends on it.

### 3. `timeline_status` is the first call an agent makes and it refuses on a fresh project

Both trial runs opened by calling it, and both got
`this project has no timeline yet — run lucid seed <clip_id>`. The refusal is
correct about the timeline and wrong about the question: the agent was asking
*what state is this project in*, and the tool that answers that on an
un-seeded project is `assets` or `doctor`, neither of which an agent would
guess first. The message names the fix (`seed`), which is the right next step
only if you already know media has been imported.

Cheapest fix: name the orientation tools in the refusal text. Better:
`timeline_status` answers `seeded: false` with the clip list instead of
raising, which is `off_timeline`'s own precedent — report rather than refuse.

**Closed 2026-08-25**, taking the better option.

### 4. Nothing in lucid notices two writers in one project

Measured the hard way. The first trial run's harness was killed; its `claude`
survived (it is spawned into its own session so a timeout can `killpg` the MCP
server with it) and went on calling tools for minutes. The second run's
`prepare` deleted and re-initialised the project underneath it, and the second
agent then found three cues in a project it had just watched be created and
reported it in its own prose (*"The cue table already existed in the project —
I didn't write it"*) — a run that reads like an agent hallucinating a cue table
and is in fact two agents in one project. Its `events.jsonl` was discarded when
the work directory was reset for the clean run, so this section is the record;
there is no artifact to go back to.

`scripts/agent_trial.py` now holds a PID lock, which fixes the instrument and
not the product. Lucid itself has no advisory lock and no write-conflict check.
`Project.write_manifest` is atomic per write — a temp file and a `replace`, so
nothing is ever torn — and that is a different property: across two writers it
is last-writer-wins, and the loser's edit is gone with nothing raised. A second
`lucid web`, a second panel, or a CLI command run beside either is the same
shape.

**Closed 2026-08-25.** `write_manifest` and `restore` both refuse with
`ProjectConflictError` when the manifest moved since this instance last read
it, so the loser loses cleanly. Nothing still stops two writers starting.

### 5. A refused check is not a failed one, and a consumer will get that wrong

The harness's own first score reported `verify_similarity` as a red **FAIL**
whose detail was a CUDA out-of-memory traceback — another job held the GPU. The
agent's own two `verify` calls had read 34/34 at similarity 1.0 minutes
earlier. Lucid's message is good (it says outright that this is what a busy GPU
looks like); what was wrong was the consumer, which treated "could not run" as
"disagreed". Fixed here — those checks now report unsettled, `lucid doctor`'s
own rule — and it is worth stating because every front end that composes a
check has the same trap available to it.

### 6. Registered-and-not-on-the-timeline has no report of its own

Related to (2) and worth its own row. After the trial the project holds four
clips, one of which (`delivered`) is on no lane and under no cue.
`timeline_view` answers `off_timeline` for a clip you *name*; nothing lists
which clips are in that state. A finish-time report of "registered, never
used" would have caught this without anybody reading the agent's prose.

**Closed 2026-08-25** as `finish_report`'s `unused_clips`.

### 7. The agent cannot see what media exists — it must be told

Deliberate, and recorded rather than proposed. With `--tools ""` there is no
directory listing, so the three source paths came from the brief. On a real job
something has to supply them: the panel's user, a wrapper, or a lucid tool that
lists importable media under a named directory. Worth deciding before the
first unattended run on real footage, not during it.

**Decided and built 2026-08-26** — the third option, as `list_media` /
`lucid list-media <source_dir>`, because a tool is reachable inside the same
`--tools ""` sandbox and needs neither a person nor a new client.

## What the trial says about the four sheets

The wiki row asking whether the tiles answer the question is Tyler's, on real
footage. This answers the other half — the client the image retrofit was built
for — and it answers yes. Four images came back inside tool results
(`contact_sheet` ×2, `shot_sheet`, `footage_sheet`) and the agent used all of
them: it identified the b-roll from its contact sheets (*"plain colour cards
with a burnt-in timecode… no depicted subject, so the choice is structural"*),
which is what made it hang picture by sentence rather than by subject; and it
read the delivered frames back as *"BLUE 0/1/3, then RUST, then BLUE
6/7/9/10"*, which is the `src_start` pin confirmed from the picture rather than
from the shot table. Nothing gated on a reading, per the standing rule.

What it also says is that the retrofit stopped one tool short — see queue item
2. The agent reached the delivered picture only by importing it as source
media, because the tool that samples a finished file returns paths.

## The publish rehearsal — NEXT.md § 2

Both agent-doable items ran.

**The exposure scrub is applied.** Nine edits in HISTORY.md: the tailnet IPv4
(three places), the IPv6 suffix, the MagicDNS name and the short host name
(two places each), and two absolute `/home/<user>` paths. Every reachable
identifier is now **elided** (`100.x.y.z`, `<host>.<tailnet>.ts.net`,
`fd7a:115c:a1e0::…`) rather than replaced with a plausible substitute, because
HISTORY.md records what was measured and a believable fake address would make
it claim a run against a machine nobody dialed — CLAUDE.md § Conventions now
states that rule. Left deliberately, each with a reason:

- `~/lucid-*` and `~/TheVaultData` — `$HOME`-relative, naming no user and no
  host, and cited throughout CLAUDE.md's conventions.
- the bare hostname in PLAN.md and docs/plans/DAYDREAM.md, where it names a
  homelab box in a decision record rather than a reachable address, and
  rewriting it would drift four prose lines for no gain now that the MagicDNS
  form is gone.
- `192.168.1.50` in HISTORY.md — an illustrative RFC1918 address, matching the
  test that uses it, not this node's.
- the author line in `pyproject.toml`, which is published on purpose.
- `scratch/`, which holds absolute paths and NAS directory names and is
  gitignored — confirmed absent from a fresh clone.

**The fresh-checkout dry run passes, and found one defect.** Clone to a clean
directory, `uv sync`, `uv run lucid doctor` (everything required present),
`make_demo.py --build`, then every command in `docs/DEMO.md` steps 3–6. Every
number the walkthrough prints still holds on a checkout that is not this one:
47 words, 4 segments, `removed` 4.7 planned and 4.8 padded, `duration_after`
11.866, shots `0.00 + 9.66 blue` / `9.66 + 2.21 rust`, 286 frames through
melt over 3 sources, `verify` 0.971 with 34 of 34, `frames` agrees with delta
0. The suite runs there too: **1921 passed, nothing skipped, 10m27s** — all
five melt-rendering tests included, since this box had a Wayland session. The
defect the rehearsal found: `make_demo.py --build` echoed its steps as
`$ lucid.cli init …`, an argv slice rather than a command anybody can type.
Fixed.

## What this trial does not settle

- **One brief, one project, one model, one run.** The demo footage has no
  subject, which is why the agent chose picture structurally; a brief over real
  footage is a different question and the harness takes one (`--brief-file`,
  and run it on a *copy*).
- **Nobody has watched the output.** Every check here is a number or a tile the
  agent read. `cut.mp4` is at `~/lucid-work/agent-trial/`.
- **The user-level `CLAUDE.md` is in the agent's context**, as it is for the
  shipped panel — `claude` loads user memory whatever the cwd. It is a confound
  for anyone reproducing this off this box, and it is what the panel really
  runs with, so it was left alone and is recorded here instead.
