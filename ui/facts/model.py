"""The World: the whole database in memory, loaded fresh from Postgres on
every request so the UI layer always reads what the data layer stored.

Loading is a dozen queries and a few thousand rows; cheap enough to do per
click, and it is what lets the inference layer's solver evaluate thousands
of candidate compositions without a query each.
"""

import math
import re
import statistics
from collections import defaultdict

from db.data.names import name_key

ROLES = ("tank", "damage", "support")

# Keyword families the wiki tags abilities with. Read verbatim from the
# keywords column; nothing here is guessed from prose, except the authored
# name lists below (PILOT_GUNS to SAVE_TOOLS). The wiki writes a
# keyword as `family;;qualifier` ("area of effect;;spherical", "invulnerable;;
# targets"): a Kit keeps the family in `keywords` and the whole atom in `atoms`.
CC_KEYWORDS = ("stun", "sleep", "immobilize", "hinder", "knockback", "knockdown",
               "hacked")
MOBILITY_KEYWORDS = ("movement", "strong movement", "active movement", "evasive", "flight",
                     "strong flight")
FLIGHT_KEYWORDS = ("flight", "strong flight")
CLEANSE_KEYWORDS = ("lesser cleanse", "greater cleanse", "perfect cleanse")
AREA_KEYWORDS = ("area of effect", "shockwave")     # a ground or cone wave is tagged shockwave
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
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?")
PRIMARY_SLOTS = ("primary_fire", "hip_fire", "default")
# the pilot's gun, held once the mech is lost: no hit of the hero's either
PILOT_GUNS = ("Light Gun", "Portable Fusion Repeater")
# swapped to off the fight: the Forge Hammer's heal and swing are the turret's
OFF_FIGHT = ("Forge Hammer",)
# weapon forms held for seconds on a cooldown, out of the hero's fighting form,
# or a charged side shot: not the weapon the hero fights with (authored; the
# wiki has no field)
FORM_GATED = ("Configuration: Assault", "Pummel", "Tesla Cannon Alt Fire",
              *PILOT_GUNS, *OFF_FIGHT)
REMECH = ("Call Mech",)     # climbing back into the mech: an ultimate by kind, not a fight tool
# tools that stop a death without the wiki's `invulnerable` keyword
SAVE_TOOLS = ("Immortality Field",)
SQUISHY_POOL = 250


class Stat:
    __slots__ = (
        "code",
        "condition",
        "den_value",
        "text",
        "unit_den",
        "unit_num",
        "value",
    )

    def __init__(self, code, value, unit_num, unit_den, den_value, condition, text):
        self.code = code
        self.value = float(value) if value is not None else None
        self.unit_num, self.unit_den = unit_num, unit_den
        self.den_value = float(den_value) if den_value is not None else None
        self.condition, self.text = condition, text

    def rendered(self):
        if self.value is not None:
            out = "%g" % self.value
            if self.unit_num:
                out += " " + self.unit_num
            if self.unit_den:
                out += " per " + ("%g " % self.den_value
                                  if self.den_value not in (None, 1) else "") \
                       + self.unit_den
        else:
            out = self.text or "?"
        if self.condition:
            out += " (%s)" % self.condition
        return out

    @property
    def per_second(self):
        """The value as a per-second rate, or None if not one."""
        if self.value is None or self.unit_den != "seconds":
            return None
        return self.value / (self.den_value or 1.0)


class Kit:
    """An ability, a weapon config or a perk: a named thing with stats."""
    __slots__ = ("atoms", "description", "extra", "keywords", "kind", "name", "stats")

    def __init__(self, name, kind, description="", keywords=""):
        self.name, self.kind, self.description = name, kind, description
        self.atoms = {k.strip().lower() for k in (keywords or "").split("::") if k.strip()}
        self.keywords = {a.split(";;")[0].strip() for a in self.atoms}
        self.stats = defaultdict(list)
        self.extra = {}

    def qualifiers(self, family):
        """The qualifiers the wiki hangs on one keyword family here."""
        return {a.split(";;", 1)[1].strip() for a in self.atoms
                if ";;" in a and a.split(";;")[0].strip() == family}

    @property
    def for_allies(self):
        """Tagged as landing on a teammate."""
        return any(q in ALLY_QUALIFIERS for a in self.atoms if ";;" in a
                   for q in [a.split(";;", 1)[1].strip()])

    def plain_stat(self, code):
        """The largest value published without a condition; with none, the
        largest of all - "300 default, 750 during Rally" is 300."""
        rows = [s for s in self.stats.get(code, ()) if s.value is not None]
        plain = [s.value for s in rows if not s.condition or s.condition == "default"]
        return max(plain) if plain else (max(s.value for s in rows) if rows else None)

    def max_stat(self, code):
        values = [s.value for s in self.stats.get(code, ()) if s.value is not None]
        return max(values) if values else None

MIN_FALLOFF = 10.0      # a "falloff range" under this is a splash radius, not a reach
MIN_KNOCKBACK = 10.0    # m/s onto an enemy; under this a knockback is a nudge, not crowd control


def _number(text):
    """The first figure in a line of the wiki's prose; of a range, its top."""
    found = NUMBER_RE.search(text or "")
    return float(found.group(2) or found.group(1)) if found else None


