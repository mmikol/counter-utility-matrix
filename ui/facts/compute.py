"""The metrics: pure functions over a World.

Every number the board shows as a joint fact and every number a strategy
can reference is computed here, once, in one place - the facts engine
renders these into sentences and the inference layer's solver scores
candidate compositions with the same functions. The registries below
(TEAM_METRICS, MATCHUP_METRICS, MAP_METRICS, WORLD_METRICS) are the
vocabulary a strategy's frontmatter may use: `team.<key>`,
`enemy.<key>` (the other side's team metrics), `matchup.<key>`,
`map.<key>`, `world.<key>`.

Unknowns are numeric, never None: a metric that needs a map reads 0 (or
falls back to the roster-wide figure where that is the honest substitute,
which the description says) and `map.known` tells a strategy which.
"""

import statistics
from collections import Counter, OrderedDict

from ui.facts.model import ROLES, SQUISHY_POOL, TERRAIN_FEATURES

TEAM_SIZE = 6             # 6v6 Open Queue
MAX_BANS = 5              # each team's two and the lobby's
SIDED_MODES = ("Escort", "Hybrid")   # modes with an attacking and a defending side
SIDES = ("attack", "defense")
ROLE_COUNT = {"tank": "tanks", "damage": "damage", "support": "supports"}   # role -> its count key
SPECIALIST_DELTA = 2.5
RANK_SENSITIVE = 6.0
TREND_POINTS = 1.5
TERRAIN_STANDOUT = 0.75   # sd from the ordinary map at which a terrain feature is a fact
STAGE_MENTIONS = 2        # mentions a stage's text must hold of a feature to stand out on it
STAGE_FEATURES = 2        # standout features a stage fact names, largest first
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
    ("cc_tools", "the crowd-control tools"),
    ("mobility_count", "picks with a movement or evasive ability"),
    ("mobility_tools", "the movement tools"),
    ("flyers", "picks that fly or hover"),
    ("light_flyers", "picks that fly or hover, tanks aside"),
    ("barrier_hp", "summed barrier health the team fields"),
    ("barrier_count", "picks with a barrier"),
    ("barrier_piercers", "picks whose kit ignores barriers"),
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
    ("exposure_share", "share of blue answered by red"),
    ("dive_pressure", "red picks with a movement tool"),
    ("flyers", "red picks that fly, tanks aside"),
    ("barrier_need", "barrier health red fields"),
    ("antiheal_need", "red supports' summed peak heal"),
    ("ult_threat", "red's summed damage-ultimate ceiling"),
    ("ult_answers", "blue invulnerabilities plus cleanses"),
    ("style_lean_red", "red's majority playstyle, else none"),
])

MAP_METRICS = OrderedDict([
    ("known", "1 if a map is set"),
    ("sided", "1 if the mode has an attacking and a defending side (Escort, Hybrid)"),
    ("side", "this seat's side on a sided map: attack, defense, or empty"),
    ("style_top", "the playstyle the map rewards most: the rates' lift plus the terrain's lean"),
    ("style_margin", "top style score minus the runner-up, in sd"),
    ("mode", "the game mode"),
    ("stages", "separate arenas, one played at a time: Control's 3, Flashpoint's 5; else 0"),
    ("phases", "named parts of one route, played in order: Hybrid's 2, an Escort map's"
               " named stretches; else 0"),
    ("bans", "bans already made in this match: a ban rate is a risk only before them"),
])
TERRAIN_WORDS = {
    "chokes": "chokepoints, narrow streets, corridors, tunnels, gates and doorways",
    "interiors": "rooms, caves and other indoor ground",
    "high_ground": "high ground, rooftops, balconies and other vertical ground",
    "flanks": "flank routes and side paths",
    "sightlines": "long sightlines",
    "open_ground": "open ground and ground said to lack cover",
    "hazards": "drops, pits and other environmental hazards",
    "cover": "cover",
}
# map.<feature>: one per terrain feature, numeric
MAP_METRICS.update((f, "%s: the wiki article's mentions per thousand words, in sd from the mean of"
                       " the maps with text (0 with no text)" % TERRAIN_WORDS[f])
                   for f in TERRAIN_FEATURES)

WORLD_METRICS = OrderedDict([
    ("heal_bench", "2 x the median peak heal across the released supports"),
    ("hps_bench", "2 x the median sustained healing across the released supports"),
    ("roster_size", "heroes in the roster"),
])


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else 0.0


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


EXPECTED_SHAPE = {"tank": 2, "damage": 2, "support": 2}   # what a lobby fields: two of each
SYNERGY_PULL = 2.0        # pick-rate points a hero gains per synergy partner already on the six


