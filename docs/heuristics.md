# The heuristics: 100 considerations, mathematically encoded

Choosing a five-hero composition is a hundred small judgements. This
catalog writes every one of them down as a formula over the database -
role shape, healing supply, frontline mass, damage identity, counter
algebra, synergy structure, map fit, meta pressure, tempo, and honest
uncertainty - so that when the model argues for a comp, the arithmetic it
leans on is inspectable, reproducible, and tunable.

The catalog is DATA, not just documentation. It lives in the playbook:

- **`heuristics`** - the 100 rows below, loaded from
  `data/proprietary/heuristics.csv` by the `user.heuristics` pipeline.
- **`heuristic_params`** - the dials. Every threshold a live formula uses
  is a row here, loaded from `data/proprietary/heuristic_params.csv`.
  The dossier reads them at build time, so tuning is: edit the CSV,
  `python -m data.proprietary.load.user.heuristics`, done. The same names
  exist as defaults in `dossier.py` only so a database predating these
  tables still builds.

Each formula carries an honest status:

- **live** - the dossier emits it today, under the evidence tag in its
  `tag` column. 65 formulas.
- **ready** - computable from the current schema, not yet wired into the
  dossier. 22 formulas. This is the implementation queue.
- **blocked** - its inputs are missing; the row names exactly what -
  a column the schema lacks, or (for the stage formulas) a column that
  exists but the scrape's page budget leaves empty. 13 formulas. This
  is the data roadmap.

A test enforces catalog parity: the set of `derived:` tags the dossier
source emits must equal the set on live derived rows here - the catalog
cannot drift from the code it describes.

## Notation

`T, D, S` are the tank/damage/support counts among the five picks;
`E` the named enemies; `A` the locked allies; `C` the candidate pool (the
top-18 hero_meta-ranked union of enemy-answers, map-strong heroes, and
synergy participants); `avail = A ∪ C`. `counters(x, y)` is the playbook
row "y answers x"; `win_map(h)`/`pick_map(h)` are all-ranks map_meta
figures on the asked map; `win_all(h)` the hero's all-ranks hero_meta
figure; `pool(h) = health + shield + armor`; `styles(h)` the playstyle
tags. `NAMES_IN_CAPS` are dials from `heuristic_params` (defaults in
parentheses). An `*` marks a locked ally in any emitted line.
Everything below is deterministic SQL + arithmetic - the model reads
these lines, it never computes them.

## The live formulas, in depth

### derived:coverage
`coverage(h) = |{ e ∈ E : counters(e, h) }|` for `h ∈ avail`. Emitted for
the top 6 with `coverage ≥ COVERAGE_MIN (2)`, only when `|E| ≥ 2`. The
intersections show who answers each enemy separately; coverage finds the
picks that answer *several at once* - the highest-leverage slots in a
five-hero budget.

### derived:teamcover
`|{ e ∈ E : ∃a ∈ A, counters(e, a) }| / |E|`, with the still-unanswered
enemies named explicitly. What the locked picks already handle, before an
open slot is spent on it - the open slots' to-do list, as names.

### derived:netmatchup
`net(c) = |{ e ∈ E : counters(e, c) }| − |{ e ∈ E : counters(c, e) }|`,
top `NET_LIMIT (5)` candidates with both terms shown. Answering two
enemies means less if both also answer you; the difference is the edge.

### derived:safe
`safe = { h ∈ C : ∀e ∈ E, ¬counters(h, e) }`, first 10 in pool order.
The complement of the CAUTION lines: picks that walk into no counter
already on the field.

### derived:shape
The role census `T/D/S` over `A`, with the open-slot count and flags:
TANKLESS (`T = 0`), double tank (`T ≥ 2`), triple+ DPS (`D ≥ 3`),
NO SUPPORT (`S = 0`), solo heal (`S = 1`); plus the archetype deviation
`Σ_r max(0, count_r − slots_r)` against the map's top-style
comp_archetypes row. "Enough healing, triple DPS, one or no tank" -
the shapes that decide games, stated before any hero argument starts.

### derived:healing
`peak(h) = MAX` heal-keyed stat across `h`'s abilities *and* weapons;
supply `= Σ peak` over locked supports; bench `= 2 × median(peak over the
whole support roster)`. UNDER-HEALED flag iff `S ≥ 2` and
`supply < HEAL_MARGIN (0.75) × bench`. "Enough healing" with a real
denominator: the kits' own numbers against the roster's median line.

### derived:frontline
`Σ pool(h)` over locked tanks, each with its armor share. The literal hit
points standing between the enemy and the backline, and how much of them
discount sustained fire.

