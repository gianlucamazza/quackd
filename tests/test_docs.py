"""Docs that make promises about code are checked against the code."""

from __future__ import annotations

import json
import re
from pathlib import Path

from quackd.transport import upstream_api as up
from quackd.verbs.registry import default_registry

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")


def test_transport_status_lists_every_upstream_ref() -> None:
    doc = (REPO / "docs" / "transport-status.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in up.all_refs() if ref.name not in doc]
    assert not missing, f"docs/transport-status.md is missing: {missing}"


def test_reachy_doc_lists_every_sdk_ref() -> None:
    from quackd.adapters.reachy_mini import upstream_api as reachy

    doc = (REPO / "docs" / "adapters" / "reachy_mini.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in reachy.all_refs() if ref.name not in doc]
    assert not missing, f"docs/adapters/reachy_mini.md is missing: {missing}"
    assert reachy.PIN[:7] in doc and "never" in doc.lower()  # the honesty label


def test_readme_promises() -> None:
    for needle in (
        "not affiliated with or endorsed by Pollen Robotics",
        "claude mcp add quackd",
        "dr-eureka",
        "github.com/pollen-robotics/microduck_rl",
        "--goal",
        "--provider fake",
        "biped",
        "pronounced",
        "Any LLM, one <code>.duck</code> file",
        "Non goals for now",
        "--provider openai",
        "--provider gemini",
        "--provider grok",
        "--provider ollama",
        "docs/local-llms.md",
        "| Local models (",
        "--flock",
        "flock-kick",
        "docs/flock.md",
    ):
        assert needle in README, needle
    assert "quadruped" not in README.lower()
    for hype in ("revolutionary", "world's first", "fully autonomous", "swarm intelligence"):
        assert hype not in README.lower(), hype


def test_readme_punctuation_style() -> None:
    """House style: no semicolons and no dashes used as punctuation (em/en dash, ' - ').

    Fenced code blocks are exempt (YAML lists, shell comments, JSON are what they are)."""
    prose = re.sub(r"```.*?```", "", README, flags=re.S)
    for i, line in enumerate(prose.splitlines(), 1):
        assert ";" not in line, f"README:{i}: semicolon"
        for dash in ("—", "–", " - "):  # noqa: RUF001  (em dash, en dash, spaced hyphen)
            assert dash not in line, f"README:{i}: dash punctuation {dash!r}"


def test_readme_ends_with_license_section() -> None:
    prose = re.sub(r"```.*?```", "", README, flags=re.S)  # ignore headings inside code blocks
    headings = re.findall(r"^## (.+)$", prose, flags=re.M)
    assert headings[-1] == "License", headings
    # a blank line (<br>) before every section, for breathing room on GitHub
    assert prose.count("<br>\n\n## ") == len(headings), "every H2 needs a <br> before it"


def test_readme_images_are_absolute_and_exist() -> None:
    srcs = re.findall(r'<img[^>]+src="([^"]+)"', README) + re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)", README
    )
    assert srcs, "README has no images"
    raw = "https://raw.githubusercontent.com/rokbenko/quackd/main/"
    for src in srcs:
        assert src.startswith("https://"), f"relative image breaks on PyPI: {src}"
        if src.startswith(raw):
            path = src[len(raw) :].split("?", 1)[0]  # ?v=N busts GitHub's image cache
            assert (REPO / path).exists(), f"missing asset {src}"


def test_readme_verbs_match_registry() -> None:
    for name in default_registry().names():
        assert f"`{name}`" in README, f"README does not mention verb {name}"


def test_mcp_doc_lists_every_tool() -> None:
    from quackd.mcp_server import TOOL_NAMES

    doc = (REPO / "docs" / "mcp.md").read_text(encoding="utf-8")
    missing = [name for name in TOOL_NAMES if f"`{name}" not in doc]
    assert not missing, f"docs/mcp.md is missing: {missing}"
    assert "--robots" in doc and "--robots" in README


def test_mcp_json_is_a_stdio_server() -> None:
    cfg = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))
    server = cfg["mcpServers"]["quackd"]
    assert "command" in server and "type" not in server
    assert "serve-mcp" in server["args"]


def test_adr_links_resolve() -> None:
    for md in (REPO / "docs").rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        for target in re.findall(r"\]\((adr/[^)]+\.md)\)", text):
            assert (REPO / "docs" / target).exists(), f"{md.name} links to missing {target}"
