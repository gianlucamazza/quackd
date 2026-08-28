"""Docs that make promises about code are checked against the code."""

from __future__ import annotations

import json
import re
from pathlib import Path

from quackd.transport import upstream_api as up
from quackd.verbs.registry import default_registry

REPO = Path(__file__).resolve().parents[1]


def test_transport_status_lists_every_upstream_ref() -> None:
    doc = (REPO / "docs" / "transport-status.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in up.all_refs() if ref.name not in doc]
    assert not missing, f"docs/transport-status.md is missing: {missing}"


def test_readme_status_and_disclaimer() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in (
        "not affiliated with or endorsed by Pollen Robotics",
        "docs/assets/hero.gif",
        "--provider fake",
        "claude mcp add quackd",
        "dr-eureka",
        "github.com/pollen-robotics/microduck_rl",
    ):
        assert needle in readme, needle


def test_readme_verbs_match_registry() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for name in default_registry().names():
        assert f"`{name}`" in readme, f"README does not mention verb {name}"


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
