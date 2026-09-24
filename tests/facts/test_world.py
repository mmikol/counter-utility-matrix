"""The World itself: every data table the load reads, the names a hero or a
map resolves by, one hero to a seat, and the model's own lookups and
derivations on the synthetic World. The kits the load reads are
tests/facts/test_world_kits.py's, the maps test_world_maps.py's."""

import pathlib
import re

import pytest

from db import Refusal
from facts import model, tables
from facts.model import Hero, Map
from facts.records import Rates, StyleScore


@pytest.mark.invariant
def test_every_data_table_is_read_by_the_load(world, rows):
    """Every data table is named in the load, the ledger aside, and read whole."""
    src = pathlib.Path(tables.__file__).read_text(encoding="utf-8")
    unread = [
        t for (t,) in rows("select tablename from pg_tables where schemaname='public'")
        if t != "schema_migrations" and not re.search(r"\b%s\b" % t, src)]
    assert unread == [], unread
    modifiers = sum(len(h.modifiers) for h in world.heroes.values())
    assert modifiers == rows("select count(*) from ability_modifiers")[0][0]
    # one population of rates, Blizzard's: no third party is read or named
    both = src + pathlib.Path(model.__file__).read_text(encoding="utf-8")
    assert "map_strategy" not in both and "counterpick" not in both


@pytest.mark.invariant
def test_names_resolve_across_spellings(world):
    assert world.hero("lucio").name == "Lúcio"
    assert world.hero("D.VA").name == "D.Va"
    assert world.map("kings row").name == "King's Row"
    with pytest.raises(Refusal, match="unknown heroes"):
        world.resolve(None, ["Goku"], [])
    with pytest.raises(Refusal, match="unknown map"):
        world.resolve("Atlantis", [], [])


def test_one_hero_cannot_hold_two_seats(synthetic_world):
    """A six with a hero twice is a five, and team_metrics would count it
    twice; a hero may play for both teams."""
    world = synthetic_world
    for red, blue, bans in ((["Anvil", "Anvil"], [], []), ([], ["Balm", "Balm"], []),
                            ([], [], ["Needle", "Needle"])):
        with pytest.raises(Refusal, match="same hero twice"):
            world.resolve("Harbor Gate", red, blue, bans)
    world.resolve("Harbor Gate", ["Anvil"], ["Anvil"], [])


def test_a_board_names_only_what_the_world_holds_and_may_pick(synthetic_world):
    """An unknown map, a banned pick and an announced hero are each refused
    by name; the announced hero only where the caller does not allow it."""
    world = synthetic_world
    assert world.hero("anvil").name == "Anvil" and world.map("HARBOR GATE").name == "Harbor Gate"
    assert world.hero("Nemo") is None and world.map("Atlantis") is None
    with pytest.raises(Refusal, match="unknown map: Atlantis"):
        world.resolve("Atlantis", [], [])
    with pytest.raises(Refusal, match="banned this match, cannot be picked: Balm"):
        world.resolve(None, [], ["Balm"], ["Balm"])
    with pytest.raises(Refusal, match=r"announced, not yet playable: Wisp \(releases 2026-12-01\)"):
        world.resolve(None, ["Wisp"], [])
    board = world.resolve("Harbor Gate", ["Wisp"], ["Anvil"], ["Needle"], allow_announced=True)
    assert [h.name for h in board.red] == ["Wisp"] and board.map.name == "Harbor Gate"
    assert [h.name for h in board.banned] == ["Needle"]


def test_the_models_lookups_and_derivations(synthetic_world):
    """The roster by role then name and the maps by name; a hero's rank spread
    and trend from its rates, its ultimate under the roster's cap; a map's top
    style and margin with no style, one, or a tie."""
    world = synthetic_world
    roster = [h.name for h in world.heroes_by_role()]
    assert roster[:5] == ["Anvil", "Kite", "Mortar", "Quarry", "Flint"] and roster[-1] == "Wisp"
    assert [m.name for m in world.maps_sorted()] == ["Ember Ruins", "Harbor Gate", "Salt Flats"]
    assert world.synergy(world.hero("Anvil").id, world.hero("Balm").id).score == 2
    assert world.is_countered_by(world.hero("Mortar").id, world.hero("Anvil").id)
    hero = Hero(id=99, name="Probe", role="damage", subrole="Flanker", win=51.0, prev_win=49.5,
                by_tier={"bronze": Rates(48.0, 5.0, 1.0), "gold": Rates(None, 5.0, 1.0),
                         "grandmaster": Rates(55.0, 5.0, 1.0)},
                ult_damage_raw=900.0)
    hero.derive_rates()
    assert (hero.rank_spread, hero.trend) == (7.0, 1.5)
    hero.cap_ult(600.0)
    assert hero.ult_damage == 600.0
    hero.cap_ult(0.0)                         # no cap on record: the raw figure
    assert hero.ult_damage == 900.0
    alone = Hero(id=98, name="Lone", role="tank", subrole="Stalwart", win=50.0)
    alone.derive_rates()
    assert (alone.rank_spread, alone.trend) == (0.0, None)
    m = Map(9, "Test Site", "Push")
    assert m.style_top is None and m.style_margin == 0
    m.styles = {"poke": StyleScore(1.5, None)}
    assert m.style_top == "poke" and m.style_margin == 1.5
    m.styles["brawl"] = StyleScore(1.5, None)          # a tie goes to the name
    assert m.style_top == "brawl" and m.style_margin == 0
