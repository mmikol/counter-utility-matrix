"""Assemble the evidence a recommendation stands on - from the whole database.

Everything the model is shown is a numbered line - E1, E2, ... - each drawn
from named tables, so a pick can cite exactly what justified it and the
citation can be stored, joined, and inspected later. Nothing here calls a
model; this is the deterministic half of the inference layer, testable alone.

The dossier is comprehensive but shaped, not a dump: it opens with its own
vintage (when the rates were captured, under which patch and season), walks
the map, profiles each enemy's kit down to cooldowns and interaction flags,
performs the COUNTER = MAX[...] intersections itself, then profiles a
candidate pool - kit, rates, rank sensitivity, and who on the enemy team
answers them - before the playbook, the meta leaders, the operator's own
notes, and what this layer has recommended before.
"""

from data.heuristic.transform.counterpick.names import match_key

# Default thresholds for the derived heuristics. The playbook's
# heuristic_params table overrides these at build time (see _tuning), so
# tuning is a CSV edit and a reload, not a code change; these values only
# decide when the table is absent or a dial is missing from it. The whole
# catalog is documented in docs/heuristics.md and stored in the heuristics
# table.
COVERAGE_MIN = 2          # answers at least this many named enemies
SPECIALIST_DELTA = 2.5    # on-map win minus own baseline, percentage points
SLEEPER_WIN = 51.0        # wins at least this much on the map...
SLEEPER_PICK = 6.0        # ...while picked at most this much
PAIRING_LIMIT = 6
NET_LIMIT = 5             # top candidates by net matchup
TREND_POINTS = 1.5        # win-rate movement between snapshots worth naming
HEAL_MARGIN = 0.75        # supply below this share of the benchmark is a flag


class Evidence:
    """The numbered lines, in order, with where each came from."""

    def __init__(self):
        self.lines = []          # [(tag, source_table, text)]

    def add(self, table, text):
        tag = "E%d" % (len(self.lines) + 1)
        self.lines.append((tag, table, text))
        return tag

    def rendered(self):
        return "\n".join("[%s] %s" % (tag, text) for tag, _, text in self.lines)


def _rows(cx, sql, *args):
    return cx.execute(sql, args or None).fetchall()


def _trim(text, limit=110):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _pool_line(parts):
    return "; ".join(p for p in parts if p)


# --- sections ---------------------------------------------------------------

def _vintage(ev, cx):
    """The dossier states its own age before anything else."""
    for code, captured, patch, released, season in _rows(cx, """
            select src.code, ms.captured_at::date, p.name, p.released, se.name
            from meta_snapshots ms
            join sources src using(source_id)
            left join patches p using(patch_id)
            left join seasons se using(season_id)
            order by ms.captured_at desc limit 4"""):
        ev.add("meta_snapshots",
               "%s rates captured %s under %s (%s), %s"
               % (code, captured, patch or "an unknown patch",
                  released or "-", season or "unknown season"))
    newer = _rows(cx, """select p.name, p.released from patches p
        where p.released > (select coalesce(max(pp.released),'1900-01-01')
            from meta_snapshots ms join patches pp using(patch_id))
        order by p.released desc""")
    if newer:
        ev.add("patches",
               "WARNING: %d patch(es) shipped since the rates were captured,"
               " newest %s (%s) - treat rates as pre-patch" %
               (len(newer), newer[0][0], newer[0][1]))


def _hero_card(cx, hero_id, name):
    """One compact kit line per hero, from six HEROES tables."""
    role, sub, hp, sh, ar = _rows(cx, """
        select r.name, sr.name, h.health, h.shield, h.armor
        from heroes h join roles r using(role_id)
        join subroles sr on sr.subrole_id = h.subrole_id
        where h.hero_id=%s""", hero_id)[0]
    pool = "%dhp" % (hp or 0)
    if sh: pool += "+%dsh" % sh
    if ar: pool += "+%dar" % ar
    ults = _rows(cx, """select a.name, a.description from abilities a
        join ability_kinds k using(kind_id)
        where a.hero_id=%s and k.code='ultimate'""", hero_id)
    ult = "; ".join("ult %s: %s" % (n, _trim(d, 80)) for n, d in ults[:2])
    wtypes = [w for w, in _rows(cx, """select distinct c.weapon_type
        from weapon_configs c join weapons w using(weapon_id)
        where w.hero_id=%s and c.weapon_type is not null""", hero_id)]
    styles = [s for s, in _rows(
        cx, "select style from playstyle where hero_id=%s", hero_id)]
    return _pool_line([
        "%s - %s (%s), %s" % (name, role, sub, pool),
        "styles: %s" % ", ".join(styles) if styles else "",
        "weapon: %s" % ", ".join(wtypes) if wtypes else "",
        ult,
    ])


def _enemy_depth(ev, cx, hero_id, name):
    """Cooldowns and interaction flags: the counterplay windows."""
    cds = _rows(cx, """select a.name, s.value from ability_stats s
        join abilities a using(ability_id)
        join stat_keys k using(stat_key_id)
        where a.hero_id=%s and k.code='cooldown' and s.value is not null
        order by s.value desc limit 5""", hero_id)
    if cds:
        ev.add("ability_stats", "%s cooldowns: %s" % (name, ", ".join(
            "%s %gs" % (a, v) for a, v in cds)))
    flags = _rows(cx, """select a.name, k.code from ability_stats s
        join abilities a using(ability_id)
        join stat_keys k using(stat_key_id)
        where a.hero_id=%s and k.code like 'ignores_%%' and s.value = 1
        order by a.name""", hero_id)
    if flags:
        ev.add("ability_stats", "%s pierces defenses: %s" % (name, "; ".join(
            "%s ignores %s" % (a, c[8:]) for a, c in flags[:6])))


def _rank_sensitivity(cx, hero_id):
    row = _rows(cx, """select min(m.win_rate), max(m.win_rate)
        from hero_meta m join competitive_tiers t on t.tier_id=m.tier_id
        join meta_snapshots s using(snapshot_id)
        join sources src on src.source_id=s.source_id
        where m.hero_id=%s and t.code <> 'all' and src.code='blizzard'
        and m.win_rate is not null""", hero_id)
    if row and row[0][0] is not None and row[0][1] - row[0][0] >= 6:
        return float(row[0][0]), float(row[0][1])
    return None


