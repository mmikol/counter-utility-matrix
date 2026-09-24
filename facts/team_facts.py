"""A team's facts and the matchup's: one fact per team metric, worded for a
reader, for each side with picks, then the matchup once both sides have
them. The numbers are team_metrics' and compute.matchup_metrics' - the
ones the solver scores - so a fact states exactly what a strategy reads.
facts.board_facts calls write() once per board.
"""

import functools
from collections.abc import Sequence
from dataclasses import dataclass

from facts import compute
from facts.factset import FactSet
from facts.model import SQUISHY_POOL, Hero, Map, Resolved, World
from facts.team import (
    RANK_SENSITIVE,
    TEAM_METRICS,
    MetricBag,
    answers,
    names,
    number,
    numbers,
    style_tally,
    synergy_pairs,
    team_metrics,
)

# the support healing ratio under which the board flags a line: the playbook's
# HEAL_MARGIN (two-light-healers-lose) and the lifelines-cover-thin-heals guard
UNDER_HEALED = 0.7


def _count(n: float, word: str = "pick") -> str:
    """A count reads as a sentence: one pick, two picks, never one pick(s)."""
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def write(fs: FactSet, world: World, board: Resolved) -> None:
    """Each side's team facts, red first, once the side has picks; the matchup
    once both sides have them."""
    red_t = team_metrics(world, board.red, board.map, board.blue) if board.red else None
    blue_t = team_metrics(world, board.blue, board.map, board.red) if board.blue else None
    if red_t:
        _write_side(fs, world, team="red", heroes=board.red, metrics=red_t, m=board.map,
            enemies=board.blue)
    if blue_t:
        _write_side(fs, world, team="blue", heroes=board.blue, metrics=blue_t, m=board.map,
            enemies=board.red)
    if red_t and blue_t:
        matchup = compute.matchup_metrics(blue_t, red_t)
        _matchup_trades(fs, matchup, blue_t, red_t)
        _matchup_threats(fs, matchup, blue_t, red_t)


# --- one side -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _TeamWriter:
    """One side's facts: each worded around a team metric and valued by it."""
    fs: FactSet
    team: str
    metrics: MetricBag

    @property
    def label(self) -> str:
        return "%s team" % self.team

    @property
    def other_team(self) -> str:
        return "red" if self.team == "blue" else "blue"

    def fact(self, key: str, text: str, unit: str | None = None, also: Sequence[str] = ()) -> None:
        self.fs.add("team", self.team, "team." + key, text, value=self.metrics[key], unit=unit,
            source="derived:team." + key, team=self.team, also=also)

    def listed(self, key: str, unit: str | None = None) -> None:
        """A metric worded by its registry line, once compute carries it."""
        if self.metrics.get(key):
            self.fact(key, "%s %s: %g" % (
                self.label, TEAM_METRICS[key], number(self.metrics[key])), unit)


def _write_side(
        fs: FactSet, world: World, *, team: str, heroes: Sequence[Hero], metrics: MetricBag,
        m: Map | None, enemies: Sequence[Hero]) -> None:
    """One fact per team metric, worded for a reader, a helper per section of
    TEAM_METRICS in registry order."""
    w = _TeamWriter(fs, team, metrics)
    # the bag's numbers, typed: the sentences compute with them
    figures = numbers(metrics)
    _shape_facts(w, figures, heroes, m)
    _durability_facts(w, figures)
    _damage_facts(w, figures, heroes)
    _sustain_facts(w, figures, world)
    _tool_facts(w, figures, heroes)
    _cohesion_facts(w, figures)
    _meta_facts(w, figures, m)
    if m is not None:
        _map_facts(w, figures, m)
    if enemies:
        _versus_facts(w, figures, enemies)


