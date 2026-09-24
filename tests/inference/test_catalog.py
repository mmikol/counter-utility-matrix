"""The catalog: what a strategy file may be named, how the playbook in force
is chosen, how the catalog reads as text, the files a playbook reads and
fingerprints, the frontmatter and the forms a strategy takes, and the
weights one board overrides."""

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

import pytest

from db import Refusal
from inference import catalog
from inference.frontmatter import parse_frontmatter
from inference.strategy import KINDS, CatalogError, Strategy
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts import compute


def _fights(strategies: Iterable[Strategy]) -> list[str]:
    """Each unguarded heuristic against every heuristic that weighs its metric
    the other way, worded for the failure."""
    by_metric = {}
    for strategy in strategies:
        if strategy.kind == "heuristic":
            by_metric.setdefault(strategy.metric, []).append(strategy)
    fights = []
    for metric, group in sorted(by_metric.items()):
        for one in group:
            if one.when is not None:
                continue                      # a guarded pair is a situation, not a fight
            for other in group:
                if other.direction != one.direction:
                    fights.append("%s: %s (always, %s) opposes %s (%s)"
                                  % (metric, one.id, one.direction, other.id, other.direction))
    return fights


@pytest.mark.parametrize("directory", [FIXTURE_PLAYBOOK, None], ids=["reference", "in-force"])
def test_no_ungated_heuristic_opposes_a_gated_one_on_its_metric(directory):
    """A heuristic with no `when` reads on every board, so one that maximises a
    metric another minimises under a guard fights that guard wherever it holds:
    weight is spent on both sides and the board cannot say which it answered.
    Opposed pairs are fine - they must both be guarded, into different
    situations."""
    strategies = catalog.load(directory)
    if directory is None and not any(s.kind == "heuristic" for s in strategies):
        pytest.skip("the playbook in force (%s) holds no heuristic: the reference case carries"
                    " the guard" % catalog.strategies_dir())
    fights = _fights(strategies)
    assert not fights, fights


@pytest.mark.parametrize("when, fights", [
    ("", ["team.exposed_count: always-exposed (always, maximize) opposes exposure (minimize)"]),
    ("when: enemy.size >= 1\n", []),
], ids=["always", "guarded"])
def test_a_heuristic_fights_a_guarded_one_it_opposes_unless_it_is_guarded_too(
        catalog_copy, when, fights):
    """The guard can fail: beside the reference's exposure, which minimises
    team.exposed_count once red has a pick, a heuristic that maximises it on
    every board is a fight, and the same heuristic under a guard is not."""
    Path(catalog_copy, "always-exposed.md").write_text(
        "---\nname: Walk into every counter\nkind: heuristic\ncategory: matchup\n"
        "direction: maximize\nmetric: team.exposed_count\nweight: 1\n%s---\n"
        "Stand where the revealed enemies answer the most picks.\n" % when,
        encoding="utf-8")
    assert _fights(catalog.load(catalog_copy)) == fights


def test_a_filename_that_is_not_lowercase_kebab_is_refused_before_the_folder_counts(tmp_path):
    """The id is the filename, so the id rule runs on every file before the
    empty-folder check: a folder holding only a badly named file is refused
    for its name."""
    (tmp_path / "Bad_Name.md").write_text("---\nname: x\nkind: assumption\n---\nx\n",
                                          encoding="utf-8")
    with pytest.raises(CatalogError, match="lowercase-kebab"):
        catalog.load(str(tmp_path))