def _rate(kit, code, per_shot):
    """One kit piece's sustained rate for `code` (dps or hps), hp/s: the
    published rate with its reload where the wiki gives one, else the firing
    rate over its magazine and reload where the kit publishes both, else the
    firing rate, else one `per_shot` times the fire rate. None when nothing says."""
    plain, variants, loaded = [], [], []
    worded = False
    for stat in kit.stats.get(code, ()):
        value = stat.value if stat.value is not None else _number(stat.text)
        if value is None:
            continue
        worded = worded or bool(RELOAD_RE.search(stat.text or ""))
        note = "%s %s" % (stat.condition or "", stat.text or "")
        if RELOAD_RE.search(stat.condition or ""):
            with_reload = _number(stat.condition)
        elif RELOAD_RE.search(note):
            found = TEXT_RELOAD_RE.search(stat.text or "")
            with_reload = float(found.group(1)) if found else value
        else:
            with_reload = None
        if stat.value is None and with_reload:
            loaded.append(with_reload)      # prose row: its first figure may be another fire mode
            continue
        if with_reload is not None and with_reload <= value:
            loaded.append(with_reload)
        elif stat.condition and not RELOAD_RE.search(stat.condition):
            variants.append(value)               # "variant 2", "at full charge"
        else:
            plain.append(value)
    if loaded:
        return min(loaded)
    rate = kit.max_stat("fire_rate")
    if plain:
        firing = max(plain)
    elif variants:
        firing = statistics.median_low(variants)
    else:
        # the hit the rate counts: "1.18 swings per second" is the swing, not the finisher
        counted = {(s.unit_num or "").rstrip("s") for s in kit.stats.get("fire_rate", ())} - {""}
        rows = [s for s in kit.stats.get(per_shot, ())
                if s.value is not None and s.unit_den is None]
        shots = [s.value for s in [s for s in rows if s.condition in counted] or rows]
        firing = max(shots) * rate if shots and rate else None
    if not firing or worded:
        return firing                        # the text words its own reload figure: left alone
    # no usable reload figure: the magazine's share of magazine + reload. A
    # reload worded "per shot" or "from empty" is ammo that regenerates
    ammo = kit.max_stat("ammo")
    reloads = [s.value for s in kit.stats.get("reload_time", ()) if s.value and not s.condition]
    if not (ammo and rate and reloads):
        return firing
    lasts = ammo / (kit.max_stat("ammo_drain") or 1.0) / rate
    return firing * lasts / (lasts + max(reloads))


def _dual_rate(guns):
    """Two guns fired together from one magazine, hp/s with the reload in; None
    unless exactly two publish a 'simultaneous fire' row and the same magazine."""
    pair = [w for w in guns
            if any("simultaneous fire" in (s.condition or "")
                   for c in ("damage_falloff_range", "spread") for s in w.stats.get(c, ()))]
    firing = [w.plain_stat("dps") for w in pair]
    shots = [w.max_stat("fire_rate") for w in pair]
    ammo = {w.max_stat("ammo") for w in pair}
    reloads = [s.value for w in pair for s in w.stats.get("reload_time", ())
               if s.value and not s.condition]
    if len(pair) != 2 or not (all(firing) and all(shots) and reloads) or len(ammo) != 1 \
            or not min(ammo):
        return None
    lasts = ammo.pop() / sum(shots)
    return sum(firing) * lasts / (lasts + max(reloads))


def _reach(kit):
    """How far a damaging kit piece fights, in metres: its published range, or
    the end of its damage falloff. None when it publishes neither."""
    falloff = kit.max_stat("damage_falloff_range") or 0.0
    published = [v for v in (kit.plain_stat("range"),
                             falloff if falloff >= MIN_FALLOFF else None) if v]
    return max(published) if published else None


