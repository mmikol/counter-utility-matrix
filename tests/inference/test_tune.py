"""Tuning, adding and completing strategies: each change validated through
the catalog before it is written, and logged with a reason."""

import os
from pathlib import Path

import pytest

from db import Refusal
from inference import catalog, tune
from inference.strategy import CatalogError

# --- tuning --------------------------------------------------------------------------

def test_a_strategy_is_three_sentences_at_most(catalog_copy):
    """The add tool refuses a fourth sentence, counts a code span as one token
    and the title line as none; the playbook's own files keep to it."""
    assert tune.sentence_count("# Title\n\nOne. Two! Three?") == 3
    assert tune.sentence_count("One `require: a == 2.` two.") == 1
    assert tune.sentence_count("One (as noted). Two \"quoted.\" Three.") == 3
    with pytest.raises(tune.TuneError, match="at most 3 sentences"):
        tune.add("four-sentences", "Four sentences", "assumption",
                 "One. Two. Three. Four.", None, "test", directory=catalog_copy)
    added = tune.add("three-sentences", "Three sentences", "assumption",
                     "One. Two. Three.", None, "test", directory=catalog_copy)
    assert added["form"] == "assumption"
    for h in catalog.load():
        assert tune.sentence_count(h.body) <= tune.MAX_SENTENCES, h.id


def test_tune_edits_validates_and_logs(catalog_copy):
    change = tune.tune("coverage", "weight", 3.5, "test: more coverage", catalog_copy)
    assert change["old"] == "3" and change["new"] == "3.5"
    cat = {h.id: h for h in catalog.load(catalog_copy)}
    assert cat["coverage"].weight == 3.5
    change = tune.tune("under-healed", "params.HEAL_MARGIN", 0.8, "test", catalog_copy)
    assert cat["under-healed"].params["HEAL_MARGIN"] == 0.75 and change["old"] == "0.75"
    assert {h.id: h for h in catalog.load(catalog_copy)}[
        "under-healed"].params["HEAL_MARGIN"] == 0.8
    tune.tune("anti-air", "when", "enemy.flyers >= 1 and map.known == 1", "test", catalog_copy)
    assert {h.id: h for h in catalog.load(catalog_copy)}["anti-air"].when.source == \
        "enemy.flyers >= 1 and map.known == 1"
    tune.tune("map-fit", "params.NEW_DIAL", 2, "a dial added from nothing", catalog_copy)
    assert {h.id: h for h in catalog.load(catalog_copy)}["map-fit"].params["NEW_DIAL"] == 2
    log = Path(catalog_copy, "tuning-log.md").read_text(encoding="utf-8")
    assert "`coverage` weight: 3 -> 3.5 (test: more coverage)" in log
    assert log.count("\n- ") == 4


