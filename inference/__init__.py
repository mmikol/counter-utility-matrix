"""The INFERENCE LAYER: facts in, the optimal composition out.

    strategies/   the playbook - STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS:
                  one markdown file per strategy. A constraint is a limit
                  (require: must hold) or a scored adjustment (bonus/penalty
                  while a condition holds); a heuristic maximises or
                  minimises a metric; an assumption is prose the agent holds
                  a comp to
    README.md     the citation record the playbook is rebuilt from: a line
                  per strategy id, shipped or removed
    frontmatter   the dialect a strategy file's frontmatter is written in
    strategy      one strategy: its fields, its kind and form, and the rules
                  every file keeps
    catalog       reads the playbook's files into strategies, orders, mirrors
                  and documents them
    expr          the safe expression language the frontmatter uses
    scoring       the objective: what one six scores on one board
    shapes        the legal shapes: the role counts a six may take around the
                  locked picks
    scale         the board's one scale: the seeded reference sample and field
                  every heuristic is normalised against, and each hero's standing
    solver        searches compositions under the constraints and heuristics;
                  players are assumed to play optimally
    engine        infer(), evaluate() and board(): the API over the solver
    result        the Result and Board records and their citations into the
                  facts the UI layer generated
    plan          the game plan and the verdict in prose
    parallel      the process pool the board splits its searches across
    supersede     latest wins: a board a newer request replaced stops at its
                  next round
    tune          one validated, logged edit to a strategy file; add and complete
    derive        the engine asking the model for a draft's frontmatter
    reach         the board each released hero is optimal on, within a match's bans
    serve         the engine over HTTP, for the compose stack's board
"""
