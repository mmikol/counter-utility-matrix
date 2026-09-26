"""A hero's derived numbers: what its kit rows add up to, set on the hero once
per load so the metrics read fields, not rows.

    scalars.derive_scalars(hero)

derive_scalars sorts the kit into its sets and runs one step per section,
in order, each setting its own fields on the hero. The keyword families and
the authored name lists below decide what a kit piece counts toward.
Sustained healing, hero.hps, has its own section: a formation model, the
reach and resource rules, and the judgements each constant names.
ally_lifesteal adds a heal that rides the teammates' damage once the load
knows the roster's dps.
"""

import math
import re
import statistics
from typing import NamedTuple

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from facts.draft import TEAM_SIZE
from facts.kit import KitPiece, dual_rate, on_self
from facts.model import Hero

# Keyword families the wiki tags abilities with, read verbatim from the
# keywords column; the wiki's prose is read only in facts.kit, and the name
# lists below (PILOT_GUNS to SAVE_TOOLS) are authored. The wiki writes a
# keyword as `family;;qualifier` ("area of effect;;spherical", "invulnerable;;
# targets"): a KitPiece keeps the family in `keywords` and the whole atom in
# `atoms`.
CC_KEYWORDS = ("stun", "sleep", "immobilize", "hinder", "knockback", "knockdown", "hacked")
MOBILITY_KEYWORDS = (
    "movement", "strong movement", "active movement", "evasive", "flight", "strong flight")
FLIGHT_KEYWORDS = ("flight", "strong flight")
CLEANSE_KEYWORDS = ("lesser cleanse", "greater cleanse", "perfect cleanse")
AREA_KEYWORDS = ("area of effect", "shockwave")     # a ground or cone wave is tagged shockwave
PRIMARY_SLOTS = ("primary_fire", "hip_fire", "default")
# the pilot's gun, held once the mech is lost: no hit of the hero's either
PILOT_GUNS = ("Light Gun", "Portable Fusion Repeater")
# swapped to off the fight: the Forge Hammer's heal and swing are the turret's
OFF_FIGHT = ("Forge Hammer",)
# weapon forms held for seconds on a cooldown, out of the hero's fighting form,
# or a charged side shot: not the weapon the hero fights with (authored; the
# wiki has no field)
FORM_GATED = ("Configuration: Assault", "Pummel", "Tesla Cannon Alt Fire", *PILOT_GUNS, *OFF_FIGHT)
# tools that stop a death without the wiki's `invulnerable` keyword
SAVE_TOOLS = ("Immortality Field",)

