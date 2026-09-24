"""Map and stage terrain read off the wiki's map articles: the section filter
and a stage's own text, on inline wikitext. The lexicon is
test_wiki_terrain_lexicon.py's, the pull test_wiki_terrain_pull.py's."""

import pytest

from db.data.wiki import terrain

# --- the section filter --------------------------------------------------------

ARTICLE = """{{Infobox map
| name = Kingsbridge
| type = Hybrid
| terrain = Narrow cobblestone streets
}}
'''Kingsbridge''' is a [[Hybrid]] [[map]] with a choke in its lead.

==Official Description==
A rooftop in the lore.

==Background==
A tunnel in the lore.
===History===
A corridor in the lore.

==Known Locations==
*[[Gateway Hotel]]

==Gameplay==
{{stub-section}}
[[File:Kingsbridge.jpg|thumb|A balcony in a caption, by [[Someone]].]]
Each turn is played on one of the sections:
*Docks
*Market
Attackers leave through a [[Passage|narrow passage]].<ref>A pit in a citation.</ref>
=== The Castle Interior ===
The last fight is indoors.

== Strategy ==
=== <u>Defense</u> ===
''This section is currently blank. Please help by adding any strategies.''
*'''[[Mei]]:''' {{al|Ice Wall}}
*[[Mei]] can block the gateway with {{al|Ice Wall}}.
{| class="listtable"
! Hero !! Quote
|-
| Mei || A cliff in a table.
|}

==Trivia==
A courtyard in the trivia.
===Development===
A sightline in the development notes.
==== Season 13 rework ====
A flank route was added to the high ground.
=== Season 13 rework images ===
<gallery>
Rework.jpg|A plaza in a gallery.
</gallery>

==References==
"""


def test_the_article_splits_into_sections_under_their_heading_paths():
    paths = [path for path, _ in terrain.sections(ARTICLE)]
    assert paths[0] == ()
    assert ("Background", "History") in paths
    assert ("Gameplay", "The Castle Interior") in paths
    assert ("Strategy", "Defense") in paths          # <u> is stripped
    assert ("Trivia", "Development", "Season 13 rework") in paths
    assert ("Trivia", "Season 13 rework images") in paths


@pytest.mark.parametrize("path, kept", [
    ((), False),                                     # the lead: mode and date
    (("Gameplay",), True),
    (("Gameplay", "The Castle Interior"), True),
    (("Strategy", "Attack", "Assault"), True),
    (("Map layout and points of interest",), True),
    (("Tactics",), True),
    (("Environmental hazards",), True),
    (("Description",), True),
    (("Official Description",), False),
    (("Background",), False),
    (("Background", "History", "Uprising"), False),  # under a dropped heading
    (("Trivia",), False),
    (("Trivia", "Development"), False),
    (("Trivia", "Development", "Season 13 rework"), True),
    (("Development", "Season 7 design changes"), True),
    (("Gallery", "Season 13 rework images"), False),
    (("Known Locations",), False),
    (("Locations",), False),
    (("Known Residents",), False),
    (("Gameplay", "Stadium"), False),
    (("King's Row (Winter Wonderland)",), False),
    (("Media", "360° Panorama"), False),
    (("References",), False),
])
def test_sections_about_the_ground_are_kept_and_lore_is_dropped(path, kept):
    assert terrain.is_kept(path) is kept


def test_the_kept_text_is_the_terrain_line_the_headings_and_the_prose():
    text = terrain.terrain_text(ARTICLE)
    assert text.startswith("Narrow cobblestone streets")
    assert "Attackers leave through a narrow passage." in text
    assert "The Castle Interior" in text and "The last fight is indoors." in text
    assert "Mei can block the gateway with ." in text
    assert "A flank route was added to the high ground." in text
    for dropped in ("lead", "lore", "Gateway Hotel", "caption", "citation",
                    "Docks", "Market", "currently blank", "Ice Wall", "table",
                    "trivia", "development notes", "gallery", "Infobox", "Hybrid"):
        assert dropped not in text, dropped


def test_mentions_are_counted_over_the_kept_text_only():
    counts = terrain.count_features(terrain.terrain_text(ARTICLE))
    assert set(counts) == set(terrain.FEATURES)
    # narrow streets, narrow passage, gateway
    assert counts["chokes"] == 3
    # The Castle Interior (its heading), indoors
    assert counts["interiors"] == 2
    assert counts["high_ground"] == 1 and counts["flanks"] == 1
    assert counts["sightlines"] == counts["open_ground"] == 0
    assert counts["hazards"] == counts["cover"] == 0


def test_words_are_runs_of_letters():
    assert terrain.word_count("King's Row: 3 high-ground routes (A) - 12m.") == 6
    assert terrain.per_thousand(3, 150) == 20.0
    assert terrain.per_thousand(0, 0) == 0.0