### derived:barriers
Every enemy `barrier_health` stat (the audit), against
`{ h ∈ A ∪ C : ignores_barrier }` (the piercers). The barrier war stated
as: what they field, who simply does not care.

### derived:pairings
Synergy edges `(a, b)` with **both** ends in `avail`, ordered by authored
score desc, top `PAIRING_LIMIT (6)`. The synergies table lists what works
in principle; this filters to what is *draftable in this game*.

### derived:skeleton
For each style the map rewards: take the archetype's role slots; seat
locked allies first, then fill greedily from same-role candidates ranked
by `(style ∈ styles(h), win_map else win_all)` desc, no hero twice. Emit
with `avg win` and `[has gaps]`. A straw man by design - the model argues
against something concrete instead of assembling from scratch.

### derived:specialists
`delta(h) = win_map(h) − win_all(h)`; top 6 with
`delta ≥ SPECIALIST_DELTA (2.5)`. Separates "good here" from "good
everywhere": a specialist's map figure is signal about the ground.

### derived:sleepers
`win_map(h) ≥ SLEEPER_WIN (51.0)` and `pick_map(h) ≤ SLEEPER_PICK (6.0)`,
top 5 by win. High win at low pick is the underrated-here signature, with
the standing caveat that low pick means small samples - the model is told
the lobby underrates it, not that it is secretly best.

### derived:lean
`lean(s) = |{ e ∈ E : s ∈ styles(e) }|` per style when `|E| ≥ 2`; "leans
s" only for a strict majority (heroes carry multiple tags, so plurality
alone overclaims).

### derived:trend
`Δ(h) = win_all(h)` at the latest blizzard snapshot minus the previous
one, at the all-ranks tier; emitted where `|Δ| ≥ TREND_POINTS (1.5)`.
The snapshot series exists to be differenced; a two-point mover is patch
news the current rates alone cannot show.

### The wide tranche

Beyond the fourteen tags above, another twenty-five formulas emit as
single lines each - kit arithmetic (`derived:teampool`, `squish`,
`weakestlink`, `overhealth`, `dmgmix`, `hitscan`, `rangeprofile`,
`cdtempo`, `burstceiling`, `burstsurvive`, `oneshot`, `antiheal`,
`ultcensus`, `ultburst`), synergy-graph structure (`cohesion`,
`isolated`, `synreach`), coverage algebra (`coverbreadth`, `doublecover`,
`banproof`), and map/meta screens (`styleconsensus`, `offmap`,
`overrated`, `availability`, `pickmass`). Their exact definitions are
their numbered catalog entries below - the catalog IS the specification.

## The dials (heuristic_params)

| dial | default | meaning |
|---|---|---|
| `COVERAGE_MIN` | 2 | a candidate must answer at least this many named enemies to earn a coverage line |
| `SPECIALIST_DELTA` | 2.5 | percentage points above (specialist) or below (off-map) a hero's own baseline win rate |
| `SLEEPER_WIN` | 51.0 | minimum map win rate for a sleeper |
| `SLEEPER_PICK` | 6.0 | maximum pick rate for a sleeper; doubled, the floor for an over-picked underperformer |
| `PAIRING_LIMIT` | 6 | how many proven partners to list per locked pick |
| `NET_LIMIT` | 5 | how many candidates the net-matchup line ranks |
| `TREND_POINTS` | 1.5 | minimum win-rate movement between snapshots worth naming |
| `HEAL_MARGIN` | 0.75 | healing supply below this share of the two-support benchmark raises the under-healed flag |
| `WEAK_TIE` | 2 | synergy scores at or below this are documented doubts (weak-tie audit, when wired) |

## The catalog

One entry per consideration; the same rows, verbatim, sit in the
`heuristics` table. Statuses: **live** / **ready** / **blocked**.

### Role shape

**1. role census** (live, `derived:shape`)
`T, D, S = |{h in picks : role(h) = r}| for r in {tank, damage, support}; always T+D+S = |picks|`
*Inputs:* heroes.role_id, roles.code. *Why:* every other shape heuristic reads these three counts; stating them first makes the rest auditable

**2. tankless flag** (live, `derived:shape`)
`flag iff T = 0`
*Inputs:* role census. *Why:* no one makes space: the comp must win on range or flank tempo, and the dossier should say so out loud

**3. triple-DPS flag** (live, `derived:shape`)
`flag iff D >= 3`
*Inputs:* role census. *Why:* wins the fights it starts and loses attrition; a deliberate shape, but never an accidental one

**4. support drought flag** (live, `derived:shape`)
`flag iff S = 0`
*Inputs:* role census. *Why:* sustain becomes spawn-door only; the strongest single warning a shape can carry

