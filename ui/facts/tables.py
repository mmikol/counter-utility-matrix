"""The load: every data table read into one World, fresh on each request, so
the UI layer always reads what the data layer stored.

    world = tables.load(cx)

Loading is a dozen queries and a few thousand rows; cheap enough to do per
click, and it is what lets the inference layer's solver evaluate thousands
of candidate compositions without a query each. Each read step fills one
part of the World from its tables, and load runs them in the order each
relies on, then derives what the rows imply. Every data table is named
here: a test greps this module's source for each one.
"""

import statistics

import psycopg
from psycopg.rows import TupleRow

from db import KIND_ULTIMATE, KIND_WEAPON
from db.data.names import name_key
from ui.facts.kit import Kit, Stat
from ui.facts.model import REMECH, TERRAIN_FEATURES, TERRAIN_LEAN, Hero, Map, World
from ui.facts.records import Modifier, Snapshot

type Connection = psycopg.Connection[TupleRow]

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


def _rows(cx: Connection, sql: str, *args: object) -> list[TupleRow]:
    return cx.execute(sql, args or None).fetchall()


def _z_scores[K](values: dict[K, float]) -> dict[K, float]:
    """{key: value} -> {key: z}, by the population's mean and sd; 0 where sd is 0."""
    if not values:
        return {}
    mean, sd = statistics.fmean(values.values()), statistics.pstdev(values.values())
    return {k: round((v - mean) / sd, 3) if sd else 0.0 for k, v in values.items()}


def map_terrain(w: World) -> None:
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


def stage_terrain(w: World) -> None:
    """Map.stage_z[stage][F]: the stage's mentions of F per thousand words of its
    own text, z-scored across every stage that has text; a stage without text
    holds nothing."""
    read = sorted((m.id, stage) for m in w.maps.values() for stage in m.stage_terrain)
    for m in w.maps.values():
        m.stage_z = {stage: {} for stage in m.stage_terrain}
    for feature in TERRAIN_FEATURES:
        rates = {
            (mid, stage): w.maps[mid].stage_terrain[stage].get(feature, (0.0, 0))[0]
            for mid, stage in read}
        for (mid, stage), z in _z_scores(rates).items():
            w.maps[mid].stage_z[stage][feature] = z


