"""The README is the PyPI long description, and PyPI cannot follow a relative link.

`README.md`'s links are relative on purpose: that is what is correct on GitHub, where a
relative link follows the branch you are reading. On the PyPI project page there is no
branch, so every one of them 404s. `hatch_build.py` rewrites them at build time.

That rewrite is invisible when it breaks: nothing in a normal run reads the built metadata,
and the only symptom is dead links on a page nobody on the team opens. So this test asserts
the property directly, without building anything. It checks both ways this README writes a
link, because the first cut of the hook handled only Markdown and left four raw `<a href>`
links 404ing while a narrower version of this test passed.
"""

from __future__ import annotations

import re
import tomllib

from hatch_build import BLOB, ReadmeHook, absolutise, pypi_readme, relative_links
from tests.conftest import REPO


def test_the_readme_itself_keeps_its_relative_links() -> None:
    """The repository's own README must NOT be absolutised: relative is right on GitHub."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert relative_links(readme), "README has no relative links left to rewrite"


def test_the_built_long_description_has_no_relative_links() -> None:
    left = relative_links(pypi_readme(REPO))
    assert not left, f"these would 404 on the PyPI project page: {left}"


def test_both_link_syntaxes_are_covered() -> None:
    """Markdown and raw HTML, because this README uses both and only one was handled."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    md = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)").findall(readme)
    html = re.compile(r'<a\s[^>]*href="(?!https?://|#|mailto:)([^"]+)"', re.I).findall(readme)
    assert md and html, "expected both link styles in the README"
    built = pypi_readme(REPO)
    for target in set(md) | set(html):
        assert f"{BLOB}{target}" in built, f"{target} was not rewritten"


def test_only_the_link_targets_change() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    built = pypi_readme(REPO)
    n = len(relative_links(readme))
    assert n > 0
    assert len(built) == len(readme) + n * len(BLOB), (
        "the rewrite inserted or dropped something besides the URL prefixes"
    )
    # images are already absolute, and PyPI renders the whole file on one page, so
    # in-page anchors must survive untouched
    assert built.count("raw.githubusercontent.com") == readme.count("raw.githubusercontent.com")
    for anchor in re.findall(r"\]\((#[^)]+)\)", readme):
        assert f"]({anchor})" in built, f"in-page anchor {anchor} was rewritten"


def test_absolutise_leaves_alone_what_pypi_can_already_resolve() -> None:
    keep = '[a](https://x.dev) [c](#anchor) [d](mailto:x@y.z) <a href="https://x.dev">e</a>'
    assert absolutise(keep) == keep
    assert absolutise("[e](docs/faq.md)", base="B/") == "[e](B/docs/faq.md)"
    assert absolutise('<a href="LICENSE">L</a>', base="B/") == '<a href="B/LICENSE">L</a>'


def test_the_hook_hatchling_actually_calls_produces_that_description() -> None:
    """The helpers above could be right while the hook wires them up wrongly."""
    metadata: dict[str, object] = {}
    ReadmeHook(str(REPO), {}).update(metadata)
    readme = metadata["readme"]
    assert isinstance(readme, dict)
    assert readme["content-type"] == "text/markdown"
    assert not relative_links(str(readme["text"]))


def test_pyproject_declares_the_hook_and_ships_it() -> None:
    """Half-applying this fails the build loudly, but a later edit could half-undo it."""
    cfg = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "readme" in cfg["project"]["dynamic"]
    assert "readme" not in cfg["project"], "a static readme= would win over the hook"
    assert cfg["tool"]["hatch"]["metadata"]["hooks"]["custom"]["path"] == "hatch_build.py"
    # the sdist must carry the hook, or building a wheel from it cannot run this
    assert "hatch_build.py" in cfg["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
