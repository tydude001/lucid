# The rename: lucid → proofcut

Written 2026-09-13, the evening the repo went public, for a fresh session to
work through. Status lives **only** in the wiki's Open items table
(`wiki/README.md`, id `lucid-rename`); this document never carries a status
header. When a step ships, HISTORY.md gets a named section and the step here
gains a one-line "Shipped — see HISTORY.md § <name>".

## Why, and why now

LAUNCH.md § What this plan deliberately does not do said **No rename**, on
two grounds: the discoverability problem was solved by the tagline, and a
new name would orphan every doc citation. Both grounds were true and the
decision was still wrong, because it never weighed the third fact:

- **Lucid Software** (Lucidchart) ships an official MCP server whose registry
  name is literally `Lucid` — `app.lucid.mcp/lucid` in the official registry,
  first result for the word there, on GitHub's MCP registry, on PulseMCP, and
  as a Microsoft connector. The official registry's own search for `lucid`
  returns it above `io.github.tydude001/lucid`.
- Lucid Software holds a **live US trademark on the bare word LUCID** for
  software services (serial 88808001, class 42), beside LUCIDCHART and
  LUCIDSPARK. Two MCP servers named lucid in one registry, used from the same
  AI clients, is as confusable as a name gets — and the cure for a
  cease-and-desist is this same rename, done after Show HN with a thread
  permalink, directory rows and strangers' configs all pointing at the dead
  name.

LAUNCH.md named exactly one thing that would reopen the question: "the HN
thread confusing the two". The registry does it structurally, before any
thread exists.

**Why now is the cheapest it will ever be.** After a few hours public, the
whole outward surface is: the GitHub repo, the `v0.22.0` release with the
clip and two uncut runs, two pinned issues, and the registry entry. Show HN
is unposted, the awesome-mcp-servers PR is unopened, Glama has not indexed
it, there is no PyPI package, and no stranger has filed anything. Every one
of those is a redirect or a re-publish today and a broken link next month.

**Why `proofcut`.** Twenty-two candidates were swept
(`~/lucid-work/name-sweep/sweep.sh`) against the official MCP registry,
PyPI, npm, GitHub repos and account names, domains, Bluesky, and a plain
web search for anyone trading under the word. Two survived clean:
`proofcut` and `answerprint`. `proofcut` says the product in eight
characters — a cut, and proof that it is right, which is the whole
differentiator ("render, then verify") — and types well as a CLI and an
env-var prefix. `answerprint` is the film-lab term for the same idea and had
zero collisions anywhere, but nobody outside film knows it and "print" reads
as paper in a registry row. Eliminated with a reason each: `reelproof`
(funded AI-video company), `picturelock` (an LLC at picturelock.app),
`matchcut` (Netflix research repo), `cleancut` (well-known Rust educator),
`editbay` (live trademark DPS EDITBAY), `checkprint` (bank-check printing),
`splicer`/`cutroom`/`dailies`/`conform` (taken on PyPI or npm).

What is free as of 2026-09-13: `proofcut` on the registry (0 hits), PyPI,
npm, GitHub user/org, `proofcut.dev`, `proofcut.org`, the Bluesky handle.
Taken: `proofcut.com`, `proofcut.app` (holder not checked). One hackathon
repo `hey-Chloe/proofcut` (0 stars, turns transcripts into topical segments)
and `gongyu/ProofCut` (1 star) exist; neither is a product or a mark.

**One check is still open, and it is Tyler's before step 1 starts:** the
trademark search was web-search only — Justia and uspto.report both refuse
automated fetches. Run `proofcut` through <https://tmsearch.uspto.gov> and
look for any live mark in classes 9 or 42. Nothing found means proceed; a
live mark means the fallback is `answerprint` and this plan is re-read with
that word.

## How to work this plan

- **It is one rename, landed in one release, `v0.23.0`.** A half-renamed
  tree (new CLI, old manifest name; new package, old env vars) is worse than
  either whole state, because every stale string looks deliberate. The
  steps below are ordered so the tree is never committed half-done, but
  they are one piece of work, not a queue to be paused between.
