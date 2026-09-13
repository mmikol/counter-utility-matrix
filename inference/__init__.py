"""The INFERENCE LAYER: facts in, the optimal composition out.

    heuristics/   the brain - one markdown file per heuristic, of three
                  kinds: constraints (must hold), goals (maximise or
                  minimise a metric), strategies (prose, optionally with a
                  bonus/penalty the solver adds while a condition holds)
    catalog       reads, validates and mirrors the heuristics
    expr          the safe expression language the frontmatter uses
    solver        searches compositions under the constraints, goals and
                  strategies; players are assumed to play optimally
    engine        infer() and evaluate(): the solver plus citations into
                  the facts the user layer generated
    record        the storage gates and the transcript for a decided comp
"""
