# proofcut — showing the whole film

Provenance: Tyler asked on 2026-09-15 whether the repo highlights that
proofcut can make an entire video, not just trim one, and to consider renaming
it again in that light. It had just been established that "several YouTube
videos and the launch video, almost entirely with proofcut + Claude Code" is
not yet true (docs/plans/NATIVE.md § Provenance). This is the answer, written
as a plan. Sources: README.md, docs/MANUAL.md and docs/DEMO.md as of
`b42af9f` (v0.24.0); both trial briefs (TRIAL.md); HISTORY.md § The Scream
native rebuild; docs/plans/RENAME.md; and a sweep of the official MCP registry
and five name candidates run the same day.

Status lives **only** in the wiki's Open items table; this file never carries
a status header. When a step ships, HISTORY.md gets a named section and the
step here gains a one-line pointer.

**The three findings that frame it:**

1. **The strong claim is true and the obvious wording of it is false.**
   "Recordings in, a finished and mastered film out of one `proofcut export`,
   with no NLE and nothing after it" is measured as of today, on both essays
   (NATIVE.md § What "cut with proofcut" means here; HISTORY.md § The Scream
   native rebuild). "Generates a video from scratch" is not. proofcut writes no
   script and makes no footage. It also puts proofcut in the most crowded
   corner of the registry. Of the official registry's first 100 results for
   `video` on 2026-09-15, about fifteen distinct servers make a video from a
   script, topic or prompt. One reads *"Script in, finished 1080p narrated
   video out"* and another *"Narrated, captioned videos from a topic or
   script"*. A reader meets proofcut's whole-film line next to those. Only the
   word **proof** separates it there.
2. **The unattended-agent evidence covers the front half of a film only.**
   Both trial briefs (the demo, 2026-08-25, and real footage, 2026-09-03)
   asked for cuts, b-roll, captions, a render and a check. Neither asked for
   music, a card, a hold, a cold open, an end card or a loudness target. The
   two essays were rebuilt by `assemble_*_native.py`, scripts of proofcut
   commands written in Claude Code sessions, not by an agent handed a brief.
   So "an agent makes a whole film" is **unmeasured**, and nothing may say it
   until step 4 measures it.
3. **Every document a newcomer reads predates the finishing half.**
   - **README.md:** "music" appears three times, all as MLT's job in a table.
     `head`, `hold`, the passages and `--loudness` are absent.
   - **MANUAL.md:** zero occurrences of "music" or "loudness", and no section
     for `proofcut music`, `head` or `hold` (§ Cards, cues and tails is the
     nearest).
   - **DEMO.md:** mentions none of them.
   - **The listings:** `pyproject.toml`, `server.json` and both plugin
     manifests say *"cut by transcript, hang b-roll off phrases, render, then
     verify"*.

   The features shipped in v0.24.0, and every description of proofcut
   predates them.

## What may be said, and when

| Claim | True today? | Made true by |
|---|---|---|
| proofcut takes recordings to a finished, mastered film in one export | **yes**, measured on two essays | nothing |
| an agent cuts, hangs b-roll, captions, renders and checks, unattended | **yes**, 9 of 9 twice (TRIAL.md) | nothing |
| an agent makes the whole film unattended (music, cards, master) | no, never asked of one | step 4 |
| a stranger can make a whole film in the two-minute demo | no, the demo stops at a verified cut with b-roll | step 3 |
| "my essays are cut with proofcut + Claude Code" | no, neither is posted | step 5, Tyler's hand |
| "the launch video was cut with proofcut" | no | NATIVE.md Part B, not this plan |
| proofcut generates video / makes a video from scratch | **no, and never** | nothing; it makes no footage |

## Step 1 — the README and the manual say it

**The tagline keeps "proves its cuts" and gains the film.** Proof is the
differentiator (finding 1), so it stays the first thing read. Recommended:

> **An AI video editor that proves its cuts.** Your recordings in, a
> finished, mastered film out: cut by transcript, with b-roll, cards, music
> and captions, and every step an agent can call. proofcut renders on your
> own machine, then transcribes the render and checks that it says what the
> edit says.

It does not say "an agent makes your film", which is finding 2's unmeasured
claim, until step 4 has measured it.

**A "From recordings to a finished film" section**, directly under the hero
clip and before § Why proofcut. It lists each stage as the one command that
does it, in the order a film is built:

1. import and transcribe
2. cut by words
3. b-roll by phrase (`cue`)
4. title and end cards (`card new`, `tail`)
5. a cold open (`head`)
6. the film's own audio in a gap (`hold add`) or under the narration
   (`hold under`)
7. music as placed passages, crossfaded and levelled under the VO (`music`)
8. captions
9. `export --render --loudness -16`
10. `verify`

