"""The FactSet: everything the database holds about a board, numbered.

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
own row (a hero's kit, rates and style; the map's mode and note; the
meta's vintage); the dependent facts are the selection joined with others
(map_meta is heroes ⋈ maps ⋈ meta, counters and synergies are heroes ⋈
heroes, the team is the six joined, the matchup the twelve, the bans join
both teams), and a join belongs to every domain it touches - the
dependent facts are where the domains' fact sets intersect.
Independent facts per hero and for the map come first; the joins per team
appear once a team has picks, and the matchup once both teams do.
Below them, numbered S1.., rides the PLAYBOOK's record: the archetypes it
names, how many constraints, heuristics and assumptions it holds -
citable, never mistaken for data, and not the strategies themselves (those
are the constraints and heuristics the solver reads). Both sides are
structured (scope, subject, key, value) so the inference layer can read
them by key, and rendered as sentences so a person - or the /comp skill -
can read them as evidence. Ids are dense and stable within a board.
"""

from ui.facts import compute
from ui.facts.compute import (
    MAX_BANS,
    RANK_SENSITIVE,
    SIDES,
    SPECIALIST_DELTA,
    TREND_POINTS,
    is_sided,
    opposite,
)
from ui.facts.model import SQUISHY_POOL


class Fact:
    __slots__ = (
        "id",
        "key",
        "scope",
        "source",
        "subject",
        "team",
        "text",
        "unit",
        "value",
    )

    def __init__(self, fid, scope, subject, team, key, text, value, unit, source):
        self.id, self.scope, self.subject, self.team = fid, scope, subject, team
        self.key, self.text, self.value, self.unit, self.source = (
            key, text, value, unit, source)

    def to_dict(self):
        return {"id": self.id, "scope": self.scope, "subject": self.subject,
                "team": self.team, "key": self.key, "text": self.text,
                "value": _plain(self.value), "unit": self.unit,
                "source": self.source}


def _plain(value):
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


PLAYBOOK_SCOPE = "playbook"
PLAYBOOK_DIVIDER = "-- the playbook's record: what it holds - not facts --"


class FactSet:
    """The facts (F1..) and the playbook's record (S1..) of one board. Both
    live in `facts` in order, so a citation of either resolves; `count` is
    the facts alone."""

    def __init__(self, map_name=None, red=(), blue=(), bans=(), side=""):
        self.map_name, self.red, self.blue = map_name, list(red), list(blue)
        self.bans, self.side = list(bans), side
        self.facts = []
        self._by_key = {}
        self._n = {"F": 0, "S": 0}

    def add(self, scope, subject, key, text, value=None, unit=None,
            source="", team=None):
        prefix = "S" if scope == PLAYBOOK_SCOPE else "F"
        self._n[prefix] += 1
        fid = "%s%d" % (prefix, self._n[prefix])
        fact = Fact(fid, scope, subject, team, key, text, value, unit, source)
        self.facts.append(fact)
        self._by_key.setdefault((key, subject), []).append(fact)
        return fid

    @property
    def count(self):
        return self._n["F"]

    @property
    def playbook(self):
        return [f for f in self.facts if f.scope == PLAYBOOK_SCOPE]

    def find(self, key, subject=None):
        """Facts with this key (and subject, if given)."""
        if subject is not None:
            return list(self._by_key.get((key, subject), ()))
        return [f for f in self.facts if f.key == key]

    def rendered(self):
        lines = ["[%s] %s" % (f.id, f.text) for f in self.facts if f.scope != PLAYBOOK_SCOPE]
        side = self.playbook
        if side:
            lines += [PLAYBOOK_DIVIDER] + ["[%s] %s" % (f.id, f.text) for f in side]
        return "\n".join(lines)

    def to_dict(self):
        return {"map": self.map_name, "red": self.red, "blue": self.blue,
                "bans": self.bans, "side": self.side, "count": self.count,
                "playbook_count": self._n["S"],
                "facts": [f.to_dict() for f in self.facts]}


def _g(value):
    return "%g" % value if isinstance(value, float) else str(value)


