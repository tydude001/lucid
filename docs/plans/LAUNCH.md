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
  Steps 1, 2 and 4 can overlap; 3 gates 4, and 2 and 4 gate 5.
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
- **CI runs on three OSes and is green on Gitea**; the GitHub mirror is one
  sync behind (`ddf56cf`, wiki `lucid-portability`). The three-OS suite is
  what lets step 2 ask a Mac to try it at all.

## Step 1 — the launch asset: a watchable closed loop

Built — see HISTORY.md § The launch clip. The recorder, four scored takes and
a 60 s cut exist; the narration is a placeholder in Tyler's cloned voice
until he reads the script, and the 9:16 re-author is not made.

**What it is.** One screen recording, 60–90 seconds cut and the full run
uncut, of the agent pane in the workspace driving a brief from `lucid init`
to a verified render. The cut version is what every channel below posts; the
uncut one is the link under it for anyone who wants to check it was not
staged. The pitch is the thing itself: an agent on a timeline, the render
checking itself against the edit, and no cloud in the frame.

**Footage rule.** The recording shows only footage lucid owns — the generated
demo project, or Tyler's own recorded material (the co-hosted recording once
the second mic is routed, wiki `lucid-second-mic`). **Never a frame of
Scream.** CLAUDE.md's committed-image rule is about the repo, but a launch
clip is more public than a README and the same reasoning applies: a
promotional video of copyrighted film clips invites the one argument the
launch does not need. The real-footage trial's *numbers* are quoted in the
post (9 of 9, 45.23s, similarity 0.984, 123 of 123 heard); its *frames* stay
in `~/lucid-work/agent-trial/`.

**Make it with lucid.** The recording is a screen capture (OBS, which is
already set up for the show), and the cut is done in lucid — the making-of
is a second post for free, and "the launch video was cut by the tool" is a
line that survives scrutiny only if it is true. Captions burned, because
every platform below autoplays muted.

**What it must show, in order**, so the 60 seconds carries the argument:
1. the brief, typed into the agent pane in plain language;
2. `import` and `transcribe` landing in the assets tab;
3. the cut — a retake struck through in the transcript, the timeline
   redrawing;
4. picture hung off phrases, the shot sheet coming back as an image the agent
   reads;
5. `export`, then `verify` and `check_frames` reporting agreement — the
   "it checked its own work" beat is the one no competitor has;
6. a title card, made by `card_new`, saying the name and the tagline.

**The instrument already exists.** `scripts/agent_trial.py` runs exactly
this loop; what it lacks is a viewer. The recording is of the *workspace*
pane rather than a terminal, because the workspace is what a stranger will
open first, and the README's screenshot is of it. Drive the trial's own
brief through `POST /api/agent` (the panel's route) so the run in the video
is the run the trial measured — no second script, no drift.

**Done when:** the cut exists at a canvas the channels take (1920x1080 for
X/Bluesky/HN links, and a 9:16 re-author for anything vertical — the aspect
swap is lucid's own feature), the uncut run is on a share link, and both are
viewable on Tyler's phone.

## Step 2 — one stranger's run, on a Mac

**What it is.** A person who is not Tyler clones the repo, runs `uv sync`,
`lucid doctor`, and docs/DEMO.md end to end on a machine Tyler does not own,
and reports every ✗ and every wrong number. A Mac, because that is where the
HN / X / Claude Code audience mostly is, and lucid has never been run on one
by anybody (README.md § Requirements says so, and must keep saying so until
this step passes).

**Why it gates Show HN.** The launch thread is where first-run failures are
reported publicly and permanently. Each "doctor said ✗ five times" comment
costs more than the post earns, and the fix — a resolver, a font, a melt
path — is a one-line change if it is found the week before. Portability
steps 4–5 (measure melt, libass and magick per OS) are the deep version of
this; step 2 here is the shallow one: does the two-minute demo reach a
verified render, yes or no, and where did it stop.

**Who.** Anyone with a Mac and an hour; a friend, a colleague, a Discord
acquaintance. The ask is scripted so it costs them nothing to think about:
"clone this, run these four commands, paste me the output of each, stop at
the first failure." `lucid doctor`'s output is designed to be that paste.

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

**Done when:** one Mac run reaches `verify` agreeing with the timeline, its
queue is closed or recorded, and README.md's "never been run on macOS"
sentence is replaced by what was measured.

## Step 3 — the flip, and the ten minutes after it

Tyler's hand, in this order, the same afternoon:

1. Sync the GitHub mirror so the public repo is at the tip (wiki
   `git-server.md` § GitHub push mirrors — **never `git push --mirror`**).
2. Flip `tydude001/lucid` public.
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
6. Tag a release. `v0.21.0` is the version in `pyproject.toml`; a GitHub
   release with notes gives the directories in step 4 something to cite and
   the HN post a permalink that will not move. Release notes are the
   HISTORY.md section names since the last tag, one line each — not a
   changelog, which the repo does not keep on purpose.
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

**Done when:** the public URL unfurls with the image and the tagline, the
Security tab shows "Report a vulnerability", and a release exists.

## Step 4 — the MCP directories, listed quietly

"An MCP server that edits video" is a category of one, and the MCP ecosystem
is the one channel where lucid's shape is the pitch rather than a curiosity.
List it a week *before* Show HN so the first strangers arrive in ones and
twos, with time to fix what they find.

- **The official MCP registry** (`registry.modelcontextprotocol.io`) — a
  `server.json` in the repo and a publish through its CLI. Check its current
  docs at the time; the mechanics have changed more than once since it
  launched, and this plan states the *step*, not the command.
- **The community directories** — PulseMCP, Glama, Smithery, and a pull
  request to the `awesome-mcp-servers` list under its media/video heading.
  Each takes the repo URL, the description and the release; none needs
  anything built.
- **A Claude Code plugin.** The agent pane already spawns `claude` against a
  generated MCP config (`webui._agent_bin`), so the one-command install for a
  Claude Code user is a plugin manifest naming `lucid mcp` as its server.
  This is lucid *being* a plugin, which PLAN.md's non-goal ("a plugin system
  before there are two users") does not touch — that non-goal is about lucid
  *having* plugins. The manifest is a file; verify the current plugin
  manifest and marketplace format against Claude Code's docs at the time
  rather than from memory, the same rule as the registry.

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
> start to finish: [clip] / [uncut run]. Two things people will ask:
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
