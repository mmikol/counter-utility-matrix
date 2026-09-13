# Scaling the meta's granularity

Everything here is about the *fact* tables — the ones holding rates and
playbook rows. Hero kits, weapons, maps and modes have no such dimensions: a
cooldown is a cooldown in every region, on every platform, at every rank.

## The one structural fact that makes this cheap

**A rebuild drops the database and reapplies the migrations from scratch,**
and the migrations ledger makes the Docker entrypoint do the same the moment
the files change. So adding a dimension is never a data migration — there is
no data to migrate. It is an edit to `004_meta.sql`, an edit to `pull_rates`,
and a refetch (recorded comps come back from the `data/raw` mirror).

That means the schema is *not* the constraint on any of this. The constraint is
the request count, and it is multiplicative.

## Where each dimension stands

| dimension | column exists? | populated today | to widen it |
| --- | --- | --- | --- |
| tier — `hero_meta` | yes | 9 ranks | already there |
| tier — `map_meta` | yes | all-ranks only | restore the inner loop; ×9 requests |
| region — `hero_meta` | yes | Americas | drop the region pin; ×3 requests |
| region — `map_meta` | yes | Americas | drop the region pin; ×3 requests |
| platform | as `meta_snapshots.platform` | Console | fetch `input=PC` too; ×2 requests |
| input device | yes | controller (entailed by console) | a source that splits PC by device (see below) |
| map stage | `map_stages` 36 rows | stage list loaded | a source with per-stage rates (see below) |
| any — PLAYBOOK tables | deliberately none | — | judgements are tier- and region-agnostic by design: a current read of the game, not a measurement of a population. Dimensioned numbers live in META |

## The two that are not merely unfetched

**Input device is not the same as platform**, and only one of them is
published. Blizzard's filter offers `PC` and `Console` — a platform. It says
nothing about whether that player held a controller or a mouse, and both
platforms support both. A `input` dimension would need a source that actually
separates them; none of the three does. The column is deliberately absent
rather than filled with a guess inferred from platform.

**Map stages exist; per-stage rates do not.** The stage list itself is now
loaded — 36 stages across the ten Control and Flashpoint maps, read from each
map's wiki article — so `map_stages` is populated and `map_meta.stage_id` has
a real vocabulary to point at. What is still missing is any source that
reports rates *per stage*: Blizzard's map filter stops at whole maps, so every
`map_meta` row keeps `stage_id` NULL until someone publishes
King's-Row-first-point numbers.

## Why the request count is the real ceiling

The dimensions compose multiplicatively, and the source refuses long sweeps.
`map_meta` at full granularity:

```
30 maps × 9 ranks × 3 regions × 2 platforms = 1,620 requests
```

The rates endpoint began answering `504 Gateway Time-out` partway through a
**280**-request sweep, and then closed connections outright. 1,620 is not
reachable in one pass at any polite rate.

What makes it tractable is that the page cache is permanent and keyed by the
full query, so granularity can be widened one dimension at a time across many
runs, each resuming from what is already on disk. The order to widen in is
whichever dimension separates the numbers most, and rank is the current
evidence-backed answer: Widowmaker swings about fifteen points between Bronze
and Grandmaster on a single map, which the all-ranks figure averages away.

## Every dimension now has a column

There is no longer a dimension that needs a migration to add — only data to
put in one. Two are empty because nothing publishes them:
`meta_snapshots.input` and `map_meta.stage_id` are both NULL on every
row, and `map_stages` has no rows at all. The rest carry a real value that
used to be implicit: `map_meta.region_id` says Americas rather than
leaving it to be inferred from the database as a whole, the playbook tables
say all-ranks rather than leaving rank unstated, and `meta_snapshots.input`
says controller because the console platform entails it.

`stage_id` is nullable and NULL means the whole map, so `map_meta` uses
`UNIQUE NULLS NOT DISTINCT`. Postgres treats NULLs as distinct by default,
which would let the same hero, map and rank be inserted over and over - every
whole-map row looking unique because its stage is NULL.

## What is already safe to assume

- adding a dimension never invalidates existing rows, because there are none
  that survive a run
- every fact table already carries `snapshot_id`, so a dimension that belongs
  to the whole capture (platform, queue) can be added to `meta_snapshots`
  without touching the fact tables at all
- `map_meta` rows already carry `tier_id`, set to the all-ranks tier, so
  restoring rank granularity there needs no migration whatsoever