# --- sustained healing ------------------------------------------------------
# hero.hps is hp/s landed on teammates, summed over every teammate a piece
# reaches and over every piece that runs beside the others; the caster's own
# healing is out (docs/inference.md, Sustained healing). The six stand spread
# uniformly over a disk of radius FORMATION_RADIUS: a piece centred on the
# caster reaches TEAMMATES x p(r) of them, a piece that lands on an aimed
# teammate 1 + (TEAMMATES - 1) x p(r), p(r) the chance two points of the disk
# lie within r (p_within).
#
# 15 m is a judgement. Its anchor is the shortest single-target heal range
# among the supports: Caduceus Staff, Biotic Grasp and Healing Pylon (the
# Mercy, Moira and Illari pages). The wiki gives no fight size
# (Team_Composition, Control, Escort, Hybrid, Push, Flashpoint and Maps
# checked). Two teammates stand 0.905 R = 13.6 m apart on average, inside it.
FORMATION_RADIUS = 15.0
TEAMMATES = TEAM_SIZE - 1
# Illari page: Healing Pylon's cooldown is 7 s, 14 s once destroyed. It lives
# one cooldown and is then destroyed, a judgement: the wiki gives no lifetime.
PYLON_UPTIME = 7.0 / (7.0 + 14.0)
UPTIME = {"Healing Pylon": PYLON_UPTIME}
# Juno page: Pulsar Torpedoes lock onto any number of allies within 40 m.
# Half of the teammates past the aimed one stand in front of her and lock, a
# judgement. The lock takes 0.35 s at LOCK_NEAR, rising to 1 s at the
# targeting range, and holds the Mediblaster; a teammate FORMATION_RADIUS away
# sets it.
TORPEDO_VIEW = 0.5
LOCK_NEAR = 5.0
# Moira page: the spray heals "all allies in front", its width unpublished; it
# reaches one teammate.
SPRAY_TARGETS = 1.0
SPRAYS = ("Biotic Grasp",)
# Brigitte page: the Rocket Flail is in contact throughout, as hero.dps holds
# every weapon on its target. A Flail trigger locks Inspire out for 1.25 s, so
# it fires on every third swing of 0.6 s: once each 1.8 s.
FLAIL_CONTACT = 1.0
INSPIRE_LOCKOUT = 1.25
TRIGGERED = {"Inspire": ("Rocket Flail", INSPIRE_LOCKOUT)}
# Illari page: an emptied bar waits 0.4 s more before it recharges.
EMPTY_WAIT = {"Solar Rifle Alt Fire": 0.4}
# Wuyang page: the stream's tooltips tick 4.8 and 9.6 per 0.192 s, 25 and 50
# hp/s, where its heal rows read 20 and 55; the page's 75 total agrees with the
# ticks. The tick sets the rate. The passive tick draws no resource.
TICK_RATES = {"Restorative Stream": {"passive": 25.0, "bonus manual healing": 50.0}}
FREE_TICK = "passive"
# Wuyang page, Guardian Wave: "Replenishes 33% Restorative Stream resource upon
# successful cast". The refund is more stream time, once a wave.
ENERGY_REFUND = {"Guardian Wave": ("Restorative Stream", 33.0)}
# Jetpack Cat page: primary fire ends Lifeline, so it never runs beside the gun.
NOT_BESIDE = ("Lifeline",)
# Lifeweaver page: Rejuvenating Dash heals Lifeweaver ("heal yourself"); its row
# names no target.
OWN_HEALS = ("Rejuvenating Dash",)
# Lucio page: Amp It Up raises Crossfade's heal for its duration; it adds the
# difference.
BOOSTS = {"Amp It Up": "Crossfade"}
# Held or deployed for their duration, where the page says the cooldown starts
# after it or says nothing: one cycle is the cooldown plus the duration. Every
# other cast is instant or starts its cooldown on use, and cycles on the
# cooldown alone.
HELD = ("Amp It Up", "Cardiac Overdrive", "Purr", "Biotic Field", "Biotic Orb")
# Area heals centred on the caster, or where it stands: they reach
# TEAMMATES x p(radius).
CASTER = (
    "Crossfade", "Amp It Up", "Remedy Aura", "Regenerative Burst", "Inspire", "Purr",
    "Biotic Field", "Cardiac Overdrive")
# Area heals that land on an aimed teammate: 1 + (TEAMMATES - 1) x p(radius).
AIMED = ("Biotic Grenade", "Protection Suzu", "Biotic Launcher Alt Fire")
# a heal row that lingers after the cast: summed with the instant one
LINGERING_RE = re.compile(r"over time|\bhot\b", re.I)
# a bounce's order in its row's condition: "2nd bounce"
BOUNCE_RE = re.compile(r"(\d+)\w*\s+bounce", re.I)
# the total a per-second heal stops at: "75 per second , up to 300"
CAP_RE = re.compile(r"up to\s*(\d+(?:\.\d+)?)", re.I)


def derive_scalars(hero: Hero) -> None:
    """The hero's numbers, from the kit rows. Three kit sets:

        base    weapons, abilities and passives - what the hero brings every fight
        ults    the ultimates - their numbers are their own (ult_*), and they
                count toward the tools a team plans its big fights around
                (crowd control, area damage, saves, overhealth, anti-heal)
        perks   one of two choices a tier: never a baseline number

    The steps run in order: the body, dps, burst, healing (the one step
    that reads an earlier one's result, dps), reach, weapon kinds, area,
    barriers, amps, control, saves and the ultimate."""
    ults = hero.ults
    base = hero.weapons + [a for a in hero.abilities if a.kind != KIND_ULTIMATE]
    fights = base + ults
    fought = [k for k in base if k.name not in OFF_FIGHT]
    steady = [w for w in hero.weapons if w.name not in FORM_GATED]
    guns = [w for w in steady if w.damages]
    _body(hero, base)
    _dps(hero, steady, guns)
    _burst(hero, base)
    _healing(hero, fought, hero.dps)
    _reach(hero, guns)
    _weapon_kinds(hero, base, guns)
    _area(hero, fights)
    _barriers(hero, base, fought)
    _amps(hero, fights, fought)
    _control(hero, base, fights)
    _saves(hero, base, ults)
    _ult(hero, ults)


