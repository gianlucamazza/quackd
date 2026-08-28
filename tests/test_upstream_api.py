"""UNVERIFIED upstream assumptions must not leak past the experimental transports."""

from __future__ import annotations

import re
from pathlib import Path

from quackd.transport import upstream_api

PKG = Path(__file__).resolve().parents[1] / "quackd"
ALLOWED = {
    "transport/upstream_api.py",
    "transport/jsonrpc_unix.py",
    "transport/websocket_stub.py",
    "doctor.py",
}


def _unverified_identifiers() -> list[str]:
    return [
        name
        for name, value in vars(upstream_api).items()
        if isinstance(value, upstream_api.UpstreamRef) and value.status == "UNVERIFIED"
    ]


def test_every_ref_has_a_source_link() -> None:
    for ref in upstream_api.all_refs():
        assert ref.source.startswith("https://github.com/pollen-robotics/microduck"), ref


def test_unverified_refs_only_used_in_experimental_transports() -> None:
    idents = _unverified_identifiers()
    assert idents, "expected at least one UNVERIFIED ref"
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, idents)) + r")\b")
    offenders = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG).as_posix()
        if rel in ALLOWED:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_verified_vocabulary_matches_upstream_enums() -> None:
    assert upstream_api.SOUND_TAG_LIST == (
        "alarm",
        "greet",
        "inquire",
        "peck",
        "chirp",
        "coo",
        "wheee",
    )
    assert "kick_left" in upstream_api.SKILLS.name and "sit_toggle" in upstream_api.SKILLS.name
    assert (
        upstream_api.ROBOT_MOVE.name == "robot.move"
        and "NOTIFICATION" in upstream_api.ROBOT_MOVE.note
    )