class Hero:
    @property
    def released(self):
        return self.status == "released"

    def __init__(self, hid, name, role, subrole, health, shield, armor,
                 portrait, status="released", release_date=None):
        self.id, self.name = hid, name
        self.role, self.subrole = role, subrole
        self.status, self.release_date = status, release_date   # announced: shown, never picked
        self.health, self.shield, self.armor = health or 0, shield or 0, armor or 0
        self.portrait = portrait
        self.styles = set()
        self.abilities, self.weapons, self.perks = [], [], []
        self.modifiers = []
        self.win = self.pick = self.ban = None
        self.by_tier = {}
        self.prev_win = None
        self.map_rates = {}
        self.map_bans = {}           # map_id -> ban rate on that map, when published
        self.best_maps = []          # map ids, three at most: see best_maps()
        self.perk_effects = []       # (perk, the ability it alters)

    # --- derived scalars, computed once the kit and rates are loaded ------

    def finish(self):
        """The hero's numbers, from the kit rows. Three kit sets:
            base   weapons, abilities and passives - what the hero brings every fight
            ults   the ultimates - their numbers are their own (ult_*), and they
                   count toward the tools a team plans its big fights around
                   (crowd control, area damage, saves, overhealth, anti-heal)
            perks  one of two choices a tier: never a baseline number
        """
        ults = [a for a in self.abilities if a.kind == "ultimate" and a.name not in REMECH]
        base = self.weapons + [a for a in self.abilities if a.kind != "ultimate"]
        fights = base + ults
        fought = [k for k in base if k.name not in OFF_FIGHT]
        self.pool = self.health + self.shield + self.armor
        self.keywords = set().union(*(k.keywords for k in base)) if base else set()
        def flat(kit, code):
            """The rows in hit points: not a rate, not a percent."""
            return [s for s in kit.stats.get(code, ()) if s.value is not None
                    and s.unit_den is None and s.unit_num != "percent"]

        def damages(kit):
            return bool(kit.stats.get("damage") or kit.stats.get("dps"))

        def shoves(kit):
            return max([s.value for s in kit.stats.get("kbspeed", ())
                        if s.value is not None and "self" not in (s.condition or "")]
                       or [0.0]) >= MIN_KNOCKBACK

        def kind(weapon):
            return (weapon.extra.get("weapon_type") or "").lower()

        def typed(kit, text):
            """The wiki's Type field names it: one shot_type row a type."""
            return any((s.text or "").strip().lower() == text
                       for s in kit.stats.get("shot_type", ()))

        # armor an ability's form wears (Nemesis Form), by the form's uptime. Kept
        # apart from the base row: `armor` and `pool` stay what the hero spawns with
        self.form_armor = 0.0
        for kit in base:
            wait, lasts = kit.max_stat("cooldown"), kit.max_stat("duration")
            share = lasts / (lasts + wait) if wait and lasts else 1.0
            if kit.kind == "ability":
                self.form_armor += sum(s.value * share for s in flat(kit, "armor")
                                       if s.condition != "allies")

        # --- damage: the weapon the hero fights with, sustained ------------------
        steady = [w for w in self.weapons if w.name not in FORM_GATED]
        held = [w for w in steady if w.extra.get("slot") in PRIMARY_SLOTS and damages(w)]
        rates = [r for r in (_rate(w, "dps", "damage") for w in (held or steady)) if r]
        # both chainguns at once. The kit puts simultaneous-fire falloff at 10-20 m:
        # the dual rate and the single gun's 40 m reach are different fire modes
        dual = _dual_rate([w for w in steady if damages(w)])
        self.dps = max([*rates, dual or 0.0])

        # --- burst: the biggest single hit, a headshot where one counts ---------
        hits = []
        for kit in base:
            if kit.name in PILOT_GUNS:
                continue
            tick = max([s.per_second for s in kit.stats.get("damage", ()) if s.per_second]
                       or [0.0])
            lasts = kit.max_stat("duration") or 0.0
            crit = kit.max_stat("headshot_mod") or 1.0
            crits = (kit.max_stat("headshot") or 0) >= 1 and (kit.max_stat("pellets") or 1) < 2
            singles = [s.value for s in flat(kit, "damage") if not s.condition]
            for stat in flat(kit, "damage"):
                if SUMMED_RE.search("%s %s" % (stat.condition or "", stat.text or "")):
                    continue
                if tick and lasts and abs(stat.value - tick * lasts) < 0.5:
                    continue                      # the rate over its duration, not a hit
                if any(one and stat.value > one and stat.value % one == 0 for one in singles):
                    continue                      # five orbs at once: not one hit
                splash = SPLASH_RE.search(stat.condition or "")
                hits.append(stat.value * (crit if crits and not splash else 1.0))
        # a cast that throws several pieces and publishes only the one piece (Sticky
        # Bombs: "25, explosion, enemy", six of them): the cast is the pieces together
        for kit in base:
            rows = flat(kit, "damage")
            pieces = kit.max_stat("pellets") or 1
            if (kit.kind == "ability" and pieces >= 2 and rows
                    and all(s.condition and not SUMMED_RE.search(
                        "%s %s" % (s.condition, s.text or "")) for s in rows)):
                hits.append(pieces * max(s.value for s in rows if "self" not in s.condition))
        self.burst = max(hits) if hits else 0.0

        # --- healing: a rate (hp/s) and a cast (hp) are two quantities; what
        #     lands on teammates is the team's, the rest is the hero's own -------
        team_rate, team_cast, own_rate, own_cast = [], [], [], []
        for kit in fought:
            mine = not (self.role == "support" or kit.for_allies
                        or "deployable" in kit.keywords)
            rate = _rate(kit, "hps", "heal") if kit.kind == "weapon" else None
            if rate is None:
                per = [s for c in ("hps", "heal") for s in kit.stats.get(c, ())
                       if s.per_second and s.condition != "self"]
                rate = max(s.per_second for s in per) if per else None
                wait = kit.max_stat("cooldown")
                lasts = kit.max_stat("duration")
                if rate and wait and lasts:       # up for `lasts` of every lasts + wait
                    rate *= lasts / (lasts + wait)
            casts = [s.value for s in flat(kit, "heal") if s.condition != "self"]
            selfs = [s.value for s in flat(kit, "heal") if s.condition == "self"]
            if rate:
                (own_rate if mine else team_rate).append(rate)
            if casts:
                (own_cast if mine else team_cast).append(max(casts))
            own_cast.extend(selfs)
            # an own heal that runs for a duration is also a cast: 150 a second for
            # 3 s is 450, "100 over 3 seconds" is 100
            runs = kit.max_stat("duration") or 0.0
            if mine and kit.kind != "weapon":
                own_cast.extend(s.value if s.den_value not in (None, 1.0) else s.per_second * runs
                                for c in ("hps", "heal") for s in kit.stats.get(c, ())
                                if s.per_second)
            # a share of the damage dealt, for a duration on a cooldown, is the held
            # weapon's rate over it. An ability that deals its own damage heals off
            # that, which publishes no rate: unknown is not a number
            shares = [s.value / 100.0 for s in kit.stats.get("heal", ())
                      if s.value is not None and s.unit_num == "percent"
                      and (s.condition == "self" or (mine and not s.condition))]
            if shares and runs and kit.max_stat("cooldown") and not damages(kit):
                own_cast.append(max(shares) * self.dps * runs)
        self.hps = max(team_rate or [0.0])
        self.peak_heal = max(team_cast or [0.0])
        self.self_hps = max(own_rate or [0.0])
        self.self_heal = max(own_cast or [0.0])
        # a percent heal is a share of the damage the hero deals, not hit points
        self.lifesteal = max([s.value / 100.0 for k in fought for s in k.stats.get("heal", ())
                              if s.value is not None and s.unit_num == "percent"
                              and s.condition != "allies"] or [0.0])

        # --- reach: the weapons' published limits. A weapon that publishes none
        #     says nothing, and the hero stays out of the range metrics: unknown is
        #     not a number. A held projectile that publishes no limit leaves only
        #     hitscan figures standing ----------------------------------------------
        guns = [w for w in steady if damages(w)]
        blind = any(w.extra.get("slot") in PRIMARY_SLOTS and not _reach(w)
                    and not any(t in kind(w) for t in ("hitscan", "beam", "melee"))
                    for w in guns)
        known = [r for r in (_reach(w) for w in guns if not blind or "hitscan" in kind(w)) if r]
        self.max_range = max(known) if known else 0.0
        self.hitscan_range = max([r for r in (_reach(w) for w in guns if "hitscan" in kind(w))
                                  if r] or [0.0])

        cds = [s.value for k in self.abilities if k.kind != "ultimate"
               for s in k.stats.get("cooldown", ()) if s.value is not None]
        self.cooldowns = sorted(cds)
        self.median_cooldown = statistics.median(cds) if cds else None
        # a weapon that deals no damage says nothing here: a healing beam is not a beam
        self.weapon_kinds = set()
        for w in guns:
            t = kind(w)
            if t:
                self.weapon_kinds.add(
                    "hitscan" if "hitscan" in t else "beam" if "beam" in t
                    else "melee" if "melee" in t else "projectile")
        tagged = set().union(*(k.keywords for k in base if k.kind == "weapon" and damages(k))) \
            if base else set()
        self.hitscan = "hitscan" in self.weapon_kinds or "hitscan" in tagged
        self.beam = "beam" in self.weapon_kinds or "beam" in tagged
        # a form's melee weapon (Pummel) still makes a melee hero
        self.melee = any("melee" in kind(w) for w in self.weapons if w.name not in OFF_FIGHT)
        self.melee_only = self.melee and self.weapon_kinds <= {"melee"}
        # a weapon is in the abilities table too (kind 'weapon', no config extra):
        # each weapon once, whatever its configs
        area = {}                                 # piece -> does it damage
        for k in fights:
            # tagged, or a damaging piece typed Area of effect with no tag (Trailblazer)
            if (k.keywords & set(AREA_KEYWORDS) or (damages(k) and typed(k, "area of effect"))) \
                    and not (k.kind == "weapon" and not k.extra and self.weapons):
                piece = k.extra.get("weapon", k.name)
                area[piece] = area.get(piece, False) or damages(k)
        self.aoe_count = len(area)
        self.aoe_damage = sum(area.values())
        barriers = [k.plain_stat("barrier_health") for k in base]
        barriers += [k.plain_stat("health") for k in base
                     if k.keywords & {"barrier", "bubble"} and not k.stats.get("barrier_health")]
        self.barrier_hp = max([b for b in barriers if b] or [0.0])
        # a passive's quick melee (Snap Kick, Clobber) passes barriers like every
        # hero's melee and says nothing about the hero
        self.pierces_barrier = any(
            damages(k) and ("barrier piercing" in k.keywords
                            or ((k.max_stat("ignores_barrier") or 0) >= 1
                                and not k.for_allies))
            for k in fought if k.kind != "passive")

        def granted(s):
            """Overhealth in hp as published; a percent or a rate is worth its cap."""
            if s.unit_num == "hp" and s.unit_den is None:
                return s.value
            found = OVERHEALTH_CAP_RE.search("%s %s" % (s.text or "", s.condition or ""))
            return float(found.group(1) or found.group(2)) if found else None

        self.overhealth = max([v for k in fights for s in k.stats.get("overhealth", ())
                               for v in [granted(s)] if v is not None] or [0.0])
        mods = [s.value for k in fights for s in k.stats.get("healing_mod", ())
                if s.value is not None]
        self.antiheal = min([m for m in mods if m < 0] or [0.0])
        self.heal_amp = max([m for m in mods if m > 0] or [0.0])
        # a passive's damage_amp is the hero's own bonus (Opportunist), not the team's
        amps = [s.value for k in fights if k.kind != "passive"
                for s in k.stats.get("damage_amp", ())
                if s.value is not None and s.value > 0 and not s.condition]
        self.dmg_amp = max(amps) if amps else 0.0
        # crowd control: tagged as such, an ability that slows, or an ABILITY
        # that knocks an enemy back at MIN_KNOCKBACK or more - a weapon's knockback
        # stat is recoil, and a movement tool's is the hero's own flight
        self.cc_tools = sorted({
            k.name for k in fights
            if k.keywords & set(CC_KEYWORDS)
            or (k.kind in ("ability", "ultimate") and damages(k) and shoves(k)
                and not k.keywords & set(MOBILITY_KEYWORDS))
            or (k.kind in ("ability", "ultimate")
                and any((s.value or 0) < 0 for s in k.stats.get("mspeed_slow", ())))})
        moves = [a for a in base if a.kind in ("ability", "passive")]
        # tagged as movement, or typed Movement with no tag (Siphon Blaster, Roll)
        self.mobility_tools = sorted({k.name for k in moves
                                      if k.keywords & set(MOBILITY_KEYWORDS)
                                      or typed(k, "movement")})
        self.flyer = any(k.keywords & set(FLIGHT_KEYWORDS) for k in moves)
        # a save is a tool, not a passive: Eject! leaves the mech, it saves no one
        tools = [k for k in base if k.kind != "passive"] + [
            u for u in ults if u.for_allies
            or (self.role == "support" and (u.stats.get("heal") or u.stats.get("hps")))]
        self.cleanse_tools = sorted({k.name for k in tools
                                     if k.keywords & set(CLEANSE_KEYWORDS)})
        self.invuln_tools = sorted({k.name for k in tools
                                    if "invulnerable" in k.keywords or k.name in SAVE_TOOLS})
        # what lands on a teammate: tagged for allies, an area that deals no damage
        # (Protection Suzu; Burrow's area is its exit hit), or an ultimate admitted above
        shared = [k for k in tools if k.for_allies or k in ults
                  or ("area of effect" in k.keywords and not damages(k))]
        self.team_cleanse_tools = sorted({k.name for k in shared
                                          if k.keywords & set(CLEANSE_KEYWORDS)})
        self.save_tools = sorted({k.name for k in shared
                                  if k.name in self.cleanse_tools + self.invuln_tools})
        # a bubble worn by a hero is not placed
        self.deployables = sorted({k.name for k in base if "deployable" in k.keywords
                                   and "attached" not in k.keywords})
        self.ult = ults[0] if ults else None

        def ult_hit(u):
            """One cast's damage: a flat figure times the cast's published charges, a
            total published over a window ("90 over 0.3 seconds"), a per-second rate
            over its duration, a shot fired at its rate for the duration (no more
            shots than the ammo), or a shot on its own cooldown, fired once and
            again each time it returns."""
            rows = [s for c in ("damage", "dps") for s in u.stats.get(c, ()) if s.per_second]
            over = [s.value for s in rows if s.den_value not in (None, 1.0)]
            rate = max([s.per_second for s in rows if s.den_value in (None, 1.0)] or [0.0])
            whole = [] if u.stats.get("dps") else [s.value * (u.plain_stat("charges") or 1)
                                                   for s in flat(u, "damage")]
            lasts = u.plain_stat("duration") or 0.0
            shots = [s.per_second for s in u.stats.get("fire_rate", ()) if s.per_second]
            hits = [s.value for s in flat(u, "damage") if "self" not in (s.condition or "")]
            fired = 0.0
            if not rows and shots and lasts and hits:
                fired = max(hits) * min(max(shots) * lasts, u.max_stat("ammo") or math.inf)
            # "cooldown 2.5 s (heavy round)" beside "175 (heavy round direct hit)"
            timed = [(s.value, w.value) for w in u.stats.get("cooldown", ())
                     if w.value and w.condition
                     for s in flat(u, "damage")
                     if w.condition in (s.condition or "") and "self" not in s.condition]
            if timed and lasts and not rows and not shots:
                fired = max(hit * (1 + math.floor(lasts / wait)) for hit, wait in timed)
            return max([*whole, *over, rate * lasts, fired, 0.0])

        self.ult_damage_raw = max([ult_hit(u) for u in ults] or [0.0])
        self.ult_damage = self.ult_damage_raw          # capped by World.settle_ults
        strongest = max(ults, key=ult_hit) if ults else None
        costs = [c for c in (u.max_stat("ult_req") for u in ults) if c]
        self.ult_cost = ((strongest.max_stat("ult_req") if strongest else None)
                         or (max(costs) if costs else None))
        # a damage ultimate by its rows: EMP's percent of current health counts,
        # and adds no hit points to ult_damage
        self.dmg_ult = any(s.value for u in ults for c in ("damage", "dps")
                           for s in u.stats.get(c, ()))
        tiers = [w for w in self.by_tier.values() if w[0] is not None]
        self.rank_spread = (max(t[0] for t in tiers) - min(t[0] for t in tiers)) \
            if len(tiers) >= 2 else 0.0
        self.trend = (self.win - self.prev_win
                      if self.win is not None and self.prev_win is not None else None)
        return self

    def map_win(self, map_id):
        rate = self.map_rates.get(map_id)
        return rate[0] if rate else None

    def map_ban(self, map_id):
        return self.map_bans.get(map_id)

    def map_pick(self, map_id):
        rate = self.map_rates.get(map_id)
        return rate[1] if rate else None


