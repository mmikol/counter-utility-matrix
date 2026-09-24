"""Deriving a draft's frontmatter from its prose: the prompt, the model's
answer stored through tune.complete, the one retry with the catalog's
objection, a run without a signed-in CLI, and the headless recipe the
orchestrator shares."""

import os
import re

import pytest

from db import Refusal
from inference import catalog, derive, tune
from inference.strategy import FIELDS, CatalogError


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


def test_the_derive_prompt_asks_only_for_fields_a_strategy_has(catalog_copy):
    """Every key the prompt's answer templates name, for a heuristic draft and
    a constraint one, is a field the rule in strategy.FIELDS checks."""
    _draft(catalog_copy, "heal-line", "constraint")
    _draft(catalog_copy, "sustain-first", "heuristic")
    cat = catalog.load(catalog_copy)
    for hid in ("heal-line", "sustain-first"):
        draft = next(h for h in cat if h.id == hid)
        asked = set(re.findall(r'"([a-z_]+)":', derive.prompt(draft, cat))) - {"fields", "reason"}
        assert asked and asked <= set(FIELDS), (hid, asked - set(FIELDS))


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
    with pytest.raises(Refusal, match="no JSON object"):
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


def test_the_headless_recipe_drops_the_session_and_reads_a_signed_out_cli(monkeypatch):
    """The three pieces orchestrator.py's agents run shares: an environment
    with no CLAUDE* key, the signed-out sentinels, and a missing CLI refused
    as unavailable."""
    monkeypatch.setenv("CLAUDECODE", "1")
    env = derive.clean_env()
    assert "CLAUDECODE" not in env and env["PATH"] == os.environ["PATH"]
    assert derive.not_signed_in("Not logged in - Please run /login")
    assert derive.not_signed_in("run /login first")
    assert not derive.not_signed_in("rate limited")
    monkeypatch.setattr(derive, "cli", lambda: None)
    with pytest.raises(derive.CliUnavailableError, match="set COUNTRIX_CLAUDE"):
        derive.require_cli()
    monkeypatch.setattr(derive, "cli", lambda: "/x/claude")
    assert derive.require_cli() == "/x/claude"


def test_the_cli_is_looked_for_under_home_as_it_is_now(tmp_path, monkeypatch):
    """The native installer's path is expanded when cli() runs, not when the
    module was imported: a HOME set later is the one searched."""
    home, empty = tmp_path / "home", tmp_path / "empty"
    binary = home / ".local" / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    empty.mkdir()
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.delenv("COUNTRIX_CLAUDE", raising=False)
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("HOME", str(home))
    assert derive.cli() == str(binary)


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
    with pytest.raises(Refusal, match="fields a strategy does not have"):
        derive.parse('{"fields": {"prose": true, "weight": 2}, "reason": "r"}')
    with pytest.raises(Refusal, match="keeps its kind"):
        derive.parse('{"fields": {"kind": "constraint"}, "reason": "r"}')
    parsed = derive.parse('{"fields": {"kind": "assumption"}, "reason": "r"}')
    assert parsed[0] == {"kind": "assumption"}
    fields, reason = derive.parse('{"fields": {"weight": 2, "params": {"A": 1.5}}, "reason": "r"}')
    assert fields == {"weight": 2, "params": {"A": 1.5}} and reason == "r"
    with pytest.raises(Refusal, match="does not parse"):     # an objection, not a crash
        derive.parse('{"fields": {"weight": 2,}}')


def test_a_dial_that_is_no_finite_number_is_sent_back_as_the_objection(catalog_copy):
    """JSON reads Infinity and NaN as numbers. tune.complete checks every
    params.NAME by the rule the loader keeps, so the answer is refused, the
    refusal goes back once, and the second answer is stored."""
    _draft(catalog_copy)
    answers = iter(['{"fields": {"bonus": "min(team.antiheal, 1) * params.A",'
                    ' "params": {"A": Infinity}}, "reason": "r"}',
                    '{"fields": {"bonus": "min(team.antiheal, 1) * params.A",'
                    ' "params": {"A": 1.5}}, "reason": "r"}'])
    seen = []
    def runner(text):
        seen.append(text)
        return next(answers)
    result = derive.derive(directory=catalog_copy, runner=runner, log=lambda m: None)
    assert len(seen) == 2 and "a param must be a finite number" in seen[1]
    assert result["derived"][0]["set"]["params.A"] == "1.5" and not result["failed"]
    assert next(h for h in catalog.load(catalog_copy) if h.id == "heal-line").params == {"A": 1.5}


def test_a_fault_past_the_answer_is_raised_and_never_sent_back_as_an_objection(
        catalog_copy, monkeypatch):
    """Only a Refusal is the model's to fix. A broken playbook or a docs file
    without its markers is the operator's: derive() raises it and asks the
    model nothing more."""
    _draft(catalog_copy, "heal-line", "heuristic")
    def broken(*args, **kwargs):
        raise CatalogError("no strategies in the copy")
    monkeypatch.setattr(derive.tune, "complete", broken)
    asked = []
    def runner(text):
        asked.append(text)
        return '{"fields": {"metric": "team.heal_peak_total", "direction": "maximize"}}'
    with pytest.raises(CatalogError, match="no strategies"):
        derive.derive(directory=catalog_copy, runner=runner, log=lambda m: None)
    assert len(asked) == 1