def expected_picks(world, m, revealed=(), bans=(), shape=None):
    """What the other side is likely to field, from the data alone - no
    strategy read: any picks given as revealed first, then slot by slot the
    hero the map's pick rates (the overall meta with no map set) and the
    wiki's synergies make likeliest - a hero's likelihood is its pick rate
    plus SYNERGY_PULL per partner already on the six - into a two-two-two,
    past the bans. Deterministic; the board calls it with nothing revealed,
    so the six is static for the board. Each entry says what it rests on
    -> [{hero, role, rate, locked, why}]."""
    shape = dict(shape or EXPECTED_SHAPE)
    revealed, banned = list(revealed), {h.id for h in bans}
    chosen = list(revealed)
    for h in revealed:
        shape[h.role] = max(0, shape.get(h.role, 0) - 1)
    taken = {h.id for h in revealed} | banned

    def rate(h):
        r = h.map_pick(m.id) if m is not None else None
        return (r if r is not None else h.pick, r is not None)

    def partners(h):
        return [c for c in chosen if world.synergy(c.id, h.id)]

    picked = []
    while any(shape.values()):
        field = [h for h in world.heroes.values()
                 if h.released and h.id not in taken and shape.get(h.role, 0) > 0]
        if not field:
            break
        best = max(field, key=lambda h: ((rate(h)[0] or 0.0) + SYNERGY_PULL * len(partners(h)),
                                         [-ord(c) for c in h.name]))
        value, on_map = rate(best)
        with_ = partners(best)
        if value is None:
            why = "no pick rate on record"
        elif on_map:
            why = "picked in %.1f%% of matches on %s" % (value, m.name)
        else:
            why = "picked in %.1f%% of matches overall%s" % (
                value, " (no rate on this map)" if m is not None else " (no map set)")
        if with_:
            why += "; pairs with " + ", ".join(c.name for c in with_)
        picked.append({"hero": best.name, "role": best.role, "rate": value, "locked": False,
                       "why": why})
        chosen.append(best)
        taken.add(best.id)
        shape[best.role] -= 1
    out = [{"hero": h.name, "role": h.role, "rate": None, "locked": True, "why": "revealed"}
           for h in revealed]
    return out + sorted(picked, key=lambda p: (ROLES.index(p["role"]), p["hero"]))


