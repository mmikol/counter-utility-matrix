"""The INFERENCE LAYER: facts in, the optimal composition out.

    strategies/   the playbook - STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS:
                  one markdown file per strategy, and tuning-log.md, a line
                  per change. A constraint is a limit
                  (require: must hold) or a scored adjustment (bonus/penalty
                  while a condition holds); a heuristic maximises or
                  minimises a metric; an assumption is prose the agent holds
                  a comp to
    README.md     the citation record the playbook is rebuilt from: a line
                  per strategy id, shipped or removed, with the threads a
                  rule was drawn from or the user's word for an assumption
    frontmatter   the dialect a strategy file's frontmatter is written in
    strategy      one strategy: its fields, its kind and form, and the rules
                  every file keeps
    catalog       reads the playbook's files into strategies, orders, mirrors
                  and documents them; AUTHORED, the `sources` row the
                  mirror and the recorded matches carry
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
                  facts the facts layer generated
    plan          the game plan and the verdict in prose
    parallel      the process pool the board splits its searches across
    supersede     latest wins: a board a newer request replaced stops at its
                  next round
    tune          one validated, logged edit to a strategy file; add and complete
    derive        the engine asking the model for a draft's frontmatter
    reach         the board each released hero is optimal on, within a match's bans
    validate      the playbook against the recorded matches: each map rescored
                  from both seats, five models scored out of sample on a time
                  and a sessions split, each strategy family ablated, the data
                  guard and the pin
    predict       the models validate scores, M0 a coin flip to M4 the heroes
                  plus the playbook score, and the splits it scores them on
    fit           the statistics validate reads, in pure Python: a ridge
                  logistic fit, log loss and Brier, the bootstrap over
                  sessions, the maps an effect needs
    serve         the engine over HTTP, for the compose stack's board
"""
