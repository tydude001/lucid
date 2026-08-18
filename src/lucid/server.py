"""The `lucid mcp` server — MCP tools over stdio, or over HTTP.

Every tool here is a thin wrapper over `lucid.ops`, and every one has a
matching `lucid` CLI subcommand (CLAUDE.md). Tool bodies stay trivial on
purpose: logic that lives here is logic the CLI cannot reach and the stdio
tests cannot isolate.

Note the SDK is v2 — `MCPServer` from `mcp.server`. There is no `FastMCP` and
no `mcp.server.fastmcp` module, whatever your priors say.

stdio is the default transport and every existing client spawns the server
that way; HTTP is opt-in (`lucid mcp --transport http`, DAYDREAM.md § MCP
over HTTP) for the day something needs to drive an already-running project
from outside. Its guard mirrors `webui.py`'s discipline exactly — see
`_LoopbackGuard` and `_serve_http` below — because an HTTP MCP server carries
the same edit-mutating tools stdio does, reachable from anywhere that can
route to the port.
"""

from __future__ import annotations

import functools
import inspect
import socket
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from mcp.server import MCPServer
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from lucid import __version__, asr, energy, ops, webui
from lucid.project import ProjectError

mcp: MCPServer = MCPServer(
    name="lucid",
    version=__version__,
    instructions=(
        "lucid edits video locally. All state lives in a project directory on "
        "disk; nothing is uploaded.\n\n"
        "The usual order is: init -> import_media -> attach_transcript -> "
        "seed_timeline -> cut_by_transcript (repeatedly) -> export.\n\n"
        "Word indices in cut_by_transcript address the ORIGINAL recording and "
        "never renumber, so a range stays valid across accumulated cuts. Use "
        "get_transcript with search= to locate a phrase rather than reading "
        "the whole transcript. Every mutation is snapshotted; undo rolls one "
        "back."
    ),
)


#: The project this server is bound to, or None when it is unbound. Set once
#: by `serve(root=...)`, which `lucid mcp` calls with its `-C` directory — and
#: only when `-C` was actually typed, because a globally-configured
#: `lucid mcp` has no project and must keep reaching any of them.
_BOUND_ROOT: Path | None = None

#: Bind address and port `lucid mcp --transport http` uses when neither flag
#: is given. Loopback, matching `webui.DEFAULT_HOST` (127.0.0.1): an HTTP MCP
#: server carries the same edit-mutating tools stdio does, so it gets
#: `webui.py`'s discipline (CLAUDE.md) rather than a looser default of its
#: own. The port is one past `webui.DEFAULT_PORT` for the same reason that
#: one isn't 8000/8080 — don't collide with `lucid web` running on the same
#: project, or with whatever else a dev box already has up.
DEFAULT_HTTP_HOST = webui.DEFAULT_HOST
DEFAULT_HTTP_PORT = webui.DEFAULT_PORT + 1

#: Bind-side "any interface" addresses. These are never a client-presented
#: identity — no real client dials `0.0.0.0` or `::`, so no real `Host:`
#: header ever names one. Widening the guard's allow-list with the literal
#: `--host` string is honest for a specific address (a client that reaches
#: the server by that address naturally sends it in `Host:`) but not for a
#: wildcard bind: it would add a string only an attacker who read the
#: server's own startup banner would ever send, while doing nothing for the
#: real remote clients the wildcard bind exists to admit — they show up with
#: whatever address they actually dialed, never `0.0.0.0`/`::`. See
#: `_build_http_server`.
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})


def _host_name(host_header: str) -> str:
    """Normalize a `Host:` header value to a bare, lowercased name.

    The same parse `webui.Handler._host_is_loopback` does — strip a trailing
    `:port`, unwrap a bracketed IPv6 literal — reimplemented rather than
    called, because this one runs against Starlette's `Headers` instead of
    `BaseHTTPRequestHandler`'s, and is checked against a name set the HTTP
    guard can widen (`--allow-remote`), which `webui.py`'s never does.
    """
    host = (host_header or "").strip()
    name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if name.startswith("[") and "]" in name:
        name = name[: name.index("]") + 1]
    return name.lower()


