# Security

## Reporting a vulnerability

Please report security problems privately, through GitHub's private
vulnerability reporting: the repository's **Security** tab, then **Report a
vulnerability**. Don't open a public issue for them.

## What counts

proofcut runs locally, but two of its servers can edit your projects and run an
agent, so anything that lets someone else reach them is in scope:

- **`proofcut web`** binds loopback, checks the `Host` header, and requires
  `application/json` on every request that changes something. With
  `--allow-remote` or `--tailscale` it also requires a token, sent as an
  `HttpOnly`, `SameSite=Strict` cookie. A way past any of these — DNS
  rebinding, cross-site requests, a token leak, reading files outside the
  project — is a vulnerability.
- **`proofcut mcp --transport http`** binds loopback and checks `Host`, the same
  way. A way to reach it from off the machine without `--allow-remote` is a
  vulnerability.
- **`proofcut review serve`** is meant to be reached from other devices and
  requires a token on every request. A way to read or stream a file without
  the token, or outside the review round, is a vulnerability.
- **Project confinement.** An MCP server started with `-C` must refuse any
  `path` outside its project. A way to read or write outside the project
  through a tool is a vulnerability.

Not in scope: anything that needs an attacker to already run code as you, and
what an agent you pointed at your own project decides to do inside it.