def _shape_facts(
        w: _TeamWriter, figures: dict[str, float], heroes: Sequence[Hero], m: Map | None) -> None:
    label, metrics = w.label, w.metrics
    picked = ", ".join(h.name for h in heroes)
    w.fact("size", "%s: %d pick%s locked (%s), %d slot%s open" % (
        label, figures["size"], "" if figures["size"] == 1 else "s", picked,
        figures["open_slots"], "" if figures["open_slots"] == 1 else "s"))
    w.fact("tanks", "%s shape: %d tank / %d dps / %d support%s" % (
        label, figures["tanks"], figures["damage"], figures["supports"],
        " - " + "; ".join(names(metrics["shape_flags"])) if metrics["shape_flags"] else ""),
        also=("team.damage", "team.supports"))
    w.fact("subrole_diversity", "%s subrole diversity: %d distinct jobs across %d picks (%s)"
        % (label, len(names(metrics["subroles"])), figures["size"],
            ", ".join(names(metrics["subroles"]))))
    if metrics["style_counts"]:
        w.fact("style_top", "%s style profile: %s%s" % (label, ", ".join(
            "%s %d/%d" % (s, c, figures["size"]) for s, c in sorted(
                style_tally(metrics["style_counts"]).items(), key=lambda kv: (-kv[1], kv[0]))),
            " - leans %s" % metrics["style_lean"] if metrics["style_lean"]
            else " - no majority style"),
            also=("team.style_lean",))
    if m is not None and m.style_top:
        w.fact("style_fit", "%s fit with the %s style %s rewards: %.0f%% of picks"
            % (label, m.style_top, m.name, 100 * figures["style_fit"]))
    if metrics["shape_excess"]:
        w.fact("shape_excess", "%s over two per role: %s"
            % (label, _count(figures["shape_excess"])))


def _durability_facts(w: _TeamWriter, figures: dict[str, float]) -> None:
    label, metrics = w.label, w.metrics
    w.fact("pool_total", "%s effective HP: %d across %d picks"
        % (label, figures["pool_total"], figures["size"]), "hp")
    w.fact("pool_min", "%s weakest link: %s at %d pool - focus fire finds the minimum"
        % (label, metrics["weakest"], figures["pool_min"]), "hp")
    if metrics["armor_total"]:
        w.fact("armor_share", "%s armor: %d of %d pool (%.0f%%) discounts sustained fire"
            % (label, figures["armor_total"], figures["pool_total"],
                100 * figures["armor_share"]),
            also=("team.armor_total",))
    if metrics["shield_total"]:
        w.fact("shield_share", "%s recharging shields: %d of %d pool (%.0f%%) - rewards"
            " disengages" % (label, figures["shield_total"], figures["pool_total"],
                100 * figures["shield_share"]),
            also=("team.shield_total",))
    if metrics["squishies"]:
        w.fact("squish_count", "%s squish index: %d/%d picks at %d pool or less (%s)"
            % (label, figures["squish_count"], figures["size"], SQUISHY_POOL,
                ", ".join(names(metrics["squishies"]))))
    if metrics["overhealth_total"]:
        w.fact("overhealth_total", "%s overhealth: %g granted, outside the healing figures"
            % (label, figures["overhealth_total"]), "hp")


def _damage_facts(w: _TeamWriter, figures: dict[str, float], heroes: Sequence[Hero]) -> None:
    label, metrics = w.label, w.metrics
    w.fact("dps_floor", "%s sustained damage: %g per second, held weapons summed, %d of %d"
        " picks with a figure" % (label, figures["dps_floor"], figures["dps_count"],
            figures["size"]), "hp/s",
        also=("team.dps_count",))
    if metrics["burst_max"]:
        w.fact("burst_max", "%s burst ceiling: %s's %g in one hit"
            % (label, metrics["burst_hero"], figures["burst_max"]), "hp",
            also=("team.burst_ranged",))
    w.listed("burst_ranged", "hp")
    if metrics["one_shots"]:
        w.fact("one_shots", "%s one-shots: %s whose biggest hit, a melee swing aside,"
            " kills a %d pool" % (label, _count(figures["one_shots"]), SQUISHY_POOL))
    w.fact("dmg_ults", "%s damage ultimates: %d of %d carry damage, %g summed"
        % (label, figures["dmg_ults"], figures["size"], figures["ult_damage_total"]),
        also=("team.ult_damage_total",))
    if metrics["ult_cost_mean"]:
        w.fact("ult_cost_mean", "%s mean ultimate cost: %.0f charge"
            % (label, figures["ult_cost_mean"]))
    w.fact("hitscan", "%s damage identity: %d hitscan, %d projectile, %d beam, %d melee"
        % (label, figures["hitscan"], figures["projectile"], figures["beam"], figures["melee"]),
        also=("team.melee", "team.projectile", "team.beam"))
    w.listed("hitscan_reach")
    if metrics["aoe_count"]:
        w.fact("aoe_count", "%s area-damage volume: %d kit pieces tagged area of effect"
            % (label, figures["aoe_count"]))
    if metrics["range_median"]:
        w.fact("range_median", "%s reach: median %gm across the %d of %d picks whose weapons"
            " publish one (%gm to %gm) - reads as %s"
            % (label, figures["range_median"], sum(1 for h in heroes if h.max_range),
                figures["size"], figures["range_min"], figures["range_max"],
                "poke" if figures["range_median"] >= 20 else "brawl"), "m",
            also=("team.range_max", "team.range_min"))
    if metrics["dmg_amp"]:
        w.fact("dmg_amp", "%s damage amplification: %s boost someone's damage"
            % (label, _count(figures["dmg_amp"])))


