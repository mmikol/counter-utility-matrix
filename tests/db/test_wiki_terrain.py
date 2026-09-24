"""Map and stage terrain read off the wiki's map articles. The section filter,
a stage's own text and each feature's pattern on inline text, wrong senses
included; then run() over the wiki page cache inside a transaction that is
rolled back, skipped without the cache or the database."""

import os

import pytest

from db import CACHE_DIRS
from db.data.wiki import maps, terrain

needs_cache = pytest.mark.skipif(
    not os.path.isdir(CACHE_DIRS["wiki"]), reason="the wiki page cache is not on this machine")

FEATURES = {"chokes", "interiors", "high_ground", "flanks", "sightlines",
            "open_ground", "hazards", "cover"}


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
    assert set(counts) == FEATURES
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


# --- the lexicon: the terrain sense, and the wrong senses --------------------------

def matches(feature, text):
    return [m.group(0).lower() for m in terrain.FEATURES[feature].finditer(text)]


@pytest.mark.parametrize("feature, text, found", [
    ("chokes", "Mei walls off the first chokepoint and the choke point after it.",
     ["chokepoint", "choke point"]),
    ("chokes", "Narrow cobblestone streets end in a tight corridor and a tunnel.",
     ["narrow cobblestone streets", "tight corridor", "tunnel"]),
    ("chokes", "Through the gateway, the doorway and a low archway: a bottleneck.",
     ["gateway", "doorway", "archway", "bottleneck"]),
    # a street is no choke unless it is narrow; a name is not terrain
    ("chokes", "New Queen Street is a Push map. Tanks choked on the long street.", []),

    ("interiors", "The bunker is an indoor location with an enclosed room.",
     ["indoor", "enclosed", "room"]),
    ("interiors", "Building interiors, closer quarters, an underground cavern.",
     ["interiors", "closer quarters", "underground", "cavern"]),
    ("interiors", "The payload is moved into the large building; fight inside a volcano.",
     ["into the large building", "inside a volcano"]),
    # a spawn room is not fought in; a building named as a landmark is no interior
    ("interiors", "Exit the spawn room. Snipers stand on the building to your right.", []),

    ("high_ground", "Take the high ground: rooftops, a balcony, the ledges.",
     ["high ground", "rooftops", "balcony", "ledges"]),
    ("high_ground", "A highground overlooking the second floor, up the staircase.",
     ["highground", "overlooking", "second floor", "staircase"]),
    ("high_ground", "The map is very vertical, a steep incline, an uphill push.",
     ["vertical", "incline", "uphill"]),
    # "second area" is a stage of the route; a high price is no high ground
    ("high_ground", "In the second area the defenders pay a high price on the ground.", []),

    ("flanks", "A flank route for flankers; the side door and the back route.",
     ["flank", "flankers", "side door", "back route"]),
    ("flanks", "Several routes lead in; sneak around by the alternate path.",
     ["several routes", "sneak around", "alternate path"]),
    # the backline is a part of the team, a side is not a side path
    ("flanks", "Keep a strong backline on the left side of the point.", []),

    ("sightlines", "Long sightlines, long sight lines and a line of sight for snipers.",
     ["sightlines", "sight lines", "line of sight", "snipers"]),
    ("sightlines", "A very long open street; long-range heroes hold it from afar.",
     ["long open street", "long-range", "from afar"]),
    # long in time is not long in view; a street's name is no sightline
    ("sightlines", "The fight on New Queen Street takes a long time; stay in sight.", []),

    ("open_ground", "A large open area, a plaza and a courtyard, wide open.",
     ["large open area", "plaza", "courtyard", "wide open"]),
    ("open_ground", "Long open stretches with minimal cover; there isn't much cover.",
     ["open stretches", "minimal cover", "isn't much cover"]),
    # "open" the verb
    ("open_ground", "The path opens up into stairs; Sombra can open the door; "
                    "entrances were opened to provide more angles.", []),

    ("hazards", "The big hole in the middle of the Well: escape from the well.",
     ["big hole", "the well", "the well"]),
    ("hazards", "Environmental kills by knockback; push enemies off the point.",
     ["environmental kills", "knockback", "push enemies off"]),
    ("hazards", "Deadly pitfalls, a lava moat, the cliff and a steep drop.",
     ["pitfalls", "lava", "moat", "cliff", "steep drop"]),
    # "drop" and "push" with a payload, "well" the adverb, a hole in a wall
    ("hazards", "Drop the payload as well as you can; push the payload along into "
                "the park. Symmetra is utilized well. Holes in various assets "
                "were blocked. A well-known spot.", []),

    ("cover", "Buildings provide cover; take cover behind the wall or a pillar.",
     ["cover", "cover", "behind the wall", "pillar"]),
    ("cover", "Cover was added after the first turn; Mercy can hide behind the rock.",
     ["cover", "hide behind"]),
    # "cover" the verb; cover said to be missing is open ground's
    ("cover", "His turret can cover a lot of ground and Reaper will cover the choke."
              " There is no cover, minimal cover, and fewer places to take cover.", []),
])
def test_a_pattern_matches_the_terrain_sense_only(feature, text, found):
    assert matches(feature, text) == found