def _trim(text, limit=110):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- the board -------------------------------------------------------------

def generate(world, map_name=None, red=(), blue=(), bans=(), side=""):
    """The FactSet for a board: the map (and blue's side on a sided map),
    the red and blue picks, and the match's bans (each team's two and the
    lobby's - up to five, all optional). A banned hero cannot be picked and
    cannot be recommended."""
    if side not in ("", *SIDES):
        raise ValueError("side must be attack or defense, got %r" % side)
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
    red_t = compute.team_metrics(world, red_h, m, blue_h) if red_h else None
    blue_t = compute.team_metrics(world, blue_h, m, red_h) if blue_h else None
    if red_t:
        _team_facts(fs, world, "red", red_h, red_t, m, blue_h)
    if blue_t:
        _team_facts(fs, world, "blue", blue_h, blue_t, m, red_h)
    if red_t and blue_t:
        _matchup_facts(fs, world, blue_t, red_t)
    _playbook_record(fs, world, m)
    return fs


def _meta_facts(fs, world):
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


def _ban_facts(fs, world, bans, red, blue):
    """What the bans took off the table, for both sides."""
    fs.add("bans", "match", "bans.count", "bans this match: %d of %d - %s"
           % (len(bans), MAX_BANS, ", ".join(h.name for h in bans)),
           value=[h.name for h in bans], source="derived:bans.count")
    for h in bans:
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


def _map_facts(fs, world, m, side=""):
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
                   " - pick blue's side to tune the comps" % m.name, value="",
                   source="derived:map.side")
        fs.add("map", m.name, "map.side_caveat", "the rates do not split by side on"
               " %s: side-specific advice comes from the kit facts and the side"
               " strategies, not from win rates" % m.name, value=m.mode,
               source="derived:map.side_caveat")
    else:
        fs.add("map", m.name, "map.side", "%s (%s) has no attacking or defending side"
               % (m.name, m.mode), value="", source="derived:map.side")
    if m.stages:
        fs.add("map", m.name, "map.stages", "%s stages: %s"
               % (m.name, ", ".join(m.stages)), value=m.stages, source="map_stages")
    for style, (score, note) in sorted(m.styles.items(), key=lambda kv: -(kv[1][0] or 0)):
        fs.add("map", m.name, "map.style", "%s rewards %s (%s/3): %s"
               % (m.name, style, score, note), value={"style": style, "score": score},
               source="map_playstyle")
    if m.styles:
        fs.add("map", m.name, "map.style_top", "%s's rewarded style is %s (margin %s"
               " over the runner-up)" % (m.name, m.style_top, _g(m.style_margin)),
               value=m.style_top, source="derived:map.style_top")
    ranked = sorted((h for h in world.heroes.values() if h.map_win(m.id) is not None),
                    key=lambda h: -h.map_win(m.id))
    for h in ranked[:10]:
        fs.add("map", m.name, "map.leader", "on %s: %s wins %.1f%% (picked %.1f%%)"
               % (m.name, h.name, h.map_win(m.id), h.map_pick(m.id) or 0),
               value={"hero": h.name, "win": h.map_win(m.id)}, source="map_meta")
    if len(ranked) > 6:
        fs.add("map", m.name, "map.strugglers", "struggle on %s: %s" % (m.name, ", ".join(
            "%s (%.1f%%)" % (h.name, h.map_win(m.id)) for h in ranked[-6:][::-1])),
            value=[h.name for h in ranked[-6:]], source="map_meta")
    for h in world.heroes_by_role():
        if m.id in h.best_maps:
            fs.add("map", m.name, "map.playbook_pick", "%s is a top-%d map for %s"
                   % (m.name, h.best_maps.index(m.id) + 1, h.name),
                   value=h.name, source="map_strategy")
    for style in sorted(m.styles, key=lambda s: -(m.styles[s][0] or 0)):
        fits = [h for h in ranked if style in h.styles][:6]
        if fits:
            fs.add("map", m.name, "map.style_fit", "%s heroes who hold up on %s: %s"
                   % (style, m.name, ", ".join(
                       "%s (%.1f%%)" % (h.name, h.map_win(m.id)) for h in fits)),
                   value=[h.name for h in fits], source="playstyle+map_meta")


