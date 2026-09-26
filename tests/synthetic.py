"""A synthetic World: twelve released heroes, four a role, one announced hero
and three maps, built by hand with no database, so the metric, derivation
and board-facts tests work every expected value from the inputs below.

    w = synthetic.world()

Every name and number here is invented. Each value sits where a test needs
one: on a rule's boundary (a 250 hit at range against SQUISHY_POOL, and a
swing over it from a melee-only hero and from one with a gun as well; 30 m
and 25 m hitscan against FLIER_REACH; a map lift of exactly
SPECIALIST_DELTA; a stage's terrain on STAGE_MENTIONS and one mention
short), a flying tank and a flying damage hero, a form's armor, a hero that
heals only off its own damage and one that heals only itself, and a tie
for the last seat of the likely six.

The rates are exact binary fractions, so the arithmetic is exact. A hero's
map rate is its overall win plus a lift per map, chosen so each style's lift
across Harbor Gate, Ember Ruins and Salt Flats reads brawl +2, 0, -2; dive
-2, +2, 0; poke -2, -2, +4 - Flint carries dive and poke, and counts a half
in each.

world() fills the World the way tables.load's reads do, sets heal_bench,
hps_bench, pool_medians and ult_cap as inputs, then runs what load runs after
its reads, in its order: derive_rates, best_maps, the terrain, the stages'
terrain, the styles and the ultimate cap. derive_scalars does not run: there
are no kit rows, so a hero's kit numbers are given whole.
"""

import datetime
from typing import TypedDict

from db.data.names import name_key
from facts import tables
from facts.compute import STAGE_MENTIONS
from facts.model import Hero, Map, World
from facts.records import MapRate, Rates, Snapshot, StageTerrain, Synergy

HARBOR, EMBER, SALT = 1, 2, 3           # the map ids, in the order a hero's lifts are given
MAP_IDS = (HARBOR, EMBER, SALT)

# (loser, winner): the loser is countered by the winner, as the wiki words it
COUNTERS = (
    ("Mortar", "Anvil"), ("Gale", "Needle"), ("Gale", "Flint"), ("Anvil", "Gale"),
    ("Needle", "Kite"), ("Balm", "Rook"))
# (a, b, score 1 or 2, note): pairs the wiki says play well together
SYNERGIES = (
    ("Anvil", "Balm", 2, "the charm keeps the hammer swinging"),
    ("Kite", "Gale", 2, "both take the fight to the air"),
    ("Gale", "Sorrel", 1, "the field covers a dive"),
    ("Needle", "Tansy", 2, "the boost lands on the long shot"),
    ("Mortar", "Myrrh", 1, "the dart holds a target in the pit"))


class _RateFields(TypedDict):
    """A released hero's rates, as Hero's keyword fields."""
    win: float
    pick: float
    ban: float
    by_tier: dict[str, Rates]
    prev_win: float
    map_rates: dict[int, MapRate]


def _rates(
        win: float, pick: float, ban: float, lifts: tuple[float, float, float],
        picks: tuple[float, float, float], *, spread: float = 2.0,
        trend: float = 0.0) -> _RateFields:
    """The all-ranks rates; two tiers `spread` win points apart around them;
    the previous capture's win, `trend` points behind; and on each map, in
    MAP_IDS order, the overall win plus the map's lift and the map's pick."""
    return _RateFields(
        win=win, pick=pick, ban=ban,
        by_tier={
            "bronze": Rates(win - spread / 2, pick, ban),
            "grandmaster": Rates(win + spread / 2, pick, ban)},
        prev_win=win - trend,
        map_rates={
            mid: MapRate(win + lift, on_map)
            for mid, lift, on_map in zip(MAP_IDS, lifts, picks, strict=True)})


