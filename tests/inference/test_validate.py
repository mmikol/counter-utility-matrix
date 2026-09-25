"""The validation: planted effects are found by the model that can see them
and pure noise by none, the guard withholds a verdict below the maps an
effect needs, the time split never trains on a later map and the sessions
split never splits a session, a playbook is judged only from its digest's
first map, the families file every scoring strategy once, an ablation drops
exactly its family's terms, and the rescore is the engine's evaluate from
both seats. No database: the synthetic World and synthetic matches."""

import datetime
import math

import pytest

from db import Refusal
from facts.compute import matchup_metrics
from facts.matches import Match
from facts.team import numbers, team_metrics
from inference import catalog, engine, predict, rescore, validate
from inference.report import rendered
from tests import matches
from tests.inference import ASSUMPTIONS_ONLY, FIXTURE_PLAYBOOK

COIN = math.log(2.0)


def _assess(rows, catalog=(), effect=validate.EFFECT):
    return validate.assess(rescore.Rescoring(rows, []), matches.judged(rows, catalog),
                           validate.Options(effect=effect))


def _models(split):
    return {m["id"]: m for m in split["models"]}


@pytest.fixture(scope="module")
def world():
    from tests import synthetic
    return synthetic.world()


def test_a_planted_hero_effect_is_recovered_by_the_heroes_model(world):
    report = _assess(matches.rows(world, 400, matches.anvil, seed="anvil"))
    assert report["guard"]["enough"]
    for split in report["splits"]:
        models = _models(split)
        assert models["M3"]["vs_coin"]["high"] < 0, split["name"]     # beats the coin flip
        assert models["M3"]["log_loss"]["value"] < COIN - 0.05
    assert report["heroes"][0]["hero"] == "Anvil"
    assert report["heroes"][0]["effect"] > 0.5
    assert all(abs(h["effect"]) < 0.5 for h in report["heroes"][1:3])


def test_a_planted_playbook_score_effect_is_recovered_by_m4(world):
    report = _assess(matches.rows(world, 400, matches.score, seed="score"))
    for split in report["splits"]:
        models = _models(split)
        assert split["playbook_adds"]["high"] < 0, split["name"]      # M4 beats M3
        assert models["M4"]["vs_coin"]["high"] < 0
        assert models["M3"]["vs_coin"]["high"] > 0                    # the heroes cannot see it
        assert "M4 scores best" in split["verdict"]
    assert report["score_effect"]["log_odds"] > 0.5
    assert report["score_effect"]["needed"] < 400


def test_pure_noise_leaves_every_model_near_the_coin_flip(world):
    report = _assess(matches.rows(world, 400, matches.noise, seed="noise"))
    for split in report["splits"]:
        for model in split["models"]:
            assert abs(model["log_loss"]["value"] - COIN) < 0.03, (split["name"], model["id"])
            assert abs(model["brier"]["value"] - 0.25) < 0.015, (split["name"], model["id"])
            assert model["vs_coin"]["high"] >= 0, (split["name"], model["id"])
        assert "beating the coin flip: none" in split["verdict"]


def test_the_guard_withholds_a_verdict_below_the_maps_an_effect_needs(world):
    rows = matches.rows(world, 120, matches.score, seed="guard")
    report = _assess(rows)
    guard = report["guard"]
    assert (guard["decided"], guard["needed"], guard["enough"]) == (120, 191, False)
    assert guard["reference"] == {"0.60": 191, "0.55": 779}
    assert report["verdict"] == guard["text"]
    assert "120 decided maps" in guard["text"] and "too few for a verdict" in guard["text"]
    assert all(split["verdict"] is None for split in report["splits"])
    assert all(split["models"] for split in report["splits"])    # the scores still show
    assert _assess(rows, effect=0.7)["guard"]["enough"]           # 0.85 log-odds needs 44
    assert validate.guard(778, 0.55)["enough"] is False
    assert validate.guard(779, 0.55)["enough"] is True


def test_the_maps_an_effect_needs_are_the_power_rule():
    assert validate.guard(0, 0.60)["needed"] == 191               # about 200
    assert validate.guard(0, 0.55)["needed"] == 779               # about 800
    assert validate.guard(0, 0.60)["log_odds"] == pytest.approx(math.log(1.5))


@pytest.mark.parametrize("effect", [0.5, 1.0, 0.3, 1.2])
def test_the_effect_is_a_win_chance_above_one_half(effect):
    with pytest.raises(Refusal, match="effect is a win chance"):
        validate.guard(10, effect)