def test_the_docs_word_every_form_the_reference_playbook_holds(tmp_path, monkeypatch):
    """write_docs words a hard limit, a soft limit, a scored constraint and a
    heuristic under their headings, and drops each file's title line - the
    heading names it."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    path = tmp_path / "inference.md"
    path.write_text("# The doc\n\n<!-- generated:catalog -->\n<!-- /generated:catalog -->\n",
                    encoding="utf-8")
    assert catalog.write_docs(catalog.load(FIXTURE_PLAYBOOK), path=str(path)) == str(path)
    text = path.read_text(encoding="utf-8")
    assert "##### At most two tanks (`open-queue-tanks`, shape, limit)\n\n" \
        "`require team.tanks <= 2` (hard)\n" in text
    assert "`require team.hitscan >= 1` (soft, penalty `2.5`); when `enemy.flyers >= 1`" in text
    assert "weight 1; penalty `max(0, team.squish_count - 4) * 1.0`" in text
    assert "`maximize team.pool_total` - " in text and "\n# At most two tanks" not in text


def test_the_rendered_catalog_is_one_line_per_strategy_led_by_its_kind():
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    lines = catalog.catalog_rendered(playbook).split("\n")
    assert len(lines) == len(playbook)
    for line, strategy in zip(lines, playbook, strict=True):
        assert line.startswith(strategy.kind) and strategy.id in line


def test_a_file_named_for_another_id_cannot_hijack_it(catalog_copy):
    Path(catalog_copy, "aaa.md").write_text(
        "---\nname: x\nkind: assumption\nid: coverage\n---\nx\n",
        encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        catalog.load(catalog_copy)
    assert caught.value.file == "aaa.md" and "id: is the filename" in str(caught.value)


def test_another_playbook_is_chosen_by_the_environment(monkeypatch, tmp_path):
    """COUNTRIX_STRATEGIES names another folder of strategy files; the
    shipped playbook is the default, and the docs are written from it alone."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    assert catalog.strategies_dir() == catalog.SHIPPED_DIR
    other = tmp_path / "other"                      # one rule, copied from the playbook
    other.mkdir()
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), other)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(other))
    chosen = catalog.strategies_dir()
    assert chosen == str(other)
    one = catalog.load(chosen)
    assert {h.id for h in one} == {"open-queue-tanks"}
    assert catalog.write_docs(one, path=str(tmp_path / "never.md")) is None
    assert not (tmp_path / "never.md").exists()


def test_a_playbooks_digest_reads_its_strategy_files_and_nothing_beside_them(catalog_copy):
    """A proven fixture records the digest of the playbook it was proved under.
    The tuning log, the README and anything that is not markdown never move
    it; a line added to one strategy file does."""
    digest = catalog.playbook_digest(catalog_copy)
    assert digest == catalog.playbook_digest(FIXTURE_PLAYBOOK)
    for name in ("tuning-log.md", "README.md", "notes.txt"):
        Path(catalog_copy, name).write_text("# beside the playbook\n", encoding="utf-8")
    assert catalog.strategy_files(catalog_copy) == catalog.strategy_files(FIXTURE_PLAYBOOK)
    assert catalog.playbook_digest(catalog_copy) == digest
    with Path(catalog_copy, "cohesion.md").open("a", encoding="utf-8") as handle:
        handle.write("One more line.\n")
    assert catalog.playbook_digest(catalog_copy) != digest


def test_a_folder_that_is_not_there_holds_no_playbook(tmp_path):
    with pytest.raises(CatalogError, match="no strategies directory"):
        catalog.strategy_files(str(tmp_path / "gone"))
    with pytest.raises(CatalogError, match="no strategies directory"):
        catalog.playbook_digest(str(tmp_path / "gone"))


def test_frontmatter_parses_scalars_lists_and_params():
    meta, body = parse_frontmatter(
        "---\nname: X\nweight: 2.5\nsoft: true\ntags: [a, b]\nn: -4\nf: 1e3\nw: word\nz: ~\n"
        "params:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "X", "weight": 2.5, "soft": True, "tags": ["a", "b"], "n": -4,
                    "f": 1000.0, "w": "word", "z": None, "params": {"K": 3}}
    assert type(meta["n"]) is int and type(meta["f"]) is float
    assert body == "# X\nbody"


