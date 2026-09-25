"""A named hero's facts: first what the hero is wherever it plays - who it is,
the traits its kit's numbers and keywords carry, its abilities, weapons and
perks, its rates, and the wiki's counters and partners - then what only
this board has: on this map, against these opponents, beside these
teammates. facts.board_facts calls write() once per pick, red first.
"""

from facts.compute import TREND_POINTS
from facts.factset import FactSet
from facts.model import Hero, Map, Resolved, World
from facts.team import RANK_SENSITIVE, SPECIALIST_DELTA

# a kit trait as the fact states it - key, sentence, value, unit - or None
# where the kit does not carry it
type TraitRow = tuple[str, str, object, str | None] | None


def _trim(text: str | None, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def write(fs: FactSet, world: World, board: Resolved, hero: Hero, team: str) -> None:
    """Every independent fact about ONE hero, then the facts that only exist
    on this board: on this map, against these opponents, beside these
    teammates."""
    own, opponents = (board.red, board.blue) if team == "red" else (board.blue, board.red)
    teammates = [x for x in own if x is not hero]
    _hero_identity(fs, world, hero, team)
    _hero_traits(fs, hero, team)
    _hero_abilities(fs, hero, team)
    _hero_weapons(fs, hero, team)
    _hero_perks(fs, hero, team)
    _hero_rates(fs, world, hero, team)
    _hero_rate_flags(fs, hero, team)
    if board.map is None:
        _hero_best_maps(fs, world, hero, team)
    _hero_relations(fs, world, hero, team)
    # --- facts that exist only on this board ------------------------------
    if board.map is not None:
        _hero_on_map(fs, hero, team, board.map)
    _hero_versus(fs, world, hero, team, opponents, teammates)


def _hero_identity(fs: FactSet, world: World, h: Hero, team: str) -> None:
    """Who the hero is: role, pool, styles, weapon and ultimate, whether it is
    playable yet, and its subrole's passive."""
    name = h.name
    pool = "%dhp" % h.health + ("+%dsh" % h.shield if h.shield else "") + \
        ("+%dar" % h.armor if h.armor else "")
    ult = "; ult %s: %s" % (h.ult.name, _trim(h.ult.description, 80)) if h.ult else ""
    fs.add("hero", name, "hero.identity",
        "%s %s - %s (%s), %s%s%s%s" % (
            team, name, h.role.capitalize(), h.subrole, pool,
            "; styles: " + ", ".join(sorted(h.styles)) if h.styles else "",
            "; weapon: " + ", ".join(sorted(h.weapon_kinds)) if h.weapon_kinds else "",
            ult),
        value={"role": h.role, "subrole": h.subrole}, source="heroes", team=team)
    if not h.released:
        fs.add("hero", name, "hero.announced", "CAUTION: %s is announced, not yet playable%s -"
            " the kit is the wiki's preview and there are no rates" % (
                name, " (releases %s)" % h.release_date if h.release_date else ""),
            value=str(h.release_date) if h.release_date else None, source="heroes", team=team)
    fs.add("hero", name, "hero.pool", "%s pool: %d (%d health, %d shield, %d armor)%s"
        % (name, h.pool, h.health, h.shield, h.armor,
            ", %g more armor from its forms, time-averaged" % h.form_armor
            if h.form_armor else ""),
        value=h.pool, unit="hp", source="heroes", team=team)
    passive = world.subrole_passives.get(h.subrole)
    if passive:
        fs.add("hero", name, "hero.passive", "%s's %s passive: %s"
            % (name, h.subrole, _trim(passive, 100)), value=h.subrole,
            source="subroles", team=team)


# --- traits read off the kit's own numbers and keywords -----------------------

def _output_traits(h: Hero) -> list[TraitRow]:
    """What the kit puts out: damage, burst, healing, reach and cooldowns."""
    name = h.name
    return [
        ("hero.dps", "%s's weapon sustains %g damage per second" % (name, h.dps), h.dps, "hp/s")
        if h.dps else None,
        ("hero.burst", "%s's biggest single hit: %g" % (name, h.burst), h.burst, "hp")
        if h.burst else None,
        ("hero.heal_peak", "%s's biggest single heal: %g" % (name, h.peak_heal),
            h.peak_heal, "hp") if h.peak_heal else None,
        ("hero.hps", "%s sustains %g healing per second on teammates" % (name, h.hps),
            h.hps, "hp/s") if h.hps else None,
        ("hero.self_heal", "%s heals itself: %s" % (name, ", ".join(
            text % n for text, n in (("%g a cast", h.self_heal), ("%g per second", h.self_hps))
            if n)), {"cast": h.self_heal, "per_second": h.self_hps}, None)
        if (h.self_heal or h.self_hps) else None,
        ("hero.range", "%s's weapon reaches %gm" % (name, h.max_range),
            h.max_range, "m") if h.max_range else None,
        ("hero.cooldown_median", "%s's median cooldown: %gs across %d abilities"
            % (name, h.median_cooldown, len(h.cooldowns)), h.median_cooldown, "s")
        if h.median_cooldown is not None else None,
    ]


def _tool_traits(h: Hero) -> list[TraitRow]:
    """The kit's tools: crowd control, movement, flight, barriers and amps."""
    name = h.name
    return [
        ("hero.cc", "%s brings crowd control: %s" % (name, ", ".join(h.cc_tools)),
            h.cc_tools, None) if h.cc_tools else None,
        ("hero.mobility", "%s brings movement: %s" % (name, ", ".join(h.mobility_tools)),
            h.mobility_tools, None) if h.mobility_tools else None,
        ("hero.flyer", "%s flies: a vertical threat, answered by hitscan"
            % name, True, None) if h.flyer else None,
        ("hero.barrier", "%s fields a %g-hp barrier" % (name, h.barrier_hp),
            h.barrier_hp, "hp") if h.barrier_hp else None,
        ("hero.pierces_barrier", "%s's kit ignores barriers" % name, True, None)
        if h.pierces_barrier else None,
        ("hero.antiheal", "%s carries anti-heal (%g%% healing)" % (name, h.antiheal),
            h.antiheal, "%") if h.antiheal < 0 else None,
        ("hero.heal_amp", "%s amplifies healing by up to %g%%" % (name, h.heal_amp),
            h.heal_amp, "%") if h.heal_amp else None,
        ("hero.dmg_amp", "%s amplifies damage by up to %g%%" % (name, h.dmg_amp),
            h.dmg_amp, "%") if h.dmg_amp else None,
    ]


def _save_traits(h: Hero) -> list[TraitRow]:
    """The kit's saves and its ultimate: overhealth, cleanses, invulnerability,
    deployables, the ultimate's damage and cost."""
    name = h.name
    return [
        ("hero.overhealth", "%s grants up to %g overhealth" % (name, h.overhealth),
            h.overhealth, "hp") if h.overhealth else None,
        ("hero.cleanse", "%s can cleanse: %s" % (name, ", ".join(h.cleanse_tools)),
            h.cleanse_tools, None) if h.cleanse_tools else None,
        ("hero.invuln", "%s has an invulnerability: %s" % (name, ", ".join(h.invuln_tools)),
            h.invuln_tools, None) if h.invuln_tools else None,
        ("hero.deployables", "%s deploys: %s" % (name, ", ".join(h.deployables)),
            h.deployables, None) if h.deployables else None,
        ("hero.ult_damage", "%s's ultimate %s deals up to %g" % (name, h.ult.name, h.ult_damage),
            h.ult_damage, "hp") if h.ult_damage and h.ult else None,
        ("hero.ult_cost", "%s's ultimate costs %g charge" % (name, h.ult_cost),
            h.ult_cost, "points") if h.ult_cost else None,
    ]


def _hero_traits(fs: FactSet, h: Hero, team: str) -> None:
    """One fact per trait the kit carries, then one per playstyle."""
    name = h.name
    for trait in (*_output_traits(h), *_tool_traits(h), *_save_traits(h)):
        if trait:
            key, text, value, unit = trait
            fs.add("hero", name, key, text, value=value, unit=unit,
                source="derived:" + key, team=team)
    for style in sorted(h.styles):
        fs.add("hero", name, "hero.style", "%s is a %s hero" % (name, style),
            value=style, source="playstyle", team=team)


# --- the kit piece by piece -------------------------------------------------

def _hero_abilities(fs: FactSet, h: Hero, team: str) -> None:
    name = h.name
    for a in h.abilities:
        fs.add("hero", name, "hero.ability", "%s - %s (%s): %s"
            % (name, a.name, a.kind, _trim(a.description, 90)),
            value=a.name, source="abilities", team=team)
        if a.keywords:
            fs.add("hero", name, "hero.ability_keywords", "%s's %s is tagged: %s"
                % (name, a.name, ", ".join(sorted(a.keywords))),
                value=sorted(a.keywords), source="abilities", team=team)
        for code, stats in a.stats.items():
            for s in stats:
                fs.add("hero", name, "hero.ability_stat", "%s's %s %s: %s"
                    % (name, a.name, code.replace("_", " "), s.rendered()),
                    value=s.value, unit=s.unit_num, source="ability_stats", team=team)


def _hero_weapons(fs: FactSet, h: Hero, team: str) -> None:
    name = h.name
    for w in h.weapons:
        fs.add("hero", name, "hero.weapon", "%s weapon: %s%s%s%s"
            % (name, w.extra.get("weapon"),
                " - " + w.name if w.name != w.extra.get("weapon") else "",
                " [%s]" % w.extra["weapon_type"] if w.extra.get("weapon_type") else "",
                ", %s" % w.extra["slot"].replace("_", " ")
                if w.extra.get("slot") not in (None, "default") else ""),
            value=w.name, source="weapon_configs", team=team)
        for code, stats in w.stats.items():
            for s in stats:
                fs.add("hero", name, "hero.weapon_stat", "%s's %s %s: %s"
                    % (name, w.name, code.replace("_", " "), s.rendered()),
                    value=s.value, unit=s.unit_num, source="weapon_stats", team=team)


def _hero_perks(fs: FactSet, h: Hero, team: str) -> None:
    """The perks and their stats, what each alters, and every ability modifier."""
    name = h.name
    for p in h.perks:
        fs.add("hero", name, "hero.perk", "%s perk (%s) - %s: %s"
            % (name, p.kind.split(":")[1], p.name, _trim(p.description, 90)),
            value=p.name, source="perks", team=team)
        for code, stats in p.stats.items():
            for s in stats:
                fs.add("hero", name, "hero.perk_stat", "%s's perk %s %s: %s"
                    % (name, p.name, code.replace("_", " "), s.rendered()),
                    value=s.value, unit=s.unit_num, source="perk_stats", team=team)
    for perk, ability in h.perk_effects:
        fs.add("hero", name, "hero.perk_effect", "%s's perk %s alters %s"
            % (name, perk, ability), value={"perk": perk, "ability": ability},
            source="perk_ability_effects", team=team)
    for aname, affects, applies, magnitude, unit in h.modifiers:
        fs.add("hero", name, "hero.modifier", "%s's %s changes %s by %+g%s%s"
            % (name, aname, affects.replace("_", " "), magnitude,
                "%" if unit == "percent" else " " + unit,
                " on %s" % applies if applies else ""),
            value=magnitude, source="ability_modifiers", team=team)


# --- the rates ----------------------------------------------------------------

def _hero_rates(fs: FactSet, world: World, h: Hero, team: str) -> None:
    """The all-ranks rates, then each tier's up the ladder, named as Blizzard
    names it."""
    name = h.name
    if h.win is not None:
        fs.add("hero", name, "hero.rate", "%s across all ranks: wins %.1f%%, picked %.1f%%%s"
            % (name, h.win, h.pick or 0,
                ", banned %.1f%%" % h.ban if h.ban is not None else ""),
            value={"win": h.win, "pick": h.pick, "ban": h.ban}, source="hero_meta",
            team=team)
    for tier, (win, pick, ban) in h.by_tier.items():
        if win is not None:
            fs.add("hero", name, "hero.rate_tier", "%s in %s lobbies: wins %.1f%%, picked %.1f%%%s"
                % (name, world.tier_names[tier], win, pick or 0,
                    ", banned %.1f%%" % ban if ban is not None else ""),
                value={"tier": tier, "win": win}, source="hero_meta", team=team)


def _hero_rate_flags(fs: FactSet, h: Hero, team: str) -> None:
    """What the rates warn of: a rank-sensitive hero, a moving one, a likely ban."""
    name = h.name
    if h.rank_spread >= RANK_SENSITIVE:
        lo = min(r.win for r in h.by_tier.values() if r.win is not None)
        fs.add("hero", name, "hero.rank_sensitivity", "RANK-SENSITIVE: %s swings %.1f"
            " points across ranks (%.1f%%-%.1f%%)"
            % (name, h.rank_spread, lo, lo + h.rank_spread), value=h.rank_spread,
            source="derived:hero.rank_sensitivity", team=team)
    if h.trend is not None and abs(h.trend) >= TREND_POINTS:
        fs.add("hero", name, "hero.trend", "trend since the previous capture: %s %+.1f win rate"
            % (name, h.trend), value=h.trend, source="derived:hero.trend", team=team)
    if h.ban and h.ban > 20:
        fs.add("hero", name, "hero.ban_pressure", "%s is banned in %.0f%% of lobbies -"
            " %s" % (name, h.ban, "a near-certain ban" if h.ban > 25 else "a likely ban"),
            value=h.ban, source="hero_meta", team=team)


def _hero_best_maps(fs: FactSet, world: World, h: Hero, team: str) -> None:
    """With no map on the board: one line of where the hero does best, not a
    line per map - with a map, the facts on it are the whole story."""
    name = h.name
    if h.map_rates:
        best = sorted(h.map_rates.items(), key=lambda kv: -kv[1].win)[:3]
        fs.add("hero", name, "hero.rate_maps", "%s's best maps: %s" % (name, ", ".join(
            "%s (%.1f%%)" % (world.maps[mid].name, win) for mid, (win, _) in best)),
            value=[world.maps[mid].name for mid, _ in best], source="map_meta", team=team)
    if h.best_maps and h.win is not None:
        # the same intersection rule as the rates. best_maps is filled only for
        # a hero with a win rate, from maps it has a rate on.
        overall = h.win
        fs.add("hero", name, "hero.best_map", "%s's three best maps by Blizzard's map rates,"
            " over its own %.1f%%: %s" % (name, overall, ", ".join(
                "%s (%+.1f)" % (world.maps[mid].name, h.map_rates[mid].win - overall)
                for mid in h.best_maps)),
            value=[world.maps[mid].name for mid in h.best_maps],
            source="derived:hero.best_map", team=team)


def _hero_relations(fs: FactSet, world: World, h: Hero, team: str) -> None:
    """The wiki's match-up advice and synergies, whoever else is picked."""
    name = h.name
    answered_by = sorted(world.heroes[x].name for x in world.answered_by.get(h.id, ()))
    if answered_by:
        fs.add("hero", name, "hero.answered_by", "%s is countered by, in the wiki's match-up"
            " advice: %s" % (name, ", ".join(answered_by)), value=answered_by,
            source="counters", team=team)
    answers = sorted(world.heroes[x].name for x in world.answers.get(h.id, ()))
    if answers:
        fs.add("hero", name, "hero.answers", "%s answers, in the wiki's match-up advice: %s"
            % (name, ", ".join(answers)), value=answers, source="counters", team=team)
    for other, (score, note) in sorted(world.partners.get(h.id, {}).items(),
            key=lambda kv: -(kv[1][0] or 0)):
        fs.add("hero", name, "hero.partner", "%s + %s (%s/2): %s"
            % (name, world.heroes[other].name, score if score is not None else "?",
                note or "no note"), value=world.heroes[other].name,
            source="synergies", team=team)


# --- the board's own ----------------------------------------------------------

def _hero_on_map(fs: FactSet, h: Hero, team: str, m: Map) -> None:
    """The hero on this map: its rates here, against its own, and whether the
    map is one of its best or rewards its style."""
    name = h.name
    win = h.map_win(m.id)
    if win is not None:
        ban_here = h.map_ban(m.id)
        fs.add("hero", name, "hero.map_win", "%s on %s (this map): wins %.1f%%,"
            " picked %.1f%%%s" % (name, m.name, win, h.map_pick(m.id) or 0,
                ", banned %.1f%%" % ban_here if ban_here is not None else ""),
            value=win, unit="%", source="map_meta", team=team)
        if h.win is not None:
            delta = win - h.win
            label = ("map specialist" if delta >= SPECIALIST_DELTA else
                "off-map liability" if delta <= -SPECIALIST_DELTA else
                "in line with their baseline")
            fs.add("hero", name, "hero.map_delta", "%s runs %+.1f on %s vs their own"
                " overall %.1f%% - %s" % (name, delta, m.name, h.win, label),
                value=delta, source="derived:hero.map_delta", team=team)
    if m.id in h.best_maps:
        fs.add("hero", name, "hero.home_map", "this map is %s's top-%d by Blizzard's"
            " map rates" % (name, h.best_maps.index(m.id) + 1),
            value=h.best_maps.index(m.id) + 1, source="derived:hero.home_map",
            team=team)
    if m.style_top and m.style_top in h.styles:
        fs.add("hero", name, "hero.map_style_fit", "%s fits the %s style %s rewards"
            % (name, m.style_top, m.name), value=m.style_top,
            source="derived:hero.map_style_fit", team=team)


def _hero_versus(
        fs: FactSet, world: World, h: Hero, team: str, opponents: list[Hero],
        teammates: list[Hero]) -> None:
    """The hero against these opponents and beside these teammates."""
    name = h.name
    other_side = "red" if team == "blue" else "blue"
    threats = [o.name for o in opponents if world.is_countered_by(h.id, o.id)]
    if threats:
        fs.add("hero", name, "hero.vs_answered_by", "%s: %s %s is answered by %s %s"
            % ("WARNING" if team == "blue" else "NOTE", team, name, other_side,
                ", ".join(threats)), value=threats,
            source="counters", team=team)
    wins = [o.name for o in opponents if world.is_countered_by(o.id, h.id)]
    if wins:
        fs.add("hero", name, "hero.vs_answers", "%s %s answers %s %s"
            % (team, name, other_side, ", ".join(wins)), value=wins,
            source="counters", team=team)
    for mate in teammates:
        edge = world.synergy(h.id, mate.id)
        if edge:
            fs.add("hero", name, "hero.with_ally", "%s %s + %s (%s/2): %s"
                % (team, name, mate.name, edge.score if edge.score is not None else "?",
                    edge.note or "no note"), value=mate.name, source="synergies",
                team=team)
