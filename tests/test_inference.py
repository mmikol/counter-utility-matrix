"""The inference layer's two halves, without ever calling a model.

The dossier (deterministic evidence assembly) is tested against the built
database; persistence is tested with a synthetic model answer and rolled
back, which also exercises the citation validation - a model citing evidence
it was never shown must be an error, not a stored row."""

import pytest

from data.proprietary import dossier
from data.proprietary.load.user.strategies import read_files
from data.proprietary.store import persist, validate_answer

pytestmark = pytest.mark.invariant


# --- strategy files (pure, needs no db) ----------------------------------

def test_strategy_files_load_whole_and_skip_the_readme(tmp_path):
    (tmp_path / "anti-dive.md").write_text("# Anti dive\nPeel hard.", "utf-8")
    (tmp_path / "README.md").write_text("not a strategy", "utf-8")
    (tmp_path / "empty.md").write_text("   ", "utf-8")
    (tmp_path / "notes.txt").write_text("wrong extension", "utf-8")
    assert read_files(str(tmp_path)) == [("anti dive", "# Anti dive\nPeel hard.")]


def test_validate_answer_enforces_the_shape():
    good = {"playstyle": "brawl", "reasoning": "r",
            "picks": [{"hero": "H%d" % i, "why": "w", "evidence": ["E1"]}
                      for i in range(5)]}
    assert validate_answer(good) is good
    import copy, pytest as pt
    four = copy.deepcopy(good); four["picks"].pop()
    with pt.raises(ValueError, match="five picks"):
        validate_answer(four)
    bare = copy.deepcopy(good); bare["picks"][2]["evidence"] = []
    with pt.raises(ValueError, match="missing 'evidence'"):
        validate_answer(bare)
    with pt.raises(ValueError, match="missing 'playstyle'"):
        validate_answer({"reasoning": "r", "picks": good["picks"]})


# --- the dossier ----------------------------------------------------------

def test_dossier_lines_are_densely_numbered_and_sourced(db):
    ev, ctx = dossier.build(db, "Ilios", ["Zarya"])
    assert [t for t, _, _ in ev.lines] == [
        "E%d" % i for i in range(1, len(ev.lines) + 1)]
    assert all(table and text for _, table, text in ev.lines)
    assert ctx["map_id"] is not None and len(ctx["enemy_ids"]) == 1
    joined = ev.rendered()
    assert "Ilios" in joined and "Zarya is countered by" in joined
    db.rollback()


def test_dossier_refuses_names_it_does_not_know(db):
    with pytest.raises(ValueError, match="unknown map"):
        dossier.build(db, "Atlantis", [])
    with pytest.raises(ValueError, match="unknown heroes"):
        dossier.build(db, None, ["Goku"])
    db.rollback()


def test_dossier_without_map_or_enemies_still_has_a_playbook(db):
    ev, _ = dossier.build(db)
    tables = {t for _, t, _ in ev.lines}
    assert {"comp_archetypes", "synergies"} <= tables
    db.rollback()


# --- persistence of a (synthetic) answer -----------------------------------

def _fake_answer(ev, heroes):
    tags = [t for t, _, _ in ev.lines[:5]]
    return {"playstyle": "brawl",
            "reasoning": "synthetic answer for the persistence test",
            "picks": [{"hero": h, "why": "test", "evidence": [tags[i]]}
                      for i, h in enumerate(heroes)]}


def test_persist_stores_picks_and_citations_then_rolls_back(db, one):
    ev, ctx = dossier.build(db, "Ilios", [])
    heroes = [r[0] for r in db.execute(
        "select name from heroes order by name limit 5")]
    rec_id = persist(db, "test question", _fake_answer(ev, heroes),
                     ev, ctx["map_id"], "PROMPT", "test-model", "{}")
    assert one("select count(*) from recommendation_picks where rec_id=%s",
               rec_id) == 5
    assert one("""select count(*) from recommendation_evidence
                  where rec_id=%s""", rec_id) == 5
    assert one("select playstyle from recommendations where rec_id=%s",
               rec_id) == "brawl"
    db.rollback()          # a test must not leave a recommendation behind


