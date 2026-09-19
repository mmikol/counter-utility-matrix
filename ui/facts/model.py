"""The World: the whole database in memory, loaded fresh from Postgres on
every request so the UI layer always reads what the data layer stored.

Loading is a dozen queries and a few thousand rows; cheap enough to do per
click, and it is what lets the inference layer's solver evaluate thousands
of candidate compositions without a query each.
"""

import re
import statistics
from collections import defaultdict

from db.data.names import name_key

ROLES = ("tank", "damage", "support")

# Keyword families the wiki tags abilities with. Read verbatim from the
# keywords column; nothing here is guessed from prose. The wiki writes a
# keyword as `family;;qualifier` ("area of effect;;spherical", "invulnerable;;
# targets"): a Kit keeps the family in `keywords` and the whole atom in `atoms`.
CC_KEYWORDS = ("stun", "sleep", "immobilize", "hinder", "knockback", "knockdown",
               "hacked")
MOBILITY_KEYWORDS = ("movement", "strong movement", "evasive", "flight", "strong flight")
FLIGHT_KEYWORDS = ("flight", "strong flight")
CLEANSE_KEYWORDS = ("lesser cleanse", "greater cleanse", "perfect cleanse")
ALLY_QUALIFIERS = ("target ally", "targets")
# a flat damage figure that is a sum, not one hit
SUMMED_RE = re.compile(r"\b(dot|over time|total|if all|both)\b", re.I)
# a rate with its reload folded in, as the wiki words it beside the firing rate
RELOAD_RE = re.compile(r"reload|overall|recharge", re.I)
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?")
PRIMARY_SLOTS = ("primary_fire", "hip_fire", "default")
# weapon forms held for seconds on a cooldown, or out of the hero's fighting
# form: not the weapon the hero fights with (authored; the wiki has no field)
FORM_GATED = ("Configuration: Assault", "Light Gun")
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


def _number(text):
    """The first figure in a line of the wiki's prose; of a range, its top."""
    found = NUMBER_RE.search(text or "")
    return float(found.group(2) or found.group(1)) if found else None


