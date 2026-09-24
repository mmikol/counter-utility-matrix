"""The World: the whole database in memory - the heroes, the maps, the
relations between them and the names they resolve by. facts.tables.load
builds one from Postgres on every request, so the UI layer always reads what
the data layer stored. A hero's kit pieces and the numbers read off their
rows are facts.kit's; the records a Hero, a Map and the World hand on are
facts.records'.
"""

import datetime
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from db import KIND_ULTIMATE, Refusal
from db.data.names import name_key
from facts.kit import Kit
from facts.records import (
    MapRate,
    Modifier,
    Patch,
    PerkEffect,
    Rates,
    Snapshot,
    StageTerrain,
    StyleScore,
    Synergy,
)

ROLES = ("tank", "damage", "support")

REMECH = ("Call Mech",)     # climbing back into the mech: an ultimate by kind, not a fight tool
SQUISHY_POOL = 250


@dataclass(eq=False, kw_only=True)
class Hero:
    """A hero: who it is, its kit, its rates, and the numbers derived from them.
    The load builds one by keyword; equality and hashing are by identity."""
    id: int
    name: str
    role: str
    subrole: str
    health: int = 0
    shield: int = 0
    armor: int = 0
    portrait: str | None = None
    status: str = "released"            # announced: shown, never picked
    release_date: datetime.date | None = None
    styles: set[str] = field(default_factory=set)
    abilities: list[Kit] = field(default_factory=list)
    weapons: list[Kit] = field(default_factory=list)
    perks: list[Kit] = field(default_factory=list)
    modifiers: list[Modifier] = field(default_factory=list)
    perk_effects: list[PerkEffect] = field(default_factory=list)    # a perk, the ability it alters
    win: float | None = None
    pick: float | None = None
    ban: float | None = None
    by_tier: dict[str, Rates] = field(default_factory=dict)
    prev_win: float | None = None
    map_rates: dict[int, MapRate] = field(default_factory=dict)
    map_bans: dict[int, float] = field(default_factory=dict)        # map_id -> its ban rate, if any
    best_maps: list[int] = field(default_factory=list)              # map ids, three at most
    # What derive_scalars() reads off the kit and derive_rates() off the
    # rates, at rest: the class states its whole shape here, so a hero the
    # rows never filled reads zero rather than raising, and a reader sees
    # the fields in one place.
    pool: int = 0
    keywords: set[str] = field(default_factory=set)
    form_armor: float = 0.0
    dps: float = 0.0
    burst: float = 0.0
    hps: float = 0.0
    peak_heal: float = 0.0
    self_hps: float = 0.0
    self_heal: float = 0.0
    lifesteal: float = 0.0
    max_range: float = 0.0
    hitscan_range: float = 0.0
    cooldowns: list[float] = field(default_factory=list)
    median_cooldown: float | None = None
    weapon_kinds: set[str] = field(default_factory=set)
    hitscan: bool = False
    beam: bool = False
    melee: bool = False
    melee_only: bool = False
    aoe_count: int = 0
    aoe_damage: int = 0
    barrier_hp: float = 0.0
    pierces_barrier: bool = False
    overhealth: float = 0.0
    antiheal: float = 0.0
    heal_amp: float = 0.0
    dmg_amp: float = 0.0
    cc_tools: list[str] = field(default_factory=list)
    mobility_tools: list[str] = field(default_factory=list)
    flyer: bool = False
    cleanse_tools: list[str] = field(default_factory=list)
    invuln_tools: list[str] = field(default_factory=list)
    team_cleanse_tools: list[str] = field(default_factory=list)
    save_tools: list[str] = field(default_factory=list)
    deployables: list[str] = field(default_factory=list)
    ult: Kit | None = None
    ult_damage_raw: float = 0.0
    ult_damage: float = 0.0
    ult_cost: float | None = None
    dmg_ult: bool = False
    rank_spread: float = 0.0
    trend: float | None = None

    @property
    def released(self) -> bool:
        return self.status == "released"

    @property
    def ults(self) -> list[Kit]:
        """The ultimates the hero fights with: climbing back into the mech is not one."""
        return [a for a in self.abilities if a.kind == KIND_ULTIMATE and a.name not in REMECH]

    def derive_rates(self) -> None:
        """rank_spread and trend, from the rates the load read: the win rate's
        spread across the tiers, and its move since the previous capture."""
        tiers = [r.win for r in self.by_tier.values() if r.win is not None]
        self.rank_spread = max(tiers) - min(tiers) if len(tiers) >= 2 else 0.0
        self.trend = (
            self.win - self.prev_win
            if self.win is not None and self.prev_win is not None else None)

    def cap_ult(self, cap: float) -> None:
        """ult_damage: the raw figure, capped at `cap` where the roster has a cap."""
        self.ult_damage = min(self.ult_damage_raw, cap) if cap else self.ult_damage_raw

    def map_win(self, map_id: int) -> float | None:
        rate = self.map_rates.get(map_id)
        return rate.win if rate else None

    def map_ban(self, map_id: int) -> float | None:
        return self.map_bans.get(map_id)

    def map_pick(self, map_id: int) -> float | None:
        rate = self.map_rates.get(map_id)
        return rate.pick if rate else None


