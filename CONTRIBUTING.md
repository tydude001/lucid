# Contributing to lucid

Issues and pull requests are welcome. lucid is maintained by one person in
their spare time, so a reply can take a while.

## Before you start

Run `uv run lucid doctor` first. Most "lucid is broken" reports turn out to be
a missing or wrong external binary, and doctor names the fix for each one.

For anything bigger than a bug fix, open an issue first. lucid's design is
recorded in [PLAN.md](PLAN.md), and a change that fights it will usually be
turned down however good the code is.

## The rules a pull request is checked against

[CLAUDE.md](CLAUDE.md) is the full list of traps. It is written for coding
agents and reads that way, but every entry in it is a real failure this repo
has already hit. These are the ones outside changes break most often:

- **Every MCP tool gets a matching `lucid` CLI subcommand.** The CLI is how an
  operation gets scripted and debugged without an agent in the loop, and the
  test suite enforces parity.
- **Register tools with `@_tool()`, never `@mcp.tool()`.** Both advertise the
  same schema, but only `@_tool()` confines `path` to the project the server
  is bound to (`-C`).
- **The web UI never decides anything.** Every change it makes posts to the
  same `ops` function the CLI and MCP tools call, and it renders that
  function's return value.
- **Test through the real process.** A new MCP tool gets a test in
  `tests/test_server_stdio.py` that talks to a spawned `lucid mcp` over stdio,
  and a web route gets one in `tests/test_webui_http.py` over a real socket.
  Calling the function directly proves nothing about whether it is reachable.
- **Don't edit an existing test to make it pass.** If your change and a test
  disagree, say so in the pull request. The test may be the one that is right.
- **Check renders, not exit codes.** ffmpeg, melt, auto-editor and libass all
  exit 0 on some failures. If your change touches rendering, check the output
  file (its duration, its frames, its audio) rather than the exit code.
- **Refer to documentation sections by name, never by number.** Sections get
  renumbered.

## Running the checks

```sh
uv sync
uv run ruff check .
uv run pytest
```

**Never run `ruff format`.** The repo has no ruff config, so the formatter
applies its 88-column default to code written wider and rewrites almost every
file, burying your actual change.

The full suite takes about ten minutes. Tests that need a binary you don't
have (whisper, auto-editor, melt, ImageMagick) skip rather than fail. The
seven tests that render through `melt` also need a display. Without one, try
`QT_QPA_PLATFORM=offscreen`, and run the suite under `xvfb-run -a` where
`lucid doctor`'s Display row says your MLT ignores it.

## Commits

Prefix commit messages with `feat:`, `fix:`, `docs:` or `chore:`. A change a
user can call bumps the minor version, in both `pyproject.toml` and
`src/lucid/__init__.py` (`tests/test_version.py` checks the two match).

By contributing, you license your contribution to the project under the
[MIT licence](https://opensource.org/license/mit) — inbound MIT, outbound
[PolyForm Shield](LICENSE). MIT's sublicense right is what lets your patch
ship under lucid's own terms, and under any commercial licence lucid later
offers, without a contributor agreement to sign. lucid itself is not MIT.