def test_the_time_split_never_trains_on_a_later_map(world):
    rows = validate.examples(matches.rows(world, 97, matches.noise, seed="time",
                                          per_session=7), [])
    folds = predict.time_folds(rows)
    assert len(folds) == predict.TIME_BLOCKS - 1
    for fold in folds:
        latest = max(ex.match.played_on for ex in fold.train)
        assert all(ex.match.played_on > latest for ex in fold.test)
    tested = [ex.match.match_id for fold in folds for ex in fold.test]
    assert len(tested) == len(set(tested))                         # each map scored once
    first = min(ex.match.played_on for ex in rows)
    assert all(ex.match.played_on != first for fold in folds for ex in fold.test)


def test_the_sessions_split_scores_every_map_once_and_never_splits_a_session(world):
    rows = validate.examples(matches.rows(world, 60, matches.noise, seed="sessions"), [])
    folds = predict.session_folds(rows)
    assert len(folds) == 60 // matches.PER_SESSION + 1 == 8       # fewer sessions than folds
    for fold in folds:
        assert not ({ex.match.played_on for ex in fold.train}
                    & {ex.match.played_on for ex in fold.test})
    tested = sorted(ex.match.match_id for fold in folds for ex in fold.test)
    assert tested == sorted(ex.match.match_id for ex in rows)
    one = [ex for ex in rows if ex.match.played_on == rows[0].match.played_on]
    assert predict.session_folds(one) == []
    assert predict.time_folds(one) == []


def _match(i, day, digest, result=validate.WIN):
    return Match(match_id=i, played_on=datetime.date(2026, 3, day), map_name="Salt Flats",
                 side="", result=result, blue=("Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh"),
                 red=("Mortar", "Quarry", "Gale", "Flint", "Sorrel", "Tansy"), bans=(),
                 playbook_digest=digest, note="")


def test_a_playbook_is_judged_only_from_its_digests_first_map():
    recorded = [_match(1, 1, matches.OTHER_DIGEST), _match(2, 1, matches.OTHER_DIGEST),
                _match(3, 2, matches.DIGEST), _match(4, 3, matches.OTHER_DIGEST),
                _match(5, 4, matches.DIGEST)]
    assert [m.match_id for m in rescore.pinned(recorded, matches.DIGEST)] == [3, 4, 5]
    assert rescore.pinned(recorded, "f" * 64) == []
    pins = rescore.pins(recorded, matches.DIGEST)
    assert [(p["digest"][0], p["maps"], p["first"], p["last"], p["judged"]) for p in pins] == [
        ("e", 3, "2026-03-01", "2026-03-03", False), ("d", 2, "2026-03-02", "2026-03-04", True)]


def test_a_playbook_no_map_was_played_under_is_not_judged(world):
    recorded = [_match(1, 1, matches.OTHER_DIGEST)]
    subject = validate.Subject(ASSUMPTIONS_ONLY, "p", matches.DIGEST)
    report = validate.validate(world, recorded, subject)
    assert report["counts"]["set_aside"] == 1 and report["counts"]["judged"] == 0
    assert report["verdict"].startswith("No recorded map was played under this playbook")
    unpinned = validate.validate(world, recorded, subject, validate.Options(pin=False))
    assert unpinned["counts"]["judged"] == 1 and not unpinned["pinned"]


def test_the_families_file_every_scoring_strategy_once():
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    kin = {f.name: f.ids for f in rescore.families(playbook)}
    assert kin == {
        "side": ("attack-breaks-the-hold", "defense-holds-the-ground"),
        "counters": ("coverage", "exposure"),
        "synergy": ("cohesion",),
        "rates": ("map-fit", "meta-strength"),
        "scored": ("anti-heal-answer", "squish-limit", "under-healed"),
        "other": ("anti-air", "effective-hp", "healing-floor", "range-war")}
    filed = [i for ids in kin.values() for i in ids]
    assert sorted(filed) == sorted(s.id for s in playbook if rescore.scores(s))
    assert "open-queue-tanks" not in filed                        # a hard limit scores nothing
    assert rescore.families(ASSUMPTIONS_ONLY) == []


def test_an_ablation_drops_exactly_its_familys_terms(world):
    [row] = matches.rows(world, 1, matches.noise, seed="ablate")
    row = row._replace(blue_score=5.0, red_score=3.0,
                       blue_terms={"coverage": 1.5, "cohesion": 0.5, "map-fit": 3.0},
                       red_terms={"coverage": 0.25, "cohesion": 2.0, "map-fit": 0.75})
    assert rescore.without(row, []) == 2.0
    assert rescore.without(row, ["coverage"]) == (5.0 - 1.5) - (3.0 - 0.25)
    assert rescore.without(row, ["coverage", "cohesion", "map-fit"]) == 0.0
    kin = [rescore.Family("counters", "", ("coverage",)), rescore.Family("synergy", "",
                                                                            ("cohesion",))]
    [example] = validate.examples([row._replace(match=row.match._replace(result="win"))], kin)
    assert example.score == {"": 2.0, "counters": 0.75, "synergy": 3.5}


