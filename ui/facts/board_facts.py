"""A board's facts: everything the database holds about it, as a numbered
FactSet.

    generate(world, "King's Row", red=["Zarya", "Pharah"], blue=["Ana"])

    for each domain D in { HEROES, MAPS, META }:
      INDEPENDENT(D) = ⋃ facts(s)      over each selection s in D   s alone: its own row
      DEPENDENT(D)   = ⋃ facts(s ⋈ t)  over the other selections t  s joined with t
      FACTS(D)       = INDEPENDENT(D) ∪ DEPENDENT(D)
    FACTS       = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)      F1..
    STRATEGIES  = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS         the playbook
    (the playbook's record)                                      S1..  what it holds

FACTS are derived from the authoritative data - what the sources say about
the heroes, the maps and the meta, pulled and set - for this board, and
every domain yields both kinds: the independent facts are a selection's
own row (a hero's kit, rates and style; the map's mode and stages; the
meta's vintage); the dependent facts are the selection joined with others
(map_meta is heroes ⋈ maps ⋈ meta, counters and synergies are heroes ⋈
heroes, the team is the six joined, the matchup the twelve, the bans join
both teams), and a join belongs to every domain it touches - the
dependent facts are where the domains' fact sets intersect.
Independent facts per hero and for the map come first; the joins per team
appear once a team has picks, and the matchup once both teams do.
Below them, numbered S1.., rides the PLAYBOOK's record: how many
constraints, heuristics and assumptions it holds - citable, never mistaken
for data, and not the strategies themselves (those are the constraints and
heuristics the solver reads). Both sides are
structured (scope, subject, key, value) so the inference layer can read
them by key, and rendered as sentences so a person - or the /comp skill -
can read them as evidence. Ids are dense and stable within a board.
"""

from collections.abc import Sequence

