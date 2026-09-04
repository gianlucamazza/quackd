"""The README, rewritten for PyPI at build time.

`README.md` is the long description on the PyPI project page, and its links are relative
because that is what is correct on GitHub: a relative link follows the branch you are
reading, so it works on `main`, on a tag and in a fork. PyPI has no such context, so every
one of them used to 404.

This metadata hook rewrites only what PyPI cannot resolve, in both of the ways this README
writes a link: Markdown `[text](target)` and the raw `<a href="target">` inside the centred
HTML blocks. Absolute URLs, in-page `#anchor` links and `mailto:` are left exactly as they
are, and images need no rewriting because the README already uses absolute
`raw.githubusercontent.com` URLs for them. The repository's own README is never modified.

`tests/test_pypi_readme.py` asserts the result has no relative link of either kind left, so
this staying correct does not depend on anyone remembering to open the PyPI page.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface

BLOB = "https://github.com/rokbenko/quackd/blob/main/"

_NOT_ABSOLUTE = r"(?!https?://|#|mailto:)"

RELATIVE_LINK = re.compile(rf"\]\({_NOT_ABSOLUTE}([^)]+)\)")
"""A Markdown link target PyPI cannot resolve."""

RELATIVE_HREF = re.compile(rf'(<a\s[^>]*href="){_NOT_ABSOLUTE}([^"]+)(")', re.I)
"""The same, in the raw HTML this README uses for its badges and centred blocks. Missing
these was the first version of this hook's own bug: four links kept 404ing while a test
said the rewrite was complete."""


def absolutise(markdown: str, base: str = BLOB) -> str:
    """Every relative link target, Markdown or HTML, prefixed with the repository URL."""
    out = RELATIVE_LINK.sub(lambda m: f"]({base}{m.group(1)})", markdown)
    return RELATIVE_HREF.sub(lambda m: f"{m.group(1)}{base}{m.group(2)}{m.group(3)}", out)


def relative_links(markdown: str) -> list[str]:
    """Every target PyPI could not resolve. Empty is the property the test asserts."""
    return RELATIVE_LINK.findall(markdown) + [m[1] for m in RELATIVE_HREF.findall(markdown)]


def pypi_readme(root: str | Path = ".") -> str:
    return absolutise(Path(root, "README.md").read_text(encoding="utf-8"))


class ReadmeHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        metadata["readme"] = {
            "content-type": "text/markdown",
            "text": pypi_readme(self.root),
        }