- **Never a blind global replace.** `lucid` is also the first half of
  thirty real directory names on this box (`~/lucid-final-cut`,
  `~/lucid-work`, `~/lucid-archive`, …), the name of the company this rename
  is moving away from (`lucidsoftware`, `lucid.co`, Lucidchart — quoted in
  LAUNCH.md and PRIOR-ART.md as a record of what was measured), and a
  version's worth of GitHub URLs that redirect. § The guard list is what a
  replace must leave alone, and the diff is reviewed against it before the
  commit, category by category.
- **Records are not restamped.** HISTORY.md (572 mentions), TRIAL.md, and
  the closed plans in `docs/plans/` (DAYDREAM, POLISH, STUDIO) said `lucid`
  when they were written and still do. They gain a one-paragraph preface,
  and HISTORY.md gains a new `##` section; nothing inside an existing
  section changes. A dated measurement in a living document (LAUNCH.md's
  "Measured 2026-09-13: Glama's search for the name…") is a record too and
  stays. **A Markdown link is a path and must resolve** — a link into
  `src/lucid/` anywhere, record or not, is updated; the sweep found none
  today, so this is a check, not a job.
- **Tyler's hand is every public-surface action**, the same list the launch
  had: the Gitea rename, the push, the GitHub rename, the release publish
  and asset uploads, the registry publish and the old entry's deletion, the
  issue edits. The session prepares each one as a single pasted line and
  reads the result back; it does not run them (memory:
  `public-surface-actions-are-tylers-hand`).
- **`ruff --fix` runs after every Python edit** and will delete an import it
  thinks unused; the package move is `git mv` plus import rewrites, and the
  suite is what says the rewrites landed. Never `ruff format`.
- **The suite is ~10 minutes; run it to a file, backgrounded, and read the
  summary line from the file** (memory: `run-the-suite-to-a-file-not-a-pipe`).
  Do not edit source while it runs.
- **The move of Tyler's data is asked, never assumed.** Step 5 migrates the
  pinned dogfood projects and edits this box's environment; each of those is
  named before it is run.

## The surface, measured 2026-09-13

Counts are case-insensitive hits of the word, before any edit. They are the
size of the job, not a checklist — the checklist is the steps.

| Area | Files | Hits | What the hits are |
|---|---|---|---|
| `src/lucid/` (→ `src/proofcut/`) | 100 | 655 | the package dir, 15 files importing it, `name="lucid"` in `server.py`, `prog="lucid"` in `cli.py`, `MANIFEST_NAME = "lucid.json"`, the OTIO metadata key, the MLT identity strings, the cookie, the theme event, the drag MIME, twelve `tempfile` prefixes, `RENDER_SCRATCH`, two `server_version` strings, the web chrome (`<title>`, `.brand`, three hints), and docstrings |
| `tests/` | 178 | 483 | 70 files import the package; 11 files / 44 lines assert on the literal (`"lucid"`, `lucid.json`, `lucid_token`, `lucid:theme`, `lucid-review`, `x-lucid`, `"lucid <version>"`) |
| `scripts/` | 7 | 181 | the two kits (`mac_trial.sh` 45, `windows_trial.ps1` 38), `agent_trial.py`, `make_demo.py`, `capture_screenshots.py`, `record_run.py`, `trial_check.py` |
| `docs/` | 12 | 1239 | HISTORY.md 572 and TRIAL.md 25 (records); PLAN.md 191, MANUAL.md 120, DEMO.md 39, PRIOR-ART.md 44, NEXT.md 4, LAUNCH.md 48, PORTABILITY.md 32 (living); DAYDREAM 27, POLISH 19, STUDIO 15 (closed plans, records) |
| root docs | 4 | 157 | CLAUDE.md 76, README.md 65, CONTRIBUTING.md 12, SECURITY.md 4 |
| `.github/` | 8 | 37 | ci runs `uv run lucid …`; mac/windows-demo name `LUCID_TRIAL_REPORT`, `~/lucid-mac-trial`, `lucid-*-report.zip`; five issue templates quote commands and `/plugin install lucid@lucid` |
| launch listings | 4 | 25 | `pyproject.toml` (name, script, three URLs), `server.json` (name, title, two URLs), `.claude-plugin/plugin.json` and `marketplace.json` (name, displayName, `mcpServers` key and args, URLs), `LICENSE` line 1's Required Notice URL, `glama.json` (none) |
| `.claude/skills/verify-live` | 2 | 4 | the SKILL.md description, `uv run lucid -C … web`, the `lucid:theme` event |
| env vars | — | 21 distinct | `LUCID_MELT` 35, `LUCID_FACE` 32, `LUCID_WHISPER` 28, `LUCID_TTS_VOICE` 27, `LUCID_TTS` 25, `LUCID_VLM` 22, `LUCID_MAGICK` 14, `LUCID_TTS_MODEL` 13, `LUCID_AGENT_BIN` 7, `LUCID_TRIAL_*` (six), `LUCID_TAILSCALE`/`_ENV`, `LUCID_AUTO_EDITOR`, `LUCID_VLM_DEVICE`, `LUCID_TTS_DEVICE`, `LUCID_BROWSER`/`_ENV` |