from db import Refusal
from ui.facts import compute
from ui.facts.compute import TERRAIN_STANDOUT, TREND_POINTS
from ui.facts.draft import MAX_BANS, SIDES, is_sided, opposite
from ui.facts.factset import PLAYBOOK_SCOPE, FactSet
from ui.facts.model import SQUISHY_POOL, TERRAIN_FEATURES, TERRAIN_LEAN, Hero, Map, World
from ui.facts.team import (
    RANK_SENSITIVE,
    SPECIALIST_DELTA,
    TEAM_METRICS,
    MetricBag,
    answers,
    names,
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


def _g(value: object) -> str:
    return "%g" % value if isinstance(value, float) else str(value)


def _trim(text: str | None, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- the board -------------------------------------------------------------

def generate(world: World, map_name: str | None = None, red: Sequence[str] = (),
             blue: Sequence[str] = (), bans: Sequence[str] = (), side: str = "") -> FactSet:
    """The FactSet for a board: the map (and blue's side on a sided map),
    the red and blue picks, and the match's bans (each team's two and the
    lobby's - up to five, all optional). A banned hero cannot be picked and
    cannot be recommended; a side that is not one, and every name World.resolve
    refuses, is a Refusal."""
    if side not in ("", *SIDES):
        raise Refusal("side must be attack or defense, got %r" % side)
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans, allow_announced=True)
    side = side if is_sided(m) else ""
    fs = FactSet(m.name if m else None, [h.name for h in red_h],
                 [h.name for h in blue_h], [h.name for h in bans_h], side)
    _meta_facts(fs, world)
    if bans_h:
        _ban_facts(fs, world, bans_h, red_h, blue_h)
    if m is not None:
        _map_facts(fs, world, m, side)
    for h in red_h:
        _hero_facts(fs, world, h, "red", m, blue_h, [x for x in red_h if x is not h])
    for h in blue_h:
        _hero_facts(fs, world, h, "blue", m, red_h, [x for x in blue_h if x is not h])
    red_t = team_metrics(world, red_h, m, blue_h) if red_h else None
    blue_t = team_metrics(world, blue_h, m, red_h) if blue_h else None
    if red_t:
        _team_facts(fs, world, "red", red_h, red_t, m, blue_h)
    if blue_t:
        _team_facts(fs, world, "blue", blue_h, blue_t, m, red_h)
    if red_t and blue_t:
        _matchup_facts(fs, blue_t, red_t)
    _playbook_record(fs, world)
    return fs


def _meta_facts(fs: FactSet, world: World) -> None:
    for s in world.snapshots:                 # one per source: its newest capture
        fs.add("meta", "snapshot", "meta.snapshot",
               "%s rates: captured %s, %s (%s), %s - %s, %s, %s"
               % (s["source"], s["captured"], s["patch"] or "an unknown patch",
                  s["released"] or "-", s["season"] or "unknown season",
                  s["queue"].replace("competitive_", "").replace("_", " "), s["platform"],
                  s["region"] or "region unstated"),
               value=s, source="meta_snapshots")
    if world.newer_patches:
        name, released = world.newer_patches[0]
        fs.add("meta", "snapshot", "meta.vintage_warning",
               "WARNING: %d patch(es) shipped since the rates were captured,"
               " newest %s (%s) - treat rates as pre-patch"
               % (len(world.newer_patches), name, released),
               value=len(world.newer_patches), source="patches")


def _ban_facts(fs: FactSet, world: World, banned: Sequence[Hero], red: Sequence[Hero],
               blue: Sequence[Hero]) -> None:
    """What the bans took off the table, for both sides."""
    fs.add("bans", "match", "bans.count", "bans this match: %d of %d - %s"
           % (len(banned), MAX_BANS, ", ".join(h.name for h in banned)),
           value=[h.name for h in banned], source="derived:bans.count")
    for h in banned:
        fs.add("bans", h.name, "bans.hero", "%s is banned this match - neither team"
               " can pick them" % h.name, value=h.name, source="derived:bans.hero")
        answered = [e.name for e in red if world.counters_of(e.id, h.id)]
        if answered:
            fs.add("bans", h.name, "bans.answered_red", "banned %s answered red %s -"
                   " that answer is off the table" % (h.name, ", ".join(answered)),
                   value=answered, source="counters")
        threatened = [a.name for a in blue if world.counters_of(a.id, h.id)]
        if threatened:
            fs.add("bans", h.name, "bans.answered_blue", "banned %s answered blue %s -"
                   " that threat is gone" % (h.name, ", ".join(threatened)),
                   value=threatened, source="counters")


def _halves(m: Map, style: str) -> str:
    """The two halves of a map's style score, as the fact words them."""
    parts = [("terrain", m.terrain_lean.get(style)), ("rates", m.rate_lift.get(style))]
    return ", ".join("%s %+.1f" % (word, z) if z is not None else "no %s" % word
                     for word, z in parts)


def _map_facts(fs: FactSet, world: World, m: Map, side: str = "") -> None:
    fs.add("map", m.name, "map.mode", "%s is a %s map" % (m.name, m.mode),
           value=m.mode, source="map_modes")
    if is_sided(m):
        if side:
            verb = {"attack": "attacks", "defense": "defends"}
            fs.add("map", m.name, "map.side", "blue %s %s; red %s" % (
                verb[side], m.name, verb[opposite(side)]), value=side,
                source="derived:map.side")
        else:
            fs.add("map", m.name, "map.side", "%s has an attacking and a defending side"
                   "; blue's side is not set" % m.name, value="",
                   source="derived:map.side")
        fs.add("map", m.name, "map.side_caveat", "the rates do not split by side on"
               " %s: side-specific advice comes from the kit facts and the side"
               " strategies, not from win rates" % m.name, value=m.mode,
               source="derived:map.side_caveat")
    else:
        fs.add("map", m.name, "map.side", "%s (%s) has no attacking or defending side"
               % (m.name, m.mode), value="", source="derived:map.side")
    if compute.arenas(m):
        fs.add("map", m.name, "map.stages", "%s stages: %s"
               % (m.name, ", ".join(m.stages)), value=m.stages, source="map_stages")
    elif compute.phases(m):
        fs.add("map", m.name, "map.phases", "%s phases, in order: %s"
               % (m.name, ", ".join(m.stages)), value=m.stages, source="map_stages")
    for stage in m.stages:
        standouts = compute.stage_standouts(m, stage)
        if standouts:
            fs.add("map", m.name, "map.stage_terrain",
                   "%s - %s: %s" % (m.name, stage, "; ".join(
                       "%s, %.1f sd above the ordinary stage (%d mentions in the wiki's article)"
                       % (f.replace("_", " "), z, m.stage_terrain[stage][f][1])
                       for f, z in standouts)),
                   value={"stage": stage, "features": [
                       {"feature": f, "z": z, "per_thousand": m.stage_terrain[stage][f][0],
                        "mentions": m.stage_terrain[stage][f][1]} for f, z in standouts]},
                   source="stage_terrain")
    if m.terrain:
        for feature in sorted(TERRAIN_FEATURES, key=lambda f: (-abs(m.terrain_z[f]), f)):
            z = m.terrain_z[feature]
            if abs(z) >= TERRAIN_STANDOUT:
                fs.add("map", m.name, "map.terrain", "%s: %s, %.1f sd %s the ordinary map (the"
                       " wiki's article)" % (m.name, feature.replace("_", " "), abs(z),
                                             "below" if z < 0 else "above"),
                       value={"feature": feature, "z": z, "per_thousand": m.terrain[feature]},
                       source="map_terrain")
    else:
        fs.add("map", m.name, "map.terrain_unread", "%s: the wiki's article has too little on"
               " the ground; its terrain metrics read 0" % m.name, value=0,
               source="map_terrain")
    ranked_styles = sorted(m.styles, key=lambda s: (-m.styles[s][0], s))
    for style in ranked_styles:
        if style in m.rate_lift:
            score = m.rate_lift[style]
            fs.add("map", m.name, "map.rate_lift", "%s heroes win %.1f sd %s on %s than on other"
                   " maps" % (style, abs(score), "less" if score < 0 else "more", m.name),
                   value={"style": style, "score": score}, source="playstyle+map_meta")
    for style in ranked_styles:
        if style in m.terrain_lean:
            fs.add("map", m.name, "map.terrain_lean", "%s's terrain leans %+.1f sd to %s (%s)"
                   % (m.name, m.terrain_lean[style], style,
                      ", ".join(f.replace("_", " ") for f in TERRAIN_LEAN[style])),
                   value={"style": style, "score": m.terrain_lean[style]},
                   source="map_terrain")
    for style in ranked_styles:
        fs.add("map", m.name, "map.style", "%s on %s: %+.1f sd (%s)"
               % (style, m.name, m.styles[style][0], _halves(m, style)),
               value={"style": style, "score": m.styles[style][0],
                      "terrain": m.terrain_lean.get(style), "rates": m.rate_lift.get(style)},
               source="derived:map.style")
    top = m.style_top                   # None exactly when the map has no styles
    if top is not None:
        fs.add("map", m.name, "map.style_top", "%s rewards %s: %s (%s sd over the runner-up)"
               % (m.name, top, _halves(m, top), _g(m.style_margin)),
               value=top, source="derived:map.style_top")
    wins = {h.id: win for h in world.heroes.values() if (win := h.map_win(m.id)) is not None}
    ranked = sorted((h for h in world.heroes.values() if h.id in wins),
                    key=lambda h: -wins[h.id])
    for h in ranked[:10]:
        fs.add("map", m.name, "map.leader", "on %s: %s wins %.1f%% (picked %.1f%%)"
               % (m.name, h.name, wins[h.id], h.map_pick(m.id) or 0),
               value={"hero": h.name, "win": wins[h.id]}, source="map_meta")
    if len(ranked) > 6:
        fs.add("map", m.name, "map.strugglers", "struggle on %s: %s" % (m.name, ", ".join(
            "%s (%.1f%%)" % (h.name, wins[h.id]) for h in ranked[-6:][::-1])),
            value=[h.name for h in ranked[-6:]], source="map_meta")
    for h in world.heroes_by_role():
        if m.id in h.best_maps:
            fs.add("map", m.name, "map.playbook_pick", "%s is %s's top-%d map by Blizzard's"
                   " map rates" % (m.name, h.name, h.best_maps.index(m.id) + 1),
                   value=h.name, source="derived:map.playbook_pick")
    for style in sorted(m.styles, key=lambda s: (-m.styles[s][0], s)):
        fits = [h for h in ranked if style in h.styles][:6]
        if fits:
            fs.add("map", m.name, "map.style_fit", "%s heroes who hold up on %s: %s"
                   % (style, m.name, ", ".join(
                       "%s (%.1f%%)" % (h.name, wins[h.id]) for h in fits)),
                   value=[h.name for h in fits], source="playstyle+map_meta")


def _hero_facts(fs: FactSet, world: World, h: Hero, team: str, m: Map | None,
                opponents: Sequence[Hero], teammates: Sequence[Hero]) -> None:
    """Every independent fact about ONE hero, then the facts that only exist
    on this board: on this map, against these opponents, beside these
    teammates."""
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
    # traits read off the kit's own numbers and keywords
    traits = [
        ("hero.dps", "%s's weapon sustains %g damage per second" % (name, h.dps), h.dps, "hp/s")
        if h.dps else None,
        ("hero.burst", "%s's biggest single hit: %g" % (name, h.burst), h.burst, "hp")
        if h.burst else None,
        ("hero.heal_peak", "%s's biggest single heal: %g" % (name, h.peak_heal),
         h.peak_heal, "hp") if h.peak_heal else None,
        ("hero.hps", "%s sustains %g healing per second on teammates" % (name, h.hps), h.hps,
         "hp/s")
        if h.hps else None,
        ("hero.self_heal", "%s heals itself: %s" % (name, ", ".join(
            text % n for text, n in (("%g a cast", h.self_heal), ("%g per second", h.self_hps))
            if n)), {"cast": h.self_heal, "per_second": h.self_hps}, None)
        if (h.self_heal or h.self_hps) else None,
        ("hero.range", "%s's weapon reaches %gm" % (name, h.max_range),
         h.max_range, "m") if h.max_range else None,
        ("hero.cooldown_median", "%s's median cooldown: %gs across %d abilities"
         % (name, h.median_cooldown, len(h.cooldowns)), h.median_cooldown, "s")
        if h.median_cooldown is not None else None,
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
    for trait in traits:
        if trait:
            key, text, value, unit = trait
            fs.add("hero", name, key, text, value=value, unit=unit,
                   source="derived:" + key, team=team)
    for style in sorted(h.styles):
        fs.add("hero", name, "hero.style", "%s is a %s hero" % (name, style),
               value=style, source="playstyle", team=team)
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
    if h.win is not None:
        fs.add("hero", name, "hero.rate", "%s across all ranks: wins %.1f%%, picked %.1f%%%s"
               % (name, h.win, h.pick or 0,
                  ", banned %.1f%%" % h.ban if h.ban is not None else ""),
               value={"win": h.win, "pick": h.pick, "ban": h.ban}, source="hero_meta",
               team=team)
    for tier, (win, pick, ban) in sorted(h.by_tier.items()):
        if win is not None:
            fs.add("hero", name, "hero.rate_tier", "%s in %s lobbies: wins %.1f%%, picked %.1f%%%s"
                   % (name, tier, win, pick or 0,
                      ", banned %.1f%%" % ban if ban is not None else ""),
                   value={"tier": tier, "win": win}, source="hero_meta", team=team)
    if h.rank_spread >= RANK_SENSITIVE:
        lo = min(w[0] for w in h.by_tier.values() if w[0] is not None)
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
    if m is None and h.map_rates:
        # no map on the board: one line of where the hero does best, not a
        # line per map - with a map, the intersection below is the fact
        best = sorted(h.map_rates.items(), key=lambda kv: -kv[1][0])[:3]
        fs.add("hero", name, "hero.rate_maps", "%s's best maps: %s" % (name, ", ".join(
            "%s (%.1f%%)" % (world.maps[mid].name, win) for mid, (win, _) in best)),
            value=[world.maps[mid].name for mid, _ in best], source="map_meta", team=team)
    if m is None and h.best_maps and h.win is not None:
        # the same intersection rule as the rates: with a map on the board the
        # "top map" fact below is the whole story. best_maps is filled only for
        # a hero with a win rate, from maps it has a rate on.
        overall = h.win
        fs.add("hero", name, "hero.best_map", "%s's three best maps by Blizzard's map rates,"
               " over its own %.1f%%: %s" % (name, overall, ", ".join(
                   "%s (%+.1f)" % (world.maps[mid].name, h.map_rates[mid].win - overall)
                   for mid in h.best_maps)),
               value=[world.maps[mid].name for mid in h.best_maps],
               source="derived:hero.best_map", team=team)
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
        fs.add("hero", name, "hero.partner", "%s + %s (%s/3): %s"
               % (name, world.heroes[other].name, score if score is not None else "?",
                  note or "no note"), value=world.heroes[other].name,
               source="synergies", team=team)

    # --- facts that exist only on this board ------------------------------
    if m is not None:
        win = h.map_win(m.id)
        if win is not None:
            ban_here = h.map_ban(m.id)
            fs.add("hero", name, "hero.map_win", "%s on %s (this map): wins %.1f%%,"
                   " picked %.1f%%%s" % (name, m.name, win, h.map_pick(m.id) or 0,
                                         ", banned %.1f%%" % ban_here if ban_here is not None
                                         else ""),
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
            fs.add("hero", name, "hero.map_strategy", "this map is %s's top-%d by Blizzard's"
                   " map rates" % (name, h.best_maps.index(m.id) + 1),
                   value=h.best_maps.index(m.id) + 1, source="derived:hero.map_strategy",
                   team=team)
        if m.style_top and m.style_top in h.styles:
            fs.add("hero", name, "hero.map_style_fit", "%s fits the %s style %s rewards"
                   % (name, m.style_top, m.name), value=m.style_top,
                   source="derived:hero.map_style_fit", team=team)
    other_side = "red" if team == "blue" else "blue"
    threats = [o.name for o in opponents if world.counters_of(h.id, o.id)]
    if threats:
        fs.add("hero", name, "hero.vs_answered_by", "%s: %s %s is answered by %s %s"
               % ("WARNING" if team == "blue" else "NOTE", team, name, other_side,
                  ", ".join(threats)), value=threats,
               source="counters", team=team)
    wins = [o.name for o in opponents if world.counters_of(o.id, h.id)]
    if wins:
        fs.add("hero", name, "hero.vs_answers", "%s %s answers %s %s"
               % (team, name, other_side, ", ".join(wins)), value=wins,
               source="counters", team=team)
    for mate in teammates:
        edge = world.synergy(h.id, mate.id)
        if edge:
            fs.add("hero", name, "hero.with_ally", "%s %s + %s (%s/3): %s"
                   % (team, name, mate.name, edge[0] if edge[0] is not None else "?",
                      edge[1] or "no note"), value=mate.name, source="synergies",
                   team=team)


def _team_facts(fs: FactSet, world: World, team: str, heroes: Sequence[Hero], t: MetricBag,
                m: Map | None, enemies: Sequence[Hero]) -> None:
    """One fact per team metric, worded for a reader."""
    picked = ", ".join(h.name for h in heroes)
    n = numbers(t)
    label = "%s team" % team
    side = "red" if team == "blue" else "blue"

    def add(key: str, text: str, unit: str | None = None, also: Sequence[str] = ()) -> None:
        fs.add("team", team, "team." + key, text, value=t[key], unit=unit,
               source="derived:team." + key, team=team, also=also)

    def listed(key: str, unit: str | None = None) -> None:
        """A metric worded by its registry line, once compute carries it."""
        if t.get(key):
            add(key, "%s %s: %g" % (label, TEAM_METRICS[key], n[key]), unit)

    add("size", "%s: %d pick%s locked (%s), %d slot%s open" % (
        label, n["size"], "" if n["size"] == 1 else "s", picked, n["open_slots"],
        "" if n["open_slots"] == 1 else "s"))
    add("tanks", "%s shape: %d tank / %d dps / %d support%s" % (
        label, n["tanks"], n["damage"], n["supports"],
        " - " + "; ".join(names(t["shape_flags"])) if t["shape_flags"] else ""),
            also=("team.damage", "team.supports"))
    add("subrole_diversity", "%s subrole diversity: %d distinct jobs across %d picks (%s)"
        % (label, len(names(t["subroles"])), n["size"], ", ".join(names(t["subroles"]))))
    if t["style_counts"]:
        add("style_top", "%s style profile: %s%s" % (label, ", ".join(
            "%s %d/%d" % (s, c, n["size"]) for s, c in sorted(
                style_tally(t["style_counts"]).items(), key=lambda kv: (-kv[1], kv[0]))),
            " - leans %s" % t["style_lean"] if t["style_lean"] else " - no majority style"),
                also=("team.style_lean",))
    if m is not None and m.style_top:
        add("style_fit", "%s fit with the %s style %s rewards: %.0f%% of picks"
            % (label, m.style_top, m.name, 100 * n["style_fit"]))
        add("archetype_deviation", "%s over two per role: %s"
            % (label, _count(n["archetype_deviation"])))
    add("pool_total", "%s effective HP: %d across %d picks" % (label, n["pool_total"], n["size"]),
        "hp")
    add("pool_min", "%s weakest link: %s at %d pool - focus fire finds the minimum"
        % (label, t["weakest"], n["pool_min"]), "hp")
    if t["armor_total"]:
        add("armor_share", "%s armor: %d of %d pool (%.0f%%) discounts sustained fire"
            % (label, n["armor_total"], n["pool_total"], 100 * n["armor_share"]),
                also=("team.armor_total",))
    if t["shield_total"]:
        add("shield_share", "%s recharging shields: %d of %d pool (%.0f%%) - rewards"
            " disengages" % (label, n["shield_total"], n["pool_total"], 100 * n["shield_share"]),
                also=("team.shield_total",))
    if t["squishies"]:
        add("squish_count", "%s squish index: %d/%d picks at %d pool or less (%s)"
            % (label, n["squish_count"], n["size"], SQUISHY_POOL,
               ", ".join(names(t["squishies"]))))
    if t["overhealth_total"]:
        add("overhealth_total", "%s overhealth: %g granted, outside the healing figures"
            % (label, n["overhealth_total"]), "hp")
    add("dps_floor", "%s sustained damage: %g per second, held weapons summed, %d of %d"
        " picks with a figure" % (label, n["dps_floor"], n["dps_count"], n["size"]), "hp/s",
            also=("team.dps_count",))
    if t["burst_max"]:
        add("burst_max", "%s burst ceiling: %s's %g in one hit"
            % (label, t["burst_hero"], n["burst_max"]), "hp", also=("team.burst_ranged",))
    listed("burst_ranged", "hp")
    if t["one_shots"]:
        add("one_shots", "%s one-shots: %s whose biggest hit, a melee swing aside,"
            " kills a %d pool" % (label, _count(n["one_shots"]), SQUISHY_POOL))
    add("dmg_ults", "%s damage ultimates: %d of %d carry damage, %g summed"
        % (label, n["dmg_ults"], n["size"], n["ult_damage_total"]), also=("team.ult_damage_total",))
    if t["ult_cost_mean"]:
        add("ult_cost_mean", "%s mean ultimate cost: %.0f charge" % (label, n["ult_cost_mean"]))
    add("hitscan", "%s damage identity: %d hitscan, %d projectile, %d beam, %d melee"
        % (label, n["hitscan"], n["projectile"], n["beam"], n["melee"]),
            also=("team.melee", "team.projectile", "team.beam"))
    listed("hitscan_reach")
    if t["aoe_count"]:
        add("aoe_count", "%s area-damage volume: %d kit pieces tagged area of effect"
            % (label, n["aoe_count"]))
    if t["range_median"]:
        add("range_median", "%s reach: median %gm across the %d of %d picks whose weapons"
            " publish one (%gm to %gm) - reads as %s"
            % (label, n["range_median"], sum(1 for h in heroes if h.max_range), n["size"],
               n["range_min"], n["range_max"],
               "poke" if n["range_median"] >= 20 else "brawl"), "m",
                   also=("team.range_max", "team.range_min"))
    if t["dmg_amp"]:
        add("dmg_amp", "%s damage amplification: %s boost someone's damage"
            % (label, _count(n["dmg_amp"])))
    add("hps_floor", "%s healing onto teammates: %g per second summed across the picks"
        % (label, n["hps_floor"]), "hp/s")
    if t["supports"]:
        add("hps_supports", "%s healing supply: %g per second sustained across the supports vs"
            " the roster's ~%.0f two-support bench (ratio %.2f)%s"
            % (label, n["hps_supports"], world.hps_bench, n["hps_ratio"],
               " - UNDER-HEALED" if n["supports"] >= 2 and n["hps_ratio"] < UNDER_HEALED else ""),
            "hp/s", also=("team.hps_ratio",))
        add("heal_peak_supports", "%s biggest single heals: %g summed across the supports vs"
            " the roster's ~%.0f two-support bench (ratio %.2f)"
            % (label, n["heal_peak_supports"], world.heal_bench, n["heal_ratio"]), "hp",
                also=("team.heal_ratio",))
    if t["heal_peak_total"]:
        add("heal_peak_total", "%s single heals: %g summed, one cast per pick, self-heals"
            " included" % (label, n["heal_peak_total"]), "hp")
    add("lifelines", "%s lifelines: %d of %d picks carry any healing"
        % (label, n["lifelines"], n["size"]), also=("team.heal_peak_total",))
    if t["heal_amp"]:
        add("heal_amp", "%s healing amplification: %s" % (label, _count(n["heal_amp"])))
    if t["antiheal"]:
        add("antiheal", "%s anti-heal: %s can shut healing off" % (label, _count(n["antiheal"])))
    if t["cleanse"] or t["invuln"]:
        add("invuln", "%s defensive answers: %d invulnerability, %d cleanse"
            % (label, n["invuln"], n["cleanse"]),
                also=("team.cleanse", "team.team_cleanse", "team.team_saves"))
    listed("team_cleanse")
    listed("team_saves")
    if t["cooldown_count"]:
        add("cooldown_median", "%s cooldown tempo: median %gs across %d cooldowns - %s"
            % (label, n["cooldown_median"], n["cooldown_count"],
               "high-uptime brawl tempo" if n["cooldown_median"] <= 8 else
               "cooldown-bound; pick your fights"), "s", also=("team.cooldown_count",))
    cc_tools = ["%s: %s" % (h.name, ", ".join(h.cc_tools)) for h in heroes if h.cc_tools]
    add("cc_count", "%s crowd control: %s%s" % (
        label, _count(n["cc_count"]), "; " + "; ".join(cc_tools) if cc_tools else ""))
    mobility_tools = ["%s: %s" % (h.name, ", ".join(h.mobility_tools))
                      for h in heroes if h.mobility_tools]
    add("mobility_count", "%s engage/escape tools: %s%s" % (
        label, _count(n["mobility_count"]),
        "; " + "; ".join(mobility_tools) if mobility_tools else ""))
    if t["flyers"]:
        add("flyers", "%s vertical threats: %s fly" % (label, _count(n["flyers"])))
    if t["barrier_hp"]:
        add("barrier_hp", "%s barriers: %g hp across %s"
            % (label, n["barrier_hp"], _count(n["barrier_count"])), "hp",
                also=("team.barrier_count",))
    if t["barrier_piercers"]:
        add("barrier_piercers", "%s barrier-piercers: %s ignore barriers"
            % (label, _count(n["barrier_piercers"])))
    if t["deployables"]:
        add("deployables", "%s deployables: %s" % (label, _count(n["deployables"])))
    if n["size"] >= 2:
        pairs = "; ".join("%s+%s" % p[:2] for p in synergy_pairs(t["pairs"]))
        add("synergy_edges", "%s cohesion: %d of %d possible synergy edges (density %.2f,"
            " score sum %d)%s" % (label, n["synergy_edges"], n["size"] * (n["size"] - 1) // 2,
                                  n["synergy_density"], n["synergy_score"],
                                  " - " + pairs if t["pairs"] else " - no documented pair"),
                                      also=("team.synergy_score", "team.synergy_density"))
        add("core_size", "%s synergy core: the largest documented group is %s"
            % (label, _count(n["core_size"])))
        if t["isolated"]:
            add("isolated_count", "%s isolated: %s, with no documented partner on the"
                " team" % (label, ", ".join(names(t["isolated"]))))
    add("win_mean", "%s mean win rate (all ranks): %.1f%%" % (label, n["win_mean"]), "%")
    add("pick_mass", "%s pick-rate mass: %.1f summed - %s" % (
        label, n["pick_mass"], "meta-shaped; expect practiced answers"
        if n["pick_mass"] >= 30 else "off-meta lean; surprise value"))
    if m is not None and round(n["map_availability"], 2) != round(n["availability"], 2):
        add("map_availability", "%s availability on %s: %.0f%% chance every pick survives the"
            " ban screen here, from this map's ban rates" % (label, m.name,
                                                             100 * n["map_availability"]))
    add("availability", "%s expected availability: %.0f%% chance every pick survives the"
        " ban screen%s" % (label, 100 * n["availability"],
                           " (%s at %.0f%% ban)" % (t["max_ban_hero"], n["max_ban_rate"])
                           if t["max_ban_hero"] else ""), also=("team.max_ban_rate",))
    if t["rank_sensitive_count"]:
        add("rank_sensitive_count", "%s rank-sensitive picks: %d swing %g+ points across"
            " ranks" % (label, n["rank_sensitive_count"], RANK_SENSITIVE))
    if t["trend_sum"]:
        add("trend_sum", "%s trend since the previous capture: %+.1f win-rate points"
            " summed" % (label, n["trend_sum"]))
    if m is not None:
        add("map_win_mean", "%s on %s: mean win rate %.1f%% (pick mass %.1f)"
            % (label, m.name, n["map_win_mean"], n["map_pick_mass"]), "%")
        add("map_specialists", "%s map fit on %s: %s, %d off-map, %d with"
            " this map among their three best by rate"
            % (label, m.name, _count(n["map_specialists"], "specialist"),
               n["map_offmap"], n["map_strategy_hits"]),
                   also=("team.map_strategy_hits", "team.map_offmap"))
    if enemies:
        add("coverage", "%s coverage: answers %d/%d %s picks%s" % (
            label, n["coverage"], len(enemies), side,
            "; still unanswered: " + ", ".join(names(t["unanswered"])) if t["unanswered"] else ""),
                also=("team.coverage_share", "team.unanswered"))
        add("net_edges", "%s net matchup: %d answer-edges into %s vs %d %s answer-edges"
            " back (%+d)" % (label, n["answer_edges"], side, n["exposure_edges"], side,
                             n["net_edges"]), also=("team.answer_edges", "team.exposure_edges"))
        if t["exposed"]:
            add("exposed_count", "%s exposed: %s answered by at least one %s pick; %d safe"
                % (label, ", ".join(names(t["exposed"])), side, n["safe_count"]),
                    also=("team.safe_count",))
        if t["double_covered"]:
            add("double_covered", "%s double-covered: %s on %s answered by two or"
                " more" % (label, _count(n["double_covered"]), side))
        if t["max_ban_hero"]:
            add("banproof_coverage", "%s ban-resilient coverage: without %s (%.0f%% ban)"
                " still %d/%d answered" % (label, t["max_ban_hero"], n["max_ban_rate"],
                                           n["banproof_coverage"], len(enemies)))
        for enemy_name, answerers in answers(t["_answered"]).items():
            if answerers:
                fs.add("team", team, "team.answer", "%s %s is answered by %s %s"
                       % (side, enemy_name, team, ", ".join(answerers)),
                       value=answerers, source="counters", team=team)


def _matchup_facts(fs: FactSet, blue_t: MetricBag, red_t: MetricBag) -> None:
    matchup = compute.matchup_metrics(blue_t, red_t)
    # each bag's numbers, typed: the facts below compute with them
    blue_n, red_n, x = numbers(blue_t), numbers(red_t), numbers(matchup)

    def add(key: str, text: str, unit: str | None = None, value: object = None,
            also: Sequence[str] = ()) -> None:
        # a few board facts read blue's own metric: matchup carries only what
        # reading both sides produces, so those pass their value in
        fs.add("matchup", "blue vs red", "matchup." + key, text,
               value=matchup[key] if value is None else value,
               unit=unit, source="derived:matchup." + key, also=also)

    add("pool_diff", "pool differential: blue's %d picks carry %d hp vs red's %d picks' %d"
        " - %+d raw material" % (blue_n["size"], blue_n["pool_total"], red_n["size"],
                                 red_n["pool_total"], x["pool_diff"]), "hp")
    add("dps_diff", "damage floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_n["dps_floor"], red_n["dps_floor"], x["dps_diff"]), "hp/s")
    add("hps_diff", "healing floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_n["hps_floor"], red_n["hps_floor"], x["hps_diff"]), "hp/s")
    add("burst_vs_heal", "burst-vs-heal, blue's way: blue's best hit %g vs red's best save %g"
        " - %s" % (blue_n["burst_max"], red_n["heal_peak_max"],
                   "a kill window exists through their healing" if x["burst_vs_heal"] > 0
                   else "their saves absorb the burst; stack or poke instead"))
    add("heal_vs_burst", "burst-vs-heal, red's way: red's best hit %g vs blue's best save %g"
        " - %s" % (red_n["burst_max"], blue_n["heal_peak_max"],
                   "blue's saves keep pace" if x["heal_vs_burst"] >= 0
                   else "red's burst outruns blue's save; do not trade in the open"),
                       also=("team.heal_peak_max",))
    add("chew_time_ours", "chew-time floor, blue into red: %d pool / %g per second = %.1fs of"
        " unmitigated fire (no healing, no misses)" % (
            red_n["pool_total"], blue_n["dps_floor"], x["chew_time_ours"]), "s")
    add("chew_time_theirs", "chew-time floor, red into blue: %d pool / %g per second = %.1fs"
        % (blue_n["pool_total"], red_n["dps_floor"], x["chew_time_theirs"]), "s")
    add("tempo_diff", "tempo war: blue median cooldown %gs vs red %gs - %s" % (
        blue_n["cooldown_median"], red_n["cooldown_median"],
        "blue re-engages first; force fight frequency" if x["tempo_diff"] > 0 else
        "red re-engages first; make each fight decisive" if x["tempo_diff"] < 0 else
        "even tempo"), "s")
    add("range_diff", "poke war: blue median reach %gm vs red %gm - %s" % (
        blue_n["range_median"], red_n["range_median"],
        "blue outranges; open fights at distance" if x["range_diff"] > 0 else
        "red outranges; close fast or trade cover" if x["range_diff"] < 0 else "even reach"), "m")
    net = blue_n["net_edges"]
    add("net_edges", "board net matchup: %d blue answer-edges into red vs %d red into blue"
        " (%+d) - %s" % (blue_n["answer_edges"], blue_n["exposure_edges"], net,
                         "the draft is ahead" if net > 0 else
                         "the draft is behind; the open slots must swing it"
                         if net < 0 else "dead even"), value=net)
    add("coverage_share", "coverage: blue answers %.0f%% of red; red answers %.0f%% of blue"
        % (100 * blue_n["coverage_share"], 100 * x["exposure_share"]),
        value=blue_t["coverage_share"], also=("matchup.exposure_share",))
    if x["dive_pressure"]:
        add("dive_pressure", "dive pressure: %s on red carry engage tools; blue peel"
            " (%s) must hold" % (_count(x["dive_pressure"]),
                                  _count(blue_n["cc_count"], "crowd-control pick")))
    if x["flyers"]:
        add("flyers", "vertical threat: %s on red against %s on blue"
            % (_count(x["flyers"], "flyer"),
               _count(blue_n["hitscan"], "hitscan pick")))
    if x["barrier_need"]:
        add("barrier_need", "barrier war: red fields %g barrier hp against %s on blue"
            % (x["barrier_need"],
               _count(blue_n["barrier_piercers"], "barrier-piercer")), "hp")
    if x["antiheal_need"]:
        add("antiheal_need", "sustain war: red supports peak %g heal against %s on blue"
            % (x["antiheal_need"],
               _count(blue_n["antiheal"], "anti-heal pick")), "hp")
    if x["ult_threat"]:
        add("ult_threat", "ult threat: red's damage ultimates total %g against %s on blue"
            % (x["ult_threat"],
               _count(x["ult_answers"], "invulnerability or cleanse answer")), "hp",
                   also=("matchup.ult_answers",))
    if matchup["style_lean_red"] or blue_t["style_lean"]:
        add("style_lean_red", "style war: red leans %s, blue leans %s" % (
            matchup["style_lean_red"] or "nothing yet", blue_t["style_lean"] or "nothing yet"),
            value=matchup["style_lean_red"])


def _playbook_record(fs: FactSet, world: World) -> None:
    """S1..: the playbook's record - what it holds - never what the sources
    say, and not the constraints and heuristics themselves."""
    scope = PLAYBOOK_SCOPE
    if world.catalog_counts:
        c = world.catalog_counts
        fs.add(scope, "catalog", "playbook.catalog",
               "the playbook%s holds %d constraints, %d heuristics and %d assumptions"
               " (STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS)"
               % (" (%s)" % world.playbook if world.playbook else "",
                  c.get("constraint", 0), c.get("heuristic", 0), c.get("assumption", 0)),
               value=c, source="strategies")
