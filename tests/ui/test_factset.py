"""The FactSet itself: how a fact is filed and found. Pure - no database,
so it runs on the pull-request gate with the rest of the arithmetic."""

from ui.facts.engine import FactSet


def test_a_fact_is_found_under_every_metric_its_sentence_states():
    """One sentence often carries several metrics. `also` indexes the fact
    under each, so a strategy that names any of them cites the line that says
    it - no table in a third module guessing which fact holds which number."""
    fs = FactSet()
    fid = fs.add("team", "blue", "team.tanks", "blue team shape: 2 tank / 2 dps / 2 support",
                 also=("team.damage", "team.supports"))
    for key in ("team.tanks", "team.damage", "team.supports"):
        [found] = fs.find(key, "blue")
        assert found.id == fid and found.key == "team.tanks"   # the key it is worded around
    assert fs.find("team.damage", "red") == []                 # the subject still narrows
    assert fs.count == 1                                       # one fact, three ways in
