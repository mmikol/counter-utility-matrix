"""The catalog's guards: what a strategy file may be named, how the
playbook in force is chosen, and how the catalog reads as text."""

import pytest

from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK


def test_no_ungated_heuristic_opposes_a_gated_one_on_its_metric():
    """A heuristic with no `when` reads on every board, so one that maximises a
    metric another minimises under a guard fights that guard wherever it holds:
    weight is spent on both sides and the board cannot say which it answered.
    Opposed pairs are fine - they must both be guarded, into different
    situations."""
    playbook = catalog.load()
    heuristics = [s for s in playbook if s.kind == "heuristic"]
    by_metric = {}
    for strategy in heuristics:
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
    assert not fights, fights


def test_a_filename_that_is_not_lowercase_kebab_is_refused_before_the_folder_counts(tmp_path):
    """The id is the filename, so the id rule runs on every file before the
    empty-folder check: a folder holding only a badly named file is refused
    for its name."""
    (tmp_path / "Bad_Name.md").write_text("---\nname: x\nkind: assumption\n---\nx\n",
                                          encoding="utf-8")
    with pytest.raises(catalog.CatalogError, match="lowercase-kebab"):
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