def _body(hero: Hero, base: list[KitPiece]) -> None:
    """pool, keywords and form_armor; cooldowns and median_cooldown."""
    hero.pool = hero.health + hero.shield + hero.armor
    hero.keywords = set[str]().union(*(k.keywords for k in base))
    # armor an ability's form wears (Nemesis Form), by the form's uptime. Kept
    # apart from the base row: `armor` and `pool` stay what the hero spawns with
    hero.form_armor = 0.0
    for piece in base:
        wait, lasts = piece.max_stat("cooldown"), piece.max_stat("duration")
        share = lasts / (lasts + wait) if wait and lasts else 1.0
        if piece.kind == KIND_ABILITY:
            hero.form_armor += sum(
                s.value * share for s in piece.flat("armor") if s.condition != "allies")
    cds = [
        s.value for k in hero.abilities if k.kind != KIND_ULTIMATE
        for s in k.stats.get("cooldown", ()) if s.value is not None]
    hero.cooldowns = sorted(cds)
    hero.median_cooldown = statistics.median(cds) if cds else None


def _dps(hero: Hero, steady: list[KitPiece], guns: list[KitPiece]) -> None:
    """dps: the weapon the hero fights with, sustained."""
    held = [w for w in steady if w.extra.get("slot") in PRIMARY_SLOTS and w.damages]
    rates = [r for r in (w.rate("dps", "damage") for w in (held or steady)) if r]
    # both chainguns at once. The kit puts simultaneous-fire falloff at 10-20 m:
    # the dual rate and the single gun's 40 m reach are different fire modes
    hero.dps = max([*rates, dual_rate(guns) or 0.0])


def _burst(hero: Hero, base: list[KitPiece]) -> None:
    """burst: the biggest single hit, a headshot where one counts; a cast that
    throws several pieces is the pieces together."""
    hits = [hit for piece in base if piece.name not in PILOT_GUNS for hit in piece.hits()]
    hits += [cast for cast in (piece.cast_hit() for piece in base) if cast]
    hero.burst = max(hits, default=0.0)


def _healing(hero: Hero, fought: list[KitPiece], dps: float) -> None:
    """hps and hps_pieces, sustained healing onto teammates (_team_pieces);
    peak_heal, the largest cast onto one; self_hps and self_heal, the hero's
    own. A rate (hp/s) and a cast (hp) are two quantities, and what lands on
    a teammate is the team's."""
    team_cast: list[float] = []
    own_rate: list[float] = []
    own_cast: list[float] = []
    for piece in fought:
        mine = not _lands_on_team(hero, piece)
        rate = piece.heal_rate()
        casts = [s.value for s in piece.flat("heal") if not on_self(s.condition)]
        if rate and mine:
            own_rate.append(rate)
        if casts:
            (own_cast if mine else team_cast).append(max(casts))
        own_cast.extend(s.value for s in piece.flat("heal") if on_self(s.condition))
        if mine and piece.kind != KIND_WEAPON:
            own_cast.extend(piece.run_casts())
        share = _share_cast(piece, mine, dps)
        if share is not None:
            own_cast.append(share)
    hero.hps_pieces = _team_pieces(hero, fought)
    hero.hps = sum(hero.hps_pieces.values())
    hero.peak_heal = max(team_cast, default=0.0)
    hero.self_hps = max(own_rate, default=0.0)
    hero.self_heal = max(own_cast, default=0.0)


def _share_cast(piece: KitPiece, mine: bool, dps: float) -> float | None:
    """A share of the damage dealt, for a duration on a cooldown, is the held
    weapon's rate over it. An ability that deals its own damage heals off
    that, which publishes no rate: unknown is not a number."""
    runs = piece.max_stat("duration") or 0.0
    shares = [
        s.value / 100.0 for s in piece.stats.get("heal", ())
        if s.value is not None and s.unit_num == "percent"
        and (on_self(s.condition) or (mine and not s.condition))]
    if shares and runs and piece.max_stat("cooldown") and not piece.damages:
        return max(shares) * dps * runs
    return None


# --- sustained healing ------------------------------------------------------


class Energy(NamedTuple):
    """A resource beam's energy rows: the cost and the regeneration in percent
    a second, the wait before it regenerates in seconds."""
    cost: float
    regen: float
    delay: float


def p_within(r: float, big: float = FORMATION_RADIUS) -> float:
    """The chance two points spread uniformly over a disk of radius `big` lie
    within `r` of each other: the disk's distance distribution, closed form."""
    s = r / big
    if s <= 0:
        return 0.0
    if s >= 2:
        return 1.0
    return (
        1 + 2 / math.pi * (s * s - 1) * math.acos(s / 2)
        - s / (2 * math.pi) * (1 + s * s / 2) * math.sqrt(4 - s * s))


