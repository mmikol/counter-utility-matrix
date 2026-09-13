# proprietary - what we author

The other two types of data answer *what is true* about the game:

| type | claim | example |
| --- | --- | --- |
| `data/authoritative` | what a source measured | Ana's biotic grenade has a 10s cooldown; Widowmaker wins 49.5% on Busan |
| `data/heuristic` | what a source judges | Winston is a dive hero; Zarya is countered by Sombra |

This directory holds what **we** author, and what the inference layer
produced. None of it can be re-scraped, so all of it is committed, and
`db_rebuild` restores the recorded output from the `data/raw` mirror.

## The authored inputs (loaded by `load_playbook`)

- `synergies.csv` - `hero,other,score,note`: one PAIR per row, written
  once in either order, stored once. The note is the reasoning the board
  shows and the solver's `cohesion` goal counts.
- `archetypes.csv` - `style,role,slots,note`: what a composition IS - the
  role shape each playstyle wants.
- `map_playstyle.csv` - `map,style,score,note`: what kind of fight each map
  rewards (1-3). The `style-alignment` goal reads the top style.
- `seasons.csv` - `name,started,note`: the coarse delineator of rates
  snapshots; loading recomputes `season_id` on every snapshot.
- `strategies/*.md` - free-form operator notes, loaded whole and shown on
  the board as citable `playbook.strategy` facts.

All follow the same contract: committed, whole-truth on reload, loud
errors on malformed rows or unknown names.

The inference layer's own brain - the heuristics - lives in
[`inference/heuristics/`](../../inference/heuristics/) as markdown, and
`load_playbook` mirrors it into the `heuristics` table. See
[docs/heuristics.md](../../docs/heuristics.md).

## The recorded output

`recommendations/` holds one markdown transcript per recorded composition
(the durable record); the INFERENCE tables hold the same rows queryably,
mirrored to `data/raw` and restored after every rebuild. Both come from
one write path, `inference/record.py`, whose gates hold whoever decided
the comp - the solver, the board's "record this comp" button, or the
`/comp` skill: exactly six real heroes, each citing fact ids the board
for (map, red, the six) actually shows.
