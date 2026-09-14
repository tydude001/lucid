# lucid — the launch plan: getting eyes on a public repo

Provenance: Tyler asked on 2026-09-11 how a public `tydude001/lucid` gets
seen. This is the answer, written as a plan. Sources: NEXT.md § 1 (the closed
loop is the thesis), TRIAL.md (both runs of it, 9 of 9 each, and the publish
rehearsal), docs/plans/PORTABILITY.md (steps 4–6 are unrun and need machines
this box is not), HISTORY.md § The licence, chosen, and the wiki's Open items
rows `lucid-publish` and `lucid-portability`. The finding that frames it:
**flipping the repo public produces no eyes on its own. GitHub is where
people land after seeing something elsewhere, so the work is one asset worth
sharing and a short list of places whose audience already wants it — and
every leak between "saw it" and "ran it" is a first-run failure on a machine
that is not this one.**

This is the one document for that work. Status lives **only** in the wiki's
Open items table (`~/projects/wiki/README.md`, `lucid-publish`); this file
never carries a status header. When a step ships: HISTORY.md gets a named
section, the step here gains a one-line "Shipped — see HISTORY.md § <name>"
pointer, and the wiki row updates.

## How to work this plan

- **The order is the plan.** Each step is cheap on its own and worthless out
  of sequence: a Show HN before a stranger's run turns the launch thread into
  a bug tracker, and a directory listing before the flip points at a 404.
  Step 1 is done; 3 gates 2 and 4, which then overlap, and 2 and 4 gate 5.
  **Step 2 ran ahead of the flip until 2026-09-13**, when the friend it
  counted on fell through (Tyler: nobody he knows can test it). A stranger
  can only reach a public repo, so the flip moved in front of it.
- **Steps 1 and 3 are Tyler's hands; step 2 is somebody else's.** An agent
  can draft every post, build the recording pipeline, and prepare the
  directory submissions, but cannot press record on a screen, cannot flip the
  repo, and cannot be the stranger.
- **What "eyes" means here is measured in strangers who ran `lucid doctor`,
  not stars.** A star is a bookmark. The numbers that say the launch worked
  are issues filed by people who are not Tyler, installs reported by the MCP
  directories, and one outside pull request. Set no targets — there is no
  baseline — but record those three in HISTORY.md at the two-week mark.
- **A launch is a record too.** What was posted where, when, and what came
  back goes in HISTORY.md § The launch, dated, the same as a measurement —
  because the second launch (a release, a port shipping) will want to know
  which channel produced the strangers.

## What is already done, and must not be redone

- **The closed loop has run twice and passed 9 of 9 both times** — the
  generated demo project on 2026-08-25 (31 turns, 184s, $1.31) and real
  footage on 2026-09-03 (77 turns, 914s, $6.94, the agent choosing picture by
  subject, reviewing its own shot sheet, and defeating the duration trap
  unprompted). TRIAL.md § The result, § The result — real footage. The
  launch does not need a run; it needs a *recording* of one.
- **The fresh-checkout rehearsal passed on this box**: clone, `uv sync`,
  `lucid doctor`, every command in docs/DEMO.md, the full suite at 1921
  passed. TRIAL.md § The publish rehearsal. What it does not say is anything
  about a machine that is not Fedora with this box's binaries.
- **The exposure scrub is applied and the history rewritten** —
  HISTORY.md § The repo, readied for strangers. Nothing in the repo names a
  reachable address, and CLAUDE.md § Conventions holds the rule.
- **The licence is settled: PolyForm Shield**, chosen before the flip
  because a shipped MIT version stays MIT. HISTORY.md § The licence, chosen.
  Open-core, a hosted tier and a commercial licence are later calls, and
  **none of them is a launch step** — see § What this plan deliberately does
  not do.
- **CI runs on three OSes, on GitHub**: Linux and macOS are green and
  Windows is not yet (HISTORY.md § The second run on macOS and Windows).
  The three-OS suite is what lets step 2 ask a Mac to try it at all.

## Step 1 — the launch asset: a watchable closed loop