# the terrain the wiki's map articles describe, as map_terrain stores it
TERRAIN_FEATURES = ("chokes", "interiors", "high_ground", "flanks", "sightlines",
                    "open_ground", "hazards", "cover")
# the terrain each playstyle is played on (authored; cover leans to none)
TERRAIN_LEAN = {
    "brawl": ("chokes", "interiors"),
    "dive": ("high_ground", "flanks", "hazards"),
    "poke": ("sightlines", "open_ground"),
}


class Map:
    def __init__(self, mid, name, mode):
        self.id, self.name, self.mode = mid, name, mode
        self.stages = []          # names, in play order: see map_stages
        self.stage_terrain = {}   # stage -> {feature: (per thousand words, mentions)}; text only
        self.stage_z = {}         # stage -> {feature: z}: see stage_terrain
        self.terrain = {}         # feature -> mentions per thousand words; empty without text
        self.terrain_z = dict.fromkeys(TERRAIN_FEATURES, 0.0)   # see map_terrain
        self.rate_lift = {}       # style -> z: see map_styles
        self.terrain_lean = {}    # style -> z: see map_terrain
        self.styles = {}          # style -> (rate_lift + terrain_lean, None)

    @property
    def style_top(self):
        if not self.styles:
            return None
        return sorted(self.styles, key=lambda s: (-(self.styles[s][0] or 0), s))[0]

    @property
    def style_margin(self):
        scores = sorted((v[0] or 0 for v in self.styles.values()), reverse=True)
        if len(scores) >= 2:
            return round(scores[0] - scores[1], 3)
        return scores[0] if scores else 0