def _sustain_facts(w: _TeamWriter, figures: dict[str, float], world: World) -> None:
    label, metrics = w.label, w.metrics
    w.fact("hps_floor", "%s healing onto teammates: %g per second summed across the picks"
        % (label, figures["hps_floor"]), "hp/s")
    if metrics["supports"]:
        under = figures["supports"] >= 2 and figures["hps_ratio"] < UNDER_HEALED
        w.fact("hps_supports", "%s healing supply: %g per second sustained across the"
            " supports vs the roster's ~%.0f two-support bench (ratio %.2f)%s"
            % (label, figures["hps_supports"], world.hps_bench, figures["hps_ratio"],
                " - UNDER-HEALED" if under else ""),
            "hp/s", also=("team.hps_ratio",))
        w.fact("heal_peak_supports", "%s biggest single heals: %g summed across the supports"
            " vs the roster's ~%.0f two-support bench (ratio %.2f)"
            % (label, figures["heal_peak_supports"], world.heal_bench, figures["heal_ratio"]),
            "hp", also=("team.heal_ratio",))
    if metrics["heal_peak_total"]:
        w.fact("heal_peak_total", "%s single heals: %g summed, one cast per pick, self-heals"
            " included" % (label, figures["heal_peak_total"]), "hp")
    w.fact("lifelines", "%s lifelines: %d of %d picks carry any healing"
        % (label, figures["lifelines"], figures["size"]), also=("team.heal_peak_total",))
    if metrics["heal_amp"]:
        w.fact("heal_amp", "%s healing amplification: %s" % (label, _count(figures["heal_amp"])))
    if metrics["antiheal"]:
        w.fact("antiheal", "%s anti-heal: %s can shut healing off"
            % (label, _count(figures["antiheal"])))
    if metrics["cleanse"] or metrics["invuln"]:
        w.fact("invuln", "%s defensive answers: %d invulnerability, %d cleanse"
            % (label, figures["invuln"], figures["cleanse"]),
            also=("team.cleanse", "team.team_cleanse", "team.team_saves"))
    w.listed("team_cleanse")
    w.listed("team_saves")


def _tool_facts(w: _TeamWriter, figures: dict[str, float], heroes: Sequence[Hero]) -> None:
    """Tempo and tools: the cooldowns, then what the kits bring to a fight."""
    label, metrics = w.label, w.metrics
    if metrics["cooldown_count"]:
        w.fact("cooldown_median", "%s cooldown tempo: median %gs across %d cooldowns - %s"
            % (label, figures["cooldown_median"], figures["cooldown_count"],
                "high-uptime brawl tempo" if figures["cooldown_median"] <= 8 else
                "cooldown-bound; pick your fights"), "s", also=("team.cooldown_count",))
    cc_tools = ["%s: %s" % (h.name, ", ".join(h.cc_tools)) for h in heroes if h.cc_tools]
    w.fact("cc_count", "%s crowd control: %s%s" % (
        label, _count(figures["cc_count"]), "; " + "; ".join(cc_tools) if cc_tools else ""))
    mobility_tools = ["%s: %s" % (h.name, ", ".join(h.mobility_tools))
        for h in heroes if h.mobility_tools]
    w.fact("mobility_count", "%s engage/escape tools: %s%s" % (
        label, _count(figures["mobility_count"]),
        "; " + "; ".join(mobility_tools) if mobility_tools else ""))
    if metrics["flyers"]:
        w.fact("flyers", "%s vertical threats: %s fly" % (label, _count(figures["flyers"])))
    if metrics["barrier_hp"]:
        w.fact("barrier_hp", "%s barriers: %g hp across %s"
            % (label, figures["barrier_hp"], _count(figures["barrier_count"])), "hp",
            also=("team.barrier_count",))
    if metrics["barrier_piercers"]:
        w.fact("barrier_piercers", "%s barrier-piercers: %s ignore barriers"
            % (label, _count(figures["barrier_piercers"])))
    if metrics["deployables"]:
        w.fact("deployables", "%s deployables: %s" % (label, _count(figures["deployables"])))


