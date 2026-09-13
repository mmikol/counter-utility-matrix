# authored - the inputs we write

Everything else in the database is fetched by a pull tool. These files are
written by hand, so they are committed, loaded whole-truth by
`load_playbook`, and never discarded by a rebuild.

- `synergies.csv` - `hero,other,score,note`: one PAIR per row, written once
  in either order, stored once. The note is the reasoning the board shows
  and the solver's `cohesion` goal counts.
- `archetypes.csv` - `style,role,slots,note`: what a six-stack of each
  playstyle looks like (2-2-2 by default).
- `map_playstyle.csv` - `map,style,score,note`: what kind of fight each map
  rewards (1-3). The `style-alignment` goal reads the top style.
- `seasons.csv` - `name,started,note`: the coarse delineator of rates
  snapshots; loading recomputes `season_id` on every snapshot.
- `strategies/*.md` - free-form operator notes, loaded whole and shown on the
  board as citable `playbook.strategy` facts.

All follow the same contract: committed, whole-truth on reload, loud errors
on malformed rows or unknown names. The inference layer's own brain - the
heuristics - lives in [`inference/heuristics/`](../../inference/heuristics/).

`recommendations/` holds one markdown transcript per recorded composition,
the durable record; the INFERENCE tables hold the same rows queryably,
mirrored to `data/raw` and restored after every rebuild. Both come from one
write path, `inference/record.py`, whose gates hold whoever decided the comp.
