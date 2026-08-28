"""The command line is the product's front door.

`uvx quackd run ducks/find-and-kick.duck --provider anthropic --transport sim2d` is the
north-star demo; every command here exists to make that line, and the debugging around it,
boring. Commands are thin: they parse, load `.env`, wire objects together, and hand off.
"""

from __future__ import annotations

import typer
from rich.console import Console

from quackd import __version__

app = typer.Typer(
    name="quackd",
    help="Give your Microduck a brain. Any LLM, one .duck file. 🦆🧠",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"quackd {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """quackd — pilot a Microduck (real or simulated) with any LLM."""


def _not_yet(milestone: str) -> None:
    err_console.print(f"[yellow]Not implemented yet — lands in {milestone}.[/yellow]")
    raise typer.Exit(code=2)


@app.command()
def run(duckfile: str = typer.Argument(..., help="Path to a .duck file.")) -> None:
    """Run a .duck file: the LLM picks verbs, quackd enforces the contract."""
    _not_yet("M1")


@app.command()
def validate(duckfiles: list[str] = typer.Argument(..., help=".duck files or globs.")) -> None:
    """Validate .duck files against the spec (fails fast, exits non-zero)."""
    _not_yet("M1")


@app.command()
def doctor() -> None:
    """Check the environment: keys, optional extras, transports."""
    _not_yet("M4")


@app.command("serve-mcp")
def serve_mcp() -> None:
    """Expose the duck as MCP tools over stdio (Claude Code / Claude Desktop)."""
    _not_yet("M4")


@app.command("list-verbs")
def list_verbs() -> None:
    """List every registered verb with its params and safety class."""
    _not_yet("M1")


@app.command()
def record(duckfile: str = typer.Argument(..., help="Path to a .duck file.")) -> None:
    """Like `run`, but always writes a GIF (for READMEs and launches)."""
    _not_yet("M2")


if __name__ == "__main__":
    app()