def _cohesion_facts(w: _TeamWriter, figures: dict[str, float]) -> None:
    """The synergy graph among the picks, once there are two."""
    if figures["size"] < 2:
        return
    label, metrics = w.label, w.metrics
    pairs = "; ".join("%s+%s" % (p.first, p.second) for p in synergy_pairs(metrics["pairs"]))
    w.fact("synergy_edges", "%s cohesion: %d of %d possible synergy edges (density %.2f,"
        " score sum %d)%s" % (label, figures["synergy_edges"],
            figures["size"] * (figures["size"] - 1) // 2,
            figures["synergy_density"], figures["synergy_score"],
            " - " + pairs if metrics["pairs"] else " - no documented pair"),
        also=("team.synergy_score", "team.synergy_density"))
    w.fact("core_size", "%s synergy core: the largest documented group is %s"
        % (label, _count(figures["core_size"])))
    if metrics["isolated"]:
        w.fact("isolated_count", "%s isolated: %s, with no documented partner on the"
            " team" % (label, ", ".join(names(metrics["isolated"]))))


def _meta_facts(w: _TeamWriter, figures: dict[str, float], m: Map | None) -> None:
    label, metrics = w.label, w.metrics
    w.fact("win_mean", "%s mean win rate (all ranks): %.1f%%"
        % (label, figures["win_mean"]), "%")
    w.fact("pick_mass", "%s pick-rate mass: %.1f summed - %s" % (
        label, figures["pick_mass"], "meta-shaped; expect practiced answers"
        if figures["pick_mass"] >= 30 else "off-meta lean; surprise value"))
    if m is not None and round(figures["map_availability"], 2) != round(figures["availability"], 2):
        w.fact("map_availability", "%s availability on %s: %.0f%% chance every pick survives"
            " the ban screen here, from this map's ban rates"
            % (label, m.name, 100 * figures["map_availability"]))
    w.fact("availability", "%s expected availability: %.0f%% chance every pick survives the"
        " ban screen%s" % (label, 100 * figures["availability"],
            " (%s at %.0f%% ban)" % (metrics["max_ban_hero"], figures["max_ban_rate"])
            if metrics["max_ban_hero"] else ""),
        also=("team.max_ban_rate",))
    if metrics["rank_sensitive_count"]:
        w.fact("rank_sensitive_count", "%s rank-sensitive picks: %d swing %g+ points across"
            " ranks" % (label, figures["rank_sensitive_count"], RANK_SENSITIVE))
    if metrics["trend_sum"]:
        w.fact("trend_sum", "%s trend since the previous capture: %+.1f win-rate points"
            " summed" % (label, figures["trend_sum"]))


def _map_facts(w: _TeamWriter, figures: dict[str, float], m: Map) -> None:
    label = w.label
    w.fact("map_win_mean", "%s on %s: mean win rate %.1f%% (pick mass %.1f)"
        % (label, m.name, figures["map_win_mean"], figures["map_pick_mass"]), "%")
    w.fact("map_specialists", "%s map fit on %s: %s, %d off-map, %d with"
        " this map among their three best by rate"
        % (label, m.name, _count(figures["map_specialists"], "specialist"),
            figures["map_offmap"], figures["home_map_hits"]),
        also=("team.home_map_hits", "team.map_offmap"))