Off the tree, and each is a step below:

- **On disk here:** 29 `lucid.json` manifests under `~/lucid-*` and
  `~/lucid-work/*`; `~/.config/environment.d/60-lucid.conf` setting four
  `LUCID_*` variables (`LUCID_TTS_VOICE` is set somewhere else — no shell rc
  on this box carries it; find it before step 5); the auto-memory directory
  `~/.claude/projects/-var-home-tyler-projects-lucid/`; the
  `~/.claude.json` project entry for `/var/home/tyler/projects/lucid`; the
  in-repo `.venv`, whose entry-point scripts carry the absolute path.
- **Gitea:** repo `tydude001/lucid`, its push mirror to
  `github.com/tydude001/lucid.git`, this clone's `origin`.
- **GitHub:** the repo, description, topics, social preview
  (`docs/img/edit-mode.png` — which shows the `.brand` span, so it is
  regenerated, not kept), release `v0.22.0` and its two assets
  `lucid-v0.22.0-uncut-*.mp4`, the README clip's `user-attachments` URL,
  issues #1 and #2 (pinned, labelled `mac-test`/`windows-test`), the
  `mac-test`/`windows-test` labels, private vulnerability reporting.
- **The registry:** `io.github.tydude001/lucid` 0.22.0, `active`,
  published 2026-09-14T01:17Z. `mcp-publisher status --status deleted` exists
  (v1.8.1, `--all-versions`, `--message`), so the old name can be retired
  rather than left as a second listing.
- **The recordings:** both uncut runs and the 47-second clip show `lucid`
  in the terminal and the bar. `~/lucid-work/launch-v4/record_full.py`,
  `mcp/record_mcp.py`, `clip.py` and `uncut/encode.py` are the scripted
  pipeline (HISTORY.md § The launch clip, approved; § The uncut runs).
- **The wiki:** `projects.md`'s row, `README.md`'s five `lucid-*` open
  items, `git-server.md`'s mirror row, `tooling.md`, `decisions.md`,
  `log.md`. **Launch drafts** in `~/lucid-work/launch-release/` (NOTES,
  MAC-ISSUE, WINDOWS-ISSUE, FLIP-SESSION) and
  `~/lucid-work/launch-listings/LISTINGS.md` (the awesome-list line and the
  Show HN draft).

## Decisions

Each is stated as decided, with the reason, so the working session does not
re-litigate. Where a step finds the reason wrong, it says so in HISTORY.md
and does the other thing.

1. **The manifest is `proofcut.json`, and an old project is refused, not
   migrated, by `open`.** `Project.open` already refuses an old *schema*
   and never migrates one (CLAUDE.md § Conventions), because it backs
   `info` and `status`. The filename gets the same rule: a directory with
   `lucid.json` and no `proofcut.json` refuses with a message naming
   `proofcut migrate`, and `migrate` gains a **filename step that runs before
   the version steps** — it is not a schema bump (`SCHEMA_VERSION` stays 4;
   the number says what the keys mean, not what the file is called), so it
   is not a `_MIGRATIONS` entry keyed by version. `migrate --plan` reports
   it. The picker's scan (`webui.py`, `child / MANIFEST_NAME`) must classify
   such a directory as `needs_migration`, not as not-a-project — check
   that outcome exists for it rather than assuming the schema check catches
   it. `_backup_manifest` keeps the old file as the backup it already
   writes.