def test_the_lexicon_is_the_fixed_set_of_features():
    assert set(terrain.FEATURES) == FEATURES


# --- the page cache -> the table -----------------------------------------------

def terrain_of(connection, name):
    return {feature: (mentions, per_thousand) for feature, mentions, per_thousand
            in connection.execute(
                "select t.feature, t.mentions, t.per_thousand from map_terrain t"
                " join maps m using (map_id) where m.name = %s", (name,))}


@needs_cache
@pytest.mark.invariant
def test_terrain_pulls_from_the_cache(sandbox):
    data = terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select t.map_id, t.feature, t.mentions, t.per_thousand, src.code"
        " from map_terrain t join sources src using (source_id)").fetchall()
    total = sandbox.execute("select count(*) from maps").fetchone()[0]

    assert set(data) == {"maps", "without_text", "missing", "rows", "words", "stages",
                         "stages_no_text", "stage_rows", "tables"}
    assert data["missing"] == []                  # every article fetched from the cache
    assert data["tables"] == ["map_terrain", "stage_terrain"]
    assert data["rows"] == len(rows) == data["maps"] * len(FEATURES)
    assert data["maps"] + len(data["without_text"]) == total
    # most maps' articles describe their ground; the thin ones are named
    assert data["maps"] > total / 2
    assert data["words"] >= data["maps"] * terrain.MIN_WORDS

    assert {code for *_, code in rows} == {"wiki"}
    assert {feature for _, feature, *_ in rows} == FEATURES
    assert all(mentions >= 0 and per_thousand >= 0
               for _, _, mentions, per_thousand, _ in rows)
    assert all((mentions == 0) == (per_thousand == 0)
               for _, _, mentions, per_thousand, _ in rows)
    by_map = {}
    for map_id, feature, *_ in rows:
        by_map.setdefault(map_id, set()).add(feature)
    assert all(features == FEATURES for features in by_map.values())


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_the_well_known_ground(sandbox):
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)

    # King's Row: narrow streets, the first chokepoint, the gateway
    kings_row = terrain_of(sandbox, "King's Row")
    assert kings_row["chokes"][0] >= 3
    assert max(kings_row, key=lambda f: kings_row[f][1]) == "chokes"
    # Ilios: the hole in the middle of the Well
    ilios = terrain_of(sandbox, "Ilios")
    assert ilios["hazards"][0] >= 2
    assert max(ilios, key=lambda f: ilios[f][1]) == "hazards"
    # Lijiang Tower: environmental kills on the bridges
    assert terrain_of(sandbox, "Lijiang Tower")["hazards"][0] >= 2
    # Havana: "the massive sightlines", "long open stretches"
    havana = terrain_of(sandbox, "Havana")
    assert havana["sightlines"][0] >= 3 and havana["open_ground"][0] >= 2
    # Eichenwalde: "the multitude of chokepoints", the castle interior
    eichenwalde = terrain_of(sandbox, "Eichenwalde")
    assert eichenwalde["chokes"][0] >= 2 and eichenwalde["interiors"][0] >= 2


def stage_terrain_of(connection, map_name, stage):
    return {feature: (mentions, per_thousand) for feature, mentions, per_thousand
            in connection.execute(
                "select t.feature, t.mentions, t.per_thousand from stage_terrain t"
                " join map_stages s using (stage_id) join maps m using (map_id)"
                " where m.name = %s and s.name = %s", (map_name, stage))}


