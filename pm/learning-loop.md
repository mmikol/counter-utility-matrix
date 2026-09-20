# The learning loop, and what has to exist first

A plan, not an implementation. Nothing here is built.

## What blocks it

**There are no labels.** No match outcomes are recorded anywhere, and
`inference/fit.py` was deleted in `917cddb` along with the outcome tables.
`inference/strategies/tuning-log.md` still records weights *"fitted to 117
community comps, held-out AUC 0.89"*, and neither the code that fitted them nor
the data it fitted on is in the repository. Until a signal exists, a loop would
optimise against nothing.

Three sources, in order of what they cost and what they are worth:

| source | cost | worth |
| --- | --- | --- |
| the 117 community comps, recovered from history | a day | the fit is reproducible again, but 117 comps cannot identify 238 weighted terms - under collinearity only sums are identifiable |
| ladder or match outcomes, scraped | weeks | the real signal |
| in-app feedback: did you play it, did it hold | slow | ours, and honest |

## The shape on DigitalOcean

Nothing here needs new architecture. The stack is the compose file that already
exists; what it needs is somewhere awake.

| piece | what runs it |
| --- | --- |
| the stack | a Droplet running `compose.yaml` unchanged |
| the database | **Managed PostgreSQL**, not the `db` container: backups and point-in-time recovery, and no volume to lose |
| the caches and the CSV mirror | **Spaces**, S3-compatible, in place of the bind mounts |
| the daily refresh | the `refresher` service, which already does this |
| the cleaning agent | `sentry` already quarantines a strategy file the catalog refuses; `derive` already asks the model for a draft's frontmatter |
| the front door | the Cloudflare Tunnel and Access described in [deploy.md](../docs/deploy.md) |

## The loop itself, gated

A fit that writes weights directly will make the model worse the first time the
data is thin. The loop has three steps and a gate:

1. **Record.** Every board the app answers, with what was picked and - where a
   signal exists - what happened.
2. **Fit.** On a training split, against a held-out split. Never on everything.
3. **Propose, never apply.** A fit writes a proposal. `sentry` validates it
   against the catalog. A weight changes when a person accepts it, and the
   `tuning-log` records why, as it does today.

**The gate:** a proposal that does not improve held-out AUC is refused. Without
it the loop is a random walk with extra steps.

## What stays out

**No user-authored expressions.** The sliders stay: `parse_weights` clamps to
0..10, drops anything unparseable, and reads `id:value` pairs, so there is no
language to escape. A user picking a metric, a direction and a weight is a form.
A user writing an expression is an interpreter, and `inference/expr.py` is not
ready to be one - see [security.md](../docs/security.md).

## Before any of this

The engine's own gaps come first, or the loop fits weights to a solver that
cannot express them:

- **A board costs about twice what it did** since the scale started reading the
  field. `ui/facts/compute.py`'s `team_metrics` is half a board, and 41% of that
  is 2.25M `sum()` calls; a per-hero vector add measured 23x on the additive
  core. `_climb` rebuilds a namespace that differs by one hero.
- **Two heroes reach no board.** Freja and Shion, named in
  `tests/inference/test_reach.py`. That is the playbook, not the engine.
- **The expression language admits `1e400`** and a left-nested exponent tower
  that computes `2^(8^10)` in five seconds. Internal-only today, since nothing
  untrusted reaches it, but it is the first thing to fix if that changes.