2. **The OTIO metadata key is written as `"proofcut"` and read as either.**
   `timeline.py` stamps `clip.metadata["lucid"]` and
   `timeline.metadata["lucid"]` into every `project.otio`, and reads them
   back. A reader that accepts only the new key breaks every undo: the
   snapshots in `cache/history/N.otio` carry the old key forever and
   `restore` puts one back whole. So the reader takes `"proofcut"` and falls
   back to `"lucid"`, permanently and in one helper, and the migration step
   rewrites the *live* `project.otio`'s keys so a migrated project is clean
   on its face. The writer writes the new key only. A test restores a
   snapshot carrying the old key and reads it.
3. **Every `LUCID_*` variable becomes `PROOFCUT_*`, and `doctor` names any
   `LUCID_*` still set.** Twenty-one names, no aliases in the resolvers —
   a resolver that reads both is two facts, and the rule since 2026-09-10 is
   that a resolver reads its variable and nothing after. `doctor` gets one
   row: every `LUCID_*` in the environment, listed with the new name beside
   it, as a note and never a ✗ (an absent optional capability is
   "unavailable", never a failure). Without that row a stranger's
   `60-lucid.conf` silently loses face detection at exit 0, which is the
   same shape as the venv that lost torch.
4. **The package, module and CLI all rename; the on-disk working paths do
   not.** `src/lucid/` → `src/proofcut/` by `git mv` so history follows; the
   CLI is `proofcut`; `-m proofcut.cli` in the generated MCP config. But
   `~/lucid-work`, `~/lucid-archive`, `~/lucid-final-cut` and the other
   pinned directories on this box **stay exactly where they are** —
   manifests store absolute paths, six of them point into
   `~/lucid-final-cut/proj`, and CLAUDE.md § Conventions already says moving
   any of them means rewriting manifests first. New spikes may go under
   `~/proofcut-work/` or keep going under `~/lucid-work/`; the convention
   sentence in CLAUDE.md says which (recommend: keep `~/lucid-work`, one
   scratch root on one machine is not a public surface). **`RENDER_SCRATCH`
   does change**, to `~/proofcut-render` — it is a code literal a
   stranger's install creates, and `_SCRATCH_NAME` matches the subdirectory
   pattern, not the root, so the sweep is unaffected. This box's
   `~/lucid-render` is deleted by hand after the first render lands in the
   new root.
5. **Internal identifiers rename too, in the same commit as their
   readers.** The cookie `lucid_token` → `proofcut_token` (everyone is
   logged out once; there is nobody). The theme event `lucid:theme`, the drag
   MIME `application/x-lucid-asset`, the twelve `tempfile` prefixes, both
   `server_version` strings, the MLT `"description"` and the `uuid5` seed
   `lucid:{name}` (a different UUID in every generated document; nothing
   reads it back). **Three places state the MCP server's own name and must
   move together:** `server.py`'s `name="lucid"`, the `"lucid"` key
   `webui.py` writes into the generated MCP config, and `agent.js`'s
   `servers.find(s => s.name === "lucid")` — that check is what draws the
   "no tools" banner, so a mismatch is the silent-prose failure HISTORY.md
   § The agent panel had no tools at all describes.
6. **The working copy moves to `~/projects/proofcut`, and the auto-memory
   directory moves with it.** Working copies are named after the repo
   (`~/.claude/CLAUDE.md` § Repo conventions), and the repo is renamed on
   Gitea. The memory directory is keyed by the absolute path, so
   `~/.claude/projects/-var-home-tyler-projects-lucid/` is renamed to
   `-var-home-tyler-projects-proofcut/` in the same breath or every memory
   in it is unreachable from the new path. `.venv` is rebuilt (`rm -rf
   .venv && uv sync`) because its scripts carry the old absolute path.
7. **The version is `0.23.0`**, bumped in all six literals with `uv sync`
   behind it (`tests/test_version.py` holds them together; its
   `"lucid <version>"` assertion becomes `"proofcut <version>"`). Something
   new becomes callable — `proofcut` — which is the minor-bump rule. The
   annotated tag names HISTORY.md § The rename. `v0.22.0` and its assets are
   left exactly as they are: a release is a record.
8. **Git history is not rewritten.** The two `filter-repo` passes were for
   addresses and the MIT grant — things that must not be public. An old name
   in old commits is neither, and every pre-rewrite hash in
   `~/lucid-archive/*.commit-map` is already a liability nobody wants a
   third of.