class World:
    def __init__(self):
        self.heroes = {}
        self.by_key = {}
        self.maps = {}
        self.maps_by_key = {}
        self.counters = set()
        self.answered_by = defaultdict(set)     # loser -> {winners}
        self.answers = defaultdict(set)         # winner -> {losers}
        self.synergies = {}                     # frozenset({a,b}) -> (score, note)
        self.partners = defaultdict(dict)       # a -> {b: (score, note)}
        self.snapshots = []
        self.newer_patches = []
        self.subrole_passives = {}              # subrole -> its passive's description
        self.role_icons = {}
        self.heal_bench = 0.0
        self.hps_bench = 0.0         # 2 x the median sustained healing across the supports
        self.ult_cap = 0.0           # the largest single figure an ultimate publishes
        self.catalog_counts = {}     # the strategies mirror: kind -> count
        self.playbook = ""           # the folder the mirror came from, when not the shipped one

    # --- lookups -------------------------------------------------------

    def hero(self, name):
        hid = self.by_key.get(name_key(name))
        return self.heroes[hid] if hid is not None else None

    def map(self, name):
        mid = self.maps_by_key.get(name_key(name))
        return self.maps[mid] if mid is not None else None

    def resolve(self, map_name, red, blue, bans=(), allow_announced=False):
        """Names -> (map or None, [Hero] red, [Hero] blue, [Hero] banned);
        unknown names raise, and so does a pick that is banned - or, unless
        `allow_announced`, a hero announced but not yet released."""
        unknown = [n for n in list(red) + list(blue) + list(bans) if self.hero(n) is None]
        if unknown:
            raise ValueError("unknown heroes: %s" % ", ".join(unknown))
        # a hero may play for either team but cannot hold two seats on one, and a
        # ban list naming the same hero twice bans one hero
        for label, names in (("red", red), ("blue", blue), ("ban", bans)):
            seen, twice = set(), []
            for n in names:
                hid = self.hero(n).id
                twice.append(n) if hid in seen else seen.add(hid)
            if twice:
                raise ValueError("%s picks the same hero twice: %s"
                                 % (label, ", ".join(sorted(set(twice)))))
        if not allow_announced:
            early = [self.hero(n) for n in list(red) + list(blue) + list(bans)
                     if not self.hero(n).released]
            if early:
                raise ValueError("announced, not yet playable: %s" % ", ".join(
                    "%s (releases %s)" % (h.name, h.release_date) if h.release_date else h.name
                    for h in early))
        m = None
        if map_name:
            m = self.map(map_name)
            if m is None:
                raise ValueError("unknown map: %s" % map_name)
        banned = [self.hero(n) for n in bans]
        banned_ids = {h.id for h in banned}
        picked = [self.hero(n) for n in list(red) + list(blue)]
        clash = [h.name for h in picked if h.id in banned_ids]
        if clash:
            raise ValueError("banned this match, cannot be picked: %s" % ", ".join(clash))
        return (m, [self.hero(n) for n in red], [self.hero(n) for n in blue], banned)

    def heroes_by_role(self):
        return sorted(self.heroes.values(),
                      key=lambda h: (ROLES.index(h.role), h.name))

    def maps_sorted(self):
        return sorted(self.maps.values(), key=lambda m: m.name)

    def synergy(self, a, b):
        return self.synergies.get(frozenset((a, b)))

    def counters_of(self, loser, winner):
        return (loser, winner) in self.counters


