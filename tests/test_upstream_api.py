"""UNVERIFIED upstream assumptions must not leak past the experimental backends.

One row per upstream (ADR-0006, extended by ADR-0022): the module that spells its names,
the only files allowed to touch its UNVERIFIED refs, and the source prefixes every ref must
link to.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

import pytest

from quackd.adapters.reachy_mini import upstream_api as reachy_api
from quackd.transport import upstream_api

PKG = Path(__file__).resolve().parents[1] / "quackd"

UPSTREAMS: list[tuple[ModuleType, set[str], tuple[str, ...]]] = [
    (
        upstream_api,
        {
            "transport/upstream_api.py",
            "transport/jsonrpc_unix.py",
            "transport/websocket_stub.py",
            "doctor.py",
        },
        ("https://github.com/pollen-robotics/microduck",),
    ),
    (
        reachy_api,
        {
            "adapters/reachy_mini/upstream_api.py",
            "adapters/reachy_mini/sdk.py",
            "doctor.py",
        },
        (
            "https://github.com/pollen-robotics/reachy_mini",
            "https://huggingface.co/datasets/pollen-robotics/",
        ),
    ),
]
IDS = ["microduck", "reachy_mini"]


def _unverified_identifiers(module: ModuleType) -> list[str]:
    return [
        name
        for name, value in vars(module).items()
        if isinstance(value, upstream_api.UpstreamRef) and value.status == "UNVERIFIED"
    ]


@pytest.mark.parametrize(("module", "allowed", "prefixes"), UPSTREAMS, ids=IDS)
def test_every_ref_has_a_source_link(
    module: ModuleType, allowed: set[str], prefixes: tuple[str, ...]
) -> None:
    for ref in module.all_refs():
        assert ref.source.startswith(prefixes), ref
        assert ref.status in ("VERIFIED", "UNVERIFIED")


@pytest.mark.parametrize(("module", "allowed", "prefixes"), UPSTREAMS, ids=IDS)
def test_unverified_refs_only_used_in_experimental_backends(
    module: ModuleType, allowed: set[str], prefixes: tuple[str, ...]
) -> None:
    idents = _unverified_identifiers(module)
    assert idents, "expected at least one UNVERIFIED ref"
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, idents)) + r")\b")
    offenders = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG).as_posix()
        if rel in allowed:
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


def test_reachy_verified_vocabulary_matches_the_sdk_read() -> None:
    # pinned to what was read; the sdk backend asserts the same strings at runtime
    assert reachy_api.MDNS_SERVICE.name == "_reachy-mini._tcp.local."
    assert reachy_api.WS_PATH.name == "/ws/sdk"
    assert reachy_api.EMOTIONS_DATASET.name == "pollen-robotics/reachy-mini-emotions-library"
    assert "no TTS" in reachy_api.MEDIA_PLAY_SOUND.note
    assert reachy_api.GET_STATUS.name == "client.get_status"  # not a ReachyMini method
    assert (
        reachy_api.DISABLE_MOTORS.status == "VERIFIED" and "NEVER" in reachy_api.DISABLE_MOTORS.note
    )
    assert reachy_api.PIN in reachy_api.LOOK_AT_WORLD.source
    assert len(reachy_api.refs_by_status("VERIFIED")) >= 40