9. **Both recordings are re-made, not kept.** The clip is the README's
   first screen and the launch asset; a first screen that prints a name the
   repo no longer has is the wrong first impression. The pipeline is
   scripted end to end, so this is an evening, not a rebuild: the same
   brief, the same media, the same encode settings, and the same
   path-and-name readback before upload (HISTORY.md § The uncut runs). The
   README's clip URL is a `user-attachments` upload into the `v0.23.0`
   release draft, published in place — LAUNCH.md § Step 3's rule, kept.
10. **The screenshots are regenerated, never edited.** Every README
    screenshot shows the `.brand` span; `scripts/capture_screenshots.py` is
    the only way they are made (CLAUDE.md § Conventions), and its checks
    stay. The social preview is re-uploaded from the new `edit-mode.png`.

## Steps

Steps 1–4 are the session's, on `main`, committed and not pushed. Step 5 is
this box. Steps 6–8 are Tyler's hand with the session preparing each line.
Step 9 closes the record. **The USPTO check in § Why is before step 1.**

### Step 1 — the tree

Shipped — see HISTORY.md § The rename.

One logical change, landed as a few reviewable commits (package move; code
literals; tests; scripts and CI; docs), each with the suite or the relevant
tests green before the next. The order matters only in that the package
move goes first, so every later diff is against importable code.

1. **The package.** `git mv src/lucid src/proofcut`; rewrite `from lucid`/
   `import lucid` in the 15 `src` files and 70 `tests`/`scripts` files;
   `pyproject.toml` `name`, `[project.scripts]` (`proofcut = "proofcut.cli:main"`),
   the three URLs; `rm -rf .venv && uv sync`; `uv run proofcut --version`.
   Watch `ruff --fix` on every touched file.
2. **The literals** (decisions 1–5): `MANIFEST_NAME`, the migration's
   filename step and `open`'s refusal, the picker outcome, the OTIO helper
   with its fallback, `prog=`, `name=`, the three-place server name, the
   cookie, the event, the MIME, the `tempfile` prefixes, `server_version`
   twice, the MLT strings, `RENDER_SCRATCH`, the 21 env vars, `doctor`'s
   legacy-variable row, `cli.py`'s `f"lucid: {exc}"`, `ops.py`'s two
   `"lucid"` defaults (13364, and `captions.py`/`timeline.py`/`mlt.py`'s
   `name: str = "lucid"`), `doctor.py`'s version row key, the web chrome
   (`<title>` and `.brand` in `index.html` and `picker.html`, the three
   import hints), `verify-live`'s SKILL.md and command.
3. **The tests.** The 44 literal lines in 11 files; the new tests decision 1
   and 2 name (a refused `lucid.json` directory, `migrate --plan` reporting
   the filename step, a restored old-key snapshot reading back); the
   `test_version` string. **Read every changed assertion for whether the
   test and the code still disagree** — an assertion rewritten to a new
   literal is a rename, an assertion loosened to pass is not, and the second
   is refused (`~/.claude/CLAUDE.md` § Working here).
4. **Scripts and CI.** Both kits (install dir, report zip, every quoted
   command), `agent_trial.py` (imports the panel's flags — check they still
   resolve), `make_demo.py`, `capture_screenshots.py`, `record_run.py`,
   `trial_check.py`; ci.yml's two commands; mac/windows-demo's variable,
   directory and artifact names; the five issue templates (`proofcut@proofcut`,
   the zip names, every quoted command, the version placeholder).
5. **Living docs.** README.md, CONTRIBUTING.md, SECURITY.md, CLAUDE.md,
   MANUAL.md, DEMO.md, PLAN.md, PRIOR-ART.md, NEXT.md, LAUNCH.md,
   PORTABILITY.md — the product name, every quoted command, every
   `LUCID_*`, the GitHub URLs (ten files carry
   `github.com/tydude001/lucid`; they redirect, and they are rewritten
   anyway, because a redirect is a dependency on nobody ever creating a
   repo of that name). Dated measurements inside them stay (§ How to work
   this plan). CLAUDE.md's first line gets the pointer to this plan; its
   § Conventions sentence about `~/lucid-work` says what decision 4 decided;
   § Things that will bite you gains the OTIO-key fallback and the
   three-place server name.