# --- a stage's own text --------------------------------------------------------

CONTROL = """'''Thera''' is a [[Control]] map. The Well is in its lead.

==Background==
The Well was dug in the lore.

==Gameplay==
{{stub-section}}
Each turn is played on one of the three sections of the map:
*Lighthouse
** Lighthouse is a town on a cliff.
*Well
*Ruins

==Strategy==
On the Well section of the map, the big hole in the middle of the point kills.
{| class="listtable"
| Ruins || A pit in a table.
|}

The Ruins and the Lighthouse both have long sightlines.

* On Ruins, heroes can hide behind the pillars.
*'''[[Mei]]:''' {{al|Ice Wall}}

=== Ruins ===
==== Pathing ====
The back route is a corridor. The Well is not here.
"""

HYBRID = """
==Gameplay==
Kingsbridge is a Hybrid map which takes place in three main locations: The
Town, The Castle Grounds, and the Castle Interior.

=== The Town ===
Attackers push through a choke onto the point.

=== The Castle Grounds ===
A bridge with cliffs on either side.

=== The Castle Interior ===
The last fight is indoors.

== Strategy ==
The Escort phase is long. The Assault phase has high ground.

=== <u>Attack</u> ===
==== Assault ====
Take the rooftops.
==== Escort ====
=== <u>Defense</u> ===
==== Assault ====
Hold the gateway.
==== Escort  ====
Use the narrow streets.
"""


def test_a_section_splits_into_paragraphs_and_list_items():
    body = dict(terrain.sections(CONTROL))[("Strategy",)]
    assert terrain.section_paragraphs(body) == [
        "On the Well section of the map, the big hole in the middle of the point kills.",
        "The Ruins and the Lighthouse both have long sightlines.",
        "On Ruins, heroes can hide behind the pillars.",
    ]                                                # the table and the name item are dropped


def test_a_stages_text_is_its_sections_and_the_paragraphs_that_name_it_alone():
    texts = terrain.stage_texts(CONTROL, ["Lighthouse", "Well", "Ruins"])
    assert list(texts) == ["Lighthouse", "Well", "Ruins"]
    # the sub-bullet under the stage's own bullet names it
    assert texts["Lighthouse"] == "Lighthouse is a town on a cliff."
    # a paragraph that names one stage; not the lead, not the lore
    assert texts["Well"] == ("On the Well section of the map, the big hole in the"
                             " middle of the point kills.")
    # a list item that names it, then the section under its heading, whole -
    # the Well named inside it stays Ruins' text; the table is dropped
    assert texts["Ruins"] == ("On Ruins, heroes can hide behind the pillars. . Ruins"
                              " . Pathing . The back route is a corridor."
                              " The Well is not here.")
    # a paragraph that names two stages is neither's
    assert not any("sightlines" in text for text in texts.values())

    counts = {stage: terrain.count_features(text) for stage, text in texts.items()}
    assert counts["Well"]["hazards"] == 2            # the Well, the big hole
    assert counts["Lighthouse"]["hazards"] == 1      # a cliff
    # hide behind, the pillars; a corridor
    assert counts["Ruins"]["cover"] == 2 and counts["Ruins"]["chokes"] == 1


def test_a_stage_the_article_says_nothing_about_has_no_text():
    assert terrain.stage_texts("==Gameplay==\n*Docks\n*Market\n", ["Docks", "Market"]) == {
        "Docks": "", "Market": ""}
    assert terrain.stage_texts(CONTROL, []) == {}


def test_a_phases_text_is_every_section_of_its_name_and_its_stretches():
    texts = terrain.stage_texts(HYBRID, ["Assault", "Escort"], phases=True)
    # the first stretch is the capture point's; attack and defense count together
    assert texts["Assault"] == ("The Town . Attackers push through a choke onto the point."
                                " . Assault . Take the rooftops. . Assault . Hold the gateway.")
    # the rest of the route is the payload's; the empty Escort section adds its heading
    assert texts["Escort"] == ("The Castle Grounds . A bridge with cliffs on either side."
                               " . The Castle Interior . The last fight is indoors."
                               " . Escort . Escort . Use the narrow streets.")
    # a phase's name is a mode's: a paragraph that names it is not read
    assert "phase" not in texts["Assault"] + texts["Escort"]
    assert terrain.stage_texts("==Strategy==\nThe Escort is long and open.\n",
                               ["Assault", "Escort"], phases=True) == {
        "Assault": "", "Escort": ""}


def test_a_stage_needs_fewer_words_than_a_map():
    assert 0 < terrain.STAGE_MIN_WORDS < terrain.MIN_WORDS