# the terrain the wiki's map articles describe, as map_terrain stores it
TERRAIN_FEATURES = (
    "chokes", "interiors", "high_ground", "flanks", "sightlines", "open_ground", "hazards",
    "cover")
# the terrain each playstyle is played on (authored; cover leans to none)
TERRAIN_LEAN = {
    "brawl": ("chokes", "interiors"),
    "dive": ("high_ground", "flanks", "hazards"),
    "poke": ("sightlines", "open_ground"),
}


class Map:
    """A map: its mode and stages, the terrain its wiki text describes, and the
    styles its rates and its terrain reward."""

    def __init__(self, mid: int, name: str, mode: str | None) -> None:
        self.id, self.name, self.mode = mid, name, mode
        self.stages: list[str] = []                             # in play order: see map_stages
        self.stage_terrain: dict[str, dict[str, StageTerrain]] = {}   # stage -> feature; text only
        self.stage_z: dict[str, dict[str, float]] = {}          # stage -> {feature: z}
        self.terrain: dict[str, float] = {}     # feature -> mentions per thousand words, with text
        self.terrain_z = dict.fromkeys(TERRAIN_FEATURES, 0.0)   # see tables.map_terrain
        self.rate_lift: dict[str, float] = {}                   # style -> z: see tables.map_styles
        self.terrain_lean: dict[str, float] = {}                # style -> z: see tables.map_terrain
        self.styles: dict[str, StyleScore] = {}     # style -> score: see tables.map_styles

    @property
    def style_top(self) -> str | None:
        if not self.styles:
            return None
        return sorted(self.styles, key=lambda s: (-(self.styles[s].score or 0), s))[0]

    @property
    def style_margin(self) -> float:
        scores = sorted((v.score or 0 for v in self.styles.values()), reverse=True)
        if len(scores) >= 2:
            return round(scores[0] - scores[1], 3)
        return scores[0] if scores else 0


class Resolved(NamedTuple):
    """A board's names as the World's objects: the map when one is named, and
    each side's heroes and the banned ones, in the order named."""
    map: Map | None
    red: list[Hero]
    blue: list[Hero]
    banned: list[Hero]