def _versus_facts(w: _TeamWriter, figures: dict[str, float], enemies: Sequence[Hero]) -> None:
    """The side against the other: coverage, the answer edges, the exposed
    picks, and each enemy's answerers."""
    label, metrics, other = w.label, w.metrics, w.other_team
    w.fact("coverage", "%s coverage: answers %d/%d %s picks%s" % (
        label, figures["coverage"], len(enemies), other,
        "; still unanswered: " + ", ".join(names(metrics["unanswered"]))
        if metrics["unanswered"] else ""),
        also=("team.coverage_share", "team.unanswered"))
    w.fact("net_edges", "%s net matchup: %d answer-edges into %s vs %d %s answer-edges"
        " back (%+d)" % (label, figures["answer_edges"], other, figures["exposure_edges"],
            other, figures["net_edges"]),
        also=("team.answer_edges", "team.exposure_edges"))
    if metrics["exposed"]:
        w.fact("exposed_count", "%s exposed: %s answered by at least one %s pick; %d safe"
            % (label, ", ".join(names(metrics["exposed"])), other, figures["safe_count"]),
            also=("team.safe_count",))
    if metrics["double_covered"]:
        w.fact("double_covered", "%s double-covered: %s on %s answered by two or"
            " more" % (label, _count(figures["double_covered"]), other))
    if metrics["max_ban_hero"]:
        w.fact("banproof_coverage", "%s ban-resilient coverage: without %s (%.0f%% ban)"
            " still %d/%d answered" % (label, metrics["max_ban_hero"], figures["max_ban_rate"],
                figures["banproof_coverage"], len(enemies)))
    for enemy_name, answerers in answers(metrics["_answered"]).items():
        if answerers:
            w.fs.add("team", w.team, "team.answer", "%s %s is answered by %s %s"
                % (other, enemy_name, w.team, ", ".join(answerers)),
                value=answerers, source="counters", team=w.team)


# --- the matchup --------------------------------------------------------------

def _add_matchup(
        fs: FactSet, matchup: MetricBag, key: str, text: str, unit: str | None = None,
        value: object = None, also: Sequence[str] = ()) -> None:
    # a few board facts read one side's own metric, blue's or red's: matchup
    # carries only what reading both sides produces, so those pass their value in
    fs.add("matchup", "blue vs red", "matchup." + key, text,
        value=matchup[key] if value is None else value,
        unit=unit, source="derived:matchup." + key, also=also)


