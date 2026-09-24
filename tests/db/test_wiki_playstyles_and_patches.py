"""Unit tests: the Team Composition page read into playstyles, and the
Patches cargo rows read into dated patches. No database, no network."""

import pytest

from db.data.wiki import WikiError
from db.data.wiki.patches import dated_patches
from db.data.wiki.playstyles import parse_playstyles

# --- playstyles: one heroes section per style ----------------------------

COMPOSITION = """
= Popular compositions =
Most teams settle on one style, such as [[Dive]].

== Dive ==
Dive wins on mobility, with heroes like [[Genji]].

=== Dive heroes ===
'''Tank:''' [[Winston]], [[D.Va|DVa]]
* note

== Brawl ==
Brawl fights close, behind [[Reinhardt]].

=== Brawl heroes ===
* '''Tank:''' [[Reinhardt]], [[Winston]]

=== Poke heroes ===
No list yet.

= References =
[[Tracer]]
"""


def test_a_playstyle_reads_only_its_own_heroes_section():
    # a heading of any level ends a section, so the prose above a heroes
    # heading and the references below it are not read; a piped link gives its
    # target, a hero sits under every style that lists it, and a heroes
    # section that links no one is no playstyle
    assert parse_playstyles(COMPOSITION) == [
        ("dive", "Dive", ["Winston", "D.Va"]),
        ("brawl", "Brawl", ["Reinhardt", "Winston"]),
    ]


def test_the_last_heroes_section_runs_to_the_end_of_the_page():
    assert parse_playstyles("=== Dive heroes ===\n[[Winston]]") == [
        ("dive", "Dive", ["Winston"])]


def test_a_page_with_no_heroes_section_is_refused():
    with pytest.raises(WikiError, match="Team Composition"):
        parse_playstyles("== Dive ==\n[[Winston]]\n")


# --- patches: the rows that name a patch and its date --------------------

def test_a_patch_without_a_name_or_a_date_is_skipped_and_counted():
    rows = [
        {"name": "April 1, 2020 Patch", "date": "2020-04-01",
         "platform": "PC Switch PS4 Xbox One",
         "source": "https://playoverwatch.com/en-us/news/patch-notes/pc"},
        {"name": "Undated Patch", "date": "", "platform": "PC", "source": ""},
        {"date": "2021-03-03", "platform": "PC", "source": ""},
        {"name": "Hotfix", "date": "2022-02-02", "platform": "", "source": ""},
    ]
    # an empty platform or source is stored as NULL
    assert dated_patches(rows) == ([
        ("April 1, 2020 Patch", "2020-04-01", "PC Switch PS4 Xbox One",
         "https://playoverwatch.com/en-us/news/patch-notes/pc"),
        ("Hotfix", "2022-02-02", None, None),
    ], 2)
