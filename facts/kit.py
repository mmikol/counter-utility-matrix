"""The kit: an ability, a weapon config or a perk, its stat rows, and the
combat numbers read off them.

db/data/wiki/kits/measurements.py stores each wiki stat as measurements
(value, unit, condition) beside the stat's original value_text. This module
derives a kit piece's combat numbers from both at read time - a reload
worded beside a firing rate, a figure that is a sum and not one hit, a
percent worth its published cap - so a fix to how a wording is read is a
code change here and needs no re-pull. The rest of the facts package reads
the measurements and the keywords, never the prose.
"""

import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from db import KIND_ABILITY, KIND_WEAPON

# the qualifiers that land a keyword on a teammate ("heal;;target ally")
ALLY_QUALIFIERS = ("target ally", "targets")
# an area row: it lands on the body, never the head
SPLASH_RE = re.compile(r"explosion|splash", re.I)
# a flat damage figure that is a sum, not one hit
SUMMED_RE = re.compile(r"\b(dot|over time|total|if all|both|maximum)\b", re.I)
# a rate with its reload folded in, as the wiki words it beside the firing rate
RELOAD_RE = re.compile(r"reload|overall|recharge", re.I)
# the same figure inside the row's own text: "125 while firing (108.7 overall w/reload)"
TEXT_RELOAD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:overall\b|w/\s*reload|with reload)", re.I)
# a percent or a rate of overhealth is worth its published cap: "60 percent (400 max)"
OVERHEALTH_CAP_RE = re.compile(r"(?:up to|max\.?)\s*(\d+)|(\d+)\s*max", re.I)
# a figure in prose, or a range's two ends: "100 - 50"
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?")
MIN_FALLOFF = 10.0      # a "falloff range" under this is a splash radius, not a reach
MIN_KNOCKBACK = 10.0    # m/s onto an enemy; under this a knockback is a nudge, not crowd control


@dataclass(slots=True, kw_only=True, eq=False)
class Stat:
    """One measurement of a kit piece as the data layer stored it: a value in
    its units, under a condition, and the wiki's own words for the stat. It is
    built by keyword, since its two unit columns and its two text columns sit
    side by side and a swapped pair would still read as a stat. A numeric
    column arrives as a Decimal and is held as a float."""
    code: str
    value: float | None
    unit_num: str | None
    unit_den: str | None
    den_value: float | None
    condition: str | None
    text: str | None

    def __post_init__(self) -> None:
        self.value = float(self.value) if self.value is not None else None
        self.den_value = float(self.den_value) if self.den_value is not None else None

    def rendered(self) -> str:
        """The value with its units and condition; the wiki's words where no value
        was read."""
        if self.value is not None:
            out = "%g" % self.value
            if self.unit_num:
                out += " " + self.unit_num
            if self.unit_den:
                count = "%g " % self.den_value if self.den_value not in (None, 1) else ""
                out += " per " + count + self.unit_den
        else:
            out = self.text or "?"
        if self.condition:
            out += " (%s)" % self.condition
        return out

    @property
    def per_second(self) -> float | None:
        """The value as a per-second rate, or None if not one."""
        if self.value is None or self.unit_den != "seconds":
            return None
        return self.value / (self.den_value or 1.0)

    @property
    def overhealth(self) -> float | None:
        """Overhealth in hp as published; a percent or a rate is worth its cap."""
        if self.unit_num == "hp" and self.unit_den is None:
            return self.value
        found = OVERHEALTH_CAP_RE.search("%s %s" % (self.text or "", self.condition or ""))
        return float(found.group(1) or found.group(2)) if found else None


class Figure(NamedTuple):
    """A flat row in hit points: its value, and the condition and words it was
    published under."""
    value: float
    condition: str | None
    text: str | None


class WeaponConfig(TypedDict, total=False):
    """What a weapon config's piece carries beside its stats: the weapon it
    belongs to, the wiki's weapon type and the slot it fires from. An ability
    or a perk carries none of it."""
    weapon: str
    weapon_type: str | None
    slot: str


def _first_figure(text: str | None) -> float | None:
    """The first figure in a line of the wiki's prose; of a range, its top."""
    found = NUMBER_RE.search(text or "")
    return float(found.group(2) or found.group(1)) if found else None


