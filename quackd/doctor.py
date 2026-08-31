"""`quackd doctor`: what can run here, and what this machine is assuming about the robot.

It exists because "it doesn't work" almost always means a missing extra, a missing key,
or an upstream assumption — and all three should be visible in one screen, before anyone
opens an issue.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import os
import platform
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from quackd import __version__
from quackd.agent.providers.factory import DEFAULT_MODELS, KEY_ENV, LOCAL_NAMES, PROVIDER_NAMES
from quackd.agent.providers.local import PRESETS
from quackd.duckfile.parser import list_bundled_ducks
from quackd.transport import upstream_api as up
from quackd.transport.factory import TRANSPORT_STATUS

EXTRAS = {
    "anthropic": ("anthropic", "quackd[anthropic]"),
    "openai": ("openai", "quackd[openai] / quackd[grok]"),
    "gemini": ("google.genai", "quackd[gemini]"),
    "yolo": ("ultralytics", "quackd[yolo]"),
    "live": ("pygame", "quackd[live]"),
}


def _installed(module: str) -> str | None:
    try:
        importlib.import_module(module)
    except Exception:
        return None
    dist = {"google.genai": "google-genai"}.get(module, module)
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return "?"


def _mask(value: str) -> str:
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "set"


def _probe_models(base_url: str, timeout_s: float = 1.5) -> str:
    """Reachability of an OpenAI-compatible server, plus the first few model ids."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=timeout_s) as r:
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return f"[yellow]HTTP {e.code}[/yellow]"
    except Exception:
        return "[dim]not running[/dim]"
    ids = [str(m.get("id", "")) for m in payload.get("data", []) if isinstance(m, dict)]
    shown = ", ".join(i for i in ids[:3] if i)
    more = f" (+{len(ids) - 3})" if len(ids) > 3 else ""
    return f"[green]up[/green] · {shown}{more}" if ids else "[green]up[/green] · no models loaded"


def run_doctor(console: Console) -> bool:
    ok = True
    console.print(
        f"[bold]quackd {__version__}[/bold] · Python {platform.python_version()} · "
        f"{platform.system()} {platform.release()}"
    )

    t = Table(title="core", show_header=False)
    for name, module in (
        ("pydantic", "pydantic"),
        ("mcp", "mcp"),
        ("opencv", "cv2"),
        ("numpy", "numpy"),
        ("Pillow", "PIL"),
    ):
        ver = _installed(module)
        t.add_row(name, f"[green]{ver}[/green]" if ver else "[red]missing[/red]")
        ok &= ver is not None
    t.add_row("bundled ducks", str(len(list_bundled_ducks())))
    console.print(t)

    t = Table(title="providers")
    t.add_column("provider")
    t.add_column("extra")
    t.add_column("key")
    t.add_column("default model")
    for name in PROVIDER_NAMES:
        if name == "fake":
            t.add_row("fake", "[green]built-in[/green]", "—", "scripted")
            continue
        module, extra = EXTRAS["openai" if name in ("grok", *LOCAL_NAMES) else name]
        ver = _installed(module)
        key = os.environ.get(KEY_ENV[name], "")
        model = os.environ.get("QUACKD_MODEL") or DEFAULT_MODELS.get(name) or "auto (first served)"
        if name in LOCAL_NAMES:
            key_cell = f"[green]{_mask(key)}[/green]" if key else "[dim]optional[/dim]"
        else:
            key_cell = (
                f"[green]{_mask(key)}[/green]" if key else f"[yellow]{KEY_ENV[name]} unset[/yellow]"
            )
        t.add_row(
            name,
            f"[green]{ver}[/green]" if ver else f"[yellow]missing[/yellow] ({extra})",
            key_cell,
            model,
        )
    console.print(t)

    t = Table(title="local LLM servers (GET /v1/models, 1.5 s timeout)")
    t.add_column("preset")
    t.add_column("base url")
    t.add_column("status")
    custom = os.environ.get("QUACKD_BASE_URL")
    for preset, url in {**PRESETS, **({"local": custom} if custom else {})}.items():
        if not url:
            t.add_row(preset, "[dim]set QUACKD_BASE_URL or --base-url[/dim]", "")
            continue
        t.add_row(preset, url, _probe_models(url))
    console.print(t)

    t = Table(title="transports")
    t.add_column("name")
    t.add_column("status")
    t.add_column("notes")
    for name, status in TRANSPORT_STATUS.items():
        note = ""
        if name == "jsonrpc":
            root = os.environ.get(up.RUNTIME_DIR_ENV.name, "/run")
            sock = Path(root) / "robotd.sock"
            if sys.platform == "win32":
                note = (
                    "Windows: use --address tcp://host:port via "
                    "`ssh -L 9870:/run/robotd.sock robot`"
                )
            elif sock.exists():
                note = f"[green]{sock} present[/green]"
            else:
                note = f"{sock} not found (not on a robot?)"
        if name == "websocket":
            note = up.WEBSOCKET_GATEWAY.note
        t.add_row(name, status, note)
    console.print(t)
    console.print(
        "[dim]flock mode (--flock): sim2d only in v0.3, in-process bus. "
        "A LAN bus for real ducks is future work (docs/flock.md).[/dim]"
    )

    t = Table(title="optional extras", show_header=False)
    for label, (module, extra) in EXTRAS.items():
        ver = _installed(module)
        t.add_row(label, f"[green]{ver}[/green]" if ver else f"[dim]not installed ({extra})[/dim]")
    console.print(t)

    unverified = up.refs_by_status("UNVERIFIED")
    t = Table(
        title=f"upstream assumptions (UNVERIFIED: {len(unverified)}) — see docs/transport-status.md"
    )
    t.add_column("what")
    t.add_column("note")
    for ref in unverified:
        t.add_row(ref.name, ref.note)
    console.print(t)
    console.print(
        f"[dim]upstream contract: duck-ipc-proto API v{up.API_VERSION.name} · "
        f"VERIFIED refs: {len(up.refs_by_status('VERIFIED'))}[/dim]"
    )
    return bool(ok)
