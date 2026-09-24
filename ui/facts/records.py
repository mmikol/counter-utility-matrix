"""The typed records a Hero, a Map and the World keep and hand to other
modules: the facts engine, the metrics and the solver read them by field or
unpack them, and the shape each one has is declared here once."""

from typing import NamedTuple, TypedDict


class Modifier(NamedTuple):
    """An ability's change to a stat, as ability_modifiers stores it: +50 percent
    damage_dealt amplifies, -45 reduces."""
    ability: str
    affects: str
    applies_to: str | None
    magnitude: float
    unit: str


class Snapshot(TypedDict):
    """One source's newest capture of rates, as the meta facts word it: the
    capture day, the patch and season it fell in, the queue and platform, and
    the regions its rows cover."""
    source: str
    captured: str
    patch: str | None
    released: str | None
    season: str | None
    queue: str
    platform: str
    region: str | None