def test_who_asked_is_folded_onto_the_one_log_line(catalog_copy):
    """by is folded like the reason, so a line break in it cannot forge a
    second entry in the log; a blank one reads as the session."""
    log = os.path.join(catalog_copy, "tuning-log.md")
    tune.tune("coverage", "weight", 2, "r", catalog_copy, by="x]\n- 2026-01-01T00:00Z `forged` w")
    assert len(tune.log_tail(20, log)) == 1
    assert tune.log_tail(1, log)[0].endswith("[x] - 2026-01-01T00:00Z `forged` w]")
    tune.tune("coverage", "weight", 3, "r", catalog_copy, by="  ")
    lines = tune.log_tail(20, log)
    assert len(lines) == 2 and lines[1].endswith("[claude-code-session]")
    # the last n lines, and none for n below 1
    assert tune.log_tail(0, log) == [] and tune.log_tail(-2, log) == []
    assert tune.log_tail(1, log) == [lines[1]]


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
    assert draft.form == "draft" and draft.pending and not draft.solver_reads
    assert all(
        h.form == "assumption" and not h.pending for h in cat
        if h.id in ("vintage", "objective", "locked-picks"))
    with pytest.raises(CatalogError, match="carries nothing to score"):
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
    prose = (
        "When their support line heals at or above the roster bench, one\n"
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
    assert next(h for h in cat if h.id == "sustain-first").solver_reads
    # refusals leave nothing behind
    with pytest.raises(tune.TuneError, match="reason"):
        tune.add("no-reason", "No reason", "assumption", "x", None, "  ", directory=catalog_copy)
    assert not os.path.exists(os.path.join(catalog_copy, "no-reason.md"))
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


# --- the guards: ids, injected fields, an unclosed fence ---------------------------------

def test_tune_and_complete_refuse_ids_that_are_paths(catalog_copy):
    for bad in ("../../README", "coverage/../vintage", "Coverage", ""):
        with pytest.raises(tune.TuneError, match="no strategy"):
            tune.tune(bad, "weight", 1, "r", directory=catalog_copy)
        with pytest.raises(tune.TuneError, match="no strategy"):
            tune.complete(bad, {"weight": 1}, "r", directory=catalog_copy)
    with pytest.raises(tune.TuneError, match="under 120 characters"):
        tune.add("too-long", "x" * 121, "constraint", "prose", None, "r", directory=catalog_copy)


def test_the_markdown_beside_the_playbook_is_no_strategy_to_add_or_tune(catalog_copy):
    # the catalog never reads tuning-log.md, so a strategy by that id is refused unwritten
    log = Path(catalog_copy, "tuning-log.md")
    with pytest.raises(tune.TuneError, match="beside the playbook"):
        tune.add("tuning-log", "Log", "assumption", "One.", None, "r", directory=catalog_copy)
    assert not log.exists()
    # a log that opens with frontmatter is still the log
    text = "---\nname: Log\nkind: assumption\n---\n# Log\n\nOne.\n"
    log.write_text(text, encoding="utf-8")
    with pytest.raises(tune.TuneError, match="beside the playbook"):
        tune.tune("tuning-log", "category", "general", "r", directory=catalog_copy)
    with pytest.raises(tune.TuneError, match="beside the playbook"):
        tune.complete("tuning-log", {"category": "general"}, "r", directory=catalog_copy)
    assert log.read_text(encoding="utf-8") == text


def test_frontmatter_cannot_be_injected_through_a_field_or_a_value(catalog_copy):
    """Every line break the loader splits on is refused, a trailing one
    included, and so is every number that is not finite, a bool where an
    expression goes and the params block where one dial goes."""
    before = Path(catalog_copy, "coverage.md").read_text(encoding="utf-8")
    for field, value in (("params.A\nweight: 99\nB", 1), ("params.lower", 1),
                         ("when", "1 == 1\nweight: 99"), ("bonus", "---\nx"),
                         ("bonus", "x" * 501), ("when", "1 == 1\u2028weight: 9"),
                         ("category", "general\x85weight: 9"), ("when", "team.tanks >= 1\n"),
                         ("params.A", float("inf")), ("params.A", float("nan")),
                         ("params.A", "1 == 1"),
                         ("weight", float("nan")), ("penalty", True), ("params", {"A": 1})):
        with pytest.raises(tune.TuneError):
            tune.tune("coverage", field, value, "r", directory=catalog_copy)
    assert Path(catalog_copy, "coverage.md").read_text(encoding="utf-8") == before
    with pytest.raises(tune.TuneError, match=r"within 0\.\.10"):
        tune.tune("coverage", "weight", 11, "r", directory=catalog_copy)
    Path(catalog_copy, "heavy.md").write_text(
        "---\nname: h\nkind: heuristic\nmetric: team.tanks\ndirection: maximize\n"
        "weight: 1e308\n---\nx\n",
        encoding="utf-8")
    with pytest.raises(CatalogError, match=r"within 0\.\.10"):
        catalog.load(catalog_copy)


def test_add_refuses_a_name_or_a_category_that_closes_the_frontmatter(catalog_copy):
    """add writes the name into its header and sets the category like any
    other field: both keep the one-line rule, and a refusal leaves no file."""
    for name, fields in (("N\n---\n", None), ("N", {"category": "general\n---\n"})):
        with pytest.raises(tune.TuneError, match="one line of text"):
            tune.add("closes-early", name, "assumption", "One.", fields, "r",
                     directory=catalog_copy)
        assert not os.path.exists(os.path.join(catalog_copy, "closes-early.md"))
    added = tune.add("files-itself", "Files itself", "assumption", "One.",
                     {"category": "shape"}, "r", directory=catalog_copy)
    assert next(h for h in catalog.load(catalog_copy) if h.id == "files-itself").category == "shape"
    assert Path(added["path"]).read_text(encoding="utf-8").count("category:") == 1


def test_a_soft_limit_takes_a_numeric_penalty(catalog_copy):
    """The number the prompt, the skill and the docs promise a soft limit's
    penalty is the number every writer accepts."""
    Path(catalog_copy, "tank-cap.md").write_text(
        "---\nname: Tank cap\nkind: constraint\n---\n# Tank cap\n\nAt most two tanks.\n",
        encoding="utf-8")
    done = tune.complete("tank-cap", {"require": "team.tanks <= 2", "soft": True, "penalty": 2},
                         "r", directory=catalog_copy)
    assert done["form"] == "limit" and done["set"]["penalty"] == "2"
    assert next(h for h in catalog.load(catalog_copy) if h.id == "tank-cap").soft


def test_a_file_whose_frontmatter_never_closes_is_refused():
    """find() gives -1 for a missing fence, and -1 slices from the tail: the
    edit would have silently rewritten the end of the file."""
    for broken in ("---\nname: X\nweight: 1\n", "---\n", "---"):
        with pytest.raises(tune.TuneError, match="frontmatter"):
            tune.edit_frontmatter(broken, "weight", 2)
    whole = "---\nname: X\nweight: 1\n---\nbody\n"
    assert tune.edit_frontmatter(whole, "weight", 2) == (
        "---\nname: X\nweight: 2\n---\nbody\n", "1")


def test_a_catalog_error_is_the_operators_fault_and_a_tune_error_the_callers():
    """A tuning change the caller got wrong is a Refusal every door answers as
    the caller's error; a playbook that does not load is the operator's."""
    assert issubclass(tune.TuneError, Refusal)
    assert not issubclass(CatalogError, Refusal)