# --- loading ---------------------------------------------------------------

LATEST_BLIZZARD = """(select ms.snapshot_id from meta_snapshots ms
    join sources s on s.source_id = ms.source_id where s.code = 'blizzard'
    order by ms.captured_at desc, ms.snapshot_id desc limit 1)"""
# the latest earlier capture whose rates differ from the latest: a repeat pull
# stores the same rates again, and a date would turn on the session's timezone
PREVIOUS_BLIZZARD = """(select ms.snapshot_id from meta_snapshots ms
    join sources s on s.source_id = ms.source_id where s.code = 'blizzard'
    and exists (select 1 from hero_meta a join hero_meta b
                on b.hero_id = a.hero_id and b.tier_id = a.tier_id and b.region_id = a.region_id
                where a.snapshot_id = ms.snapshot_id and b.snapshot_id = %s
                  and a.win_rate is distinct from b.win_rate)
    order by ms.captured_at desc, ms.snapshot_id desc limit 1)""" % LATEST_BLIZZARD


def _rows(cx, sql, *args):
    return cx.execute(sql, args or None).fetchall()


def _z_scores(values):
    """{key: value} -> {key: z}, by the population's mean and sd; 0 where sd is 0."""
    if not values:
        return {}
    mean, sd = statistics.fmean(values.values()), statistics.pstdev(values.values())
    return {k: round((v - mean) / sd, 3) if sd else 0.0 for k, v in values.items()}


def map_terrain(w):
    """Map.terrain_z[F]: the map's mentions of F per thousand words, z-scored
    across the maps that have text; 0 for every F on a map with none.
    Map.terrain_lean[S]: the mean of terrain_z over TERRAIN_LEAN[S], z-scored
    across the same maps; absent on a map with no text."""
    read = sorted((m for m in w.maps.values() if m.terrain), key=lambda m: m.id)
    for m in w.maps.values():
        m.terrain_z = dict.fromkeys(TERRAIN_FEATURES, 0.0)
        m.terrain_lean = {}
    for feature in TERRAIN_FEATURES:
        for mid, z in _z_scores({m.id: m.terrain.get(feature, 0.0) for m in read}).items():
            w.maps[mid].terrain_z[feature] = z
    for style, features in sorted(TERRAIN_LEAN.items()):
        means = {m.id: statistics.fmean(m.terrain_z[f] for f in features) for m in read}
        for mid, z in _z_scores(means).items():
            w.maps[mid].terrain_lean[style] = z


def stage_terrain(w):
    """Map.stage_z[stage][F]: the stage's mentions of F per thousand words of its
    own text, z-scored across every stage that has text; a stage without text
    holds nothing."""
    read = sorted((m.id, stage) for m in w.maps.values() for stage in m.stage_terrain)
    for m in w.maps.values():
        m.stage_z = {stage: {} for stage in m.stage_terrain}
    for feature in TERRAIN_FEATURES:
        rates = {(mid, stage): w.maps[mid].stage_terrain[stage].get(feature, (0.0, 0))[0]
                 for mid, stage in read}
        for (mid, stage), z in _z_scores(rates).items():
            w.maps[mid].stage_z[stage][feature] = z