**5. solo-heal flag** (live, `derived:shape`)
`flag iff S = 1`
*Inputs:* role census. *Why:* one support is a plan only when the other four peel for them or self-sustain

**6. double-tank flag** (live, `derived:shape`)
`flag iff T >= 2`
*Inputs:* role census. *Why:* two frontlines trade damage output for space; worth naming because open queue allows it

**7. archetype deviation** (live, `derived:shape`)
`dev = SUM over roles r of max(0, count_r - slots_r), slots from the map's top-style comp_archetypes row`
*Inputs:* role census, map_playstyle, comp_archetypes. *Why:* measures how far the locked picks already sit from the shape the map's own playstyle wants

**8. open-slot role demand** (ready, `derived:shape`)
`demand_r = max(0, slots_r - count_r) per role for the map archetype; lists what the open slots owe`
*Inputs:* role census, comp_archetypes, map_playstyle. *Why:* turns deviation into a prescription: not just 'off-shape' but which roles the remaining picks should fill

**9. subrole balance** (live, `derived:shape`)
`distinct subroles among picks / |picks|; 1.0 = every pick brings a different job`
*Inputs:* heroes.subrole_id, subroles. *Why:* two main tanks or two flex supports overlap jobs even when the role counts look fine

**10. role-flex reserve** (ready, `derived:shape`)
`|{c in C : role(c) = argmax_r demand_r}|; how deep the pool runs for the neediest role`
*Inputs:* candidate pool, open-slot role demand. *Why:* a demand the pool cannot fill is a different problem than one with twelve answers

### Healing and sustain

**11. peak kit heal** (live, `derived:healing`)
`peak(h) = MAX over h's ability_stats and weapon_stats of value where stat_key in (heal, hps)`
*Inputs:* ability_stats, weapon_stats, stat_keys. *Why:* the kit's own biggest heal number, ability or weapon side - measured, not judged

**12. healing supply vs bench** (live, `derived:healing`)
`supply = SUM peak(h) over locked supports; bench = 2 x median(peak over the whole support roster)`
*Inputs:* peak kit heal, roles. *Why:* 'enough healing' needs a denominator; the roster median is the only honest one the schema holds

**13. under-healed flag** (live, `derived:healing`)
`flag iff S >= 2 and supply < HEAL_MARGIN x bench`
*Inputs:* healing supply vs bench, heuristic_params.HEAL_MARGIN. *Why:* only fires when the support line is complete and still light - two Zens is a choice, name it

**14. self-sustain census** (blocked, `derived:selfheal`)
`|{h in picks : h has a heal stat targeting self}|`
*Inputs:* ability_stats (heal target not encoded). *Why:* the schema stores heal amounts but not who receives them; needs a target column on ability_stats

**15. anti-heal exposure** (live, `derived:antiheal`)
`|{e in E : e has healing_mod stat < 0}| and the worst value`
*Inputs:* ability_stats, stat_keys.healing_mod. *Why:* a comp built on sustain answers Ana's grenade differently than one built on burst; the -100 is in the data

**16. overhealth supply** (live, `derived:overhealth`)
`SUM over picks of MAX overhealth stat per kit`
*Inputs:* ability_stats, stat_keys.overhealth. *Why:* temporary health is burst insurance the healing-supply number does not see

**17. healing amplification stack** (ready, `derived:healamp`)
`|{h in picks : h has healing_mod stat > 0}| and the product of (1 + mod)`
*Inputs:* ability_stats, stat_keys.healing_mod. *Why:* amp multiplies the supply number; two amps on one comp is a sustain identity

**18. burst-vs-drip mix** (ready, `derived:healmix`)
`per support: ability-side max heal / weapon-side max heal; >2 = burst kit, <1 = drip kit`
*Inputs:* ability_stats, weapon_stats. *Why:* 350 supply from burst kits and 350 from drip kits survive different damage profiles

**19. sustain uptime proxy** (ready, `derived:healuptime`)
`per heal ability: duration / (duration + cooldown), using each kit's own stats`
*Inputs:* ability_stats, stat_keys.cooldown, stat_keys.duration. *Why:* peak heal on a 14s cooldown is not the same supply as peak heal every 4s

**20. lifeline redundancy** (ready, `derived:lifelines`)
`|{h in picks : peak(h) > 0}|; count of picks carrying any healing at all`
*Inputs:* peak kit heal. *Why:* when the count is exactly S, killing the supports ends the sustain; off-role healing is redundancy

### Frontline and durability

**21. frontline pool** (live, `derived:frontline`)
`SUM over tanks of pool(h), pool = health + shield + armor`
*Inputs:* heroes.health/shield/armor. *Why:* the literal hit points standing between the enemy and the backline

