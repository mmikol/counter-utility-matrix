"""The validation's statistics: the ridge fit recovers a known logistic
model and stays finite where the outcomes separate, the scores read the
coin flip as ln 2 and a quarter, and the bootstrap resamples whole sessions
and pairs two scores drawn on one seed."""

import math
import random

import pytest

from inference import fit


def test_the_ridge_fit_recovers_a_known_logistic_model():
    rng = random.Random("fit|known")
    rows, wins = [], []
    for _ in range(4000):
        x1, x2 = rng.gauss(0, 1), rng.choice((-1.0, 0.0, 1.0))
        rows.append({1: x1, 2: x2} if x2 else {1: x1})
        wins.append(1 if rng.random() < fit.sigmoid(0.3 + 1.2 * x1 - 0.8 * x2) else 0)
    coef = fit.fit(rows, wins, 2, penalty=0.01)
    assert coef == pytest.approx([0.3, 1.2, -0.8], abs=0.12)
    assert fit.predict(coef, {1: 0.0}) == pytest.approx(fit.sigmoid(coef[0]))


def test_the_penalty_keeps_a_separating_feature_finite_and_pulls_it_toward_zero():
    rows = [{1: 1.0}] * 20 + [{1: -1.0}] * 20
    wins = [1] * 20 + [0] * 20
    light, heavy = fit.fit(rows, wins, 1, penalty=1.0), fit.fit(rows, wins, 1, penalty=16.0)
    assert 0 < heavy[1] < light[1] < 10
    assert light[0] == pytest.approx(0.0, abs=1e-9)
    assert fit.fit([], [], 3, penalty=1.0) == [0.0, 0.0, 0.0, 0.0]


def test_the_scores_read_the_coin_flip_as_ln_2_and_a_quarter():
    assert fit.log_loss(0.5, 1) == fit.log_loss(0.5, 0) == pytest.approx(math.log(2))
    assert fit.brier(0.5, 1) == fit.brier(0.5, 0) == 0.25
    assert fit.log_loss(0.0, 1) == pytest.approx(-math.log(fit.CLIP))    # clipped, finite
    assert fit.brier(1.0, 1) == 0.0


def test_the_bootstrap_resamples_whole_sessions():
    one = fit.bootstrap([[0.2, 0.4, 0.6]], draws=200, seed="s")
    assert one == {"value": pytest.approx(0.4), "low": pytest.approx(0.4),
                   "high": pytest.approx(0.4)}
    two = fit.bootstrap([[0.0, 0.0], [1.0]], draws=500, seed="s")
    assert two["value"] == pytest.approx(1 / 3)
    assert two["low"] == 0.0 and two["high"] == 1.0       # all of one session, or the other
    assert fit.bootstrap([], draws=10, seed="s") == {"value": 0.0, "low": 0.0, "high": 0.0}


def test_two_scores_bootstrapped_on_one_seed_draw_the_same_sessions():
    groups = [[float(i)] * (i + 1) for i in range(12)]
    shifted = [[v + 1.0 for v in g] for g in groups]
    a = fit.bootstrap(groups, draws=300, seed="paired")
    b = fit.bootstrap(shifted, draws=300, seed="paired")
    assert (b["low"] - a["low"], b["high"] - a["high"]) == pytest.approx((1.0, 1.0))


def test_the_maps_an_effect_needs_fall_with_the_square_of_the_effect():
    assert fit.maps_needed(fit.log_odds(0.60)) == 191
    assert fit.maps_needed(fit.log_odds(0.55)) == 779
    assert fit.maps_needed(-0.8) == fit.maps_needed(0.8) == math.ceil((5.6 / 0.8) ** 2)
