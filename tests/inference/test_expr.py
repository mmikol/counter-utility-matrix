"""The expression language the frontmatter uses: dotted names read as numbers,
nothing past the whitelist, and a sandbox that refuses what would hang or
exhaust it. No database."""

import pytest

from inference.expr import Expr, ExprError


def test_expressions_read_dotted_names_and_arithmetic():
    ns = {"team": {"tanks": 1, "hitscan": 3}, "params": {"X": 2}}
    assert Expr("team.tanks == 1 and team.hitscan >= params.X").evaluate(ns) is True
    assert Expr("min(team.hitscan, 2) * 1.5").evaluate(ns) == 3.0
    assert Expr("team.missing + 1").evaluate(ns) == 1          # unknown reads 0
    assert Expr("'dive' if team.tanks else 'brawl'").evaluate(ns) == "dive"
    assert Expr("team.tanks / 0").evaluate(ns) == 0.0


def test_expressions_refuse_anything_beyond_the_whitelist():
    for bad in ("__import__('os')", "team.__class__", "[x for x in y]",
                "lambda: 1", "open('f')", "team.tanks = 2"):
        with pytest.raises(ExprError):
            Expr(bad).evaluate({"team": {}})
    # an operator outside the whitelist's tuples is refused as the node it sits in
    for bad, node in (("team.tanks | 1", "BinOp"), ("~team.tanks", "UnaryOp")):
        with pytest.raises(ExprError, match="unsupported syntax %s" % node):
            Expr(bad)


def test_expression_names_are_the_full_dotted_keys():
    assert Expr("team.tanks + enemy.flyers * params.K").names == [
        "enemy.flyers", "params.K", "team.tanks"]


def test_the_sandbox_refuses_what_would_hang_or_exhaust_it():
    from inference.expr import Expr, ExprError
    for bomb in ("9 ** 9 ** 9", "2 ** team.tanks", "'a' * 1000000000", "'x' + 'y'",
                 "'" + "s" * 201 + "' == team.style_lean", "-" * 45 + "1"):
        with pytest.raises(ExprError):
            Expr(bomb)
    assert Expr("team.tanks ** 2").evaluate({"team": {"tanks": 3}}) == 9
    # a bomb the parse lets through is refused at evaluation with its own message
    with pytest.raises(ExprError, match=r"OverflowError: .*too large"):
        Expr("team.big ** 2").evaluate({"team": {"big": 1e200}})
    assert Expr("team.style_lean == 'dive'").evaluate({"team": {"style_lean": "dive"}}) is True