def _reload_figure(stat: Stat, value: float) -> float | None:
    """A rate row's figure with the reload in, where its wording has one: the
    figure in its condition ("68.18 overall w/reload"), else the one its text
    words beside the firing rate, else `value` itself. None when neither the
    condition nor the text speaks of a reload."""
    if RELOAD_RE.search(stat.condition or ""):
        return _first_figure(stat.condition)
    if RELOAD_RE.search("%s %s" % (stat.condition or "", stat.text or "")):
        found = TEXT_RELOAD_RE.search(stat.text or "")
        return float(found.group(1)) if found else value
    return None


def _one_hit(stat: Figure, tick: float, lasts: float, singles: list[float]) -> bool:
    """A flat damage row that is one hit: not a sum, not the piece's rate over
    its duration (`tick` hp/s for `lasts` s), and not several of a single
    unconditioned hit at once."""
    if SUMMED_RE.search("%s %s" % (stat.condition or "", stat.text or "")):
        return False
    if tick and lasts and abs(stat.value - tick * lasts) < 0.5:
        return False                    # the rate over its duration, not a hit
    # five orbs at once: not one hit
    return not any(one and stat.value > one and stat.value % one == 0 for one in singles)


class Kit:
    """An ability, a weapon config or a perk: a named thing with stats."""
    __slots__ = ("atoms", "description", "extra", "keywords", "kind", "name", "stats")

    def __init__(
            self, name: str, kind: str, description: str | None = "",
            keywords: str | None = "") -> None:
        self.name, self.kind, self.description = name, kind, description
        self.atoms = {k.strip().lower() for k in (keywords or "").split("::") if k.strip()}
        self.keywords = {a.split(";;")[0].strip() for a in self.atoms}
        self.stats: defaultdict[str, list[Stat]] = defaultdict(list)
        self.extra: WeaponConfig = {}

    def qualifiers(self, family: str) -> set[str]:
        """The qualifiers the wiki hangs on one keyword family here."""
        return {
            a.split(";;", 1)[1].strip() for a in self.atoms
            if ";;" in a and a.split(";;")[0].strip() == family}

    @property
    def for_allies(self) -> bool:
        """Tagged as landing on a teammate."""
        return any(a.split(";;", 1)[1].strip() in ALLY_QUALIFIERS for a in self.atoms if ";;" in a)

    def plain_stat(self, code: str) -> float | None:
        """The largest value published without a condition; with none, the
        largest of all - "300 default, 750 during Rally" is 300."""
        rows = [(s.value, s.condition) for s in self.stats.get(code, ()) if s.value is not None]
        plain = [value for value, condition in rows if not condition or condition == "default"]
        return max(plain) if plain else max((value for value, _ in rows), default=None)

    def max_stat(self, code: str) -> float | None:
        return max((s.value for s in self.stats.get(code, ()) if s.value is not None), default=None)

    def flat(self, code: str) -> list[Figure]:
        """The rows in hit points: not a rate, not a percent."""
        return [
            Figure(value=s.value, condition=s.condition, text=s.text)
            for s in self.stats.get(code, ())
            if s.value is not None and s.unit_den is None and s.unit_num != "percent"]

    @property
    def damages(self) -> bool:
        return bool(self.stats.get("damage") or self.stats.get("dps"))

    @property
    def shoves(self) -> bool:
        """Knocks an enemy back at MIN_KNOCKBACK or more."""
        pushes = (
            s.value for s in self.stats.get("kbspeed", ())
            if s.value is not None and "self" not in (s.condition or ""))
        return max(pushes, default=0.0) >= MIN_KNOCKBACK

    @property
    def weapon_kind(self) -> str:
        return (self.extra.get("weapon_type") or "").lower()

    @property
    def reach(self) -> float | None:
        """How far a damaging piece fights, in metres: its published range, or the
        end of its damage falloff. None when it publishes neither."""
        falloff = self.max_stat("damage_falloff_range") or 0.0
        limits = (self.plain_stat("range"), falloff if falloff >= MIN_FALLOFF else None)
        return max((v for v in limits if v), default=None)

    def typed(self, text: str) -> bool:
        """The wiki's Type field names it: one shot_type row a type."""
        return any((s.text or "").strip().lower() == text for s in self.stats.get("shot_type", ()))

    # --- rates -------------------------------------------------------------

    def rate(self, code: str, per_shot: str) -> float | None:
        """This piece's sustained rate for `code` (dps or hps), hp/s: the
        published rate with its reload where the wiki gives one, else the firing
        rate over its magazine and reload where the kit publishes both, else the
        firing rate, else one `per_shot` times the fire rate. None when nothing
        says."""
        loaded, plain, variants, worded = self._published_rates(code)
        if loaded:
            return min(loaded)
        firing: float | None
        if plain:
            firing = max(plain)
        elif variants:
            firing = statistics.median_low(variants)
        else:
            firing = self._per_shot_rate(per_shot)
        if not firing or worded:
            return firing               # the text words its own reload figure: left alone
        return self._with_reload(firing)

    def _published_rates(self, code: str) -> tuple[list[float], list[float], list[float], bool]:
        """The `code` rows by their wording, (loaded, plain, variants, worded):
        each rate with its reload in, the rates published without a condition,
        the ones under one ("variant 2", "at full charge"), and whether a row's
        text words its own reload figure."""
        loaded: list[float] = []
        plain: list[float] = []
        variants: list[float] = []
        worded = False
        for stat in self.stats.get(code, ()):
            value = stat.value if stat.value is not None else _first_figure(stat.text)
            if value is None:
                continue
            worded = worded or bool(RELOAD_RE.search(stat.text or ""))
            with_reload = _reload_figure(stat, value)
            if stat.value is None and with_reload:
                loaded.append(with_reload)      # prose: its first figure may be another fire mode
                continue
            if with_reload is not None and with_reload <= value:
                loaded.append(with_reload)
            elif stat.condition and not RELOAD_RE.search(stat.condition):
                variants.append(value)          # "variant 2", "at full charge"
            else:
                plain.append(value)
        return loaded, plain, variants, worded

    def _per_shot_rate(self, per_shot: str) -> float | None:
        """One `per_shot` figure times the fire rate. With no rate to turn a
        figure into one, a figure worded "over time", which already is one."""
        rate = self.max_stat("fire_rate")
        # the hit the rate counts: "1.18 swings per second" is the swing, not the finisher
        counted = {(s.unit_num or "").rstrip("s") for s in self.stats.get("fire_rate", ())} - {""}
        rows = [
            (s.condition, s.value) for s in self.stats.get(per_shot, ())
            if s.value is not None and s.unit_den is None]
        shots = [value for condition, value in rows if condition in counted]
        shots = shots or [value for _, value in rows]
        if shots and rate:
            return max(shots) * rate
        # Nothing published a rate: no dps row, and no fire_rate to turn a
        # per-shot figure into one. A damage row worded "over time" already is
        # a rate - the wiki writes Domina's beam as 60 over time, which its own
        # tooltip spells 7.2 every 0.12 seconds - so read it as one rather than
        # leave a tank dealing no damage. Only where nothing else scored.
        sustained = [
            s.value for s in self.stats.get(per_shot, ())
            if s.value is not None and "over time" in (s.condition or "").lower()]
        return max(sustained, default=None)

    def _with_reload(self, firing: float) -> float:
        """`firing` over the magazine's share of magazine plus reload, where the
        kit publishes both. A reload worded "per shot" or "from empty" is ammo
        that regenerates: a reload under a condition does not count."""
        ammo = self.max_stat("ammo")
        rate = self.max_stat("fire_rate")
        reloads = [
            s.value for s in self.stats.get("reload_time", ()) if s.value and not s.condition]
        if not (ammo and rate and reloads):
            return firing
        lasts = ammo / (self.max_stat("ammo_drain") or 1.0) / rate
        return firing * lasts / (lasts + max(reloads))

    def heal_rate(self) -> float | None:
        """Healing per second onto a target: a weapon's sustained rate; else the
        largest per-second heal, up for `duration` of every duration plus
        cooldown where the piece publishes both. A heal on the hero itself is
        not counted."""
        rate = self.rate("hps", "heal") if self.kind == KIND_WEAPON else None
        if rate is not None:
            return rate
        rate = max(
            (s.per_second for c in ("hps", "heal") for s in self.stats.get(c, ())
                if s.per_second and s.condition != "self"),
            default=None)
        wait, lasts = self.max_stat("cooldown"), self.max_stat("duration")
        if rate and wait and lasts:     # up for `lasts` of every lasts + wait
            return rate * (lasts / (lasts + wait))
        return rate

    def run_casts(self) -> list[float]:
        """A heal that runs for a duration, as the cast it adds up to: 150 a
        second for 3 s is 450, "100 over 3 seconds" is 100."""
        runs = self.max_stat("duration") or 0.0
        return [
            s.value if s.den_value not in (None, 1.0) else s.per_second * runs
            for c in ("hps", "heal") for s in self.stats.get(c, ())
            if s.value is not None and s.per_second]

    # --- hits --------------------------------------------------------------

    def hits(self) -> list[float]:
        """The single hits this piece publishes, a headshot where one counts:
        its flat damage rows that are one hit each. An area row lands on the
        body."""
        tick = max(
            (s.per_second for s in self.stats.get("damage", ()) if s.per_second), default=0.0)
        lasts = self.max_stat("duration") or 0.0
        crit = self.max_stat("headshot_mod") or 1.0
        crits = (self.max_stat("headshot") or 0) >= 1 and (self.max_stat("pellets") or 1) < 2
        singles = [s.value for s in self.flat("damage") if not s.condition]
        return [
            s.value * (crit if crits and not SPLASH_RE.search(s.condition or "") else 1.0)
            for s in self.flat("damage") if _one_hit(s, tick, lasts, singles)]

    def cast_hit(self) -> float | None:
        """A cast that throws several pieces and publishes only the one piece
        (Sticky Bombs: "25, explosion, enemy", six of them): the pieces together.
        None for any other piece, and for one that hits only the hero itself."""
        rows = self.flat("damage")
        pieces = self.max_stat("pellets") or 1
        # every row a piece's own: under a condition, and not a sum
        apiece = all(
            s.condition and not SUMMED_RE.search("%s %s" % (s.condition, s.text or ""))
            for s in rows)
        hits = [s.value for s in rows if "self" not in (s.condition or "")]
        if self.kind != KIND_ABILITY or pieces < 2 or not hits or not apiece:
            return None
        return pieces * max(hits)

    def ult_hit(self) -> float:
        """One cast's damage: a flat figure times the cast's published charges, a
        total published over a window ("90 over 0.3 seconds"), a per-second rate
        over its duration, a shot fired at its rate for the duration (no more
        shots than the ammo), or a shot on its own cooldown, fired once and
        again each time it returns."""
        rows = [s for c in ("damage", "dps") for s in self.stats.get(c, ()) if s.per_second]
        over = [s.value for s in rows if s.value and s.den_value not in (None, 1.0)]
        rate = max(
            (s.per_second for s in rows if s.per_second and s.den_value in (None, 1.0)),
            default=0.0)
        charges = self.plain_stat("charges") or 1
        whole = [] if self.stats.get("dps") else [s.value * charges for s in self.flat("damage")]
        lasts = self.plain_stat("duration") or 0.0
        fired = 0.0
        if lasts and not rows:
            shots = [s.per_second for s in self.stats.get("fire_rate", ()) if s.per_second]
            fired = self._fired_at_rate(shots, lasts) if shots else self._fired_on_cooldown(lasts)
        return max([*whole, *over, rate * lasts, fired, 0.0])

    def _fired_at_rate(self, shots: list[float], lasts: float) -> float:
        """The largest hit fired at the fastest rate for `lasts` seconds, no more
        shots than the ammo. A hit on the hero itself is not the ultimate's."""
        hits = [s.value for s in self.flat("damage") if "self" not in (s.condition or "")]
        if not hits:
            return 0.0
        return max(hits) * min(max(shots) * lasts, self.max_stat("ammo") or math.inf)

    def _fired_on_cooldown(self, lasts: float) -> float:
        """A shot on its own cooldown for `lasts` seconds, fired once and again
        each time it returns: "cooldown 2.5 s (heavy round)" beside "175 (heavy
        round direct hit)"."""
        timed = [
            (s.value, w.value) for w in self.stats.get("cooldown", ()) if w.value and w.condition
            for s in self.flat("damage")
            if w.condition in (s.condition or "") and "self" not in (s.condition or "")]
        return max((hit * (1 + math.floor(lasts / wait)) for hit, wait in timed), default=0.0)


def dual_rate(guns: Iterable[Kit]) -> float | None:
    """Two guns fired together from one magazine, hp/s with the reload in; None
    unless exactly two publish a 'simultaneous fire' row and the same magazine."""
    pair = [w for w in guns if any(
        "simultaneous fire" in (s.condition or "")
        for c in ("damage_falloff_range", "spread") for s in w.stats.get(c, ()))]
    firing = [f for f in (w.plain_stat("dps") for w in pair) if f]
    shots = [r for r in (w.max_stat("fire_rate") for w in pair) if r]
    magazines = {w.max_stat("ammo") for w in pair}
    magazine = magazines.pop() if len(magazines) == 1 else None
    reloads = [
        s.value for w in pair for s in w.stats.get("reload_time", ())
        if s.value and not s.condition]
    if len(pair) != 2 or len(firing) != 2 or len(shots) != 2 or not (reloads and magazine):
        return None
    lasts = magazine / sum(shots)
    return sum(firing) * lasts / (lasts + max(reloads))
