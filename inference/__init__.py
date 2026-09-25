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
    base          the default engine, always on: a six's win rates on the map,
                  the wiki's synergies and its counters against the other
                  side, the terms the playbook's sit on top of
    scoring       the objective: what one six scores on one board, the
                  default engine's terms and then the playbook's
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
    validate      the playbook against the recorded matches: the verdict from
                  rescore's maps and predict's models, and the data guard
                  that withholds it
    report        what validate answers: its records, JSON the door serves and
                  the page draws, and the same report as text
    rescore       the recorded maps a playbook is judged on - from its digest's
                  first map - each through evaluate from both seats with the
                  default engine off, and the playbook's scoring strategies in
                  the families an ablation drops
    predict       the models validate scores, M0 a coin flip to M4 the heroes
                  plus the playbook score, the splits it scores them on, and
                  each model's log loss and Brier with their intervals
    fit           the statistics validate reads, in pure Python: a ridge
                  logistic fit, log loss and Brier, the bootstrap over
                  sessions, the maps an effect needs
    serve         the engine over HTTP, for the compose stack's board
"""