def test_the_reference_and_the_live_playbooks_are_valid_and_reference_real_metrics():
    live = catalog.load()                       # the user's playbook: whatever it holds today
    assert live and {h.kind for h in live} <= set(KINDS)
    assert all(h.metric in compute.registry() for h in live if h.kind == "heuristic")
    cat = catalog.load(FIXTURE_PLAYBOOK)        # the reference: every kind and every form
    kinds = {h.kind for h in cat}
    assert kinds == set(KINDS) == {"constraint", "heuristic", "assumption"}
    forms = {h.form for h in cat}
    assert forms == {"limit", "scored", "heuristic", "assumption"}
    assert all(h.form == "heuristic" for h in cat if h.kind == "heuristic")
    assert all(
        h.form == "assumption" and not h.solver_reads for h in cat if h.kind == "assumption")
    assert {h.id for h in cat if h.kind == "assumption"} >= {"optimal-play", "vintage", "objective"}
    registry = compute.registry()
    for h in cat:
        if h.kind == "heuristic":
            assert h.metric in registry and h.metric not in compute.TEXT_METRICS
        for e in (h.when, h.require, h.bonus, h.penalty):
            for name in (e.names if e else []):
                assert name in registry or name[7:] in h.params, (h.id, name)
    assert any(h.id == "open-queue-tanks" for h in cat)


def test_catalog_rejects_a_goal_on_an_unknown_metric(tmp_path):
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: heuristic\ndirection: maximize\nmetric: team.nope\n---\nx\n",
        "utf-8")
    with pytest.raises(CatalogError, match="not a registered fact key"):
        catalog.load(str(tmp_path))
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: constraint\nwhen: team.tanks > params.T\nbonus: 1\n---\nx\n",
        "utf-8")
    with pytest.raises(CatalogError, match="params"):
        catalog.load(str(tmp_path))


def test_a_constraint_is_a_limit_or_scored_and_an_assumption_is_prose(tmp_path):
    def load_one(text):
        (tmp_path / "x.md").write_text(text, encoding="utf-8")
        return catalog.load(str(tmp_path))[0]
    limit = load_one("---\nname: l\nkind: constraint\nrequire: team.tanks <= 2\n---\nx\n")
    assert limit.form == "limit"
    assert load_one("---\nname: s\nkind: constraint\nbonus: team.tanks\n---\nx\n").form == "scored"
    assert load_one("---\nname: p\nkind: assumption\n---\nx\n").form == "assumption"
    # awaiting /strategy
    assert load_one("---\nname: d\nkind: constraint\n---\nx\n").form == "draft"
    assert load_one("---\nname: d\nkind: heuristic\n---\nx\n").pending
    assert not load_one("---\nname: p\nkind: assumption\n---\nx\n").pending
    assert load_one("---\nname: g\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                    "---\nx\n").form == "heuristic"
    for bad in ("---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nbonus: 1\n---\nx\n",
                "---\nname: b\nkind: constraint\nmetric: team.tanks\n---\nx\n",
                "---\nname: b\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                "require: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nsoft: true\n---\nx\n",
                "---\nname: b\nkind: rule\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: assumption\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: goal\ndirection: maximize\nmetric: team.tanks\n---\nx\n",
                "---\nname: b\nkind: strategy\n---\nx\n"):
        with pytest.raises(CatalogError):
            load_one(bad)


def test_weights_override_a_heuristic_for_one_board_and_never_the_file():
    """The playbook tab's sliders: `id:value` strings or a mapping become
    weights clamped to the file's range; the catalog's heuristic carries the
    override in a copy, the loaded one and its file are untouched, and a
    constraint or an unknown id is ignored."""
    parsed = catalog.parse_weights(["a:2", "b:11", "c:-1"])
    assert parsed == {"a": 2.0, "b": 10.0, "c": 0.0}
    assert catalog.parse_weights({"a": "3.5"}) == {"a": 3.5}
    # a malformed weight is refused, never dropped
    for malformed, said in ((["nonsense"], "id:value"), (["d:x"], "not a number"),
                            ({"e": None}, "not a number")):
        with pytest.raises(Refusal, match=said):
            catalog.parse_weights(malformed)
    cat = catalog.load(FIXTURE_PLAYBOOK)
    heuristic = next(h for h in cat if h.kind == "heuristic")
    limit = next(h for h in cat if h.form == "limit")
    before = heuristic.weight
    over = catalog.weighted(cat, {heuristic.id: 7.5, limit.id: 9, "no-such": 1})
    assert next(h for h in over if h.id == heuristic.id).weight == 7.5
    assert heuristic.weight == before                        # the loaded one is untouched
    assert next(h for h in over if h.id == limit.id) is limit  # a constraint's stays its own
    assert catalog.weighted(cat, {}) is cat and len(over) == len(cat)