def map_styles(w: World) -> None:
    """Map.rate_lift[S]: for a playstyle S and a map, the mean, over released
    heroes tagged S, each weighted 1/(its tag count), of the hero's win rate
    on the map minus its overall win rate, z-scored across the maps.
    Map.styles[S] = (rate_lift[S] + terrain_lean[S], None); a missing half is 0."""
    heroes = sorted(
        (h for h in w.heroes.values() if h.released and h.styles and h.win is not None),
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
        m.styles = {
            s: (round(m.rate_lift.get(s, 0.0) + m.terrain_lean.get(s, 0.0), 3), None)
            for s in sorted(set(m.rate_lift) | set(m.terrain_lean))}


def best_maps(w: World) -> None:
    """Hero.best_maps: the three maps with the largest (map win rate - overall
    win rate), only where positive; ties by map name."""
    for h in w.heroes.values():
        if h.win is None:
            continue
        lifts = sorted(
            (-round(win - h.win, 3), w.maps[mid].name, mid)
            for mid, (win, _) in h.map_rates.items() if win > h.win)
        h.best_maps = [mid for _, _, mid in lifts[:3]]


# --- the read steps: each fills its part of the World -----------------------

def _add_stats(kits: dict[int, Kit], rows: list[TupleRow]) -> None:
    """Each stat row, (piece id, code, value, units, condition, text), onto its piece."""
    for kid, code, value, un, ud, dv, cond, text in rows:
        kits[kid].stats[code].append(Stat(code, value, un, ud, dv, cond, text))


def _read_heroes(cx: Connection, w: World) -> None:
    """The heroes with their role, subrole and playstyles; the role icons and
    the subroles' passives."""
    for hid, name, role, sub, hp, sh, ar, portrait, status, released in _rows(cx, """
            select h.hero_id, h.name, r.code, sr.name, h.health,
                   h.shield, h.armor, h.portrait_url, h.status, h.release_date
            from heroes h join roles r using(role_id)
            join subroles sr on sr.subrole_id = h.subrole_id"""):
        w.heroes[hid] = Hero(hid, name, role, sub, hp, sh, ar, portrait, status, released)
        w.by_key[name_key(name)] = hid
    for code, url in _rows(cx, "select code, icon_url from roles"):
        w.role_icons[code] = url
    for sub, passive in _rows(cx, "select name, passive_description from subroles"):
        w.subrole_passives[sub] = passive
    for hid, style in _rows(cx, "select hero_id, style from playstyle"):
        w.heroes[hid].styles.add(style)


def _read_abilities(cx: Connection, w: World) -> None:
    """Each hero's abilities in order, their stats and the modifiers they apply."""
    abilities: dict[int, Kit] = {}
    for aid, hid, name, kind, desc, kw in _rows(cx, """
            select a.ability_id, a.hero_id, a.name, coalesce(k.code, 'ability'),
                   a.description, a.keywords
            from abilities a left join ability_kinds k using(kind_id)
            order by a.hero_id, a.position"""):
        kit = Kit(name, kind, desc, kw)
        abilities[aid] = kit
        w.heroes[hid].abilities.append(kit)
    _add_stats(abilities, _rows(cx, """
            select s.ability_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from ability_stats s join stat_keys k using(stat_key_id)
            order by s.ability_stat_id"""))
    for hid, name, affects, applies, magnitude, unit in _rows(cx, """
            select a.hero_id, a.name, m.affects, m.applies_to, m.magnitude, m.unit
            from ability_modifiers m join abilities a using(ability_id)
            order by m.modifier_id"""):
        w.heroes[hid].modifiers.append(Modifier(name, affects, applies, float(magnitude), unit))


def _read_weapons(cx: Connection, w: World) -> None:
    """Each hero's weapons, one kit piece per firing config, and their stats."""
    configs: dict[int, Kit] = {}
    for cid, hid, wname, cname, wtype, kw, slot in _rows(cx, """
            select c.config_id, w.hero_id, w.name, c.name, c.weapon_type,
                   c.keywords, s.code
            from weapon_configs c join weapons w using(weapon_id)
            join weapon_config_slots s on s.slot_id = c.slot_id
            order by w.hero_id, w.position, c.position"""):
        kit = Kit(cname or wname, KIND_WEAPON, "", kw)
        kit.extra["weapon"] = wname
        kit.extra["weapon_type"] = wtype
        kit.extra["slot"] = slot
        configs[cid] = kit
        w.heroes[hid].weapons.append(kit)
    _add_stats(configs, _rows(cx, """
            select s.config_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from weapon_stats s join stat_keys k using(stat_key_id)
            order by s.weapon_stat_id"""))


def _read_perks(cx: Connection, w: World) -> None:
    """Each hero's perks by tier, their stats and the abilities they alter."""
    perks: dict[int, Kit] = {}
    for pid, hid, name, tier, desc in _rows(cx, """
            select p.perk_id, p.hero_id, p.name, t.code, p.description
            from perks p join perk_tiers t using(tier_id)
            order by p.hero_id, p.tier_id, p.position"""):
        kit = Kit(name, "perk:" + tier, desc)
        perks[pid] = kit
        w.heroes[hid].perks.append(kit)
    _add_stats(perks, _rows(cx, """
            select s.perk_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from perk_stats s join stat_keys k using(stat_key_id)
            order by s.perk_stat_id"""))
    for hid, perk, ability in _rows(cx, """
            select p.hero_id, p.name, a.name from perk_ability_effects e
            join perks p using(perk_id) join abilities a using(ability_id)
            order by p.hero_id, p.position, a.position"""):
        w.heroes[hid].perk_effects.append((perk, ability))


def _read_rates(cx: Connection, w: World) -> None:
    """Each hero's rates in the latest Blizzard capture, overall and per tier,
    and its overall win rate in the capture before."""
    for hid, tier, win, pick, ban in _rows(cx, """
            select m.hero_id, t.code, m.win_rate, m.pick_rate, m.ban_rate
            from hero_meta m join competitive_tiers t on t.tier_id = m.tier_id
            where m.snapshot_id = %s""" % LATEST_BLIZZARD):
        h = w.heroes[hid]
        rates = tuple(float(x) if x is not None else None for x in (win, pick, ban))
        if tier == "all":
            h.win, h.pick, h.ban = rates
        else:
            h.by_tier[tier] = rates
    for hid, win in _rows(cx, """
            select m.hero_id, m.win_rate from hero_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % PREVIOUS_BLIZZARD):
        if win is not None:
            w.heroes[hid].prev_win = float(win)


def _read_maps(cx: Connection, w: World) -> None:
    """The maps with their mode, and their stages in play order."""
    for mid, name, mode in _rows(cx, """
            select m.map_id, m.name, g.name from maps m
            left join map_modes mm using(map_id)
            left join game_modes g using(mode_id)"""):
        w.maps[mid] = Map(mid, name, mode)
        w.maps_by_key[name_key(name)] = mid
    for mid, stage in _rows(cx, "select map_id, name from map_stages order by map_id, position"):
        w.maps[mid].stages.append(stage)


def _read_map_rates(cx: Connection, w: World) -> None:
    """Each hero's overall rates on each map in the latest Blizzard capture, and
    the best maps they make."""
    for hid, mid, win, pick, ban in _rows(cx, """
            select m.hero_id, m.map_id, m.win_rate, m.pick_rate, m.ban_rate from map_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % LATEST_BLIZZARD):
        if win is not None:
            w.heroes[hid].map_rates[mid] = (float(win), float(pick) if pick is not None else None)
            if ban is not None:
                w.heroes[hid].map_bans[mid] = float(ban)
    best_maps(w)


def _read_terrain(cx: Connection, w: World) -> None:
    """The terrain the wiki's articles describe, per map and per stage, with
    their z-scores."""
    for mid, feature, rate in _rows(cx, "select map_id, feature, per_thousand from map_terrain"):
        w.maps[mid].terrain[feature] = float(rate)
    map_terrain(w)
    for mid, stage, feature, rate, mentions in _rows(cx, """
            select s.map_id, s.name, t.feature, t.per_thousand, t.mentions
            from stage_terrain t join map_stages s using(stage_id)"""):
        w.maps[mid].stage_terrain.setdefault(stage, {})[feature] = (float(rate), mentions)
    stage_terrain(w)


def _read_relations(cx: Connection, w: World) -> None:
    """The wiki's counters, both ways, and its synergy pairs."""
    for loser, winner in _rows(cx, "select hero_id, countered_by_id from counters"):
        w.counters.add((loser, winner))
        w.answered_by[loser].add(winner)
        w.answers[winner].add(loser)
    for a, b, score, note in _rows(cx, "select hero_id, other_id, score, note from synergies"):
        w.synergies[frozenset((a, b))] = (score, note)
        w.partners[a][b] = (score, note)
        w.partners[b][a] = (score, note)


def _read_provenance(cx: Connection, w: World) -> None:
    """Where the rates come from: each source's newest capture, the patches
    shipped since, and the strategies mirror's shape."""
    w.snapshots = [
        Snapshot(
            source=src, captured=str(cap), patch=patch, released=str(rel) if rel else None,
            season=season, queue=queue, platform=platform, region=region)
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
    if _rows(cx, "select to_regclass('strategies')")[0][0]:
        w.catalog_counts = dict(_rows(cx, "select kind, count(*) from strategies group by kind"))
        named = [p for (p,) in _rows(cx, "select distinct playbook from strategies")]
        w.playbook = named[0] if len(named) == 1 and named[0] != "inference/strategies" else ""


def _benches(w: World) -> None:
    """The roster's healing benches and the ultimate cap, over the released
    heroes' derived numbers: an announced hero sets nothing."""
    supports = [
        h.peak_heal for h in w.heroes.values()
        if h.role == "support" and h.released and h.peak_heal]
    w.heal_bench = 2 * statistics.median(supports) if supports else 0.0
    rates = [h.hps for h in w.heroes.values() if h.role == "support" and h.released and h.hps]
    w.hps_bench = 2 * statistics.median(rates) if rates else 0.0
    # one ultimate's damage is worth, at most, the largest single figure one
    # publishes: a beam held for twenty seconds is not seven Self-Destructs
    flat_ults = [
        s.value for h in w.heroes.values() if h.released for u in h.abilities
        if u.kind == KIND_ULTIMATE and u.name not in REMECH
        for s in u.stats.get("damage", ())
        if s.value is not None and s.unit_den is None and s.unit_num != "percent"]
    w.ult_cap = max(flat_ults) if flat_ults else 0.0
    if w.ult_cap:                  # no cap to apply: every hero keeps its raw figure
        for hero in w.heroes.values():
            hero.ult_damage = min(hero.ult_damage_raw, w.ult_cap)


def load(cx: Connection) -> World:
    """The whole database -> World. `cx` is an open psycopg connection; this
    module never opens one of its own. The steps run in the order each relies
    on: the kit before the derived numbers, the rates before best_maps and
    map_styles, the terrain before map_styles, and the benches over the
    derived roster."""
    w = World()
    _read_heroes(cx, w)
    _read_abilities(cx, w)
    _read_weapons(cx, w)
    _read_perks(cx, w)
    _read_rates(cx, w)
    _read_maps(cx, w)
    _read_map_rates(cx, w)
    _read_terrain(cx, w)
    _read_relations(cx, w)
    _read_provenance(cx, w)
    map_styles(w)
    for hero in w.heroes.values():
        hero.derive_scalars()
    _benches(w)
    return w
