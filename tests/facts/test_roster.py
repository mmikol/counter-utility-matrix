"""The roster facts/roster.py builds once for the board's /api/roster and the
door's roster tool: its heroes in role order with every field both readers
take, its maps in name order with their mode, style and side. No database."""

from facts.roster import RosterHero, RosterMap, roster_of


def test_the_heroes_come_in_role_order_with_every_field_the_readers_take(synthetic_world):
    heroes = roster_of(synthetic_world)["heroes"]
    assert [h["name"] for h in heroes] == [h.name for h in synthetic_world.heroes_by_role()]
    assert all(h.keys() == RosterHero.__annotations__.keys() for h in heroes)
    assert all(h["pool"] > 0 for h in heroes)


def test_an_announced_hero_carries_its_release_day_as_text(synthetic_world):
    heroes = {h["name"]: h for h in roster_of(synthetic_world)["heroes"]}
    assert heroes["Wisp"]["status"] == "announced"
    assert heroes["Wisp"]["release_date"] == "2026-12-01"
    assert heroes["Balm"]["status"] == "released" and heroes["Balm"]["release_date"] is None


def test_the_maps_come_in_name_order_with_their_style_and_side(synthetic_world):
    maps = roster_of(synthetic_world)["maps"]
    assert [m["name"] for m in maps] == ["Ember Ruins", "Harbor Gate", "Salt Flats"]
    assert all(m.keys() == RosterMap.__annotations__.keys() for m in maps)
    sided = {m["name"]: m["sided"] for m in maps}
    assert sided == {"Harbor Gate": True, "Ember Ruins": False, "Salt Flats": False}
    world_maps = {m.name: m for m in synthetic_world.maps.values()}
    assert all(m["style"] == world_maps[m["name"]].style_top for m in maps)
    assert any(m["style"] for m in maps)          # or the style check proves nothing
    assert {m["name"]: m["mode"] for m in maps} == {
        "Ember Ruins": "Control", "Harbor Gate": "Hybrid", "Salt Flats": "Push"}
