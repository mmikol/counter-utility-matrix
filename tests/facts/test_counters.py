"""The mechanical counter matrix and the counter graph, facts/counters.py:
each of the thirteen mechanisms on a pair of heroes built by hand, the
three rules fixed against the research, the graph's weights and the wiki
winning either way; then on the built database, the research's pinned
pairs, a derived answer for every released hero and the matrix's
agreement with the wiki's graph."""

import pytest

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from facts import board_facts, counters
from facts.draft import Draft
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.records import DerivedEdge, Fired, Pairing
from tests import synthetic

# the units a row of each stat is written in: (numerator, denominator)
UNITS = {
    "damage": ("hp", None), "dps": ("hp", "seconds"), "range": ("meters", None),
    "pspeed": ("meters", "seconds"), "cooldown": ("seconds", None),
    "duration": ("seconds", None), "healing_mod": ("percent", None),
    "barrier_health": ("hp", None), "fire_rate": ("shots", "seconds")}


def _piece(
        name, kind=KIND_ABILITY, keywords="", description="", weapon_type=None,
        slot="primary_fire", **stats):
    """A kit piece: a weapon config where weapon_type is given, its stats one
    row each; a (value, text) pair for a flag the wiki words."""
    piece = KitPiece(name, KIND_WEAPON if weapon_type else kind, description=description,
                     keywords=keywords)
    if weapon_type:
        piece.extra.update(weapon=name, weapon_type=weapon_type, slot=slot)
    for code, given in stats.items():
        value, text = given if isinstance(given, tuple) else (given, "%g" % given)
        numerator, denominator = UNITS.get(code, (None, None))
        piece.stats[code].append(Stat(
            code=code, value=value, unit_num=numerator, unit_den=denominator,
            den_value=1.0 if denominator else None, condition=None, text=text))
    return piece


def _gun(name="Rifle", kind="hitscan", dps=100.0, hit=20.0, **stats):
    return _piece(name, weapon_type=kind, dps=dps, damage=hit, **stats)


def _hero(
        name, role="damage", subrole="Specialist", pool=250, weapons=(), abilities=(),
        hero_id=1, **scalars):
    """A hero with its kit and the scalars derive_scalars would set, given."""
    hero = Hero(id=hero_id, name=name, role=role, subrole=subrole, health=pool,
                weapons=list(weapons), abilities=list(abilities))
    hero.pool = pool
    hero.dps = max((w.max_stat("dps") or 0.0 for w in hero.weapons), default=0.0)
    for key, value in scalars.items():
        setattr(hero, key, value)
    return hero


def _fired(winner, loser, support_hps=100.0):
    """{mechanism: strength} the winner reads against the loser."""
    pairing = counters.pairing(counters.features(winner, support_hps),
                               counters.features(loser, support_hps))
    return {f.mechanism: f.strength for f in pairing.fired}


FLIER = _hero(
    "Kite", abilities=[_piece("Hover", KIND_PASSIVE, keywords="flight")],
    weapons=[_gun("Launcher", kind="projectile", dps=90.0, hit=100.0, pspeed=35.0)])
BRAWLER = _hero("Anvil", weapons=[_gun("Hammer", kind="melee", dps=80.0, hit=80.0, range=4.0)])
SNIPER = _hero(
    "Needle", subrole="Sharpshooter", weapons=[_gun("Longshot", dps=120.0, hit=250.0, range=60.0)])


def test_hitscan_at_range_answers_a_light_flier_and_the_flier_a_hero_that_cannot_shoot_up():
    """antiair: a hitscan rifle reaching past FLIER_REACH with 100 dps is
    whole against a flier that flies on a passive. flyer: that flier, 90 dps,
    over a melee hero with no anti-air."""
    assert _fired(SNIPER, FLIER)["antiair"] == 1.0
    assert _fired(FLIER, BRAWLER)["flyer"] == 1.0
    heavy = _hero("Tank", role="tank", pool=500, abilities=FLIER.abilities, weapons=FLIER.weapons)
    assert "antiair" not in _fired(SNIPER, heavy)          # over LIGHT_POOL: no light flier


def test_a_barrier_piercer_answers_a_hero_whose_pool_leans_on_a_barrier():
    shield = _hero("Wall", role="tank", pool=400, abilities=[
        _piece("Barrier", keywords="barrier", barrier_health=600.0, cooldown=5.0)])
    piercer = _hero("Beam", weapons=[_gun("Ray", kind="beam", ignores_barrier=1.0, range=20.0)])
    assert _fired(piercer, shield)["barrier"] == pytest.approx(0.6)     # 600 / (600 + 400)