def around_caster(r: float) -> float:
    """Teammates a heal of radius `r` centred on its caster reaches."""
    return min(TEAMMATES, TEAMMATES * p_within(r))


def on_teammate(r: float) -> float:
    """Teammates a heal of radius `r` reaches when it lands on an aimed one:
    that one, and the others within `r` of it."""
    return min(TEAMMATES, 1 + (TEAMMATES - 1) * p_within(r))


def energy_duty(
        cost: float, regen: float, delay: float, rate: float, hot: float = 0.0,
        hot_s: float = 0.0, empty: float = 0.0) -> float:
    """A resource beam's sustained hp/s: fire until x% is spent, wait out the
    delay, regenerate the x% and fire again, at the x (1 to 100) that heals
    most. A heal over time of `hot` hp/s lingers `hot_s` s once the beam
    stops; spending all 100% adds the `empty` wait."""
    best = 0.0
    for spent in range(1, 101):
        on = spent / cost
        off = delay + spent / regen + (empty if spent == 100 else 0.0)
        best = max(best, (rate * on + hot * min(hot_s, off)) / (on + off))
    return best


def _lands_on_team(hero: Hero, piece: KitPiece) -> bool:
    """A support's piece heals the team, and so does a piece tagged for allies
    or deployed; any other heals its hero."""
    return hero.role == "support" or piece.for_allies or "deployable" in piece.keywords


def _team_pieces(hero: Hero, fought: list[KitPiece]) -> dict[str, float]:
    """hp/s onto teammates per counted piece: the best healing weapon, and
    every ability and passive that runs beside it. A lock-on channel holds the
    weapon for its share of the cycle; a refund of a beam's energy adds to the
    beam."""
    team = [
        k for k in fought
        if _lands_on_team(hero, k) and k.name not in NOT_BESIDE + OWN_HEALS]
    guns = [(k.name, _weapon_heal(k)) for k in team if k.kind == KIND_WEAPON]
    gun, rate = max(guns, key=lambda g: g[1], default=("", 0.0))
    pieces: dict[str, float] = {}
    held = 0.0
    for piece in team:
        if piece.kind == KIND_WEAPON:
            continue
        locked = _lock_on(piece)
        if locked:
            value, share = locked
            held += share
        else:
            value = _cast_heal(piece, fought)
        if value:
            pieces[piece.name] = value
    for piece in team:
        target, refund = ENERGY_REFUND.get(piece.name, ("", 0.0))
        if target in pieces:
            pieces[target] += _refund(piece, refund, fought, target)
    if rate:
        pieces = {gun: rate * (1 - held), **pieces}
    return pieces


def _beam_rows(piece: KitPiece) -> tuple[float, float, float]:
    """A beam's per-second heal onto its target, the heal over time it leaves
    and how long that lingers: (rate, hot, hot_s). The heal row sets the rate
    before the hps field, as the tick does (Mercy: 55, where the field says
    60)."""
    rates = [
        (s.condition or "", s.per_second) for s in piece.stats.get("heal", ())
        if s.per_second and s.den_value in (None, 1.0) and not on_self(s.condition)]
    rate = next((v for c, v in rates if not LINGERING_RE.search(c)), 0.0)
    hot = next((v for c, v in rates if LINGERING_RE.search(c)), 0.0)
    hot_s = max((
        s.value for s in piece.stats.get("duration", ())
        if s.value is not None and LINGERING_RE.search(s.condition or "")), default=0.0)
    return rate, hot, hot_s


def _energy(piece: KitPiece) -> Energy | None:
    """The piece's energy rows, or None when it spends none. Of several regen
    rates the fastest: Moira's secondary fire refills it."""
    rates = [
        ((s.condition or "").lower(), s.per_second) for s in piece.stats.get("energy", ())
        if s.per_second]
    cost = [v for c, v in rates if "cost" in c]
    regen = [v for c, v in rates if "regen" in c or "recharge" in c]
    delay = [
        s.value for s in piece.stats.get("duration", ())
        if s.value is not None and "delay" in (s.condition or "")
        and ("regen" in (s.condition or "") or "recharge" in (s.condition or ""))]
    if not (cost and regen):
        return None
    return Energy(max(cost), max(regen), max(delay, default=0.0))