def _tanks() -> list[Hero]:
    """Two bodies that fight up close, a flier and one with a shield."""
    return [
        # melee only: the biggest hit on the roster is a swing
        Hero(
            id=1, name="Anvil", role="tank", subrole="Stalwart", health=400, armor=300,
            pool=700, styles={"brawl"}, dps=85.0, burst=300.0, melee=True, melee_only=True,
            weapon_kinds={"melee"}, max_range=5.0, barrier_hp=1200.0,
            cc_tools=["Quake Slam"], mobility_tools=["Bull Rush"], cooldowns=[7.0, 10.0],
            median_cooldown=8.5, ult_damage_raw=250.0, ult_deals_damage=True,
            **_rates(50.0, 11.0, 4.0, (2.5, 0.0, -3.0), (12.0, 9.0, 8.0))),
        # a flying tank, and an ultimate over the roster's cap
        Hero(
            id=2, name="Kite", role="tank", subrole="Initiator", health=350, armor=300,
            pool=650, styles={"dive"}, dps=110.0, burst=30.0, weapon_kinds={"projectile"},
            max_range=15.0, flyer=True, mobility_tools=["Thrusters"], cooldowns=[4.0, 8.0],
            median_cooldown=6.0, ult_damage_raw=900.0, ult_deals_damage=True,
            **_rates(51.0, 9.0, 10.0, (-1.0, 3.0, 1.0), (8.0, 11.0, 7.0))),
        # a form's 275 armor for half its time: 137.5 more, outside the spawn pool;
        # the form's swing is the biggest hit, though a gun is its other weapon
        Hero(
            id=3, name="Mortar", role="tank", subrole="Bruiser", health=275, armor=100,
            pool=375, form_armor=137.5, styles={"brawl"}, dps=100.0, burst=260.0, melee=True,
            weapon_kinds={"projectile", "melee"}, max_range=30.0, pierces_barrier=True,
            cc_tools=["Grasping Pit"], cooldowns=[7.0, 8.0], median_cooldown=7.5,
            **_rates(49.0, 5.0, 2.0, (2.0, 1.0, -1.0), (6.0, 5.0, 4.0))),
        # heals only itself
        Hero(
            id=4, name="Quarry", role="tank", subrole="Bruiser", health=450, shield=200,
            pool=650, styles={"poke"}, dps=120.0, burst=150.0, self_heal=300.0,
            weapon_kinds={"projectile"}, max_range=20.0, cc_tools=["Chain Hook"],
            cooldowns=[6.0, 8.0], median_cooldown=7.0,
            **_rates(48.0, 7.0, 1.0, (-2.0, -3.0, 5.0), (4.0, 3.0, 9.0))),
    ]


def _damage() -> list[Hero]:
    """Read in no name order, as a table's rows come: a tie broken by name
    must not fall to whoever was read first."""
    return [
        # 25 m of hitscan, short of a flier; heals only off its own damage
        Hero(
            id=5, name="Rook", role="damage", subrole="Flanker", health=300, pool=300,
            styles={"brawl"}, dps=150.0, burst=180.0, hitscan=True, hitscan_range=25.0,
            weapon_kinds={"hitscan"}, max_range=25.0, lifesteal=0.3,
            cleanse_tools=["Shade Step"], invuln_tools=["Shade Step"],
            mobility_tools=["Shadow Walk"], cooldowns=[6.0, 8.0], median_cooldown=7.0,
            ult_damage_raw=500.0, ult_deals_damage=True,
            **_rates(51.5, 8.0, 5.0, (2.0, -2.5, -2.0), (7.0, 5.0, 6.0), trend=-1.0)),
        # 250 at range, the most banned and the most rank-sensitive
        Hero(
            id=6, name="Needle", role="damage", subrole="Sharpshooter", health=200, pool=200,
            styles={"poke"}, dps=90.0, burst=250.0, hitscan=True, hitscan_range=70.0,
            weapon_kinds={"hitscan"}, max_range=70.0, mobility_tools=["Grapple"],
            cooldowns=[8.0, 12.0], median_cooldown=10.0, map_bans={HARBOR: 40.0},
            **_rates(52.0, 10.0, 30.0, (-2.0, -3.0, 4.5), (9.0, 8.0, 12.0), spread=7.0)),
        # flies, publishes no reach, and is rising
        Hero(
            id=7, name="Gale", role="damage", subrole="Specialist", health=250, pool=250,
            styles={"dive"}, dps=120.0, burst=120.0, weapon_kinds={"projectile"}, flyer=True,
            aoe_count=2, aoe_damage_count=2, mobility_tools=["Jump Jet"], cooldowns=[6.0, 12.0],
            median_cooldown=9.0, ult_damage_raw=600.0, ult_deals_damage=True,
            **_rates(49.5, 5.0, 12.0, (-3.0, 1.0, -1.0), (5.5, 7.0, 4.0), trend=2.0)),
        # 30 m of hitscan: enough to answer a flier
        Hero(
            id=8, name="Flint", role="damage", subrole="Flanker", health=225, pool=225,
            styles={"dive", "poke"}, dps=140.0, burst=120.0, hitscan=True,
            hitscan_range=30.0, weapon_kinds={"hitscan"}, max_range=30.0,
            mobility_tools=["Blink"], cooldowns=[5.0, 8.0], median_cooldown=6.5,
            **_rates(50.5, 6.0, 6.0, (-2.0, 2.0, 0.0), (7.0, 6.0, 5.0))),
    ]


