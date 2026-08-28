"""The command line is the product's front door.

`uvx quackd run ducks/find-and-kick.duck --provider anthropic --transport sim2d` is the
north-star demo; every command here exists to make that line, and the debugging around it,
boring. Commands are thin: they parse, load `.env`, wire objects together, and hand off.
"""

from __future__ import annotations

import asyncio
import glob
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

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
    load_dotenv()


def _expand(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for pat in patterns:
        matches = sorted(glob.glob(pat))
        out.extend(matches if matches else [pat])
    return out


def _fail(msg: str, code: int = 1) -> None:
    # escape: messages contain things like quackd[anthropic], which Rich would eat as markup
    err_console.print(f"[red]error:[/red] {escape(msg)}")
    raise typer.Exit(code=code)


# ── validate ────────────────────────────────────────────────────────────────────────────


@app.command()
def validate(
    duckfiles: list[str] = typer.Argument(..., help=".duck files, globs, or bundled names."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print failures."),
) -> None:
    """Validate .duck files against the spec and the verb registry. Exits 1 on any failure."""
    from quackd.duckfile.parser import DuckParseError, load_duck
    from quackd.verbs.registry import default_registry

    registry = default_registry()
    table = Table(title="quackd validate", show_lines=False)
    table.add_column("file")
    table.add_column("name")
    table.add_column("verbs", justify="right")
    table.add_column("result")
    failures = 0
    for path in _expand(duckfiles):
        try:
            duck = load_duck(path)
        except DuckParseError as e:
            failures += 1
            table.add_row(path, "—", "—", f"[red]✗ {e.reason}[/red]")
            continue
        unknown = registry.unknown(duck.frontmatter.verbs.allow)
        if unknown:
            failures += 1
            table.add_row(
                path,
                duck.name,
                str(len(duck.frontmatter.verbs.allow)),
                f"[red]✗ unknown verbs: {', '.join(unknown)}[/red]",
            )
            continue
        if duck.frontmatter.learned_verbs:
            failures += 1
            table.add_row(
                path,
                duck.name,
                str(len(duck.frontmatter.verbs.allow)),
                "[red]✗ learned_verbs must be empty in v0.1 (v2 feature)[/red]",
            )
            continue
        if not quiet:
            table.add_row(
                path, duck.name, str(len(duck.frontmatter.verbs.allow)), "[green]✓ valid[/green]"
            )
    if not quiet or failures:
        console.print(table)
    if failures:
        raise typer.Exit(code=1)
    console.print(f"[green]{len(_expand(duckfiles))} file(s) valid.[/green]")


# ── list-verbs ──────────────────────────────────────────────────────────────────────────


@app.command("list-verbs")
def list_verbs() -> None:
    """List every registered verb with its params and safety class."""
    from quackd.verbs.registry import default_registry

    table = Table(title="verbs")
    table.add_column("name", style="bold")
    table.add_column("kind")
    table.add_column("safety")
    table.add_column("params")
    table.add_column("description")
    for v in default_registry().verbs():
        table.add_row(v.name, v.kind, v.safety_class, v.param_summary(), v.description)
    console.print(table)


# ── run / record ────────────────────────────────────────────────────────────────────────


def _confirm_prompt(name: str, params: dict[str, Any]) -> bool:
    return typer.confirm(f"⚠️  run {name}({params})?", default=False)


def _run_impl(
    duckfile: str | None,
    goal: str | None,
    provider: str,
    transport: str,
    model: str | None,
    seed: int | None,
    dry_run: bool,
    max_steps: int | None,
    runs_dir: str,
    yes: bool,
    live: bool,
    address: str | None,
    gif: bool,
    gif_size: int,
    verbose: bool,
) -> None:
    from quackd.agent.loop import RunConfig, run_duck
    from quackd.agent.providers.base import ProviderError
    from quackd.agent.providers.factory import make_provider
    from quackd.duckfile.parser import DuckParseError, duck_from_goal, load_duck
    from quackd.safety import KillSwitch, allow_all
    from quackd.transport.base import TransportError
    from quackd.transport.factory import make_transport
    from quackd.verbs.registry import default_registry

    if (duckfile is None) == (goal is None):
        _fail('give either a .duck file (or bundled name) or --goal "...", not both')
        return
    try:
        if goal is not None:
            safe = [v.name for v in default_registry().verbs() if v.safety_class == "safe"]
            duck = duck_from_goal(goal, safe)
        else:
            duck = load_duck(duckfile or "")
    except DuckParseError as e:
        _fail(str(e))
        return
    try:
        llm = make_provider(provider, model=model, duck_name=duck.name)
        duck_transport = make_transport(transport, seed=seed, address=address, live=live)
    except (ProviderError, TransportError, ImportError) as e:
        _fail(str(e))
        return

    recorder = None
    detector = None
    if transport == "sim2d":
        from quackd.perception.color_blob import ColorBlobDetector

        detector = ColorBlobDetector()
        if gif:
            from quackd.sim2d.recorder import FrameRecorder

            recorder = FrameRecorder(duck_transport, size=gif_size)

    def log(msg: str) -> None:
        if verbose:
            err_console.print(f"[dim]{msg}[/dim]")

    cfg = RunConfig(
        duck=duck,
        provider=llm,
        transport=duck_transport,
        detector=detector,
        dry_run=dry_run,
        confirm=allow_all if yes else _confirm_prompt,
        runs_dir=runs_dir,
        max_steps=max_steps,
        log=log,
        on_frame=recorder.capture if recorder is not None else None,
    )
    console.print(
        f"🦆 [bold]{duck.name}[/bold] · provider=[cyan]{llm.name}[/cyan] ({llm.model}) · "
        f"transport=[cyan]{duck_transport.name}[/cyan]"
        + (f" · seed={seed}" if seed is not None else "")
        + (" · [yellow]DRY RUN[/yellow]" if dry_run else "")
    )
    console.print("[dim]Ctrl-C or q stops the duck.[/dim]")

    async def main() -> Any:
        from quackd.agent.loop import AgentLoop

        loop = AgentLoop(cfg)
        ks = KillSwitch(loop.executor.abort, log=log)
        ks.install()
        try:
            return await loop.run()
        finally:
            ks.uninstall()

    _ = run_duck  # imported for symmetry; AgentLoop is used directly so the kill switch can bind
    result = asyncio.run(main())
    if recorder is not None:
        gif_path = recorder.save_gif(result.run_dir / "run.gif")
        result.gif_path = gif_path
    colour = {
        "success": "green",
        "failure": "red",
        "budget": "yellow",
        "aborted": "red",
        "error": "red",
    }[result.outcome]
    console.print(f"[{colour}]{result.outcome.upper()}[/{colour}] — {result.reason}")
    usage = result.usage
    console.print(
        f"steps={result.steps} llm_calls={result.llm_calls} "
        f"tokens={usage.input_tokens}+{usage.output_tokens}"
    )
    console.print(
        f"run dir: {result.run_dir}" + (f" · gif: {result.gif_path}" if result.gif_path else "")
    )
    if result.outcome != "success":
        raise typer.Exit(code=1)


_DUCK_ARG = typer.Argument(
    None, help="Path to a .duck file, or a bundled name (hello-world, find-and-kick, ...)."
)
_GOAL = typer.Option(
    None,
    "--goal",
    "-g",
    help='A plain-language goal instead of a .duck file, e.g. --goal "find the ball and kick it".',
)
_GIFSIZE = typer.Option(256, "--gif-size", help="sim2d: pixel size of each GIF pane.")
_PROVIDER = typer.Option(
    "fake", "--provider", "-p", help="fake · anthropic · openai · gemini · grok"
)
_TRANSPORT = typer.Option(
    "sim2d", "--transport", "-t", help="sim2d · mock · jsonrpc (experimental) · websocket (stub)"
)
_MODEL = typer.Option(None, "--model", "-m", help="Override the provider's model.")
_SEED = typer.Option(None, "--seed", help="Simulator seed (deterministic runs).")
_DRY = typer.Option(False, "--dry-run", help="Print every intent, send nothing.")
_MAXSTEPS = typer.Option(None, "--max-steps", help="Override the duck's max_steps budget.")
_RUNS = typer.Option("runs", "--runs-dir", help="Where run directories go.")
_YES = typer.Option(False, "--yes", "-y", help="Auto-confirm gated verbs (careful on hardware).")
_LIVE = typer.Option(False, "--live", help="sim2d: open a live pygame window (needs quackd[live]).")
_ADDR = typer.Option(None, "--address", help="jsonrpc: unix:///run/robotd.sock or tcp://host:port")
_VERBOSE = typer.Option(False, "--verbose", "-v", help="Log every intent to stderr.")


@app.command()
def run(
    duckfile: str | None = _DUCK_ARG,
    goal: str | None = _GOAL,
    provider: str = _PROVIDER,
    transport: str = _TRANSPORT,
    model: str | None = _MODEL,
    seed: int | None = _SEED,
    dry_run: bool = _DRY,
    max_steps: int | None = _MAXSTEPS,
    runs_dir: str = _RUNS,
    yes: bool = _YES,
    live: bool = _LIVE,
    address: str | None = _ADDR,
    gif: bool = typer.Option(True, "--gif/--no-gif", help="sim2d: write run.gif into the run dir."),
    gif_size: int = _GIFSIZE,
    verbose: bool = _VERBOSE,
) -> None:
    """Run a .duck file (or a --goal): the LLM picks verbs, quackd enforces the contract."""
    _run_impl(
        duckfile,
        goal,
        provider,
        transport,
        model,
        seed,
        dry_run,
        max_steps,
        runs_dir,
        yes,
        live,
        address,
        gif,
        gif_size,
        verbose,
    )


@app.command()
def record(
    duckfile: str | None = _DUCK_ARG,
    goal: str | None = _GOAL,
    provider: str = _PROVIDER,
    model: str | None = _MODEL,
    seed: int | None = typer.Option(0, "--seed"),
    max_steps: int | None = _MAXSTEPS,
    runs_dir: str = _RUNS,
    gif_size: int = _GIFSIZE,
    verbose: bool = _VERBOSE,
) -> None:
    """Like `run` on sim2d, but always writes a GIF (for READMEs and launches)."""
    _run_impl(
        duckfile,
        goal,
        provider,
        "sim2d",
        model,
        seed,
        False,
        max_steps,
        runs_dir,
        True,
        False,
        None,
        True,
        gif_size,
        verbose,
    )


# ── doctor / serve-mcp ──────────────────────────────────────────────────────────────────


@app.command()
def doctor() -> None:
    """Check the environment: keys, optional extras, transports."""
    from quackd.doctor import run_doctor

    ok = run_doctor(console)
    if not ok:
        raise typer.Exit(code=1)


@app.command("serve-mcp")
def serve_mcp(
    transport: str = _TRANSPORT,
    duckfile: str | None = typer.Option(
        None, "--duckfile", help="Load a .duck contract at startup."
    ),
    seed: int | None = _SEED,
    address: str | None = _ADDR,
    dry_run: bool = _DRY,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Allow confirm-gated verbs (there is no terminal to ask)."
    ),
) -> None:
    """Expose the duck as MCP tools over stdio (Claude Code / Claude Desktop)."""
    from quackd.mcp_server import serve

    serve(
        transport=transport, duckfile=duckfile, seed=seed, address=address, dry_run=dry_run, yes=yes
    )


if __name__ == "__main__":
    app()
