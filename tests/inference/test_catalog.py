

def test_no_ungated_heuristic_opposes_a_gated_one_on_its_metric():
    """A heuristic with no `when` reads on every board, so one that maximises a
    metric another minimises under a guard fights that guard wherever it holds:
    weight is spent on both sides and the board cannot say which it answered.
    Opposed pairs are fine - they must both be guarded, into different
    situations."""
    from inference import catalog as catalog_module
    catalog = catalog_module.load()
    heuristics = [s for s in catalog if s.kind == "heuristic"]
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
