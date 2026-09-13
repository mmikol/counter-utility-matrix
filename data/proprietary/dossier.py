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


def build(cx, map_name=None, enemies=()):
    """-> (Evidence, context dict) for one recommendation request.

    Unknown names raise ValueError - a question about a hero we do not know
    is a question we must not quietly half-answer.
    """
    ev = Evidence()
    ctx = {"map_id": None, "map_name": None, "enemy_ids": []}

    heroes = {match_key(n): (i, n) for n, i in _rows(
        cx, "select name, hero_id from heroes")}
    maps = {match_key(n): (i, n) for n, i in _rows(
        cx, "select name, map_id from maps")}

    unknown = [e for e in enemies if match_key(e) not in heroes]
    if unknown:
        raise ValueError("unknown heroes: %s" % ", ".join(unknown))
    if map_name is not None:
        if match_key(map_name) not in maps:
            raise ValueError("unknown map: %s" % map_name)
        ctx["map_id"], ctx["map_name"] = maps[match_key(map_name)]
    ctx["enemy_ids"] = [heroes[match_key(e)][0] for e in enemies]
    enemy_set = set(ctx["enemy_ids"])

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
    pool = [h for h in pool if h not in enemy_set]

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
