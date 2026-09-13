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