def test_persist_refuses_citations_of_nothing(db):
    ev, ctx = dossier.build(db, None, [])
    heroes = [r[0] for r in db.execute(
        "select name from heroes order by name limit 5")]
    answer = _fake_answer(ev, heroes)
    answer["picks"][0]["evidence"] = ["E9999"]
    with pytest.raises(ValueError, match="never shown"):
        persist(db, "q", answer, ev, None, "P", "m", "{}")
    db.rollback()


def test_persist_refuses_invented_heroes(db):
    ev, ctx = dossier.build(db, None, [])
    answer = _fake_answer(ev, ["Goku", "Ana", "Mei", "Zarya", "Lúcio"])
    with pytest.raises(ValueError, match="invented"):
        persist(db, "q", answer, ev, None, "P", "m", "{}")
    db.rollback()


# --- the playbook intersection, the crucial part ---------------------------

def test_dossier_joins_counters_with_map_meta(db):
    ev, _ = dossier.build(db, "King's Row", ["Zarya"])
    inter = [text for _, table, text in ev.lines if table == "counters+map_meta"]
    assert inter and "answers to Zarya that also win on King's Row" in inter[0]
    db.rollback()


def test_dossier_joins_playstyle_with_map_meta(db):
    ev, _ = dossier.build(db, "King's Row")
    lines = [t for _, table, t in ev.lines if table == "playstyle+map_meta"]
    # King's Row is authored as a brawl map, so the fit line must exist
    assert any(l.startswith("brawl heroes who hold up on King's Row") for l in lines)
    db.rollback()


def test_dossier_lists_roster_styles(db):
    ev, _ = dossier.build(db)
    styles = {t.split(" heroes:")[0] for _, table, t in ev.lines
              if table == "playstyle" and " heroes:" in t}
    assert {"dive", "brawl", "poke"} <= styles
    db.rollback()


def test_strategy_notes_are_citable_evidence(db):
    src = db.execute("select source_id from sources limit 1").fetchone()[0]
    db.execute("insert into strategies (title, body, source_id)"
               " values ('test note', 'never overextend  through\nchokes', %s)",
               (src,))
    ev, _ = dossier.build(db)
    notes = [(tag, t) for tag, table, t in ev.lines if table == "strategies"]
    assert notes and "operator note 'test note': never overextend through chokes" \
        in notes[0][1]
    db.rollback()          # the note was test-only


# --- the whole-database dossier --------------------------------------------

def test_dossier_opens_with_its_own_vintage(db):
    ev, _ = dossier.build(db)
    first_tables = [t for _, t, _ in ev.lines[:4]]
    assert "meta_snapshots" in first_tables
    assert any("captured" in text and "Patch" in text
               for _, t, text in ev.lines if t == "meta_snapshots")
    db.rollback()


def test_dossier_warns_when_rates_predate_a_patch(db):
    src = db.execute("select source_id from sources limit 1").fetchone()[0]
    db.execute("insert into patches (name, released, source_id)"
               " values ('Test Future Patch', current_date, %s)", (src,))
    ev, _ = dossier.build(db)
    assert any("WARNING" in text and "pre-patch" in text
               for _, t, text in ev.lines if t == "patches")
    db.rollback()


def test_enemy_kit_depth_reaches_cooldowns_and_ultimate(db):
    ev, _ = dossier.build(db, None, ["Zarya"])
    texts = [text for _, _, text in ev.lines]
    assert any(text.startswith("enemy Zarya - Tank") and "ult " in text
               for text in texts)
    assert any("Zarya cooldowns:" in text for text in texts)
    db.rollback()


def test_candidates_are_profiled_with_rates(db):
    ev, _ = dossier.build(db, "King's Row", ["Zarya"])
    cards = [text for _, t, text in ev.lines if t == "candidates"]
    assert len(cards) >= 10
    assert all("wins " in c and " - " in c for c in cards)
    assert any("RANK-SENSITIVE" in c for c in cards)
    db.rollback()