**22. armor share** (live, `derived:frontline`)
`armor(h) / pool(h) per tank, reported beside the pool`
*Inputs:* heroes.armor. *Why:* armor discounts sustained fire; the same pool with more armor beats spam and loses to burst less

**23. team effective HP** (live, `derived:teampool`)
`SUM pool(h) over all five picks`
*Inputs:* heroes.health/shield/armor. *Why:* the ceiling on how much damage the comp absorbs before the first death, ignoring healing

**24. enemy barrier audit** (live, `derived:barriers`)
`per enemy: MAX barrier_health stat in kit; lists every barrier the enemy fields`
*Inputs:* ability_stats, stat_keys.barrier_health. *Why:* a 750hp Brigitte shield and a 1500hp Rein wall demand different amounts of chew

**25. barrier-pierce coverage** (live, `derived:barriers`)
`{h in A union C : h has ignores_barrier stat = 1}`
*Inputs:* ability_stats, stat_keys.ignores_barrier. *Why:* the direct answer to the audit: who simply does not care about the barrier

**26. armor-shred need** (ready, `derived:armorshred`)
`SUM armor over enemies vs |{h in picks : beam weapon or ignores_armor stat}|`
*Inputs:* heroes.armor, weapon_configs.weapon_type, ability_stats. *Why:* heavy enemy armor punishes low-damage-per-hit kits; beams and pierce restore the math

**27. squish index** (live, `derived:squish`)
`|{h in picks : pool(h) <= 225}|`
*Inputs:* heroes.health/shield/armor. *Why:* each 225-pool pick is a one-dive target; three of them is a dive invitation

**28. weakest-link pool** (live, `derived:weakestlink`)
`MIN pool(h) over picks`
*Inputs:* heroes.health/shield/armor. *Why:* focus fire finds the minimum, not the average

**29. shield-regen reliance** (ready, `derived:shieldshare`)
`SUM shield / SUM pool over picks`
*Inputs:* heroes.shield. *Why:* shields recharge out of fight: a high share rewards disengage-heavy playstyles and poke maps

**30. focus-fire survivability** (live, `derived:burstsurvive`)
`MIN pool(h) over picks vs MAX single-hit damage stat over enemy kits`
*Inputs:* heroes pools, ability_stats/weapon_stats damage. *Why:* when the enemy's biggest hit exceeds the weakest pool, one mistake is a death, not a retreat

### Damage profile

**31. weapon-type mix** (live, `derived:dmgmix`)
`counts of picks per weapon_configs.weapon_type (hitscan / projectile / beam / arcing)`
*Inputs:* weapon_configs.weapon_type. *Why:* all-projectile comps share one weakness; the mix is the comp's damage identity in one line

**32. hitscan census** (live, `derived:hitscan`)
`|{h in picks : any weapon_config of h has weapon_type = hitscan}|`
*Inputs:* weapon_configs.weapon_type. *Why:* the closest measured proxy for anti-air the schema holds

**33. vertical-threat answer** (blocked, `derived:antiair`)
`|{h in picks : hitscan}| vs |{e in E : e can fly}|`
*Inputs:* flight is not encoded on heroes. *Why:* needs a mobility/flight flag on heroes; until then the hitscan census is the honest substitute

**34. burst ceiling** (live, `derived:burstceiling`)
`MAX single damage stat over the comp's abilities and weapons`
*Inputs:* ability_stats, weapon_stats, stat_keys.damage. *Why:* whether the comp can delete a 250hp target through one heal window

**35. sustained damage proxy** (ready, `derived:dpsproxy`)
`SUM over picks of MAX damage stat carrying a per-second unit (unit_denominator = second)`
*Inputs:* weapon_stats/ability_stats units. *Why:* the schema stores per-second figures where the wiki does; summing only those keeps the units honest

**36. range profile** (live, `derived:rangeprofile`)
`MAX range stat per pick; comp median splits poke (>=20m) from brawl (<20m)`
*Inputs:* ability_stats/weapon_stats, stat_keys.range. *Why:* a brawl comp on a poke map loses before the fight starts; range is measured, playstyle is judged - use both

**37. beam presence** (ready, `derived:beams`)
`|{h in picks : any weapon_type = beam}|`
*Inputs:* weapon_configs.weapon_type. *Why:* beams ignore travel time and falloff quirks; they are also the armor answer in formula 26

**38. close-range dependency** (ready, `derived:meleerange`)
`|{h in picks : MAX range stat <= 10}|`
*Inputs:* stat_keys.range. *Why:* picks that must touch the enemy to contribute all fail together against disengage comps