Built three times — HISTORY.md § The launch clip, § The launch clip, re-cut
as an announcement, § The launch clip, third shape — and rejected; the fourth
shape is the one that stands, `~/lucid-work/launch-v4/clip-v6.mp4`
(HISTORY.md § The launch clip, approved). How each round was judged and why
the clip is the way it is: `~/lucid-work/launch-v4-review/PIN.md`.

**What it is.** A 47-second cut, and the full runs uncut, of one brief driven
from `lucid init` to a verified render twice: in the agent pane of the
workspace, then in Claude Code with lucid loaded as a plugin. The cut version is what every channel below posts; the
uncut one is the link under it for anyone who wants to check it was not
staged. The pitch is the thing itself: an agent on a timeline, the render
checking itself against the edit, and no cloud in the frame.

**Footage rule.** The recording shows only footage lucid owns — the generated
demo project, Tyler's own recorded material (the co-hosted recording once
the second mic is routed, wiki `lucid-second-mic`), or public-domain footage
with its provenance written down (the clip's is NASA's restored Apollo 11,
`~/lucid-work/launch-v4/media/PROVENANCE.md`). **Never a frame of
Scream.** CLAUDE.md's committed-image rule is about the repo, but a launch
clip is more public than a README and the same reasoning applies: a
promotional video of copyrighted film clips invites the one argument the
launch does not need. The real-footage trial's *numbers* are quoted in the
post (9 of 9, 45.23s, similarity 0.984, 123 of 123 heard); its *frames* stay
in `~/lucid-work/agent-trial/`.

**It is not cut with lucid, so never say it was.** The camera, the speed
ramps, the type and the mix are a compositor script
(`~/lucid-work/launch-v4/clip.py`) over the two recordings. Lucid's own
moves are linear and it cannot retime, which is most of why the first three
shapes read as choppy. "The launch video was cut by the tool" is false, and
the line that is true is stronger anyway: the film inside the clip is the
agent's own render, untouched, and every number on screen is read from the
run that produced it. The clip refuses to build from a run that did not
verify clean. Captions burned, because every platform below autoplays muted.

**What it must show, in order**, so the 60 seconds carries the argument:
1. the brief, typed into the agent pane in plain language;
2. `import` and `transcribe` landing in the assets tab;
3. the cut — a retake struck through in the transcript, the timeline
   redrawing;
4. picture hung off phrases, the shot sheet coming back as an image the agent
   reads;