def test_caution_flags_candidates_the_enemy_already_answers(db):
    # A candidate only exists if some enemy's answer-list pooled them, so the
    # test mirrors the real shape: victim answers enemy A (pooled via A) and
    # is answered by enemy B (cautioned via B) - real edges, not luck.
    triples = db.execute("""
        select v.name, a.name, b.name from counters pool
        join counters threat on threat.hero_id = pool.countered_by_id
        join heroes v on v.hero_id = pool.countered_by_id
        join heroes a on a.hero_id = pool.hero_id
        join heroes b on b.hero_id = threat.countered_by_id
        join hero_meta m on m.hero_id = v.hero_id
        join competitive_tiers t on t.tier_id = m.tier_id
        where t.code = 'all' and m.win_rate is not null
          and pool.hero_id <> threat.countered_by_id
        order by m.win_rate desc limit 5""").fetchall()
    assert triples, "no victim/A/B counter triple exists in the data"
    for victim, a, b in triples:
        ev, _ = dossier.build(db, None, [a, b])
        cards = [t for _, tab, t in ev.lines if tab == "candidates"]
        if not any(c.startswith(victim + " - ") for c in cards):
            continue                    # fell outside the top-18 pool cut
        cautions = [t for _, _, t in ev.lines if t.startswith("CAUTION")]
        assert any(victim in c and b in c for c in cautions), (victim, a, b)
        break
    else:
        raise AssertionError("no triple's victim survived the pool cut")
    db.rollback()


def test_map_section_includes_strugglers(db):
    ev, _ = dossier.build(db, "King's Row")
    assert any(text.startswith("struggle on King's Row")
               for _, _, text in ev.lines)
    db.rollback()


def test_role_passives_are_evidence(db):
    ev, _ = dossier.build(db)
    assert sum(1 for _, t, _ in ev.lines if t == "subroles") >= 5
    db.rollback()


def test_prior_recommendations_become_evidence(db, one):
    ev0, ctx = dossier.build(db, "Ilios")
    heroes = [r[0] for r in db.execute(
        "select name from heroes order by name limit 5")]
    rec_id = persist(db, "history test", _fake_answer(ev0, heroes),
                     ev0, ctx["map_id"], "P", "m", "{}")
    ev, _ = dossier.build(db, "Ilios")
    assert any("previously recommended (#%d" % rec_id in text
               for _, t, text in ev.lines if t == "recommendations")
    db.rollback()


# --- locked friendly picks are constraints -----------------------------------

def test_allies_are_profiled_with_partners_and_excluded_from_candidates(db):
    ev, ctx = dossier.build(db, "King's Row", ["Zarya"], allies=["Ana"])
    texts = [t for _, _, t in ev.lines]
    assert any(t.startswith("your locked pick: Ana") for t in texts)
    assert any(t.startswith("proven partners for Ana") for t in texts)
    assert len(ctx["ally_ids"]) == 1
    cards = [t for _, tab, t in ev.lines if tab == "candidates"]
    assert not any(c.startswith("Ana - ") for c in cards)
    db.rollback()


def test_ally_answered_by_enemy_raises_a_warning_line(db):
    # Zarya answers Ana in the counters data - a locked Ana must be flagged
    ev, _ = dossier.build(db, None, ["Zarya"], allies=["Ana"])
    assert any(t.startswith("WARNING: your Ana is answered by enemy Zarya")
               for _, _, t in ev.lines)
    db.rollback()


def test_unknown_ally_is_refused(db):
    with pytest.raises(ValueError, match="unknown heroes"):
        dossier.build(db, None, [], allies=["Goku"])
    db.rollback()


# --- the derived heuristics (cataloged in docs/heuristics.md) ---------------

def _derived(db, *args, **kw):
    ev, _ = dossier.build(db, *args, **kw)
    return [(tab, t) for _, tab, t in ev.lines if tab.startswith("derived:")]


def test_coverage_finds_multi_enemy_answers(db):
    lines = _derived(db, "King's Row", ["Zarya", "Pharah"])
    cov = [t for tab, t in lines if tab == "derived:coverage"]
    assert any("Widowmaker" in c and "2/2" in c for c in cov), cov
    db.rollback()