def team_metrics(world, heroes, m=None, enemies=(), lean=False):
    """Every TEAM_METRICS key for these picks, on this map, vs these enemies.
    lean=True leaves the name lists empty (the solver never reads them)."""
    heroes = list(heroes)
    n = len(heroes)
    t = {}
    t["size"], t["open_slots"] = n, max(0, TEAM_SIZE - n)
    for role in ROLES:
        t[ROLE_COUNT[role]] = sum(1 for h in heroes if h.role == role)
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
    t["style_top"] = sorted(counts, key=lambda s: (-counts[s], s))[0] if counts else ""
    majority = [s for s, c in counts.items() if c > n / 2.0]
    # ties fall to the alphabetically first style: the answer must not depend on
    # the order a set of names happens to iterate in (hash randomisation)
    # and a six that is as much one style as another plays the one the map rewards
    here = m.style_top if m is not None else None
    t["style_lean"] = (sorted(majority, key=lambda s: (-counts[s], s != here, s))[0]
                       if majority else "")
    map_style = m.style_top if m is not None else None
    t["style_fit"] = (sum(1 for h in heroes if map_style in h.styles) / n
                      if n and map_style else 0.0)
    dev = 0
    if map_style:
        for role, slots in EXPECTED_SHAPE.items():
            dev += max(0, t[ROLE_COUNT[role]] - slots)
    t["archetype_deviation"] = dev

    pools = [h.pool for h in heroes]
    t["pool_total"] = sum(pools) + sum(h.form_armor for h in heroes)
    t["pool_min"] = min(pools) if pools else 0
    t["weakest"] = min(heroes, key=lambda h: h.pool).name if heroes else ""
    t["armor_total"] = sum(h.armor + h.form_armor for h in heroes)
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
    t["one_shots"] = sum(1 for h in heroes if h.burst >= SQUISHY_POOL and not h.melee)
    t["burst_hero"] = burst.name if burst else ""
    t["burst_ranged"] = max([h.burst for h in heroes if not h.melee_only] or [0.0])
    t["ult_damage_total"] = sum(h.ult_damage for h in heroes)
    t["dmg_ults"] = sum(1 for h in heroes if h.dmg_ult)
    t["ult_cost_mean"] = _mean([h.ult_cost for h in heroes])
    t["hitscan"] = sum(1 for h in heroes if h.hitscan)
    t["hitscan_reach"] = sum(1 for h in heroes if h.hitscan_range >= FLIER_REACH)
    t["projectile"] = sum(1 for h in heroes if "projectile" in h.weapon_kinds)
    t["beam"] = sum(1 for h in heroes if h.beam)
    t["melee"] = sum(1 for h in heroes if h.melee)
    t["aoe_count"] = sum(h.aoe_count for h in heroes)
    t["aoe_damage"] = sum(h.aoe_damage for h in heroes)
    ranges = [h.max_range for h in heroes if h.max_range]
    t["range_median"] = _median(ranges)
    t["range_max"] = max(ranges) if ranges else 0.0
    t["range_min"] = min(ranges) if ranges else 0.0
    t["dmg_amp"] = sum(1 for h in heroes if h.dmg_amp)

    supports = [h for h in heroes if h.role == "support"]
    t["hps_floor"] = sum(h.hps for h in heroes)
    t["heal_peak_total"] = sum(max(h.peak_heal, h.self_heal) for h in heroes)
    t["heal_peak_supports"] = sum(h.peak_heal for h in supports)
    t["heal_peak_max"] = max([h.peak_heal for h in heroes] or [0.0])
    t["heal_ratio"] = (t["heal_peak_supports"] / world.heal_bench
                       if world.heal_bench else 0.0)
    t["hps_supports"] = sum(h.hps for h in supports)
    t["hps_ratio"] = t["hps_supports"] / world.hps_bench if world.hps_bench else 0.0
    t["heal_amp"] = sum(1 for h in heroes if h.heal_amp)
    t["antiheal"] = sum(1 for h in heroes if h.antiheal < 0)
    t["cleanse"] = sum(1 for h in heroes if h.cleanse_tools)
    t["invuln"] = sum(1 for h in heroes if h.invuln_tools)
    t["team_cleanse"] = sum(1 for h in heroes if h.team_cleanse_tools)
    t["team_saves"] = sum(1 for h in heroes if h.save_tools)
    t["lifelines"] = sum(1 for h in heroes
                         if h.peak_heal or h.hps or h.self_heal or h.self_hps or h.lifesteal)

    cds = [c for h in heroes for c in h.cooldowns]
    t["cooldown_median"] = _median(cds)
    t["cooldown_count"] = len(cds)
    t["cc_count"] = sum(1 for h in heroes if h.cc_tools)
    t["cc_tools"] = [] if lean else ["%s: %s" % (h.name, ", ".join(h.cc_tools))
                                     for h in heroes if h.cc_tools]
    t["mobility_count"] = sum(1 for h in heroes if h.mobility_tools)
    t["mobility_tools"] = [] if lean else ["%s: %s" % (h.name, ", ".join(h.mobility_tools))
                                           for h in heroes if h.mobility_tools]
    t["flyers"] = sum(1 for h in heroes if h.flyer)
    t["light_flyers"] = sum(1 for h in heroes if h.flyer and h.role != "tank")
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
    # a hero the wiki pairs with no one at all is unknown, not alone: unknown is not a number
    isolated = [h.name for h in heroes
                if n >= 2 and not adjacency[h.id] and world.partners.get(h.id)]
    t["isolated_count"], t["isolated"] = len(isolated), isolated
    t["core_size"] = _largest_component(adjacency)
    t["pairs"] = pairs

    t["win_mean"] = _mean([h.win for h in heroes])
    t["pick_mass"] = sum(h.pick or 0 for h in heroes)
    avail = 1.0
    for h in heroes:
        avail *= 1.0 - (h.ban or 0) / 100.0
    t["availability"] = avail
    here = 1.0
    for h in heroes:
        ban = h.map_ban(m.id) if m is not None else None
        rate = h.ban if ban is None else ban            # this map's ban, else all-ranks
        here *= 1.0 - (rate or 0) / 100.0
    t["map_availability"] = here
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
    t["_answered"] = {} if lean else {e.name: answered[e.id] for e in enemies}
    t["_exposure"] = {} if lean else {h.name: exposure[h.id] for h in heroes}
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


def red_matchup(red_t):
    """The matchup metrics red alone decides: the same for every blue six on
    a board."""
    return {"dive_pressure": red_t["mobility_count"], "flyers": red_t["light_flyers"],
            "barrier_need": red_t["barrier_hp"], "antiheal_need": red_t["heal_peak_supports"],
            "ult_threat": red_t["ult_damage_total"], "style_lean_red": red_t["style_lean"]}


RED_MATCHUP = frozenset("matchup." + key for key in (
    "dive_pressure", "flyers", "barrier_need", "antiheal_need", "ult_threat", "style_lean_red"))