def build(cx, map_name=None, enemies=(), allies=()):
    """-> (Evidence, context dict) for one recommendation request.

    allies are your locked picks: they get their own profiles and proven
    partners, are excluded from the candidate pool (they are not candidates,
    they are constraints), and draw WARNINGs when a known enemy answers them.
    Unknown names raise ValueError - a question about a hero we do not know
    is a question we must not quietly half-answer.
    """
    ev = Evidence()
    ctx = {"map_id": None, "map_name": None, "enemy_ids": [], "ally_ids": []}

    heroes = {match_key(n): (i, n) for n, i in _rows(
        cx, "select name, hero_id from heroes")}
    maps = {match_key(n): (i, n) for n, i in _rows(
        cx, "select name, map_id from maps")}

    unknown = [e for e in list(enemies) + list(allies)
               if match_key(e) not in heroes]
    if unknown:
        raise ValueError("unknown heroes: %s" % ", ".join(unknown))
    if map_name is not None:
        if match_key(map_name) not in maps:
            raise ValueError("unknown map: %s" % map_name)
        ctx["map_id"], ctx["map_name"] = maps[match_key(map_name)]
    ctx["enemy_ids"] = [heroes[match_key(e)][0] for e in enemies]
    ctx["ally_ids"] = [heroes[match_key(a)][0] for a in allies]
    enemy_set = set(ctx["enemy_ids"])
    ally_set = set(ctx["ally_ids"])

    _vintage(ev, cx)

    # --- the map, and what it rewards ---------------------------------
    if ctx["map_id"]:
        for mode, in _rows(cx, """select g.name from map_modes mm
                join game_modes g using(mode_id) where mm.map_id=%s""",
                ctx["map_id"]):
            ev.add("map_modes", "%s is a %s map" % (ctx["map_name"], mode))
        stages = [s for s, in _rows(cx, """select name from map_stages
                where map_id=%s order by position""", ctx["map_id"])]
        if stages:
            ev.add("map_stages", "%s stages: %s"
                   % (ctx["map_name"], ", ".join(stages)))
        for style, score, note in _rows(cx, """select style, score, note
                from map_playstyle where map_id=%s""", ctx["map_id"]):
            ev.add("map_playstyle", "%s rewards %s (%s/3): %s"
                   % (ctx["map_name"], style, score, note))
        for hero, win, pick in _rows(cx, """
                select h.name, m.win_rate, m.pick_rate from map_meta m
                join heroes h using(hero_id)
                join competitive_tiers t on t.tier_id=m.tier_id
                where m.map_id=%s and t.code='all' and m.win_rate is not null
                order by m.win_rate desc limit 10""", ctx["map_id"]):
            ev.add("map_meta", "on %s: %s wins %.1f%% (picked %.1f%%)"
                   % (ctx["map_name"], hero, win, pick))
        strugglers = _rows(cx, """
                select h.name, m.win_rate from map_meta m
                join heroes h using(hero_id)
                join competitive_tiers t on t.tier_id=m.tier_id
                where m.map_id=%s and t.code='all' and m.win_rate is not null
                order by m.win_rate asc limit 6""", ctx["map_id"])
        if strugglers:
            ev.add("map_meta", "struggle on %s: %s" % (ctx["map_name"],
                   ", ".join("%s (%.1f%%)" % s for s in strugglers)))
        for hero, pos in _rows(cx, """
                select h.name, ms.position from map_strategy ms
                join heroes h using(hero_id) where ms.map_id=%s
                order by ms.position""", ctx["map_id"]):
            ev.add("map_strategy", "%s is a top-%d map for %s"
                   % (ctx["map_name"], pos, hero))

    # --- each enemy: identity, kit depth, and their answers -------------
    for enemy_id in ctx["enemy_ids"]:
        name = heroes and _rows(cx, "select name from heroes where hero_id=%s",
                                enemy_id)[0][0]
        ev.add("heroes", "enemy " + _hero_card(cx, enemy_id, name))
        _enemy_depth(ev, cx, enemy_id, name)
        answers = [a for a, in _rows(cx, """
                select cb.name from counters c
                join heroes cb on cb.hero_id=c.countered_by_id
                where c.hero_id=%s order by cb.name""", enemy_id)]
        if answers:
            ev.add("counters", "%s is countered by: %s"
                   % (name, ", ".join(answers)))
        threatens = [t for t, in _rows(cx, """
                select h.name from counters c
                join heroes h on h.hero_id=c.hero_id
                where c.countered_by_id=%s order by h.name""", enemy_id)]
        if threatens:
            ev.add("counters", "%s themselves answers: %s"
                   % (name, ", ".join(threatens)))
        for _, rate in _rows(cx, """
                select h.name, m.ban_rate from hero_meta m
                join heroes h using(hero_id)
                join competitive_tiers t on t.tier_id=m.tier_id
                where h.hero_id=%s and t.code='all'
                and m.ban_rate is not null limit 1""", enemy_id):
            if rate and rate > 20:
                ev.add("hero_meta", "%s is banned in %.0f%% of lobbies -"
                       " may not stay on the enemy team" % (name, rate))

    # --- your locked picks: constraints, not candidates ------------------
    for ally_id in ctx["ally_ids"]:
        name = _rows(cx, "select name from heroes where hero_id=%s",
                     ally_id)[0][0]
        card = _hero_card(cx, ally_id, name)
        rates = _rows(cx, """
            select m.win_rate, m.pick_rate from hero_meta m
            join competitive_tiers t on t.tier_id=m.tier_id
            join meta_snapshots s using(snapshot_id)
            join sources src on src.source_id=s.source_id
            where m.hero_id=%s and t.code='all' and src.code='blizzard'
            and m.win_rate is not null limit 1""", ally_id)
        if rates:
            card += "; wins %.1f%% picks %.1f%%" % rates[0]
        spread = _rank_sensitivity(cx, ally_id)
        if spread:
            card += "; RANK-SENSITIVE %.1f%%-%.1f%% by rank" % spread
        ev.add("heroes", "your locked pick: " + card)
        _enemy_depth(ev, cx, ally_id, name)
        answers = [a for a, in _rows(cx, """
            select e.name from counters c
            join heroes e on e.hero_id = c.hero_id
            where c.countered_by_id=%s and c.hero_id = any(%s)
            order by e.name""", ally_id, list(enemy_set) or [0])]
        if answers:
            ev.add("counters", "your %s answers enemy %s"
                   % (name, ", ".join(answers)))
        partners = _rows(cx, """
            select case when s.hero_id=%s then o.name else h.name end,
                   s.score, s.note from synergies s
            join heroes h on h.hero_id=s.hero_id
            join heroes o on o.hero_id=s.other_id
            where %s in (s.hero_id, s.other_id)
            order by s.score desc nulls last limit 6""", ally_id, ally_id)
        partners = [(n, sc, nt) for n, sc, nt in partners
                    if n != name]
        if partners:
            ev.add("synergies", "proven partners for %s: %s" % (name,
                   "; ".join("%s (%s/3: %s)" % (n, sc, _trim(nt or "", 50))
                             for n, sc, nt in partners)))
        threats = [t for t, in _rows(cx, """
            select h.name from counters c
            join heroes h on h.hero_id=c.countered_by_id
            where c.hero_id=%s and c.countered_by_id = any(%s)""",
            ally_id, list(enemy_set) or [0])]
        if threats:
            ev.add("counters", "WARNING: your %s is answered by enemy %s -"
                   " the rest of the comp must cover for that"
                   % (name, ", ".join(threats)))

    # --- the playbook, intersected with the map and the enemy -----------
    #
    # The model's question is a join, so the dossier performs the join:
    # who answers this enemy AND holds up on this ground, who fits the
    # style this map rewards. The COUNTER = MAX[...] intersection, citable.
    if ctx["map_id"]:
        for style, in _rows(cx, """select style from map_playstyle
                where map_id=%s order by score desc nulls last""",
                ctx["map_id"]):
            fits = _rows(cx, """
                select h.name, m.win_rate from playstyle p
                join heroes h using(hero_id)
                join map_meta m on m.hero_id = p.hero_id and m.map_id = %s
                join competitive_tiers t on t.tier_id = m.tier_id
                where p.style = %s and t.code = 'all'
                  and m.win_rate is not null
                order by m.win_rate desc limit 6""", ctx["map_id"], style)
            if fits:
                ev.add("playstyle+map_meta",
                       "%s heroes who hold up on %s: %s" % (
                           style, ctx["map_name"], ", ".join(
                               "%s (%.1f%%)" % f for f in fits)))
        for enemy_id in ctx["enemy_ids"]:
            name = _rows(cx, "select name from heroes where hero_id=%s",
                         enemy_id)[0][0]
            joined = _rows(cx, """
                select h.name, m.win_rate from counters c
                join heroes h on h.hero_id = c.countered_by_id
                join map_meta m on m.hero_id = c.countered_by_id
                    and m.map_id = %s
                join competitive_tiers t on t.tier_id = m.tier_id
                where c.hero_id = %s and t.code = 'all'
                  and m.win_rate is not null
                order by m.win_rate desc limit 6""",
                ctx["map_id"], enemy_id)
            if joined:
                ev.add("counters+map_meta",
                       "answers to %s that also win on %s: %s" % (
                           name, ctx["map_name"], ", ".join(
                               "%s (%.1f%%)" % j for j in joined)))

    # --- the candidate pool: who the comp will likely come from ---------
    #
    # Union of everyone the intersections and playbook surfaced, profiled
    # properly: kit, current rates, rank sensitivity, and - crucially -
    # which KNOWN ENEMY answers them, so the model does not walk a pick
    # into a counter that is already on the field.
    pool = {}
    for enemy_id in ctx["enemy_ids"]:
        for hid, in _rows(cx, """select countered_by_id from counters
                where hero_id=%s""", enemy_id):
            pool[hid] = True
    if ctx["map_id"]:
        for hid, in _rows(cx, """select hero_id from map_strategy
                where map_id=%s""", ctx["map_id"]):
            pool[hid] = True
        for hid, in _rows(cx, """
                select m.hero_id from map_meta m
                join competitive_tiers t on t.tier_id=m.tier_id
                where m.map_id=%s and t.code='all'
                order by m.win_rate desc nulls last limit 12""",
                ctx["map_id"]):
            pool[hid] = True
    for hid, in _rows(cx, "select hero_id from synergies union"
                          " select other_id from synergies"):
        pool.setdefault(hid, True)
    pool = [h for h in pool if h not in enemy_set and h not in ally_set]

    ranked = _rows(cx, """
        select m.hero_id, h.name, m.win_rate, m.pick_rate from hero_meta m
        join heroes h using(hero_id)
        join competitive_tiers t on t.tier_id=m.tier_id
        join meta_snapshots s using(snapshot_id)
        join sources src on src.source_id=s.source_id
        where t.code='all' and src.code='blizzard'
        and m.hero_id = any(%s) order by m.win_rate desc nulls last
        limit 18""", pool)
    for hid, name, win, pick in ranked:
        card = _hero_card(cx, hid, name)
        if win is not None:
            card += "; wins %.1f%% picks %.1f%%" % (win, pick)
        spread = _rank_sensitivity(cx, hid)
        if spread:
            card += "; RANK-SENSITIVE %.1f%%-%.1f%% by rank" % spread
        ev.add("candidates", card)
        threats = [t for t, in _rows(cx, """
            select h.name from counters c join heroes h on h.hero_id=c.countered_by_id
            where c.hero_id=%s and c.countered_by_id = any(%s)""",
            hid, list(enemy_set))]
        if threats:
            ev.add("counters", "CAUTION: %s is answered by enemy %s"
                   % (name, ", ".join(threats)))

    _derived_heuristics(ev, cx, ctx, [h for h, *_ in ranked],
                      enemy_set, ctx["ally_ids"])

    # --- who plays which style, roster-wide -----------------------------
    for style, names in _rows(cx, """
            select style, string_agg(h.name, ', ' order by h.name)
            from playstyle p join heroes h using(hero_id)
            group by style order by style"""):
        ev.add("playstyle", "%s heroes: %s" % (style, names))

    # --- role passives: what each subrole grants for free ---------------
    for role, sub, passive in _rows(cx, """
            select r.name, sr.name, sr.passive_description from subroles sr
            join roles r using(role_id)
            where coalesce(sr.passive_description,'') <> ''
            order by r.name, sr.name"""):
        ev.add("subroles", "%s / %s passive: %s" % (role, sub, _trim(passive, 90)))

    # --- what a composition is ----------------------------------------
    for style, role, slots, note in _rows(cx, """
            select a.style, r.name, a.slots, a.note from comp_archetypes a
            join roles r using(role_id) order by a.style, r.name"""):
        ev.add("comp_archetypes", "a %s comp wants %d %s: %s"
               % (style, slots, role.lower(), note))

    # --- who works with whom (the authored playbook, whole) ------------
    for a, b, score, note in _rows(cx, """
            select h.name, o.name, s.score, s.note from synergies s
            join heroes h on h.hero_id=s.hero_id
            join heroes o on o.hero_id=s.other_id order by s.score desc nulls last"""):
        ev.add("synergies", "%s + %s (%s/3): %s"
               % (a, b, score if score is not None else "?", note or "no note"))

    # --- current meta leaders and ban pressure ---------------------------
    for label, order in (("highest win rates", "m.win_rate desc"),
                         ("most picked", "m.pick_rate desc")):
        rows = _rows(cx, """
            select h.name, m.win_rate, m.pick_rate from hero_meta m
            join heroes h using(hero_id)
            join competitive_tiers t on t.tier_id=m.tier_id
            join meta_snapshots s using(snapshot_id)
            join sources src on src.source_id=s.source_id
            where t.code='all' and src.code='blizzard'
            and m.win_rate is not null order by %s limit 8""" % order)
        ev.add("hero_meta", "%s right now: %s" % (label, ", ".join(
            "%s (%.1f%%/%.1f%%)" % r for r in rows)))
    for hero, rate in _rows(cx, """
            select h.name, m.ban_rate from hero_meta m
            join heroes h using(hero_id)
            join competitive_tiers t on t.tier_id=m.tier_id
            join meta_snapshots s using(snapshot_id)
            join sources src on src.source_id=s.source_id
            where t.code='all' and src.code='blizzard' and m.ban_rate > 25
            order by m.ban_rate desc limit 6"""):
        ev.add("hero_meta", "%s is banned in %.0f%% of lobbies - do not build"
               " a comp that dies with the ban" % (hero, rate))

    # --- the operator's own strategy notes, citable ----------------------
    for title, body in _rows(
            cx, "select title, body from strategies order by title"):
        ev.add("strategies", "operator note '%s': %s"
               % (title, " ".join(body.split())))

    # --- what this layer has said before ---------------------------------
    history = _rows(cx, """
        select r.rec_id, r.playstyle, r.reasoning,
               string_agg(h.name, ', ' order by p.position)
        from recommendations r
        join recommendation_picks p using(rec_id)
        join heroes h using(hero_id)
        where (%s::int is null or r.map_id = %s)
        group by r.rec_id order by r.rec_id desc limit 2""",
        ctx["map_id"], ctx["map_id"])
    for rec_id, playstyle, reasoning, picks in history:
        ev.add("recommendations",
               "previously recommended (#%d, %s): %s - %s"
               % (rec_id, playstyle, picks, _trim(reasoning, 90)))

    return ev, ctx


