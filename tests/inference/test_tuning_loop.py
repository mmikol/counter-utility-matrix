"""The feedback loop: outcomes recorded under gates and restored from the
mirror, heuristics tuned through validation with an audit trail, and weights
fitted from outcomes only when there is enough evidence."""

import os
import shutil

import pytest

from inference import catalog, fit, outcomes, tune

pytestmark = pytest.mark.invariant


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the heuristics to tune without touching the repo."""
    for name in os.listdir(catalog.HEURISTICS_DIR):
        if name.endswith(".md") and name not in catalog.NOT_HEURISTICS:
            shutil.copy(os.path.join(catalog.HEURISTICS_DIR, name), tmp_path / name)
    return str(tmp_path)


SIX = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
RED = ["Winston", "D.Va", "Genji", "Tracer", "Kiriko", "Juno"]


# --- outcomes ----------------------------------------------------------------------

def test_outcome_is_recorded_with_its_picks_and_becomes_facts(db):
    from user.facts import engine, model
    oid = outcomes.record_outcome(db, "win", "King's Row", "attack", SIX, RED,
                                  ["Sombra"], None, "held the first fight")
    row = db.execute("select result, side, note from outcomes where outcome_id=%s",
                     (oid,)).fetchone()
    assert row == ("win", "attack", "held the first fight")
    teams = dict(db.execute("select team, count(*) from outcome_picks where outcome_id=%s"
                            " group by team", (oid,)).fetchall())
    assert teams == {"blue": 6, "red": 6, "ban": 1}
    world = model.load(db)
    assert world.hero("Ana").outcomes["win"] >= 1
    fs = engine.generate(world, "King's Row", [], ["Ana"])
    assert fs.find("strategy.outcomes") and fs.find("hero.outcomes", "Ana")
    assert any("WIN with Reinhardt" in f.text for f in fs.find("strategy.outcome"))
    assert outcomes.summary(db)["win"] >= 1
    db.rollback()


def test_outcome_gates(db):
    with pytest.raises(ValueError, match="result must be"):
        outcomes.record_outcome(db, "victory", blue=SIX)
    with pytest.raises(ValueError, match="full 6 picks"):
        outcomes.record_outcome(db, "win", blue=SIX[:5])
    with pytest.raises(ValueError, match="banned"):
        outcomes.record_outcome(db, "win", blue=SIX, bans=["Ana"])
    with pytest.raises(ValueError, match="no recommendation"):
        outcomes.record_outcome(db, "loss", blue=SIX, rec_id=999999)
    db.rollback()


def test_outcomes_restore_with_the_recommendations(db, tmp_path, monkeypatch):
    from data.db import schema
    monkeypatch.setattr(db, "commit", lambda: None)    # restore commits by design; not here
    raw = str(tmp_path / "raw")
    outcomes.record_outcome(db, "loss", None, "", SIX, RED)
    os.makedirs(raw)
    for table in schema.RECORD_TABLES:
        with open(os.path.join(raw, table + ".csv"), "w", encoding="utf-8") as fh:
            with db.cursor().copy("COPY (SELECT * FROM %s) TO STDOUT WITH (FORMAT csv,"
                                  " HEADER true)" % table) as copy:
                for chunk in copy:
                    fh.write(bytes(chunk).decode("utf-8"))
    before = db.execute("select count(*) from outcomes").fetchone()[0]
    db.execute("delete from outcomes")
    db.execute("delete from recommendations")
    assert schema.restore_recommendations(db, raw_dir=raw) > 0
    assert db.execute("select count(*) from outcomes").fetchone()[0] == before
    db.rollback()


# --- tuning --------------------------------------------------------------------------

def test_tune_edits_validates_mirrors_and_logs(catalog_copy):
    change = tune.tune("coverage", "weight", 3.5, "test: more coverage", catalog_copy)
    assert change["old"] == "3" and change["new"] == "3.5"
    cat = {h.id: h for h in catalog.load(catalog_copy)}
    assert cat["coverage"].weight == 3.5
    change = tune.tune("under-healed", "params.HEAL_MARGIN", 0.8, "test", catalog_copy)
    assert cat["under-healed"].params["HEAL_MARGIN"] == 0.75 and change["old"] == "0.75"
    assert catalog.load(catalog_copy)[0] and {h.id: h for h in catalog.load(catalog_copy)}[
        "under-healed"].params["HEAL_MARGIN"] == 0.8
    tune.tune("anti-air", "when", "enemy.flyers >= 1 and map.known == 1", "test",
              catalog_copy)
    assert {h.id: h for h in catalog.load(catalog_copy)}["anti-air"].when.source == \
        "enemy.flyers >= 1 and map.known == 1"
    tune.tune("map-fit", "params.NEW_DIAL", 2, "a dial added from nothing", catalog_copy)
    assert {h.id: h for h in catalog.load(catalog_copy)}["map-fit"].params["NEW_DIAL"] == 2
    log = open(os.path.join(catalog_copy, "tuning-log.md"), encoding="utf-8").read()
    assert "`coverage` weight: 3 -> 3.5 (test: more coverage)" in log
    assert log.count("\n- ") == 4


def test_tune_refuses_bad_changes_and_changes_nothing(catalog_copy):
    before = open(os.path.join(catalog_copy, "coverage.md"), encoding="utf-8").read()
    with pytest.raises(tune.TuneError, match="not a registered fact key"):
        tune.tune("coverage", "metric", "team.nope", "test", catalog_copy)
    with pytest.raises(tune.TuneError, match="within"):
        tune.tune("coverage", "weight", 50, "test", catalog_copy)
    with pytest.raises(tune.TuneError, match="reason"):
        tune.tune("coverage", "weight", 2, "  ", catalog_copy)
    with pytest.raises(tune.TuneError, match="no heuristic"):
        tune.tune("nope", "weight", 2, "test", catalog_copy)
    with pytest.raises(tune.TuneError):
        tune.tune("coverage", "when", "team.tanks ===", "test", catalog_copy)
    assert open(os.path.join(catalog_copy, "coverage.md"), encoding="utf-8").read() == before
    assert not os.path.exists(os.path.join(catalog_copy, "tuning-log.md"))


# --- fitting ---------------------------------------------------------------------------

def test_fit_waits_for_evidence_then_nudges_toward_what_won(db, catalog_copy):
    proposal = fit.propose(db)
    assert proposal["ready"] is False or proposal["outcomes"] >= fit.MIN_OUTCOMES
    with pytest.raises(ValueError, match="not enough"):
        fit.apply(db, dict(proposal, ready=False))
    # a synthetic history: the same blue six wins when red is soft, loses
    # when red is the mirror
    soft_red = ["Mercy", "Lifeweaver", "Symmetra", "Torbjörn", "Roadhog", "Mauga"]
    for _ in range(3):
        outcomes.record_outcome(db, "win", "King's Row", "attack", SIX, soft_red)
        outcomes.record_outcome(db, "loss", "King's Row", "attack", SIX, RED)
    proposal = fit.propose(db, min_outcomes=6)
    assert proposal["ready"] and proposal["outcomes"] >= 6
    assert all(fit.MIN_WEIGHT <= g["proposed"] <= fit.MAX_WEIGHT for g in proposal["goals"])
    assert any(abs(g["change"]) > 0 for g in proposal["goals"])
    assert "ready to apply" in fit.rendered(proposal)
    applied = fit.apply(db, proposal, directory=catalog_copy)
    assert applied and all("fit from" in a["line"] for a in applied)
    tuned = {h.id: h.weight for h in catalog.load(catalog_copy)}
    for g in proposal["goals"]:
        if abs(g["change"]) >= 0.005:
            assert tuned[g["id"]] == g["proposed"]
    db.rollback()


# --- the logistic tier (pure) --------------------------------------------------------

def test_logistic_evidence_finds_the_goal_that_predicts_wins():
    import random
    rng = random.Random(7)
    rows = []
    for i in range(80):
        a = rng.random()                        # goal "a" decides the game
        b = rng.random()                        # goal "b" is noise
        win = rng.random() < (0.15 + 0.7 * a)
        rows.append(("win" if win else "loss", i % 3, {"a": a, "b": b}))
    ev = fit.logistic_evidence(rows, ["a", "b"])
    assert ev["a"] > 0.4 and abs(ev["b"]) < ev["a"] / 2
    assert fit.logistic_evidence([], ["a"]) == {}
    diff, w, l = fit.mean_difference(rows, "a")
    assert diff > 0.15 and w > l
