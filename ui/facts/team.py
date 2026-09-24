"""The team metrics: every TEAM_METRICS key for a team's picks, and the typed
bag they come in.

team_metrics computes the lot for one side, on a map, facing the other side;
each section of the registry - shape, durability, damage, sustain, tools,
cohesion, meta, map, versus - is one helper that writes its keys once. The
facts engine words the bag, the solver scores it, and compute's registry()
offers its keys to a strategy as team.<key> and enemy.<key>. MetricBag is
the shape every metric section shares, and number, text and the other
readers narrow a value where one kind is read.
"""

import statistics
from collections import Counter, OrderedDict
from collections.abc import Iterable

from ui.facts.draft import EXPECTED_SHAPE, TEAM_SIZE
from ui.facts.model import SQUISHY_POOL, Hero, Map, World

SPECIALIST_DELTA = 2.5
RANK_SENSITIVE = 6.0
FLIER_REACH = 30.0        # metres a hitscan weapon must publish to answer a flier

TEAM_METRICS = OrderedDict([
    # shape
    ("size", "picks locked on this team"),
    ("open_slots", "slots still open (%d - size)" % TEAM_SIZE),
    ("tanks", "tank count"), ("damage", "damage count"), ("supports", "support count"),
    ("subrole_diversity", "distinct subroles / size (1.0 = every pick a different job)"),
    ("subroles", "the subroles present"),
    ("shape_flags", "TANKLESS / double tank / triple DPS / NO SUPPORT / solo heal"),
    ("style_counts", "picks per playstyle tag (a hero can carry several)"),
    ("style_top", "the modal playstyle among the picks"),
    ("style_lean", "the playstyle a strict majority of picks carry, else none"),
    ("style_fit", "share of picks tagged with the map's rewarded style (0 without a map)"),
    ("archetype_deviation",
        "picks over EXPECTED_SHAPE's two per role (0 without a map)"),
    # durability
    ("pool_total", "team effective HP: sum of health + shield + armor, plus a form's armor by"
                   " its uptime"),
    ("pool_min", "the weakest pick's pool - focus fire finds the minimum"),
    ("weakest", "who holds the smallest pool"),
    ("armor_total", "summed armor, a form's by its uptime"), ("armor_share", "armor / pool"),
    ("shield_total", "summed recharging shields"), ("shield_share", "shields / pool"),
    ("squish_count", "picks at or under %d pool" % SQUISHY_POOL),
    ("squishies", "the picks at or under %d pool" % SQUISHY_POOL),
    ("overhealth_total", "summed peak overhealth a kit can grant"),
    # damage
    ("dps_floor",
        "summed published per-second damage figures (a floor: misses and healing ignored)"),
    ("dps_count", "picks whose kit publishes a per-second damage figure"),
    ("burst_max", "the biggest single hit on the team, a headshot where one counts"),
    ("one_shots", "picks whose biggest hit, not a melee swing, kills a 250-pool hero"),
    ("burst_hero", "who holds the biggest single hit"),
    ("burst_ranged", "the biggest single hit from a pick that is not melee-only"),
    ("ult_damage_total", "summed max damage across the team's damage ultimates"),
    ("dmg_ults", "ultimates that carry a damage figure"),
    ("ult_cost_mean", "mean ultimate charge cost where published"),
    ("hitscan", "picks with a hitscan weapon or ability"),
    ("hitscan_reach", "hitscan picks whose weapon publishes a reach of %g m or more"
                      % FLIER_REACH),
    ("projectile", "picks whose weapons are projectile"),
    ("beam", "picks with a damaging beam"), ("melee", "picks with a melee weapon"),
    ("aoe_count", "kit pieces tagged area of effect or shockwave"),
    ("aoe_damage", "kit pieces that damage an area"),
    ("range_median", "median of each pick's longest published range"),
    ("range_max", "the longest range on the team"), ("range_min", "the shortest longest-range"),
    ("dmg_amp", "picks that amplify someone's damage"),
    # sustain
    ("hps_floor", "summed sustained healing onto teammates, hp per second, reloads in"),
    ("heal_peak_total", "summed biggest single heal per pick, its own self-heal included"),
    ("heal_peak_supports", "summed biggest single heal (one cast, hp) across the supports"),
    ("heal_peak_max", "the biggest single heal a teammate can receive"),
    ("heal_ratio", "support heal peak / the roster's two-support bench"),
    ("hps_supports", "summed sustained healing across the supports, hp per second"),
    ("hps_ratio", "support sustained healing / the roster's two-support bench"),
    ("heal_amp", "picks that amplify healing"), ("antiheal", "picks with anti-heal"),
    ("cleanse", "picks with a cleanse"),
    ("invuln", "picks with an invulnerability or a death-prevention"),
    ("team_cleanse", "picks with a cleanse that lands on a teammate"),
    ("team_saves", "picks with an invulnerability, death-prevention or cleanse that lands"
                   " on a teammate"),
    ("lifelines", "picks carrying any healing at all, their own and lifesteal included"),
    # tempo and tools
    ("cooldown_median", "median cooldown across every ability on the team"),
    ("cooldown_count", "cooldowns counted"),
    ("cc_count", "picks with crowd control (stun, sleep, immobilize, hinder, knockback)"),
    ("mobility_count", "picks with a movement or evasive ability"),
    ("flyers", "picks that fly or hover"),
    ("light_flyers", "picks that fly or hover, tanks aside"),
    ("barrier_hp", "summed barrier health the team fields"),
    ("barrier_count", "picks with a barrier"),
    ("barrier_piercers", "picks whose kit ignores barriers"),
    ("pierce_dps", "summed damage of the picks whose kit ignores barriers"),
    ("deployables", "picks with deployables"),
    # cohesion
    ("synergy_edges", "the wiki's synergy pairs among the picks"),
    ("synergy_score", "summed synergy scores among the picks"),
    ("synergy_density", "synergy edges / possible pairs"),
    ("isolated_count", "picks with a documented partner somewhere and none on the team"),
    ("isolated", "the isolated picks"),
    ("core_size", "largest connected group in the team's synergy graph"),
    ("pairs", "the synergy pairs present"),
    # meta
    ("win_mean", "mean all-ranks win rate"),
    ("pick_mass", "summed all-ranks pick rate"),
    ("availability", "chance every pick survives the ban screen: product of (1 - ban)"),
    ("map_availability", "the same from this map's ban rates (the all-ranks ban where a map"
                         " publishes none; equal to availability without a map)"),
    ("max_ban_rate", "the highest ban rate on the team"),
    ("max_ban_hero", "who carries the highest ban rate"),
    ("rank_sensitive_count",
        "picks whose win rate swings %g+ points across ranks" % RANK_SENSITIVE),
    ("trend_sum", "summed win-rate movement since the rates last changed"),
    # map
    ("map_known", "1 if a map is set"),
    ("map_win_mean", "mean win rate on the map (the all-ranks mean without a map)"),
    ("map_pick_mass", "summed pick rate on the map"),
    ("map_specialists", "picks running %g+ points over their own baseline here" % SPECIALIST_DELTA),
    ("map_offmap", "picks running %g+ points under their own baseline here" % SPECIALIST_DELTA),
    ("map_strategy_hits", "picks whose three best maps by rate include this map"),
    # versus the other team (all 0 when the other team is empty)
    ("coverage", "enemies answered by at least one pick"),
    ("coverage_share", "coverage / enemies revealed"),
    ("unanswered", "enemies no pick answers"),
    ("answer_edges", "(enemy, pick) counter edges: picks answering enemies"),
    ("exposure_edges", "(pick, enemy) counter edges: enemies answering picks"),
    ("exposed_count", "picks answered by at least one enemy"),
    ("exposed", "the exposed picks"),
    ("safe_count", "picks no enemy answers"),
    ("net_edges", "answer edges minus exposure edges"),
    ("double_covered", "enemies answered by two or more picks"),
    ("banproof_coverage", "coverage recomputed without the highest-ban answerer"),
])


# A metric's value: a count or a figure, a name, the names it lists, the
# synergy pairs (two names and the pair's score), the picks per style tag, or
# the answering picks per enemy. The registry test pins which key holds which.
MetricValue = (
    int | float | str | list[str] | list[tuple[str, str, int]] | dict[str, int]
    | dict[str, list[str]])
MetricBag = dict[str, MetricValue]


def number(value: MetricValue) -> float:
    """A metric read as a number, an int staying an int. The catalog keeps
    the text metrics out of every place a number is read, so a name or a
    list here is a caller's error."""
    if isinstance(value, int | float):
        return value
    raise TypeError("a metric read as a number holds %r" % (value,))


def numbers(bag: MetricBag) -> dict[str, float]:
    """The bag's numeric metrics, each the value itself: what a reader that
    words many of them reads them from."""
    return {k: v for k, v in bag.items() if isinstance(v, int | float)}


def text(value: MetricValue) -> str:
    """A metric read as a name: a playstyle, a hero."""
    if isinstance(value, str):
        return value
    raise TypeError("a metric read as a name holds %r" % (value,))


def names(value: MetricValue) -> list[str]:
    """A metric read as the names it lists: the subroles, the squishies."""
    if isinstance(value, list):
        listed = [x for x in value if isinstance(x, str)]
        if len(listed) == len(value):
            return listed
    raise TypeError("a metric read as names holds %r" % (value,))


def synergy_pairs(value: MetricValue) -> list[tuple[str, str, int]]:
    """team.pairs: each synergy pair as two names and the pair's score."""
    if isinstance(value, list):
        pairs = [x for x in value if isinstance(x, tuple)]
        if len(pairs) == len(value):
            return pairs
    raise TypeError("a metric read as synergy pairs holds %r" % (value,))


def style_tally(value: MetricValue) -> dict[str, int]:
    """team.style_counts: the picks per playstyle tag."""
    if isinstance(value, dict):
        tally = {k: v for k, v in value.items() if isinstance(v, int)}
        if len(tally) == len(value):
            return tally
    raise TypeError("a metric read as a style tally holds %r" % (value,))


def answers(value: MetricValue) -> dict[str, list[str]]:
    """_answered: the picks answering each enemy, by the enemy's name."""
    if isinstance(value, dict):
        by_enemy = {k: v for k, v in value.items() if isinstance(v, list)}
        if len(by_enemy) == len(value):
            return by_enemy
    raise TypeError("a metric read as answers holds %r" % (value,))


def _median(values: Iterable[float | None]) -> float:
    known = [v for v in values if v is not None]
    return statistics.median(known) if known else 0.0


def _mean(values: Iterable[float | None]) -> float:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else 0.0


def team_metrics(world: World, heroes: Iterable[Hero], m: Map | None = None,
                 enemies: Iterable[Hero] = (), lean: bool = False) -> MetricBag:
    """Every TEAM_METRICS key for these picks, on this map, vs these enemies,
    and _answered, the answering picks per enemy that the facts engine words.
    lean=True leaves _answered empty: no strategy can name it, so the solver
    never reads it. Each section's helper returns its keys in registry order,
    and the bag keeps that order."""
    heroes, enemies = list(heroes), list(enemies)
    # the most-banned pick: max_ban_* name it and banproof_coverage takes its
    # answers away; with no ban rate on the team it is the first pick
    top_ban = max(heroes, key=lambda h: h.ban or 0) if heroes else None
    meta = _meta(heroes, m, top_ban)
    return {**_shape(heroes, m), **_durability(heroes), **_damage(heroes),
            **_sustain(world, heroes), **_tools(heroes), **_cohesion(world, heroes),
            **meta, **_on_map(heroes, m, meta["win_mean"], meta["pick_mass"]),
            **_versus(world, heroes, enemies, top_ban, lean)}


def _shape(heroes: list[Hero], m: Map | None) -> MetricBag:
    """The picks, their roles and subroles, and the playstyles they carry."""
    n = len(heroes)
    roles = Counter(h.role for h in heroes)
    tanks, damage, supports = roles["tank"], roles["damage"], roles["support"]
    subroles = sorted({h.subrole for h in heroes})
    counts = Counter(s for h in heroes for s in h.styles)
    majority = [s for s, c in counts.items() if c > n / 2.0]
    # ties fall to the alphabetically first style: the answer must not depend on
    # the order a set of names happens to iterate in (hash randomisation)
    # and a six that is as much one style as another plays the one the map rewards
    map_style = m.style_top if m is not None else None
    return {"size": n, "open_slots": max(0, TEAM_SIZE - n),
            "tanks": tanks, "damage": damage, "supports": supports,
            "subroles": subroles, "subrole_diversity": len(subroles) / n if n else 0.0,
            "shape_flags": _shape_flags(tanks, damage, supports) if n else [],
            "style_counts": dict(counts),
            "style_top": sorted(counts, key=lambda s: (-counts[s], s))[0] if counts else "",
            "style_lean": (sorted(majority, key=lambda s: (-counts[s], s != map_style, s))[0]
                           if majority else ""),
            "style_fit": (sum(1 for h in heroes if map_style in h.styles) / n
                          if n and map_style else 0.0),
            "archetype_deviation": (
                sum(max(0, roles[r] - slots) for r, slots in EXPECTED_SHAPE.items())
                if map_style else 0)}


def _shape_flags(tanks: int, damage: int, supports: int) -> list[str]:
    """The warnings a shape carries, in the order the facts word them."""
    flags = []
    if tanks == 0:
        flags.append("TANKLESS")
    if tanks >= 2:
        flags.append("double tank")
    if damage >= 3:
        flags.append("triple DPS")
    if supports == 0:
        flags.append("NO SUPPORT")
    elif supports == 1:
        flags.append("solo heal")
    return flags


def _durability(heroes: list[Hero]) -> MetricBag:
    """The pools, the armor and shields in them, and the picks focus fire finds."""
    pools = [h.pool for h in heroes]
    pool_total = sum(pools) + sum(h.form_armor for h in heroes)
    armor_total = sum(h.armor + h.form_armor for h in heroes)
    shield_total = sum(h.shield for h in heroes)
    squishies = [h.name for h in heroes if h.pool <= SQUISHY_POOL]
    return {"pool_total": pool_total, "pool_min": min(pools) if pools else 0,
            "weakest": min(heroes, key=lambda h: h.pool).name if heroes else "",
            "armor_total": armor_total,
            "armor_share": armor_total / pool_total if pool_total else 0.0,
            "shield_total": shield_total,
            "shield_share": shield_total / pool_total if pool_total else 0.0,
            "squish_count": len(squishies), "squishies": squishies,
            "overhealth_total": sum(h.overhealth for h in heroes)}


def _damage(heroes: list[Hero]) -> MetricBag:
    """Sustained and burst damage, the ultimates, the weapon kinds and the reach."""
    burst = max(heroes, key=lambda h: h.burst) if heroes else None
    ranges = [h.max_range for h in heroes if h.max_range]
    return {"dps_floor": sum(h.dps for h in heroes),
            "dps_count": sum(1 for h in heroes if h.dps),
            "burst_max": burst.burst if burst else 0.0,
            "one_shots": sum(1 for h in heroes if h.burst >= SQUISHY_POOL and not h.melee),
            "burst_hero": burst.name if burst else "",
            "burst_ranged": max([h.burst for h in heroes if not h.melee_only] or [0.0]),
            "ult_damage_total": sum(h.ult_damage for h in heroes),
            "dmg_ults": sum(1 for h in heroes if h.dmg_ult),
            "ult_cost_mean": _mean([h.ult_cost for h in heroes]),
            "hitscan": sum(1 for h in heroes if h.hitscan),
            "hitscan_reach": sum(1 for h in heroes if h.hitscan_range >= FLIER_REACH),
            "projectile": sum(1 for h in heroes if "projectile" in h.weapon_kinds),
            "beam": sum(1 for h in heroes if h.beam),
            "melee": sum(1 for h in heroes if h.melee),
            "aoe_count": sum(h.aoe_count for h in heroes),
            "aoe_damage": sum(h.aoe_damage for h in heroes),
            "range_median": _median(ranges),
            "range_max": max(ranges) if ranges else 0.0,
            "range_min": min(ranges) if ranges else 0.0,
            "dmg_amp": sum(1 for h in heroes if h.dmg_amp)}


def _sustain(world: World, heroes: list[Hero]) -> MetricBag:
    """Healing onto teammates against the roster's bench, and the saves."""
    supports = [h for h in heroes if h.role == "support"]
    heal_peak_supports = sum(h.peak_heal for h in supports)
    hps_supports = sum(h.hps for h in supports)
    return {"hps_floor": sum(h.hps for h in heroes),
            "heal_peak_total": sum(max(h.peak_heal, h.self_heal) for h in heroes),
            "heal_peak_supports": heal_peak_supports,
            "heal_peak_max": max([h.peak_heal for h in heroes] or [0.0]),
            "heal_ratio": (heal_peak_supports / world.heal_bench
                           if world.heal_bench else 0.0),
            "hps_supports": hps_supports,
            "hps_ratio": hps_supports / world.hps_bench if world.hps_bench else 0.0,
            "heal_amp": sum(1 for h in heroes if h.heal_amp),
            "antiheal": sum(1 for h in heroes if h.antiheal < 0),
            "cleanse": sum(1 for h in heroes if h.cleanse_tools),
            "invuln": sum(1 for h in heroes if h.invuln_tools),
            "team_cleanse": sum(1 for h in heroes if h.team_cleanse_tools),
            "team_saves": sum(1 for h in heroes if h.save_tools),
            "lifelines": sum(1 for h in heroes if h.peak_heal or h.hps or h.self_heal
                             or h.self_hps or h.lifesteal)}


def _tools(heroes: list[Hero]) -> MetricBag:
    """The cooldowns' tempo, crowd control, movement, fliers, barriers and
    deployables."""
    cooldowns = [c for h in heroes for c in h.cooldowns]
    return {"cooldown_median": _median(cooldowns), "cooldown_count": len(cooldowns),
            "cc_count": sum(1 for h in heroes if h.cc_tools),
            "mobility_count": sum(1 for h in heroes if h.mobility_tools),
            "flyers": sum(1 for h in heroes if h.flyer),
            "light_flyers": sum(1 for h in heroes if h.flyer and h.role != "tank"),
            "barrier_hp": sum(h.barrier_hp for h in heroes),
            "barrier_count": sum(1 for h in heroes if h.barrier_hp),
            "barrier_piercers": sum(1 for h in heroes if h.pierces_barrier),
            # what the piercing is worth, not how many carry it: a flail that swings
            # past a barrier and a beam that burns through one are one pick each by count
            "pierce_dps": sum(h.dps for h in heroes if h.pierces_barrier),
            "deployables": sum(1 for h in heroes if h.deployables)}


def _cohesion(world: World, heroes: list[Hero]) -> MetricBag:
    """The wiki's synergy pairs among the picks, and the graph they make."""
    n = len(heroes)
    pairs: list[tuple[str, str, int]] = []
    adjacency: dict[int, set[int]] = {h.id: set() for h in heroes}
    for i, a in enumerate(heroes):
        for b in heroes[i + 1:]:
            edge = world.synergy(a.id, b.id)
            if edge:
                pairs.append((a.name, b.name, edge[0] or 0))
                adjacency[a.id].add(b.id)
                adjacency[b.id].add(a.id)
    possible = n * (n - 1) // 2
    # a hero the wiki pairs with no one at all is unknown, not alone: unknown is not a number
    isolated = [h.name for h in heroes
                if n >= 2 and not adjacency[h.id] and world.partners.get(h.id)]
    return {"synergy_edges": len(pairs), "synergy_score": sum(p[2] for p in pairs),
            "synergy_density": len(pairs) / possible if possible else 0.0,
            "isolated_count": len(isolated), "isolated": isolated,
            "core_size": _largest_component(adjacency), "pairs": pairs}


def _meta(heroes: list[Hero], m: Map | None, top_ban: Hero | None) -> MetricBag:
    """The meta's rates, the ban screen and the rates' movement."""
    avail = 1.0
    for h in heroes:
        avail *= 1.0 - (h.ban or 0) / 100.0
    map_avail = 1.0
    for h in heroes:
        ban = h.map_ban(m.id) if m is not None else None
        rate = h.ban if ban is None else ban            # this map's ban, else all-ranks
        map_avail *= 1.0 - (rate or 0) / 100.0
    return {"win_mean": _mean([h.win for h in heroes]),
            "pick_mass": sum(h.pick or 0 for h in heroes),
            "availability": avail, "map_availability": map_avail,
            "max_ban_rate": (top_ban.ban or 0) if top_ban else 0.0,
            "max_ban_hero": top_ban.name if top_ban and top_ban.ban else "",
            "rank_sensitive_count": sum(1 for h in heroes if h.rank_spread >= RANK_SENSITIVE),
            "trend_sum": sum(h.trend for h in heroes if h.trend is not None)}


def _on_map(heroes: list[Hero], m: Map | None, win_mean: MetricValue,
            pick_mass: MetricValue) -> MetricBag:
    """The picks on this map's rates; without a map, the all-ranks figures the
    meta section read, and zeros."""
    if m is None:
        return {"map_known": 0, "map_win_mean": win_mean, "map_pick_mass": pick_mass,
                "map_specialists": 0, "map_offmap": 0, "map_strategy_hits": 0}
    wins = [h.map_win(m.id) for h in heroes]
    deltas = [
        win - h.win for h, win in zip(heroes, wins, strict=True)
        if win is not None and h.win is not None]
    return {"map_known": 1,
            "map_win_mean": _mean(wins) if any(w is not None for w in wins) else win_mean,
            "map_pick_mass": sum(h.map_pick(m.id) or 0 for h in heroes),
            "map_specialists": sum(1 for d in deltas if d >= SPECIALIST_DELTA),
            "map_offmap": sum(1 for d in deltas if d <= -SPECIALIST_DELTA),
            "map_strategy_hits": sum(1 for h in heroes if m.id in h.best_maps)}


def _versus(world: World, heroes: list[Hero], enemies: list[Hero], top_ban: Hero | None,
            lean: bool) -> MetricBag:
    """The counter edges between the picks and the other team: all zeros while
    that team is empty."""
    # enemy id -> the picks answering it; pick id -> the enemies answering it
    answered = {e.id: [h.name for h in heroes if world.counters_of(e.id, h.id)]
                for e in enemies}
    exposure = {h.id: [e.name for e in enemies if world.counters_of(h.id, e.id)]
                for h in heroes}
    covered = [e for e in enemies if answered[e.id]]
    exposed = [h.name for h in heroes if exposure[h.id]]
    answer_edges = sum(len(v) for v in answered.values())
    exposure_edges = sum(len(v) for v in exposure.values())
    return {"coverage": len(covered),
            "coverage_share": len(covered) / len(enemies) if enemies else 0.0,
            "unanswered": [e.name for e in enemies if not answered[e.id]],
            "answer_edges": answer_edges, "exposure_edges": exposure_edges,
            "exposed_count": len(exposed), "exposed": exposed,
            "safe_count": len(heroes) - len(exposed) if enemies else 0,
            "net_edges": answer_edges - exposure_edges,
            "double_covered": sum(1 for v in answered.values() if len(v) >= 2),
            "banproof_coverage": (
                sum(1 for e in enemies if any(x != top_ban.name for x in answered[e.id]))
                if enemies and top_ban is not None else 0),
            "_answered": {} if lean else {e.name: answered[e.id] for e in enemies}}


def _largest_component(adjacency: dict[int, set[int]]) -> int:
    """The size of the largest connected group in a graph of hero ids."""
    seen: set[int] = set()
    best = 0
    for start in adjacency:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            node = stack.pop()
            size += 1
            for other in adjacency[node]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        best = max(best, size)
    return best