def _tuning(cx):
    """The dial panel: heuristic_params rows override the module defaults."""
    tune = {"COVERAGE_MIN": COVERAGE_MIN,
            "SPECIALIST_DELTA": SPECIALIST_DELTA,
            "SLEEPER_WIN": SLEEPER_WIN, "SLEEPER_PICK": SLEEPER_PICK,
            "PAIRING_LIMIT": PAIRING_LIMIT, "NET_LIMIT": NET_LIMIT,
            "TREND_POINTS": TREND_POINTS, "HEAL_MARGIN": HEAL_MARGIN}
    if _rows(cx, "select to_regclass('heuristic_params')")[0][0]:
        for code, value in _rows(cx,
                                 "select code, value from heuristic_params"):
            if code in tune:
                tune[code] = float(value)
    return tune


def _derived_heuristics(ev, cx, ctx, cand_ids, enemy_set, ally_ids):
    """Analytics the database computes so the model does not have to.

    Every line here is DERIVED - a formula over tables, not a row from one -
    and tagged `derived:<name>`. The catalog lives in the playbook's
    heuristics table and docs/heuristics.md; the thresholds come from
    _tuning.
    """
    avail = list(dict.fromkeys(list(ally_ids) + cand_ids))
    if not avail:
        return
    tune = _tuning(cx)
    names = dict(_rows(cx, "select hero_id, name from heroes"))
    ally_mark = {h: "*" for h in ally_ids}

    # coverage: how many of the named enemies each available hero answers
    if len(enemy_set) >= tune["COVERAGE_MIN"]:
        cover = _rows(cx, """
            select c.countered_by_id, count(distinct c.hero_id),
                   string_agg(distinct e.name, ', ')
            from counters c join heroes e on e.hero_id = c.hero_id
            where c.hero_id = any(%s) and c.countered_by_id = any(%s)
            group by 1 having count(distinct c.hero_id) >= %s
            order by 2 desc""", list(enemy_set), avail,
            tune["COVERAGE_MIN"])
        for hid, k, covered in cover[:6]:
            ev.add("derived:coverage", "coverage: %s%s answers %d/%d named"
                   " enemies (%s)" % (names[hid], ally_mark.get(hid, ""),
                                      k, len(enemy_set), covered))

    # safe picks: candidates no named enemy answers
    if enemy_set:
        answered = {h for h, in _rows(cx, """
            select distinct hero_id from counters
            where hero_id = any(%s) and countered_by_id = any(%s)""",
            avail, list(enemy_set))}
        safe = [names[h] for h in cand_ids if h not in answered][:10]
        if safe:
            ev.add("derived:safe", "unanswered by this enemy comp: %s"
                   % ", ".join(safe))

    # strongest pairings actually available to this draft
    pairs = _rows(cx, """
        select s.hero_id, s.other_id, s.score, s.note from synergies s
        where s.hero_id = any(%s) and s.other_id = any(%s)
        order by s.score desc nulls last limit %s""",
        avail, avail, int(tune["PAIRING_LIMIT"]))
    for a, b, score, note in pairs:
        ev.add("derived:pairings", "available pairing: %s%s + %s%s (%s/3): %s"
               % (names[a], ally_mark.get(a, ""), names[b],
                  ally_mark.get(b, ""), score, _trim(note or "", 60)))

    # draft skeletons: greedy archetype fill from what is actually available
    prof = {}
    for hid, role, win_all in _rows(cx, """
        select h.hero_id, r.name, m.win_rate from heroes h
        join roles r using(role_id)
        left join hero_meta m on m.hero_id = h.hero_id
        left join competitive_tiers t on t.tier_id = m.tier_id
            and t.code = 'all'
        left join meta_snapshots ms on ms.snapshot_id = m.snapshot_id
        left join sources src on src.source_id = ms.source_id
            and src.code = 'blizzard'
        where h.hero_id = any(%s)""", avail):
        cur = prof.setdefault(hid, [role, set(), None, None])
        if win_all is not None:
            cur[2] = max(cur[2] or 0, float(win_all))
    for hid, style in _rows(cx,
            "select hero_id, style from playstyle where hero_id = any(%s)",
            avail):
        if hid in prof:
            prof[hid][1].add(style)
    if ctx["map_id"]:
        for hid, w in _rows(cx, """select m.hero_id, m.win_rate from map_meta m
            join competitive_tiers t on t.tier_id=m.tier_id
            where m.map_id=%s and t.code='all' and m.hero_id = any(%s)""",
            ctx["map_id"], avail):
            if w is not None:
                prof[hid][3] = float(w)

    if ctx["map_id"]:
        styles = [s for s, in _rows(cx, """select style from map_playstyle
            where map_id=%s order by score desc nulls last""", ctx["map_id"])]
    else:
        styles = [s for s, in _rows(
            cx, "select distinct style from comp_archetypes order by 1")]
    for style in styles:
        slots = _rows(cx, """select r.name, a.slots from comp_archetypes a
            join roles r using(role_id) where a.style=%s""", style)
        if not slots:
            continue
        used, parts, wins, gap = set(), [], [], False
        for role, n in slots:
            chosen = [h for h in ally_ids
                      if prof.get(h, [None])[0] == role][:n]
            rest = sorted(
                (h for h in cand_ids
                 if h not in used and h not in chosen
                 and prof.get(h, [None])[0] == role),
                key=lambda h: (style in prof[h][1],
                               prof[h][3] if prof[h][3] is not None
                               else (prof[h][2] or 0)),
                reverse=True)
            chosen += rest[:n - len(chosen)]
            used.update(chosen)
            if len(chosen) < n:
                gap = True
            parts.append("%s %s" % (role, ", ".join(
                names[h] + ally_mark.get(h, "") for h in chosen) or "(gap)"))
            wins += [prof[h][3] if prof[h][3] is not None else prof[h][2]
                     for h in chosen if prof.get(h)]
        wins = [w for w in wins if w is not None]
        avg = " - avg win %.1f%%" % (sum(wins) / len(wins)) if wins else ""
        ev.add("derived:skeleton", "draft skeleton (%s): %s%s%s"
               % (style, " | ".join(parts), avg,
                  " [has gaps]" if gap else ""))

    # map specialists and sleepers: this ground vs their own baseline
    if ctx["map_id"]:
        for name, delta in _rows(cx, """
            select h.name, round(m.win_rate - hm.win_rate, 1) from map_meta m
            join heroes h using(hero_id)
            join competitive_tiers t on t.tier_id=m.tier_id and t.code='all'
            join hero_meta hm on hm.hero_id = m.hero_id
            join competitive_tiers t2 on t2.tier_id=hm.tier_id and t2.code='all'
            join meta_snapshots ms2 on ms2.snapshot_id = hm.snapshot_id
            join sources s2 on s2.source_id = ms2.source_id
                and s2.code='blizzard'
            where m.map_id=%s and m.win_rate is not null
              and hm.win_rate is not null
              and m.win_rate - hm.win_rate >= %s
            order by 2 desc limit 6""", ctx["map_id"],
            tune["SPECIALIST_DELTA"]):
            ev.add("derived:specialists", "map specialist: %s runs %+.1f here"
                   " vs their own overall baseline" % (name, delta))
        for name, win, pick in _rows(cx, """
            select h.name, m.win_rate, m.pick_rate from map_meta m
            join heroes h using(hero_id)
            join competitive_tiers t on t.tier_id=m.tier_id and t.code='all'
            where m.map_id=%s and m.win_rate >= %s and m.pick_rate <= %s
            order by m.win_rate desc limit 5""",
            ctx["map_id"], tune["SLEEPER_WIN"],
            tune["SLEEPER_PICK"]):
            ev.add("derived:sleepers", "sleeper here: %s wins %.1f%% while"
                   " picked only %.1f%% - the lobby underrates this"
                   % (name, win, pick))

    _team_heuristics(ev, cx, ctx, cand_ids, enemy_set, ally_ids, names,
                     ally_mark, tune)
    _breadth_heuristics(ev, cx, ctx, cand_ids, enemy_set, ally_ids, names,
                        tune)

    # what the enemy comp leans toward
    if len(enemy_set) >= 2:
        lean = _rows(cx, """select style, count(*) from playstyle
            where hero_id = any(%s) group by 1 order by 2 desc""",
            list(enemy_set))
        if lean:
            ev.add("derived:lean", "enemy comp style profile: %s%s" % (
                ", ".join("%s %d/%d" % (s, n, len(enemy_set))
                          for s, n in lean),
                " - leans %s" % lean[0][0]
                if lean[0][1] > len(enemy_set) / 2 else ""))