def test_anti_heal_answers_a_hero_that_heals_itself():
    grenade = _hero("Myrrh", role="support", abilities=[
        _piece("Grenade", healing_mod=-100.0, cooldown=10.0)])
    drinker = _hero("Hog", role="tank", pool=600, self_heal=600.0)
    assert _fired(grenade, drinker)["antiheal"] == 1.0


def test_a_one_shot_answers_a_squishy_and_a_dash_is_no_burst():
    """burst: a 250 hit on a 250 pool is whole. A movement tool's 300 pinned
    hit is the dash, read as control, never as burst."""
    target = _hero("Balm", role="support", subrole="Medic")
    assert _fired(SNIPER, target)["burst"] == 1.0
    charger = _hero("Rook", role="tank", pool=550, weapons=BRAWLER.weapons, melee_only=True,
                    abilities=[_piece("Charge", keywords="displace::movement", damage=300.0,
                                      cooldown=10.0)])
    features = counters.features(charger, 100.0)
    assert (features.burst, features.burst_piece) == (80.0, "Hammer")
    assert "burst" not in _fired(charger, target)


def test_control_answers_a_channel_and_mobility():
    """cc: a stun on an 8 s cooldown is whole; a channelled ultimate is half a
    hero's reliance on channels."""
    stunner = _hero("Rook", abilities=[_piece("Stun", keywords="stun", cooldown=8.0)])
    channel = _hero("Myrrh", abilities=[_piece("Beam Ult", KIND_ULTIMATE, keywords="channel")])
    assert _fired(stunner, channel)["cc"] == 0.5


def test_a_projectile_eater_takes_what_its_family_or_its_description_names():
    """eater: Defense Matrix reads its own flags and eats a hitscan rifle; a
    Javelin Spin, with no family of its own, takes projectiles alone, as its
    description says, and a hitscan shot passes it whole."""
    matrix = _hero("Mech", role="tank", pool=550, abilities=[_piece(
        "Defense Matrix", keywords="negate projectile", description="Block projectiles.",
        duration=2.0, cooldown=1.0)])
    spinner = _hero("Spin", role="tank", pool=500, abilities=[_piece(
        "Javelin Spin", keywords="negate projectile", description="Destroy projectiles.",
        duration=2.0, cooldown=1.0)])
    rifle = _hero("Gun", weapons=[_gun(hit=60.0, range=40.0)])
    rocket = _hero("Rocket", weapons=[_gun("Rocket", kind="projectile", hit=60.0, pspeed=35.0)])
    assert _fired(matrix, rifle)["eater"] == 1.0
    assert "eater" not in _fired(spinner, rifle)
    assert _fired(spinner, rocket)["eater"] == 1.0


def test_a_beam_passes_an_eater_that_cannot_block_it_and_a_hitscan_one_it_never_claimed():
    """eaterproof: Deflect's flags pass a beam whole; a family-less eater's
    details say it cannot block a beam, and a hitscan weapon is outside what
    it takes, neither eaten nor proof against it."""
    deflect = _hero("Blade", abilities=[_piece(
        "Deflect", keywords="negate projectile;;reflect", description="Deflect projectiles.",
        duration=2.0, cooldown=6.0)])
    spinner = _hero("Spin", role="tank", pool=500, abilities=[_piece(
        "Javelin Spin", keywords="negate projectile", description="Destroy projectiles.",
        duration=2.0, cooldown=1.0)])
    beam = _hero("Beam", weapons=[_gun("Ray", kind="beam", ignores_deflect=1.0, range=12.0)])
    rifle = _hero("Gun", weapons=[_gun(hit=60.0, range=40.0)])
    assert _fired(beam, deflect)["eaterproof"] == 1.0
    assert _fired(beam, spinner)["eaterproof"] == 1.0
    assert "eaterproof" not in _fired(rifle, spinner)


def test_armor_answers_a_weapon_of_small_hits():
    """armor: 300 armor of a 500 pool against 5-damage pellets that lose half
    to it: 0.6 x 0.5 / ARMOR_CAP."""
    armored = _hero("Plate", role="tank", pool=500, armor=300)
    spray = _hero("Spray", weapons=[_gun(hit=5.0, range=20.0)])
    assert _fired(armored, spray)["armor"] == pytest.approx(0.6)