6. **Records.** A preface paragraph at the top of HISTORY.md and TRIAL.md,
   and one line at the top of DAYDREAM/POLISH/STUDIO: "This document was
   written when the project was called lucid, and says so throughout;
   nothing in it was rewritten for the rename (HISTORY.md § The rename)."
   LAUNCH.md's **No rename** bullet is rewritten to say it was decided on
   two grounds and wrong on a third, and points here.
7. **The guard list** (§ below) is grepped over the whole diff before each
   commit, and the count of each protected string is the same before and
   after.

**Done when:** `uv run proofcut doctor` prints `ok`; the full suite is green
from a log file; `grep -rniw lucid src tests scripts .github .claude-plugin
pyproject.toml server.json LICENSE README.md CONTRIBUTING.md SECURITY.md`
returns only guard-list strings; and every Markdown link in `docs/`
resolves.

### Step 2 — verify against the real thing, not the suite

Shipped — see HISTORY.md § The rename.

- `uv run proofcut init` a fresh project in `~/lucid-work/rename-check/`,
  import `scripts/make_demo.py`'s media, transcribe, cut, export, verify —
  the DEMO.md walk, by hand, reading each return.
- `uv run proofcut web` on it; the bar reads `proofcut`, the picker's title
  does, the theme toggle repaints (the event renamed on both ends), a drag
  from assets to the timeline lands (the MIME renamed on both ends), and the
  agent pane's banner says it reaches the timeline through the tools — run
  one turn and check the init event's `mcp_servers` names `proofcut`
  connected. This is a `verify-live` pass at 0ms and ~120ms dwell, not a
  DOM stub.
- `tests/test_server_stdio.py` is the MCP proof; additionally spawn `uv run
  proofcut mcp` under `claude mcp add` in an isolated `CLAUDE_CONFIG_DIR`
  and list its tools.