def _weapon_heal(piece: KitPiece) -> float:
    """A weapon's sustained hp/s onto teammates: a resource beam at the duty
    its energy allows, a beam at its heal row, any other at its published
    rate with the reload in; a splash that lands on an aimed teammate adds
    the others it reaches."""
    energy = _energy(piece)
    if "beam" in piece.keywords:
        rate, hot, hot_s = _beam_rows(piece)
        if energy and rate:
            targets = SPRAY_TARGETS if piece.name in SPRAYS else 1.0
            return targets * energy_duty(
                energy.cost, energy.regen, energy.delay, rate, hot, hot_s,
                EMPTY_WAIT.get(piece.name, 0.0))
        if rate:
            return rate
    rate = piece.rate("hps", "heal") or 0.0
    direct = [f.value for f in piece.flat("heal") if "direct" in (f.condition or "")]
    splash = [f.value for f in piece.flat("heal") if "splash" in (f.condition or "")]
    radius = piece.plain_stat("radius")
    if direct and splash and radius and piece.name in AIMED:
        shot = max(direct) + max(splash)
        rate *= (max(direct) + max(splash) * on_teammate(radius)) / shot
    return rate


def _reach_count(piece: KitPiece) -> float:
    """Teammates the piece reaches: an area around its caster or on an aimed
    teammate by its radius, a wave by its angle, else one."""
    radius = piece.plain_stat("radius") or piece.plain_stat("range") or 0.0
    if piece.name in CASTER:
        return around_caster(radius)
    if piece.name in AIMED:
        return on_teammate(radius)
    angle = piece.max_stat("view_angle")
    if "shockwave" in piece.keywords and angle:
        return min(TEAMMATES, 1 + (TEAMMATES - 1) * angle / 360)
    return 1.0


def _cycle(piece: KitPiece) -> float:
    """Seconds from one cast to the next: the cooldown, and the duration too
    where the effect is held (HELD). 0 when there is no cooldown."""
    wait = piece.max_stat("cooldown") or 0.0
    if wait and piece.name in HELD:
        return wait + (piece.max_stat("duration") or 0.0)
    return wait


def _per_second(piece: KitPiece) -> float:
    """The piece's per-second heal onto a teammate, 0 when it has none."""
    return max((
        s.per_second for s in piece.stats.get("heal", ())
        if s.per_second and s.den_value in (None, 1.0) and not on_self(s.condition)),
        default=0.0)


def _cast_total(piece: KitPiece) -> float:
    """One cast's heal onto one teammate: the instant heal and what lingers.
    Of instant figures under different conditions the smallest is the one
    every cast lands - 120 at low health and 100 under half are conditional;
    a heal per pulse counts every pulse of the duration."""
    flats = [f for f in piece.flat("heal") if not on_self(f.condition)]
    instant = [f.value for f in flats if not LINGERING_RE.search(f.condition or "")]
    lingering = [f.value for f in flats if LINGERING_RE.search(f.condition or "")]
    totals = [
        s.value for s in piece.stats.get("heal", ())
        if s.value is not None and s.den_value not in (None, 1.0) and s.unit_den == "seconds"
        and not on_self(s.condition)]
    cast = min(instant, default=0.0) + sum(lingering) + sum(totals)
    pulses = [
        s.value for s in piece.stats.get("duration", ())
        if s.value and "pulse" in (s.condition or "")]
    if pulses and any("pulse" in (f.condition or "") for f in flats):
        cast *= math.floor((piece.max_stat("duration") or 0.0) / min(pulses))
    return cast


def _cast_heal(piece: KitPiece, fought: list[KitPiece]) -> float:
    """An ability's or a passive's sustained hp/s onto teammates."""
    if piece.name in TICK_RATES:
        return _stream(piece)
    if piece.name in UPTIME:
        return _shots(piece) * UPTIME[piece.name]
    if piece.name in TRIGGERED:
        return _triggered(piece, fought)
    if any(BOUNCE_RE.search(f.condition or "") for f in piece.flat("heal")):
        return _bounces(piece)
    cycle = _cycle(piece)
    rate = _per_second(piece)
    if rate:
        boosted = BOOSTS.get(piece.name)
        rate -= max((_per_second(k) for k in fought if k.name == boosted), default=0.0)
        if not cycle:
            return rate * _reach_count(piece)
        total = rate * (piece.max_stat("duration") or 0.0)
        return min(total, _cap(piece) or total) * _reach_count(piece) / cycle
    cast = _cast_total(piece)
    return cast * _reach_count(piece) / cycle if cast and cycle else 0.0


def _cap(piece: KitPiece) -> float | None:
    """The total a per-second heal stops at, where its row words one: "75 per
    second , up to 300"."""
    caps = [
        float(found.group(1)) for s in piece.stats.get("heal", ())
        for found in [CAP_RE.search(s.text or "")] if found]
    return max(caps, default=None)