def _supports() -> list[Hero]:
    """Four whose peak heals and rates set the benches, and an announced one."""
    return [
        # a cleanse and an invulnerability that land on a teammate
        Hero(
            id=9, name="Balm", role="support", subrole="Tactician", health=225, pool=225,
            styles={"brawl"}, dps=50.0, burst=120.0, weapon_kinds={"projectile"},
            peak_heal=70.0, hps=60.0, cleanse_tools=["Warding Charm"],
            invuln_tools=["Warding Charm"], team_cleanse_tools=["Warding Charm"],
            save_tools=["Warding Charm"], mobility_tools=["Swift Step"],
            cooldowns=[6.0, 14.0], median_cooldown=10.0, map_bans={HARBOR: 10.0},
            **_rates(50.0, 9.5, 8.0, (2.0, 0.0, -2.0), (10.0, 8.0, 7.0))),
        Hero(
            id=10, name="Myrrh", role="support", subrole="Tactician", health=250, pool=250,
            styles={"brawl"}, dps=70.0, burst=75.0, weapon_kinds={"projectile"},
            max_range=40.0, peak_heal=75.0, hps=80.0, antiheal=-50.0, cc_tools=["Hush Dart"],
            cooldowns=[10.0, 12.0], median_cooldown=11.0,
            **_rates(49.0, 6.0, 3.0, (1.5, 1.5, -2.0), (5.5, 6.5, 5.0))),
        Hero(
            id=11, name="Sorrel", role="support", subrole="Survivor", health=250, pool=250,
            styles={"dive"}, dps=80.0, burst=90.0, weapon_kinds={"projectile"},
            max_range=45.0, peak_heal=90.0, hps=70.0, invuln_tools=["Stasis Field"],
            save_tools=["Stasis Field"], deployables=["Stasis Field"],
            mobility_tools=["Leap Boots"], cooldowns=[13.0, 15.0], median_cooldown=14.0,
            **_rates(50.5, 5.5, 2.0, (-2.0, 2.0, 0.0), (5.0, 6.0, 4.5))),
        Hero(
            id=12, name="Tansy", role="support", subrole="Medic", health=225, pool=225,
            styles={"poke"}, dps=60.0, burst=20.0, weapon_kinds={"projectile"},
            peak_heal=60.0, hps=55.0, dmg_amp=30.0, invuln_tools=["Second Wind"],
            save_tools=["Second Wind"], mobility_tools=["Guardian Leap"],
            cooldowns=[1.5, 30.0], median_cooldown=15.75,
            **_rates(51.0, 7.5, 1.0, (-2.0, -2.0, 4.5), (4.5, 5.0, 8.0))),
        # announced: the wiki's preview kit and no rates
        Hero(
            id=13, name="Wisp", role="support", subrole="Medic", health=225, pool=225,
            status="announced", release_date=datetime.date(2026, 12, 1), styles={"dive"},
            dps=50.0, burst=60.0, weapon_kinds={"projectile"}, peak_heal=80.0, hps=90.0,
            cooldowns=[8.0], median_cooldown=8.0),
    ]


