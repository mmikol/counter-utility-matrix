"""The inference layer: the expression language and catalog are pure; the
solver, evaluation and recording run against the built database."""

import pytest

from user.facts import compute
from inference import catalog, expr
from inference.expr import Expr, ExprError


# --- the expression language (pure) --------------------------------------

def test_expressions_read_dotted_names_and_arithmetic():
    ns = {"team": {"tanks": 1, "hitscan": 3}, "params": {"X": 2}}
    assert Expr("team.tanks == 1 and team.hitscan >= params.X").eval(ns) is True
    assert Expr("min(team.hitscan, 2) * 1.5").eval(ns) == 3.0
    assert Expr("team.missing + 1").eval(ns) == 1          # unknown reads 0
    assert Expr("'dive' if team.tanks else 'brawl'").eval(ns) == "dive"
    assert Expr("team.tanks / 0").eval(ns) == 0.0


def test_expressions_refuse_anything_beyond_the_whitelist():
    for bad in ("__import__('os')", "team.__class__", "[x for x in y]",
                "lambda: 1", "open('f')", "team.tanks = 2"):
        with pytest.raises(ExprError):
            Expr(bad).eval({"team": {}})


def test_expression_names_are_the_full_dotted_keys():
    assert Expr("team.tanks + enemy.flyers * params.K").names == [
        "enemy.flyers", "params.K", "team.tanks"]
    assert expr.lookup({"a": {"b": None}}, "a.b", default=7) == 7


# --- the catalog (pure) -----------------------------------------------------

def test_frontmatter_parses_scalars_lists_and_params():
    meta, body = catalog.parse_frontmatter(
        "---\nname: X\nweight: 2.5\nsoft: true\ntags: [a, b]\nparams:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "X", "weight": 2.5, "soft": True, "tags": ["a", "b"],
                    "params": {"K": 3}}
    assert body == "# X\nbody"


def test_shipped_catalog_is_valid_and_references_real_metrics():
    cat = catalog.load()
    kinds = {h.kind for h in cat}
    assert kinds == set(catalog.KINDS) == {"constraint", "goal", "strategy"}
    assert any(h.kind == "strategy" and h.scored for h in cat)        # peel, under-healed...
    assert any(h.kind == "strategy" and not h.scored for h in cat)    # optimal-play...
    registry = compute.registry()
    for h in cat:
        if h.kind == "goal":
            assert h.metric in registry and h.metric not in compute.TEXT_METRICS
        for e in (h.when, h.require, h.bonus, h.penalty):
            for name in (e.names if e else []):
                assert name in registry or name[7:] in h.params, (h.id, name)
    assert any(h.id == "open-queue-tanks" for h in cat)


def test_catalog_rejects_a_goal_on_an_unknown_metric(tmp_path):
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: goal\ndirection: maximize\nmetric: team.nope\n---\nx\n",
        "utf-8")
    with pytest.raises(catalog.CatalogError, match="not a registered fact key"):
        catalog.load(str(tmp_path))
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: strategy\nwhen: team.tanks > params.T\nbonus: 1\n---\nx\n",
        "utf-8")
    with pytest.raises(catalog.CatalogError, match="params"):
        catalog.load(str(tmp_path))


# --- the solver against the built database ------------------------------------

@pytest.fixture(scope="module")
def world(db):
    from user.facts import model
    w = model.load(db)
    db.rollback()
    return w


@pytest.mark.invariant
def test_infer_keeps_locked_picks_and_the_open_queue_shape(world):
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    assert len(r.blue) == 6 and "Ana" in r.blue
    roles = [world.hero(n).role for n in r.blue]
    assert roles.count("tank") <= 2
    assert r.considered > 100 and r.score > 0
    assert any(p["hero"] == "Ana" and p["locked"] for p in r.picks)
    # every pick cites facts the board for (map, red, the five) shows
    assert r.facts.blue == r.blue
    ids = {f.id for f in r.facts.facts}
    for p in r.picks:
        assert p["evidence"] and set(p["evidence"]) <= ids
    # coverage of both enemies is worth 3 points, and the optimum takes them
    cov = [c for c in r.contributions if c["id"] == "coverage"][0]
    assert cov["raw"] == 1.0 and cov.get("fact")