5. `export`, then `verify` and `check_frames` reporting agreement — the
   "it checked its own work" beat, said specifically: the render was
   transcribed and its words diffed against the timeline's, and its frames
   counted against the timeline's. kinocut says "quality gates", and read
   from source those score brightness and loudness, not agreement with the
   edit (`~/lucid-work/launch-listings/LISTINGS.md` § kinocut's gate, read);
6. the same brief in Claude Code, no window, ending on the agent's own check
   — because the launch's headline is "an MCP server" and the clip otherwise
   never shows one;
7. an end card with the name, the tagline, the repo, and the two `/plugin`
   commands that install it.

**The instrument already exists.** `scripts/agent_trial.py` runs exactly
this loop; what it lacks is a viewer. The recording is mostly of the
*workspace* pane, because the workspace is what a stranger will open first,
and the README's screenshot is of it. The terminal beat is a real `claude`
session recorded byte for byte (`~/lucid-work/launch-v4/mcp/`), not a mock-up. Drive the trial's own
brief through `POST /api/agent` (the panel's route) so the run in the video
is the run the trial measured — no second script, no drift.

**Done when:** the cut exists at 1920x1080, the uncut runs are on a share
link, and both are viewable on Tyler's phone. **The uncut runs are assets
on the `v0.22.0` release** (2026-09-13) — the plan's own permalink, not a
third-party share — and README.md links them under the clip. HISTORY.md
§ The uncut runs. **No vertical cut** (Tyler,
2026-09-13): every channel in steps 3–6 plays 16:9, a 16:9 editor window
cropped to a phone column loses most of what it shows, and the one vertical
outlet here, step 6's making-of short, is the slow channel and can have its
own cut when it happens.

**The README plays it on GitHub and links it on Gitea, from one commit.**
GitHub strips `<video>` and will not play a committed file — its renderer,
asked 2026-09-13, turned `<video>` into an empty paragraph and `![](clip.mp4)`
into a broken image — so the file is a GitHub upload (a `user-attachments`
URL), and it is never committed. The README carries only the bare URL on its
own line, which GitHub draws as a player and Gitea as a link. **Never add a
poster linking to that URL**: GitHub turns every link to an upload into a
player, image or not, so a linked poster drew a second player and no poster
(the first sync, 2026-09-13). The upload is
`~/lucid-work/launch-v4/readme/clip-readme-1080.mp4`, 9.2 MB, because
GitHub's cap on a free plan is 10 MB.

## Step 2 — one stranger's run, on a Mac

**What it is.** A person who is not Tyler clones the repo, runs `uv sync`,
`lucid doctor`, and docs/DEMO.md end to end on a machine Tyler does not own,
and reports every ✗ and every wrong number. A Mac, because that is where the
HN / X / Claude Code audience mostly is, and no person has run lucid on one
(README.md § Requirements says so, and must keep saying so until this step
passes — GitHub's runner is not a person, § The Mac test in CI below).

**Why it gates Show HN.** The launch thread is where first-run failures are
reported publicly and permanently. Each "doctor said ✗ five times" comment
costs more than the post earns, and the fix — a resolver, a font, a melt
path — is a one-line change if it is found the week before. Portability
steps 4–5 (measure melt, libass and magick per OS) are the deep version of
this; step 2 here is the shallow one: does the two-minute demo reach a
verified render, yes or no, and where did it stop.

**Who.** A stranger, reached through the public repo — there is no friend
or colleague to ask (2026-09-13). The ask is in three places, each pointing
at the next: README.md § Help wanted, right above § Requirements, where a
Mac user reading the install list meets it; a pinned issue saying the same
thing, for anyone who lands on the Issues tab (step 3, item 9); and the
`Mac test report` issue form, `.github/ISSUE_TEMPLATE/mac-test.yml`, which
asks for the run's own summary block and the report zip, so a report comes
back in one shape whoever files it. It is scripted so it costs the tester
nothing to think about: clone, one command, attach a zip. What finds the
stranger is step 4's listings — their audience runs Claude Code, mostly on
Macs — and, if a week of those produces nobody, one "Mac tester wanted"
post in a room step 6 does not use, so no launch channel's first
impression is spent on a request. Show HN still waits for the report.

**What comes back is a queue, not a verdict** — the trial's own rule (TRIAL.md
§ The queue). Every ✗ becomes a fix or a documented requirement; every
number that differs from the walkthrough's is either a platform difference
(record it in DEMO.md) or a bug.

**The install path is measured before it is built.** The dependency list
(whisper, auto-editor's upstream binary, melt, magick, espeak-ng) is the
obvious place curiosity dies, and the obvious fix is a container or an
install script. **Don't build either until this step says where the stranger
actually stopped** — a container that packages the wrong thing is the
inherited-blocker mistake (wiki `practice.md`), and `doctor` already prints
the fix under each ✗. If the stranger stops at the same binary twice, that
binary gets a one-line installer in DEMO.md § What you need.

**The kit, 2026-09-11 — a deliberate departure from the rule above.** Tyler
asked for the tester's run to be "really really easy", for a friend rather
than a stranger, so `scripts/mac_trial.sh --pack OUT.sh` writes one file with
the repo at HEAD inside it: no git, no GitHub access, since the repo is still
private. On the Mac it installs `uv ffmpeg espeak-ng auto-editor` with
Homebrew (22 formulae with dependencies, checked against formulae.brew.sh
that day), melt from the Shotcut app (Homebrew's `mlt` pulls 135, OpenCV and
VTK among them), whisper with `uv tool` unless one is already on PATH. Then
it runs DEMO.md's commands to the first failure and zips a report to the
Desktop. `--uninstall` removes what the run recorded adding and nothing the
tester already had. What it measures is therefore **this install path plus
lucid on macOS**, not whether a stranger can follow `doctor`'s fixes. That
second question is still open, and this run answers the one PORTABILITY.md
step 4 needs first: does Shotcut's melt carry the modules lucid's documents
use. The report's two frames settle that, never melt's exit code.

**The same script runs from a clone** (2026-09-13): `bash
lucid/scripts/mac_trial.sh` with no payload uses the checkout it sits in, and
tells the tester to attach the zip to the issue form rather than send it to
Tyler. Because that zip is posted publicly, the project's `lucid.json` and
`project.otio` are scrubbed of the home folder along with the log — both store
absolute paths. `--pack` still works, for a tester with no GitHub access.
HISTORY.md § The Mac test, asked of strangers.

**GitHub's macOS runner runs the same kit** (`.github/workflows/mac-demo.yml`,
2026-09-13), and `scripts/trial_check.py` judges the run, since the kit
exits 0 on a render that disagrees with the timeline. That is most of this
step's technical question — does the demo reach a checked render on macOS —
answered without waiting for a person. It does not answer the rest: a runner
is not a stranger's Mac, it already has Homebrew, and nobody reads the
instructions. So a green run does not meet this step's done-when on its own;
it means the stranger's run is a check of the install path rather than a
first contact with macOS. HISTORY.md § The Mac test in CI.

**Done when:** one Mac run reaches `verify` agreeing with the timeline, its
queue is closed or recorded, and README.md's "no person has run it on a
Mac yet" is replaced by what was measured.

## Step 3 — the flip, and the ten minutes after it

**No public commit may carry the MIT grant.** A flip publishes every tag
and commit, not just the tip, and until 2026-09-11 all 17 tags carried MIT.
They were rewritten to carry Shield instead (HISTORY.md § The MIT history,
rewritten). The GitHub repo was recreated for it, since GitHub serves an
overwritten commit by its hash; any later rewrite needs the same.

Tyler's hand, in this order, the same afternoon:

**The README's clip lives in the draft `v0.22.0` release** (uploaded
2026-09-13, `user-attachments/assets/3c3517cd-…` in README.md twice). The
upload belongs to that draft's notes, so **item 6 publishes that draft and
never deletes or recreates it**, and the notes it publishes keep the video
line. While the repo is private the URL answers 404 to anyone logged out,
which is GitHub's documented rule for private uploads, not a broken link.
After item 1, open it logged out (a private window) and it has to play; if
it does not, the README's first screen is a dead link on launch day.

1. Flip `tydude001/lucid` public.
2. Sync the GitHub mirror so the public repo is at the tip (wiki
   `git-server.md` § GitHub push mirrors — **never `git push --mirror`**).
   **Flip first, then sync** (2026-09-13): the account's included Actions
   minutes are spent, and a sync touching `src/` runs ci and both demo
   workflows — about 250 billed minutes of overage on a private repo and
   nothing on a public one. The repo sits public at the previous sync for
   the minutes between, so that commit has to pass the same scrub as the
   tip. **Push the `v0.22.0` tag to Gitea before this sync**, or item 6's
   release creates it on GitHub alone and the sync after that prunes it.
3. Enable private vulnerability reporting — SECURITY.md already points at it
   and is wrong until this is on.
4. Repo description: `Source-available, local-first AI video editor — an MCP
   server over ffmpeg, whisper and OpenTimelineIO` (pyproject.toml's own
   line). Topics: `mcp`, `mcp-server`, `video-editing`, `whisper`, `ffmpeg`,
   `local-first`, `claude-code`, `opentimelineio`. **The name is not
   searchable** — "lucid" is a car, a diagramming suite and a thousand dream
   apps — so the description and the tagline are what get found, and they say
   the same seven words everywhere: *lucid, the local-first AI video editor*.
5. Social preview image: `docs/img/edit-mode.png`, which is what every link
   unfurls to on X, Bluesky and Slack. It is already screened for footage and
   paths (CLAUDE.md § Conventions, the screenshot rule).
6. Tag a release: `v0.22.0`, at the tip that goes public. `v0.21.0`
   predates the licence change. **All six version literals are already at
   0.22.0** (2026-09-12, `uv sync` behind them, `tests/test_version.py`
   holding them together and green), so this item is the annotated tag and
   the GitHub release, not the bump. It read "two" until `b217b18`, when
   step 4's own manifests added four more — CLAUDE.md § Conventions names
   all six. A GitHub release with notes gives the
   directories in step 4 something to cite and the HN post a permalink that
   will not move. Release notes are the HISTORY.md section names since the
   last tag, one line each — not a changelog, which the repo does not keep
   on purpose. The draft is `~/lucid-work/launch-release/NOTES.md`.
7. Pin docs/DEMO.md from the README's first screen, if it is not already the
   first link a newcomer sees.
8. **A way to buy the author a coffee** (Tyler's ask, 2026-09-11; deferred —
   nothing else in this plan waits on it). The whole build is a
   `.github/FUNDING.yml` naming the account (GitHub Sponsors, Ko-fi or Buy
   Me a Coffee — one, not three) plus one line at the foot of the README,
   which puts the **Sponsor** button on the repo page. It is not revenue and
   is not the open-core call (§ What this plan deliberately does not do):
   it is the cheapest honest answer to "how do I say thanks", and a launch
   thread asks that question within the hour. Wire it before Show HN, since
   the button is what the thread will find.
9. **Open and pin the Mac test issue**, and create the `mac-test` label the
   issue form applies, so reports can be found by it — the repo has only
   GitHub's defaults. Step 2's stranger arrives from here on, so this is the same
   afternoon, not later. The draft body is
   `~/lucid-work/launch-release/MAC-ISSUE.md`.

**Done when:** the public URL unfurls with the image and the tagline, the
Security tab shows "Report a vulnerability", a release exists, and the Mac
test issue is pinned.

## Step 4 — the MCP directories, listed quietly

"An MCP server that edits video" is **not** a category of one. The
awesome-mcp-servers Multimedia section holds several on 2026-09-12, FableCut
(667★, a browser NLE an agent drives live) and kinocut among them. PRIOR-ART.md
had said so on 2026-08-25, before this sentence claimed the opposite. The MCP
ecosystem is still the channel whose audience wants the shape, but a listing
has to say what lucid does that the line above it does not. What each
directory actually takes today — PulseMCP paused and reading the registry,
Smithery local-only as `.mcpb`, Glama scoring tool descriptions — and the
drafted awesome-list line: `~/lucid-work/launch-listings/LISTINGS.md`.
List it a week *before* Show HN so the first strangers arrive in ones and
twos, with time to fix what they find.

- **The official MCP registry** (`registry.modelcontextprotocol.io`) —
  **`server.json` is written and in the repo** (2026-09-12, against the
  published `2025-12-11` schema); what remains is the publish through its
  CLI, which proves the `io.github.tydude001` namespace with a GitHub login
  and so cannot be done before the flip. The entry carries **no `packages`
  block**, because lucid is on no package registry and a `pypi` identifier
  would name something that does not exist — `websiteUrl` points at
  docs/DEMO.md instead. If lucid is ever published to PyPI, that block is
  the one thing to add. Re-check the schema URL at publish time; the
  mechanics have changed more than once. Shipped — see HISTORY.md § The
  registry entry and the plugin manifest. **Published 2026-09-13** — see
  HISTORY.md § The registry listing.
- **The community directories** — PulseMCP, Glama, Smithery, and a pull
  request to the `awesome-mcp-servers` list under its media/video heading.
  Each takes the repo URL, the description and the release; none needs
  anything built. **Glama's ownership claim, `glama.json`, is already at the
  repo root** (2026-09-12, checked against its published schema), so after
  the flip nothing is left to add but the listing itself. Shipped — see
  HISTORY.md § The launch clip's product defects, fixed.
- **A Claude Code plugin.** The agent pane already spawns `claude` against a
  generated MCP config (`webui._agent_bin`), so the one-command install for a
  Claude Code user is a plugin manifest naming `lucid mcp` as its server.
  This is lucid *being* a plugin, which PLAN.md's non-goal ("a plugin system
  before there are two users") does not touch — that non-goal is about lucid
  *having* plugins. **Built 2026-09-12**: `.claude-plugin/plugin.json` and a
  single-plugin `.claude-plugin/marketplace.json`, both read off
  code.claude.com's current references. The server command is
  `uv run --project ${CLAUDE_PLUGIN_ROOT} lucid mcp` — a static manifest
  cannot name `sys.executable`, and a bare `lucid` is the silent `tools: []`
  failure HISTORY.md § The agent panel had no tools at all measured — and it
  was driven over stdio with the repo's venv scrubbed from PATH: 90 tools.
  README.md § Try it carries the two install commands
  (`/plugin marketplace add tydude001/lucid`, `/plugin install lucid@lucid`),
  which 404 until the flip and need nothing else afterwards. Shipped — see
  HISTORY.md § The registry entry and the plugin manifest.

**What to watch.** Each listing reports something — installs, stars,
"tried it" comments. Record which ones actually sent a stranger (an issue, a
doctor paste, a pull request) in HISTORY.md § The launch; that is the number
the next release's listing order is chosen by.

**Done when:** the four listings are live and one week has passed with the
queue they produced closed.

## Step 5 — Show HN

One shot, so it goes after steps 1, 2 and 4, on a weekday morning US
Eastern, with Tyler at a keyboard for the following six hours.

**Title** (draft; HN strips "Show HN:" formatting quirks, keeps it under 80
characters, no exclamation):
> Show HN: Lucid – a local-first AI video editor that's an MCP server

**The first comment is Tyler's, posted immediately, and it does three
things**: says what it is in two sentences, links the 60-second clip and the
uncut run, and pre-empts the two questions that will otherwise be the
thread. Draft:

> lucid puts an AI agent on a video timeline and keeps everything on your
> own machine — whisper, ffmpeg, auto-editor, MLT and OpenTimelineIO under
> an MCP server, so any agent that speaks MCP (Claude Code, Codex, your own)
> can cut by transcript, hang b-roll off phrases, caption, render, and then
> check the render against the edit. Here is one doing that unattended,
> start to finish: [clip](https://github.com/user-attachments/assets/3c3517cd-1113-43f1-bdea-b5c11473ab10) / [the uncut runs](https://github.com/tydude001/lucid/releases/tag/v0.22.0). Two things people will ask:
>
> *Licence.* PolyForm Shield — source-available; you can read, run, modify
> and redistribute it, and the one thing reserved is shipping a competing
> product. I chose it before publishing because I'd like this to earn a
> living and a shipped MIT version stays MIT forever. Not open source by the
> OSI definition, and I'd rather say so here than have it found.
>
> *Platforms.* Developed on Linux; the demo has been run end to end on one
> Mac, and Windows has only CI. `lucid doctor` tells you what's missing and
> how to fix it, and I'd genuinely like the doctor output from your machine
> if it says ✗.

**The licence paragraph is the load-bearing one.** "Source-available" draws
scrutiny on HN, and a defensive reply loses the thread; the paragraph above
concedes the OSI point before anyone makes it and gives the reason as a
person rather than a company. Do not argue the definition in replies — link
the PolyForm text and move on. HISTORY.md § The licence, chosen has the full
reasoning if anyone wants it, and it is public.

**What else will come up, with the answer ready:**
- *"Why not just use Descript / Opus Clip / CapCut?"* — the README's own
  first section: those are desktop apps around a metered cloud; this is the
  same primitives, local, with an agent surface. Don't name a competitor the
  README does not.
- *"How is this different from kinocut / FableCut?"* — the question the
  Multimedia section guarantees. Answer with the mechanism, not a
  superlative: lucid re-transcribes the render and diffs it word for word
  against the timeline, and counts its frames against the timeline's.
  kinocut's gate scores signal levels (brightness, saturation, loudness) and
  its receipts are hashes. FableCut is a browser NLE an agent edits live, with
  no transcript addressing, and its export runs in the open browser tab — so
  its agent cannot render or check a cut on its own. Credit both, and concede
  FableCut's hand editing and its one-command install, which are real.
  LISTINGS.md § kinocut's gate, read; PRIOR-ART.md § FableCut, read.
- *"Isn't this just a wrapper around ffmpeg?"* — yes, and around six other
  things, and the value is that an agent can drive them and *verify the
  result*: `verify`, `check_frames`, `film_check`. Point at the clip's last
  ten seconds.
- *"Whisper hallucinates."* — it does, both passes, and `asr.clean` catches
  two classes of it; HISTORY.md § The ingest path's hallucination guard.
  Answers that cite a measurement land; answers that reassure do not.
- *"Does it need a GPU?"* — no for the core (whisper on CPU is slow but
  works); yes for `describe` and `reframe-detect`, both optional and both
  reported as "unavailable" rather than failing.

**Done when:** posted, the first comment up within a minute, and every
question in the thread answered within the day. Whatever the thread finds
goes into a queue the same way the trial's did.

## Step 6 — the follow-on channels, one per day

Not all at once: each channel's feedback should land separately, so it can
be told apart. Order by fit, each with the same clip and a one-line hook
tuned to the room.

1. **r/LocalLLaMA** — the hook is local whisper, a local VLM, a local face
   model, no cloud. This is their thesis, not a video-editing pitch.
2. **r/ClaudeAI** and the Claude Code Discord — the hook is the agent pane
   and the plugin from step 4. Tag it as an MCP server first, an editor
   second.
3. **X and Bluesky** — the clip, the seven-word tagline, and the MCP and
   Claude Code tags. Anthropic's developer-relations people repost MCP
   servers that do something visibly new, and an agent cutting video with a
   self-check is that; do not ask them to, just make it easy to find.
4. **r/selfhosted** — the hook is "no accounts, no metering", which is the
   README's stated non-goal and their whole reason for being there.
5. **The films themselves.** Every goodsometimes release from here carries
   "cut in lucid" and the repo link in its description, and the launch clip's
   making-of is a short of its own. This is the slow channel and the honest
   one: the tool's best advertisement is the work made with it.

**r/VideoEditing is deliberately last, or never.** Editors are the eventual
audience and the wrong first one: they will judge it against Premiere on
finishing, which PLAN.md's non-goals already concede. Developers who make
screencasts adopt it first; editors come when one of them posts a film.

## Step 7 — say so

When the two-week mark passes: HISTORY.md § The launch records what was
posted where, what each channel returned (strangers by the three measures in
§ How to work this plan), and what the queue held. The wiki row
`lucid-publish` closes, or becomes whatever remains. This file gains its
"Shipped" pointers. And the question open-core was waiting on — "after the
demo run exists" — is now answerable with numbers rather than a guess, so
the decision moves to wiki `decisions.md`, not here.

## What this plan deliberately does not do

- **No paid tier, no hosted anything, no commercial licence before the
  launch has produced strangers.** Revenue is a standing goal
  (HISTORY.md § The licence, chosen) and none of those is a launch step; a
  paid feature shipped to zero users is a feature nobody bought.
- **No relicensing for adoption.** Shield was chosen with the trade-off
  known. If the HN thread argues for MIT, the answer is the paragraph in
  step 5, not a change.
- **No rename.** The discoverability problem is real and it is solved by
  the tagline appearing everywhere the name does, not by a new name that
  would orphan every doc citation in the repo.
- **No container or install script before step 2 says where the stranger
  stopped.** Measure the blocker, then beat it.
- **No Product Hunt, no paid promotion, no launch-day mass posting.** Wrong
  audience, wrong signal, and a launch that lands everywhere at once cannot
  say which channel worked.
- **No Windows run as a gate.** CI is the Windows evidence until somebody
  with a Windows box turns up, and the Show HN comment says exactly that.