def _rate(kit, code, per_shot):
    """One kit piece's sustained rate for `code` (dps or hps), hp/s: the
    published rate with its reload where the wiki gives one, else the firing
    rate, else one `per_shot` times the fire rate. None when nothing says."""
    plain, variants, loaded = [], [], []
    for stat in kit.stats.get(code, ()):
        value = stat.value if stat.value is not None else _number(stat.text)
        if value is None:
            continue
        note = "%s %s" % (stat.condition or "", stat.text or "")
        with_reload = _number(stat.condition) if RELOAD_RE.search(stat.condition or "") \
            else (value if RELOAD_RE.search(note) else None)
        if with_reload is not None and with_reload <= value:
            loaded.append(with_reload)
        elif stat.condition and not RELOAD_RE.search(stat.condition):
            variants.append(value)               # "variant 2", "at full charge"
        else:
            plain.append(value)
    if loaded:
        return min(loaded)
    if plain:
        return max(plain)
    if variants:
        return statistics.median_low(variants)
    rate = kit.max_stat("fire_rate")
    shots = [s.value for s in kit.stats.get(per_shot, ())
             if s.value is not None and s.unit_den is None]
    return max(shots) * rate if shots and rate else None


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
        self.alt_rates = {}          # other sources' own populations: code -> (win, pick)
        self.prev_win = None
        self.map_rates = {}
        self.map_bans = {}           # map_id -> ban rate on that map, when published
        self.best_maps = []
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
        ults = [a for a in self.abilities if a.kind == "ultimate"]
        base = self.weapons + [a for a in self.abilities if a.kind != "ultimate"]
        fights = base + ults
        self.pool = self.health + self.shield + self.armor
        self.keywords = set().union(*(k.keywords for k in base)) if base else set()

        def flat(kit, code):
            return [s for s in kit.stats.get(code, ()) if s.value is not None
                    and s.unit_den is None]

        def damages(kit):
            return bool(kit.stats.get("damage") or kit.stats.get("dps"))

        # --- damage: the weapon the hero fights with, sustained ------------------
        steady = [w for w in self.weapons if w.name not in FORM_GATED]
        held = [w for w in steady if w.extra.get("slot") in PRIMARY_SLOTS and damages(w)]
        rates = [r for r in (_rate(w, "dps", "damage") for w in (held or steady)) if r]
        self.dps = max(rates) if rates else 0.0

        # --- burst: the biggest single hit, a headshot where one counts ---------
        hits = []
        for kit in base:
            tick = max([s.per_second for s in kit.stats.get("damage", ()) if s.per_second]
                       or [0.0])
            lasts = kit.max_stat("duration") or 0.0
            crit = kit.max_stat("headshot_mod") or 1.0
            crits = (kit.max_stat("headshot") or 0) >= 1 and (kit.max_stat("pellets") or 1) < 2
            singles = [s.value for s in flat(kit, "damage") if not s.condition]
            for stat in flat(kit, "damage"):
                if SUMMED_RE.search(stat.condition or ""):
                    continue
                if tick and lasts and abs(stat.value - tick * lasts) < 0.5:
                    continue                      # the rate over its duration, not a hit
                volley = any(one and stat.value > one and stat.value % one == 0
                             for one in singles)  # five orbs at once: no one headshot
                hits.append(stat.value * (crit if crits and not volley else 1.0))
        self.burst = max(hits) if hits else 0.0

        # --- healing: a rate (hp/s) and a cast (hp) are two quantities; what
        #     lands on teammates is the team's, the rest is the hero's own -------
        team_rate, team_cast, own_rate, own_cast = [], [], [], []
        for kit in base:
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
        self.hps = max(team_rate or [0.0])
        self.peak_heal = max(team_cast or [0.0])
        self.self_hps = max(own_rate or [0.0])
        self.self_heal = max(own_cast or [0.0])

        # --- reach: the weapons' published limits. A weapon that publishes none
        #     says nothing, and the hero stays out of the range metrics: unknown is
        #     not a number ------------------------------------------------------------
        known = [r for r in map(_reach, [w for w in steady if damages(w)]) if r]
        self.max_range = max(known) if known else 0.0

        cds = [s.value for k in self.abilities for s in k.stats.get("cooldown", ())
               if s.value is not None]
        self.cooldowns = sorted(cds)
        self.median_cooldown = statistics.median(cds) if cds else None
        self.weapon_kinds = set()
        for w in steady:
            t = (w.extra.get("weapon_type") or "").lower()
            if t:
                self.weapon_kinds.add(
                    "hitscan" if "hitscan" in t else "beam" if "beam" in t
                    else "melee" if "melee" in t else "projectile")
        guns = set().union(*(k.keywords for k in base if k.kind == "weapon")) \
            if base else set()
        self.hitscan = "hitscan" in self.weapon_kinds or "hitscan" in guns
        self.beam = "beam" in self.weapon_kinds or "beam" in guns
        self.melee = "melee" in self.weapon_kinds
        self.aoe_count = sum(1 for k in fights if "area of effect" in k.keywords)
        barriers = [k.plain_stat("barrier_health") for k in base]
        barriers += [k.plain_stat("health") for k in base
                     if k.keywords & {"barrier", "bubble"} and not k.stats.get("barrier_health")]
        self.barrier_hp = max([b for b in barriers if b] or [0.0])
        self.pierces_barrier = any(
            damages(k) and ("barrier piercing" in k.keywords
                            or ((k.max_stat("ignores_barrier") or 0) >= 1
                                and not k.for_allies)) for k in base)
        self.overhealth = max([s.value for k in fights for s in flat(k, "overhealth")]
                              or [0.0])
        mods = [s.value for k in fights for s in k.stats.get("healing_mod", ())
                if s.value is not None]
        self.antiheal = min([m for m in mods if m < 0] or [0.0])
        self.heal_amp = max([m for m in mods if m > 0] or [0.0])
        amps = [s.value for k in fights for s in k.stats.get("damage_amp", ())
                if s.value is not None and s.value > 0 and not s.condition]
        self.dmg_amp = max(amps) if amps else 0.0
        # crowd control: tagged as such, an ability that slows, or an ABILITY
        # that knocks an enemy back - a weapon's knockback stat is recoil, and a
        # movement tool's is the hero's own flight
        self.cc_tools = sorted({
            k.name for k in fights
            if k.keywords & set(CC_KEYWORDS)
            or (k.kind in ("ability", "ultimate") and damages(k) and k.stats.get("kbspeed")
                and not k.keywords & set(MOBILITY_KEYWORDS))
            or (k.kind in ("ability", "ultimate")
                and any((s.value or 0) < 0 for s in k.stats.get("mspeed_slow", ())))})
        moves = [a for a in base if a.kind in ("ability", "passive")]
        self.mobility_tools = sorted({k.name for k in moves
                                      if k.keywords & set(MOBILITY_KEYWORDS)})
        self.flyer = any(k.keywords & set(FLIGHT_KEYWORDS) for k in moves)
        # a save is a tool, not a passive: Eject! leaves the mech, it saves no one
        tools = [k for k in base if k.kind != "passive"] + [
            u for u in ults if u.for_allies or u.stats.get("heal") or u.stats.get("hps")]
        self.cleanse_tools = sorted({k.name for k in tools
                                     if k.keywords & set(CLEANSE_KEYWORDS)})
        self.invuln_tools = sorted({k.name for k in tools if "invulnerable" in k.keywords})
        self.deployables = sorted({k.name for k in base if "deployable" in k.keywords})
        self.ult = ults[0] if ults else None

        def ult_hit(u):
            """One cast's damage: the flat figure, or a rate over its duration."""
            rate = max([s.per_second for c in ("damage", "dps") for s in u.stats.get(c, ())
                        if s.per_second] or [0.0])
            whole = [] if u.stats.get("dps") else [s.value for s in flat(u, "damage")]
            return max([*whole, rate * (u.plain_stat("duration") or 0.0), 0.0])

        self.ult_damage_raw = max([ult_hit(u) for u in ults] or [0.0])
        self.ult_damage = self.ult_damage_raw          # capped by World.settle_ults
        strongest = max(ults, key=ult_hit) if ults else None
        costs = [c for c in (u.max_stat("ult_req") for u in ults) if c]
        self.ult_cost = ((strongest.max_stat("ult_req") if strongest else None)
                         or (max(costs) if costs else None))
        self.dmg_ult = self.ult_damage > 0
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