def map_styles(w):
    """Map.rate_lift[S]: for a playstyle S and a map, the mean, over released
    heroes tagged S, each weighted 1/(its tag count), of the hero's win rate
    on the map minus its overall win rate, z-scored across the maps.
    Map.styles[S] = (rate_lift[S] + terrain_lean[S], None); a missing half is 0."""
    heroes = sorted((h for h in w.heroes.values()
                     if h.released and h.styles and h.win is not None),
                    key=lambda h: h.id)
    maps = sorted(w.maps.values(), key=lambda m: m.id)
    for m in maps:
        m.rate_lift = {}
    for style in sorted({s for h in heroes for s in h.styles}):
        lifts = {}
        for m in maps:
            total = weight = 0.0
            for h in heroes:
                win = h.map_win(m.id)
                if style in h.styles and win is not None:
                    total += (win - h.win) / len(h.styles)
                    weight += 1 / len(h.styles)
            if weight:
                lifts[m.id] = total / weight
        for mid, z in _z_scores(lifts).items():
            w.maps[mid].rate_lift[style] = z
    for m in maps:
        m.styles = {s: (round(m.rate_lift.get(s, 0.0) + m.terrain_lean.get(s, 0.0), 3), None)
                    for s in sorted(set(m.rate_lift) | set(m.terrain_lean))}


def best_maps(w):
    """Hero.best_maps: the three maps with the largest (map win rate - overall
    win rate), only where positive; ties by map name."""
    for h in w.heroes.values():
        if h.win is None:
            continue
        lifts = sorted((-round(win - h.win, 3), w.maps[mid].name, mid)
                       for mid, (win, _) in h.map_rates.items() if win > h.win)
        h.best_maps = [mid for _, _, mid in lifts[:3]]