**39. area-damage volume** (ready, `derived:spam`)
`|{h in picks : any damage stat with a radius stat on the same ability}|`
*Inputs:* ability_stats, stat_keys.radius. *Why:* area damage pressures chokes and barriers without aim; its count is the comp's siege weight

**40. one-shot exposure** (live, `derived:oneshot`)
`|{h in picks : pool(h) <= MAX enemy single-hit damage}|`
*Inputs:* heroes pools, enemy damage stats. *Why:* the mirror of formula 30 from the enemy's seat: how many of ours die to one cooldown

### Matchup algebra

**41. enemy coverage** (live, `derived:coverage`)
`cov(c) = |{e in E : (e, c) in counters}|; report candidates with cov >= COVERAGE_MIN`
*Inputs:* counters, heuristic_params.COVERAGE_MIN. *Why:* one pick answering two named enemies is worth more than two picks answering one each

**42. team coverage** (live, `derived:teamcover`)
`|{e in E : exists a in A with (e, a) in counters}| / |E|`
*Inputs:* counters, locked allies. *Why:* what the locked picks already answer, before spending an open slot on it

**43. unanswered-enemy list** (live, `derived:teamcover`)
`{e in E : no a in A answers e}, named explicitly`
*Inputs:* team coverage. *Why:* the open slots' to-do list, stated as names rather than a percentage

**44. net matchup** (live, `derived:netmatchup`)
`net(c) = |{e in E : (e,c) in counters}| - |{e in E : (c,e) in counters}|; top NET_LIMIT candidates`
*Inputs:* counters, heuristic_params.NET_LIMIT. *Why:* answering two enemies means less if both of them also answer you; the difference is the real edge

**45. safe picks** (live, `derived:safe`)
`{c in C : no e in E has (c, e) in counters}`
*Inputs:* counters. *Why:* picks the named enemies hold no listed answer to - the low-risk half of the pool

**46. exposure count** (live, `derived:netmatchup`)
`exp(c) = |{e in E : (c, e) in counters}|, reported inside the net-matchup line`
*Inputs:* counters. *Why:* the denominator of risk: how many named enemies were literally listed as this pick's answer

**47. counter diversity** (live, `derived:coverbreadth`)
`distinct enemies answered by the whole comp / |E|, counting each enemy once`
*Inputs:* counters. *Why:* five picks all answering the same Zarya is 20% breadth wearing a 100% costume

**48. coverage redundancy** (live, `derived:doublecover`)
`|{e in E : answered by >= 2 picks}|`
*Inputs:* counters. *Why:* redundant answers survive a swap or a ban; single-threaded answers do not

**49. counter-chain instability** (ready, `derived:counterchain`)
`|{(c, e) : c answers e but some e' in E answers c}| - answers that are themselves answered`
*Inputs:* counters. *Why:* an answer that dies to the enemy's other half is a swap the enemy can force mid-match

**50. ban-resilient coverage** (live, `derived:banproof`)
`team coverage recomputed with the comp's highest-ban-rate answer removed`
*Inputs:* counters, hero_meta.ban_rate. *Why:* if the plan dies when the likely ban lands, it was never a plan; measure the plan minus its ban

### Synergy graph

**51. proven partners** (live, `derived:pairings`)
`top PAIRING_LIMIT synergy edges incident to each locked pick, with scores and notes`
*Inputs:* synergies, heuristic_params.PAIRING_LIMIT. *Why:* the playbook's own memory of what worked next to the pick you already made

**52. internal synergy edges** (live, `derived:cohesion`)
`|{(a, b) in synergies : a, b both in picks}| out of C(5,2) = 10 possible`
*Inputs:* synergies. *Why:* how much of the comp the playbook has actually seen work together

**53. synergy density** (live, `derived:cohesion`)
`internal edges / 10; 0.0 = five strangers, 1.0 = a documented machine`
*Inputs:* internal synergy edges. *Why:* normalizing lets two candidate comps be compared on cohesion in one number

**54. isolated pick** (live, `derived:isolated`)
`{h in picks : no synergy edge from h to any teammate}`
*Inputs:* synergies. *Why:* a great hero with no documented partner in this comp is a solo act - sometimes fine, always worth naming

**55. synergy core** (ready, `derived:core`)
`largest connected component of the synergy subgraph induced by the picks`
*Inputs:* synergies. *Why:* a 4-hero core plus a specialist beats five loosely-paired picks; the component size says which you built

**56. score-weighted cohesion** (live, `derived:cohesion`)
`SUM of synergies.score over internal edges (null scores count 0), reported inside the cohesion line`
*Inputs:* synergies.score. *Why:* when the author scored the pairs, the sum ranks comps beyond mere edge count