class Map:
    def __init__(self, mid, name, mode):
        self.id, self.name, self.mode = mid, name, mode
        self.stages = []
        self.styles = {}          # style -> (score, note)

    @property
    def style_top(self):
        if not self.styles:
            return None
        return sorted(self.styles, key=lambda s: (-(self.styles[s][0] or 0), s))[0]

    @property
    def style_margin(self):
        scores = sorted((v[0] or 0 for v in self.styles.values()), reverse=True)
        return (scores[0] - scores[1]) if len(scores) >= 2 else (scores[0] if scores else 0)


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
        self.archetypes = defaultdict(dict)     # style -> {role: (slots, note)}
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
PREVIOUS_BLIZZARD = """(select ms.snapshot_id from meta_snapshots ms
    join sources s on s.source_id = ms.source_id where s.code = 'blizzard'
    order by ms.captured_at desc, ms.snapshot_id desc offset 1 limit 1)"""


def _rows(cx, sql, *args):
    return cx.execute(sql, args or None).fetchall()


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
    # the other sources' rates are a second population, kept apart
    for hid, code, win, pick in _rows(cx, """
            select m.hero_id, src.code, m.win_rate, m.pick_rate from hero_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            join meta_snapshots ms on ms.snapshot_id = m.snapshot_id
            join sources src on src.source_id = ms.source_id
            where t.code = 'all' and src.code <> 'blizzard' and m.win_rate is not null
              and ms.snapshot_id = (select ms2.snapshot_id from meta_snapshots ms2
                                    where ms2.source_id = ms.source_id
                                    order by ms2.captured_at desc, ms2.snapshot_id desc
                                    limit 1)"""):
        if hid in w.heroes:
            w.heroes[hid].alt_rates[code] = (float(win), float(pick) if pick is not None else None)

    for mid, name, mode in _rows(cx, """
            select m.map_id, m.name, g.name from maps m
            left join map_modes mm using(map_id)
            left join game_modes g using(mode_id)"""):
        w.maps[mid] = Map(mid, name, mode)
        w.maps_by_key[name_key(name)] = mid
    for mid, stage in _rows(cx, "select map_id, name from map_stages order by map_id, position"):
        w.maps[mid].stages.append(stage)
    for mid, style, score, note in _rows(
            cx, "select map_id, style, score, note from map_playstyle"):
        w.maps[mid].styles[style] = (score, note)
    for hid, mid, win, pick, ban in _rows(cx, """
            select m.hero_id, m.map_id, m.win_rate, m.pick_rate, m.ban_rate from map_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % LATEST_BLIZZARD):
        if hid in w.heroes and mid in w.maps and win is not None:
            w.heroes[hid].map_rates[mid] = (float(win), float(pick) if pick is not None else None)
            if ban is not None:
                w.heroes[hid].map_bans[mid] = float(ban)
    for hid, mid in _rows(
            cx, "select hero_id, map_id from map_strategy order by hero_id, position"):
        if hid in w.heroes and mid in w.maps:
            w.heroes[hid].best_maps.append(mid)

    for loser, winner in _rows(cx, "select hero_id, countered_by_id from counters"):
        w.counters.add((loser, winner))
        w.answered_by[loser].add(winner)
        w.answers[winner].add(loser)
    for a, b, score, note in _rows(cx, "select hero_id, other_id, score, note from synergies"):
        w.synergies[frozenset((a, b))] = (score, note)
        w.partners[a][b] = (score, note)
        w.partners[b][a] = (score, note)
    for style, role, slots, note in _rows(cx, """
            select a.style, r.code, a.slots, a.note from comp_archetypes a
            join roles r using(role_id)"""):
        w.archetypes[style][role] = (slots, note)

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
    if cx.execute("select to_regclass('strategies')").fetchone()[0]:
        w.catalog_counts = dict(_rows(cx, "select kind, count(*) from strategies group by kind"))
        named = [p for (p,) in _rows(cx, "select distinct playbook from strategies")]
        w.playbook = named[0] if len(named) == 1 and named[0] != "inference/strategies" else ""
    for hero in w.heroes.values():
        hero.finish()
    supports = [h.peak_heal for h in w.heroes.values()
                if h.role == "support" and h.peak_heal]
    w.heal_bench = 2 * statistics.median(supports) if supports else 0.0
    rates = [h.hps for h in w.heroes.values() if h.role == "support" and h.hps]
    w.hps_bench = 2 * statistics.median(rates) if rates else 0.0
    # one ultimate's damage is worth, at most, the largest single figure one
    # publishes: a beam held for twenty seconds is not seven Self-Destructs
    flat_ults = [s.value for h in w.heroes.values() for u in h.abilities
                 if u.kind == "ultimate" for s in u.stats.get("damage", ())
                 if s.value is not None and s.unit_den is None]
    w.ult_cap = max(flat_ults) if flat_ults else 0.0
    for hero in w.heroes.values():
        if w.ult_cap:
            hero.ult_damage = min(hero.ult_damage_raw, w.ult_cap)
    return w
