"""The terrain lexicon: each feature's pattern on inline text, the terrain
sense matched and the wrong senses not, and the fixed set of features."""

import pytest

from db.data.wiki import terrain

FEATURES = {"chokes", "interiors", "high_ground", "flanks", "sightlines",
            "open_ground", "hazards", "cover"}


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