def test_a_mobile_flanker_dives_an_immobile_back_line():
    """dive: full mobility (a strong movement tool and a weak one), 100 dps
    over KILL_WINDOW and a 20 hit against a 200-hp Sharpshooter:
    ((150 + 20) / 200 - 0.4) / 0.6."""
    diver = _hero("Blink", subrole="Flanker", weapons=[_gun(dps=100.0, range=15.0)],
                  abilities=[_piece("Leap", keywords="strong movement", cooldown=6.0),
                             _piece("Dash", keywords="evasive", cooldown=4.0)])
    backline = _hero("Scope", subrole="Sharpshooter", pool=200)
    assert _fired(diver, backline)["dive"] == pytest.approx((0.85 - 0.4) / 0.6)


def test_a_cleanse_saves_against_anti_heal():
    cleanser = _hero("Suzu", role="support", abilities=[
        _piece("Suzu", keywords="lesser cleanse", cooldown=10.0)])
    grenade = _hero("Myrrh", role="support", abilities=[
        _piece("Grenade", healing_mod=-100.0, cooldown=10.0)])
    assert _fired(cleanser, grenade)["save"] == 1.0


def test_reach_outranges_an_immobile_short_weapon_and_a_primary_says_how_far_a_hero_fights():
    """range: 60 m against 4 m is past RANGE_GAP by more than RANGE_SPAN. A
    secondary fire that publishes no reach is unknown beside a primary that
    publishes one: the Icicle's 115 m/s would read 57.5 m."""
    assert _fired(SNIPER, BRAWLER)["range"] == 1.0
    mei = _hero("Frost", weapons=[
        _gun("Blaster", kind="beam", dps=110.0, hit=5.5, range=12.0),
        _gun("Icicle", kind="projectile", dps=100.0, hit=85.0, pspeed=115.0,
                slot="secondary_fire")])
    assert (counters.features(mei, 100.0).range, counters.features(mei, 100.0).range_weapon) == (
        12.0, "Blaster")
    bow = _hero("Bow", weapons=[_gun("Bow", kind="projectile", hit=125.0, pspeed=110.0)])
    assert counters.features(bow, 100.0).range == 55.0     # nothing published: 0.5 s of flight


def test_sustained_damage_busts_a_big_tank_pool():
    tank = _hero("Hog", role="tank", pool=600)
    melter = _hero("Melt", weapons=[_gun(dps=150.0, hit=50.0, range=15.0)])
    assert _fired(melter, tank)["tankbust"] == 1.0


def test_a_score_is_the_fired_strengths_capped_and_a_weak_one_does_not_fire():
    pairing = counters.pairing(counters.features(SNIPER, 100.0), counters.features(FLIER, 100.0))
    assert pairing.score == 1.0 and len(pairing.fired) >= 2
    assert all(f.strength >= counters.FLOOR for f in pairing.fired)
    assert [f.strength for f in pairing.fired] == sorted(
        (f.strength for f in pairing.fired), reverse=True)


def _graph():
    """The synthetic World with a derived edge on a pair the wiki leaves out,
    one on a pair it reads the other way, and one where it agrees."""
    w = synthetic.world()
    ids = {h.name: h.id for h in w.heroes.values()}
    fired = (Fired("antiair", 1.0, "hitscan against a flier", "Longshot, hitscan, 60 m"),)
    for loser, winner in (("Kite", "Mortar"), ("Anvil", "Mortar"), ("Gale", "Needle")):
        w.derived[(ids[loser], ids[winner])] = DerivedEdge(
            winner=ids[winner], loser=ids[loser], score=1.0, net=1.0, fired=fired)
        w.matrix[(ids[winner], ids[loser])] = Pairing(score=1.0, fired=fired)
    return w, ids


def test_the_wiki_counts_two_a_derived_edge_one_and_the_wiki_wins_either_way():
    """Gale is answered by Needle in the wiki: 2. Mortar answers Kite only
    by the kit: 1. The wiki reads Mortar answered by Anvil, so a derived
    Mortar over Anvil counts 0, and the wiki's own edge 2."""
    w, ids = _graph()
    assert counters.weight(w, ids["Gale"], ids["Needle"]) == counters.WIKI_WEIGHT == 2
    assert counters.weight(w, ids["Kite"], ids["Mortar"]) == counters.DERIVED_WEIGHT == 1
    assert counters.weight(w, ids["Anvil"], ids["Mortar"]) == 0
    assert counters.weight(w, ids["Mortar"], ids["Anvil"]) == 2
    assert counters.weight(w, ids["Kite"], ids["Anvil"]) == 0


