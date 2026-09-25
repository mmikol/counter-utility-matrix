"""The 6v6 kit a hero article states, db/data/wiki/kits/six_a_side.py: the
infobox's 6v6 pools and each Ability_details block's 6v6_details lines,
read off fixture wikitext, a malformed value rejected and named, and each
line's stat named from its piece's own rows. No database, no network."""

from db.data.wiki.kits.six_a_side import SixLine, parse_six_a_side, with_stats

ARTICLE = """{{Infobox character
| name = Anvil
| health = 250
| armor = 300
| health6v6 = 325
| armor6v6 = 225
| shield6v6 =
}}
{{Ability_details
| ability_name = Barrier Field
| barrier_health = 1500
| 6v6_details = * Shield health increased from 1500 to 1800.
* No longer shares a cooldown with {{al|Charge}}.
}}
{{Ability_details
| ability_name = Adrenaline Rush
| 6v6_details = * Self-healing from wounds damage scalar reduced from 2.5x to 1.75x.<!--a note-->
* Damage amplification reduced from 30% to 25%.
}}
{{Ability_details
| ability_name = Charge
| 6v6_details = * Cooldown increased from 7 to 10 seconds
}}
"""


def test_the_article_gives_its_6v6_pools_and_lines_in_its_own_words():
    """The two pools the infobox fills are read and the empty one is absent;
    a figure line carries its stat's words, from and to, a multiplier held
    as the kit holds it, a percent; a line with no figure is its words."""
    six = parse_six_a_side(ARTICLE)
    assert six.pools == {"health": 325, "armor": 225}
    assert six.rejected == []
    assert six.lines == [
        SixLine("Barrier Field", "barrier_health", 1500.0, 1800.0,
                "Shield health increased from 1500 to 1800"),
        SixLine("Barrier Field", None, None, None, "No longer shares a cooldown with Charge"),
        SixLine("Adrenaline Rush", "heal", 250.0, 175.0,
                "Self-healing from wounds damage scalar reduced from 2.5x to 1.75x"),
        SixLine("Adrenaline Rush", "damage_amp", 30.0, 25.0,
                "Damage amplification reduced from 30% to 25%"),
        SixLine("Charge", "cooldown", 7.0, 10.0, "Cooldown increased from 7 to 10 seconds")]


def test_a_malformed_6v6_value_is_rejected_and_named():
    """A pool that is not a whole number and a from-to line whose figures do
    not parse are rejected, never read as a number; the rest still reads."""
    article = ARTICLE.replace("| shield6v6 =", "| shield6v6 = see the perks").replace(
        "Cooldown increased from 7 to 10 seconds", "Cooldown increased from seven to ten seconds")
    six = parse_six_a_side(article)
    assert six.rejected == [
        "shield6v6: see the perks",
        "Charge 6v6_details: Cooldown increased from seven to ten seconds"]
    assert "shield" not in six.pools
    assert [line.piece for line in six.lines if line.piece == "Charge"] == []
    assert len(six.lines) == 4


def test_an_article_without_6v6_fields_states_no_6v6_kit():
    six = parse_six_a_side("{{Infobox character\n| health = 200\n}}\nNo kit here.")
    assert (six.pools, six.lines, six.rejected) == ({}, [], [])


def test_a_lines_stat_is_the_one_its_piece_holds_with_the_from_figure():
    """"Health reduced from 225 to 200" names a barrier's health: the stat
    is barrier_health on a piece that stores that row, health on one that
    stores health, and the first code the words name on a piece with
    neither."""
    said = parse_six_a_side("""{{Ability_details
| ability_name = Particle Barrier
| 6v6_details = * Health reduced from 225 to 200.
}}
{{Ability_details
| ability_name = Projected Barrier
| 6v6_details = * Health reduced from 225 to 200.
}}
{{Ability_details
| ability_name = Graviton Surge
| 6v6_details = * Health reduced from 225 to 200.
}}
""")
    named = with_stats(said, {"particle barrier": {"barrier_health": "225", "cooldown": "12"},
                              "projected barrier": {"health": "225", "radius": "1.5 meters"}})
    assert [(line.piece, line.stat) for line in named.lines] == [
        ("Particle Barrier", "barrier_health"), ("Projected Barrier", "health"),
        ("Graviton Surge", "barrier_health")]
