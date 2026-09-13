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
from data.proprietary.load.user.heuristics import (
    CATALOG_PATH, PARAMS_PATH, HeuristicError,
    read_catalog as read_heuristics, read_params)
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


# --- heuristics (the playbook's tunable brain) ---------------------------

def test_heuristics_reject_a_gapped_numbering(tmp_path):
    with pytest.raises(HeuristicError, match="1..2 with no gaps"):
        read_heuristics(write(tmp_path,
            "id,tag,name,category,formula,inputs,status,rationale\n"
            "1,derived:x,a,cat,f,i,live,r\n3,derived:y,b,cat,f,i,ready,r\n"))


def test_heuristics_reject_an_invented_status(tmp_path):
    # live/ready/blocked is the whole honesty vocabulary
    with pytest.raises(HeuristicError, match="status"):
        read_heuristics(write(tmp_path,
            "id,tag,name,category,formula,inputs,status,rationale\n"
            "1,derived:x,a,cat,f,i,someday,r\n"))


def test_heuristics_reject_a_duplicate_name(tmp_path):
    with pytest.raises(HeuristicError, match="duplicate name"):
        read_heuristics(write(tmp_path,
            "id,tag,name,category,formula,inputs,status,rationale\n"
            "1,derived:x,a,cat,f,i,live,r\n2,derived:y,A,cat,f,i,live,r\n"))


def test_heuristic_params_reject_a_wordy_value(tmp_path):
    # a dial the dossier cannot multiply by is not a dial
    with pytest.raises(HeuristicError, match="not numeric"):
        read_params(write(tmp_path, "code,value,note\nHEAL_MARGIN,plenty,x\n"))


def test_the_shipped_catalog_is_exactly_one_hundred():
    rows = read_heuristics(CATALOG_PATH)
    assert len(rows) == 100
    assert [r[0] for r in rows] == list(range(1, 101))


def test_every_dossier_default_has_a_shipped_dial():
    # the params file must cover every constant dossier.py falls back on,
    # or "tunable" would be true for some dials and silently false for others
    codes = {code for code, _, _ in read_params(PARAMS_PATH)}
    from data.proprietary import dossier
    defaults = {"COVERAGE_MIN", "SPECIALIST_DELTA", "SLEEPER_WIN",
                "SLEEPER_PICK", "PAIRING_LIMIT", "NET_LIMIT",
                "TREND_POINTS", "HEAL_MARGIN"}
    assert defaults <= codes
    for name in defaults:
        assert hasattr(dossier, name), name