Then one sentence: two essays of five to six minutes were rebuilt this way and
measured against their delivered files. The sentence gives no titles and no
frames until they are posted (step 5), and never a frame of footage proofcut
does not own (CLAUDE.md § Conventions, the screenshot rule).

**The two trials move up**, beside the hero clip rather than as one line in
§ Documentation. The one on real footage gets named, because the demo reads as
a toy.

**§ What it does gains a Sound group**:
- music passages and rotation
- film audio held in a gap and under the VO
- `attenuate`
- `export --loudness`

**MANUAL.md gains the sections it is missing**: `music` (passages, rotation,
`under`), `head`, `hold` (`add`, `under`, `check`) and `--loudness`. Where
§ Cards, cues and tails already covers `tail` it is extended, not duplicated.
Each README line links its section.

**Done when:** the README's first screen names the film, and each command in
the new section has a manual section a link resolves to. The
`capture_screenshots.py` shots are unaffected, since no image changes.

## Step 2 — the one-line description, everywhere it is copied

The same string lives in five places:
- `server.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json` (twice)
- pyproject.toml's longer line

LAUNCH.md § Step 4 measured that this line is what gets found and what sells,
in the query that matters. Recommended (92 characters; the registry schema's
`description` caps at 100, read off the published `2025-12-11` schema):

> Local-first AI video editor: recordings to a finished film, cut by
> transcript, then verified

The GitHub repo description follows it. **It rides the next release rather
than earning one.** Changing a description makes nothing new callable. The
registry republish is Tyler's hand (memory:
`public-surface-actions-are-tylers-hand`).

Two drafts follow it too:
- `~/proofcut-work/spikes/launch-listings/LISTINGS.md` (the awesome-list line
  and the Show HN first comment)
- `~/proofcut-work/spikes/launch-release/NOTES.md`

The awesome-list PR goes in on 2026-09-20 at the latest (wiki `lucid-publish`).
Its line is copied from the description, so **steps 1–2 land before then**.

## Step 3 — the demo makes a whole film

DEMO.md is what a stranger runs first, and the Mac and Windows kits and CI's
two demo workflows all run it. Today it ends at a verified cut with b-roll;
captions are an optional extra at the bottom of the page.

`make_demo.py` gains a **generated music bed**: a few seconds of ffmpeg-made
chords, so there is still no media to licence (the script's own rule).
DEMO.md gains four commands:
- a title card
- the bed under the VO with a fade
- an end card
- `--loudness -16` on the export

`verify` and `frames` stay last, and the new commands' output is checked
the same way theirs is. The two-minute budget is measured
rather than assumed, and if the new commands break it the walkthrough says so.

`trial_check.py` judges the kits' run, so it gains checks for the bed and
the master. Otherwise a render missing music passes the CI demo at exit 0,
which is `MUSIC_KEY`'s own trap (CLAUDE.md, the A2 bullet). The repo is public,
so the demo workflows cost no Actions minutes.

**Done when:** DEMO.md's own commands produce a render that
`export --loudness` measures after mastering at the target, with the bed audible under the
VO by measurement, on this box and on CI's three runners.

## Step 4 — the third trial: a whole film, unattended

The same instrument (`scripts/agent_trial.py`), client, confinement and brief
rule: the goal, never the steps. The brief adds what a finished film has:
- music under the narration, out of the way of the words
- a title, and an end card naming the channel
- mastered for YouTube

`score()` gains the checks those need, each judged off the delivered file and
the project, never off the agent's report:
- `music_placed`: the bed on the render by tone correlation, not by the
  manifest, which says what a render *would* carry
- `card_present`
- `tail_present`
- `loudness_on_target`: within 1 LU, `export --loudness`'s own refusal band

The cost is measured and recorded like the first two.

Run it on step 3's demo media first, then on real footage Tyler owns. Its
material rule is the trial's own (TRIAL.md § The second trial over real
footage). Its result goes in TRIAL.md as a third run, whether it passes or not.
**A failing run is a queue, not a reason to drop the claim.**

**Done when:** a run passes every check, and the README may then say "an agent
makes the whole film". Until then the README says what step 1 says: an agent
does the cut, and proofcut takes the recordings to a film.

## Step 5 — made with proofcut

The claim that persuades is a film someone can watch.

- **Tyler posts** an essay whose delivered file came out of `proofcut export`
  with nothing after it. That is NATIVE.md's definition, and wiki row
  `proofcut-native` holds what is still open on each essay, Scream's missing
  duck among it.
- **The video description** carries "cut with proofcut" and the repo link.
  LAUNCH.md § Step 6 already names the films as the slow, honest channel.
- **The README gains a "Made with proofcut" line** linking the upload: a link,
  never an embedded frame of a film proofcut does not own. The
  `assemble_*_native.py` script and its measurements against the delivered file get
  linked or summarised as evidence that the claim was checked.

