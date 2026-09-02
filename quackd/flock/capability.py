"""The capability term: a robot bids only for a role its manifest can fill (ADR-0020).

Names are compared canonically, so a robot that provides `observe` satisfies a role that
requires `get_frame`. Both the member (before bidding) and the coordinator (before
counting a bid) apply the same check; the second is defence in depth for the day bids
arrive over a LAN from a robot we do not run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from quackd.duckfile.schema import FlockRole
from quackd.verbs.aliases import canonical


def missing(requires: Iterable[str], provides: Iterable[str]) -> list[str]:
    """The required verbs `provides` lacks, canonical and sorted; empty means satisfied."""
    have = {canonical(v) for v in provides}
    return sorted({canonical(r) for r in requires} - have)


def eligible_roles(roles: Mapping[str, FlockRole], provides: Iterable[str]) -> list[str]:
    """The roles a robot with these verbs may bid for, sorted by name."""
    have = list(provides)
    return sorted(name for name, role in roles.items() if not missing(role.requires, have))