def test_each_family_is_ablated_and_named_by_its_ids(world):
    rows = [r._replace(blue_terms={"coverage": r.blue_score}, red_terms={"coverage": r.red_score})
            for r in matches.rows(world, 200, matches.score, seed="families")]
    report = validate.assess(rescore.Rescoring(rows, []), matches.judged(rows))
    assert report["splits"][0]["ablations"] == []                 # the catalog names no family
    playbook = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.id in ("coverage", "exposure")]
    report = validate.assess(rescore.Rescoring(rows, []), matches.judged(rows, playbook))
    for split in report["splits"]:
        cuts = {a["family"]: a for a in split["ablations"]}
        assert set(cuts) == {"counters", "playbook"}
        assert cuts["counters"]["ids"] == ["coverage", "exposure"]
        # the whole score was coverage's: dropping it loses what M4 had over M3
        assert cuts["counters"]["vs_full"]["low"] > 0
        assert cuts["playbook"]["vs_full"]["low"] > 0


def test_a_draw_is_judged_but_never_decided(world):
    rows = matches.rows(world, 16, matches.noise, seed="draws")
    rows[0] = rows[0]._replace(match=rows[0].match._replace(result=validate.DRAW))
    report = _assess(rows)
    counts = report["counts"]
    assert (counts["judged"], counts["decided"], counts["drawn"]) == (16, 15, 1)
    assert counts["won"] + counts["lost"] == 15
    assert report["guard"]["decided"] == 15


def test_the_rescore_is_the_engines_evaluate_from_both_seats(world):
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    good = _match(1, 1, matches.DIGEST)._replace(map_name="Harbor Gate", side="attack")
    unknown = _match(2, 1, matches.DIGEST)._replace(blue=("Nobody",) * 6)
    done = rescore.rescore(world, [good, unknown], playbook)
    [row] = done.scored
    assert done.refused == [rescore.Refused(2, "unknown heroes: " + ", ".join(("Nobody",) * 6))]
    blue_seat, red_seat = rescore.seats(good)
    assert red_seat.side == "defense" and red_seat.blue == good.red
    blue = engine.evaluate(world, blue_seat, catalog=playbook)
    red = engine.evaluate(world, red_seat, catalog=playbook)
    assert (row.blue_score, row.red_score) == (blue.score, red.score)
    assert sum(row.blue_terms.values()) == pytest.approx(row.blue_score)
    assert sum(row.red_terms.values()) == pytest.approx(row.red_score)
    m, red_h, blue_h, _ = world.resolve(good.map_name, good.red, good.blue)
    blue_team = team_metrics(world, blue_h, m, red_h, lean=True)
    red_team = team_metrics(world, red_h, m, blue_h, lean=True)
    assert row.matchup == numbers(matchup_metrics(blue_team, red_team))
    assert row.blue_team["map_win_mean"] == blue_team["map_win_mean"]


def test_the_validation_runs_end_to_end_on_the_synthetic_world(world):
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    recorded = [r.match for r in matches.rows(world, 18, matches.noise, seed="end",
                                             per_session=6)]
    recorded = [m._replace(playbook_digest=matches.OTHER_DIGEST) if m.match_id <= 2 else m
                for m in recorded]
    lines = []
    subject = validate.Subject(playbook, "tests/fixtures/playbook", matches.DIGEST)
    report = validate.validate(world, recorded, subject, validate.Options(log=lines.append))
    counts = report["counts"]
    assert (counts["recorded"], counts["set_aside"], counts["judged"]) == (18, 2, 16)
    assert lines[-1] == "validate: 16 of 16 maps rescored"
    assert report["playbook"]["scoring"] and len(report["playbook"]["families"]) == 6
    assert not report["guard"]["enough"] and report["verdict"] == report["guard"]["text"]
    assert [p["judged"] for p in report["pins"]] == [False, True]
    row = report["matches"][0]
    assert row["match_id"] == 3 and set(row["predictions"]) <= {"time", "sessions"}
    assert "blue_team" not in row
    text = rendered(report)
    assert text.splitlines()[0].startswith("validation of tests/fixtures/playbook (digest ddd")
    assert "rate-derived: personal use" in text
    assert "pinned: 2 earlier maps set aside" in text
    assert "without side" in text and "(judged)" in text