def _hero_facts(fs, world, h, team, m, opponents, teammates):
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
    fs.add("hero", name, "hero.pool", "%s pool: %d (%d health, %d shield, %d armor)"
           % (name, h.pool, h.health, h.shield, h.armor), value=h.pool, unit="hp",
           source="heroes", team=team)
    passive = world.subrole_passives.get(h.subrole)
    if passive and passive[1]:
        fs.add("hero", name, "hero.passive", "%s's %s passive: %s"
               % (name, h.subrole, _trim(passive[1], 100)), value=h.subrole,
               source="subroles", team=team)
    # traits read off the kit's own numbers and keywords
    traits = [
        ("hero.dps", "%s publishes %g damage per second at best" % (name, h.dps), h.dps, "hp/s")
        if h.dps else None,
        ("hero.burst", "%s's biggest single hit: %g" % (name, h.burst), h.burst, "hp")
        if h.burst else None,
        ("hero.heal_peak", "%s's biggest single heal: %g" % (name, h.peak_heal),
         h.peak_heal, "hp") if h.peak_heal else None,
        ("hero.hps", "%s heals %g per second at best" % (name, h.hps), h.hps, "hp/s")
        if h.hps else None,
        ("hero.range", "%s's longest published range: %gm" % (name, h.max_range),
         h.max_range, "m") if h.max_range else None,
        ("hero.cooldown_median", "%s's median cooldown: %gs across %d abilities"
         % (name, h.median_cooldown, len(h.cooldowns)), h.median_cooldown, "s")
        if h.median_cooldown is not None else None,
        ("hero.cc", "%s brings crowd control: %s" % (name, ", ".join(h.cc_tools)),
         h.cc_tools, None) if h.cc_tools else None,
        ("hero.mobility", "%s brings movement: %s" % (name, ", ".join(h.mobility_tools)),
         h.mobility_tools, None) if h.mobility_tools else None,
        ("hero.flyer", "%s takes to the air - a vertical threat hitscan answers"
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
         h.ult_damage, "hp") if h.dmg_ult and h.ult else None,
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
    for code, (win, pick) in sorted(h.alt_rates.items()):
        fs.add("hero", name, "hero.rate_alt", "%s's own population has %s winning %.1f%%%s"
               % (code, name, win, ", picked %.1f%%" % pick if pick is not None else ""),
               value={"source": code, "win": win, "pick": pick}, source="hero_meta",
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
               " points across ranks (%.1f%%-%.1f%%) - advice must know its audience"
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
    if m is None and h.best_maps:
        # the same intersection rule as the rates: with a map on the board the
        # "top pick on this map" fact below is the whole story
        fs.add("hero", name, "hero.best_map", "counterpick rates %s a top pick on: %s" % (
            name, ", ".join(world.maps[mid].name for mid in h.best_maps)),
            value=[world.maps[mid].name for mid in h.best_maps], source="map_strategy",
            team=team)
    answered_by = sorted(world.heroes[x].name for x in world.answered_by.get(h.id, ()))
    if answered_by:
        fs.add("hero", name, "hero.answered_by", "%s is countered by: %s"
               % (name, ", ".join(answered_by)), value=answered_by, source="counters",
               team=team)
    answers = sorted(world.heroes[x].name for x in world.answers.get(h.id, ()))
    if answers:
        fs.add("hero", name, "hero.answers", "%s answers: %s" % (name, ", ".join(answers)),
               value=answers, source="counters", team=team)
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
            fs.add("hero", name, "hero.map_strategy", "counterpick lists %s as a top-%d"
                   " pick on this map" % (name, h.best_maps.index(m.id) + 1),
                   value=h.best_maps.index(m.id) + 1, source="map_strategy", team=team)
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


def _team_facts(fs, world, team, heroes, t, m, enemies):
    """One fact per team metric, worded for a reader."""
    names = ", ".join(h.name for h in heroes)
    label = "%s team" % team
    side = "red" if team == "blue" else "blue"

    def add(key, text, unit=None):
        fs.add("team", team, "team." + key, text, value=t[key], unit=unit,
               source="derived:team." + key, team=team)

    add("size", "%s: %d pick%s locked (%s), %d slot%s open" % (
        label, t["size"], "" if t["size"] == 1 else "s", names, t["open_slots"],
        "" if t["open_slots"] == 1 else "s"))
    add("tanks", "%s shape: %d tank / %d dps / %d support%s" % (
        label, t["tanks"], t["damage"], t["supports"],
        " - " + "; ".join(t["shape_flags"]) if t["shape_flags"] else ""))
    add("subrole_diversity", "%s subrole diversity: %d distinct jobs across %d picks (%s)"
        % (label, len(t["subroles"]), t["size"], ", ".join(t["subroles"])))
    if t["style_counts"]:
        add("style_top", "%s style profile: %s%s" % (label, ", ".join(
            "%s %d/%d" % (s, c, t["size"]) for s, c in sorted(
                t["style_counts"].items(), key=lambda kv: -kv[1])),
            " - leans %s" % t["style_lean"] if t["style_lean"] else " - no majority style"))
    if m is not None and m.style_top:
        add("style_fit", "%s fit with the %s style %s rewards: %.0f%% of picks"
            % (label, m.style_top, m.name, 100 * t["style_fit"]))
        add("archetype_deviation", "%s deviation from the %s archetype's role slots: %d"
            " pick(s) over" % (label, m.style_top, t["archetype_deviation"]))
    add("pool_total", "%s effective HP: %d across %d picks" % (label, t["pool_total"], t["size"]),
        "hp")
    add("pool_min", "%s weakest link: %s at %d pool - focus fire finds the minimum"
        % (label, t["weakest"], t["pool_min"]), "hp")
    if t["armor_total"]:
        add("armor_share", "%s armor: %d of %d pool (%.0f%%) discounts sustained fire"
            % (label, t["armor_total"], t["pool_total"], 100 * t["armor_share"]))
    if t["shield_total"]:
        add("shield_share", "%s recharging shields: %d of %d pool (%.0f%%) - rewards"
            " disengages" % (label, t["shield_total"], t["pool_total"], 100 * t["shield_share"]))
    if t["squishies"]:
        add("squish_count", "%s squish index: %d/%d picks at %d pool or less (%s) - dive"
            " bait if unprotected" % (label, t["squish_count"], t["size"], SQUISHY_POOL,
                                      ", ".join(t["squishies"])))
    if t["overhealth_total"]:
        add("overhealth_total", "%s overhealth supply: %g of burst insurance the healing"
            " number does not see" % (label, t["overhealth_total"]), "hp")
    add("dps_floor", "%s sustained damage floor: %g per second summed across the %d of %d"
        " kits that publish a rate" % (label, t["dps_floor"], t["dps_count"], t["size"]), "hp/s")
    if t["burst_max"]:
        add("burst_max", "%s burst ceiling: %s's %g in one hit"
            % (label, t["burst_hero"], t["burst_max"]), "hp")
    add("dmg_ults", "%s damage-ult census: %d of %d ultimates carry damage, %g summed"
        % (label, t["dmg_ults"], t["size"], t["ult_damage_total"]))
    if t["ult_cost_mean"]:
        add("ult_cost_mean", "%s mean ultimate cost: %.0f charge" % (label, t["ult_cost_mean"]))
    add("hitscan", "%s damage identity: %d hitscan, %d projectile, %d beam, %d melee"
        % (label, t["hitscan"], t["projectile"], t["beam"], t["melee"]))
    if t["aoe_count"]:
        add("aoe_count", "%s area-damage volume: %d kit pieces tagged area of effect"
            % (label, t["aoe_count"]))
    if t["range_median"]:
        add("range_median", "%s range profile: median longest reach %gm (from %gm to %gm)"
            " - reads as %s" % (label, t["range_median"], t["range_min"], t["range_max"],
                                "poke" if t["range_median"] >= 20 else "brawl"), "m")
    if t["dmg_amp"]:
        add("dmg_amp", "%s damage amplification: %d pick(s) boost someone's damage"
            % (label, t["dmg_amp"]))
    add("hps_floor", "%s healing floor: %g per second summed across published rates"
        % (label, t["hps_floor"]), "hp/s")
    if t["supports"]:
        add("heal_peak_supports", "%s healing supply: %g peak single heal across the"
            " supports vs the roster's ~%.0f two-support bench (ratio %.2f)%s"
            % (label, t["heal_peak_supports"], world.heal_bench, t["heal_ratio"],
               " - UNDER-HEALED" if t["supports"] >= 2 and t["heal_ratio"] < 0.75 else ""))
    add("lifelines", "%s lifelines: %d of %d picks carry any healing"
        % (label, t["lifelines"], t["size"]))
    if t["heal_amp"]:
        add("heal_amp", "%s healing amplification: %d pick(s)" % (label, t["heal_amp"]))
    if t["antiheal"]:
        add("antiheal", "%s anti-heal: %d pick(s) can shut healing off" % (label, t["antiheal"]))
    if t["cleanse"] or t["invuln"]:
        add("invuln", "%s defensive answers: %d invulnerability, %d cleanse"
            % (label, t["invuln"], t["cleanse"]))
    if t["cooldown_count"]:
        add("cooldown_median", "%s cooldown tempo: median %gs across %d cooldowns - %s"
            % (label, t["cooldown_median"], t["cooldown_count"],
               "high-uptime brawl tempo" if t["cooldown_median"] <= 8 else
               "cooldown-bound; pick your fights"), "s")
    add("cc_count", "%s crowd control: %d pick(s)%s" % (
        label, t["cc_count"], " - " + "; ".join(t["cc_tools"]) if t["cc_tools"] else ""))
    add("mobility_count", "%s engage/escape tools: %d pick(s)%s" % (
        label, t["mobility_count"],
        " - " + "; ".join(t["mobility_tools"]) if t["mobility_tools"] else ""))
    if t["flyers"]:
        add("flyers", "%s vertical threats: %d pick(s) fly" % (label, t["flyers"]))
    if t["barrier_hp"]:
        add("barrier_hp", "%s barriers: %g hp across %d pick(s)"
            % (label, t["barrier_hp"], t["barrier_count"]), "hp")
    if t["barrier_piercers"]:
        add("barrier_piercers", "%s barrier-piercers: %d pick(s) ignore barriers"
            % (label, t["barrier_piercers"]))
    if t["deployables"]:
        add("deployables", "%s deployables: %d pick(s)" % (label, t["deployables"]))
    if t["size"] >= 2:
        add("synergy_edges", "%s cohesion: %d of %d possible synergy edges (density %.2f,"
            " score sum %d)%s" % (label, t["synergy_edges"], t["size"] * (t["size"] - 1) // 2,
                                  t["synergy_density"], t["synergy_score"],
                                  " - " + "; ".join("%s+%s" % p[:2] for p in t["pairs"])
                                  if t["pairs"] else " - strangers so far"))
        add("core_size", "%s synergy core: the largest documented group is %d pick(s)"
            % (label, t["core_size"]))
        if t["isolated"]:
            add("isolated_count", "%s isolated pick(s): %s - no documented partner on the"
                " team" % (label, ", ".join(t["isolated"])))
    add("win_mean", "%s mean win rate (all ranks): %.1f%%" % (label, t["win_mean"]), "%")
    add("pick_mass", "%s pick-rate mass: %.1f summed - %s" % (
        label, t["pick_mass"], "meta-shaped; expect practiced answers"
        if t["pick_mass"] >= 30 else "off-meta lean; surprise value"))
    if m is not None and round(t["map_availability"], 2) != round(t["availability"], 2):
        add("map_availability", "%s availability on %s: %.0f%% chance every pick survives the"
            " ban screen here, from this map's ban rates" % (label, m.name,
                                                             100 * t["map_availability"]))
    add("availability", "%s expected availability: %.0f%% chance every pick survives the"
        " ban screen%s" % (label, 100 * t["availability"],
                           " (%s at %.0f%% ban)" % (t["max_ban_hero"], t["max_ban_rate"])
                           if t["max_ban_hero"] else ""))
    if t["rank_sensitive_count"]:
        add("rank_sensitive_count", "%s rank-sensitive picks: %d swing %g+ points across"
            " ranks" % (label, t["rank_sensitive_count"], RANK_SENSITIVE))
    if t["trend_sum"]:
        add("trend_sum", "%s trend since the previous capture: %+.1f win-rate points"
            " summed" % (label, t["trend_sum"]))
    if m is not None:
        add("map_win_mean", "%s on %s: mean win rate %.1f%% (pick mass %.1f)"
            % (label, m.name, t["map_win_mean"], t["map_pick_mass"]), "%")
        add("map_specialists", "%s map fit on %s: %d specialist(s), %d off-map, %d listed"
            " by counterpick here" % (label, m.name, t["map_specialists"], t["map_offmap"],
                                       t["map_strategy_hits"]))
    if enemies:
        add("coverage", "%s coverage: answers %d/%d %s picks%s" % (
            label, t["coverage"], len(enemies), side,
            "; still unanswered: " + ", ".join(t["unanswered"]) if t["unanswered"] else ""))
        add("net_edges", "%s net matchup: %d answer-edges into %s vs %d %s answer-edges"
            " back (%+d)" % (label, t["answer_edges"], side, t["exposure_edges"], side,
                             t["net_edges"]))
        if t["exposed"]:
            add("exposed_count", "%s exposed: %s answered by at least one %s pick; %d safe"
                % (label, ", ".join(t["exposed"]), side, t["safe_count"]))
        if t["double_covered"]:
            add("double_covered", "%s double-covered: %d %s pick(s) answered by two or"
                " more - ban-proof and swap-proof" % (label, t["double_covered"], side))
        if t["max_ban_hero"]:
            add("banproof_coverage", "%s ban-resilient coverage: without %s (%.0f%% ban)"
                " still %d/%d answered" % (label, t["max_ban_hero"], t["max_ban_rate"],
                                           t["banproof_coverage"], len(enemies)))
        for enemy_name, answerers in t["_answered"].items():
            if answerers:
                fs.add("team", team, "team.answer", "%s %s is answered by %s %s"
                       % (side, enemy_name, team, ", ".join(answerers)),
                       value=answerers, source="counters", team=team)


def _matchup_facts(fs, world, blue_t, red_t):
    x = compute.matchup_metrics(blue_t, red_t)

    def add(key, text, unit=None):
        fs.add("matchup", "blue vs red", "matchup." + key, text, value=x[key],
               unit=unit, source="derived:matchup." + key)

    add("pool_diff", "pool differential: blue's %d picks carry %d hp vs red's %d picks' %d"
        " - %+d raw material" % (blue_t["size"], blue_t["pool_total"], red_t["size"],
                                 red_t["pool_total"], x["pool_diff"]), "hp")
    add("dps_diff", "damage floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_t["dps_floor"], red_t["dps_floor"], x["dps_diff"]), "hp/s")
    add("hps_diff", "healing floor differential: blue %g/s vs red %g/s (%+g)"
        % (blue_t["hps_floor"], red_t["hps_floor"], x["hps_diff"]), "hp/s")
    add("burst_vs_heal", "burst-vs-heal, blue's way: blue's best hit %g vs red's best save %g"
        " - %s" % (blue_t["burst_max"], red_t["heal_peak_max"],
                   "a kill window exists through their healing" if x["burst_vs_heal"] > 0
                   else "their saves absorb the burst; stack or poke instead"))
    add("heal_vs_burst", "burst-vs-heal, red's way: red's best hit %g vs blue's best save %g"
        " - %s" % (red_t["burst_max"], blue_t["heal_peak_max"],
                   "blue's saves keep pace" if x["heal_vs_burst"] >= 0
                   else "red's burst outruns blue's save; do not trade in the open"))
    add("chew_time_ours", "chew-time floor, blue into red: %d pool / %g per second = %.1fs of"
        " unmitigated fire (no healing, no misses)" % (
            red_t["pool_total"], blue_t["dps_floor"], x["chew_time_ours"]), "s")
    add("chew_time_theirs", "chew-time floor, red into blue: %d pool / %g per second = %.1fs"
        % (blue_t["pool_total"], red_t["dps_floor"], x["chew_time_theirs"]), "s")
    add("tempo_diff", "tempo war: blue median cooldown %gs vs red %gs - %s" % (
        blue_t["cooldown_median"], red_t["cooldown_median"],
        "blue re-engages first; force fight frequency" if x["tempo_diff"] > 0 else
        "red re-engages first; make each fight decisive" if x["tempo_diff"] < 0 else
        "even tempo"), "s")
    add("range_diff", "poke war: blue median reach %gm vs red %gm - %s" % (
        blue_t["range_median"], red_t["range_median"],
        "blue outranges; open fights at distance" if x["range_diff"] > 0 else
        "red outranges; close fast or trade cover" if x["range_diff"] < 0 else "even reach"), "m")
    add("net_edges", "board net matchup: %d blue answer-edges into red vs %d red into blue"
        " (%+d) - %s" % (blue_t["answer_edges"], blue_t["exposure_edges"], x["net_edges"],
                         "the draft is ahead" if x["net_edges"] > 0 else
                         "the draft is behind; the open slots must swing it"
                         if x["net_edges"] < 0 else "dead even"))
    add("coverage_share", "coverage: blue answers %.0f%% of red; red answers %.0f%% of blue"
        % (100 * x["coverage_share"], 100 * x["exposure_share"]))
    if x["dive_pressure"]:
        add("dive_pressure", "dive pressure: %d red pick(s) carry engage tools - blue peel"
            " (%d crowd-control pick(s)) must hold" % (x["dive_pressure"], blue_t["cc_count"]))
    if x["flyers"]:
        add("flyers", "vertical threat: %d red flyer(s) vs %d blue hitscan pick(s)"
            % (x["flyers"], blue_t["hitscan"]))
    if x["barrier_need"]:
        add("barrier_need", "barrier war: red fields %g barrier hp vs %d blue barrier-piercer(s)"
            % (x["barrier_need"], blue_t["barrier_piercers"]), "hp")
    if x["antiheal_need"]:
        add("antiheal_need", "sustain war: red supports peak %g heal vs %d blue anti-heal"
            " pick(s)" % (x["antiheal_need"], blue_t["antiheal"]), "hp")
    if x["ult_threat"]:
        add("ult_threat", "ult threat: red's damage ultimates total %g vs %d blue"
            " invulnerability/cleanse answer(s)" % (x["ult_threat"], x["ult_answers"]), "hp")
    if x["style_lean_red"] or x["style_lean_blue"]:
        add("style_lean_red", "style war: red leans %s, blue leans %s" % (
            x["style_lean_red"] or "nothing yet", x["style_lean_blue"] or "nothing yet"))


def _playbook_record(fs, world, m):
    """S1..: the playbook's record - what it holds - never what the sources
    say, and not the constraints and heuristics themselves."""
    scope = PLAYBOOK_SCOPE
    for style in sorted(world.archetypes):
        for role, (slots, note) in world.archetypes[style].items():
            fs.add(scope, style, "playbook.archetype", "a %s comp wants %d %s: %s"
                   % (style, slots, role, note or ""), value={"style": style, "role": role,
                                                             "slots": slots},
                   source="comp_archetypes")
    if world.catalog_counts:
        c = world.catalog_counts
        fs.add(scope, "catalog", "playbook.catalog",
               "the playbook%s holds %d constraints, %d heuristics and %d assumptions"
               " (STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS)"
               % (" (%s, an experiment)" % world.playbook if world.playbook else "",
                  c.get("constraint", 0), c.get("heuristic", 0), c.get("assumption", 0)),
               value=c, source="strategies")