@pytest.mark.invariant
def test_infer_honours_a_hitscan_answer_to_a_flier(world):
    from inference import engine
    r = engine.infer(world, "Havana", ["Pharah", "Mercy"], [])
    assert any(world.hero(n).hitscan for n in r.blue)
    anti = [c for c in r.contributions if c["id"] == "anti-air"][0]
    assert anti["applies"] and anti["ok"]


@pytest.mark.invariant
def test_evaluate_ranks_a_full_five_against_the_field(world):
    from inference import engine
    r = engine.evaluate(world, "King's Row", ["Zarya", "Pharah"],
                        ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"])
    assert r.rank >= 1 and r.kind == "evaluate" and len(r.picks) == 6
    with pytest.raises(ValueError, match="exactly 6"):
        engine.evaluate(world, None, [], ["Ana"])


@pytest.mark.invariant
def test_the_tank_limit_is_the_only_shape_constraint(world, tmp_path):
    from inference import engine
    import shutil, os
    # two tanks is allowed by default; a third is not
    r = engine.infer(world, "King's Row", ["Zarya"], ["Winston", "D.Va"], pool_size=4)
    assert {"Winston", "D.Va"} <= set(r.blue)
    with pytest.raises(ValueError, match="no composition satisfies"):
        engine.infer(world, "King's Row", [], ["Winston", "D.Va", "Reinhardt"], pool_size=4)
    # a stricter authored constraint narrows the search the same way
    for name in os.listdir(catalog.HEURISTICS_DIR):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(catalog.HEURISTICS_DIR, name), tmp_path / name)
    (tmp_path / "shape.md").write_text(
        "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and"
        " team.damage == 2 and team.supports == 2\n---\nx\n", "utf-8")
    cat = catalog.load(str(tmp_path))
    r = engine.infer(world, "King's Row", ["Zarya"], ["Ana"], pool_size=4, catalog=cat)
    roles = sorted(world.hero(n).role for n in r.blue)
    assert roles == ["damage", "damage", "support", "support", "tank", "tank"]


# --- recording -------------------------------------------------------------------

@pytest.mark.invariant
def test_record_gates_then_rolls_back(db, world):
    from user.facts import engine as facts_engine
    from inference import record
    picks = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
    fs = facts_engine.generate(world, "King's Row", ["Zarya"], picks)
    answer = {"playstyle": "brawl", "reasoning": "test",
              "picks": [{"hero": h, "why": "w", "evidence": [fs.find("hero.identity", h)[0].id]}
                        for h in picks]}
    rec_id = record.persist(db, "q", answer, fs, world.map("King's Row").id, "P", "m", "{}")
    assert db.execute("select count(*) from recommendation_picks where rec_id=%s",
                      (rec_id,)).fetchone()[0] == 6
    db.rollback()
    bad = dict(answer, picks=[dict(p, evidence=["F99999"]) for p in answer["picks"]])
    with pytest.raises(ValueError, match="never showed"):
        record.persist(db, "q", bad, fs, None, "P", "m", "{}")
    db.rollback()
    with pytest.raises(ValueError, match="exactly 6 picks"):
        record.validate_answer(dict(answer, picks=answer["picks"][:4]))


@pytest.mark.invariant
def test_infer_never_drafts_a_banned_hero(world):
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"],
                     bans=["Widowmaker", "Bastion", "Reinhardt"])
    assert not {"Widowmaker", "Bastion", "Reinhardt"} & set(r.blue)
    assert r.bans == ["Widowmaker", "Bastion", "Reinhardt"] and "banned" in r.rendered()
    assert r.facts.bans == r.bans
    with pytest.raises(ValueError, match="banned this match"):
        engine.infer(world, None, ["Zarya"], ["Ana"], bans=["Zarya"])
