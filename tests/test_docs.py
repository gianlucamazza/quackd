"""Docs that make promises about code are checked against the code."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from quackd.transport import upstream_api as up
from quackd.verbs.registry import default_registry

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")


def test_adapter_status_lists_every_microduck_upstream_ref() -> None:
    doc = (REPO / "docs" / "adapter-status.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in up.all_refs() if ref.name not in doc]
    assert not missing, f"docs/adapter-status.md is missing: {missing}"
    from quackd.adapters.factory import BACKENDS

    for adapter, backends in BACKENDS.items():
        for backend in backends:
            assert f"`{adapter}:{backend}`" in doc, f"adapter-status.md lacks {adapter}:{backend}"
    # the old page is a redirect, not a stale copy
    old = (REPO / "docs" / "transport-status.md").read_text(encoding="utf-8")
    assert "adapter-status.md" in old and "VERIFIED (read" not in old


def test_adapter_guide_and_manifest_spec_match_the_code() -> None:
    from quackd.adapters.factory import ADAPTER_NAMES
    from quackd.verbs.core import REQUIREMENTS

    guide = (REPO / "docs" / "adapters.md").read_text(encoding="utf-8")
    for name in ADAPTER_NAMES:
        assert f"`{name}`" in guide, f"docs/adapters.md does not mention {name}"
    for fn in ("describe", "implementations", "conditions", "make"):
        assert f"def {fn}(" in guide
    spec = (REPO / "docs" / "manifest-spec.md").read_text(encoding="utf-8")
    for verb in REQUIREMENTS:
        assert f"`{verb}`" in spec, f"docs/manifest-spec.md does not list core verb {verb}"
    assert "manifest.schema.json" in spec and "digest()" in spec


@pytest.mark.parametrize("adapter", ["reachy_mini", "lerobot", "rosbridge", "open_duck"])
def test_adapter_doc_lists_every_upstream_ref(adapter: str) -> None:
    api = importlib.import_module(f"quackd.adapters.{adapter}.upstream_api")
    doc = (REPO / "docs" / "adapters" / f"{adapter}.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in api.all_refs() if ref.name not in doc]
    assert not missing, f"docs/adapters/{adapter}.md is missing: {missing}"
    assert api.PIN[:7] in doc and "never" in doc.lower()  # the honesty label


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


# ── counts, so a release cannot ship a number the code disagrees with ────────────────────

_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def _prose(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


@pytest.mark.parametrize("name", ["README.md", "docs/adapters.md", "docs/faq.md", "LAUNCH.md"])
def test_no_document_claims_the_wrong_number_of_adapters(name: str) -> None:
    """Half of the 0.5 documentation audit was stale counts that no test could see.

    "four adapters" was written in six places while five shipped. This does not police
    prose, only the specific claim that quackd has N adapters."""
    from quackd.adapters.factory import ADAPTER_NAMES

    right = _NUMBER_WORDS[len(ADAPTER_NAMES)]
    prose = _prose((REPO / name).read_text(encoding="utf-8")).lower()
    # only claim shapes that are unambiguously about how many adapters exist. "two robots
    # under one contract" is a heterogeneous flock, not a count of adapters.
    shapes = ("{w} adapters", "{w} robots supported", "{w} robots today")
    for count, word in _NUMBER_WORDS.items():
        if count == len(ADAPTER_NAMES):
            continue
        for shape in shapes:
            claim = shape.format(w=word)
            assert claim not in prose, (
                f"{name} says {claim!r}; quackd ships {right} ({', '.join(ADAPTER_NAMES)})"
            )


def test_the_readme_starter_table_lists_every_bundled_duck() -> None:
    """`open-duck-lookout` shipped in 0.5 and appeared nowhere in the README."""
    from quackd.duckfile.parser import list_bundled_ducks

    missing = [p.stem for p in list_bundled_ducks() if f"`{p.stem}`" not in README]
    assert not missing, f"README does not mention: {missing}"


def test_no_document_still_promises_a_removal_that_happened() -> None:
    """0.4 said `--transport` and the duck_* tools go in 0.5. They did, so nothing should
    still be promising it, and nothing should still be offering them."""
    from quackd.mcp_server import TOOL_NAMES

    assert not [n for n in TOOL_NAMES if n.startswith("duck_")]
    for path in sorted(REPO.glob("*.md")) + sorted((REPO / "docs").rglob("*.md")):
        if path.name in ("CHANGELOG.md", "PLAN.md") or {"design", "adr"} & set(path.parts):
            continue  # history and decisions record what was true when written
        text = _prose(path.read_text(encoding="utf-8"))
        assert "--transport" not in text, f"{path.name} still documents --transport"
        for promise in ("go away in 0.5", "gone in 0.5", "are removed in 0.5", "for one release"):
            assert promise not in text, f"{path.name} still promises {promise!r}, which happened"
