# Experiments: another playbook

A folder here is a playbook of its own - the same markdown files, fewer or
different - that the whole stack runs on when `COUNTER_MATRIX_STRATEGIES`
names it (in `.env`, a path relative to the repo root, for example
`inference/experiments/two-rules`). The board, the inference service, the
MCP tools, the sentry, `/strategy` and `/tune` all follow: a strategy added
or tuned lands in the experiment, not in `strategies/`. The shipped playbook
stays where it is and the tests keep running on it. `db_docs` leaves the
catalog section of `docs/inference.md` alone while an experiment is active,
so the docs keep describing the real playbook.

Unset the variable and recreate the stack to come back.

- `two-rules/` - the two-tank limit and "maximize healing", nothing else:
  the smallest playbook that still produces a six, and a demonstration that
  one heuristic alone makes a degenerate comp (five supports).