def _stream(piece: KitPiece) -> float:
    """A stream's ticks (TICK_RATES): the free tick in full, the rest at the
    duty its energy allows."""
    ticks = TICK_RATES[piece.name]
    free = sum(v for c, v in ticks.items() if c == FREE_TICK)
    drawn = sum(v for c, v in ticks.items() if c != FREE_TICK)
    energy = _energy(piece)
    if not energy:
        return free + drawn
    return free + energy_duty(energy.cost, energy.regen, energy.delay, drawn)


def _refund(piece: KitPiece, refund: float, fought: list[KitPiece], target: str) -> float:
    """hp/s a cast of `piece` adds to `target` by refunding `refund`% of its
    energy: that much more of the drawn tick, once a cycle."""
    cycle = _cycle(piece)
    ticks = TICK_RATES.get(target, {})
    drawn = sum(v for c, v in ticks.items() if c != FREE_TICK)
    for beam in fought:
        energy = _energy(beam)
        if beam.name == target and energy and cycle:
            return drawn * refund / energy.cost / cycle
    return 0.0


def _shots(piece: KitPiece) -> float:
    """A deployable's heal a shot at its fire rate: 40 a shot, 1.25 a second."""
    shot = max((
        s.value for s in piece.stats.get("heal", ())
        if s.value is not None and s.unit_num != "percent" and not on_self(s.condition)),
        default=0.0)
    return shot * (piece.max_stat("fire_rate") or 0.0)


def _triggered(piece: KitPiece, fought: list[KitPiece]) -> float:
    """A heal a weapon's hits trigger (TRIGGERED), held while they land: the
    trigger comes on the first swing past each lockout. The instant heal
    counts once a trigger, the per-second one over what its duration covers
    of the gap."""
    weapon, lockout = TRIGGERED[piece.name]
    swings = [
        s.per_second for k in fought if k.name == weapon
        for s in k.stats.get("fire_rate", ()) if s.per_second]
    if not swings:
        return 0.0
    swing = 1 / max(swings)
    period = swing * math.ceil(lockout / swing)
    lasts = piece.max_stat("duration") or 0.0
    instant = min((f.value for f in piece.flat("heal") if not on_self(f.condition)), default=0.0)
    held = _per_second(piece) * min(lasts, period) / period
    return (held + instant / period) * FLAIL_CONTACT * _reach_count(piece)


def _bounces(piece: KitPiece) -> float:
    """A heal that bounces from teammate to teammate: the first lands on the
    aimed one, each next on a teammate not yet healed within the bounce range
    of the last, while one stands there."""
    chain = sorted(
        (int(found.group(1)), f.value) for f in piece.flat("heal")
        for found in [BOUNCE_RE.search(f.condition or "")] if found)
    hop = max((
        s.value for s in piece.stats.get("range", ())
        if s.value is not None and "bounce" in (s.condition or "")), default=0.0)
    near = p_within(hop)
    landed, total = 1.0, 0.0
    for order, (_, value) in enumerate(chain):
        if order:
            landed *= 1 - (1 - near) ** (TEAMMATES - order)
        total += value * landed
    cycle = _cycle(piece)
    return total / cycle if cycle else 0.0


def _lock_on(piece: KitPiece) -> tuple[float, float] | None:
    """A lock-on channel's hp/s and the share of its cycle it holds the weapon
    (Pulsar Torpedoes); None for any other piece. The lock time runs from its
    shortest at LOCK_NEAR to its longest at the targeting range, read at a
    teammate FORMATION_RADIUS away."""
    locks = [
        s.value for s in piece.stats.get("duration", ())
        if s.value is not None and "lock-on" in (s.condition or "")]
    span = piece.plain_stat("range") or 0.0
    wait = piece.max_stat("cooldown") or 0.0
    if not (locks and span > LOCK_NEAR and wait):
        return None
    along = min(1.0, max(0.0, (FORMATION_RADIUS - LOCK_NEAR) / (span - LOCK_NEAR)))
    lock = min(locks) + (max(locks) - min(locks)) * along
    cycle = wait + lock
    reach = min(TEAMMATES, 1 + (TEAMMATES - 1) * p_within(span) * TORPEDO_VIEW)
    return _cast_total(piece) * reach / cycle, lock / cycle