def _breadth_heuristics(ev, cx, ctx, cand_ids, enemy_set, ally_ids, names,
                        tune):
    """The wide tranche of the catalog: kit arithmetic, matchup algebra,
    synergy-graph structure, and map/meta screens - one line each, exact
    definitions in the heuristics table rows they are numbered by."""
    E, A = list(enemy_set), list(ally_ids)

    def kit_max(ids, key):
        """{hero_id: max value of `key` across ability and weapon stats}."""
        if not ids:
            return {}
        return dict(_rows(cx, """
            select hero_id, max(v) from (
                select a.hero_id, s.value v from ability_stats s
                join abilities a using(ability_id)
                join stat_keys k using(stat_key_id)
                where k.code = %s and s.value is not null
                  and a.hero_id = any(%s)
                union all
                select w.hero_id, s.value from weapon_stats s
                join weapon_configs c on c.config_id = s.config_id
                join weapons w on w.weapon_id = c.weapon_id
                join stat_keys k on k.stat_key_id = s.stat_key_id
                where k.code = %s and s.value is not null
                  and w.hero_id = any(%s)) t group by 1""",
            key, ids, key, ids))

    pools = dict(_rows(cx, """select hero_id, coalesce(health,0)
        + coalesce(shield,0) + coalesce(armor,0) from heroes
        where hero_id = any(%s)""", list(dict.fromkeys(A + E + cand_ids))))

    # --- enemy-facing kit arithmetic ------------------------------------
    if E:
        antiheal = _rows(cx, """
            select h.name, a.name, min(s.value) from ability_stats s
            join abilities a using(ability_id)
            join heroes h on h.hero_id = a.hero_id
            join stat_keys k using(stat_key_id)
            where k.code='healing_mod' and s.value < 0 and a.hero_id = any(%s)
            group by 1, 2""", E)
        if antiheal:
            ev.add("derived:antiheal", "anti-heal on the field: %s - a"
                   " sustain comp answers this or dies to it" % "; ".join(
                       "%s's %s (%g%% healing)" % r for r in antiheal))
        ebig = kit_max(E, "damage")
        if ebig and A:
            top_e = max(ebig, key=lambda h: ebig[h])
            weakest = min(A, key=lambda h: pools.get(h, 0))
            ev.add("derived:burstsurvive",
                   "focus-fire check: your weakest locked pool is %s at %d"
                   " vs %s's biggest damage figure %g"
                   % (names[weakest], pools.get(weakest, 0), names[top_e],
                      ebig[top_e]))
            dead = [names[h] for h in A if pools.get(h, 0) <= ebig[top_e]]
            if dead:
                ev.add("derived:oneshot", "one-shot exposure: %s can be"
                       " deleted by a single %g-damage window from %s"
                       % (", ".join(dead), ebig[top_e], names[top_e]))
        if A:
            abig = kit_max(A, "damage")
            if abig:
                top_a = max(abig, key=lambda h: abig[h])
                soft = min(E, key=lambda h: pools.get(h, 9999))
                ev.add("derived:burstceiling",
                       "your burst ceiling: %s's %g vs their softest pool"
                       " %s at %d - %s"
                       % (names[top_a], abig[top_a], names[soft],
                          pools.get(soft, 0),
                          "a kill window exists"
                          if abig[top_a] >= pools.get(soft, 0)
                          else "no solo kill window; stack damage"))

    # --- locked-team kit arithmetic --------------------------------------
    if A:
        subs = _rows(cx, """select sr.name, count(*) from heroes h
            join subroles sr using(subrole_id)
            where h.hero_id = any(%s) group by 1 order by 2 desc, 1""", A)
        ev.add("derived:shape", "subrole balance: %d distinct jobs across"
               " %d locked picks (%s)" % (len(subs), len(A), ", ".join(
                   "%s x%d" % s if s[1] > 1 else s[0] for s in subs)))
        ev.add("derived:teampool", "team effective HP locked in: %d across"
               " %d picks" % (sum(pools.get(h, 0) for h in A), len(A)))
        squishy = [names[h] for h in A if pools.get(h, 0) <= 225]
        if squishy:
            ev.add("derived:squish", "squish index: %d/%d locked picks at"
                   " 225 pool or less (%s) - dive bait if unprotected"
                   % (len(squishy), len(A), ", ".join(squishy)))
        weakest = min(A, key=lambda h: pools.get(h, 0))
        ev.add("derived:weakestlink", "weakest link: %s at %d pool - focus"
               " fire finds the minimum, not the average"
               % (names[weakest], pools.get(weakest, 0)))
        over = kit_max(A, "overhealth")
        if over:
            ev.add("derived:overhealth", "overhealth supply: %g of burst"
                   " insurance the healing number does not see (%s)"
                   % (sum(float(v) for v in over.values()), ", ".join(
                       "%s %g" % (names[h], v) for h, v in over.items())))
        wt = _rows(cx, """select w.hero_id, c.weapon_type from weapon_configs c
            join weapons w using(weapon_id)
            where w.hero_id = any(%s) and c.weapon_type is not null""", A)
        mix = {}
        for h, t in wt:
            kind = ("hitscan" if "hitscan" in t else
                    "beam" if "beam" in t else
                    "melee" if "melee" in t else "projectile")
            mix.setdefault(kind, set()).add(h)
        if mix:
            ev.add("derived:dmgmix", "damage identity locked in: %s"
                   % "; ".join("%s: %s" % (k, ", ".join(
                       sorted(names[h] for h in v)))
                       for k, v in sorted(mix.items())))
            hs = mix.get("hitscan", set())
            ev.add("derived:hitscan", "hitscan census: %d locked (%s) - the"
                   " measured proxy for anti-air" % (len(hs), ", ".join(
                       sorted(names[h] for h in hs)) or "none"))
        rng = kit_max(A, "range")
        if rng:
            vals = sorted(float(v) for v in rng.values())
            med = vals[len(vals) // 2]
            ev.add("derived:rangeprofile", "range profile: %s - median %gm"
                   " reads as %s" % ("; ".join(
                       "%s %gm" % (names[h], v) for h, v in rng.items()),
                       med, "poke" if med >= 20 else "brawl"))
        cds = _rows(cx, """select s.value from ability_stats s
            join abilities a using(ability_id)
            join stat_keys k using(stat_key_id)
            where k.code='cooldown' and s.value is not null
              and a.hero_id = any(%s)""", A)
        if cds:
            vals = sorted(float(v) for v, in cds)
            med = vals[len(vals) // 2]
            ev.add("derived:cdtempo", "cooldown tempo: median %gs across %d"
                   " locked cooldowns - %s" % (med, len(vals),
                   "high-uptime brawl tempo" if med <= 8
                   else "cooldown-bound; pick your fights"))
        ults = _rows(cx, """
            select h.name, a.name, max(s.value) from abilities a
            join ability_kinds k using(kind_id)
            join heroes h on h.hero_id = a.hero_id
            left join ability_stats s on s.ability_id = a.ability_id
                and s.stat_key_id = (select stat_key_id from stat_keys
                                     where code='damage')
            where k.code='ultimate' and a.hero_id = any(%s)
            group by 1, 2""", A)
        dmg_ults = [(h, u, v) for h, u, v in ults if v is not None]
        ev.add("derived:ultcensus", "damage-ult census: %d of %d locked"
               " ultimates carry damage%s" % (len(dmg_ults), len(ults),
               " (%s)" % ", ".join("%s's %s" % (h, u)
                                   for h, u, _ in dmg_ults)
               if dmg_ults else ""))
        if dmg_ults:
            ev.add("derived:ultburst", "ult burst stack: %g total - the"
                   " ceiling a coordinated all-in is actually claiming"
                   % sum(float(v) for _, _, v in dmg_ults))
        bans = dict(_rows(cx, """
            select m.hero_id, m.ban_rate from hero_meta m
            join competitive_tiers t on t.tier_id=m.tier_id
            join meta_snapshots s using(snapshot_id)
            join sources src on src.source_id=s.source_id
            where t.code='all' and src.code='blizzard'
              and m.hero_id = any(%s)""", A))
        avail = 1.0
        for h in A:
            avail *= 1.0 - float(bans.get(h) or 0) / 100.0
        ev.add("derived:availability", "expected availability: %.0f%% chance"
               " every locked pick survives the ban screen" % (avail * 100))
        picks_ = _rows(cx, """
            select coalesce(sum(m.pick_rate), 0) from hero_meta m
            join competitive_tiers t on t.tier_id=m.tier_id
            join meta_snapshots s using(snapshot_id)
            join sources src on src.source_id=s.source_id
            where t.code='all' and src.code='blizzard'
              and m.hero_id = any(%s)""", A)
        ev.add("derived:pickmass", "pick-rate mass: %.1f summed - %s"
               % (float(picks_[0][0]),
                  "meta-shaped; expect practiced answers"
                  if float(picks_[0][0]) >= 30
                  else "off-meta lean; surprise value"))

    # --- synergy-graph structure over the locked picks --------------------
    if len(A) >= 2:
        edges = _rows(cx, """select h.name, o.name, s.score from synergies s
            join heroes h on h.hero_id=s.hero_id
            join heroes o on o.hero_id=s.other_id
            where s.hero_id = any(%s) and s.other_id = any(%s)""", A, A)
        possible = len(A) * (len(A) - 1) // 2
        score_sum = sum(int(sc) for _, _, sc in edges if sc is not None)
        ev.add("derived:cohesion", "cohesion: %d of %d possible synergy"
               " edges among locked picks (density %.2f, score sum %d)%s"
               % (len(edges), possible, len(edges) / possible, score_sum,
                  " - " + "; ".join("%s+%s" % (a, b) for a, b, _ in edges)
                  if edges else ""))
        paired = {n for a, b, _ in edges for n in (a, b)}
        loners = [names[h] for h in A if names[h] not in paired]
        if loners:
            ev.add("derived:isolated", "isolated pick: %s has no documented"
                   " partner among your locked picks - a solo act, name the"
                   " plan for them" % ", ".join(loners))
    if A and cand_ids:
        reach = _rows(cx, """
            select c.h, count(*) from (
                select case when s.hero_id = any(%s) then s.other_id
                            else s.hero_id end h
                from synergies s
                where (s.hero_id = any(%s)) <> (s.other_id = any(%s))) c
            where c.h = any(%s) group by 1 order by 2 desc limit 6""",
            A, A, A, cand_ids)
        if reach:
            ev.add("derived:synreach", "candidates who plug into your locked"
                   " picks: %s" % ", ".join(
                       "%s (%d edge%s)" % (names[h], n, "" if n == 1 else "s")
                       for h, n in reach))

    # --- coverage algebra beyond the raw counts ---------------------------
    if E and A:
        cover = _rows(cx, """select c.hero_id, c.countered_by_id from counters c
            where c.hero_id = any(%s) and c.countered_by_id = any(%s)""",
            E, A)
        if cover:
            distinct = {e for e, _ in cover}
            ev.add("derived:coverbreadth", "counter diversity: %d distinct"
                   " enemies answered through %d answer-edges - redundancy"
                   " is the difference" % (len(distinct), len(cover)))
            twice = sorted(names[e] for e in distinct
                           if sum(1 for x, _ in cover if x == e) >= 2)
            if twice:
                ev.add("derived:doublecover", "double-covered: %s answered"
                       " by two or more of your picks - ban-proof and"
                       " swap-proof" % ", ".join(twice))
            bans = dict(_rows(cx, """
                select m.hero_id, m.ban_rate from hero_meta m
                join competitive_tiers t on t.tier_id=m.tier_id
                join meta_snapshots s using(snapshot_id)
                join sources src on src.source_id=s.source_id
                where t.code='all' and src.code='blizzard'
                  and m.hero_id = any(%s)""", [a for _, a in cover]))
            answerers = {a for _, a in cover}
            if answerers:
                risky = max(answerers, key=lambda h: float(bans.get(h) or 0))
                left = {e for e, a in cover if a != risky}
                ev.add("derived:banproof", "ban-resilient coverage: without"
                       " %s (your highest-ban answer, %.0f%%) you still"
                       " answer %d/%d named enemies"
                       % (names[risky], float(bans.get(risky) or 0),
                          len(left), len(E)))

    # --- map and meta screens over the pool --------------------------------
    if ctx["map_id"]:
        top2 = _rows(cx, """select style, score from map_playstyle
            where map_id=%s and score is not null
            order by score desc limit 2""", ctx["map_id"])
        if len(top2) == 2:
            margin = int(top2[0][1]) - int(top2[1][1])
            ev.add("derived:styleconsensus", "style consensus: %s by %d over"
                   " %s - %s" % (top2[0][0], margin, top2[1][0],
                   "bind the skeleton to it" if margin >= 2
                   else "contested read; argue the style choice"))
        offmap = _rows(cx, """
            select h.name, mm.win_rate, hm.win_rate from map_meta mm
            join hero_meta hm on hm.hero_id = mm.hero_id
            join competitive_tiers t on t.tier_id = mm.tier_id
            join competitive_tiers t2 on t2.tier_id = hm.tier_id
            join meta_snapshots s on s.snapshot_id = hm.snapshot_id
            join sources src on src.source_id = s.source_id
            join heroes h on h.hero_id = mm.hero_id
            where mm.map_id=%s and t.code='all' and t2.code='all'
              and src.code='blizzard' and mm.hero_id = any(%s)
              and mm.win_rate is not null and hm.win_rate is not null
              and mm.win_rate <= hm.win_rate - %s
            order by hm.win_rate - mm.win_rate desc limit 6""",
            ctx["map_id"], cand_ids, tune["SPECIALIST_DELTA"])
        for name, mwin, owin in offmap:
            ev.add("derived:offmap", "off-map liability: %s runs %.1f%% here"
                   " vs %.1f%% overall - comfort is measurably underperforming"
                   % (name, mwin, owin))
        overrated = _rows(cx, """
            select h.name, m.win_rate, m.pick_rate from map_meta m
            join competitive_tiers t on t.tier_id=m.tier_id
            join heroes h using(hero_id)
            where m.map_id=%s and t.code='all' and m.win_rate < 50
              and m.pick_rate >= %s order by m.pick_rate desc limit 5""",
            ctx["map_id"], 2 * tune["SLEEPER_PICK"])
        for name, win, pick in overrated:
            ev.add("derived:overrated", "over-picked underperformer: %s at"
                   " %.1f%% pick but %.1f%% win here - do not copy the lobby"
                   % (name, pick, win))


def _team_heuristics(ev, cx, ctx, cand_ids, enemy_set, ally_ids, names,
                     ally_mark, tune):
    """Comp-shape, sustain, and matchup arithmetic over the locked picks."""
    E, A = list(enemy_set), list(ally_ids)

    # net matchup: answers minus exposures against the named enemies
    if E and cand_ids:
        net = _rows(cx, """
            with ans as (select countered_by_id h, count(*) n from counters
                         where hero_id = any(%s) and countered_by_id = any(%s)
                         group by 1),
                 exp as (select hero_id h, count(*) n from counters
                         where countered_by_id = any(%s) and hero_id = any(%s)
                         group by 1)
            select c.h, coalesce(a.n,0), coalesce(x.n,0)
            from (select unnest(%s::int[]) h) c
            left join ans a on a.h = c.h left join exp x on x.h = c.h
            order by coalesce(a.n,0) - coalesce(x.n,0) desc,
                     coalesce(a.n,0) desc limit %s""",
            E, cand_ids, E, cand_ids, cand_ids,
            int(tune["NET_LIMIT"]))
        parts = ["%s %+d (answers %d, answered-by %d)"
                 % (names[h], a - x, a, x) for h, a, x in net]
        ev.add("derived:netmatchup",
               "net matchup vs this enemy comp: " + "; ".join(parts))

    if not A:
        return

    # team coverage of the locked picks, and who is still unanswered
    if E:
        covered = {e for e, in _rows(cx, """
            select distinct hero_id from counters
            where hero_id = any(%s) and countered_by_id = any(%s)""", E, A)}
        ev.add("derived:teamcover",
               "your locked picks answer %d/%d named enemies%s"
               % (len(covered), len(E),
                  "; still unanswered: " + ", ".join(
                      names[e] for e in E if e not in covered)
                  if len(covered) < len(E) else ""))

    # role shape: counts, and the flags that decide games
    role_of = dict(_rows(cx, """select h.hero_id, r.code from heroes h
        join roles r using(role_id) where h.hero_id = any(%s)""", A))
    counts = {"tank": 0, "damage": 0, "support": 0}
    for h in A:
        counts[role_of[h]] = counts.get(role_of[h], 0) + 1
    flags = []
    if counts["tank"] == 0:
        flags.append("TANKLESS - no one makes space")
    if counts["tank"] >= 2:
        flags.append("double tank")
    if counts["damage"] >= 3:
        flags.append("triple+ DPS - wins fights it starts, loses attrition")
    if counts["support"] == 0:
        flags.append("NO SUPPORT - sustain is spawn-door only")
    if counts["support"] == 1:
        flags.append("solo heal - protect them or run self-sustain")
    open_slots = 5 - len(A)
    ev.add("derived:shape",
           "locked shape: %d tank / %d dps / %d support, %d slot%s open%s"
           % (counts["tank"], counts["damage"], counts["support"],
              open_slots, "" if open_slots == 1 else "s",
              " - " + "; ".join(flags) if flags else ""))
    if ctx["map_id"]:
        top = _rows(cx, """select style from map_playstyle where map_id=%s
            order by score desc nulls last limit 1""", ctx["map_id"])
        if top:
            slots = dict(_rows(cx, """select r.code, a.slots
                from comp_archetypes a join roles r using(role_id)
                where a.style=%s""", top[0][0]))
            if slots:
                dev = sum(max(0, counts.get(r, 0) - n)
                          for r, n in slots.items())
                if dev:
                    ev.add("derived:shape",
                           "shape deviation: %d pick(s) over the %s"
                           " archetype's role slots for this map"
                           % (dev, top[0][0]))

    # healing supply: peak single heal in each kit (ability or weapon side),
    # against the median across the whole support roster - the kits' own
    # numbers, not a judged rating
    def peak_heal(ids):
        return dict(_rows(cx, """
            select hero_id, max(v) from (
                select a.hero_id, s.value v from ability_stats s
                join abilities a using(ability_id)
                join stat_keys k using(stat_key_id)
                where k.code in ('heal','hps') and s.value is not null
                  and a.hero_id = any(%s)
                union all
                select w.hero_id, s.value from weapon_stats s
                join weapon_configs c on c.config_id = s.config_id
                join weapons w on w.weapon_id = c.weapon_id
                join stat_keys k on k.stat_key_id = s.stat_key_id
                where k.code in ('heal','hps') and s.value is not null
                  and w.hero_id = any(%s)) t group by 1""", ids, ids))
    sup_ids = [h for h in A if role_of[h] == "support"]
    if sup_ids:
        roster = [h for h, in _rows(cx,
            """select h.hero_id from heroes h join roles r using(role_id)
               where r.code='support'""")]
        supply = peak_heal(sup_ids)
        all_sup = sorted(float(v) for v in peak_heal(roster).values())
        median = all_sup[len(all_sup) // 2] if all_sup else 0
        total = sum(float(supply.get(h, 0)) for h in sup_ids)
        bench = median * 2
        ev.add("derived:healing",
               "healing supply locked in: %s (peak single heal) = %.0f total"
               " vs ~%.0f for a typical two-support line%s"
               % (", ".join("%s %.0f" % (names[h], supply.get(h, 0))
                            for h in sup_ids), total, bench,
                  " - UNDER-HEALED unless the open slots add sustain"
                  if len(sup_ids) >= 2
                  and total < bench * tune["HEAL_MARGIN"]
                  else ""))

    # frontline pool: what the tanks actually bring
    tanks = [h for h in A if role_of[h] == "tank"]
    if tanks:
        pools = _rows(cx, """select name, coalesce(health,0)+coalesce(shield,0)
            +coalesce(armor,0), coalesce(armor,0) from heroes
            where hero_id = any(%s)""", tanks)
        ev.add("derived:frontline", "frontline pool locked in: %s"
               % "; ".join("%s %dhp (%d armor)" % p for p in pools))

    # barrier war: their barrier HP vs our pierce
    if E:
        eb = _rows(cx, """select e.name, max(s.value) from ability_stats s
            join abilities a using(ability_id)
            join heroes e on e.hero_id = a.hero_id
            join stat_keys k using(stat_key_id)
            where k.code='barrier_health' and s.value is not null
              and a.hero_id = any(%s) group by 1""", E)
        if eb:
            pierce = _rows(cx, """
                select distinct h.name from ability_stats s
                join abilities a using(ability_id)
                join heroes h on h.hero_id = a.hero_id
                join stat_keys k using(stat_key_id)
                where k.code='ignores_barrier' and s.value=1
                  and a.hero_id = any(%s)""", list(dict.fromkeys(A + cand_ids)))
            ev.add("derived:barriers",
                   "barrier war: enemy fields %s; available barrier-piercers:"
                   " %s" % ("; ".join("%s %.0fhp" % b for b in eb),
                            ", ".join(n for n, in pierce) or "none"))

    # trend: movement since the previous blizzard snapshot, when one exists
    trend = _rows(cx, """
        with snaps as (select snapshot_id, row_number() over
            (order by captured_at desc) rn from meta_snapshots ms
            join sources s using(source_id) where s.code='blizzard')
        select h.name, round(cur.win_rate - prev.win_rate, 1) d
        from hero_meta cur
        join snaps sc on sc.snapshot_id = cur.snapshot_id and sc.rn = 1
        join competitive_tiers t on t.tier_id = cur.tier_id and t.code='all'
        join hero_meta prev on prev.hero_id = cur.hero_id
        join snaps sp on sp.snapshot_id = prev.snapshot_id and sp.rn = 2
        join competitive_tiers t2 on t2.tier_id = prev.tier_id
            and t2.code='all'
        join heroes h on h.hero_id = cur.hero_id
        where abs(cur.win_rate - prev.win_rate) >= %s
        order by abs(cur.win_rate - prev.win_rate) desc limit 6""",
        tune["TREND_POINTS"])
    for name, d in trend:
        ev.add("derived:trend", "trend since the previous capture: %s %+.1f"
               " win rate" % (name, d))


def main():
    """Print the rendered dossier - the skill's and humans' window into it.

        python -m data.proprietary.dossier --map "King's Row" --enemy Zarya
    """
    import psycopg
    from data.proprietary import pipeline

    parser = pipeline.build_parser(main.__doc__)
    parser.add_argument("--map", dest="map_name")
    parser.add_argument("--enemy", action="append", default=[])
    parser.add_argument("--ally", action="append", default=[],
                        help="a locked friendly pick (repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable evidence instead of lines")
    args = parser.parse_args()
    with psycopg.connect(pipeline.resolve_dsn(args)) as cx:
        ev, _ = build(cx, args.map_name, args.enemy, args.ally)
    if args.json:
        import json
        print(json.dumps([{"tag": t, "table": tb, "text": x}
                          for t, tb, x in ev.lines], ensure_ascii=False))
    else:
        print(ev.rendered())


if __name__ == "__main__":
    main()
