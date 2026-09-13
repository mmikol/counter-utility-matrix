# proprietary — the strategy layer

**Partially implemented: the authored playbook is real.** Five committed
CSVs load into the playbook — `synergies.csv`, `archetypes.csv` (the role
shape each style's comp wants), `map_playstyle.csv` (what kind of fight
each map rewards), and the tunable brain: `heuristics.csv` (the
100-consideration catalog behind the dossier's `derived:` lines) with
`heuristic_params.csv` (its dials) — see "The authored pipelines" below.
The inference layer is built too — see "Asking for a comp".

## What this type of data is for

The other two types answer *what is true* about the game:

| type | claim | example |
| --- | --- | --- |
| `data/authoritative` | what a source measured | Ana's biotic grenade has a 10s cooldown; Widowmaker wins 49.5% on Busan |
| `data/heuristic` | what a source judges | Winston is a dive hero; Zarya is countered by Sombra |

This type answers *what we should do about it* — and, unlike the other two, its
input is **ours**, not scraped. A user writes strategies in whatever form suits
them: a paragraph of prose, a list of rules, a note about a team's tendencies, a
scribbled preference for brawl over poke. There is no schema to fill in.

A model then reads that alongside everything in the database — the roster and
its abilities, the map pool, the rates, the playbook of counters and best maps
— and infers a team composition.

```
COUNTER = MAX[ HEROES ∩ MAPS ∩ META ]
```

The other types supply the three sets. This one supplies the objective
function: which maximum, for whom, under what constraints.

## Why it is a separate type

Because its data cannot be re-scraped. Drop the database and rerun the
pipeline, and everything in the authoritative and heuristic types comes back
byte for byte. Anything written here does not — it exists only because someone
wrote it. That difference in provenance is the whole reason for the separation:
these are the rows that need backing up, and the ones a rebuild must never
silently discard.

It is also the only type whose output is an *opinion the database produced*,
rather than an opinion it recorded. A heuristic row says "counterpick.gg thinks
Sombra beats Zarya". A proprietary row would say "given your strategy notes and
this map, play Sombra". Those want to be told apart when reading results back.

## The authored pipelines (built)

`synergies.csv` holds one ordered claim per row — `hero,other,score,note` —
and is committed, because it cannot be re-scraped. Synergy is bidirectional - a pair is written once,
in either order, and stored once (counters, by contrast, are arrows). The
loader treats the file as the whole truth (the table mirrors it exactly),
refuses unknown hero names and duplicated pairs loudly instead of dropping
rows, and records everything under the `user` source. The `note` column is not decoration: the reasoning is what a strategy
model will actually condition on.

`seasons.csv` (`name,started,note`) is the coarse delineator of meta
snapshots - authored because the wiki's season pages are undated lore. Loading
it recomputes `season_id` on every existing snapshot, so a season added later
corrects history. The current era's chapters ("Reign of Talon") have no
published dates yet; add them here the day they do.

`archetypes.csv` (`style,role,slots,note`) defines what a composition IS - the
role shape each playstyle wants, with the note naming who typically fills the
slot. `map_playstyle.csv` (`map,style,score,note`) says what kind of fight
each map rewards, on the same 1-3 scale.

`heuristics.csv` is the catalog of every consideration the dossier
mathematically encodes when weighing a comp - 100 numbered formulas with an
honest status each (`live` / `ready` / `blocked`) - and
`heuristic_params.csv` is its dial panel: the thresholds the live formulas
read at build time. Tuning is continuous by design: edit a value, re-run
`python -m data.proprietary.load.user.heuristics`, and the next dossier
computes with it - no code change. The whole catalog is rendered in
[docs/heuristics.md](../../docs/heuristics.md).

All of them follow the same contract:
committed, whole-truth on reload, loud errors on malformed rows.

## Asking for a comp (built)

```bash
python -m data.proprietary.recommend --map "King's Row" \
    --enemy Zarya --enemy Mei --ask "we keep losing the first fight"
```

`dossier.py` (deterministic, model-free, tested) assembles numbered evidence
lines — E1, E2, ... — from the whole database, ~90–140 lines per question
across 16+ tables: its own vintage first (capture date, patch, season, and a
loud warning when patches shipped since), the map with its stages, styles,
leaders and strugglers, each enemy profiled to kit depth (HP pools, ultimates,
cooldowns, which abilities pierce barriers/matrix/deflect), the
COUNTER = MAX[...] intersections pre-joined (`counters+map_meta`,
`playstyle+map_meta`), a ranked candidate pool with full profiles,
rank-sensitivity spreads and CAUTION lines where a known enemy answers the
candidate, role passives, archetype slot shapes, every authored synergy and
strategy note, meta leaders and ban pressure, a block of `derived:`
analytics computed by formula (multi-enemy coverage, safe picks, available
pairings, greedy draft skeletons around your locked picks, map specialists,
sleepers, enemy style lean — see docs/heuristics.md) — and what this layer
itself recommended before on the same map. The model that reads it is the Claude
Code session itself: the `/comp` skill (`.claude/skills/comp`) turns any
session in this repo into the inference layer - subscription-covered, no API
key, no per-token bill. The session runs the dossier CLI, decides under the
skill's ground rules, answers in chat with per-pick citations, and records
through `record.py` -> `store.py`, where two gates hold whoever the author
is: the shape (exactly five picks, each with a why and evidence) and the
meaning (an invented hero or a citation of evidence never shown is refused,
not stored). Strategy notes from `strategies/*.md` ride inside the dossier
as citable lines.

Every exchange lands twice: in the INFERENCE tables (`recommendations`,
`recommendation_picks`, `recommendation_evidence` — queryable, wiped by
rebuild like any session state) and as a markdown transcript in
`recommendations/` (committed, durable).

The three needs sketched here originally all now exist: free-form strategy
input (`strategies/*.md` → the strategies table), the full
asked/shown/answered record (`recommendations.prompt` / `.response`), and
per-pick links back to justifying rows (`recommendation_evidence`). What
remains judgement is the dossier's selectivity — which slices of the
database are worth showing — and that is tuned in `dossier.py`, in the open.

## What has to be true first

A recommendation is only as good as the granularity underneath it. See
[docs/scaling.md](../../docs/scaling.md): today the meta is Americas, one
platform, all ranks combined, and whole maps rather than map stages. A team
composition for a specific stage, at a specific rank, on a specific platform is
not answerable from the current data — not because the model could not reason
about it, but because the numbers underneath are not sliced that finely yet.
