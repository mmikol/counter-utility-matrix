"""validate_playbook through the door, over no database: the World and the
recorded matches are stubbed, the playbook is a folder the call names, a
folder outside the repo or one that does not load is refused, and the
reply is the report's text over its JSON."""

import contextlib
import json

import pytest

from db import Refusal
from door.mcp import solver, tools
from facts import tables
from inference import catalog
from tests import matches
from tests.inference import FIXTURE_PLAYBOOK


class Offline(tools.Context):
    """The door's context over no database: the loads are stubbed."""

    def connect(self, boot=False):
        return contextlib.nullcontext("cx")


@pytest.fixture()
def ctx(synthetic_world, monkeypatch, tmp_path):
    digest = catalog.playbook_digest(FIXTURE_PLAYBOOK)
    recorded = [r.match for r in matches.rows(synthetic_world, 6, matches.noise, seed="door",
                                             digest=digest, per_session=3)]
    monkeypatch.setattr(tables, "load", lambda cx: synthetic_world)
    monkeypatch.setattr(solver, "load_matches", lambda cx: recorded)
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    return Offline(dsn="postgresql://nowhere", client="test")


def test_validate_playbook_judges_the_recorded_matches_through_the_door(ctx):
    text, data = ctx.call("validate_playbook", playbook="tests/fixtures/playbook")
    assert text.startswith("validation of tests/fixtures/playbook (digest ")
    assert data["counts"]["judged"] == 6 and data["pinned"] is True
    assert data["playbook"]["digest"] == catalog.playbook_digest(FIXTURE_PLAYBOOK)
    assert not data["guard"]["enough"] and "too few for a verdict" in data["verdict"]
    json.dumps(data)                                          # the structured reply is JSON
    _, detailed = ctx.call("validate_playbook", playbook="tests/fixtures/playbook",
                           detail=True, effect=0.55)
    assert "blue_team" in detailed["matches"][0] and detailed["guard"]["needed"] == 779


def test_the_playbook_in_force_is_judged_when_none_is_named(ctx, monkeypatch):
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    _, data = ctx.call("validate_playbook")
    assert data["playbook"]["name"] == "tests/fixtures/playbook"


@pytest.mark.parametrize(("folder", "refusal"), [
    ("..", "inside the repo"), ("/tmp", "inside the repo"), ("no/such/folder", "no playbook"),
    ("docs", "does not load")])
def test_a_playbook_folder_outside_the_repo_or_that_does_not_load_is_refused(
        ctx, folder, refusal):
    with pytest.raises(Refusal, match=refusal):
        ctx.call("validate_playbook", playbook=folder)


def test_an_effect_that_is_not_a_win_chance_is_refused_before_the_rescore(ctx, monkeypatch):
    monkeypatch.setattr(tables, "load", lambda cx: pytest.fail("the World was loaded"))
    with pytest.raises(Refusal, match="effect is a win chance"):
        ctx.call("validate_playbook", playbook="tests/fixtures/playbook", effect=0.5)