def ally_lifesteal(hero: Hero, ally_dps: float) -> None:
    """A heal of a share of the damage the teammates deal, for a duration on a
    cycle (Cardiac Overdrive), at `ally_dps` a teammate: added to hps and
    hps_pieces. The load calls it once the roster's dps is known."""
    for piece in hero.abilities:
        shares = [
            s.value / 100.0 for s in piece.stats.get("heal", ())
            if s.value is not None and s.unit_num == "percent" and s.condition == "allies"]
        lasts = piece.max_stat("duration") or 0.0
        cycle = _cycle(piece)
        if piece.kind == KIND_ULTIMATE or not (shares and lasts and cycle):
            continue
        hero.hps_pieces[piece.name] = (
            max(shares) * ally_dps * lasts / cycle * _reach_count(piece))
        hero.hps = sum(hero.hps_pieces.values())


def _reach(hero: Hero, guns: list[KitPiece]) -> None:
    """max_range and hitscan_range: the weapons' published limits. A weapon
    that publishes none says nothing, and the hero stays out of the range
    metrics: unknown is not a number. A held projectile that publishes no
    limit leaves only hitscan figures standing."""
    blind = any(
        w.extra.get("slot") in PRIMARY_SLOTS and not w.reach
        and not any(t in w.weapon_kind for t in ("hitscan", "beam", "melee"))
        for w in guns)
    known = [r for r in (w.reach for w in guns if not blind or "hitscan" in w.weapon_kind) if r]
    hero.max_range = max(known, default=0.0)
    hitscan = (w.reach for w in guns if "hitscan" in w.weapon_kind)
    hero.hitscan_range = max((r for r in hitscan if r), default=0.0)


def _weapon_kinds(hero: Hero, base: list[KitPiece], guns: list[KitPiece]) -> None:
    """weapon_kinds, hitscan, beam, melee and melee_only. A weapon that deals no
    damage says nothing here: a healing beam is not a beam."""
    hero.weapon_kinds = {
        "hitscan" if "hitscan" in t else "beam" if "beam" in t else "melee" if "melee" in t
        else "projectile"
        for t in (w.weapon_kind for w in guns) if t}
    tagged = set[str]().union(
        *(k.keywords for k in base if k.kind == KIND_WEAPON and k.damages))
    hero.hitscan = "hitscan" in hero.weapon_kinds or "hitscan" in tagged
    hero.beam = "beam" in hero.weapon_kinds or "beam" in tagged
    # a form's melee weapon (Pummel) still makes a melee hero
    hero.melee = any("melee" in w.weapon_kind for w in hero.weapons if w.name not in OFF_FIGHT)
    hero.melee_only = hero.melee and hero.weapon_kinds <= {"melee"}


def _area(hero: Hero, fights: list[KitPiece]) -> None:
    """aoe_count and aoe_damage_count: the pieces that hit an area, and those
    of them that deal damage. A weapon is in the abilities table too (kind
    'weapon', no config extra): each weapon counts once, whatever its
    configs."""
    area: dict[str, bool] = {}                  # piece -> does it damage
    for k in fights:
        # tagged, or a damaging piece typed Area of effect with no tag (Trailblazer)
        wide = k.keywords & set(AREA_KEYWORDS) or (k.damages and k.typed("area of effect"))
        if wide and not (k.kind == KIND_WEAPON and not k.extra and hero.weapons):
            piece = k.extra.get("weapon", k.name)
            area[piece] = area.get(piece, False) or k.damages
    hero.aoe_count = len(area)
    hero.aoe_damage_count = sum(area.values())


def _barriers(hero: Hero, base: list[KitPiece], fought: list[KitPiece]) -> None:
    """barrier_hp and pierces_barrier."""
    barriers = [k.plain_stat("barrier_health") for k in base]
    barriers += [
        k.plain_stat("health") for k in base
        if k.keywords & {"barrier", "bubble"} and not k.stats.get("barrier_health")]
    hero.barrier_hp = max((b for b in barriers if b), default=0.0)
    # a passive's quick melee (Snap Kick, Clobber) passes barriers like every
    # hero's melee and says nothing about the hero
    hero.pierces_barrier = any(
        k.damages and (
            "barrier piercing" in k.keywords
            or ((k.max_stat("ignores_barrier") or 0) >= 1 and not k.for_allies))
        for k in fought if k.kind != KIND_PASSIVE)