**57. candidate synergy reach** (live, `derived:synreach`)
`reach(c) = |{a in A : (a, c) in synergies}|`
*Inputs:* synergies, locked allies. *Why:* the direct draft question: which candidate plugs into the picks already locked

**58. weak-tie audit** (ready, `derived:weakties`)
`internal edges with score <= WEAK_TIE among the picks`
*Inputs:* synergies.score, heuristic_params.WEAK_TIE. *Why:* a low-scored pair the author kept is a documented doubt; surface it rather than average it away

**59. synergy hubs** (ready, `derived:hubs`)
`top heroes by degree in the whole synergy graph, restricted to C`
*Inputs:* synergies. *Why:* high-degree heroes keep the comp flexible: whatever else changes, they still have partners

**60. pairing gravity** (ready, `derived:gravity`)
`rank candidates by (reach(c), mwin(c, map)); synergy first, map rate as tiebreak`
*Inputs:* synergies, map_meta. *Why:* a draft order that respects the playbook's judgement before the population's average

### Map and mode fit

**61. map strategy alignment** (live, `map_strategy`)
`picks appearing in map_strategy for this map, in the authored rank order`
*Inputs:* map_strategy. *Why:* the playbook's explicit per-map picks; alignment with them is a cited argument, not a vibe

**62. style-map intersection** (live, `playstyle+map_meta`)
`heroes whose playstyle matches the map's top styles AND hold mwin >= 50 on it`
*Inputs:* playstyle, map_playstyle, map_meta. *Why:* judged style and measured rate agreeing on the same hero is the strongest single signal we compute

**63. draft skeleton** (live, `derived:skeleton`)
`greedy fill of the map archetype's role slots from C, allies seated first, ranked by (style match, mwin else win); reports avg win`
*Inputs:* comp_archetypes, map_playstyle, playstyle, map_meta, hero_meta. *Why:* a straw-man five to argue against; greedy by design and labeled as such - not an optimum

**64. stage volatility** (blocked, `derived:stagesplit`)
`per pick: MAX - MIN of mwin across the map's stages`
*Inputs:* map_meta.stage_id exists but holds no rows - the per-stage scrape was cut with the map x tier page budget. *Why:* a hero who wins Lighthouse and loses Ruins is a mid-map swap candidate, not a lock - the column is ready; re-widening the rates scrape to stages fills it

**65. attack-defense asymmetry** (blocked, `derived:sidedness`)
`per pick: mwin on attack vs defense for this map`
*Inputs:* side is not encoded on map_meta. *Why:* the rates page does not split by side; needs a side column and a source that measures it

**66. gamemode profile** (ready, `derived:modefit`)
`per pick: mean mwin grouped by maps.gamemode, compared to the current map's mode`
*Inputs:* maps.gamemode, map_meta. *Why:* a hero can be a control specialist rather than an Ilios specialist; the mode average separates the two

**67. style consensus margin** (live, `derived:styleconsensus`)
`map_playstyle top score minus second score for this map`
*Inputs:* map_playstyle. *Why:* a map judged brawl-by-a-landslide should bind the skeleton harder than a coin-flip map

**68. off-map liability** (live, `derived:offmap`)
`{c : mwin(c, map) <= win(c) - SPECIALIST_DELTA} - the specialist formula's dark twin`
*Inputs:* map_meta, hero_meta, heuristic_params.SPECIALIST_DELTA. *Why:* comfort picks that measurably underperform here deserve the same visibility as specialists

**69. comp map breadth** (ready, `derived:mapbreadth`)
`|{maps m : mean mwin of picks on m >= 50}| over all maps`
*Inputs:* map_meta. *Why:* for scrims and tournaments: whether this five is a one-map trick or a portable identity

**70. stage specialist** (blocked, `derived:stagepick`)
`{c : mwin(c, stage) >= mwin(c, map) + SPECIALIST_DELTA for some stage of this map}`
*Inputs:* map_meta.stage_id exists but holds no rows - the per-stage scrape was cut with the map x tier page budget. *Why:* control maps are three maps in a trenchcoat; a Lighthouse specialist is real information - the column is ready; re-widening the rates scrape to stages fills it

### Meta and population

**71. sleepers** (live, `derived:sleepers`)
`{c : mwin(c, map) >= SLEEPER_WIN and pick(c) <= SLEEPER_PICK}`
*Inputs:* map_meta, hero_meta, heuristic_params.SLEEPER_WIN/SLEEPER_PICK. *Why:* wins a lot, picked rarely: either an inefficiency to exploit or a selection artifact to argue about

