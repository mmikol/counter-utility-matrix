"""Deriving a draft's frontmatter from its prose: the prompt, the model's
answer stored through tune.complete, the one retry with the catalog's
objection, and a run without a signed-in CLI."""

import os

import pytest

from inference import catalog, derive, tune


def _draft(directory, hid="heal-line", kind="constraint"):
    with open(os.path.join(directory, hid + ".md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: Shut off a heavy heal line\nkind: %s\ncategory: matchup\n---\n"
                     "# Shut off a heavy heal line\n\nWhen their support line heals at or above"
                     " the roster bench, one anti-heal pick is worth more than another damage"
                     " dealer. One is rewarded; two overlap.\n" % kind)


def test_the_derive_prompt_anchors_its_style_on_one_file_per_form(catalog_copy):
    """The prompt shows one finished file of each form the playbook holds -
    the first by id, so the anchors are stable - and never a draft."""
    _draft(catalog_copy)
    cat = catalog.load(catalog_copy)
    anchors = derive.style_anchors(cat)
    assert [h.id for h in anchors] == ["anti-air", "anti-heal-answer", "cohesion", "locked-picks"]
    assert {h.form for h in anchors} == {h.form for h in cat} - {"draft"}


def test_derive_completes_a_draft_from_the_models_answer(catalog_copy):
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
    assert next(h for h in cat if h.id == "heal-line").solver_reads
    assert "inferred -> scored" in tune.log_tail(1, os.path.join(catalog_copy, "tuning-log.md"))[0]
    assert derive.derive(directory=catalog_copy, runner=runner)["skipped"] == "nothing pending"


def test_derive_sends_the_catalogs_objection_back_once(catalog_copy):
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
    _draft(catalog_copy)
    monkeypatch.setattr(derive, "cli", lambda: None)
    result = derive.derive(directory=catalog_copy, log=lambda m: None)
    assert result["skipped"].startswith("no claude CLI here") and not result["derived"]
    def not_logged_in(text):
        raise derive.CliUnavailableError("the claude CLI is not signed in: run `claude login` once")
    result = derive.derive(directory=catalog_copy, runner=not_logged_in, log=lambda m: None)
    assert "not signed in" in result["skipped"]
    assert "not signed in" in derive.derive_rendered(result)
    assert next(h for h in catalog.load(catalog_copy) if h.id == "heal-line").pending


def test_derive_counts_drafts_past_the_cap_apart_from_why_it_stopped(catalog_copy, monkeypatch):
    """The drafts past MAX_PER_RUN are deferred, a count of their own: a run
    that stops signed out still says how many wait, and a run that completes
    its share says it stopped for nothing."""
    monkeypatch.setattr(derive, "MAX_PER_RUN", 2)
    for hid in ("draft-a", "draft-b", "draft-c"):
        _draft(catalog_copy, hid, "heuristic")
    def not_logged_in(text):
        raise derive.CliUnavailableError("the claude CLI is not signed in: run `claude login` once")
    result = derive.derive(directory=catalog_copy, runner=not_logged_in, log=lambda m: None)
    assert "not signed in" in result["skipped"] and result["deferred"] == 1
    assert not result["derived"]
    def answer(text):
        return ('{"fields": {"metric": "team.heal_peak_total", "direction": "maximize",'
                ' "weight": 2}, "reason": "r"}')
    result = derive.derive(directory=catalog_copy, runner=answer, log=lambda m: None)
    assert len(result["derived"]) == 2 and result["deferred"] == 1
    assert result["skipped"] is None
    assert "1 draft(s) left for the next run" in derive.derive_rendered(result)


def test_the_deriver_accepts_only_a_strategys_fields():
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
