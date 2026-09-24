"""A hero's derived numbers: what its kit rows add up to, set on the hero once
per load so the metrics read fields, not rows.

    scalars.derive_scalars(hero)

derive_scalars sorts the kit into its sets and runs one step per section,
in order, each setting its own fields on the hero. The keyword families and
the authored name lists below decide what a kit piece counts toward.
"""

import statistics

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from facts.kit import Kit, dual_rate
from facts.model import Hero

# Keyword families the wiki tags abilities with, read verbatim from the
# keywords column; the wiki's prose is read only in facts.kit, and the name
# lists below (PILOT_GUNS to SAVE_TOOLS) are authored. The wiki writes a
# keyword as `family;;qualifier` ("area of effect;;spherical", "invulnerable;;
# targets"): a Kit keeps the family in `keywords` and the whole atom in `atoms`.
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


def _body(hero: Hero, base: list[Kit]) -> None:
    """pool, keywords and form_armor; cooldowns and median_cooldown."""
    hero.pool = hero.health + hero.shield + hero.armor
    hero.keywords = set[str]().union(*(k.keywords for k in base))
    # armor an ability's form wears (Nemesis Form), by the form's uptime. Kept
    # apart from the base row: `armor` and `pool` stay what the hero spawns with
    hero.form_armor = 0.0
    for kit in base:
        wait, lasts = kit.max_stat("cooldown"), kit.max_stat("duration")
        share = lasts / (lasts + wait) if wait and lasts else 1.0
        if kit.kind == KIND_ABILITY:
            hero.form_armor += sum(
                s.value * share for s in kit.flat("armor") if s.condition != "allies")
    cds = [
        s.value for k in hero.abilities if k.kind != KIND_ULTIMATE
        for s in k.stats.get("cooldown", ()) if s.value is not None]
    hero.cooldowns = sorted(cds)
    hero.median_cooldown = statistics.median(cds) if cds else None


def _dps(hero: Hero, steady: list[Kit], guns: list[Kit]) -> None:
    """dps: the weapon the hero fights with, sustained."""
    held = [w for w in steady if w.extra.get("slot") in PRIMARY_SLOTS and w.damages]
    rates = [r for r in (w.rate("dps", "damage") for w in (held or steady)) if r]
    # both chainguns at once. The kit puts simultaneous-fire falloff at 10-20 m:
    # the dual rate and the single gun's 40 m reach are different fire modes
    hero.dps = max([*rates, dual_rate(guns) or 0.0])


def _burst(hero: Hero, base: list[Kit]) -> None:
    """burst: the biggest single hit, a headshot where one counts; a cast that
    throws several pieces is the pieces together."""
    hits = [hit for kit in base if kit.name not in PILOT_GUNS for hit in kit.hits()]
    hits += [cast for cast in (kit.cast_hit() for kit in base) if cast]
    hero.burst = max(hits, default=0.0)


def _healing(hero: Hero, fought: list[Kit], dps: float) -> None:
    """hps and peak_heal, per second and per cast onto teammates; self_hps and
    self_heal, the hero's own. A rate (hp/s) and a cast (hp) are two
    quantities, and what lands on a teammate is the team's."""
    team_rate: list[float] = []
    team_cast: list[float] = []
    own_rate: list[float] = []
    own_cast: list[float] = []
    for kit in fought:
        mine = not (hero.role == "support" or kit.for_allies or "deployable" in kit.keywords)
        rate = kit.heal_rate()
        casts = [s.value for s in kit.flat("heal") if s.condition != "self"]
        if rate:
            (own_rate if mine else team_rate).append(rate)
        if casts:
            (own_cast if mine else team_cast).append(max(casts))
        own_cast.extend(s.value for s in kit.flat("heal") if s.condition == "self")
        if mine and kit.kind != KIND_WEAPON:
            own_cast.extend(kit.run_casts())
        share = _share_cast(kit, mine, dps)
        if share is not None:
            own_cast.append(share)
    hero.hps = max(team_rate, default=0.0)
    hero.peak_heal = max(team_cast, default=0.0)
    hero.self_hps = max(own_rate, default=0.0)
    hero.self_heal = max(own_cast, default=0.0)


def _share_cast(kit: Kit, mine: bool, dps: float) -> float | None:
    """A share of the damage dealt, for a duration on a cooldown, is the held
    weapon's rate over it. An ability that deals its own damage heals off
    that, which publishes no rate: unknown is not a number."""
    runs = kit.max_stat("duration") or 0.0
    shares = [
        s.value / 100.0 for s in kit.stats.get("heal", ())
        if s.value is not None and s.unit_num == "percent"
        and (s.condition == "self" or (mine and not s.condition))]
    if shares and runs and kit.max_stat("cooldown") and not kit.damages:
        return max(shares) * dps * runs
    return None


def _reach(hero: Hero, guns: list[Kit]) -> None:
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


def _weapon_kinds(hero: Hero, base: list[Kit], guns: list[Kit]) -> None:
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


def _area(hero: Hero, fights: list[Kit]) -> None:
    """aoe_count and aoe_damage: the pieces that hit an area, and those of them
    that deal damage. A weapon is in the abilities table too (kind 'weapon',
    no config extra): each weapon counts once, whatever its configs."""
    area: dict[str, bool] = {}                  # piece -> does it damage
    for k in fights:
        # tagged, or a damaging piece typed Area of effect with no tag (Trailblazer)
        wide = k.keywords & set(AREA_KEYWORDS) or (k.damages and k.typed("area of effect"))
        if wide and not (k.kind == KIND_WEAPON and not k.extra and hero.weapons):
            piece = k.extra.get("weapon", k.name)
            area[piece] = area.get(piece, False) or k.damages
    hero.aoe_count = len(area)
    hero.aoe_damage = sum(area.values())


def _barriers(hero: Hero, base: list[Kit], fought: list[Kit]) -> None:
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


def _amps(hero: Hero, fights: list[Kit], fought: list[Kit]) -> None:
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


def _control(hero: Hero, base: list[Kit], fights: list[Kit]) -> None:
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


def _saves(hero: Hero, base: list[Kit], ults: list[Kit]) -> None:
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


def _ult(hero: Hero, ults: list[Kit]) -> None:
    """ult, ult_damage_raw, ult_cost and dmg_ult. The load caps ult_damage_raw
    into ult_damage once the roster's cap is known: Hero.cap_ult."""
    hero.ult = ults[0] if ults else None
    hero.ult_damage_raw = max((u.ult_hit() for u in ults), default=0.0)
    strongest = max(ults, key=Kit.ult_hit) if ults else None
    costs = [c for c in (u.max_stat("ult_req") for u in ults) if c]
    strongest_cost = strongest.max_stat("ult_req") if strongest else None
    hero.ult_cost = strongest_cost or max(costs, default=None)
    # a damage ultimate by its rows: EMP's percent of current health counts,
    # and adds no hit points to ult_damage
    hero.dmg_ult = any(
        s.value for u in ults for c in ("damage", "dps") for s in u.stats.get(c, ()))