class _LoopbackGuard:
    """ASGI middleware: refuses any HTTP request whose Host header isn't allowed.

    `webui.py` solved exactly this problem (`Handler._host_is_loopback`,
    answered with `HTTPStatus.FORBIDDEN`), and CLAUDE.md is explicit that
    binding loopback is not enough by itself — a hostile page's cross-origin
    fetch, or a DNS-rebinding attempt, reaches a loopback-bound socket just
    fine, and only the Host header tells it apart from a real local client.
    The MCP HTTP surface carries the same mutating tools stdio does (every
    `@_tool()` in this module), so it gets the same two-layer guard: loopback
    bind by default (`_serve_http`) plus this middleware, implemented as real
    ASGI middleware wrapping the SDK's own Starlette app rather than left as
    a comment saying the guard belongs somewhere.

    A pure ASGI callable rather than Starlette's `BaseHTTPMiddleware`: it has
    to run in front of the SDK's own routing, including the streamable-HTTP
    session manager's `lifespan`-scoped startup, and must pass any scope type
    that isn't `"http"` straight through untouched rather than adapt it into
    a request/response pair that doesn't exist for it.
    """

    def __init__(self, app: ASGIApp, allowed_names: frozenset[str]) -> None:
        self._app = app
        self._allowed_names = allowed_names

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if _host_name(headers.get("host", "")) not in self._allowed_names:
            response = PlainTextResponse(
                "this server answers loopback requests only", status_code=403
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

F = TypeVar("F", bound=Callable[..., Any])


def _confine(path: str) -> str:
    """Resolve a tool's project-selector argument against the bound project.

    **Only a project selector is confined, and that is a deliberate
    boundary**: `path` is the selector, so leaving it free is what lets an
    agent panel opened on one project mutate another. The file arguments are
    not selectors and are left alone — `import_media`'s `source` reads footage
    that lives on the NAS, and `export`/`add_captions` write where the user
    asked. Confining either would break the ordinary workflow while buying
    nothing, since neither can touch a second project's state.

    `reel`'s `dest` is the one argument that is a *second* selector rather
    than a file: it names a whole project, and an unconfined one would let a
    bound panel write a project anywhere on disk. It is confined by being
    named at the registration site (`@_tool("path", "dest")`) rather than by
    a line in the body, for the reason the decorator exists.

    A relative path resolves against the bound root rather than the process
    cwd. For the agent panel the two are the same directory (`webui.py` sets
    `cwd` on the Popen), but a bound server means "this project", and that
    reading should not depend on where the client happened to be standing.
    Both sides are `resolve()`d, so `..` and a symlink out are refused rather
    than followed.
    """
    root = _BOUND_ROOT
    if root is None:
        return path
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ProjectError(
            f"this server is bound to {root} and {path!r} resolves outside it "
            f"({resolved}). It was started as `lucid -C {root} mcp`, so every "
            "tool addresses that project; pass a path at or under it."
        )
    return str(resolved)


def _tool(*selectors: str) -> Callable[[F], F]:
    """Register a tool, routing its project-selector arguments through `_confine`.

    A decorator rather than a line in each body because the confinement has
    to hold for *every* tool — one body that forgot it would be the whole
    hole again — and because tool bodies stay trivial (see this module's
    docstring). `functools.wraps` sets `__wrapped__`, which the SDK's
    `inspect.signature(fn, eval_str=True)` follows, so the advertised schema
    is the undecorated function's and nothing about the tool surface changes.

    Defaults to `path`, which is every tool but one, so `@_tool()` keeps its
    meaning. Naming more than one is for a tool that addresses a *second*
    project — `reel`'s `dest` — and an unlisted selector is silently
    unconfined, exactly the way a tool registered with `mcp.tool()` is, so
    the list belongs beside the registration where it can be read.
    """
    names = selectors or ("path",)

    def decorator(fn: F) -> F:
        signature = inspect.signature(fn)
        present = [name for name in names if name in signature.parameters]
        if not present:
            return mcp.tool()(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            for name in present:
                # `bind` omits an argument the caller left to its default, and
                # a selector never has one — but reading it unguarded would
                # turn "you forgot dest" into a KeyError from the decorator.
                if name in bound.arguments:
                    bound.arguments[name] = _confine(bound.arguments[name])
            return fn(*bound.args, **bound.kwargs)

        return mcp.tool()(wrapper)

    return decorator


@_tool()
def ping() -> dict[str, str]:
    """Check that the lucid MCP server is alive, and report its version."""
    return {"status": "ok", "server": "lucid", "version": __version__}


@_tool()
def init(path: str, name: str | None = None) -> dict[str, Any]:
    """Create a lucid project directory at `path`."""
    return ops.init(path, name=name)


@_tool()
def migrate_project(path: str, plan: bool = False) -> dict[str, Any]:
    """Bring an older project manifest forward to the current schema version.

    Every other tool refuses a project written by an older lucid rather than
    guessing at a layout it does not recognise; this is what clears that. It
    is forward-only, and it copies the manifest into `cache/history/` before
    writing. `plan=True` reports the version and the steps without writing,
    which is how to ask what a project is before deciding to change it.
    """
    return ops.migrate(path, plan=plan)


@_tool()
def import_media(
    path: str,
    source: str,
    clip_id: str | None = None,
    copy: bool = False,
    mix: bool = False,
    audio_stream: int | None = None,
) -> dict[str, Any]:
    """Register a media file with the project, probing it with ffprobe.

    Links the media by default rather than copying it. Returns the clip record,
    including the `clip_id` every other tool takes, and `audio_streams` — how
    many the container holds, since every other audio field on the record
    describes only the first.

    A container with more than one audio stream is refused rather than
    registered as if the first were the recording: whisper picks a stream of
    its own and MLT picks again at render, so the others would be missing
    from the film with every check clean. `mix=True` sums them into one track
    (two mics of one performance); `audio_stream=k` keeps one, numbered from
    0 in ffmpeg's own audio ordering. Either writes a derived copy under
    `cache/mixed/` that every later op reads without knowing it.
    """
    return ops.import_media(
        path, source, clip_id=clip_id, copy=copy, mix=mix, audio_stream=audio_stream
    )


@_tool()
def clip_role(
    path: str, clip_id: str, role: str | None = None, reset: bool = False
) -> dict[str, Any]:
    """Read or set a clip's import role — voiceover vs footage.

    Called with no `role` and no `reset` it just reports what is stored;
    `role` must be `"voiceover"` or `"footage"` (`ops.CLIP_ROLES`); `reset`
    clears it back to undeclared.

    **This changes nothing about how `transcribe`/`attach_transcript` or
    `describe` treat the clip.** Both already gate on their own evidence — a
    transcript file, `has_video` — and neither reads this field, so an
    undeclared clip is exactly as eligible for both as it always was. It is
    the assets pane's grouping, purely, and setting one is not a schema bump
    for that reason: an additive optional field on an existing clip record.
    """
    return ops.clip_role(path, clip_id, role, reset=reset)


@_tool()
def attach_transcript(path: str, clip_id: str, transcript_path: str) -> dict[str, Any]:
    """Ingest an existing word-timed whisper JSON as this clip's transcript.

    Checks the transcript against itself for `near_duplicates` — adjacent
    runs of words that sound like the same line said twice. That is a
    retake `verify` can never catch once both takes are cut into the edit,
    since nothing then disagrees with the timeline. A hit is not a verdict:
    a deliberate callback line looks the same as a swallowed retake here.

    Also reports `suspect_durations`, `overlaps` and `repeats`. An `overlaps`
    seam is a retake splice whisper read straight across, interleaving both
    takes and inventing words nobody said — check it before drawing anything
    derived from this transcript. `repeats` is a back-to-back duplicated
    phrase, the shape a retake makes when it survives as distinct words
    rather than as a seam — a different subset of retakes than `overlaps`
    finds, not a smaller one. Use transcript_checks to see all four again
    later.
    """
    return ops.attach_transcript(path, clip_id, transcript_path)


@_tool()
def transcribe(
    path: str, clip_id: str, model: str = "turbo", language: str | None = None
) -> dict[str, Any]:
    """Transcribe a clip's own media with whisper, and attach the result.

    attach_transcript's ASR-driven sibling: use that when the recording
    already has a transcript, this when it needs one made. Takes minutes on a
    long recording — there is no timeout, so let it run. Reports
    `near_duplicates`, `suspect_durations`, `overlaps` and `repeats` the same
    way attach_transcript does.
    """
    return ops.transcribe(path, clip_id, model=model, language=language)


@_tool()
def get_transcript(
    path: str,
    clip_id: str,
    first: int | None = None,
    last: int | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Read a clip's transcript.

    With `search`, returns each match as a word range ready to hand to
    cut_by_transcript — prefer this to reading the whole transcript. With
    `first`/`last`, returns that window of words. Indices are inclusive.
    """
    return ops.get_transcript(path, clip_id, first=first, last=last, search=search)


@_tool()
def transcript_checks(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """Re-check an already-attached transcript against itself.

    Returns the same four findings attach_transcript does —
    `near_duplicates`, `suspect_durations`, `overlaps`, `repeats` — for a
    transcript attached earlier, whose findings were reported once and are
    otherwise gone. Omit `clip_id` for every clip that has a transcript.

    Read `overlaps` before anything derived from this transcript is drawn on
    screen. A seam there is whisper reading across a retake splice and
    interleaving both takes, which **invents words nobody said** — and they
    read as ordinary English, so a human proofread finds some and is blind to
    the rest. `repeats` catches the other shape a retake takes: one that
    survived transcription as distinct, cleanly-timed duplicated words rather
    than as an interleaved seam. Reads only; it never writes.
    """
    return ops.transcript_checks(path, clip_id)


@_tool()
def describe(
    path: str,
    clip_id: str | None = None,
    window: float = 10.0,
    force: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Describe footage in fixed windows, so b-roll can be found by what is in it.

    A description is `(clip_id, src_start, src_end, text)` in **source**
    seconds, which is why cutting the edit can never invalidate one. Omit
    `clip_id` to describe every video clip that has not been described yet;
    name one to do just that clip. Audio-only clips are refused — their words
    are what `transcribe` indexes.

    **This is a job, not a request.** Cost is about three seconds per window
    regardless of how much footage the window spans, so a project's footage
    is minutes of GPU time. Run it with `plan=True` first: that resolves the
    whole work list and the estimate, and reports whether this machine can
    run the model at all, without loading anything.

    Already-described clips are skipped unless `force`. Do not widen `window`
    to save time without a reason — a single pass over a whole clip describes
    six frames as six people, fluently and with nothing saying it is wrong.

    Read `errors` and `truncated` in the result. A truncated description
    stops mid-fact and reads exactly like a complete one, and a window is
    never evidence of a *continuous shot*: the model narrates across a cut
    inside one as though it were a single take.
    """
    return ops.describe(path, clip_id, window=window, force=force, plan=plan)


@_tool()
def describe_ls(
    path: str, clip_id: str | None = None, contains: str | None = None
) -> dict[str, Any]:
    """Read the footage descriptions, to find b-roll by what is in it.

    **This is the search.** There is no ranking and no similarity score to
    ask for — you read the descriptions and pick, which is why the prompt
    behind them asks for concrete nouns. Each entry is `(clip_id, src_start,
    src_end, text)` in **source** seconds, so what you pick stays valid
    however the edit is cut.

    `contains` filters: whitespace-separated terms, case-insensitive, and
    every term must appear — `"kitchen knife"` matches "a knife on the
    kitchen counter". Reach for it before reading everything on a large
    project; `words` says how much text came back.

    Two things not to over-read. A window is evidence of what is *visible in
    a span*, never of a continuous shot — the model narrates across a cut
    inside one as though it were a single take. And an entry with
    `truncated` true stopped mid-fact and reads exactly like a complete
    description.

    A clip listed under `clips` with `windows: 0` has not been described yet;
    `describe` is what indexes it.
    """
    return ops.describe_ls(path, clip_id, contains=contains)


@_tool()
def card_templates() -> dict[str, Any]:
    """The card templates lucid ships, and the slots each one takes.

    Read this before card_new: each slot says what it is for, whether it is
    required, and what it defaults to. The palette and font stacks are slots
    too, so a card can be restyled without authoring an SVG by hand.
    """
    return ops.card_templates()


@_tool()
def fonts(path: str | None = None, install: bool = False) -> dict[str, Any]:
    """Will the caption font actually draw on this machine?

    Reports two answers side by side and does not merge them: `fontconfig`
    says whether the family is present, `render` burns the family and an
    impossible family and compares the pixels. Identical pixels mean the name
    is substituting whatever fontconfig claims — the only way to settle which
    face drew is to measure a render.

    `path` is optional: with a project, this checks the font that project's
    caption style would burn; without one, lucid's default. `install` copies
    the vendored face where fontconfig looks and is off by default, because it
    writes into the home directory.
    """
    return ops.fonts(path, install=install)


@_tool()
def card_new(
    path: str,
    name: str,
    template: str,
    slots: dict[str, Any],
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Make a card from a template: fill its slots, write the SVG, render it.

    `name` is the `<name>` in `card:<name>` — the key a cue points at. Both
    the SVG source and the PNG are written under the project's
    `assets/cards/`, so the card can be re-edited later and re-rendered with
    card_render rather than redrawn.

    A slot value is text. A newline inside one is a line break wherever the
    template accepts multiple lines; nothing wraps automatically, because a
    guessed wrap overflows the frame without saying so. Ratings are numbers
    out of five, to the nearest half.

    **Leave `width`/`height` unset unless you mean something other than this
    film.** They default to the project's own canvas, which is what stops a
    card from pillarboxing inside the frame it was made for; naming a size
    that is not the project's is how a card loses a quarter of its width to
    black bar. Given at all, both must be.

    Refused if a card of this name exists, unless `overwrite` — a cue may
    already point at it. Read `font_warnings` in the result: a template
    naming a face this machine lacks still renders, in a substitute, with
    nothing else to say so.
    """
    return ops.card_new(
        path, name, template, slots, width=width, height=height, overwrite=overwrite
    )


@_tool()
def card_render(
    path: str, name: str, width: int | None = None, height: int | None = None
) -> dict[str, Any]:
    """Rasterise `assets/cards/<name>.svg` into the PNG `card:<name>` shows.

    Author the SVG under the project's `assets/cards/`, then render it here;
    both files are kept, so a card can be re-edited rather than redrawn. The
    PNG is what a `card:` cue resolves to, so a card is not usable until this
    has run.

    `width`/`height` are given together or not at all and set the *render*
    size — the document is drawn at that scale rather than rasterised and
    resampled — and they fit rather than distort, so a size at a different
    aspect from the document's comes back smaller on one axis. Omitted, the
    document renders at its own declared size.

    Every call reports the fonts the document names and what fontconfig will
    actually draw. Read `font_warnings`: a card naming a face this machine
    lacks renders pixel-identically to one naming a face it has, so nothing
    downstream can catch the substitution.
    """
    return ops.card_render(path, name, width=width, height=height)


@_tool()
def card_reauthor(path: str, name: str | None = None, plan: bool = False) -> dict[str, Any]:
    """Draw recorded cards again at the shape this project renders at now.

    Reach for this after `canvas` — a card is the only thing in a project
    whose shape a canvas change cannot fix on its own, because the aspect is
    baked into the SVG it was drawn from. Re-rendering the old SVG at the new
    size would pillarbox the card inside the frame; this fills the template
    again at the new canvas, from what `card_new` recorded.

    With no `name` it sweeps every recorded card the canvas has left behind,
    plus any whose files have gone missing. Named, it redraws that one
    whatever its canvas.

    Read `unrecorded` in the result. Those are cards with files on disk and
    no record of what made them — nothing can re-author one, and the way to
    fix it is card_new with `overwrite`, which records it on the way past.
    `plan` reports what would change and writes nothing.
    """
    return ops.card_reauthor(path, name, plan=plan)


@_tool()
def card_safe_zones(path: str, card: str, platform: str) -> dict[str, Any]:
    """Measure a rendered card's ink in and around a platform's reserved band.

    **Report only** — nothing here blocks a render, and there is no default
    floor: `SCENE_THRESHOLD`'s own history is that a threshold gets pinned by
    looking at real output, not picked cold, and this check has had exactly
    one look so far. `platform` is one of lucid's own zones (`tiktok-organic`,
    `tiktok-ads`, `reels`, `shorts`, `worst-case`) or one an applied pack's
    active variant declares — `pack_show` lists both.

    Reads `card` from its already-rendered PNG, never from the manifest's
    recorded slots alone, so the ink it measures is the ink actually on disk.
    Refuses a card with no PNG yet (card_new/card_render it first) or a
    platform neither source declares.
    """
    return ops.card_safe_zones(path, card, platform)


@_tool()
def pack_apply(
    path: str,
    pack_path: str,
    variant: str = "default",
    allow_fallback: bool = False,
    install_fonts: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Load a channel preset pack, resolve and snapshot every variant, activate one.

    `pack_path` is an external file — never confined to the project, the same
    way `import_media`'s `source` is not — because a pack typically lives in
    a separate branding repo. **Every declared variant is resolved and
    hashed, not only the one `variant` activates**, so `pack_activate` can
    switch between them later with no file re-read; nothing after this call
    ever depends on `pack_path` staying reachable.

    For every font role, `fonts.probe` asks whether the declared family
    actually draws *on this box* — a family that does not refuses the whole
    call unless `allow_fallback` (then its declared CSS fallback is used and
    recorded, never silent); one that draws but is vendored nowhere lucid
    knows about is recorded `font_provenance: "unvendored"` rather than
    refused, since the render here is genuinely correct today. `install_fonts`
    vendors the pack's own `fonts/` directory if it ships one — off by
    default, since it writes into `$HOME`.

    Writes nothing to caption styling or to any card already on disk; a card
    picks up the new style only when `card_new`/`card_reauthor` next draws
    it, and captions only via `pack_apply_captions`. `plan` resolves and
    probes without writing.
    """
    return ops.pack_apply(
        path,
        pack_path,
        variant=variant,
        allow_fallback=allow_fallback,
        install_fonts=install_fonts,
        plan=plan,
    )


@_tool()
def pack_activate(path: str, variant: str, plan: bool = False) -> dict[str, Any]:
    """Switch the active pack variant to one already snapshotted by pack_apply.

    No file re-read — refuses an unknown variant by name, naming the ones
    that are actually available, rather than trying to load it here.
    """
    return ops.pack_activate(path, variant, plan=plan)


@_tool()
def pack_apply_captions(path: str, preset: str, plan: bool = False) -> dict[str, Any]:
    """Apply the active pack variant's caption preset, through caption_style.

    **Concrete resolved fields, never a live pointer**: this reads the
    preset's already-resolved dict off the snapshot and hands it to the
    ordinary caption_style call, so a later pack swap can never silently
    overwrite a project's caption look out from under it. Separate from
    pack_apply on purpose — applying a pack never restyles captions on its
    own, only this does.
    """
    return ops.pack_apply_captions(path, preset, plan=plan)


@_tool()
def pack_show(
    pack_path: str | None = None, path: str | None = None, variant: str | None = None
) -> dict[str, Any]:
    """What a pack declares — from its file, a project's snapshot, or both.

    `pack_path` alone reads and resolves the file fresh, needing no project
    (`card_templates`'s own shape). `path` alone reports what a project
    actually has applied, from its stored snapshot — never the file again.
    Both together compares "what the file says now" against "what the
    project is still running."
    """
    return ops.pack_show(pack_path, path=path, variant=variant)


@_tool()
def pack_status(path: str) -> dict[str, Any]:
    """Active pack variant, and which cards/captions have drifted from it.

    A card is `stale` when its own recorded pack_hash no longer matches the
    active variant's current hash — not wrong, since card_new only pre-merges
    a pack's style and a per-call slot still wins, but worth a `card_reauthor`
    to catch up. `caption_preset_stale` is the same question for whatever
    pack_apply_captions last wrote.
    """
    return ops.pack_status(path)


@_tool()
def cue_add(
    path: str, clip_id: str, word_index: int, asset: str, src_start: float | None = None
) -> dict[str, Any]:
    """Add a picture cue: from `word_index` of `clip_id` onward, show `asset`.

    Source-addressed like a word range — `asset` is an opaque key or path,
    not checked against disk here; `build_shots` resolves it, the same way
    assemble_scream.py's CUES table did by hand. Refused if a cue already
    sits at that exact word; cue_rm it first to replace it. Echoes the
    resolved word plus three either side, the same convention every
    word-indexed tool follows.

    `src_start` pins **where inside `asset` the shot reads from**: seconds in
    that asset's own source time, which is exactly the number `describe_ls`
    reports for a window. This is how a moment you found with `describe` gets
    placed — without it the shot reads from wherever the per-asset cursor
    had got to, which is right for re-using a clip and wrong for showing the
    thing you searched for.

    It is an in-point and never a range: the out-point stays derived from the
    next cue through the edit, so a later cut still renumbers the shot
    correctly. The cost is a refusal instead of a rewind — if the shot's
    length runs past the end of the asset from that in-point, `build_shots`
    and the picture lane report it rather than quietly showing the asset's
    opening seconds instead. Shorten the shot with another cue, or pin
    earlier. A card takes no `src_start`; a held frame has no playhead.
    """
    return ops.cue_add(path, clip_id, word_index, asset, src_start=src_start)


@_tool()
def cue_rm(path: str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Remove the cue at `clip_id` word `word_index`."""
    return ops.cue_rm(path, clip_id, word_index)


@_tool()
def cue_ls(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """List the picture cue table, each entry echoed with its resolved word.

    Read-only. Omit `clip_id` to see every clip's cues. Ordered by
    `(clip_id, word_index)`, not by resolved timeline position — that needs
    the edit's surviving ranges, which is `build_shots`'s job.
    """
    return ops.cue_ls(path, clip_id=clip_id)


@_tool()
def assets(path: str) -> dict[str, Any]:
    """Every asset a cue can point at — clip or card — for an assets pane.

    The cue vocabulary is `clip_id` or `card:name`, so this lists both: each
    clip with its probe metadata, transcript/description presence, `role`
    and `media.playability` verdict; each card with what it was made from,
    whether its files exist, and whether it has a re-author record. Every
    entry carries `cues`, how many cues reference it — "is this used" is
    the question an assets pane exists to answer. Read-only.
    """
    return ops.assets(path)


@_tool()
def unspoken_add(path: str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Mark a word the transcript holds and the recording never said.

    Whisper transcribes straight *across* a retake splice and emits words from
    both takes interleaved, so words appear in the index that nobody said.
    They are in the transcript and nowhere else — not the audio, not the
    render — so captions draw them and `verify` expects them.

    This writes a mark beside the transcript and never touches the transcript
    itself: word indices must not renumber, or every cue pointing at one would
    move. Captions, `caption_view` and `verify` all stop expecting the word;
    no audio, timing or shot changes, because the seconds around it are the
    take that was kept. Echoes the word it resolved to, plus three either side.

    Prefer `unspoken_detect` to find them: it is evidence rather than reading,
    and reading for sense provably misses the grammatical ones.
    """
    return ops.unspoken_add(path, clip_id, word_index)


@_tool()
def unspoken_rm(path: str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Unmark a word, putting it back into captions and into `verify`."""
    return ops.unspoken_rm(path, clip_id, word_index)


@_tool()
def unspoken_ls(path: str) -> dict[str, Any]:
    """Every word marked never-spoken, with what the transcript says now.

    Read-only. `stale` is a mark whose recorded text and current text
    disagree — the transcript was re-attached under it. A stale mark is never
    applied, so re-transcribing surfaces as a list to re-check rather than as
    words disappearing from a caption file.
    """
    return ops.unspoken_ls(path)


@_tool()
def unspoken_detect(
    path: str,
    render: str,
    clip_id: str | None = None,
    transcript_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
    pad: float = ops.UNSPOKEN_PAD,
    apply: bool = False,
) -> dict[str, Any]:
    """Propose the words a render's own transcription says were never spoken.

    Candidates come from two mechanisms and one witness decides both. A
    **seam** is where whisper read across a splice and invented a word; a
    **fragment** is where a cut left a sliver of a real one, which draws as a
    whole word on screen and is inaudible. The witness is the render: the
    candidate's word is counted in the timeline over a short window and in the
    render's own transcription over the same seconds, and it is proposed only
    where the timeline has more of them than the render heard. Counted rather
    than looked up because the inventions are function words — asking whether
    the render says "the" near here answers yes off the real one beside it.

    `apply=False` by default, like `reframe_detect`: this changes what a
    caption says, and a wrong mark deletes a real word from every check lucid
    has. Read the echoes first.

    `transcript_path` takes an existing transcription of the render, which is
    what `verify` leaves in `cache/verify/`. Pass it explicitly — it is never
    found automatically, because a re-render under the same filename would
    otherwise be judged against the previous render's audio.
    """
    return ops.unspoken_detect(
        path,
        render,
        clip_id=clip_id,
        transcript_path=transcript_path,
        model=model,
        language=language,
        pad=pad,
        apply=apply,
    )


@_tool()
def build_shots(path: str, fps: float | None = None) -> dict[str, Any]:
    """Project the cue table into contiguous shots over the current edit.

    Maps each cue's word through the edit's surviving ranges to a timeline
    frame, resolves its `asset` to a checked path (`card:name` under
    `assets/cards/`, else a registered video clip_id), and runs each shot to
    the next cue — the last to the edit's own frame total. Refuses if a
    cue's word was cut from the edit; fix it with cue_rm/cue_add first.

    `fps` picks the frame grid; it defaults to the project's timebase, which
    for an audio-only project is milliseconds rather than frames. Pass the
    rate `export` will use to see the frames the export actually cuts at.
    """
    return ops.build_shots(path, fps=fps)


@_tool()
def seed_timeline(
    path: str,
    clip_id: str,
    remove_silences: bool = True,
    threshold: float = 0.04,
    margin: str | None = None,
    edit_expr: str | None = None,
) -> dict[str, Any]:
    """Lay a clip down as the timeline, silence-cut by auto-editor by default.

    `edit_expr` passes auto-editor's edit language straight through, e.g.
    "(or audio:0.03 motion:0.06)".
    """
    return ops.seed_timeline(
        path,
        clip_id,
        remove_silences=remove_silences,
        threshold=threshold,
        margin=margin,
        edit_expr=edit_expr,
    )


@_tool()
def cut_by_transcript(
    path: str,
    clip_id: str,
    cut: Sequence[Sequence[int]] | None = None,
    keep: Sequence[Sequence[int]] | None = None,
    pad: float = 0.0,
    confirm_suspect: bool = False,
    through_pause: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut or keep inclusive word ranges, e.g. cut=[[30, 45], [120, 131]].

    Pass exactly one of `cut` or `keep`. `pad` widens each range on both sides
    in seconds, to land the cut in the silence between words. The timeline is
    snapshotted first, so this is undoable.

    Every range echoes back the words it resolved to, plus the few words either
    side of it — an index one past the intended phrase reads fine on its own
    and is only visibly wrong next to its neighbours. `pad_reach` names any
    neighbour the padding eats, since padding is in seconds and the echoed text
    is not.

    `through_pause=True` (cut only) extends each range's trailing edge through
    the pause after its last word, whenever that gap is wide enough to have
    drawn a `[N.Ns]` marker in the transcript pane — so cutting a phrase also
    removes the dead air after it instead of leaving it playing. A no-op when
    the trailing gap is too short to have drawn a marker.

    `plan=True` returns that whole payload — including what the timeline would
    become — without writing anything. Prefer it over cutting and undoing.

    Refused if a range's first or last word claims a suspect duration (see
    `attach_transcript`/`transcribe`'s `suspect_durations`) — that word's
    `end`/`start` is what the cut boundary resolves to, and it is usually
    hiding a retake rather than ending where it claims. Check the word, then
    retry with `confirm_suspect=True` if the boundary is actually fine. Under
    `plan=True` these are reported as `suspect_boundaries` instead of refused.
    """
    return ops.cut_by_transcript(
        path,
        clip_id,
        cut=cut,
        keep=keep,
        pad=pad,
        confirm_suspect=confirm_suspect,
        through_pause=through_pause,
        plan=plan,
    )


@_tool()
def cut_by_time(
    path: str,
    spans: Sequence[Sequence[float]],
    pad: float = 0.0,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut spans of RENDER/TIMELINE time — what a human reports watching an export.

    Each span is [start, end) in the seconds the current export plays at
    (what timeline_status/verify describe), not source time and not word
    indices. lucid converts each span to the source interval(s) it plays —
    the inverse of the mapping captions and playback use — and cuts those
    through the same Edit.remove path cut_by_transcript uses. The render
    timestamp is never stored: the conversion happens once, here, at call
    time.

    All spans resolve against the CURRENT timeline before any is applied, so a
    list of notes from one watch stays valid together even though a real cut
    would shift every later timestamp. Overlapping spans are refused rather
    than silently double-applied.

    Every piece echoes the source interval it produced (more than one when the
    span crosses an earlier cut or a clip boundary) and the words it overlaps
    there, plus three neighbours either side — the human check that the
    timestamp actually hit the intended flub. `pad` widens only the OUTER
    edges of each requested span. `plan=True` resolves and reports without
    writing, identically to cut_by_transcript.

    Refused the same way cut_by_transcript is if a span overlaps a word with a
    suspect duration; `confirm_suspect=True` or `plan=True` behave the same.
    """
    return ops.cut_by_time(path, spans=spans, pad=pad, confirm_suspect=confirm_suspect, plan=plan)


@_tool()
def restore(
    path: str,
    clip_id: str,
    ranges: Sequence[Sequence[int]],
    pad: float = 0.0,
    plan: bool = False,
) -> dict[str, Any]:
    """Un-cut whichever part of these inclusive word ranges is not currently in the timeline.

    Same range shape as cut_by_transcript's cut=/keep=. Each range resolves to
    source time exactly like a cut does; only the part Edit.gaps says is
    actually absent comes back — material still present in the request is left
    alone, a request spanning two separate cuts restores both as separate
    pieces, a request only touching part of one cut restores only that part.
    Restoring only ever brings back material the source recording already has
    (bounded by the clip's own registered duration), so the timeline stays a
    subset of the source throughout — this is not vo_extend (PLAN.md parks that
    separately), which would add material the source never had.

    pad matches cut_by_transcript's own pad: pass the same value used on the
    original cut to bring back its padding sliver, not just the words.

    Unlike a cut, there is no suspect-duration refusal — a boundary that looks
    like it swallowed a retake is exactly the kind of thing restore exists to
    bring back, not a mistake to guard against.

    Refused if clip_id has no surviving segment anywhere in the edit (nothing
    left of it to splice the range next to — undo or re-seed instead), or if
    its segments are not contiguous in the edit (an interleaved multi-source
    timeline, which restore does not support yet).

    plan=True resolves and reports without writing, identically to
    cut_by_transcript.
    """
    return ops.restore(path, clip_id, ranges, pad=pad, plan=plan)


@_tool()
def locate(
    path: str,
    clip_id: str,
    first: int | None = None,
    last: int | None = None,
    source_start: float | None = None,
    source_end: float | None = None,
) -> dict[str, Any]:
    """Where does a SOURCE word or SOURCE time play in the current render?

    cut_by_time's read-only mirror, and the tool to reach for before quoting
    any timestamp to a human: word indices and transcript times address the
    original recording, so they are NOT render times and every accumulated cut
    moves them further apart.

    Address it one way per call — `first`/`last` are inclusive word indices
    (`last` defaults to `first`), `source_start`/`source_end` are seconds into
    the recording (omit `source_end` to locate an instant).

    Read `present` first. False means the material is not in the render, and
    `beyond_source` distinguishes "you cut it" from "the recording never went
    that far". A partially-cut range is normal: `placements` lists each
    surviving piece in playback order with the source coordinates saying which
    part of the phrase it is, `covered` how much survives, and `contiguous`
    whether the survivors still play back-to-back. Word mode echoes the
    resolved words plus three either side; time mode echoes the words the
    interval overlaps, or its nearest neighbours if it landed in silence.
    Read-only: nothing is written.
    """
    return ops.locate(
        path,
        clip_id,
        first=first,
        last=last,
        source_start=source_start,
        source_end=source_end,
    )


@_tool()
def timeline_status(path: str) -> dict[str, Any]:
    """Report the current timeline: duration, segment count, undo depth.

    `tail` echoes the finishing pass set with the `tail` tool, or null for
    none. `expected_frames`/`expected_duration` are what `export` would lay
    down — `timeline_duration` alone stays the `Edit`'s own length even with a
    tail configured, since the `Edit` never grows to describe one.
    """
    return ops.status(path)


@_tool()
def timeline_view(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """The whole edit at once: segments, cut seams, and every word's fate.

    timeline_status counts things; this says what they are. Each segment
    carries both coordinate systems (source in, timeline out), each seam is
    named by the surviving words either side of it rather than by the second
    it currently sits at, and each word reports whether it survived, how much
    of it did, and where it now plays.

    Survival is an overlap test, so a word a cut split reports present with
    `partial` set — that is normal on whisper timings, not a defect. Words
    with a suspect duration carry the same flag attach_transcript reported.

    This is locate asked once for the whole clip instead of once per range,
    and it is what the `lucid web` view draws. Read-only.

    `shots` is the picture lane the cue table projects — null when there are no
    cues, and null with a `shots_error` message when the plan refuses (a cue
    that was cut, or a shot longer than the asset it points at). The refusal is
    reported here rather than raised, because this is the view a person uses to
    find the cue to fix. `shots_rate` is the frame grid it was quantised on,
    which is export's rate and not `timebase`.
    """
    return ops.timeline_view(path, clip_id=clip_id)


@_tool()
def properties(
    path: str, clip_id: str | None = None, word_index: int | None = None
) -> dict[str, Any]:
    """Project/clip/cue detail for a properties inspector, composed only.

    No arguments: `status`, `canvas` and `caption_style`'s own reports.
    `clip_id`: adds that clip's `assets` entry, its `reframe` window table,
    and its whole `cue_ls`. Both `clip_id` and `word_index`: adds `cue` (the
    matching entry from that `cue_ls`, or null if the word carries none) and,
    only when `cue` is null, `context` — the word plus three either side,
    the same echo every word-indexed tool gives (a cue's own entry already
    carries this, so it is not duplicated). `word_index` needs `clip_id`.
    """
    return ops.properties(path, clip_id=clip_id, word_index=word_index)


@_tool()
def finish_report(path: str, framing: bool = False) -> dict[str, Any]:
    """Duration/canvas/caption/picture/marks/seams report for Finish mode,
    composed only — the truth strip's own numbers.

    `duration`: edit seconds, tail seconds, and their sum. `canvas`: the
    stored or footage-fallback canvas, plus each export preset's own
    ok/refusal-message. `captions`: whether a style is configured, its
    resolved font, and whether the last render actually burned it in
    ("yes"/"no"/"unknown" — unknown when no render log exists). `picture`:
    cue count, pinned count, and the picture plan's own refusal message when
    it has one. `marks`: unspoken marks applied vs. still stale. `seams`:
    the transcript's own overlap count. `flags`: the rolled-up warnings
    behind all of the above, each one naming the mode that fixes it.

    `framing` adds `reframe_coverage`'s stale-framing numbers and their two
    flags, and is off by default because it decodes placed footage for a
    scene-cut scan — 5.7s wall and 46s of CPU on the film, uncached, every
    call. Off, `framing` is `None`, which means "not measured" rather than
    "nothing stale".
    """
    return ops.finish_report(path, framing=framing)


@_tool()
def undo(path: str) -> dict[str, Any]:
    """Roll the timeline back to the state before the last mutation."""
    return ops.undo(path)


@_tool()
def export(
    path: str,
    output: str,
    export_format: str | None = "kdenlive",
    fps: float | None = None,
    preset: str | None = None,
    resolution: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Export the timeline, or render it.

    "kdenlive" writes an MLT project that Kdenlive opens and melt renders —
    the handoff that works on Linux. Pass export_format=null to render media
    instead. Other auto-editor targets (shotcut, premiere, resolve, final-cut-pro)
    pass straight through.

    A **multi-source** timeline — one with a cue table, or with two clips on
    it — is written by lucid itself as MLT ("kdenlive" or "mlt") and rendered
    by melt, because auto-editor refuses to export a second source and renders
    it at 720x576 while exiting 0. The reply says which writer ran
    ("auto-editor", "mlt" or "melt"), and a melt render reports the resolution
    and frame count measured off the finished file rather than melt's exit code.

    `fps` sets the NLE timeline's frame rate; it defaults to the picture's rate,
    or 30 for an audio-only project. It sets the render's frame rate too on the
    multi-source path, where lucid owns the profile; it is ignored when
    auto-editor renders a single-source timeline.

    `preset` is one of "youtube", "web", "tiktok-reels", or "custom" (which
    requires `resolution`) — a named quality bundle, only meaningful together
    with `export_format=null` (an NLE project file has no bitrate).
    "tiktok-reels" additionally **checks** that the project renders 9:16 and
    refuses otherwise: it never sets the shape, because a preset that reshaped
    a project would be an export argument rewriting project state. Set the
    shape with `canvas` first. `resolution` is `[width, height]`; it
    **letterboxes** the existing frame on the single-source render path — it
    does not crop or reframe it — and is refused outright on a multi-source
    (melt) project, where widening the hardcoded consumer to accept it has not
    been re-proven memory-safe (HISTORY.md § 4). The reply's `canvas` is the
    shape the render was built at, on either road.
    """
    return ops.export(
        path,
        output,
        export_format=export_format,
        fps=fps,
        preset=preset,
        resolution=tuple(resolution) if resolution is not None else None,
    )


@_tool()
def add_captions(
    path: str,
    output: str,
    clip_id: str | None = None,
    preset: str | None = None,
    max_words: int | None = None,
    max_gap: float | None = None,
    max_duration: float | None = None,
    hold: float | None = None,
    burn: str | None = None,
    burn_output: str | None = None,
) -> dict[str, Any]:
    """Write word-timed ASS captions for the current timeline to `output`.

    Timings follow the *timeline*, not the original recording, so captions stay
    correct after cuts; words that were cut are omitted and counted as
    `words_cut`.

    The look comes from the project — set it with caption_style, see it with
    caption_view. The arguments here override it for this one file and are not
    written back, so regenerating after a cut is styled the project's way
    again. Leave them unset unless you specifically want a one-off.

    The sidecar .ass is the default exit — Kdenlive loads it and it stays
    restylable. Pass `burn` (a render of THIS timeline) to burn the captions in
    with ffmpeg instead; against any other video the timings will not line up.
    """
    return ops.add_captions(
        path,
        output,
        clip_id=clip_id,
        preset=preset,
        max_words=max_words,
        max_gap=max_gap,
        max_duration=max_duration,
        hold=hold,
        burn=burn,
        burn_output=burn_output,
    )


@_tool()
def caption_view(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """The captions this timeline would produce, and the style in force.

    add_captions without writing a file: the same cues, in timeline seconds,
    already grouped by the project's own break rules — so this is how to check
    a restyle, or read back what a caption actually says at some moment,
    before committing a file to it.

    Reports rather than refuses: a project with no transcript, or one whose
    every word has been cut, comes back with an empty `cues` and a
    `cues_error` saying which. Read-only.
    """
    return ops.caption_view(path, clip_id=clip_id)


@_tool()
def caption_style(
    path: str,
    preset: str | None = None,
    font: str | None = None,
    size: int | None = None,
    text: str | None = None,
    highlight: str | None = None,
    outline_colour: str | None = None,
    box_colour: str | None = None,
    bold: bool | None = None,
    box: bool | None = None,
    outline_width: float | None = None,
    shadow: float | None = None,
    position: str | None = None,
    margin: int | None = None,
    karaoke: bool | None = None,
    max_words: int | None = None,
    max_gap: float | None = None,
    max_duration: float | None = None,
    hold: float | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the caption look this project keeps.

    The style is project state and the captions are derived from it, so a
    restyle survives every later cut: regenerating re-reads this. Call it with
    no arguments to read the current look and learn the field names; any
    argument sets that field and leaves the others alone. `reset` drops every
    override first — `reset` plus `preset` starts clean from a preset.

    `preset` is the base look ("clean", "karaoke" for per-word highlight, or
    "boxed"); everything else overrides one of its fields, and only the
    overrides are stored.

    Colours take "#rrggbb", "#rrggbbaa", a name ("yellow", "white", "red", …)
    or an ASS "&H…" value. `text` is the word's colour and `highlight` what it
    turns as it is spoken, which only shows with karaoke on. `position` is
    named: "bottom", "top", "top-right", and so on. Both come back resolved,
    because ASS quotes colours backwards and alpha-inverted.

    `plan` validates and resolves without writing. Use caption_view to see the
    result on the actual timeline.
    """
    return ops.caption_style(
        path,
        preset=preset,
        font=font,
        size=size,
        text=text,
        highlight=highlight,
        outline_colour=outline_colour,
        box_colour=box_colour,
        bold=bold,
        box=box,
        outline_width=outline_width,
        shadow=shadow,
        position=position,
        margin=margin,
        karaoke=karaoke,
        max_words=max_words,
        max_gap=max_gap,
        max_duration=max_duration,
        hold=hold,
        reset=reset,
        plan=plan,
    )


@_tool()
def canvas(
    path: str,
    size: str | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the shape this project renders at.

    The canvas is project state and every frame size derives from it — the
    MLT profile and the captions' reference canvas both read it, so a project
    cannot quote caption sizes against one shape and render another. Call it
    with no `size` to read what is in force plus the footage-derived shape it
    would fall back to; `reset` drops the override and returns to that shape.

    `size` is "WIDTHxHEIGHT", e.g. "1080x1920" for a vertical reel. Both
    edges must be even.

    Setting one has a routing consequence, reported as `routes_through`: an
    overridden project renders through the MLT writer whatever its source
    count, because auto-editor cannot be handed a canvas it will honour.
    An override that changes the *aspect* crops to fill rather than
    pillarboxing, so `cropped` names every clip that loses footage to it —
    use `reframe` to see or change which part of each one is kept.
    """
    return ops.canvas(path, size=size, reset=reset, plan=plan)


@_tool()
def tail(
    path: str,
    asset: str | None = None,
    seconds: float | None = None,
    fade: float | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the finishing pass this project plays after its last frame.

    An end card or a bumper, applied by `export` itself rather than glued on
    afterward with ffmpeg — the fix for a defect that has already shipped: a
    finishing pass applied downstream of `export` is dropped by every
    derivation at exit 0, silently, because nothing in the project ever knew
    it existed (HISTORY.md § The bumper the teaser never had, § The end card).
    Call it with no arguments to read what is in force.

    `asset` must be `card:name`, never a clip_id — `verify` diffs a render's
    own transcription against the timeline's words, and silence adds none of
    its own, which is exactly what a card behind it guarantees and a media
    clip would not. `seconds` is the tail's *whole* length, card included, not
    a hold with `fade` added on top of it (the known trap: `xfade` finishes
    exactly at the length it is given). `fade` is recorded and echoed but not
    yet drawn — this build cuts to the card hard, at `seconds`.

    Setting `asset` or `seconds` for the first time needs both together;
    either alone after that updates just that field, the same partial-update
    shape `caption_style` has. `reset` drops the tail entirely.

    **Needs an existing picture cue lane covering the whole film** — add cues
    first (`cue_add`) if the project does not have one; `export` names why
    otherwise. `plan` resolves and validates without writing.
    """
    return ops.tail(path, asset=asset, seconds=seconds, fade=fade, reset=reset, plan=plan)


@_tool()
def music(
    path: str,
    asset: str | None = None,
    clip_id: str | None = None,
    word_index_start: int | None = None,
    word_index_end: int | None = None,
    fade_in: float | None = None,
    fade_out: float | None = None,
    clear_end: bool = False,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the A2 music bed this project mixes under its edit.

    The cue stores word indices and an asset, never a length: the bed starts
    where `word_index_start` of `clip_id` lands on the timeline and runs to
    where `word_index_end` ends — or, with no end word, to the end of the
    timeline (the single-pass hold). Duration is derived at build time
    through the edit, so a cut before either boundary moves both
    automatically; a stored length was measured drifting onto live material
    (PLAN.md § The A2 music lane — the design note).

    `asset` is a registered clip_id, never `card:name` — a held frame has no
    sound to mix. It plays from its own head; shorter than its span pads out
    with real silence, longer is trimmed. Call with no arguments to read what
    is in force; first set needs `asset`, `clip_id` and `word_index_start`
    together, either alone after that updates its own field. `clear_end`
    drops the end word back to "to the end"; `reset` drops the bed entirely.
    `fade_in`/`fade_out` are seconds of fade drawn over the bed's audible
    span — a fade-out ends where the music actually ends, and a pair that
    outgrows the bed refuses at build time. `plan` resolves and validates
    without writing. Both word indices are echoed with their resolved words
    and neighbours — check them.
    """
    return ops.music(
        path,
        asset=asset,
        clip_id=clip_id,
        word_index_start=word_index_start,
        word_index_end=word_index_end,
        fade_in=fade_in,
        fade_out=fade_out,
        clear_end=clear_end,
        reset=reset,
        plan=plan,
    )


@_tool()
def vo_extend(
    path: str,
    clip_id: str,
    word_index: int,
    seconds: float,
    plan: bool = False,
) -> dict[str, Any]:
    """Open a gap in `clip_id`'s track for material the recording never had.

    The one item authorized to bend `Edit`'s subtractive invariant (PLAN.md
    § `vo_extend` — the design note) — a real hold in the VO, e.g. to let a
    line the film's own footage carries play under it, or manufactured
    mid-film silence for the same reason. Not the tail (`tail`, downstream of
    `Edit`), and not `restore` (which only ever walks the invariant backward).

    `word_index` names the last word *before* the gap; the hold opens
    immediately after that word's own end. The word must currently be on the
    timeline — an index naming cut material is refused rather than guessed
    at. `seconds` is the hold's length, an editorial call this makes no
    attempt to derive.

    The manufactured stretch is a real silent WAV, imported and registered
    like any other clip (never a clip_id widened past its registered
    duration, which is unreadable — melt would be asked for frames the file
    does not have). A second call at the same `seconds` reuses the same
    registered clip.

    **`covered_by` is the reason this needs its own design note.**
    `build_shots` runs each shot to the next cue, so whichever picture was
    already playing auto-extends across a hold by default — a silent
    success, with `shots_error`/`verify`/`check_frames` all staying clean.
    `covered_by` names every shot the opened gap now overlaps, so a stale
    freeze is visible instead of invisible; `[]` with no cue table at all,
    truthfully, since there is no picture layer to freeze.

    Two consequences ride along for free once a hold lands: `restore`
    refuses the moment `clip_id`'s segments stop being contiguous (its own
    existing check), and export permanently switches to the MLT writer
    (`_is_layered`'s existing multi-clip test) — there is no path back to
    auto-editor for a project that has ever been extended.

    `plan=True` resolves and reports `covered_by` without writing the
    manifest or the timeline; its `hold_clip_id` is a placeholder, since
    nothing was actually registered.
    """
    return ops.vo_extend(path, clip_id, word_index, seconds, plan=plan)


@_tool("path", "dest")
def reel(
    path: str,
    dest: str,
    start: float,
    end: float,
    canvas: str | None = None,
    name: str | None = None,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Derive a new project at `dest` holding `[start, end)` of this timeline.

    `start` and `end` are the seconds *an export plays at* — the same numbers
    cut_by_time takes, read off a watch — and they name the span to **keep**,
    which is the opposite direction from every other tool here. The head and
    the tail are what get cut, through cut_by_time.

    Reach for this before setting a vertical `canvas` on a film. The canvas is
    project state, so reshaping the film to take one reel would leave it
    reshaped afterwards; deriving is what keeps the film alone. Pass the reel's
    shape as `canvas` here (e.g. "1080x1920") and it is set on the copy only.

    Media is linked, not copied, so this costs a manifest rather than the
    footage. Descriptions and reframes come across unchanged and stay valid,
    because neither stores a timeline position. Cues come across only where
    the reel still has the word they hang on — read `cues_dropped`, which is
    one entry per picture the reel will not have, and read it head-first: one
    pruned just outside the kept span opens the reel on no picture at all.
    Every surviving cue is **pinned** to the in-point the film gave it, since
    dropping the others would otherwise make each one replay its asset from
    the head — a different film with nothing reporting it. `cues_pinned` names
    those, `pins_error` says why there are none. Cards are
    re-authored at the new canvas; read `cards_unrecorded` in the result,
    which names any that cannot be, and `over_platform_cap`, which says
    whether the result still runs longer than a vertical feed will take.

    A configured `tail` (an end card, a bumper) is never inherited — the
    derived project gets none, and `tail_dropped` reports what the film had,
    if anything. A teaser cut from an essay should not silently end on the
    essay's own end card.

    Refused if either kept edge lands on a word with a suspect duration — one
    that likely hides a retake, so the reel would open or close on the wrong
    take — unless `confirm_suspect=True`. Read `suspect_edges` in the result;
    it is about the reel's own two edges, not everything being cut away.

    `plan=True` resolves the spans and the clips it would link, and creates
    nothing.
    """
    return ops.reel(
        path,
        dest,
        start=start,
        end=end,
        canvas=canvas,
        name=name,
        confirm_suspect=confirm_suspect,
        plan=plan,
    )


@_tool()
def reframe(
    path: str,
    clip_id: str | None = None,
    rect: str | None = None,
    pane: str | None = None,
    src_start: float | None = None,
    interp: bool = False,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or set which part of each clip survives into the frame.

    What makes a swapped canvas fill the frame instead of pillarboxing it.
    A rect is "X,Y,W,H" in that clip's own source pixels — the region kept —
    and the default is a centre crop, which is **wrong whenever the subject
    is not centred**. Call it with no `clip_id` to read the crops in force for
    every clip, including how much of each is kept.

    An override is a floor rather than a frame: a rect that is not already
    the canvas's shape is grown to it, so nothing named is pushed off screen,
    and the reply gives both `asked` and the `crop` it became. It is stored
    as asked and refit whenever the canvas moves.

    `src_start` frames a **shot** rather than a clip: seconds into that clip's
    own source, the rect in force from there until the next window. One clip
    holds as many windows as it has camera shots, and because the address is
    the source's own clock, a clip used seven times picks up the right window
    at each placement with nothing said seven times. Omitted, it is the window
    from the head of the file — which is what a per-clip crop always was.
    `clips[].windows` in the reply is the whole series per clip.

    `pane` makes that window a **stacked split**: two half-height panes, `rect`
    on top and `pane` below, each cropping about twice the width one 9:16
    window gets. It is for the shot one window cannot frame — a two-hander,
    where every face is a true positive and only one of them is the shot, so
    picking between them loses one. Both rects are grown to the pane's shape
    rather than the canvas's, and a source too tall to carry it is refused.

    `interp` makes that window **slide in** from whatever governed before it,
    instead of stepping to it: MLT keeps drawing the frame in motion across
    the two windows rather than cutting between them. It flags the
    destination window, needs `src_start` after 0 (there is nothing before
    the head of the source to slide from), and cannot be combined with
    `pane` — a split's lower half has no interpolation of its own.

    `clip_id` with `reset` drops that clip's overrides — with `src_start`,
    only the window there — `reset` alone drops every one, and `plan` resolves
    without writing. Nothing *here* analyses the picture: `reframe_detect` is
    the tool that proposes crops, and it writes through this one rather than
    framing anything itself.
    """
    return ops.reframe(
        path,
        clip_id,
        rect=rect,
        pane=pane,
        src_start=src_start,
        interp=interp,
        reset=reset,
        plan=plan,
    )


@_tool()
def reframe_detect(
    path: str,
    clip_id: str | None = None,
    threshold: float = ops.SCENE_THRESHOLD,
    frames: int = ops.DETECT_FRAMES,
    apply: bool = False,
    split: bool = True,
) -> dict[str, Any]:
    """Propose a framing window per camera shot, from where the faces are.

    The first pass at the framing `reframe` refuses to guess. Every placement
    is split at its own camera cuts, each window is sampled at three moments,
    and the window is centred on the faces found there. Measured against the
    fifteen hand-framed windows that were watched and approved, it beats the
    centre crop it replaces on every column — 0.755 mean overlap against 0.568,
    112px displacement against 199px — and never leaves an approved subject
    entirely outside the frame, which the centre crop does on one shot.

    **It proposes; it does not frame.** `apply` is off by default, the opposite
    of most `plan` flags here and deliberately: the pass is still 24% of a
    window's width out on average, and 2 of the 15 hand windows were wrong in a
    way no watch showed. Call `reframe_sheet` and look before applying.
    Applying writes through `reframe` and **never over a window that is already
    an override** — that window is someone's decision.

    **A window with no face is named, never guessed at**, and comes back with
    `refused` saying so: a silent fallback is indistinguishable in the output
    from a framing decision. Expect roughly one window in seven. Read
    `falls_back_to` with it — nothing is written for a refused window, so
    whatever window is already in force carries over, which at the head of a
    clip is the centre crop and anywhere else is the **previous shot's**
    framing. Nothing here chooses the *subject* either — in a two-hander every
    face is a true positive and only one of them is the shot.

    **A window one crop cannot hold comes back as a stacked split**: `rect` and
    `pane`, two half-height panes holding both subjects at twice the width.
    That is the answer to the two-hander above, and `split=False` turns the
    offer off. The rule is strict on purpose — every sampled frame must hold
    two or three faces that one window cannot — which on the film is 3 windows
    of 59. `subjects` is the per-frame count, and the one to read: `faces` sums
    detections over the sampled frames, so it calls one face 3 and a room
    watching a television 33.
    """
    return ops.reframe_detect(
        path, clip_id=clip_id, threshold=threshold, frames=frames, apply=apply, split=split
    )


@_tool()
def reframe_coverage(
    path: str,
    clip_id: str | None = None,
    threshold: float = ops.SCENE_THRESHOLD,
) -> dict[str, Any]:
    """Which placed seconds are framed by a window chosen for an earlier shot.

    **The question `reframe_detect` cannot answer**, because that one is about
    a proposal and this is about the project as it stands. A detect run names
    `falls_back_to` for the windows it refuses that call and then throws it
    away; nothing is written for a refusal, so a project on disk cannot say
    that a stretch of it is held by a rect chosen for a shot that ended long
    before. On the film that was 13.6s of one clip across four camera setups,
    with the manifest, `status` and `reframe_sheet` all reporting clean.

    Every placement is walked against its own source's scene cuts. A cut with
    no window boundary within a frame of it opens a stale stretch, running to
    the next boundary or the placement's end. Two mechanisms reach that state —
    a refused proposal writes nothing, and a cut under `threshold` is never
    offered a window at all — and they are deliberately not separated, because
    the render cannot tell them apart either.

    Read `stale_seconds`, not the stretch count: it is an **override** held
    across a cut, which is worse than the default because a stale window looks
    deliberate. `default_seconds` beside it is the centre crop walking through
    a cut, which is only the default doing what it always did. Each stretch
    carries `timeline_start`, where it plays in the film, since the fix is to
    go and look — `reframe_sheet` for that, then `reframe_detect` on the clip.

    **`steps` is the mirror, and it is the one a viewer notices.** The walk
    above asks which cuts have no window; this asks which windows have no cut —
    a boundary *inside* one placement, where the frame travels sideways and the
    picture does not change. It reads as an edit that is not there, and
    coverage answers clean over it because nothing was held across anything.
    Each carries `shift` (how far the frame moves, in source pixels) and
    `nearest_cut`, which says whether the boundary missed a real cut narrowly
    or sits in the middle of a take. Boundaries are scored against every
    detected cut rather than the ones over `threshold`: a cut too weak to
    demand a window still explains one.

    Needs no face detector, reads and never writes.
    """
    return ops.reframe_coverage(path, clip_id=clip_id, threshold=threshold)


@_tool()
def reframe_sheet(
    path: str,
    out: str | None = None,
    moments: list[float] | None = None,
    extremes: bool = False,
) -> dict[str, Any]:
    """Draw every placement's framing window on its own source frames.

    **A framing decision is unreviewable without this.** The hand-framed
    teaser had 2 of its 15 windows wrong and neither was visible in motion —
    a badly-placed window reads as framing, because nothing in the frame says
    otherwise. Drawn on the whole source frame, the material the window is
    leaving out sits right beside it.

    Every placement the render shows — the picture lane's shots, or the edit's
    own segments where there is no lane — walked window by window, the window
    in force drawn in red and labelled with its rect. Placements and not clips:
    one clip used seven times reads seven stretches of itself.

    **A row is a window shown, not a placement.** Three fixed fractions of each
    placement missed 14 of the vertical cut's 55 windows, eight of them
    hand-approved, because a window covering a small slice of a long placement
    is one no round fraction lands in. Each placement is split at the
    boundaries it crosses and each stretch sampled inside itself, so `moments`
    are fractions of the window's own stretch.

    Returns the montage's path (under `cache/sheets/`, or `out`) and the table
    behind it: `window` is the source address the rect is stored at — what
    `reframe --src-start` takes to change it — and `windows` is how many the
    whole placement crosses. Stills come back under `skipped`: a card is
    authored at the canvas and never cropped, so it has no window to review.

    **A tile is evidence about an instant, not an approval of the span**, and
    `extremes` is what answers that. A static rect over a moving subject has a
    best moment and a sample can land on it — the teaser's opening window was
    184px out at its median while the one tile inside it landed 122px out and
    read as fine. Under `extremes` each stretch is probed with the face
    detector and drawn where the subject is leftmost, median and rightmost;
    since the rect does not move inside a stretch, the worst moment is one of
    those ends. Worst tile first, each labelled with the subject's offset from
    the middle of the crop, and `worst_offset` on the row is what to sort by. A
    stretch with no face in any probe says so rather than reporting extremes it
    does not have. It costs the detector and minutes of decoding, so it is off
    by default, and it is refused alongside `moments`.
    """
    return ops.reframe_sheet(path, out=out, moments=moments, extremes=extremes)


@_tool()
def thumbnail(
    path: str, clip_id: str, at: float, interval: float = ops.THUMB_INTERVAL
) -> dict[str, Any]:
    """One filmstrip frame for `clip_id`, at the source time nearest `at`.

    `at` snaps to a multiple of `interval` before anything is extracted, and
    the frame is cached under `cache/thumbs/` keyed by the clip's media size
    and mtime — a repeated ask for a nearby instant is a cache hit. The
    result is a path, not the image bytes; `lucid web` serves those over
    `/api/thumb/<clip_id>?at=`. It never enters the manifest, so nothing
    that renders can reach it (the same wall the preview proxy has).
    """
    return ops.thumbnail(path, clip_id, at, interval=interval)


@_tool()
def synopsis(
    path: str,
    clip_id: str | None = None,
    text: str | None = None,
    clear: bool = False,
) -> dict[str, Any]:
    """Read, set or clear what a clip *is* — the corpus b-roll gets chosen from.

    No `clip_id` lists every clip's synopsis and which are missing one;
    `clip_id` alone reads one; `text` writes; `clear` removes.

    A synopsis is a different fact from a `describe` window. A description
    says what is in front of the camera — rooms, clothing, lighting. A
    synopsis says what the footage is: the work, the scene, the people, and
    whatever else decides whether it belongs under a sentence. It is meant to
    carry what no camera can see, because that is where the signal turned out
    to be — measured on real footage, the vision index chose the same clip a
    human did 2 times in 25, and this catalogue read by something that knows
    the material chose it 13.

    Write these yourself. Nothing generates them: a model looking at the
    pixels cannot, and guessing a title from a filename would produce
    confident wrong placements rather than an obviously empty catalogue.
    """
    return ops.synopsis(path, clip_id, text, clear=clear)


@_tool()
def broll_brief(path: str, fps: float | None = None) -> dict[str, Any]:
    """The whole b-roll question as data: what there is, and what it goes under.

    Returns the footage catalogue with each clip's `synopsis` and duration,
    then every shot position on the timeline with the narration that plays
    over it, how long it is held, and what is currently there. `card: true`
    positions are shown for rhythm and are not choices.

    This is the half lucid can do. Choosing is the other half, and it belongs
    to you: read the brief, decide which clip goes under which sentence, and
    write the answers back with `cue_add`, where the picture plan checks each
    one. Ranking the catalogue by text similarity was measured and does not
    work — the sentence that earns a clip routinely shares no word with any
    description of it.

    `missing_synopsis` is the thing to fix first. A clip with no synopsis is
    invisible to any reasoning about the catalogue, so it will simply never
    be chosen.
    """
    return ops.broll_brief(path, fps=fps)


@_tool()
def verify(
    path: str,
    render: str,
    clip_id: str | None = None,
    transcript_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
    windowed: bool = False,
    # Bound to the module constants rather than restated: a stale literal here
    # is a tool whose schema advertises a default the CLI no longer uses.
    window: float = asr.WINDOW,
    overlap: float = asr.OVERLAP,
) -> dict[str, Any]:
    """Transcribe a finished render and diff it against what the timeline says.

    Run this after rendering, before calling an edit done. It transcribes the
    render with whisper and compares that word sequence to the one the timeline
    should play, which is the only check that catches a retake still in the
    picture: whisper collapses an immediate repeat into a single utterance, so a
    doubled phrase can be invisible in the source transcript and still be in the
    render.

    Read `repeated` first — an entry there is a phrase the render plays more
    times than the timeline expects, i.e. a surviving retake, with the heard word
    index to look at. `dropped` is the opposite: words the timeline expects that
    the render never says, usually a cut that reached too far.

    **A clean single-pass result is not proof.** This check has a known blind
    spot: the render's transcript is itself one whisper pass, which collapses a
    repeat the same way the source transcript did — three retakes survived a
    correct run of it on a real video. Set `windowed=True` to transcribe in
    short overlapping windows instead, which is what found them. It costs one
    whisper run over 2x the audio and uses a deliberately smaller model, so
    run the default first and escalate to it before calling an edit finished.

    `loud_gaps` comes back either way and trusts no transcript: it measures the
    render's own energy and reports holes in the heard word map that hold sound
    anyway. An entry is a place to *listen*, not a verdict — a music bed or an
    attenuated noise can produce one. Read `speech_db`/`threshold_db` beside it.

    `similarity` around 0.97 is normal on a *clean* render — whisper spells its
    own output differently on a second pass ("whodunit" / "who done it", "4" /
    "four"). Treat it as triage; `diff` is the artifact. Transcription takes
    minutes on a long render, and the result is cached under
    cache/verify/ and reported as `heard_transcript` — pass it back as
    `transcript_path` to re-diff without re-transcribing.
    """
    return ops.verify(
        path,
        render,
        clip_id=clip_id,
        transcript_path=transcript_path,
        model=model,
        language=language,
        windowed=windowed,
        window=window,
        overlap=overlap,
    )


@_tool()
def check_frames(path: str, target: str | None = None, fps: float | None = None) -> dict[str, Any]:
    """Check an export's frame count against what the timeline says it should be.

    The picture-side counterpart to `verify`, which covers only the audio. Run
    this on the exported NLE project **before** rendering — that is where it is
    worth the most, because the count settles whether the cut positions are
    right for the price of reading a document rather than encoding one.

    `target` is an NLE project (.kdenlive/.mlt/.xml, put to `melt -consumer
    xml`) or a finished render (counted with ffprobe). Omit it to just report
    `expected_frames`, the total the timeline lays down.

    Read `agrees` first, then `delta` — how many frames the target has that the
    timeline does not. A non-zero delta on an NLE project means the render will
    not be the length the edit is, and `notes` says so when the cause is one
    lucid already knows about. `agrees` is null, not false, for an audio-only
    render: it has no frames, so nothing was checked.

    `fps` must match the rate the export ran at or the two sides are counting on
    different grids; it defaults to the rate `export` would have picked.
    """
    return ops.check_frames(path, target, fps=fps)


@_tool()
def film_check(
    path: str,
    reference: str | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Compare this project against the export it is supposed to be.

    check_frames answers whether an export agrees with *this project's own*
    arithmetic; it cannot catch this project being the wrong film to begin
    with — a project can pass every check it has and still be seeded from a
    stale stage of an outside edit (HISTORY.md § The VO the project was
    holding: 73 segments/410.963s sat in a project whose shipped film was 63
    segments/336.269s, with the render, verify, the cue table and the shot
    plan all agreeing with the wrong one). This checks the project's
    `timeline_duration` against a reference file's own ffprobe duration —
    cheap, no frame counting, no melt. Segment count has nothing on the
    reference side to compare against once a film is encoded, so `segments`
    is reported alone and the notes say why.

    `reference` is remembered: passing it stores it on the project
    (additive, no schema bump), so a later call with no argument re-asks the
    same question against the same file. `reset` drops the stored reference;
    `plan` resolves without writing. With no reference given or stored, this
    reports the project's own numbers and says there is nothing to compare
    them against, rather than raising.
    """
    return ops.film_check(path, reference, reset=reset, plan=plan)


@_tool()
def import_edit(
    path: str,
    document: str,
    clip_id: str | None = None,
    plan: bool = False,
) -> dict[str, Any]:
    """Lay a cut made in Kdenlive down as this project's timeline.

    The supported way to bring an outside edit in. `seed_timeline` lays a clip
    down and lets auto-editor find the cuts; this takes a `.kdenlive` (or
    `.mlt`) playlist somebody already trimmed by hand and reads its surviving
    ranges into the timeline. It replaces the whole timeline, and the previous
    one is snapshotted first, so it is undoable like any other mutation —
    which is the part the hand-rolled version of this never had (HISTORY.md
    § The VO the project was holding: 63 ranges were parsed out of a
    `.kdenlive` and written straight to `Edit`, bypassing `cut` and its
    history).

    Every clip the document references has to be **registered already** — the
    resources are matched against registered clips by resolved path, and any
    that do not match are named rather than imported behind your back. Pass
    `clip_id` for a single-source document whose media sits at a path this
    project does not know.

    Ranges that overrun a clip's registered duration are clamped and reported
    in `overshot`, never silently dropped: auto-editor's own exports overshoot
    the tail by one frame, so a clean `overshot` is worth reading rather than
    assuming. `plan` resolves and checks without writing.

    Refused by name rather than half-read: a `<blank>` in the playlist (real
    runtime an `Edit` has nowhere to put), and two playlists carrying
    different cuts (a multi-track picture edit, which lucid's one linked A/V
    track has no shape for).
    """
    return ops.import_edit(path, document, clip_id=clip_id, plan=plan)


@_tool()
def check_black(
    path: str,
    target: str,
    fps: float | None = None,
    pix_th: float = 0.10,
    min_duration: float | None = None,
) -> dict[str, Any]:
    """Scan a render for black stretches, and say whether each is the known
    kdenlive-export tail frame (picture.KNOWN_TAIL_FRAME) or a genuine defect.

    `target` is required — unlike check_frames, there is no cheap no-target
    mode; there is nothing to detect black in without a render. A run is
    only ever explained when it sits at the tail *and* the frame delta
    against the timeline matches the known defect exactly; a black run
    inside the declared picture is always reported as a real defect.
    """
    return ops.check_black(path, target, fps=fps, pix_th=pix_th, min_duration=min_duration)


@_tool()
def spot_frames(
    path: str,
    target: str,
    count: int = 6,
    times: Sequence[float] | None = None,
    fps: float | None = None,
) -> dict[str, Any]:
    """Pull `count` evenly-spaced frames (plus any explicit `times`) from a
    render as PNGs with signalstats luma, ranked darkest-first.

    When `target`'s own probed duration still matches the current timeline
    within a frame (`mapping_trusted`), each frame also reports which
    clip/word it lands near via `Edit.source_at` — refused, not guessed,
    when the render looks stale.
    """
    return ops.spot_frames(path, target, count=count, times=times, fps=fps)


@_tool()
def speech_overlap(
    path: str,
    clip_id: str,
    at: float = 0.0,
    clip_in: float | None = None,
    clip_out: float | None = None,
    vo_clip_id: str | None = None,
    max_gap: float = 0.3,
    min_seam: float = 0.5,
    cap: float = energy.CAP,
) -> dict[str, Any]:
    """Does a proposed placement of `clip_id` overlap the VO's speech?

    The prerequisite check behind "can this clip speak here?" — answer it
    before designing any ducking. `at`/`clip_in`/`clip_out` describe where
    `clip_id` would sit on the timeline (defaults: unplaced at 0, its whole
    duration) — the clip need not be on the timeline yet, and usually isn't,
    since the current model is single-track. VO's own words map through the
    existing edit (`Edit.timeline_span`); `clip_id`'s map by offsetting into
    the proposed window instead. Both sides are trimmed with
    `energy.believable` first — an inflated word duration can hide a real
    seam — then merged into speech runs with `max_gap` tolerance, since a
    0.05s gap is not a usable seam.

    Read `overlaps` first: any entry means placing `clip_id` there would step
    on VO speech, not empty air — this caught exactly that on Billy/Stu,
    where the clip's speech nearly fully covered a VO thesis line with no
    clean seam to duck into. `clean_seams` (>= `min_seam` wide) are the
    windows where `clip_id` could speak without touching the VO. Read-only —
    nothing is written, and there is no `plan=`.
    """
    return ops.speech_overlap(
        path,
        clip_id,
        at=at,
        clip_in=clip_in,
        clip_out=clip_out,
        vo_clip_id=vo_clip_id,
        max_gap=max_gap,
        min_seam=min_seam,
        cap=cap,
    )


@_tool()
def attenuate_noises(
    path: str,
    clip_id: str,
    db: float = -12.0,
    max_event_seconds: float = 1.5,
    max_gap_seconds: float = 2.0,
    pad: float = 0.05,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Pull down short loud non-speech events instead of cutting them out.

    An event only qualifies automatically when it is both short
    (max_event_seconds) and sitting in a word-map gap narrow enough to prove
    the map is dense around it (max_gap_seconds) — a wide gap disqualifies
    even a very short event, which is the false-positive class this exists
    to prevent (speech sitting in a hole the transcript never wrote down).
    Qualifying events are pulled down `db` via one ffmpeg pass, never cut,
    and written as a new derived copy that `media_path()` picks up
    automatically everywhere downstream; the original is always what a
    re-run reads from, so repeated calls never compound gain.

    Unlike cut_by_transcript/cut_by_time, nothing here ever raises on what
    the scan finds — this is an automatic multi-candidate scan, not a
    handful of explicit ranges, so withholding is done per event rather than
    refusing the whole call. `suspect_neighbours` (a bounding word itself
    has a suspect duration — withheld unless confirm_suspect=True or
    plan=True) and `disqualified` (too long, or too wide a gap — never
    written, no override) are always reported in full, not only under
    plan=True.
    """
    return ops.attenuate_noises(
        path,
        clip_id,
        db=db,
        max_event_seconds=max_event_seconds,
        max_gap_seconds=max_gap_seconds,
        pad=pad,
        confirm_suspect=confirm_suspect,
        plan=plan,
    )


@_tool()
def proxy_transcode(path: str, clip_id: str, force: bool = False) -> dict[str, Any]:
    """Make footage the preview cannot decode playable in the window.

    The other half of what the viewer already reports: an unplayable clip
    names its reason (hev1, 10-bit, an unopenable container, an undecodable
    audio track) and shows black. This transcodes a downscaled h264/aac/mp4
    stand-in into the project's cache so it plays. One ffmpeg pass; a long
    clip is minutes.

    The result is a *preview* artefact and cannot reach a render: nothing
    records it in the manifest, so `media_path()` — what export, verify and
    check_frames all resolve through — has no way to see it. That containment
    is structural, not a convention to be careful about.

    Skips the work when a current proxy already exists (keyed by the source's
    size and mtime), so calling it on every unplayable clip in a project is
    cheap after the first pass. Refuses a clip that already plays, and refuses
    a file with no decodable streams — that is a broken file, not a codec
    problem, and it is the one refusal a transcode cannot close. `force`
    rebuilds a current proxy but does not override either refusal.
    """
    return ops.proxy_transcode(path, clip_id, force=force)


@_tool()
def review_add(
    path: str,
    name: str,
    source: str,
    kind: str,
    baseline: str | None = None,
) -> dict[str, Any]:
    """Register a rendered file, sheet or A/B member for `lucid review serve`.

    Never copies `source` — a render already lives in `renders/`, a sheet in
    `reframe_sheet`'s own directory — this just points `name` at it, so a
    served round has something to stream and a verdict has something to
    attach to.

    `kind` is one of `render`, `sheet`, `ab`, `control`. **A `control`
    requires `baseline`, the name of an already-registered item, and the two
    files' sha256 must match — a mismatch refuses the call.** This is the
    rule the round that went wrong exists to enforce (HISTORY.md § The
    bumper the teaser never had): a page once served three cuts, one
    mislabelled "control" when it was a different, later render. Nothing is
    labelled a control here unless it is byte-identical to what it claims.
    """
    return ops.review_add(path, name, source, kind=kind, baseline=baseline)


@_tool()
def review_verdict(path: str, name: str, verdict: str, note: str | None = None) -> dict[str, Any]:
    """Record a verdict against a review item registered by `review_add`.

    `verdict` is a free string, not an enum — past review rounds answered
    yes/no, "loop"/"hold", or a specific choice by name, and a fixed
    vocabulary would misfit whichever question the next round is actually
    asking.
    """
    return ops.review_verdict(path, name, verdict, note=note)


@_tool()
def review_list(path: str) -> dict[str, Any]:
    """Every item registered for this project's review round, and its verdict."""
    return ops.review_list(path)


def serve(
    root: str | Path | None = None,
    *,
    transport: str = "stdio",
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    allow_remote: bool = False,
    allow_remote_hosts: Sequence[str] | None = None,
) -> None:
    """Run the server. Blocks until the client disconnects (stdio) or interrupted (http).

    `root` binds every tool's `path` to one project (`_confine`). It is
    checked here rather than on first use because a bad root would otherwise
    surface as a refusal on every call, blaming the argument the client sent
    instead of the directory the server was started with. Existence is all
    that is checked: `init` under a bound root is legitimate, so requiring
    the root to already be a lucid project would refuse a real workflow.

    `transport` is `"stdio"` (the default — every existing client spawns the
    server this way, so changing the default would break them silently) or
    `"http"`. `host`, `port`, `allow_remote` and `allow_remote_hosts` are
    ignored for stdio.
    """
    global _BOUND_ROOT
    if root is not None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise ProjectError(f"cannot bind the MCP server to {root!r}: not a directory")
        _BOUND_ROOT = resolved

    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport != "http":
        raise ProjectError(f"unknown MCP transport {transport!r}: use 'stdio' or 'http'")
    _serve_http(
        host=host, port=port, allow_remote=allow_remote, allow_remote_hosts=allow_remote_hosts
    )


def _serve_http(
    *,
    host: str,
    port: int,
    allow_remote: bool,
    allow_remote_hosts: Sequence[str] | None = None,
) -> None:
    """Run the MCP server over streamable HTTP until interrupted.

    `host` must name loopback unless `allow_remote` is set — the opt-in
    `--host`/`--allow-remote` split asks for, because the MCP tools read and
    write whatever project this server is bound to (or any project, when
    unbound), so a non-loopback bind reaches anyone who can route to the
    port. Passing `allow_remote` says what it gives up: `_LoopbackGuard`'s
    allow-list widens from loopback names to loopback names *plus* the bound
    host, never to "accept anything" — a guard that admits any Host header
    is no guard at all.

    A wildcard bind (`host` in `_WILDCARD_HOSTS`) cannot widen that way: the
    literal string `"0.0.0.0"`/`"::"` is never what a real client's `Host:`
    header carries, only what an attacker who read the startup banner would
    send, so adding it would open the guard to a spoofed header while doing
    nothing for genuine remote clients — they arrive naming the address they
    actually dialed. `allow_remote_hosts` is required in that case: the
    operator names the address(es) clients will present (their LAN IP, a
    Tailscale hostname, ...), and only those are added.
    """

    if not allow_remote and host.lower() not in webui._LOOPBACK_NAMES:
        raise ProjectError(
            f"refusing to bind {host!r}: the MCP tools can read and write "
            "project files, so a non-loopback bind reaches anyone who can "
            "route to this port. Pass allow_remote=True (CLI: --allow-remote) "
            "once you mean that — it also widens the Host-header guard to "
            "accept this host, not just loopback."
        )
    if allow_remote and host.lower() in _WILDCARD_HOSTS and not allow_remote_hosts:
        raise ProjectError(
            f"refusing to bind {host!r} with allow_remote=True and no "
            "allow_remote_hosts: a wildcard bind has no single client-facing "
            "identity, so there is nothing honest to add to the Host-header "
            "guard's allow-list — a real client sends whatever address it "
            "dialed, never the wildcard itself. Pass allow_remote_hosts "
            "(CLI: --allow-remote-host, repeatable) naming the address(es) "
            "clients will actually present."
        )

    server, sock = _build_http_server(
        host=host, port=port, allow_remote=allow_remote, allow_remote_hosts=allow_remote_hosts
    )
    bound_port = sock.getsockname()[1]
    # Flushed: this is the one line a client needs to find the server, and a
    # piped stdout would otherwise hold it in the buffer (mirrors webui.serve).
    print(f"lucid mcp: http://{host}:{bound_port}/mcp", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        print()


def _build_http_server(
    *,
    host: str,
    port: int,
    allow_remote: bool,
    allow_remote_hosts: Sequence[str] | None = None,
) -> tuple[Any, socket.socket]:
    """Build (but do not run) the uvicorn server and its bound socket.

    Split from `_serve_http` so a test can start it on a thread and discover
    the real port (`port=0` picks a free one) the same way
    `tests/test_webui_http.py` does for `webui.make_server` — binding the
    socket here, synchronously, is what makes the port available before
    `server.run()` starts blocking.
    """
    import uvicorn

    allowed_names = set(webui._LOOPBACK_NAMES)
    if allow_remote:
        # A specific address is honest to echo back: a client that reaches
        # the server *by* that address naturally sends it in `Host:`. A
        # wildcard bind is not — see `_serve_http` and `_WILDCARD_HOSTS` —
        # so it contributes nothing here, only `allow_remote_hosts` does.
        if host.lower() not in _WILDCARD_HOSTS:
            allowed_names.add(host.lower())
        allowed_names.update(name.lower() for name in (allow_remote_hosts or ()))

    app = mcp.streamable_http_app(host=host)
    guarded = _LoopbackGuard(app, frozenset(allowed_names))

    config = uvicorn.Config(guarded, host=host, port=port, log_level="warning")
    sock = config.bind_socket()
    # `bind_socket()` only binds — `listen()` normally happens inside
    # uvicorn's own async startup, after `server.run()` is called, which is
    # too late for a caller that wants to print (or hand back) a URL that is
    # actually connectable the moment it returns. Calling `listen()` here is
    # safe to repeat: POSIX allows re-listening on a bound socket, which is
    # all asyncio's own server startup does to it next.
    sock.listen(config.backlog)
    server = uvicorn.Server(config)
    return server, sock