- **Migration on a copy.** `cp -r ~/lucid-demo/proj ~/lucid-work/rename-check/old`;
  `proofcut status` on it refuses naming `migrate`; `proofcut migrate --plan`
  lists the filename step; `proofcut migrate` renames the file and rewrites
  the OTIO keys; `status` then passes; `undo` restores a pre-rename snapshot
  and `status` still passes (decision 2's whole point).
- **The plugin from the tree.** `claude plugin marketplace add
  /var/home/tyler/projects/proofcut` in an isolated config dir;
  `claude plugin install proofcut@proofcut`; `claude mcp list` shows it
  connected. (HISTORY.md § The registry listing: `plugin details` prints
  "MCP servers (0)" for an inline server and is not the health check.)

**Done when:** each of those is a sentence in the HISTORY.md section with
what it printed.

### Step 3 — the screenshots and the recordings

Shipped — see HISTORY.md § The rename.

- `scripts/capture_screenshots.py`, all checks intact; the new
  `docs/img/*.png` show `proofcut` in the bar and no path anywhere.
- Re-run the recording pipeline in `~/lucid-work/launch-v4/` (or a copy
  beside it): `record_full.py` and `mcp/record_mcp.py` against the same brief
  and media, `clip.py` to the same 47-second shape, `uncut/encode.py` for
  the two full runs. **Read frames back for the name and for paths** before
  anything is uploaded — the terminal run's header and every tool call, at
  three timestamps each, the same way § The uncut runs did.
- Update `~/lucid-work/launch-release/NOTES.md` (the `v0.23.0` notes: one
  line per HISTORY.md section since `v0.22.0`, the first of them the
  rename), `MAC-ISSUE.md`, `WINDOWS-ISSUE.md`, and
  `~/lucid-work/launch-listings/LISTINGS.md` (the awesome-list line, the
  Show HN draft).

**Done when:** the four new media files exist, read back clean, and the
notes name them.

### Step 4 — the version

Shipped — see HISTORY.md § The rename.

All six literals to `0.23.0`, `uv sync`, `tests/test_version.py` green,
the annotated tag `v0.23.0` at the tip with HISTORY.md § The rename in its
annotation. Committed, tagged, **not pushed**.

### Step 5 — this box

Shipped — see HISTORY.md § The rename.

Each line here mutates Tyler's data or environment and is named before it
runs (memory: `verify-the-web-ui-in-a-real-browser` — `migrate` mutates his
data, ask first).

- **Migrate the pinned projects** he still uses: `~/lucid-final-cut/proj`
  first (the film's project, 63 segments, all 38 shots projecting — `film_check`
  before and after), then `~/lucid-demo/proj`, `~/lucid-kf-probe`,
  `~/lucid-scream-v2/proj`, and the settle-against copies. The 20-odd under
  `~/lucid-work/` are spikes; migrate on demand, not in a sweep — a spike
  nobody reopens is not worth a write.
- `~/.config/environment.d/60-lucid.conf` → `60-proofcut.conf` with
  `PROOFCUT_*` names; find where `LUCID_TTS_VOICE` is actually set (no
  shell rc on this box has it) and rename it there. Takes effect at the next
  login; `systemctl --user import-environment` or a fresh session in between.
  `proofcut doctor`'s legacy row should then list nothing.
- `mv ~/projects/lucid ~/projects/proofcut`; `mv
  ~/.claude/projects/-var-home-tyler-projects-lucid
  ~/.claude/projects/-var-home-tyler-projects-proofcut`; `rm -rf .venv &&
  uv sync` in the new place. `~/.claude.json`'s project entry re-creates
  itself on the first session there; the old key can stay.
- `rm -rf ~/lucid-render` once `~/proofcut-render` has taken a render.

### Step 6 — Gitea, and the push

Tyler's hand, in this order, because the mirror pushes to whatever URL it
holds:

1. **Rename the GitHub repo first** — `gh repo rename proofcut -R
   tydude001/lucid`. GitHub redirects the old URL, clones and pushes, for as
   long as nobody creates `tydude001/lucid` again.
2. Rename the Gitea repo (`tydude001/lucid` → `tydude001/proofcut`; Gitea
   redirects too). Edit its push mirror's remote to
   `https://github.com/tydude001/proofcut.git` (wiki `git-server.md`
   § GitHub push mirrors — its table row is updated in step 9).
3. `git remote set-url origin http://192.168.1.173:3000/tydude001/proofcut.git`
   in the clone; push `main` and `v0.23.0` to Gitea; Synchronize Now (the
   API call § The launch used). **One sync, with everything in it** — a
   sync touching `src/` runs ci and both demo workflows, about 250 billed
   Actions minutes (memory: `github-actions-minutes-are-metered`); say the
   number before the push, and never two pushes where one will do.
4. Confirm with `git ls-remote origin main` and the GitHub tip, never with
   the push's own output.

### Step 7 — GitHub's face

- Description stays pyproject.toml's line (it does not carry the name).
  Topics unchanged. Social preview: upload the new `docs/img/edit-mode.png`.
  Check the public URL unfurls with it, logged out.
- **Release `v0.23.0`**: create as a draft, upload the clip into its notes
  (the `user-attachments` URL the README needs), put that URL into README.md
  and push it in the same sync as step 6 if the timing allows — otherwise
  it is the one docs-only second sync, which costs nothing on a public repo
  when it touches no `src/`. Upload both uncut runs as assets
  (`proofcut-v0.23.0-uncut-*.mp4`), publish the draft in place with
  `--latest`. `v0.22.0` is untouched.
- **Issues #1 and #2**: edit title and body to the new commands and zip
  names (they are instructions, not records — a tester follows them today).
  Labels stay.
- Open it all logged out: README clip plays, release page embeds it,
  Security tab still offers a report.

### Step 8 — the registry and the plugin

Tyler's hand (the publish was refused as a public-surface action last
time, correctly):

1. `mcp-publisher validate` on the new `server.json`
   (`io.github.tydude001/proofcut`, title `proofcut`, 0.23.0, the new URLs);
   `mcp-publisher publish`. Read it back from the public API: `active`,
   `isLatest`.
2. `mcp-publisher status --status deleted --all-versions --message "renamed
   to io.github.tydude001/proofcut" io.github.tydude001/lucid`. Read back
   that the old name reports `deleted`. PulseMCP reads the registry, so
   this is its update too.
3. Prove the plugin off the public repo in an isolated `CLAUDE_CONFIG_DIR`:
   `claude plugin marketplace add tydude001/proofcut`, `claude plugin install
   proofcut@proofcut`, `claude mcp list` connected.