def load(cx):
    """The whole database -> World."""
    w = World()
    for hid, name, role, sub, hp, sh, ar, portrait, status, released in _rows(cx, """
            select h.hero_id, h.name, r.code, sr.name, h.health,
                   h.shield, h.armor, h.portrait_url, h.status, h.release_date
            from heroes h join roles r using(role_id)
            join subroles sr on sr.subrole_id = h.subrole_id"""):
        w.heroes[hid] = Hero(hid, name, role, sub, hp, sh, ar, portrait, status, released)
        w.by_key[name_key(name)] = hid
    for code, url in _rows(cx, "select code, icon_url from roles"):
        w.role_icons[code] = url
    for sub, passive in _rows(
            cx, "select name, passive_description from subroles"):
        w.subrole_passives[sub] = passive

    abilities = {}
    for aid, hid, name, kind, desc, kw in _rows(cx, """
            select a.ability_id, a.hero_id, a.name, coalesce(k.code, 'ability'),
                   a.description, a.keywords
            from abilities a left join ability_kinds k using(kind_id)
            order by a.hero_id, a.position"""):
        kit = Kit(name, kind, desc, kw)
        abilities[aid] = kit
        w.heroes[hid].abilities.append(kit)
    for aid, code, value, un, ud, dv, cond, text in _rows(cx, """
            select s.ability_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from ability_stats s join stat_keys k using(stat_key_id)
            order by s.ability_stat_id"""):
        abilities[aid].stats[code].append(Stat(code, value, un, ud, dv, cond, text))
    for aid, affects, applies, magnitude, unit in _rows(cx, """
            select ability_id, affects, applies_to, magnitude, unit
            from ability_modifiers"""):
        kit = abilities[aid]
        for hero in w.heroes.values():
            if kit in hero.abilities:
                hero.modifiers.append((kit.name, affects, applies, float(magnitude),
                                       unit))
                break

    configs = {}
    for cid, hid, wname, cname, wtype, kw, slot in _rows(cx, """
            select c.config_id, w.hero_id, w.name, c.name, c.weapon_type,
                   c.keywords, s.code
            from weapon_configs c join weapons w using(weapon_id)
            join weapon_config_slots s on s.slot_id = c.slot_id
            order by w.hero_id, w.position, c.position"""):
        kit = Kit(cname or wname, "weapon", "", kw)
        kit.extra["weapon"] = wname
        kit.extra["weapon_type"] = wtype
        kit.extra["slot"] = slot
        configs[cid] = kit
        w.heroes[hid].weapons.append(kit)
    for cid, code, value, un, ud, dv, cond, text in _rows(cx, """
            select s.config_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from weapon_stats s join stat_keys k using(stat_key_id)
            order by s.weapon_stat_id"""):
        configs[cid].stats[code].append(Stat(code, value, un, ud, dv, cond, text))

    perks = {}
    for pid, hid, name, tier, desc in _rows(cx, """
            select p.perk_id, p.hero_id, p.name, t.code, p.description
            from perks p join perk_tiers t using(tier_id)
            order by p.hero_id, p.tier_id, p.position"""):
        kit = Kit(name, "perk:" + tier, desc)
        perks[pid] = kit
        w.heroes[hid].perks.append(kit)
    for pid, code, value, un, ud, dv, cond, text in _rows(cx, """
            select s.perk_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from perk_stats s join stat_keys k using(stat_key_id)
            order by s.perk_stat_id"""):
        perks[pid].stats[code].append(Stat(code, value, un, ud, dv, cond, text))
    for hid, perk, ability in _rows(cx, """
            select p.hero_id, p.name, a.name from perk_ability_effects e
            join perks p using(perk_id) join abilities a using(ability_id)
            order by p.hero_id, p.position, a.position"""):
        w.heroes[hid].perk_effects.append((perk, ability))

    for hid, style in _rows(cx, "select hero_id, style from playstyle"):
        w.heroes[hid].styles.add(style)

    for hid, tier, win, pick, ban in _rows(cx, """
            select m.hero_id, t.code, m.win_rate, m.pick_rate, m.ban_rate
            from hero_meta m join competitive_tiers t on t.tier_id = m.tier_id
            where m.snapshot_id = %s""" % LATEST_BLIZZARD):
        h = w.heroes.get(hid)
        if h is None:
            continue
        rates = tuple(float(x) if x is not None else None for x in (win, pick, ban))
        if tier == "all":
            h.win, h.pick, h.ban = rates
        else:
            h.by_tier[tier] = rates
    for hid, win in _rows(cx, """
            select m.hero_id, m.win_rate from hero_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % PREVIOUS_BLIZZARD):
        if hid in w.heroes and win is not None:
            w.heroes[hid].prev_win = float(win)

    for mid, name, mode in _rows(cx, """
            select m.map_id, m.name, g.name from maps m
            left join map_modes mm using(map_id)
            left join game_modes g using(mode_id)"""):
        w.maps[mid] = Map(mid, name, mode)
        w.maps_by_key[name_key(name)] = mid
    for mid, stage in _rows(cx, "select map_id, name from map_stages order by map_id, position"):
        w.maps[mid].stages.append(stage)
    for hid, mid, win, pick, ban in _rows(cx, """
            select m.hero_id, m.map_id, m.win_rate, m.pick_rate, m.ban_rate from map_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % LATEST_BLIZZARD):
        if hid in w.heroes and mid in w.maps and win is not None:
            w.heroes[hid].map_rates[mid] = (float(win), float(pick) if pick is not None else None)
            if ban is not None:
                w.heroes[hid].map_bans[mid] = float(ban)
    best_maps(w)
    for mid, feature, rate in _rows(cx, "select map_id, feature, per_thousand from map_terrain"):
        if mid in w.maps:
            w.maps[mid].terrain[feature] = float(rate)
    map_terrain(w)
    for mid, stage, feature, rate, mentions in _rows(cx, """
            select s.map_id, s.name, t.feature, t.per_thousand, t.mentions
            from stage_terrain t join map_stages s using(stage_id)"""):
        if mid in w.maps:
            w.maps[mid].stage_terrain.setdefault(stage, {})[feature] = (float(rate), mentions)
    stage_terrain(w)

    for loser, winner in _rows(cx, "select hero_id, countered_by_id from counters"):
        w.counters.add((loser, winner))
        w.answered_by[loser].add(winner)
        w.answers[winner].add(loser)
    for a, b, score, note in _rows(cx, "select hero_id, other_id, score, note from synergies"):
        w.synergies[frozenset((a, b))] = (score, note)
        w.partners[a][b] = (score, note)
        w.partners[b][a] = (score, note)

    w.snapshots = [{"source": src, "captured": str(cap), "patch": patch,
                    "released": str(rel) if rel else None, "season": season,
                    "queue": queue, "platform": platform, "region": region}
                   for src, cap, patch, rel, season, queue, platform, region in _rows(cx, """
            select src.code, ms.captured_at::date, p.name, p.released, se.name,
                   ms.queue, ms.platform,
                   (select string_agg(distinct r.name, ', ') from hero_meta hm
                    join regions r using(region_id)
                    where hm.snapshot_id = ms.snapshot_id)
            from meta_snapshots ms join sources src using(source_id)
            left join patches p using(patch_id)
            left join seasons se using(season_id)
            where ms.snapshot_id in (
                select distinct on (source_id, queue) snapshot_id from meta_snapshots
                order by source_id, queue, captured_at desc)
            order by ms.captured_at desc""")]
    w.newer_patches = [(n, str(r)) for n, r in _rows(cx, """
            select p.name, p.released from patches p
            where p.released > (select coalesce(max(pp.released), '1900-01-01')
                from meta_snapshots ms join patches pp using(patch_id))
            order by p.released desc""")]
    map_styles(w)
    if cx.execute("select to_regclass('strategies')").fetchone()[0]:
        w.catalog_counts = dict(_rows(cx, "select kind, count(*) from strategies group by kind"))
        named = [p for (p,) in _rows(cx, "select distinct playbook from strategies")]
        w.playbook = named[0] if len(named) == 1 and named[0] != "inference/strategies" else ""
    for hero in w.heroes.values():
        hero.finish()
    # the benches and the cap read the released roster: an announced hero sets nothing
    supports = [h.peak_heal for h in w.heroes.values()
                if h.role == "support" and h.released and h.peak_heal]
    w.heal_bench = 2 * statistics.median(supports) if supports else 0.0
    rates = [h.hps for h in w.heroes.values()
             if h.role == "support" and h.released and h.hps]
    w.hps_bench = 2 * statistics.median(rates) if rates else 0.0
    # one ultimate's damage is worth, at most, the largest single figure one
    # publishes: a beam held for twenty seconds is not seven Self-Destructs
    flat_ults = [s.value for h in w.heroes.values() if h.released for u in h.abilities
                 if u.kind == "ultimate" and u.name not in REMECH
                 for s in u.stats.get("damage", ())
                 if s.value is not None and s.unit_den is None and s.unit_num != "percent"]
    w.ult_cap = max(flat_ults) if flat_ults else 0.0
    for hero in w.heroes.values():
        if w.ult_cap:
            hero.ult_damage = min(hero.ult_damage_raw, w.ult_cap)
    return w
