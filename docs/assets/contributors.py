"""Regenerate `contributors.svg`: one circle per human who has contributed.

Two hosted services were tried first and neither was right. `contrib.rocks` excludes bots
and sizes evenly, but its backend was still three days behind minutes after two people's
work merged, so the README would have thanked one person for a week. `contrib.nn.ci` is
current, but it has no bot filter and does not normalise a non-square avatar, so one face
came out larger than the rest.

So the image is ours: humans only (the GitHub API says who is a `Bot`), ordered by lines
added rather than commit count, every avatar clipped to the same circle with
`preserveAspectRatio="xMidYMid slice"` so a rectangular one is cropped rather than
squashed, and every byte embedded, so the file needs no network when GitHub renders it.

`.github/workflows/contributors.yml` runs this on every push to `main` and weekly, and
commits the result only when it changes. Run it by hand the same way:

    python docs/assets/contributors.py

Set `GITHUB_TOKEN` to avoid the anonymous API rate limit. Standard library only, because
this also runs on a bare CI image.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "rokbenko/quackd"
OUT = Path(__file__).with_name("contributors.svg")

SIZE = 64  # rendered diameter of one avatar
GAP = 10  # space between circles
PER_ROW = 12
RING = "#d0d7de"  # a hairline, so a white or dark avatar still reads as a circle


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "quackd-contributors"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return bytes(response.read())


def lines_added() -> dict[str, int]:
    """Lines added per author, from the stats endpoint, which reports them per week.

    Ordering by commits would put somebody who pushed six small commits ahead of somebody
    who sent one considered feature, which is backwards for a row that says thank you.
    The endpoint computes on demand and answers 202 while it does, so give it a few tries
    and fall back to the commit order rather than failing the run."""
    url = f"https://api.github.com/repos/{REPO}/stats/contributors"
    for attempt in range(5):
        try:
            raw = json.loads(_get(url))
        except urllib.error.HTTPError as e:  # 202 has an empty body while GitHub computes
            if e.code != 202 or attempt == 4:
                return {}
            time.sleep(2 * (attempt + 1))
            continue
        if not raw:  # 202 can also come back as an empty list
            time.sleep(2 * (attempt + 1))
            continue
        return {
            entry["author"]["login"]: sum(week["a"] for week in entry["weeks"])
            for entry in raw
            if entry.get("author")
        }
    return {}


def humans() -> list[dict[str, str]]:
    """Contributors with every `Bot` account dropped, most lines added first.

    Dependabot is a real contributor to this repository and still does not belong in a row
    of faces under the words "thank you to everyone who has sent quackd code"."""
    raw = json.loads(_get(f"https://api.github.com/repos/{REPO}/contributors?per_page=100"))
    people = [c for c in raw if c.get("type") == "User"]
    added = lines_added()
    if not added:
        print("stats endpoint unavailable, falling back to commit order", file=sys.stderr)
    people.sort(key=lambda c: (-added.get(c["login"], 0), -c.get("contributions", 0), c["login"]))
    return [
        {
            "login": c["login"],
            "avatar": c["avatar_url"],
            "url": c["html_url"],
            "added": str(added.get(c["login"], 0)),
            "commits": str(c.get("contributions", 0)),
        }
        for c in people
    ]


def avatar_data_uri(url: str) -> str:
    """The avatar, fetched at exactly the size we draw it and inlined."""
    payload = _get(f"{url}{'&' if '?' in url else '?'}s={SIZE * 2}")
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def render(people: list[dict[str, str]]) -> str:
    columns = min(len(people), PER_ROW) or 1
    rows = (len(people) + PER_ROW - 1) // PER_ROW or 1
    width = columns * SIZE + (columns - 1) * GAP
    height = rows * SIZE + (rows - 1) * GAP
    radius = SIZE / 2

    defs: list[str] = []
    body: list[str] = []
    for i, person in enumerate(people):
        x = (i % PER_ROW) * (SIZE + GAP)
        y = (i // PER_ROW) * (SIZE + GAP)
        defs.append(
            f'<clipPath id="c{i}"><circle cx="{x + radius}" cy="{y + radius}" r="{radius}"/></clipPath>'
        )
        body.append(
            f'<a href="{person["url"]}" target="_blank" rel="noopener">'
            f"<title>{person['login']} ({person['added']} lines added over "
            f"{person['commits']} commits)</title>"
            f'<image href="{avatar_data_uri(person["avatar"])}" x="{x}" y="{y}" '
            f'width="{SIZE}" height="{SIZE}" preserveAspectRatio="xMidYMid slice" '
            f'clip-path="url(#c{i})"/>'
            f'<circle cx="{x + radius}" cy="{y + radius}" r="{radius - 0.5}" fill="none" '
            f'stroke="{RING}" stroke-width="1"/>'
            f"</a>"
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="People who have contributed to quackd">\n'
        f"<defs>{''.join(defs)}</defs>\n" + "\n".join(body) + "\n</svg>\n"
    )


def main() -> int:
    people = humans()
    if not people:
        print("no contributors returned; refusing to write an empty image", file=sys.stderr)
        return 1
    OUT.write_text(render(people), encoding="utf-8")
    print(f"{OUT.name}: {len(people)} people ({', '.join(p['login'] for p in people)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
