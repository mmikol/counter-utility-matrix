# Derived insights: the formulas

Evidence lines tagged `derived:<name>` are not rows read from a table - they
are computed by `_derived_insights` in `data/proprietary/dossier.py`, over
the candidate pool (the top-18 hero_meta-ranked union of enemy-answers,
map-strong heroes, and synergy participants), the locked allies A, and the
named enemies E. Constants live at the top of dossier.py; change them there
and here together. Everything below is deterministic SQL + arithmetic - the
model reads these lines, it never computes them.

Notation: `counters(x, y)` means the playbook row "y answers x";
`win_map(h)`, `pick_map(h)` are the all-ranks map_meta figures on the asked
map; `win_all(h)` is the hero's all-ranks blizzard hero_meta figure;
`styles(h)` is the playstyle table's tags; `avail = A ∪ candidates`. An `*`
marks a locked ally in any line.

## derived:coverage
`coverage(h) = |{ e ∈ E : counters(e, h) }|` for `h ∈ avail`.
Emitted for the top 6 with `coverage ≥ COVERAGE_MIN (= 2)`, only when
`|E| ≥ 2`. Why it matters: the intersections show who answers each enemy
separately; coverage finds the picks that answer *several at once* - the
highest-leverage slots in a five-hero budget.

## derived:safe
`safe = { h ∈ candidates : ∀e ∈ E, ¬counters(h, e) }`, first 10 in pool
order. The complement of the CAUTION lines: picks that walk into no counter
already on the field.

## derived:pairings
Synergy edges `(a, b)` with **both** ends in `avail`, ordered by authored
score desc, top `PAIRING_LIMIT (= 6)`. The synergies table lists what works
together in principle; this filters it to what is *actually draftable in
this game*, allies included.

## derived:skeleton
For each style the map rewards (all archetype styles when no map): take the
archetype's role slots; fill each role first with locked allies of that
role, then greedily from candidates of that role ranked by
`(style ∈ styles(h), win_map(h) else win_all(h))` descending, no hero used
twice. Emit the filled skeleton with
`avg win = mean(win_map|win_all of the filled)`, `[has gaps]` when a slot
could not be filled. This is a straw-man comp, not a recommendation - it
exists so the model argues *against something concrete* instead of
assembling from scratch.

## derived:specialists
`delta(h) = win_map(h) − win_all(h)`, both non-null; emit top 6 with
`delta ≥ SPECIALIST_DELTA (= 2.5)` percentage points. Separates "good here"
from "good everywhere": a specialist's map figure is signal about the
ground, not about the hero.

## derived:sleepers
`win_map(h) ≥ SLEEPER_WIN (= 51.0)` and `pick_map(h) ≤ SLEEPER_PICK (= 6.0)`,
top 5 by win. High win at low pick is the classic underrated-here signature -
with the standard caveat that low pick means a small sample and possible
specialist-selection bias, which is why the threshold is conservative and
the model is told the lobby underrates it, not that it is secretly best.

## derived:lean
`lean(s) = |{ e ∈ E : s ∈ styles(e) }|` per style, when `|E| ≥ 2`; the
profile is emitted, plus "leans s" for the argmax only when
`lean(s) > |E| / 2` (a strict majority - heroes carry multiple style tags,
so plurality alone overclaims).

## Computed non-derived lines (documented for completeness)
- **vintage WARNING** (`patches`): fires when
  `max(patches.released) > max(released of any snapshot's patch)`.
- **RANK-SENSITIVE** (`candidates`): `max − min` of the hero's per-rank
  win rates (excluding the all-ranks row) `≥ 6` points.
- **intersections** (`counters+map_meta`, `playstyle+map_meta`): literal
  SQL joins, top 6 by `win_map`.
- **CAUTION** (`counters`): `counters(candidate, e)` for some named `e`.
- **ban lines** (`hero_meta`): `ban_rate > 25` (roster-wide) or `> 20`
  (a named enemy).

## Robustness caveats, stated rather than hidden
All rate-derived insights inherit META's population: Competitive Role Queue,
console, Americas, at the snapshot's patch - stated by the vintage lines.
Coverage/safe/pairings inherit the playbook's editorial nature (counterpick's
judgements, your synergies). The skeleton is greedy, not optimal - by
design: it is a foil for the model, and an optimal solver would be a second
opinion pretending to be a fact.