**72. map specialists** (live, `derived:specialists`)
`{c : mwin(c, map) >= win(c) + SPECIALIST_DELTA}`
*Inputs:* map_meta, hero_meta, heuristic_params.SPECIALIST_DELTA. *Why:* outperforms their own baseline here specifically - the map is doing work for them

**73. enemy style lean** (live, `derived:lean`)
`modal playstyle among E, when one style holds a strict majority`
*Inputs:* playstyle. *Why:* naming the enemy's identity (dive, brawl, poke) frames every counter argument that follows

**74. ban pressure** (live, `hero_meta`)
`flag heroes with ban(h) > 25 as near-certain bans, > 20 as likely`
*Inputs:* hero_meta.ban_rate. *Why:* a comp leaning on a 30%-ban hero needs the plan B written before the ban screen

**75. expected availability** (live, `derived:availability`)
`PRODUCT over picks of (1 - ban(h)/100): the chance the whole five survives the ban screen`
*Inputs:* hero_meta.ban_rate. *Why:* five 10%-ban picks lose the full comp four matches in ten; the product makes that visible

**76. pick-rate mass** (live, `derived:pickmass`)
`SUM pick(h) over picks`
*Inputs:* hero_meta.pick_rate. *Why:* high mass = the mirror-prone meta comp everyone practices against; low mass = off-meta surprise value

**77. win-rate trend** (live, `derived:trend`)
`delta = win(h) at latest snapshot - win(h) at previous; report |delta| >= TREND_POINTS`
*Inputs:* hero_meta across meta_snapshots, heuristic_params.TREND_POINTS. *Why:* the series the snapshots accumulate exists to be differenced; a 2-point mover is patch news

**78. rank sensitivity** (live, `hero_meta`)
`per candidate: MAX - MIN win across tiers; flag spreads >= 6 points`
*Inputs:* hero_meta per tier. *Why:* a hero that wins in Bronze and loses in GM is advice that must know its audience

**79. population proxy caveat** (live, `meta_snapshots`)
`every rate line inherits queue=RQ, platform=console, region=Americas from its snapshot`
*Inputs:* meta_snapshots population columns. *Why:* the rates are a proxy for open queue, and the dossier says so every time rather than once

**80. over-picked underperformer** (live, `derived:overrated`)
`{c : pick(c) >= 2 x SLEEPER_PICK and win(c) < 50}`
*Inputs:* hero_meta, heuristic_params.SLEEPER_PICK. *Why:* the sleeper formula's mirror: popularity the results do not justify - do not copy the lobby

### Ultimates and tempo

**81. damage-ult census** (live, `derived:ultcensus`)
`|{h in picks : h has an ultimate ability carrying a damage stat}|`
*Inputs:* abilities.kind, ability_stats. *Why:* teamfight-ending buttons per fight cycle; zero of them means the comp wins on attrition only

**82. ult burst stack** (live, `derived:ultburst`)
`SUM over picks of MAX damage stat on their ultimate`
*Inputs:* abilities.kind, ability_stats.damage. *Why:* the ceiling of a coordinated all-in; the number a 'we combo our ults' plan is actually claiming

**83. defensive-ult answer** (blocked, `derived:ultanswer`)
`enemy damage ults vs our invulnerability/cleanse ults`
*Inputs:* invulnerability is not encoded as a stat. *Why:* needs an effect taxonomy (invuln, cleanse, lockout) on abilities; text search is not a formula

**84. authored combo notes** (ready, `derived:combos`)
`synergy edges among picks whose note mentions an ultimate by name`
*Inputs:* synergies.note, abilities. *Why:* crude by admission - it reads the author's own words, so it inherits their precision, not the game's

**85. ult economy pacing** (blocked, `derived:ulteconomy`)
`ult charge cost per hero vs damage/healing throughput`
*Inputs:* charge costs are not published or scraped. *Why:* Blizzard does not publish charge requirements; without them any pacing number would be fiction

**86. cooldown tempo** (live, `derived:cdtempo`)
`median cooldown across each pick's abilities; comp median <= 8s reads as high-uptime brawl tempo`
*Inputs:* ability_stats, stat_keys.cooldown. *Why:* short-cooldown kits re-engage faster; the median is a measured stand-in for 'this comp fights constantly'

**87. engage-tool census** (blocked, `derived:engage`)
`|{h in picks : h has a movement ability}|`
*Inputs:* movement is not encoded on abilities. *Why:* needs an ability-effect taxonomy; until then playstyle 'dive' membership is the judged proxy

**88. peel-tool census** (blocked, `derived:peel`)
`|{h in picks : h has a stun/sleep/knockback ability}|`
*Inputs:* crowd control is not encoded on abilities. *Why:* same missing taxonomy as engage; the counters table encodes its consequences, not the tools

