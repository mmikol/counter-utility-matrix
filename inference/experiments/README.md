# Experiments: another playbook

A folder here is a playbook of its own - the same markdown files, fewer or
different - that the whole stack runs on when `COUNTER_MATRIX_STRATEGIES`
names it (in `.env`, a path relative to the repo root, for example
`inference/experiments/from-scratch`). The board, the inference service, the
MCP tools, the sentry, `/strategy` and `/tune` all follow: a strategy added
or tuned lands in the experiment, not in `strategies/`. The shipped playbook
stays where it is and the tests keep running on it. `db_docs` leaves the
catalog section of `docs/inference.md` alone while an experiment is active,
so the docs keep describing the real playbook.

Unset the variable and recreate the stack to come back.

The database's `strategies` table mirrors whichever playbook last loaded
into it, so run the experiment against the compose stack (whose containers
read `.env`); a tool run on the host with the variable exported writes the
experiment into the local cluster's mirror, and the invariant tests then
expect the shipped playbook there - `python -m db.mcp call load_authored
'{"only": ["strategies"]}'` without the variable puts it back.

A playbook of hard limits and prose alone scores nothing: every legal six
ties at zero, the board reads *unscored* wherever a share of the best would
go, and the "optimal" is the solver's tie-break (mean map win rate, then
names). One heuristic or scored constraint is what makes it score.

- `from-scratch/` - a playbook rebuilt one rule at a time. It holds three:
  the two-tank limit (the game's form, enforced on the roster too), a
  heuristic that rewards hitscan cover while red fields a flier, and the
  assumption that all players play optimally. With no flier revealed
  nothing scores and the board reads unscored - by design: each rule is
  added when its absence shows.
