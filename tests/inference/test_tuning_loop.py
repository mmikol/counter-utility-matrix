"""The feedback loop: outcomes recorded under gates and restored from the
mirror, strategies tuned through validation with an audit trail, and weights
fitted from outcomes only when there is enough evidence."""

import os
import shutil

import pytest

from inference import catalog, fit, outcomes, tune

pytestmark = pytest.mark.invariant


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the strategies to tune without touching the repo."""
    for name in os.listdir(catalog.STRATEGIES_DIR):
        if name.endswith(".md") and name not in catalog.NOT_HEURISTICS:
            shutil.copy(os.path.join(catalog.STRATEGIES_DIR, name), tmp_path / name)
    return str(tmp_path)


SIX = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
RED = ["Winston", "D.Va", "Genji", "Tracer", "Kiriko", "Juno"]


# --- outcomes ----------------------------------------------------------------------

def test_outcome_is_recorded_with_its_picks_and_becomes_facts(db):
    from ui.facts import engine, model
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
    assert fs.find("playbook.outcomes") and fs.find("hero.outcomes", "Ana")
    assert any("WIN with Reinhardt" in f.text for f in fs.find("playbook.outcome"))
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
    from db.psql import schema
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
    with pytest.raises(tune.TuneError, match="no strategy"):
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
    assert all(fit.MIN_WEIGHT <= g["proposed"] <= fit.MAX_WEIGHT for g in proposal["heuristics"])
    assert any(abs(g["change"]) > 0 for g in proposal["heuristics"])
    assert "ready to apply" in fit.rendered(proposal)
    applied = fit.apply(db, proposal, directory=catalog_copy)
    assert applied and all("fit from" in a["line"] for a in applied)
    tuned = {h.id: h.weight for h in catalog.load(catalog_copy)}
    for g in proposal["heuristics"]:
        if abs(g["change"]) >= 0.005:
            assert tuned[g["id"]] == g["proposed"]
    db.rollback()


# --- the logistic tier (pure) --------------------------------------------------------

def test_logistic_evidence_finds_the_goal_that_predicts_wins():
    import random
    rng = random.Random(7)
    rows = []
    for i in range(80):
        a = rng.random()                        # heuristic "a" decides the game
        b = rng.random()                        # heuristic "b" is noise
        win = rng.random() < (0.15 + 0.7 * a)
        rows.append(("win" if win else "loss", i % 3, {"a": a, "b": b}))
    ev = fit.logistic_evidence(rows, ["a", "b"])
    assert ev["a"] > 0.4 and abs(ev["b"]) < ev["a"] / 2
    assert fit.logistic_evidence([], ["a"]) == {}
    diff, w, l = fit.mean_difference(rows, "a")
    assert diff > 0.15 and w > l


# --- authoring: name, kind and prose in; the rest inferred and stored ------------------

def test_a_bare_file_is_a_draft_the_solver_ignores(catalog_copy):
    path = os.path.join(catalog_copy, "heal-line.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("---\nname: Shut off a heavy heal line\nkind: heuristic\n---\n"
                     "# Shut off a heavy heal line\n\nOne anti-heal pick is worth more.\n")
    cat = catalog.load(catalog_copy)
    draft = next(h for h in cat if h.id == "heal-line")
    assert draft.form == "draft" and draft.pending and not draft.scored
    assert all(h.form == "assumption" and not h.pending for h in cat
               if h.id in ("vintage", "objective", "locked-picks"))
    with pytest.raises(catalog.CatalogError, match="carries nothing to score"):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("---\nname: x\nkind: assumption\nmetric: team.tanks\n"
                         "direction: maximize\n---\nx\n")
        catalog.load(catalog_copy)
    # a draft that turns out to be a ground rule becomes an assumption in one step
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("---\nname: Trust the kit\nkind: constraint\n---\nx\n")
    assert tune.complete("heal-line", {"kind": "assumption"}, "nothing measurable",
                         directory=catalog_copy)["form"] == "assumption"


def test_add_stores_a_validated_strategy_and_complete_finishes_a_draft(catalog_copy):
    prose = ("When their support line heals at or above the roster bench, one\n"
             "anti-heal pick is worth more than another damage dealer.")
    added = tune.add("shut-off-heals", "Shut off a heavy heal line", "constraint", prose,
                     {"when": "enemy.heal_ratio >= params.HEAL_RATIO",
                      "bonus": "min(team.antiheal, 1) * 1.5", "params": {"HEAL_RATIO": 1.0}},
                     "user: one anti-heal against a heavy heal line", directory=catalog_copy)
    assert added["form"] == "scored"
    text = open(added["path"], encoding="utf-8").read()
    assert text.startswith("---\nname: Shut off a heavy heal line\nkind: constraint\n")
    assert "when: enemy.heal_ratio >= params.HEAL_RATIO" in text and "  HEAL_RATIO: 1" in text
    assert text.rstrip().endswith("another damage dealer.") and "# Shut off a heavy heal line" in text
    assert "`shut-off-heals` added as constraint/scored" in tune.log_tail(
        1, os.path.join(catalog_copy, "tuning-log.md"))[0]
    # a draft: name, kind, prose - then completed in one validated step
    draft = tune.add("sustain-first", "Prefer a team that can heal", "heuristic",
                     "More healing keeps a fight going.", None, "user", directory=catalog_copy)
    assert draft["form"] == "draft"
    done = tune.complete("sustain-first", {"metric": "team.heal_peak_total",
                                           "direction": "maximize", "weight": 2},
                         "healing keeps a fight going -> peak heal, maximize",
                         directory=catalog_copy)
    assert done["form"] == "heuristic" and done["set"]["weight"] == "2"
    cat = catalog.load(catalog_copy)
    assert next(h for h in cat if h.id == "sustain-first").scored
    # refusals leave nothing behind
    with pytest.raises(tune.TuneError, match="exists"):
        tune.add("sustain-first", "again", "heuristic", "x", None, "r", directory=catalog_copy)
    with pytest.raises(tune.TuneError, match="not a registered fact key"):
        tune.add("bad-metric", "Bad", "heuristic", "x",
                 {"metric": "team.nope", "direction": "maximize"}, "r", directory=catalog_copy)
    assert not os.path.exists(os.path.join(catalog_copy, "bad-metric.md"))
    with pytest.raises(tune.TuneError, match="lowercase-kebab"):
        tune.add("Bad Id", "Bad", "constraint", "x", None, "r", directory=catalog_copy)
    with pytest.raises(tune.TuneError, match="nothing to set"):
        tune.complete("sustain-first", {}, "r", directory=catalog_copy)



# --- deriving: the engine asks the model, the catalog keeps the gate ------------------

def _draft(directory, hid="heal-line", kind="constraint"):
    with open(os.path.join(directory, hid + ".md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: Shut off a heavy heal line\nkind: %s\ncategory: matchup\n---\n"
                     "# Shut off a heavy heal line\n\nWhen their support line heals at or above"
                     " the roster bench, one anti-heal pick is worth more than another damage"
                     " dealer. One is rewarded; two overlap.\n" % kind)


def test_derive_completes_a_draft_from_the_models_answer(catalog_copy):
    from inference import derive
    _draft(catalog_copy)
    asked = []
    def runner(text):
        asked.append(text)
        return ('Sure. {"fields": {"when": "enemy.heal_ratio >= params.HEAL_RATIO", '
                '"bonus": "min(team.antiheal, 1) * 1.5", "params": {"HEAL_RATIO": 1.0}}, '
                '"reason": "one anti-heal pick is worth more than another damage dealer"}')
    result = derive.derive(directory=catalog_copy, runner=runner, log=lambda m: None)
    assert result["derived"] == [{"id": "heal-line", "form": "scored", "set": {
        "when": "enemy.heal_ratio >= params.HEAL_RATIO", "bonus": "min(team.antiheal, 1) * 1.5",
        "params.HEAL_RATIO": "1"}}] and not result["failed"]
    assert len(asked) == 1
    text = asked[0]
    assert "name: Shut off a heavy heal line" in text and "kind: constraint" in text
    assert "team.antiheal - " in text and "map.side" in text and "(text)" in text
    assert "kind: constraint\ncategory: matchup\nwhen: enemy.heal_ratio" in text   # a style anchor
    cat = catalog.load(catalog_copy)
    assert next(h for h in cat if h.id == "heal-line").scored
    assert "inferred -> scored" in tune.log_tail(1, os.path.join(catalog_copy, "tuning-log.md"))[0]
    assert derive.derive(directory=catalog_copy, runner=runner)["skipped"] == "nothing pending"


def test_derive_sends_the_catalogs_objection_back_once(catalog_copy):
    from inference import derive
    _draft(catalog_copy, "sustain-first", "heuristic")
    answers = iter(['{"fields": {"metric": "team.hps_peak", "direction": "maximize", "weight": 2}, "reason": "r"}',
                    '{"fields": {"metric": "team.heal_peak_total", "direction": "maximize", "weight": 2}, "reason": "r"}'])
    seen = []
    def runner(text):
        seen.append(text)
        return next(answers)
    result = derive.derive(directory=catalog_copy, runner=runner, log=lambda m: None)
    assert result["derived"][0]["form"] == "heuristic" and len(seen) == 2
    assert "refused by the catalog: sustain-first: metric 'team.hps_peak'" in seen[1]
    # two refusals leave the draft as it was
    _draft(catalog_copy, "stubborn", "heuristic")
    bad = lambda text: '{"fields": {"metric": "team.nope", "direction": "maximize"}, "reason": "r"}'
    result = derive.derive(["stubborn"], directory=catalog_copy, runner=bad, log=lambda m: None)
    assert "stubborn" in result["failed"] and not result["derived"]
    assert next(h for h in catalog.load(catalog_copy) if h.id == "stubborn").pending
    with pytest.raises(ValueError, match="no JSON object"):
        derive.parse("I would rather not.")


def test_derive_without_a_signed_in_cli_leaves_drafts_pending(catalog_copy, monkeypatch):
    from inference import derive
    _draft(catalog_copy)
    monkeypatch.setattr(derive, "cli", lambda: None)
    result = derive.derive(directory=catalog_copy, log=lambda m: None)
    assert result["skipped"].startswith("no claude CLI here") and not result["derived"]
    def not_logged_in(text):
        raise derive.CliUnavailable("the claude CLI is not signed in: run `claude login` once")
    result = derive.derive(directory=catalog_copy, runner=not_logged_in, log=lambda m: None)
    assert "not signed in" in result["skipped"] and "not signed in" in derive.rendered(result)
    assert next(h for h in catalog.load(catalog_copy) if h.id == "heal-line").pending


def test_tune_and_complete_refuse_ids_that_are_paths(catalog_copy):
    for bad in ("../../README", "coverage/../vintage", "Coverage", ""):
        with pytest.raises(tune.TuneError, match="no strategy"):
            tune.tune(bad, "weight", 1, "r", directory=catalog_copy)
        with pytest.raises(tune.TuneError, match="no strategy"):
            tune.complete(bad, {"weight": 1}, "r", directory=catalog_copy)
    with pytest.raises(tune.TuneError, match="under 120 characters"):
        tune.add("too-long", "x" * 121, "constraint", "prose", None, "r", directory=catalog_copy)


def test_frontmatter_cannot_be_injected_through_a_field_or_a_value(catalog_copy):
    for field, value in (("params.A\nweight: 99\nB", 1), ("params.lower", 1),
                         ("when", "1 == 1\nweight: 99"), ("bonus", "---\nx"),
                         ("bonus", "x" * 501)):
        with pytest.raises(tune.TuneError):
            tune.tune("coverage", field, value, "r", directory=catalog_copy)
    text = open(os.path.join(catalog_copy, "coverage.md"), encoding="utf-8").read()
    assert "weight: 99" not in text
    with pytest.raises(tune.TuneError, match="within 0..10"):
        tune.tune("coverage", "weight", 11, "r", directory=catalog_copy)
    (open(os.path.join(catalog_copy, "heavy.md"), "w", encoding="utf-8")
     .write("---\nname: h\nkind: heuristic\nmetric: team.tanks\ndirection: maximize\nweight: 1e308\n---\nx\n"))
    with pytest.raises(catalog.CatalogError, match="within 0..10"):
        catalog.load(catalog_copy)


def test_the_deriver_accepts_only_a_strategys_fields():
    from inference import derive
    with pytest.raises(ValueError, match="fields a strategy does not have"):
        derive.parse('{"fields": {"prose": true, "weight": 2}, "reason": "r"}')
    with pytest.raises(ValueError, match="keeps its kind"):
        derive.parse('{"fields": {"kind": "constraint"}, "reason": "r"}')
    assert derive.parse('{"fields": {"kind": "assumption"}, "reason": "r"}')[0] == {"kind": "assumption"}
    with pytest.raises(ValueError, match="params must be"):
        derive.parse('{"fields": {"params": {"A": "1 == 1"}}, "reason": "r"}')
    fields, reason = derive.parse('{"fields": {"weight": 2, "params": {"A": 1.5}}, "reason": "r"}')
    assert fields == {"weight": 2, "params": {"A": 1.5}} and reason == "r"


def test_a_file_named_for_another_id_cannot_hijack_it(catalog_copy):
    (open(os.path.join(catalog_copy, "aaa.md"), "w", encoding="utf-8")
     .write("---\nname: x\nkind: assumption\nid: coverage\n---\nx\n"))
    with pytest.raises(catalog.CatalogError) as caught:
        catalog.load(catalog_copy)
    assert caught.value.file == "aaa.md" and "id: is the filename" in str(caught.value)
