"""The UI: every view renders from a real database, and the live board's
JSON endpoints speak the same dossier the /comp skill reads.

No HTTP server is spun up - the handler is thin routing, so the views and
endpoints are exercised as the functions they are, against the shared db
fixture."""

import json

import ui


def test_home_renders_counts_domains_and_the_playbook(db):
    body = ui.view_home(db)
    assert "heuristics" in body
    assert "PLAYBOOK" in body and "META" in body
    db.rollback()


def test_live_board_carries_the_whole_roster_and_maps(db):
    body = ui.view_live(db)
    heroes = [n for n, in db.execute("select name from heroes").fetchall()]
    for name in heroes:   # every hero appears on BOTH select screens
        assert body.count("data-h=\"%s\"" % ui.esc(name)) >= 2, name
    maps = [m for m, in db.execute("select name from maps").fetchall()]
    assert all("<option>%s</option>" % ui.esc(m) in body for m in maps)
    # the three interaction pieces the page is for
    assert "toggle(" in body and "localStorage" in body and "/api/dossier" in body
    assert "board enemy" in body and "board mine" in body
    db.rollback()


def test_api_dossier_returns_the_lines_the_skill_reads(db):
    body, code = ui.api_dossier(db, {"map": ["King's Row"],
                                     "enemy": ["Zarya", "Pharah"],
                                     "ally": ["Ana"]})
    assert code == 200
    data = json.loads(body)
    assert data["map"] == "King's Row"
    tables = {l["table"] for l in data["lines"]}
    assert "derived:shape" in tables and "derived:coverage" in tables
    db.rollback()


def test_api_dossier_refuses_an_invented_hero(db):
    body, code = ui.api_dossier(db, {"enemy": ["Saitama"]})
    assert code == 400 and "Saitama" in json.loads(body)["error"]
    db.rollback()


def test_api_recs_reports_the_newest_recording(db):
    body, code = ui.api_recs(db)
    assert code == 200
    data = json.loads(body)
    assert isinstance(data["latest"], int)
    if data["latest"]:
        assert data["summary"]
    db.rollback()
