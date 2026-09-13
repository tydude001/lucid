# The demo — a cut, a picture, and a render that checks itself

Two minutes, start to finish, on footage the repo generates rather than ships.
By the end you will have cut a retake out of a voiceover by naming the words,
hung two b-roll clips off phrases in the transcript, rendered the result, and
had lucid confirm the render says what the timeline says.

Every command below is verbatim. The output sketches are from a real run on
2026-08-24 — yours will differ in the third decimal place and in whatever
whisper hears, and that is the point of the last step.

## What you need

`uv`, `ffmpeg`, `espeak-ng` (a few megabytes, only to *build* the demo voice),
plus **whisper** for the transcript, **auto-editor** for the silence pass and
**melt** for the picture. The ffmpeg has to be built with `libx264`, freetype
and libass: step 1 labels the footage with `drawtext`, and it stops at its
first command without it. On a Mac that means Homebrew's `ffmpeg-full`, not
its `ffmpeg`, and because it is keg-only, first on `PATH`:

```sh
brew install ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
```

If you are not sure:

```sh
uv run lucid doctor
```

It probes all of them and, for anything missing, prints the fix rather than
just a ✗.

On a box with no desktop (a server, a container, SSH), step 6's render needs
Qt to draw without one. `lucid doctor`'s Display row renders a probe frame and
says whether `QT_QPA_PLATFORM=offscreen` is enough for your MLT. Where it is
not, as with Ubuntu 24.04's and Fedora 44's packaged melt, run the render as
`xvfb-run -a uv run lucid …` (`apt install xvfb`, or `dnf install
xorg-x11-server-Xvfb`).

## 1. Make the footage

```sh
uv sync
uv run python scripts/make_demo.py ~/lucid-demo
```

```
voiceover  -> /home/you/lucid-demo/vo.wav
b-roll     -> /home/you/lucid-demo/broll-blue.mp4
b-roll     -> /home/you/lucid-demo/broll-rust.mp4
```

The voiceover is about 19 seconds and says this — read it, because the fourth
line is the one you are about to remove:

> This is a demo of lucid, a local first video editor.
> **Every cut you make names a, hmm, no, let me try that again.**
> Every cut you make names a word in the transcript.
> So the edit stays addressable, and the render can be checked against it.

That middle line is a **retake**: the narrator starts a sentence, stops, and
says it again. Removing it is the thing lucid exists for.

The two b-roll clips are flat colours carrying three marks — a centred
counter (`BLUE 3s`), a faint grid, and `TL`/`TR`/`BL`/`BR` in the corners.
Ugly on purpose. Every frame names which clip it is and how far into it, so
one look at the render tells you whether the right footage is at the right
moment; and every *corner* names itself, so a crop window that keeps all four
is one that is not cropping. On real footage you judge a crop by whether the
subject survived — there is no subject here, so the frame answers the question
instead.

## 2. Make the project

```sh
uv run lucid init ~/lucid-demo/proj
uv run lucid -C ~/lucid-demo/proj import ~/lucid-demo/vo.wav --clip-id vo
uv run lucid -C ~/lucid-demo/proj import ~/lucid-demo/broll-blue.mp4 --clip-id blue
uv run lucid -C ~/lucid-demo/proj import ~/lucid-demo/broll-rust.mp4 --clip-id rust
```

Each `import` prints the clip record — duration, codecs, dimensions, and
`vfr` (whether the source is variable frame rate). Nothing is copied: lucid
links the media where it lies.

```sh
uv run lucid -C ~/lucid-demo/proj transcribe vo
```

whisper, with word timings. Expect **~47 words** and a `text` field that reads
back the script, disfluencies and all. This is the slow step; on a laptop
without a GPU it is a minute or two.

```sh
uv run lucid -C ~/lucid-demo/proj seed vo
```

auto-editor strips the silences and what is left becomes the timeline.

```
"segments": 4,
"source_duration": 18.55,
"timeline_duration": 16.67,
"silences_removed": true
```

Four segments, because the gaps between takes are gone.

## 3. Find the retake

```sh
uv run lucid -C ~/lucid-demo/proj transcript vo --search "let me try that again"
```

```json
{"first_word": 19, "last_word": 23, "start": 7.44, "end": 8.9,
 "text": "let me try that again."}
```

The fluff starts earlier than that, at the beginning of the abandoned
sentence. Read the words around it:

```sh
uv run lucid -C ~/lucid-demo/proj transcript vo --first 8 --last 26
```

Words 11–23 are the whole retake, `Every cut you make names a... Um, no, let
me try that again.` — and word 24 is where the good take starts.

## 4. Cut it

**Ask first.** Every mutating command takes `--plan`, which resolves the whole
thing and writes nothing:

```sh
uv run lucid -C ~/lucid-demo/proj cut vo 11:23 --plan
```

