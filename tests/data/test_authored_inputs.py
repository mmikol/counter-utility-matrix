"""Unit tests: the validators guarding the hand-authored CSVs.

Authored input is fixed at the source, never silently repaired - so every
rejection here must be loud, name the line, and leave nothing half-loaded."""

import pytest

from data.proprietary.load.user.archetypes import ArchetypeError
from data.proprietary.load.user.archetypes import read_rows as read_archetypes
from data.proprietary.load.user.map_playstyle import MapPlaystyleError
from data.proprietary.load.user.map_playstyle import read_rows as read_map_playstyle
from data.proprietary.load.user.seasons import SeasonError
from data.proprietary.load.user.seasons import read_rows as read_seasons
from data.proprietary.load.user.synergies import SynergyError
from data.proprietary.load.user.synergies import read_rows as read_synergies


def write(tmp_path, text):
    path = tmp_path / "input.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


# --- synergies -----------------------------------------------------------

def test_synergies_happy_path_keeps_order_score_and_note(tmp_path):
    rows = read_synergies(write(tmp_path,
        "hero,other,score,note\nAna,Winston,2,nano dive\nMei,Tracer,,\n"))
    assert rows == [("Ana", "Winston", 2, "nano dive"),
                    ("Mei", "Tracer", None, None)]


def test_synergies_reject_a_reversed_duplicate(tmp_path):
    # bidirectional: (a, b) and (b, a) are the same claim
    with pytest.raises(SynergyError, match="duplicate pair"):
        read_synergies(write(tmp_path,
            "hero,other,score,note\nAna,Winston,2,\nWinston,Ana,1,\n"))


def test_synergies_reject_a_self_pair(tmp_path):
    with pytest.raises(SynergyError, match="paired with itself"):
        read_synergies(write(tmp_path, "hero,other,score,note\nMei,mei,1,\n"))


def test_synergies_reject_a_wrong_header(tmp_path):
    with pytest.raises(SynergyError, match="header"):
        read_synergies(write(tmp_path, "a,b,c\nAna,Winston,2\n"))


# --- archetypes ----------------------------------------------------------

def test_archetypes_lowercase_and_reject_duplicates(tmp_path):
    rows = read_archetypes(write(tmp_path,
        "style,role,slots,note\nDive,Tank,1,engage\n"))
    assert rows == [("dive", "tank", 1, "engage")]
    with pytest.raises(ArchetypeError, match="duplicate"):
        read_archetypes(write(tmp_path,
            "style,role,slots,note\ndive,tank,1,\nDIVE,TANK,2,\n"))


# --- map playstyle -------------------------------------------------------

def test_map_playstyle_rejects_duplicate_map_style(tmp_path):
    with pytest.raises(MapPlaystyleError, match="duplicate"):
        read_map_playstyle(write(tmp_path,
            "map,style,score,note\nIlios,dive,2,\nilios,Dive,1,\n"))


def test_map_playstyle_empty_score_is_null_not_zero(tmp_path):
    [(_, _, score, _)] = read_map_playstyle(write(tmp_path,
        "map,style,score,note\nIlios,dive,,open ledges\n"))
    assert score is None


# --- seasons -------------------------------------------------------------

def test_seasons_parse_iso_dates(tmp_path):
    [(name, started, note)] = read_seasons(write(tmp_path,
        "name,started,note\nSeason 1,2022-10-04,launch\n"))
    assert (name, str(started), note) == ("Season 1", "2022-10-04", "launch")


def test_seasons_reject_a_sloppy_date(tmp_path):
    with pytest.raises(SeasonError, match="YYYY-MM-DD"):
        read_seasons(write(tmp_path, "name,started,note\nSeason 1,Oct 4 2022,\n"))


def test_seasons_reject_duplicate_names(tmp_path):
    with pytest.raises(SeasonError, match="duplicate"):
        read_seasons(write(tmp_path,
            "name,started,note\nSeason 1,2022-10-04,\nseason 1,2022-12-06,\n"))