## The rename, considered

**Recommendation: keep `proofcut`.** The question is fair, because a name
says what a thing is. Five reasons settle it:

1. **The name already covers the film.** In editing, the *cut* is the
   finished film: rough cut, final cut, director's cut. "proofcut" reads as
   "a proven film" as readily as "a proven trim".
2. **Under finding 1 the name is the differentiator.** A whole-film pitch
   shares the registry with fifteen generators. A name built from *film*,
   *reel* or *video* would blend into them; *proof* is what they do not say.
3. **The name is not what gets found.** LAUNCH.md § Step 3 measured that the
   description and tagline are, and RENAME.md's own premise was a collision,
   never a description. The whole-film message belongs in steps 1–2, which
   cost an evening, not in a name.
4. **The only rename that was ever justified had a mark behind it.** Lucid
   Software's live LUCID trademark and its same-named MCP server were
   RENAME.md's whole case. Tyler's USPTO search for `proofcut` on 2026-09-13
   found no results (HISTORY.md § The rename), so nothing like that exists
   against it. The two-word `proof cut` was never searched; that is a cheap
   check to run before Show HN, not a reason to rename.
5. **Two renames in a week is its own signal**, to the registry, Glama, the
   awesome-list maintainers and Show HN alike. The first comes across as care;
   a second looks like a project that doesn't know what it is.

**What it would cost, measured today.** Occurrences of `proofcut` in the tree:

| Area | Occurrences |
|---|---|
| `src/` | 676 |
| `tests/` | 537 |
| `docs/` | 709 |
| `scripts/` | 226 |
| root docs, pyproject and `server.json` | 169 |
| `.github/` | 40 |
| `.claude-plugin/` | 12 |
| `PROOFCUT_*` variables | 23 |

Off the tree, RENAME.md's whole list again:
- a second registry deletion
- the `v0.23.0` release and its clip URL
- re-recorded launch assets
- both kits and the pinned tester issues
- this box's `60-proofcut.conf`, its working copy and memory directory
- the `~/proofcut-work` gathering from 2026-09-14

That last item used `MOVED.tsv` because the first rename moved thirteen
directories. None of the list is hard, and all of it buys nothing finding 1
doesn't already give.

**Candidates swept anyway** (`~/proofcut-work/spikes/name-sweep/sweep.sh`,
2026-09-15). The domain column is left out: `rdap.org` answered 302 for every
`.dev` and `.com`, including names known to be taken, so it measured nothing.

| Name | Registry | PyPI | npm | GitHub repos | Says more than `proofcut`? |
|---|---|---|---|---|---|
| `provecut` | 0 | free | free | 0 | no; the same idea, less natural |
| `filmproof` | 0 | free | free | 1 | "film" joins the generators' vocabulary |
| `finalproof` | 0 | free | free | 1 | reads as proofreading |
| `wholecut` | 0 | free | free | 1 | a cut of meat |
| `cutproof` | 0 | free | free | 9 | reads as "cut-resistant" |
| `proofreel` | 0 | free | **taken** | 6 | no |

None is clearer than the current name, and none is a better search term.

**What would reopen it:** a live mark on `proofcut` in classes 9 or 42, or a
product trading under the word in video, or a launch thread that confuses
proofcut with something named like it. The same test RENAME.md applied, the
same way.

## Decisions for Tyler

Grouped by what is actionable today; each carries a recommendation.

**Actionable now:**
1. **Keep the name** (recommended), or re-open RENAME.md's sweep with a brief.
2. **The tagline and the description.** Step 1's and step 2's wording
   (recommended), or a variant. The one constraint is that neither says
   "generate" or "from scratch".
3. **Steps 1–2 before the awesome-list PR on 2026-09-20** (recommended).
   Otherwise the list carries the front-half line for as long as the list
   exists.

**Needs a run first:**
4. **Step 4 does not gate Show HN** (recommended). It gates only the README
   sentence "an agent makes the whole film". The launch's evidence is already
   the closed loop, and a queue from a failing third run should not hold a
   dated launch.

**Tyler's hand:**
5. **Which essay is posted first** is the wiki row `proofcut-native`'s call,
   not this plan's. This plan only needs one to be up for step 5.

## What this plan deliberately does not do

- **No "generate", "from scratch" or "text to video"** in any string proofcut
  publishes. It makes no footage, and the claim would land it among the
  generators, where it loses.
- **No footage-generation feature** to make that wording true. It would drop
  proofcut's reason to exist, which is checking the render against the edit.
- **No claim about the launch clip.** That is NATIVE.md Part B, step B7.
- **No rename** (§ The rename, considered).
- **No frame of either essay in the repo or the README.** A link to the posted
  film is the most it gets.