```json
"text": "Every cut you make names a... Um, no, let me try that again.",
"context_before": [{"index": 8, "text": "first"}, {"index": 9, "text": "video"},
                   {"index": 10, "text": "editor."}],
"context_after":  [{"index": 24, "text": "Every"}, {"index": 25, "text": "cut"},
                   {"index": 26, "text": "you"}],
"removed": 4.7
```

The three neighbours either side are the point: an index one past the phrase
you meant reads perfectly well on its own, and the echo is what makes that
visible. Word 10 ends the good line before, word 24 starts the good line
after, so this is the right range. Now do it:

```sh
uv run lucid -C ~/lucid-demo/proj cut vo 11:23 --pad 0.1
```

```
"removed": 4.8,
"duration_after": 11.866,
"segments": 4
```

`--pad 0.1` takes a tenth of a second either side, so the cut lands in silence
rather than on a consonant — which is the 4.7 → 4.8 difference between the
plan above and this. If you cut the wrong range, `lucid -C … undo`
puts it back.

## 5. Hang a picture on it

A cue says "from this word onward, show this asset". Address it by phrase and
lucid resolves it against the transcript, echoing what it matched:

```sh
uv run lucid -C ~/lucid-demo/proj cue add vo --phrase "Every cut you make names a word" blue
uv run lucid -C ~/lucid-demo/proj cue add vo --phrase "the render can be checked" rust
```

```sh
uv run lucid -C ~/lucid-demo/proj shots
```

```
0.00 + 9.66  blue
9.66 + 2.21  rust
```

Two shots. Note that a cue survives a cut — it names a *word*, not a second,
so nothing you do to the edit can move it out from under its own line.

## 6. Render, and check the render

```sh
uv run lucid -C ~/lucid-demo/proj export ~/lucid-demo/demo.mp4 --render
```

Two sources plus the voiceover, so this goes through MLT rather than
auto-editor — lucid picks the writer from the project, never from a flag.

```
"writer": "melt", "shots": 2, "sources": 3,
"timeline_duration": 11.866, "frames": 286
```

Now the step that matters:

```sh
uv run lucid -C ~/lucid-demo/proj verify ~/lucid-demo/demo.mp4
```

```
"similarity": 0.971,
"heard_words": 34,
"expected_words": 34
```

lucid just transcribed its own render and diffed it against what the timeline
claims. 34 words expected, 34 heard, and the retake is not among them. A
render that quietly dropped a segment, or a cut that landed a frame early,
shows up here as a number rather than as something you notice a week later.

Frame counts have their own check, because a duration and a frame grid are
different questions:

```sh
uv run lucid -C ~/lucid-demo/proj frames ~/lucid-demo/demo.mp4
```

```
"agrees": true, "delta": 0
```

## 7. Look at it

```sh
uv run lucid -C ~/lucid-demo/proj open
```

The workspace: the transcript with the cut struck through, the timeline lanes,
and a player that builds the edit live from the source — so seeing a cut costs
no render at all. Press `?` for the shortcuts.

Play to about three seconds and the frame reads `BLUE 3s`; to about ten and it
reads `RUST 0s`. That is the picture lane doing what the shot table said it
would, and it is why the demo footage is labelled.

## Shortcuts

`scripts/make_demo.py ~/lucid-demo --build` does steps 1 and 2 in one go — the
same commands, run for you — if you would rather start from a seeded project
and skip to step 3.

## What to try next

- `lucid -C ~/lucid-demo/proj cut vo 11:23 --plan` again after cutting: it
  reports `already_cut`, because the words are still addressable even though
  they are no longer on the timeline.
- `lucid -C ~/lucid-demo/proj caption-style --size 64` then
  `lucid -C ~/lucid-demo/proj captions ~/lucid-demo/demo.ass --burn ~/lucid-demo/demo.mp4`
  — captions come out of the *timeline*, not the transcript, so they land where
  the words actually play. Note that `export --render` does **not** burn them
  — the burn is its own opt-in step against a finished file.
- `lucid -C ~/lucid-demo/proj finish-report` — everything the truth strip
  draws. Its `captions.burned` reads `"unknown"` after the hand-run burn
  above, and correctly: it reports what the last *render pipeline run* did,
  and a `captions --burn` on an existing file is not one. A manifest can say
  captions are configured while nothing on disk was ever burned, and this is
  the field that stops that reading as clean.
- `lucid -C ~/lucid-demo/proj reframe blue --rect 0,0,320,180` then
  `lucid -C ~/lucid-demo/proj reframe-sheet` — a crop window is a rect in the
  clip's own *source* pixels, so no cut can invalidate one. That rect keeps
  the top-left quadrant, which the corner tags make obvious: `TL` survives and
  the other three are gone. The sheet draws every window on the frames it
  actually governs, and Frame mode in the window is the same sheet with
  coverage chips over it.
- Point step 1 at your own voiceover instead. Nothing in the walkthrough after
  step 2 knows the footage was generated.