class World:
    """The whole database in memory: the heroes and maps by id and by name, the
    wiki's counters and synergies, the rates' provenance and the roster-wide
    figures the metrics are measured against."""

    def __init__(self) -> None:
        self.heroes: dict[int, Hero] = {}
        self.by_key: dict[str, int] = {}
        self.maps: dict[int, Map] = {}
        self.maps_by_key: dict[str, int] = {}
        self.counters: set[tuple[int, int]] = set()             # (loser, winner)
        self.answered_by: defaultdict[int, set[int]] = defaultdict(set)     # loser -> {winners}
        self.answers: defaultdict[int, set[int]] = defaultdict(set)         # winner -> {losers}
        self.synergies: dict[frozenset[int], Synergy] = {}      # frozenset({a, b}) -> the pair's
        self.partners: defaultdict[int, dict[int, Synergy]] = defaultdict(dict)     # a -> {b: pair}
        self.snapshots: list[Snapshot] = []
        self.newer_patches: list[Patch] = []
        self.subrole_passives: dict[str, str] = {}              # subrole -> its passive's text
        self.role_icons: dict[str, str | None] = {}
        self.heal_bench = 0.0
        self.hps_bench = 0.0         # 2 x the median sustained healing across the supports
        self.ult_cap = 0.0           # the largest single figure an ultimate publishes
        self.catalog_counts: dict[str, int] = {}     # the strategies mirror: kind -> count
        self.playbook = ""           # the folder the mirror came from, when not the shipped one

    # --- lookups -------------------------------------------------------

    def hero(self, name: str) -> Hero | None:
        hid = self.by_key.get(name_key(name))
        return self.heroes[hid] if hid is not None else None

    def map(self, name: str) -> Map | None:
        mid = self.maps_by_key.get(name_key(name))
        return self.maps[mid] if mid is not None else None

    def resolve(
            self, map_name: str | None, red: Sequence[str], blue: Sequence[str],
            bans: Sequence[str] = (), allow_announced: bool = False) -> Resolved:
        """Names -> Resolved(map or None, red, blue, banned). Each of these is
        a Refusal: an unknown name, a hero twice on one side, a pick that is
        banned - or, unless `allow_announced`, a hero announced but not yet
        released."""
        named = [*red, *blue, *bans]
        found = {n: self.hero(n) for n in named}
        unknown = [n for n in named if found[n] is None]
        if unknown:
            raise Refusal("unknown heroes: %s" % ", ".join(unknown))
        heroes = {n: h for n, h in found.items() if h is not None}
        # a hero may play for either team but cannot hold two seats on one, and a
        # ban list naming the same hero twice bans one hero
        for label, names in (("red", red), ("blue", blue), ("ban", bans)):
            seen: set[int] = set()
            twice: list[str] = []
            for n in names:
                hid = heroes[n].id
                twice.append(n) if hid in seen else seen.add(hid)
            if twice:
                raise Refusal(
                    "%s picks the same hero twice: %s" % (label, ", ".join(sorted(set(twice)))))
        early = [heroes[n] for n in named if not heroes[n].released]
        if early and not allow_announced:
            raise Refusal("announced, not yet playable: %s" % ", ".join(
                "%s (releases %s)" % (h.name, h.release_date) if h.release_date else h.name
                for h in early))
        m = None
        if map_name:
            m = self.map(map_name)
            if m is None:
                raise Refusal("unknown map: %s" % map_name)
        banned = [heroes[n] for n in bans]
        banned_ids = {h.id for h in banned}
        clash = [heroes[n].name for n in [*red, *blue] if heroes[n].id in banned_ids]
        if clash:
            raise Refusal("banned this match, cannot be picked: %s" % ", ".join(clash))
        return Resolved(map=m, red=[heroes[n] for n in red], blue=[heroes[n] for n in blue],
                        banned=banned)

    def heroes_by_role(self) -> list[Hero]:
        return sorted(self.heroes.values(), key=lambda h: (ROLES.index(h.role), h.name))

    def maps_sorted(self) -> list[Map]:
        return sorted(self.maps.values(), key=lambda m: m.name)

    def synergy(self, a: int, b: int) -> Synergy | None:
        return self.synergies.get(frozenset((a, b)))

    def is_countered_by(self, loser: int, winner: int) -> bool:
        """Whether the wiki reads `winner` as an answer to `loser`."""
        return (loser, winner) in self.counters