def _maps() -> list[Map]:
    """A Hybrid and a Control map with terrain text, which z-score to one sd
    either side of their mean, and a Push map with no text and no stages."""
    harbor = Map(HARBOR, "Harbor Gate", "Hybrid")
    harbor.stages = ["Assault", "Escort"]
    harbor.terrain = {
        "chokes": 6.0, "interiors": 3.0, "high_ground": 1.0, "flanks": 1.0,
        "sightlines": 3.0, "open_ground": 0.5, "hazards": 0.5, "cover": 2.0}
    ember = Map(EMBER, "Ember Ruins", "Control")
    ember.stages = ["Courtyard", "Forge", "Spire"]
    ember.terrain = {
        "chokes": 2.0, "interiors": 1.0, "high_ground": 3.0, "flanks": 2.5,
        "sightlines": 2.0, "open_ground": 1.5, "hazards": 2.0, "cover": 1.0}
    # Forge stresses hazards on the mentions a stage fact needs, Spire its
    # high ground on one fewer; Courtyard has no text of its own
    ember.stage_terrain = {
        "Forge": {"hazards": StageTerrain(12.0, STAGE_MENTIONS)},
        "Spire": {"high_ground": StageTerrain(9.0, STAGE_MENTIONS - 1)}}
    return [harbor, ember, Map(SALT, "Salt Flats", "Push")]


def world() -> World:
    """The synthetic World, fresh on every call: tests change it."""
    w = World()
    for hero in _tanks() + _damage() + _supports():
        w.heroes[hero.id] = hero
        w.by_key[name_key(hero.name)] = hero.id
    for m in _maps():
        w.maps[m.id] = m
        w.maps_by_key[name_key(m.name)] = m.id
    ids = {h.name: h.id for h in w.heroes.values()}
    for loser, winner in COUNTERS:
        w.counters.add((ids[loser], ids[winner]))
        w.answered_by[ids[loser]].add(ids[winner])
        w.answers[ids[winner]].add(ids[loser])
    for a, b, score, note in SYNERGIES:
        pair = Synergy(score, note)
        w.synergies[frozenset((ids[a], ids[b]))] = pair
        w.partners[ids[a]][ids[b]] = pair
        w.partners[ids[b]][ids[a]] = pair
    w.snapshots = [Snapshot(
        source="blizzard", captured="2026-09-01", patch="September 1, 2026 Patch",
        released="2026-09-01", season="Season 1", queue="competitive_role_queue",
        platform="pc", region="Americas")]
    w.subrole_passives = {
        "Stalwart": "Takes less knockback.", "Bruiser": "Heals a little on a kill.",
        "Sharpshooter": "Deals more damage from far away."}
    w.tier_names = {"bronze": "Bronze", "grandmaster": "Grandmaster and Champion"}
    w.catalog_counts = {"constraint": 2, "heuristic": 3, "assumption": 2}
    # the released supports' peak heals are 60, 70, 75 and 90, their rates
    # 55, 60, 70 and 80: twice each median. The cap is the largest flat
    # figure an ultimate publishes, which needs kit rows: given here
    w.heal_bench, w.hps_bench, w.ult_cap = 145.0, 130.0, 600.0
    # each role's median pool, a form's armor in: tanks 512.5 (Mortar's form),
    # 650, 650 and 700; damage 200, 225, 250 and 300; supports 225, 225, 250 and
    # 250. The load sets them over the released heroes; given here as the
    # benches are, so a test can move one alone
    w.pool_medians = {"tank": 650.0, "damage": 237.5, "support": 237.5}
    for hero in w.heroes.values():
        hero.derive_rates()
    tables.best_maps(w)
    tables.map_terrain(w)
    tables.stage_terrain(w)
    tables.map_styles(w)
    for hero in w.heroes.values():
        hero.cap_ult(w.ult_cap)
    return w