4. Check Glama for the new name once it has had a day; the `glama.json` at
   the root is unchanged (it names only the maintainer).

### Step 9 — the record

- HISTORY.md § The rename — what was measured (the collision, the sweep,
  the candidates and why each fell), what changed, what each verification
  printed, what Tyler's hand did and read back.
- Wiki: `projects.md`'s row (name, URL, tagline); `README.md`'s Open items —
  the `lucid-rename` row closes, the other `lucid-*` rows keep their ids and
  get the new name in their text; `git-server.md`'s mirror row;
  `tooling.md` wherever it quotes a `LUCID_*` variable or a command;
  `decisions.md` gets the decision and its reasoning in one entry;
  `log.md` the day.
- Memory: the `lucid-orientation` pointer and any memory naming a `lucid`
  command or `LUCID_*` variable — a pointer tier is edited to point at the
  new names, not left to lose to the wiki silently.
- LAUNCH.md resumes where it was: step 2 (a stranger's Mac run) is still the
  gate on Show HN, the awesome-list line goes in under the new name, and
  the Show HN draft says the name once and the tagline everywhere.

## The guard list

Strings a replace must leave alone, with today's counts across `src`,
`tests`, `scripts`, `docs`, the root docs, `.github` and `.claude`. The
count is re-taken after every category of edit and must match.

| String | Hits | Why it stays |
|---|---|---|
| `~/lucid-work`, `lucid-work` | 65 | a real directory on this box; the voice-clone runtime dependency lives in it |
| `~/lucid-demo` | 38 | the demo project, referenced absolutely |
| `~/lucid-final-cut` | 30 | the film's project; six manifests point into it |
| `~/lucid-scream-v2`, `~/lucid-vertical`, `~/lucid-a2-probe`, `~/lucid-archive`, `~/lucid-dogfood`, `~/lucid-teaser`, `~/lucid-mac-trial`, `~/lucid-approvals`, `~/lucid-scale-spike`, `~/lucid-kf-probe`, `~/lucid-framing-detect`, `~/lucid-watch`, `~/lucid-review`, `~/lucid-flash-review`, `~/lucid-cards-reauthor`, `~/lucid-caption-anim`, `~/lucid-threshold`, `~/lucid-brief-check`, `~/lucid-a2-build`, `~/lucid-studio-walk`, `~/lucid-split-*`, `~/lucid-reel` | 99 | measured paths in records and docstrings; most exist, the rest are in `~/lucid-archive/spikes/` under the same name |
| `~/lucid-render` | 4 | the old `RENDER_SCRATCH`; the *code* literal changes, the four *mentions* in records describing where renders staged do not |
| `~/lucid-mac-trial`, `~/lucid-windows-trial` | in kits and workflows | **these do change** — they are the kit's install dir on a stranger's machine, not a directory here; listed so the distinction is explicit |
| `lucidsoftware`, `lucid.co`, `lucid-mcp-server`, `Lucidchart`, `Lucid Software`, `app.lucid.mcp` | 1 + this plan | the company this rename moves away from, quoted as a measurement |
| `lucide` | in `docs/` if anywhere | `lucide-icons` is an icon set, not this project |

Anything in HISTORY.md, TRIAL.md, DAYDREAM.md, POLISH.md, STUDIO.md below
its preface.

## What this plan deliberately does not do

- **No fallback resolver for `LUCID_*`.** `doctor` names the stale variable;
  nothing reads it. Two names for one fact is how the `~/projects` fallback
  paths got printed to strangers.
- **No permanent dual manifest name.** `open` refuses `lucid.json`; it does
  not quietly read it. A project that reads under both names is one that
  gets written under both.
- **No rewrite of any record.** Prefaces and a new section only.
- **No history rewrite.**
- **No rename of this box's working directories** beyond the clone and its
  memory directory. `~/lucid-*` is pinned for the reasons CLAUDE.md gives.
- **No new launch step.** LAUNCH.md's order stands; this is a prerequisite
  to its step 2 and 4, not a step of its own.
- **No domain purchase as part of the rename.** `proofcut.dev` and
  `proofcut.org` are free today and that is noted; buying one is Tyler's
  call and nothing here waits on it.
