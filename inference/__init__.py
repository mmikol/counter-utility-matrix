"""The INFERENCE LAYER: facts in, the optimal composition out.

    strategies/   the brain - STRATEGIES = CONSTRAINTS ∪ HEURISTICS: one markdown
                  file per strategy, of two kinds. A constraint is a limit
                  (require: must hold), a scored adjustment (bonus/penalty
                  while a condition holds) or prose the agent holds a comp
                  to; a heuristic maximises or minimises a metric
    catalog       reads, validates and mirrors the strategies
    expr          the safe expression language the frontmatter uses
    solver        searches compositions under the constraints and heuristics;
                  players are assumed to play optimally
    engine        infer() and evaluate(): the solver plus citations into
                  the facts the user layer generated
    record        the storage gates and the transcript for a decided comp
"""