def _matchup_trades(fs: FactSet, matchup: MetricBag, blue_t: MetricBag, red_t: MetricBag) -> None:
    """What each side trades into the other: pool, damage and healing floors,
    burst against saves, chew time, tempo and reach."""
    add = functools.partial(_add_matchup, fs, matchup)
    # each bag's numbers, typed: the facts below compute with them
    blue_n, red_n, matchup_n = numbers(blue_t), numbers(red_t), numbers(matchup)
    add("pool_diff", "pool differential: blue's %d picks carry %d hp vs red's %d picks' %d"
        " - %+d raw material" % (blue_n["size"], blue_n["pool_total"], red_n["size"],
            red_n["pool_total"], matchup_n["pool_diff"]), "hp")
    add("dps_diff", "damage floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_n["dps_floor"], red_n["dps_floor"], matchup_n["dps_diff"]), "hp/s")
    add("hps_diff", "healing floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_n["hps_floor"], red_n["hps_floor"], matchup_n["hps_diff"]), "hp/s")
    add("burst_vs_heal", "burst-vs-heal, blue's way: blue's best hit %g vs red's best save %g"
        " - %s" % (blue_n["burst_max"], red_n["heal_peak_max"],
            "a kill window exists through their healing" if matchup_n["burst_vs_heal"] > 0
            else "their saves absorb the burst; stack or poke instead"))
    add("heal_vs_burst", "burst-vs-heal, red's way: red's best hit %g vs blue's best save %g"
        " - %s" % (red_n["burst_max"], blue_n["heal_peak_max"],
            "blue's saves keep pace" if matchup_n["heal_vs_burst"] >= 0
            else "red's burst outruns blue's save; do not trade in the open"),
        also=("team.heal_peak_max",))
    add("chew_time_ours", "chew-time floor, blue into red: %d pool / %g per second = %.1fs of"
        " unmitigated fire (no healing, no misses)" % (
            red_n["pool_total"], blue_n["dps_floor"], matchup_n["chew_time_ours"]), "s")
    add("chew_time_theirs", "chew-time floor, red into blue: %d pool / %g per second = %.1fs"
        % (blue_n["pool_total"], red_n["dps_floor"], matchup_n["chew_time_theirs"]), "s")
    add("tempo_diff", "tempo war: blue median cooldown %gs vs red %gs - %s" % (
        blue_n["cooldown_median"], red_n["cooldown_median"],
        "blue re-engages first; force fight frequency" if matchup_n["tempo_diff"] > 0 else
        "red re-engages first; make each fight decisive" if matchup_n["tempo_diff"] < 0 else
        "even tempo"), "s")
    add("range_diff", "poke war: blue median reach %gm vs red %gm - %s" % (
        blue_n["range_median"], red_n["range_median"],
        "blue outranges; open fights at distance" if matchup_n["range_diff"] > 0 else
        "red outranges; close fast or trade cover" if matchup_n["range_diff"] < 0 else
        "even reach"), "m")


def _matchup_threats(fs: FactSet, matchup: MetricBag, blue_t: MetricBag, red_t: MetricBag) -> None:
    """The draft's answer edges and coverage, then red's threats, each against
    blue's answer to it, and the style war. A threat is red's own team metric,
    so its sentence carries the enemy.* key a strategy reads it by."""
    add = functools.partial(_add_matchup, fs, matchup)
    blue_n, red_n, matchup_n = numbers(blue_t), numbers(red_t), numbers(matchup)
    net = blue_n["net_edges"]
    add("net_edges", "board net matchup: %d blue answer-edges into red vs %d red into blue"
        " (%+d) - %s" % (blue_n["answer_edges"], blue_n["exposure_edges"], net,
            "the draft is ahead" if net > 0 else
            "the draft is behind; the open slots must swing it"
            if net < 0 else "dead even"), value=net)
    add("coverage_share", "coverage: blue answers %.0f%% of red; red answers %.0f%% of blue"
        % (100 * blue_n["coverage_share"], 100 * matchup_n["exposure_share"]),
        value=blue_t["coverage_share"], also=("matchup.exposure_share",))
    if red_n["mobility_count"]:
        add("dive_pressure", "dive pressure: %s on red carry engage tools; blue peel"
            " (%s) must hold" % (_count(red_n["mobility_count"]),
                _count(blue_n["cc_count"], "crowd-control pick")),
            value=red_n["mobility_count"], also=("enemy.mobility_count",))
    if red_n["light_flyers"]:
        add("flyers", "vertical threat: %s on red against %s on blue"
            % (_count(red_n["light_flyers"], "flyer"),
                _count(blue_n["hitscan"], "hitscan pick")),
            value=red_n["light_flyers"], also=("enemy.light_flyers",))
    if red_n["barrier_hp"]:
        add("barrier_need", "barrier war: red fields %g barrier hp against %s on blue"
            % (red_n["barrier_hp"],
                _count(blue_n["barrier_piercers"], "barrier-piercer")), "hp",
            value=red_n["barrier_hp"], also=("enemy.barrier_hp",))
    if red_n["heal_peak_supports"]:
        add("antiheal_need", "sustain war: red supports peak %g heal against %s on blue"
            % (red_n["heal_peak_supports"],
                _count(blue_n["antiheal"], "anti-heal pick")), "hp",
            value=red_n["heal_peak_supports"], also=("enemy.heal_peak_supports",))
    if red_n["ult_damage_total"]:
        add("ult_threat", "ult threat: red's damage ultimates total %g against %s on blue"
            % (red_n["ult_damage_total"],
                _count(matchup_n["ult_answers"], "invulnerability or cleanse answer")), "hp",
            value=red_n["ult_damage_total"], also=("matchup.ult_answers", "enemy.ult_damage_total"))
    if red_t["style_lean"] or blue_t["style_lean"]:
        add("style_lean_red", "style war: red leans %s, blue leans %s" % (
            red_t["style_lean"] or "nothing yet", blue_t["style_lean"] or "nothing yet"),
            value=red_t["style_lean"], also=("enemy.style_lean",))
