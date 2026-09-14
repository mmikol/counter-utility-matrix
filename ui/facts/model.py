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
# keywords column; nothing here is guessed from prose.
CC_KEYWORDS = ("stun", "sleep", "immobilize", "hinder", "knockback",
               "self knockback", "freeze", "hack")
MOBILITY_KEYWORDS = ("movement", "strong movement", "evasive", "flight")
CLEANSE_KEYWORDS = ("lesser cleanse", "greater cleanse")
FLIGHT_RE = re.compile(r"\b(fly|flies|flight|hover|airborne|soar)\w*", re.I)
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
    __slots__ = ("description", "extra", "keywords", "kind", "name", "stats")

    def __init__(self, name, kind, description="", keywords=""):
        self.name, self.kind, self.description = name, kind, description
        self.keywords = {k.strip().lower() for k in (keywords or "").split("::")
                         if k.strip()}
        self.stats = defaultdict(list)
        self.extra = {}

    def max_stat(self, code):
        values = [s.value for s in self.stats.get(code, ()) if s.value is not None]
        return max(values) if values else None

class Hero:
    @property
    def released(self):
        return self.status == "released"

    def __init__(self, hid, slug, name, role, subrole, health, shield, armor,
                 portrait, status="released", release_date=None):
        self.id, self.slug, self.name = hid, slug, name
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
        self.best_maps = []
        self.perk_effects = []       # (perk, the ability it alters)

    # --- derived scalars, computed once the kit and rates are loaded ------

    def finish(self):
        kits = self.abilities + self.weapons + self.perks
        self.pool = self.health + self.shield + self.armor
        self.keywords = set().union(*(k.keywords for k in kits)) if kits else set()

        def kit_max(code, among=None):
            values = [k.max_stat(code) for k in (among or kits)]
            values = [v for v in values if v is not None]
            return max(values) if values else None

        heal_values = [k.max_stat(c) for k in kits for c in ("heal", "hps")]
        heal_values = [v for v in heal_values if v is not None]
        self.peak_heal = max(heal_values) if heal_values else 0.0
        self.hps = max([s.per_second for k in kits for c in ("hps", "heal")
                        for s in k.stats.get(c, ()) if s.per_second] or [0.0])
        self.dps = max([s.per_second for k in kits for c in ("dps", "damage")
                        for s in k.stats.get(c, ()) if s.per_second] or [0.0])
        burst = [s.value for k in kits for s in k.stats.get("damage", ())
                 if s.value is not None and s.unit_den is None]
        self.burst = max(burst) if burst else 0.0
        self.max_range = kit_max("range") or 0.0
        cds = [s.value for k in self.abilities for s in k.stats.get("cooldown", ())
               if s.value is not None]
        self.cooldowns = sorted(cds)
        self.median_cooldown = statistics.median(cds) if cds else None
        self.weapon_kinds = set()
        for w in self.weapons:
            t = (w.extra.get("weapon_type") or "").lower()
            if t:
                self.weapon_kinds.add(
                    "hitscan" if "hitscan" in t else "beam" if "beam" in t
                    else "melee" if "melee" in t else "projectile")
        self.hitscan = "hitscan" in self.weapon_kinds or "hitscan" in self.keywords
        self.beam = "beam" in self.weapon_kinds or "beam" in self.keywords
        self.melee = "melee" in self.weapon_kinds
        self.aoe_count = sum(1 for k in kits if "area of effect" in k.keywords)
        self.barrier_hp = kit_max("barrier_health") or 0.0
        self.pierces_barrier = any(
            (k.max_stat("ignores_barrier") or 0) >= 1 or "ignore barrier" in k.keywords
            or "barrier piercing" in k.keywords for k in kits)
        self.overhealth = kit_max("overhealth") or 0.0
        mods = [s.value for k in kits for s in k.stats.get("healing_mod", ())
                if s.value is not None]
        self.antiheal = min([m for m in mods if m < 0] or [0.0])
        self.heal_amp = max([m for m in mods if m > 0] or [0.0])
        amps = [s.value for k in kits for s in k.stats.get("damage_amp", ())
                if s.value is not None and s.value > 0]
        self.dmg_amp = max(amps) if amps else 0.0
        # crowd control: tagged as such, or an ABILITY that knocks back -
        # a weapon's knockback stat is recoil physics, not peel
        self.cc_tools = sorted({k.name for k in kits
                                if k.keywords & set(CC_KEYWORDS)
                                or (k.kind in ("ability", "ultimate")
                                    and k.stats.get("kbspeed"))})
        self.mobility_tools = sorted({k.name for k in self.abilities
                                      if k.keywords & set(MOBILITY_KEYWORDS)})
        self.flyer = any("flight" in k.keywords or FLIGHT_RE.search(k.description or "")
                         for k in self.abilities)
        self.cleanse_tools = sorted({k.name for k in kits
                                     if k.keywords & set(CLEANSE_KEYWORDS)})
        self.invuln_tools = sorted({k.name for k in kits
                                    if "invulnerable" in k.keywords})
        self.deployables = sorted({k.name for k in kits if "deployable" in k.keywords})
        ults = [a for a in self.abilities if a.kind == "ultimate"]
        self.ult = ults[0] if ults else None
        self.ult_damage = max([u.max_stat("damage") or 0.0 for u in ults] or [0.0])
        costs = [u.max_stat("ult_req") for u in ults]
        costs = [c for c in costs if c]
        self.ult_cost = min(costs) if costs else None
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
        self.subrole_passives = {}
        self.role_icons = {}
        self.heal_bench = 0.0
        self.catalog_counts = {}     # the strategies mirror: kind -> count

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
    for hid, slug, name, role, sub, hp, sh, ar, portrait, status, released in _rows(cx, """
            select h.hero_id, h.slug, h.name, r.code, sr.name, h.health,
                   h.shield, h.armor, h.portrait_url, h.status, h.release_date
            from heroes h join roles r using(role_id)
            join subroles sr on sr.subrole_id = h.subrole_id"""):
        w.heroes[hid] = Hero(hid, slug, name, role, sub, hp, sh, ar, portrait, status, released)
        w.by_key[name_key(name)] = hid
    for code, url in _rows(cx, "select code, icon_url from roles"):
        w.role_icons[code] = url
    for role, sub, passive, icon in _rows(cx, """
            select r.code, sr.name, sr.passive_description, sr.icon_url
            from subroles sr join roles r using(role_id)"""):
        w.subrole_passives[sub] = (role, passive, icon)

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
    for hid, mid, win, pick in _rows(cx, """
            select m.hero_id, m.map_id, m.win_rate, m.pick_rate from map_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % LATEST_BLIZZARD):
        if hid in w.heroes and mid in w.maps and win is not None:
            w.heroes[hid].map_rates[mid] = (float(win), float(pick) if pick is not None else None)
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
    for hero in w.heroes.values():
        hero.finish()
    supports = [h.peak_heal for h in w.heroes.values()
                if h.role == "support" and h.peak_heal]
    w.heal_bench = 2 * statistics.median(supports) if supports else 0.0
    return w
