"""The typed records a Hero, a Map and the World keep and hand to other
modules: the facts engine, the metrics and the solver read them by field or
unpack them, and the shape each one has is declared here once."""

from typing import NamedTuple, TypedDict

# --- a hero's ------------------------------------------------------------

class Modifier(NamedTuple):
    """An ability's change to a stat, as ability_modifiers stores it: +50 percent
    damage_dealt amplifies, -45 reduces."""
    ability: str
    affects: str
    applies_to: str | None
    magnitude: float
    unit: str


class PerkEffect(NamedTuple):
    """A perk and the ability it alters."""
    perk: str
    ability: str


class Rates(NamedTuple):
    """A hero's win, pick and ban rate in one population, percent; a rate the
    capture does not publish is None."""
    win: float | None
    pick: float | None
    ban: float | None


class MapRate(NamedTuple):
    """A hero's win and pick rate on one map, percent."""
    win: float
    pick: float | None


# --- a map's -------------------------------------------------------------

class StageTerrain(NamedTuple):
    """How often a stage's own text mentions one terrain feature."""
    per_thousand: float
    mentions: int


# --- the World's ---------------------------------------------------------

class Synergy(NamedTuple):
    """A pair the wiki says plays well together: its score out of 3, and its note."""
    score: int | None
    note: str | None


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


class Patch(NamedTuple):
    """A patch shipped since the rates were captured, and its release day."""
    name: str
    released: str
