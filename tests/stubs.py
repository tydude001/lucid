"""A fake executable that runs on every OS the suite does.

Tests stand in for `whisper`, `claude` and `tailscale` with a small script
lucid spawns exactly as it would spawn the real binary. A shebang script is
that on Linux and macOS and nothing at all on Windows: CreateProcess runs a PE
image, or a batch file by its extension, and a script with a `#!` line is
neither — `[WinError 193] %1 is not a valid Win32 application`, the first
Windows CI run's error for every stub (2026-09-10).

So a stub is Python source, run by this interpreter on every OS, and on
Windows it gets a `.cmd` launcher beside it. **Use the path this returns**,
never the one passed in: on Windows they differ.

The host is read from `os.name`, never `sys.platform`, because tests patch
`sys.platform` to stand in for another OS and the stub has to run on the one
it is actually on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def write_stub(path: Path, body: str) -> Path:
    """Write `body` (Python source) as a program named `path`; return what to run."""
    if os.name != "nt":
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path
    script = path.with_name(path.name + ".py")
    script.write_text(body, encoding="utf-8")
    launcher = path.with_name(path.name + ".cmd")
    launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher
