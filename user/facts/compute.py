"""The metrics: pure functions over a World.

Every number the board shows as a joint fact and every number a heuristic
can reference is computed here, once, in one place - the facts engine
renders these into sentences and the inference layer's solver scores
candidate compositions with the same functions. The registries below
(TEAM_METRICS, MATCHUP_METRICS, MAP_METRICS, WORLD_METRICS) are the
vocabulary a heuristic's frontmatter may use: `team.<key>`,
`enemy.<key>` (the other side's team metrics), `matchup.<key>`,
`map.<key>`, `world.<key>`.

Unknowns are numeric, never None: a metric that needs a map reads 0 (or
falls back to the roster-wide figure where that is the honest substitute,
which the description says) and `map.known` tells a heuristic which.
"""

import statistics
from collections import Counter, OrderedDict

from user.facts.model import ROLES, SQUISHY_POOL

SPECIALIST_DELTA = 2.5
RANK_SENSITIVE = 6.0
TREND_POINTS = 1.5

TEAM_METRICS = OrderedDict([
    # shape
    ("size", "picks locked on this team"),
    ("open_slots", "slots still open (5 - size)"),
    ("tanks", "tank count"), ("damage", "damage count"), ("supports", "support count"),
    ("subrole_diversity", "distinct subroles / size (1.0 = every pick a different job)"),
    ("subroles", "the subroles present"),
    ("shape_flags", "TANKLESS / double tank / triple DPS / NO SUPPORT / solo heal"),
    ("style_counts", "picks per playstyle tag (a hero can carry several)"),
    ("style_top", "the modal playstyle among the picks"),
    ("style_lean", "the playstyle a strict majority of picks carry, else none"),
    ("style_fit", "share of picks tagged with the map's rewarded style (0 without a map)"),
    ("archetype_deviation", "picks over the map's top-style archetype role slots (0 without a map)"),
    # durability
    ("pool_total", "team effective HP: sum of health + shield + armor"),
    ("pool_min", "the weakest pick's pool - focus fire finds the minimum"),
    ("weakest", "who holds the smallest pool"),
    ("armor_total", "summed armor"), ("armor_share", "armor / pool"),
    ("shield_total", "summed recharging shields"), ("shield_share", "shields / pool"),
    ("squish_count", "picks at or under %d pool" % SQUISHY_POOL),
    ("squishies", "the picks at or under %d pool" % SQUISHY_POOL),
    ("overhealth_total", "summed peak overhealth a kit can grant"),
    # damage
    ("dps_floor", "summed published per-second damage figures (a floor: misses and healing ignored)"),
    ("dps_count", "picks whose kit publishes a per-second damage figure"),
    ("burst_max", "the biggest single damage figure on the team"),
    ("burst_hero", "who holds the biggest single hit"),
    ("ult_damage_total", "summed max damage across the team's damage ultimates"),
    ("dmg_ults", "ultimates that carry a damage figure"),
    ("ult_cost_mean", "mean ultimate charge cost where published"),
    ("hitscan", "picks with a hitscan weapon or ability"),
    ("projectile", "picks whose weapons are projectile"),
    ("beam", "picks with a beam"), ("melee", "picks with a melee weapon"),
    ("aoe_count", "kit pieces tagged area of effect"),
    ("range_median", "median of each pick's longest published range"),
    ("range_max", "the longest range on the team"), ("range_min", "the shortest longest-range"),
    ("dmg_amp", "picks that amplify someone's damage"),
    # sustain
    ("hps_floor", "summed published per-second healing figures"),
    ("heal_peak_total", "summed peak single heal across all picks, any role"),
    ("heal_peak_supports", "summed peak single heal across the supports"),
    ("heal_peak_max", "the biggest single heal on the team"),
    ("heal_ratio", "support heal peak / the roster's two-support bench"),
    ("heal_amp", "picks that amplify healing"), ("antiheal", "picks with anti-heal"),
    ("cleanse", "picks with a cleanse"), ("invuln", "picks with an invulnerability"),
    ("lifelines", "picks carrying any healing at all"),
    # tempo and tools
    ("cooldown_median", "median cooldown across every ability on the team"),
    ("cooldown_count", "cooldowns counted"),
    ("cc_count", "picks with crowd control (stun, sleep, immobilize, hinder, knockback)"),
    ("cc_tools", "the crowd-control tools"),
    ("mobility_count", "picks with a movement or evasive ability"),
    ("mobility_tools", "the movement tools"),
    ("flyers", "picks that fly or hover"),
    ("barrier_hp", "summed barrier health the team fields"),
    ("barrier_count", "picks with a barrier"),
    ("barrier_piercers", "picks whose kit ignores barriers"),
    ("deployables", "picks with deployables"),
    # cohesion
    ("synergy_edges", "authored synergy pairs among the picks"),
    ("synergy_score", "summed synergy scores among the picks"),
    ("synergy_density", "synergy edges / possible pairs"),
    ("isolated_count", "picks with no authored partner on the team"),
    ("isolated", "the isolated picks"),
    ("core_size", "largest connected group in the team's synergy graph"),
    ("pairs", "the synergy pairs present"),
    # meta
    ("win_mean", "mean all-ranks win rate"),
    ("pick_mass", "summed all-ranks pick rate"),
    ("availability", "chance every pick survives the ban screen: product of (1 - ban)"),
    ("max_ban_rate", "the highest ban rate on the team"),
    ("max_ban_hero", "who carries the highest ban rate"),
    ("rank_sensitive_count", "picks whose win rate swings %g+ points across ranks" % RANK_SENSITIVE),
    ("trend_sum", "summed win-rate movement since the previous snapshot"),
    # map
    ("map_known", "1 if a map is set"),
    ("map_win_mean", "mean win rate on the map (the all-ranks mean without a map)"),
    ("map_pick_mass", "summed pick rate on the map"),
    ("map_specialists", "picks running %g+ points over their own baseline here" % SPECIALIST_DELTA),
    ("map_offmap", "picks running %g+ points under their own baseline here" % SPECIALIST_DELTA),
    ("map_strategy_hits", "picks the playbook lists among their best maps here"),
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

MATCHUP_METRICS = OrderedDict([
    ("pool_diff", "blue effective HP minus red"),
    ("dps_diff", "blue damage floor minus red"),
    ("hps_diff", "blue healing floor minus red"),
    ("burst_vs_heal", "blue's biggest hit minus red's biggest single save"),
    ("heal_vs_burst", "blue's biggest single save minus red's biggest hit"),
    ("chew_time_ours", "seconds of blue's floor damage to chew red's pool (999 if unknown)"),
    ("chew_time_theirs", "seconds of red's floor damage to chew blue's pool"),
    ("tempo_diff", "red median cooldown minus blue's (positive: blue cycles faster)"),
    ("range_diff", "blue median reach minus red's"),
    ("net_edges", "blue answer edges minus blue exposure edges"),
    ("coverage_share", "share of red answered by blue"),
    ("exposure_share", "share of blue answered by red"),
    ("double_covered", "red picks answered twice over"),
    ("dive_pressure", "red picks with a movement tool"),
    ("flyers", "red picks that fly"),
    ("barrier_need", "barrier health red fields"),
    ("antiheal_need", "red supports' summed peak heal"),
    ("ult_threat", "red's summed damage-ultimate ceiling"),
    ("ult_answers", "blue invulnerabilities plus cleanses"),
    ("style_lean_red", "red's majority playstyle, else none"),
    ("style_lean_blue", "blue's majority playstyle, else none"),
])

MAP_METRICS = OrderedDict([
    ("known", "1 if a map is set"),
    ("style_top", "the playstyle the map rewards most"),
    ("style_margin", "top style score minus the runner-up"),
    ("mode", "the game mode"),
    ("stages", "stage count"),
])

WORLD_METRICS = OrderedDict([
    ("heal_bench", "2 x the median peak heal across the support roster"),
    ("roster_size", "heroes in the roster"),
])


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else 0.0


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def team_metrics(world, heroes, m=None, enemies=()):
    """Every TEAM_METRICS key for these picks, on this map, vs these enemies."""
    heroes = list(heroes)
    n = len(heroes)
    t = {}
    t["size"], t["open_slots"] = n, max(0, 5 - n)
    for role in ROLES:
        t[{"tank": "tanks", "damage": "damage", "support": "supports"}[role]] = \
            sum(1 for h in heroes if h.role == role)
    subs = sorted({h.subrole for h in heroes})
    t["subroles"] = subs
    t["subrole_diversity"] = len(subs) / n if n else 0.0
    flags = []
    if n:
        if t["tanks"] == 0:
            flags.append("TANKLESS")
        if t["tanks"] >= 2:
            flags.append("double tank")
        if t["damage"] >= 3:
            flags.append("triple DPS")
        if t["supports"] == 0:
            flags.append("NO SUPPORT")
        elif t["supports"] == 1:
            flags.append("solo heal")
    t["shape_flags"] = flags
    counts = Counter(s for h in heroes for s in h.styles)
    t["style_counts"] = dict(counts)
    t["style_top"] = counts.most_common(1)[0][0] if counts else ""
    lean = [s for s, c in counts.items() if c > n / 2.0]
    t["style_lean"] = sorted(lean, key=lambda s: -counts[s])[0] if lean else ""
    map_style = m.style_top if m is not None else None
    t["style_fit"] = (sum(1 for h in heroes if map_style in h.styles) / n
                      if n and map_style else 0.0)
    dev = 0
    if map_style and map_style in world.archetypes:
        for role, (slots, _) in world.archetypes[map_style].items():
            key = {"tank": "tanks", "damage": "damage", "support": "supports"}[role]
            dev += max(0, t[key] - slots)
    t["archetype_deviation"] = dev

    pools = [h.pool for h in heroes]
    t["pool_total"] = sum(pools)
    t["pool_min"] = min(pools) if pools else 0
    t["weakest"] = min(heroes, key=lambda h: h.pool).name if heroes else ""
    t["armor_total"] = sum(h.armor for h in heroes)
    t["armor_share"] = t["armor_total"] / t["pool_total"] if t["pool_total"] else 0.0
    t["shield_total"] = sum(h.shield for h in heroes)
    t["shield_share"] = t["shield_total"] / t["pool_total"] if t["pool_total"] else 0.0
    squishies = [h.name for h in heroes if h.pool <= SQUISHY_POOL]
    t["squish_count"], t["squishies"] = len(squishies), squishies
    t["overhealth_total"] = sum(h.overhealth for h in heroes)

    t["dps_floor"] = sum(h.dps for h in heroes)
    t["dps_count"] = sum(1 for h in heroes if h.dps)
    burst = max(heroes, key=lambda h: h.burst) if heroes else None
    t["burst_max"] = burst.burst if burst else 0.0
    t["burst_hero"] = burst.name if burst else ""
    t["ult_damage_total"] = sum(h.ult_damage for h in heroes)
    t["dmg_ults"] = sum(1 for h in heroes if h.dmg_ult)
    t["ult_cost_mean"] = _mean([h.ult_cost for h in heroes])
    t["hitscan"] = sum(1 for h in heroes if h.hitscan)
    t["projectile"] = sum(1 for h in heroes if "projectile" in h.weapon_kinds)
    t["beam"] = sum(1 for h in heroes if h.beam)
    t["melee"] = sum(1 for h in heroes if h.melee)
    t["aoe_count"] = sum(h.aoe_count for h in heroes)
    ranges = [h.max_range for h in heroes if h.max_range]
    t["range_median"] = _median(ranges)
    t["range_max"] = max(ranges) if ranges else 0.0
    t["range_min"] = min(ranges) if ranges else 0.0
    t["dmg_amp"] = sum(1 for h in heroes if h.dmg_amp)

    supports = [h for h in heroes if h.role == "support"]
    t["hps_floor"] = sum(h.hps for h in heroes)
    t["heal_peak_total"] = sum(h.peak_heal for h in heroes)
    t["heal_peak_supports"] = sum(h.peak_heal for h in supports)
    t["heal_peak_max"] = max([h.peak_heal for h in heroes] or [0.0])
    t["heal_ratio"] = (t["heal_peak_supports"] / world.heal_bench
                       if world.heal_bench else 0.0)
    t["heal_amp"] = sum(1 for h in heroes if h.heal_amp)
    t["antiheal"] = sum(1 for h in heroes if h.antiheal < 0)
    t["cleanse"] = sum(1 for h in heroes if h.cleanse_tools)
    t["invuln"] = sum(1 for h in heroes if h.invuln_tools)
    t["lifelines"] = sum(1 for h in heroes if h.peak_heal)

    cds = [c for h in heroes for c in h.cooldowns]
    t["cooldown_median"] = _median(cds)
    t["cooldown_count"] = len(cds)
    t["cc_count"] = sum(1 for h in heroes if h.cc_tools)
    t["cc_tools"] = ["%s: %s" % (h.name, ", ".join(h.cc_tools)) for h in heroes if h.cc_tools]
    t["mobility_count"] = sum(1 for h in heroes if h.mobility_tools)
    t["mobility_tools"] = ["%s: %s" % (h.name, ", ".join(h.mobility_tools))
                           for h in heroes if h.mobility_tools]
    t["flyers"] = sum(1 for h in heroes if h.flyer)
    t["barrier_hp"] = sum(h.barrier_hp for h in heroes)
    t["barrier_count"] = sum(1 for h in heroes if h.barrier_hp)
    t["barrier_piercers"] = sum(1 for h in heroes if h.pierces_barrier)
    t["deployables"] = sum(1 for h in heroes if h.deployables)

    pairs, adjacency = [], {h.id: set() for h in heroes}
    for i, a in enumerate(heroes):
        for b in heroes[i + 1:]:
            edge = world.synergy(a.id, b.id)
            if edge:
                pairs.append((a.name, b.name, edge[0] or 0))
                adjacency[a.id].add(b.id)
                adjacency[b.id].add(a.id)
    possible = n * (n - 1) // 2
    t["synergy_edges"] = len(pairs)
    t["synergy_score"] = sum(p[2] for p in pairs)
    t["synergy_density"] = len(pairs) / possible if possible else 0.0
    isolated = [h.name for h in heroes if n >= 2 and not adjacency[h.id]]
    t["isolated_count"], t["isolated"] = len(isolated), isolated
    t["core_size"] = _largest_component(adjacency)
    t["pairs"] = pairs

    t["win_mean"] = _mean([h.win for h in heroes])
    t["pick_mass"] = sum(h.pick or 0 for h in heroes)
    avail = 1.0
    for h in heroes:
        avail *= 1.0 - (h.ban or 0) / 100.0
    t["availability"] = avail
    banned = max(heroes, key=lambda h: h.ban or 0) if heroes else None
    t["max_ban_rate"] = (banned.ban or 0) if banned else 0.0
    t["max_ban_hero"] = banned.name if banned and banned.ban else ""
    t["rank_sensitive_count"] = sum(1 for h in heroes if h.rank_spread >= RANK_SENSITIVE)
    t["trend_sum"] = sum(h.trend for h in heroes if h.trend is not None)

    t["map_known"] = 1 if m is not None else 0
    if m is not None:
        wins = [h.map_win(m.id) for h in heroes]
        t["map_win_mean"] = _mean(wins) if any(w is not None for w in wins) \
            else t["win_mean"]
        t["map_pick_mass"] = sum(h.map_pick(m.id) or 0 for h in heroes)
        deltas = [(h.map_win(m.id) - h.win) for h in heroes
                  if h.map_win(m.id) is not None and h.win is not None]
        t["map_specialists"] = sum(1 for d in deltas if d >= SPECIALIST_DELTA)
        t["map_offmap"] = sum(1 for d in deltas if d <= -SPECIALIST_DELTA)
        t["map_strategy_hits"] = sum(1 for h in heroes if m.id in h.best_maps)
    else:
        t["map_win_mean"] = t["win_mean"]
        t["map_pick_mass"] = t["pick_mass"]
        t["map_specialists"] = t["map_offmap"] = t["map_strategy_hits"] = 0

    enemies = list(enemies)
    answered = {}                     # enemy id -> [answering pick names]
    exposure = {}                     # pick id -> [enemy names answering it]
    for e in enemies:
        answered[e.id] = [h.name for h in heroes if world.counters_of(e.id, h.id)]
    for h in heroes:
        exposure[h.id] = [e.name for e in enemies if world.counters_of(h.id, e.id)]
    covered = [e for e in enemies if answered[e.id]]
    t["coverage"] = len(covered)
    t["coverage_share"] = len(covered) / len(enemies) if enemies else 0.0
    t["unanswered"] = [e.name for e in enemies if not answered[e.id]]
    t["answer_edges"] = sum(len(v) for v in answered.values())
    t["exposure_edges"] = sum(len(v) for v in exposure.values())
    exposed = [h.name for h in heroes if exposure[h.id]]
    t["exposed_count"], t["exposed"] = len(exposed), exposed
    t["safe_count"] = n - len(exposed) if enemies else 0
    t["net_edges"] = t["answer_edges"] - t["exposure_edges"]
    t["double_covered"] = sum(1 for v in answered.values() if len(v) >= 2)
    if enemies and heroes:
        risky = max(heroes, key=lambda h: h.ban or 0)
        t["banproof_coverage"] = sum(
            1 for e in enemies if any(x != risky.name for x in answered[e.id]))
    else:
        t["banproof_coverage"] = 0
    t["_answered"] = {e.name: answered[e.id] for e in enemies}
    t["_exposure"] = {h.name: exposure[h.id] for h in heroes}
    return t


def _largest_component(adjacency):
    seen, best = set(), 0
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


def matchup_metrics(blue_t, red_t):
    """MATCHUP_METRICS from blue's seat, given both teams' metrics."""
    x = {}
    x["pool_diff"] = blue_t["pool_total"] - red_t["pool_total"]
    x["dps_diff"] = blue_t["dps_floor"] - red_t["dps_floor"]
    x["hps_diff"] = blue_t["hps_floor"] - red_t["hps_floor"]
    x["burst_vs_heal"] = blue_t["burst_max"] - red_t["heal_peak_max"]
    x["heal_vs_burst"] = blue_t["heal_peak_max"] - red_t["burst_max"]
    x["chew_time_ours"] = (red_t["pool_total"] / blue_t["dps_floor"]
                           if blue_t["dps_floor"] and red_t["pool_total"] else 999.0)
    x["chew_time_theirs"] = (blue_t["pool_total"] / red_t["dps_floor"]
                             if red_t["dps_floor"] and blue_t["pool_total"] else 999.0)
    x["tempo_diff"] = red_t["cooldown_median"] - blue_t["cooldown_median"]
    x["range_diff"] = blue_t["range_median"] - red_t["range_median"]
    x["net_edges"] = blue_t["net_edges"]
    x["coverage_share"] = blue_t["coverage_share"]
    x["exposure_share"] = (blue_t["exposed_count"] / blue_t["size"]
                           if blue_t["size"] else 0.0)
    x["double_covered"] = blue_t["double_covered"]
    x["dive_pressure"] = red_t["mobility_count"]
    x["flyers"] = red_t["flyers"]
    x["barrier_need"] = red_t["barrier_hp"]
    x["antiheal_need"] = red_t["heal_peak_supports"]
    x["ult_threat"] = red_t["ult_damage_total"]
    x["ult_answers"] = blue_t["invuln"] + blue_t["cleanse"]
    x["style_lean_red"] = red_t["style_lean"]
    x["style_lean_blue"] = blue_t["style_lean"]
    return x


def map_metrics(m):
    if m is None:
        return {"known": 0, "style_top": "", "style_margin": 0, "mode": "",
                "stages": 0}
    return {"known": 1, "style_top": m.style_top or "",
            "style_margin": m.style_margin, "mode": m.mode or "",
            "stages": len(m.stages)}


def world_metrics(world):
    return {"heal_bench": world.heal_bench, "roster_size": len(world.heroes)}


def namespace(world, m, red, blue):
    """The whole evaluation namespace for a board: {team, enemy, matchup,
    map, world} - `team` is blue's seat, `enemy` is red's."""
    blue_t = team_metrics(world, blue, m, red)
    red_t = team_metrics(world, red, m, blue)
    return {"team": blue_t, "enemy": red_t,
            "matchup": matchup_metrics(blue_t, red_t),
            "map": map_metrics(m), "world": world_metrics(world)}


# Metrics whose value is a name or a list, not a number: a goal may not
# maximize them, but a strategy may compare them ("team.style_lean == 'dive'").
TEXT_METRICS = {
    "team.subroles", "team.shape_flags", "team.style_counts", "team.style_top",
    "team.style_lean", "team.weakest", "team.squishies", "team.burst_hero",
    "team.cc_tools", "team.mobility_tools", "team.isolated", "team.pairs",
    "team.max_ban_hero", "team.unanswered", "team.exposed",
    "matchup.style_lean_red", "matchup.style_lean_blue",
    "map.style_top", "map.mode",
}


def registry():
    """Every dotted key a heuristic may reference -> its description."""
    out = {}
    for prefix, table in (("team", TEAM_METRICS), ("enemy", TEAM_METRICS),
                          ("matchup", MATCHUP_METRICS), ("map", MAP_METRICS),
                          ("world", WORLD_METRICS)):
        for key, description in table.items():
            out["%s.%s" % (prefix, key)] = description
    return out