**89. objective presence** (blocked, `derived:objtime`)
`time-on-objective per hero`
*Inputs:* no per-hero objective statistics are scraped. *Why:* the rates page publishes win/pick/ban only; this needs a source that does not currently exist in the pipeline

**90. swap-cost awareness** (blocked, `derived:swapcost`)
`ult progress lost per proposed mid-match swap`
*Inputs:* live match state is out of scope for the database. *Why:* the database describes the game, not a running match; kept to mark the boundary deliberately

### Uncertainty and confidence

**91. vintage warning** (live, `meta_snapshots`)
`flag when patches newer than the snapshot's patch exist in patches`
*Inputs:* meta_snapshots.patch_id, patches.released. *Why:* stale rates argue less; the warning explicitly shifts weight toward kit facts and playbook judgement

**92. snapshot age** (live, `meta_snapshots`)
`days between captured_at and today, stated on every dossier`
*Inputs:* meta_snapshots.captured_at. *Why:* the reader should never have to guess how old the numbers are

**93. dual delineation** (live, `meta_snapshots`)
`every snapshot carries both patch_id and season_id, and both predate its capture`
*Inputs:* meta_snapshots, patches, seasons. *Why:* a rate without its patch and season is a number without a 'when'; enforced by invariant test, not convention

**94. sample-size caveat** (blocked, `derived:samplesize`)
`confidence interval on each win rate from its match count`
*Inputs:* the rates page publishes no sample sizes. *Why:* without n, a 55% is indistinguishable from noise on a rare hero; permanent honesty note until a source appears

**95. playbook confidence** (blocked, `derived:confidence`)
`per playbook row: an authored confidence grade weighting how hard the dossier leans on it`
*Inputs:* no confidence column exists on playbook tables. *Why:* today every authored claim argues at equal volume; a confidence column would let the author whisper

**96. citation coverage gate** (live, `store`)
`every recorded pick must cite >= 1 evidence tag that the dossier actually rendered`
*Inputs:* recommendation_picks, recommendation_evidence, store.persist. *Why:* enforced at write time: an answer that cites nothing, or cites the unseen, is refused, not warned

**97. history echo** (live, `recommendations`)
`prior recorded recommendations for the same map, surfaced as evidence`
*Inputs:* recommendations, recommendation_picks. *Why:* the system's own past answers are data; agreeing or breaking with them should be a conscious act

**98. skeleton dissent** (ready, `derived:dissent`)
`picks in the recorded answer that differ from the draft skeleton, counted and named`
*Inputs:* recommendation_picks vs the skeleton at record time. *Why:* divergence from the greedy baseline is where the model earned its keep - or went wrong; either way, log it

**99. catalog parity** (live, `heuristics`)
`set of derived: tags emitted by dossier.py = set of tags on live derived rows in this table`
*Inputs:* heuristics table, dossier source. *Why:* self-referential integrity, enforced by test: the catalog may never drift from the code it describes

**100. the objective** (ready, `derived:argmax`)
`COUNTER = argmax over 5-subsets of C of w1*coverage + w2*cohesion + w3*map fit + w4*meta - w5*exposure`
*Inputs:* every table above; weights would live in heuristic_params. *Why:* the whole database in one line; the skeleton greedily approximates it, and an exact solver is the roadmap

## Other computed lines (documented for completeness)

- **vintage WARNING** (`patches`): fires when
  `max(patches.released) > max(released of any snapshot's patch)`.
- **RANK-SENSITIVE** (`candidates`): `max − min` of a hero's per-rank win
  rates (excluding the all-ranks row) `≥ 6` points.
- **intersections** (`counters+map_meta`, `playstyle+map_meta`): literal
  SQL joins, top 6 by `win_map`.
- **CAUTION** (`counters`): `counters(candidate, e)` for some named `e`.
- **ban lines** (`hero_meta`): `ban_rate > 25` (roster-wide) or `> 20`
  (a named enemy).

## Robustness caveats, stated rather than hidden

All rate-derived heuristics inherit META's population: Competitive Role
Queue, console, Americas, at the snapshot's patch - restated by the
vintage lines on every dossier. Coverage/safe/pairings/netmatchup inherit
the playbook's editorial nature (counterpick's judgements, your
synergies). The skeleton is greedy, not optimal - by design: it is a foil
for the model, and an optimal solver would be a second opinion pretending
to be a fact (formula 100 keeps the honest version of that ambition on
the roadmap). The blocked rows are kept in the catalog precisely so the
gaps stay visible instead of forgotten.
