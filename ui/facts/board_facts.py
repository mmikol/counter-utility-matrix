"""A board's facts: everything the database holds about it, as a numbered
FactSet.

    generate(world, Draft("King's Row", red=("Zarya", "Pharah"), blue=("Ana",)))

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

This module writes the meta, the bans, the map and the playbook's record;
ui.facts.hero_facts writes a hero's facts, and ui.facts.team_facts a
team's and the matchup's.
"""

from db import Refusal
from ui.facts import compute, hero_facts, team_facts
from ui.facts.compute import TERRAIN_STANDOUT
from ui.facts.draft import MAX_BANS, SIDES, Draft, is_sided, opposite
from ui.facts.factset import PLAYBOOK_SCOPE, FactSet
from ui.facts.model import TERRAIN_FEATURES, TERRAIN_LEAN, Map, Resolved, World


def _g(value: object) -> str:
    return "%g" % value if isinstance(value, float) else str(value)


# --- the board -------------------------------------------------------------

def generate(world: World, draft: Draft) -> FactSet:
    """The FactSet for a board: the map (and blue's side on a sided map),
    the red and blue picks, and the match's bans (each team's two and the
    lobby's - up to five, all optional). A banned hero cannot be picked and
    cannot be recommended; a side that is not one, and every name World.resolve
    refuses, is a Refusal. The FactSet's draft holds the resolved names and
    the side the map keeps."""
    if draft.side not in ("", *SIDES):
        raise Refusal("side must be attack or defense, got %r" % draft.side)
    board = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans, allow_announced=True)
    side = draft.side if is_sided(board.map) else ""
    fs = FactSet(Draft(
        board.map.name if board.map else None, tuple(h.name for h in board.red),
        tuple(h.name for h in board.blue), tuple(h.name for h in board.banned), side))
    _meta_facts(fs, world)
    if board.banned:
        _ban_facts(fs, world, board)
    if board.map is not None:
        _map_facts(fs, world, board.map, side)
    for h in board.red:
        hero_facts.write(fs, world, board, h, "red")
    for h in board.blue:
        hero_facts.write(fs, world, board, h, "blue")
    team_facts.write(fs, world, board)
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


def _ban_facts(fs: FactSet, world: World, board: Resolved) -> None:
    """What the bans took off the table, for both sides."""
    banned = board.banned
    fs.add("bans", "match", "bans.count", "bans this match: %d of %d - %s"
        % (len(banned), MAX_BANS, ", ".join(h.name for h in banned)),
        value=[h.name for h in banned], source="derived:bans.count")
    for h in banned:
        fs.add("bans", h.name, "bans.hero", "%s is banned this match - neither team"
            " can pick them" % h.name, value=h.name, source="derived:bans.hero")
        answered = [e.name for e in board.red if world.counters_of(e.id, h.id)]
        if answered:
            fs.add("bans", h.name, "bans.answered_red", "banned %s answered red %s -"
                " that answer is off the table" % (h.name, ", ".join(answered)),
                value=answered, source="counters")
        threatened = [a.name for a in board.blue if world.counters_of(a.id, h.id)]
        if threatened:
            fs.add("bans", h.name, "bans.answered_blue", "banned %s answered blue %s -"
                " that threat is gone" % (h.name, ", ".join(threatened)),
                value=threatened, source="counters")


# --- the map ---------------------------------------------------------------

def _map_facts(fs: FactSet, world: World, m: Map, side: str = "") -> None:
    """The map's own facts - its mode and sides, its ground, the styles it
    rewards - then the heroes who do well on it."""
    _map_mode(fs, m, side)
    _map_terrain(fs, m)
    _map_styles(fs, m)
    _map_heroes(fs, world, m)


def _map_mode(fs: FactSet, m: Map, side: str) -> None:
    """The mode, who attacks, and the stages or phases in play order."""
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


def _map_terrain(fs: FactSet, m: Map) -> None:
    """The ground the wiki's articles stress: each stage's, then the map's."""
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


def _map_styles(fs: FactSet, m: Map) -> None:
    """The styles the map rewards: the rates' half, the terrain's half, the
    sum, and the style on top."""
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


def _halves(m: Map, style: str) -> str:
    """The two halves of a map's style score, as the fact words them."""
    parts = [("terrain", m.terrain_lean.get(style)), ("rates", m.rate_lift.get(style))]
    return ", ".join("%s %+.1f" % (word, z) if z is not None else "no %s" % word
        for word, z in parts)


def _map_heroes(fs: FactSet, world: World, m: Map) -> None:
    """Who wins on the map and who struggles, whose top map it is, and who
    holds up in each style it rewards."""
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


# --- the playbook's record -------------------------------------------------

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
