"""The playbook's life: strategies tuned through validation with an audit
trail, drafts completed from their prose, and the catalog's guards."""

import os
import shutil
from pathlib import Path

import pytest

from inference import catalog, tune

pytestmark = pytest.mark.invariant


FIXTURE_PLAYBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures",
                                "playbook")   # the former shipped playbook: every form to tune


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the reference playbook to tune without touching the repo."""
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name.endswith(".md") and name not in catalog.NOT_HEURISTICS:
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return str(tmp_path)


# --- tuning --------------------------------------------------------------------------

def test_a_strategy_is_three_sentences_at_most(catalog_copy):
    """The user's rule: the add tool refuses a fourth sentence, counts a code
    span as one token and the title line as none, and the playbook's own
    files keep to it."""
    assert tune.sentences("# Title\n\nOne. Two! Three?") == 3
    assert tune.sentences("One `require: a == 2.` two.") == 1
    assert tune.sentences("One (as noted). Two \"quoted.\" Three.") == 3
    with pytest.raises(tune.TuneError, match="at most 3 sentences"):
        tune.add("four-sentences", "Four sentences", "assumption",
                 "One. Two. Three. Four.", directory=catalog_copy)
    added = tune.add("three-sentences", "Three sentences", "assumption",
                     "One. Two. Three.", directory=catalog_copy)
    assert added["form"] == "assumption"
    for h in catalog.load():
        assert tune.sentences(h.body) <= tune.MAX_SENTENCES, h.id


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
    log = Path(catalog_copy, "tuning-log.md").read_text(encoding="utf-8")
    assert "`coverage` weight: 3 -> 3.5 (test: more coverage)" in log
    assert log.count("\n- ") == 4


def test_tune_refuses_bad_changes_and_changes_nothing(catalog_copy):
    before = Path(catalog_copy, "coverage.md").read_text(encoding="utf-8")
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
    assert Path(catalog_copy, "coverage.md").read_text(encoding="utf-8") == before
    assert not os.path.exists(os.path.join(catalog_copy, "tuning-log.md"))


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
    text = Path(added["path"]).read_text(encoding="utf-8")
    assert text.startswith("---\nname: Shut off a heavy heal line\nkind: constraint\n")
    assert "when: enemy.heal_ratio >= params.HEAL_RATIO" in text and "  HEAL_RATIO: 1" in text
    assert text.rstrip().endswith("another damage dealer.")
    assert "# Shut off a heavy heal line" in text
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


def test_the_derive_prompt_anchors_its_style_on_files_the_playbook_holds():
    """STYLE names reference files; a playbook without them - the user's own
    rules - still gets one anchor per form, so the prompt never goes bare."""
    from inference import derive
    reference = catalog.load(FIXTURE_PLAYBOOK)
    assert {h.id for h in derive.style_anchors(reference)} >= {"anti-heal-answer", "coverage"}
    own = [h for h in reference if h.id not in derive.STYLE]
    anchors = derive.style_anchors(own)
    assert anchors and {h.form for h in anchors} == {h.form for h in own if h.form != "draft"}
    assert not {h.id for h in anchors} & set(derive.STYLE)


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
    answers = iter(['{"fields": {"metric": "team.hps_peak", "direction": "maximize", "weight": 2},'
                    ' "reason": "r"}',
                    '{"fields": {"metric": "team.heal_peak_total", "direction": "maximize",'
                    ' "weight": 2},'
                    ' "reason": "r"}'])
    seen = []
    def runner(text):
        seen.append(text)
        return next(answers)
    result = derive.derive(directory=catalog_copy, runner=runner, log=lambda m: None)
    assert result["derived"][0]["form"] == "heuristic" and len(seen) == 2
    assert "refused by the catalog: sustain-first: metric 'team.hps_peak'" in seen[1]
    # two refusals leave the draft as it was
    _draft(catalog_copy, "stubborn", "heuristic")
    def bad(text):
        return '{"fields": {"metric": "team.nope", "direction": "maximize"}, "reason": "r"}'
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
        raise derive.CliUnavailableError("the claude CLI is not signed in: run `claude login` once")
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
    text = Path(catalog_copy, "coverage.md").read_text(encoding="utf-8")
    assert "weight: 99" not in text
    with pytest.raises(tune.TuneError, match=r"within 0\.\.10"):
        tune.tune("coverage", "weight", 11, "r", directory=catalog_copy)
    Path(catalog_copy, "heavy.md").write_text(
        "---\nname: h\nkind: heuristic\nmetric: team.tanks\ndirection: maximize\n"
        "weight: 1e308\n---\nx\n",
        encoding="utf-8")
    with pytest.raises(catalog.CatalogError, match=r"within 0\.\.10"):
        catalog.load(catalog_copy)


def test_the_deriver_accepts_only_a_strategys_fields():
    from inference import derive
    with pytest.raises(ValueError, match="fields a strategy does not have"):
        derive.parse('{"fields": {"prose": true, "weight": 2}, "reason": "r"}')
    with pytest.raises(ValueError, match="keeps its kind"):
        derive.parse('{"fields": {"kind": "constraint"}, "reason": "r"}')
    parsed = derive.parse('{"fields": {"kind": "assumption"}, "reason": "r"}')
    assert parsed[0] == {"kind": "assumption"}
    with pytest.raises(ValueError, match="params must be"):
        derive.parse('{"fields": {"params": {"A": "1 == 1"}}, "reason": "r"}')
    fields, reason = derive.parse('{"fields": {"weight": 2, "params": {"A": 1.5}}, "reason": "r"}')
    assert fields == {"weight": 2, "params": {"A": 1.5}} and reason == "r"


def test_a_file_named_for_another_id_cannot_hijack_it(catalog_copy):
    Path(catalog_copy, "aaa.md").write_text(
        "---\nname: x\nkind: assumption\nid: coverage\n---\nx\n",
                                            encoding="utf-8")
    with pytest.raises(catalog.CatalogError) as caught:
        catalog.load(catalog_copy)
    assert caught.value.file == "aaa.md" and "id: is the filename" in str(caught.value)


def test_an_experiment_playbook_is_chosen_by_the_environment(monkeypatch, tmp_path):
    """COUNTER_MATRIX_STRATEGIES names another folder of strategy files; the
    shipped playbook is the default, and the docs are written from it alone."""
    monkeypatch.delenv("COUNTER_MATRIX_STRATEGIES", raising=False)
    assert catalog.strategies_dir() == catalog.SHIPPED_DIR
    experiment = tmp_path / "experiment"            # one rule, copied from the playbook
    experiment.mkdir()
    shutil.copy(os.path.join(catalog.SHIPPED_DIR, "open-queue-tanks.md"), experiment)
    monkeypatch.setenv("COUNTER_MATRIX_STRATEGIES", str(experiment))
    chosen = catalog.strategies_dir()
    assert chosen == str(experiment)
    two = catalog.load(chosen)
    assert {h.id for h in two} == {"open-queue-tanks"}
    monkeypatch.setattr(catalog, "STRATEGIES_DIR", chosen)
    assert catalog.write_docs(two, path=str(tmp_path / "never.md")) is None
    assert not (tmp_path / "never.md").exists()