def matchup_metrics(blue_t, red_t):
    """MATCHUP_METRICS from blue's seat, given both teams' metrics.

    Only what reading both sides produces. A blue number that is already a
    team metric is not restated here under a second name: two strategies
    reading the same number through two keys weigh one signal twice, and the
    catalog cannot see that they do. Read team.* for blue's own.
    """
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
    x["exposure_share"] = (blue_t["exposed_count"] / blue_t["size"]
                           if blue_t["size"] else 0.0)
    x.update(red_matchup(red_t))
    x["ult_answers"] = blue_t["invuln"] + blue_t["cleanse"]
    return x


def is_sided(m):
    return m is not None and (m.mode or "") in SIDED_MODES


def opposite(side):
    return {"attack": "defense", "defense": "attack"}.get(side, "")


def arenas(m):
    """The map's stages where each is its own ground (Control, Flashpoint)."""
    return [] if m is None or is_sided(m) else list(m.stages)


def phases(m):
    """The map's stages where they are parts of one route (Hybrid, Escort)."""
    return list(m.stages) if is_sided(m) else []


def stage_standouts(m, stage):
    """[(feature, z)] a stage's own text stresses: z at or over TERRAIN_STANDOUT
    on STAGE_MENTIONS or more mentions, largest first, STAGE_FEATURES at most.
    Stage texts are short: one mention swings the rate, and none says nothing."""
    terrain, z = m.stage_terrain.get(stage, {}), m.stage_z.get(stage, {})
    found = [(f, z[f]) for f in TERRAIN_FEATURES
             if f in terrain and z.get(f, 0.0) >= TERRAIN_STANDOUT
             and terrain[f][1] >= STAGE_MENTIONS]
    return sorted(found, key=lambda fz: (-fz[1], fz[0]))[:STAGE_FEATURES]


def map_metrics(m, side="", bans=0):
    if m is None:
        return {"known": 0, "sided": 0, "side": "", "style_top": "",
                "style_margin": 0, "mode": "", "stages": 0, "phases": 0, "bans": bans,
                **dict.fromkeys(TERRAIN_FEATURES, 0.0)}
    sided = 1 if is_sided(m) else 0
    return {"known": 1, "sided": sided, "side": side if sided else "",
            "style_top": m.style_top or "", "style_margin": m.style_margin,
            "mode": m.mode or "", "stages": len(arenas(m)),
            "phases": len(phases(m)), "bans": bans,
            **{f: m.terrain_z[f] for f in TERRAIN_FEATURES}}


def world_metrics(world):
    return {"heal_bench": world.heal_bench, "hps_bench": world.hps_bench,
            "roster_size": len(world.heroes)}


def namespace(world, m, red, blue, side="", bans=0):
    """The whole evaluation namespace for a board: {team, enemy, matchup,
    map, world} - `team` is blue's seat, `enemy` is red's, `side` blue's."""
    blue_t = team_metrics(world, blue, m, red)
    red_t = team_metrics(world, red, m, blue)
    return {"team": blue_t, "enemy": red_t,
            "matchup": matchup_metrics(blue_t, red_t),
            "map": map_metrics(m, side, bans), "world": world_metrics(world)}


# Metrics whose value is a name or a list, not a number: a heuristic may not
# maximize them, but a constraint may compare them ("team.style_lean == 'dive'").
TEXT_METRICS = {
    "team.subroles", "team.shape_flags", "team.style_counts", "team.style_top",
    "team.style_lean", "team.weakest", "team.squishies", "team.burst_hero",
    "team.cc_tools", "team.mobility_tools", "team.isolated", "team.pairs",
    "team.max_ban_hero", "team.unanswered", "team.exposed",
    "matchup.style_lean_red",
    "map.style_top", "map.mode", "map.side",
}
TEXT_METRICS |= {n.replace("team.", "enemy.", 1) for n in TEXT_METRICS if n.startswith("team.")}

# team metrics that read the other side. The solver builds red's metrics once,
# facing no one, so as enemy.* these would all read zero: not offered
VERSUS_KEYS = frozenset((
    "coverage", "coverage_share", "unanswered", "answer_edges", "exposure_edges",
    "exposed_count", "exposed", "safe_count", "net_edges", "double_covered",
    "banproof_coverage"))


def registry():
    """Every dotted key a strategy may reference -> its description."""
    out = {}
    for prefix, table in (("team", TEAM_METRICS), ("enemy", TEAM_METRICS),
                          ("matchup", MATCHUP_METRICS), ("map", MAP_METRICS),
                          ("world", WORLD_METRICS)):
        for key, description in table.items():
            if prefix == "enemy" and key in VERSUS_KEYS:
                continue
            out["%s.%s" % (prefix, key)] = description
    return out