def test_the_board_words_a_derived_edge_with_its_mechanism_and_numbers():
    w, _ = _graph()
    fs = board_facts.generate(w, Draft(map_name="Harbor Gate", red=("Mortar",), blue=("Kite",)))
    texts = [f.text for f in fs.find("hero.vs_derived")]
    assert texts == ["Mortar answers Kite - derived: hitscan against a flier (Longshot, hitscan,"
                     " 60 m)"]
    assert all(f.source == "derived:counters" for f in fs.find("hero.vs_derived"))


def test_derive_fills_only_the_pairs_the_wiki_leaves_out():
    """Four heroes: the sniper answers the flier by the kit, and the wiki
    already reads the brawler answered by the flier, so only the sniper's
    edge is derived."""
    w = World()
    heroes = [_hero(h.name, role=h.role, subrole=h.subrole, pool=h.pool, weapons=h.weapons,
                    abilities=h.abilities, hero_id=i)
                for i, h in enumerate((FLIER, BRAWLER, SNIPER), start=1)]
    for h in heroes:
        w.heroes[h.id] = h
    w.counters.add((2, 1))                  # the flier answers the brawler, in the wiki
    counters.derive(w)
    assert (1, 3) in w.derived and (2, 1) not in w.derived and (1, 2) not in w.derived
    edge = w.derived[(1, 3)]
    assert (edge.winner, edge.loser, edge.score) == (3, 1, 1.0) and edge.net > 0
    assert len(w.matrix) == 6


# --- on the built database ------------------------------------------------------

@pytest.mark.invariant
def test_the_research_pinned_pairs_hold(world):
    """Soldier: 76 over Pharah by anti-air, D.Va over Widowmaker by Defense
    Matrix (its own flags take a hitscan shot), Ana over Roadhog by anti-heal,
    Winston over Reinhardt through the barrier, Symmetra over Genji by a beam
    Deflect cannot take. None moves with the rule fixes: Defense Matrix and
    Deflect read their own families."""
    def strength(winner, loser, mechanism):
        pairing = world.matrix[(world.hero(winner).id, world.hero(loser).id)]
        return {f.mechanism: f.strength for f in pairing.fired}.get(mechanism, 0.0)
    assert strength("Soldier: 76", "Pharah", "antiair") == 1.0
    assert strength("D.Va", "Widowmaker", "eater") >= 0.9
    assert strength("Ana", "Roadhog", "antiheal") >= 0.9
    assert strength("Winston", "Reinhardt", "barrier") >= 0.7
    assert strength("Symmetra", "Genji", "eaterproof") == 1.0
    # the fixes: Javelin Spin takes no hitscan shot, Mei's Icicle is no 57.5 m
    # reach, Reinhardt's Charge no burst
    assert strength("Orisa", "Widowmaker", "eater") == 0.0
    assert strength("Mei", "Junkrat", "range") == 0.0
    assert strength("Reinhardt", "Cassidy", "burst") == 0.0


@pytest.mark.invariant
def test_every_released_hero_has_a_derived_answer_and_the_fill_leaves_the_wikis_pairs(world):
    released = [h for h in world.heroes.values() if h.released]
    for hero in released:
        answers = [win for (win, lose), pairing in world.matrix.items() if lose == hero.id
                   and pairing.score >= counters.THRESHOLD
                   and pairing.score > world.matrix[(lose, win)].score]
        assert answers, "no derived answer: %s" % hero.name
    for loser, winner in world.derived:
        assert (loser, winner) not in world.counters and (winner, loser) not in world.counters
    per_loser = [sum(1 for loser, _ in world.derived if loser == h.id) for h in released]
    assert max(per_loser) <= counters.TOP_ANSWERS
    # the heroes no wiki edge answers are answered by the kit
    bare = [h for h in released if not world.answered_by.get(h.id)]
    assert all(any(loser == h.id for loser, _ in world.derived) for h in bare)


@pytest.mark.invariant
def test_the_matrix_agrees_with_the_wikis_graph_beyond_chance(world):
    """AUC of the score on the wiki's edges against every other ordered pair:
    0.60 sits above the best of 2,000 hero-label shuffles the research drew
    (0.581), so a pull or a rule that breaks the agreement fails here."""
    assert counters.auc(world) >= 0.60