def test_skeleton_drafts_around_the_locked_ally(db):
    lines = _derived(db, "King's Row", ["Zarya"], allies=["Ana"])
    sk = [t for tab, t in lines if tab == "derived:skeleton"]
    assert sk and any("Ana*" in s for s in sk), sk
    # a skeleton never drafts a hero into two slots
    for s in sk:
        drafted = [n.strip(" *") for part in
                   s.split(": ", 1)[1].split(" - ")[0].split(" | ")
                   for n in part.split(" ", 1)[1].split(", ")]
        assert len(drafted) == len(set(drafted)), s
    db.rollback()


def test_safe_picks_contradict_no_caution(db):
    ev, _ = dossier.build(db, "King's Row", ["Zarya", "Pharah"])
    safe = next((t for _, tab, t in ev.lines if tab == "derived:safe"), "")
    cautioned = {t.split("CAUTION: ")[1].split(" is answered")[0]
                 for _, _, t in ev.lines if t.startswith("CAUTION")}
    named = {n.strip() for n in safe.split(": ", 1)[1].split(",")} if safe else set()
    assert not (named & cautioned), (named & cautioned)
    db.rollback()


def test_specialists_and_lean_emit_on_a_real_map(db):
    lines = _derived(db, "King's Row", ["Zarya", "Pharah"])
    tables = {tab for tab, _ in lines}
    assert "derived:specialists" in tables
    assert "derived:lean" in tables
    db.rollback()


def test_shape_flags_a_tankless_solo_heal_lock(db):
    lines = _derived(db, "King's Row", ["Zarya"],
                     allies=["Ana", "Genji", "Tracer"])
    shape = [t for tab, t in lines if tab == "derived:shape"]
    assert shape and "0 tank / 2 dps / 1 support" in shape[0], shape
    assert "TANKLESS" in shape[0] and "solo heal" in shape[0], shape
    db.rollback()


def test_healing_supply_reads_the_kits_own_numbers(db):
    lines = _derived(db, "King's Row", ["Zarya"], allies=["Ana", "Brigitte"])
    heal = [t for tab, t in lines if tab == "derived:healing"]
    # Ana's biggest heal lives ability-side, Brigitte's too; both nonzero
    assert heal and "Ana 250" in heal[0] and "Brigitte 100" in heal[0], heal
    db.rollback()


def test_teamcover_names_the_unanswered_enemy(db):
    lines = _derived(db, "King's Row", ["Zarya", "Pharah"], allies=["Mei"])
    cover = [t for tab, t in lines if tab == "derived:teamcover"]
    assert cover, lines
    covered, total = cover[0].split("answer ")[1].split(" ")[0].split("/")
    assert int(covered) <= int(total) == 2
    if int(covered) < 2:
        assert "still unanswered:" in cover[0], cover
    db.rollback()


def test_netmatchup_shows_both_sides_of_the_ledger(db):
    lines = _derived(db, "King's Row", ["Zarya", "Pharah"])
    net = [t for tab, t in lines if tab == "derived:netmatchup"]
    assert net and "answers" in net[0] and "answered-by" in net[0], net
    db.rollback()


def test_heuristic_params_tune_a_live_formula_without_code(db):
    # crank the dial inside the transaction, watch the flag flip, roll back
    db.execute("UPDATE heuristic_params SET value = 2.0"
               " WHERE code = 'HEAL_MARGIN'")
    lines = _derived(db, "King's Row", ["Zarya"], allies=["Ana", "Brigitte"])
    heal = [t for tab, t in lines if tab == "derived:healing"]
    assert heal and "UNDER-HEALED" in heal[0], heal
    db.rollback()
    lines = _derived(db, "King's Row", ["Zarya"], allies=["Ana", "Brigitte"])
    heal = [t for tab, t in lines if tab == "derived:healing"]
    assert heal and "UNDER-HEALED" not in heal[0], heal
    db.rollback()


def test_catalog_parity_the_table_matches_the_code(db):
    # the heuristics table may never drift from the dossier that emits it
    import os
    import re
    src = open(os.path.join(os.path.dirname(dossier.__file__), "dossier.py"),
               encoding="utf-8").read()
    in_code = set(re.findall(r"derived:[a-z]+", src))
    in_table = {tag for tag, in db.execute(
        "SELECT tag FROM heuristics WHERE status = 'live'"
        " AND tag LIKE 'derived:%'").fetchall()}
    assert in_code == in_table, (in_code ^ in_table)
    db.rollback()