def _amps(hero: Hero, fights: list[KitPiece], fought: list[KitPiece]) -> None:
    """overhealth, antiheal, heal_amp, dmg_amp and lifesteal."""
    hero.overhealth = max(
        (s.overhealth for k in fights for s in k.stats.get("overhealth", ())
            if s.overhealth is not None),
        default=0.0)
    mods = [
        s.value for k in fights for s in k.stats.get("healing_mod", ()) if s.value is not None]
    hero.antiheal = min((m for m in mods if m < 0), default=0.0)
    hero.heal_amp = max((m for m in mods if m > 0), default=0.0)
    # a passive's damage_amp is the hero's own bonus (Opportunist), not the team's
    amps = [
        s.value for k in fights if k.kind != KIND_PASSIVE for s in k.stats.get("damage_amp", ())
        if s.value is not None and s.value > 0 and not s.condition]
    hero.dmg_amp = max(amps, default=0.0)
    # a percent heal is a share of the damage the hero deals, not hit points
    hero.lifesteal = max(
        (s.value / 100.0 for k in fought for s in k.stats.get("heal", ())
            if s.value is not None and s.unit_num == "percent" and s.condition != "allies"),
        default=0.0)


def _control(hero: Hero, base: list[KitPiece], fights: list[KitPiece]) -> None:
    """cc_tools, mobility_tools and flyer."""
    # crowd control: tagged as such, an ability that slows, or an ABILITY
    # that knocks an enemy back at MIN_KNOCKBACK or more - a weapon's knockback
    # stat is recoil, and a movement tool's is the hero's own flight
    hero.cc_tools = sorted({
        k.name for k in fights
        if k.keywords & set(CC_KEYWORDS)
        or (k.kind in (KIND_ABILITY, KIND_ULTIMATE) and k.damages and k.shoves
            and not k.keywords & set(MOBILITY_KEYWORDS))
        or (k.kind in (KIND_ABILITY, KIND_ULTIMATE)
            and any((s.value or 0) < 0 for s in k.stats.get("mspeed_slow", ())))})
    moves = [a for a in base if a.kind in (KIND_ABILITY, KIND_PASSIVE)]
    # tagged as movement, or typed Movement with no tag (Siphon Blaster, Roll)
    hero.mobility_tools = sorted({
        k.name for k in moves if k.keywords & set(MOBILITY_KEYWORDS) or k.typed("movement")})
    hero.flyer = any(k.keywords & set(FLIGHT_KEYWORDS) for k in moves)


def _saves(hero: Hero, base: list[KitPiece], ults: list[KitPiece]) -> None:
    """cleanse_tools, invuln_tools, team_cleanse_tools, save_tools and
    deployables."""
    # a save is a tool, not a passive: Eject! leaves the mech, it saves no one
    tools = [k for k in base if k.kind != KIND_PASSIVE] + [
        u for u in ults
        if u.for_allies or (hero.role == "support" and (u.stats.get("heal") or u.stats.get("hps")))]
    hero.cleanse_tools = sorted({k.name for k in tools if k.keywords & set(CLEANSE_KEYWORDS)})
    hero.invuln_tools = sorted({
        k.name for k in tools if "invulnerable" in k.keywords or k.name in SAVE_TOOLS})
    # what lands on a teammate: tagged for allies, an area that deals no damage
    # (Protection Suzu; Burrow's area is its exit hit), or an ultimate admitted above
    shared = [
        k for k in tools
        if k.for_allies or k in ults or ("area of effect" in k.keywords and not k.damages)]
    hero.team_cleanse_tools = sorted({
        k.name for k in shared if k.keywords & set(CLEANSE_KEYWORDS)})
    hero.save_tools = sorted({
        k.name for k in shared if k.name in hero.cleanse_tools + hero.invuln_tools})
    # a bubble worn by a hero is not placed
    hero.deployables = sorted({
        k.name for k in base if "deployable" in k.keywords and "attached" not in k.keywords})


def _ult(hero: Hero, ults: list[KitPiece]) -> None:
    """ult, ult_damage_raw, ult_cost and ult_deals_damage. The load caps
    ult_damage_raw into ult_damage once the roster's cap is known:
    Hero.cap_ult."""
    hero.ult = ults[0] if ults else None
    hero.ult_damage_raw = max((u.ult_hit() for u in ults), default=0.0)
    strongest = max(ults, key=KitPiece.ult_hit) if ults else None
    costs = [c for c in (u.max_stat("ult_req") for u in ults) if c]
    strongest_cost = strongest.max_stat("ult_req") if strongest else None
    hero.ult_cost = strongest_cost or max(costs, default=None)
    # a damage ultimate by its rows: EMP's percent of current health counts,
    # and adds no hit points to ult_damage
    hero.ult_deals_damage = any(
        s.value for u in ults for c in ("damage", "dps") for s in u.stats.get(c, ()))
