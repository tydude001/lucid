"""lucid — an open-source, local-first AI video editor.

The public surface is the MCP server (``lucid mcp``) and the equivalent CLI
(``lucid <subcommand>``). Everything operates on a *project directory*; see
:mod:`lucid.project` for its layout.
"""

#: Duplicated in ``pyproject.toml`` deliberately. The metadata lookup that
#: would remove the copy reads the *installed* dist-info, which goes stale
#: against an editable checkout without saying so; tests/test_version.py
#: has the reasoning and holds the two numbers together.
__version__ = "0.21.0"

__all__ = ["__version__"]