@needs_cache
@pytest.mark.invariant
def test_stage_terrain_pulls_from_the_cache(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    data = terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select t.stage_id, t.feature, t.mentions, t.per_thousand, src.code"
        " from stage_terrain t join sources src using (source_id)").fetchall()
    total = sandbox.execute("select count(*) from map_stages").fetchone()[0]

    assert data["stage_rows"] == len(rows) == data["stages"] * len(FEATURES)
    assert data["stages"] + data["stages_no_text"] == total
    # most stages are a name in a list; the wiki writes about some
    assert 20 <= data["stages"] < total

    assert {code for *_, code in rows} == {"wiki"}
    assert all(mentions >= 0 and (mentions == 0) == (per_thousand == 0)
               for _, _, mentions, per_thousand, _ in rows)
    by_stage = {}
    for stage_id, feature, *_ in rows:
        by_stage.setdefault(stage_id, set()).add(feature)
    assert all(features == FEATURES for features in by_stage.values())

    # a stage's mentions are text of its own map's article: never more than the
    # article holds, when the map's terrain is stored
    assert sandbox.execute(
        "select count(*) from stage_terrain t join map_stages s using (stage_id)"
        " join map_terrain m on m.map_id = s.map_id and m.feature = t.feature"
        " where t.mentions > m.mentions").fetchone()[0] == 0
    # no Push map holds a stage, so none holds stage terrain
    assert sandbox.execute(
        "select count(*) from stage_terrain t join map_stages s using (stage_id)"
        " join map_modes mm using (map_id) join game_modes g using (mode_id)"
        " where g.code = 'push'").fetchone()[0] == 0
    # the articles that name their route describe every stretch of it
    assert dict(sandbox.execute(
        "select m.name, count(distinct t.stage_id) from stage_terrain t"
        " join map_stages s using (stage_id) join maps m using (map_id)"
        " join map_modes mm using (map_id) join game_modes g using (mode_id)"
        " where g.code = 'escort' group by m.name").fetchall()) == {
        "Circuit Royal": 3, "Havana": 3, "Rialto": 3, "Route 66": 3}


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_a_stages_ground(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)

    # Ilios: "On the Well section of the map, the big hole in the middle"
    well = stage_terrain_of(sandbox, "Ilios", "Well")
    assert well["hazards"][0] == 2
    assert [f for f in well if well[f][0]] == ["hazards"]
    # the article says nothing of the other two
    assert stage_terrain_of(sandbox, "Ilios", "Lighthouse") == {}
    assert stage_terrain_of(sandbox, "Ilios", "Ruins") == {}
    # Samoa: "environmental kills on Volcano, as there is a lava moat"
    assert stage_terrain_of(sandbox, "Samoa", "Volcano")["hazards"][0] == 3
    # Lijiang Tower: Garden's bridges and knockback kills, its back route
    garden = stage_terrain_of(sandbox, "Lijiang Tower", "Garden")
    assert garden["hazards"][0] >= 3 and garden["flanks"][0] >= 2
    # Havana: the Distillery is "an enclosed building"; the Sea Fort's straight
    # has "very minimal cover" and "an environmental hazard"
    assert stage_terrain_of(sandbox, "Havana", "Distillery")["interiors"][0] >= 2
    assert stage_terrain_of(sandbox, "Havana", "City Streets")["interiors"][0] == 0
    sea_fort = stage_terrain_of(sandbox, "Havana", "Sea Fort")
    assert sea_fort["open_ground"][0] >= 1 and sea_fort["hazards"][0] >= 1
    # King's Row: defenders hold "the first chokepoint"; the payload runs
    # "the narrow streets"
    assert stage_terrain_of(sandbox, "King's Row", "Assault")["chokes"][0] >= 2
    assert stage_terrain_of(sandbox, "King's Row", "Escort")["chokes"][0] >= 2
    # Eichenwalde: The Town's "multitude of chokepoints" is the capture point's;
    # the bridge's "environmental hazards" and the castle are the payload's
    town = stage_terrain_of(sandbox, "Eichenwalde", "Assault")
    castle = stage_terrain_of(sandbox, "Eichenwalde", "Escort")
    assert town["chokes"][0] >= 2 and town["hazards"][0] == 0
    assert castle["hazards"][0] >= 1 and castle["interiors"][0] >= 2
    # Hollywood's Attack and Defense sections are not split by phase
    assert stage_terrain_of(sandbox, "Hollywood", "Assault") == {}


@needs_cache
@pytest.mark.invariant
def test_the_pull_replaces_the_tables_whole(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    counts = "select (select count(*) from map_terrain), (select count(*) from stage_terrain)"
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    first = sandbox.execute(counts).fetchone()
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    assert sandbox.execute(counts).fetchone() == first and all(first)


@needs_cache
@pytest.mark.invariant
def test_pulling_the_maps_again_keeps_the_stages_and_their_terrain(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    before = sandbox.execute(
        "select s.stage_id, s.map_id, s.position, s.name, count(t.feature)"
        " from map_stages s left join stage_terrain t using (stage_id)"
        " group by s.stage_id order by s.stage_id").fetchall()
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    assert sandbox.execute(
        "select s.stage_id, s.map_id, s.position, s.name, count(t.feature)"
        " from map_stages s left join stage_terrain t using (stage_id)"
        " group by s.stage_id order by s.stage_id").fetchall() == before
