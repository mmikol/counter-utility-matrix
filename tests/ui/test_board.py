"""The board: every JSON endpoint speaks the same facts and inference the
MCP tools serve, and the page carries the two rosters. No HTTP server is
spun up - the handler is thin routing."""

import json

import pytest

from ui import board

pytestmark = pytest.mark.invariant


def test_board_page_has_two_rosters_and_the_three_panels():
    body = board.view_board()
    assert "team red" in body and "team blue" in body
    assert "tab-comps" in body and "tab-facts" in body and "tab-playbook" in body
    assert "recorded" not in body
    assert "record this comp" not in board.static_file("board.js")[0].decode()
    assert "FACTS = HEROES" not in body                              # the equation moved to /math
    assert "href='/math'" in body and "id='captured'" in body
    # the status and the vintage sit in a footer
    foot = body[body.index("<footer class='foot'>"):body.index("</footer>")]
    assert "id='status'" in foot
    assert "id='captured'" in foot
    assert body.index("</footer>") > body.index("id='tab-playbook'")
    assert "id='flash'" in body[:body.index("</header>")]
    assert "data-tab='comps'" in body
    # the two old panels were merged into comps: both seats side by side, the
    # current comp below, in one section
    assert "tab-inf" not in body and "tab-cur" not in body
    assert "data-tab='inf'" not in body and "data-tab='cur'" not in body
    comps = body[body.index("id='tab-comps'"):body.index("id='tab-facts'")]
    assert "id='inf-blue'" in comps and "id='inf-red'" in comps
    script = board.static_file("board.js")[0].decode()
    assert "/api/roster" in script and "/api/facts" in script and "/api/infer" in script
    assert "localStorage" in script
    assert "var TABS = ['comps', 'facts', 'playbook']" in script
    assert "normalized" in script and "/ 100" in script    # the 0-100 figure, and only it
    assert "' of the best '" not in script and "(score " not in script   # no raw sum anywhere
    assert "d.unscored || UNSCORED" in script                # the engine's reason
    # the playbook holds three kinds; the badge appends the form only when it differs
    # the equation lives on /math now
    assert "STRATEGIES     = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS" in board.view_math()
    assert "h.form !== h.kind ?" in script
    assert "'assumption' ? 'assumption - taken as given" in script
    assert "prose -" not in script
    assert b".kind.assumption" in board.static_file("board.css")[0]


def test_the_ban_picker_is_a_roster_and_the_dropdown_is_gone():
    body = board.view_board()
    assert "bansel" not in body and "<select id='bansel'" not in body
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    script = board.static_file("board.js")[0].decode()
    assert "function buildBanPicker" in script and "rosterHTML('ban')" in script
    assert "bansOpen = false" in script                     # collapsed by default
    css = board.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css
    assert ".bans select" not in css


def test_an_announced_hero_is_a_coming_soon_tile_in_its_role_column():
    script = board.static_file("board.js")[0].decode()
    # no constant: the roster carries the status
    assert "DOCTRINE" not in script and "announcedTile" not in script
    assert "if (h.status === 'announced') return soonTile(h);" in script
    card = script[script.index("function soonTile"):script.index("function rosterHTML")]
    assert "class='tile soon'" in card and "data-h" not in card and "data-team" not in card
    assert "coming soon" in card and "SILHOUETTE" in card and "releases" in card
    assert 'var SILHOUETTE = "<svg' in script and ">announced</h4>" not in script
    css = board.static_file("board.css")[0].decode()
    assert ".tile.soon" in css and ".rolecol.announced" not in css


def test_roster_endpoint_carries_portraits_and_maps(db):
    data = board.api_roster(db)
    assert {h["role"] for h in data["heroes"]} == {"tank", "damage", "support"}
    assert all(h["status"] in ("released", "announced") for h in data["heroes"])
    assert all(h["portrait"] for h in data["heroes"] if h["status"] == "released")
    assert any(m["name"] == "King's Row" for m in data["maps"])
    for h in data["heroes"]:                          # an announced hero rides in its role, dated
        if h["status"] == "announced":
            assert h["role"] in ("tank", "damage", "support") and "release_date" in h
    db.rollback()


def test_facts_endpoint_returns_the_board(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya", "Pharah"],
                                   "blue": ["Ana"]})
    assert code == 200 and data["count"] > 300
    keys = {f["key"] for f in data["facts"]}
    assert "team.coverage" in keys and "matchup.net_edges" in keys
    data, code = board.api_facts(db, {"red": ["Saitama"]})
    assert code == 400 and "Saitama" in data["error"]
    db.rollback()


def test_infer_endpoint_serves_both_seats_and_the_current_comp(db):
    data, code = board.api_infer(db, {"map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"],
                                      "side": ["attack"]})
    assert code == 200 and data["side"] == "attack"
    assert data["blue"]["kind"] == "infer" and len(data["blue"]["blue"]) == 6
    assert data["red"]["seat"] == "red" and data["red"]["side"] == "defense"
    assert data["current"]["partial"] and data["current"]["blue"] == ["Ana"]
    assert data["blue"]["cited"] and all(p["evidence"] for p in data["blue"]["picks"])
    data, code = board.api_infer(db, {"blue": ["Reinhardt", "Zarya", "Widowmaker", "Bastion",
                                               "Ana", "Lúcio"]})
    assert code == 200 and data["current"]["kind"] == "evaluate" and data["current"]["rank"] >= 1
    db.rollback()


def test_strategies_endpoint():
    data = board.api_strategies()
    assert len(data["strategies"]) >= 30
    assert json.dumps(data)
    assert not hasattr(board, "api_recs") and not hasattr(board, "api_record")   # recording is gone


def test_bans_ride_the_query_string(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya"],
                                      "ban": ["Widowmaker", "Sombra"]})
    assert code == 200 and data["bans"] == ["Widowmaker", "Sombra"]
    assert any(f["scope"] == "bans" for f in data["facts"])
    data, code = board.api_infer(db, {"red": ["Zarya"], "blue": ["Ana"], "ban": ["Ana"]})
    assert code == 400 and "banned" in data["error"]
    data = board.api_roster(db)
    assert any(m["name"] == "King's Row" and m["sided"] for m in data["maps"])
    assert any(m["name"] == "Ilios" and not m["sided"] for m in data["maps"])
    db.rollback()


def test_the_page_is_a_shell_over_static_files():
    body = board.view_board()
    assert "/static/board.css" in body and "/static/board.js" in body
    assert "id='momentum'" in body and "id='plan'" in body
    # scores live in the boxes
    assert "id='bluescore'" in body
    assert "id='redscore'" in body
    assert "id='cur'" not in body
    assert "data-clear='red'" in body and "data-clear='blue'" in body
    # the momentum strip sits above both boxes
    assert body.index("id='momentum'") < body.index("id='blueslots'")
    assert "id='momentum'" not in body[body.index("id='tab-comps'"):]
    # blue on the left, red on the right, like the boxes
    assert body.index("id='inf-blue'") < body.index("id='inf-red'")
    assert body.index("id='blueslots'") < body.index("id='redslots'")
    script = board.static_file("board.js")[0].decode()
    assert "their comp as revealed" in script and "red_current" in script and "d.momentum" in script
    # blue's seat is the optimal six only
    assert "'blue - your picks'" not in script
    assert "function meaning(d)" in script and "100 is the best six the solver can build" in script
    assert "game plan" in script and "d.plan" in script
    assert "paintSuggestions" in script and "slot suggested" in script and "bluescore" in script
    assert "leadReason" not in script and "class='sug'" not in script   # the hero alone
    # the playbook's shape limits hold on the roster: a capped role dims and refuses
    assert "function roleCap" in script and "' capped'" in script and "d.shapes" in script
    assert "the playbook allows at most" in script
    # a heuristic's weight is a slider under its card; the setting rides with each request
    assert "function weightRow" in script and "type='range' min='1' max='10' step='0.01'" in script
    assert "type='number' class='wval' min='1' max='10' step='0.01'" in script
    assert "q.push('weight=' + " in script and "st.weights" in script
    assert "function setWeight" in script
    assert "h.form === 'heuristic' ? weightRow(h)" in script     # only heuristics have weights
    assert "function storeWeight" in script and "fetch('/api/weight', { method: 'POST'" in script
    assert "d.playbook || 'inference/strategies'" in script       # the card names its folder
    # a playbook that scores nothing reads unscored, never 100 / 100
    assert "d.scoring === false" in script and "'unscored'" in script and "var UNSCORED" in script
    assert ".tile.capped" in board.static_file("board.css")[0].decode()
    # swap sides and new game are gone
    assert "swapbtn" not in script and "clearbtn" not in script
    assert "el('clearall').onclick" in script                # clear all takes new game's place
    assert "swapbtn" not in board.view_board() and "clearbtn" not in board.view_board()
    assert "id='clearall'" in board.view_board()
    header = board.view_board().split("</header>")[0]
    # the two pills, pinned top-right
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links
    assert board.REPO_URL in links
    assert links.rstrip().endswith("GitHub</a></span>")
    # a team's clear button empties that team only
    assert "near('[data-clear]')" in script
    suggestions = script[script.index("function paintSuggestions"):
                         script.index("function renderResult")]
    assert "redscore" in script and "el('redslots')" not in suggestions
    assert "renderFill" not in script and "el('cur')" not in script
    assert "var TEAM = 6, BANS = 5;" in body
    data, ctype = board.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function renderResult" in data
    data, ctype = board.static_file("board.css")
    assert ctype.startswith("text/css") and b".tile.banned" in data
    assert board.static_file("../board.py") is None and board.static_file("nope.js") is None


def test_the_math_page_states_the_equation_and_the_layers():
    page = board.view_math()
    for line in ("DATA           = HEROES &cup; MAPS &cup; META",
                 "for each domain D in { HEROES, MAPS, META }:",
                 "  INDEPENDENT(D) = &#8899; facts(s)",
                 "  DEPENDENT(D)   = &#8899; facts(s &#8904; t)",
                 "  FACTS(D)       = INDEPENDENT(D) &cup; DEPENDENT(D)",
                 "FACTS          = FACTS(HEROES) &cup; FACTS(MAPS) &cup; FACTS(META)",
                 "FACTS(D) &cap; FACTS(E) = the joins of D with E",
                 "STRATEGIES     = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS",
                 "COMP           = ARGMAX[ STRATEGIES( FACTS ) ]"):
        assert line in page
    # every domain yields both kinds; the dependent ones are the joins, stated as such
    assert "<b>independent</b> facts" in page and "<b>dependent</b> facts" in page
    assert "heroes\n&#8904; map_meta" in page or "heroes &#8904; map_meta" in page
    # the function itself: what it reads, its terms, the formula, the scale, the empty case
    assert "The function: STRATEGIES( FACTS )" in page
    assert "score(x) = &Sigma; heuristics h" in page and "norm_h(v) = clamp(" in page
    assert "What 100 means" in page and "not a win probability" in page
    assert "When the playbook holds only limits" in page
    assert "The data layer" in page and "The inference layer" in page and "The board" in page
    assert "never calls a language model" in page


# --- the board's one write: a weight stored through the tune tool ------------------


def test_storing_a_weight_is_a_tune_call_over_the_door(monkeypatch):
    """With an MCP URL set (the compose stack) the board sends one tools/call
    for `tune` - the id, the field, the rounded weight, the reason - and
    relays the tool's line or its refusal; bad input never reaches the door."""
    calls = []

    def fake_mcp(name, arguments):
        calls.append((name, arguments))
        if arguments["id"] == "no-such":
            return "no strategy 'no-such'", None, True
        return "tuned %s: weight 1 -> %s\n- log line" % (arguments["id"], arguments["value"]), \
            {"id": arguments["id"], "field": "weight", "old": 1.0, "new": "9.99"}, False
    monkeypatch.setattr(board, "MCP_URL", "http://data:8020/mcp")
    monkeypatch.setattr(board, "mcp_call", fake_mcp)
    data, code = board.api_weight({"id": "healing-floor", "weight": "9.994"})
    assert code == 200 and data["line"] == "tuned healing-floor: weight 1 -> 9.99"
    assert calls == [("tune", {"id": "healing-floor", "field": "weight", "value": 9.99,
                               "reason": board.STORE_REASON, "by": "the board"})]
    data, code = board.api_weight({"id": "no-such", "weight": 2})
    assert code == 400 and "no strategy" in data["error"]
    for bad in ({"id": "../escape", "weight": 2}, {"id": "healing-floor", "weight": "x"},
                {"id": "healing-floor", "weight": 11}, {}, None):
        assert board.api_weight(bad)[1] == 400
    assert len(calls) == 2                                   # the refusals never knocked


def test_storing_a_weight_locally_runs_the_tune_tool_in_process(db, dsn, tmp_path, monkeypatch):
    """Without an MCP URL the same call goes through the tool registry: the
    file's weight changes, the tuning log says why, and the catalog is
    mirrored - here into a rolled-back transaction, on a private copy of
    the playbook."""
    import os
    import shutil

    from inference import catalog, tune
    from tests.db.test_sources_from_cache import Sandbox
    for name in os.listdir(catalog.STRATEGIES_DIR):
        if name.endswith(".md"):
            shutil.copy(os.path.join(catalog.STRATEGIES_DIR, name), tmp_path / name)
    heuristic = next(h for h in catalog.load() if h.kind == "heuristic")
    monkeypatch.setattr(board, "MCP_URL", "")
    monkeypatch.setattr(board, "tool_context", lambda: Sandbox(dsn=dsn))
    monkeypatch.setattr(catalog, "STRATEGIES_DIR", str(tmp_path))
    monkeypatch.setattr(tune, "LOG_PATH", str(tmp_path / "tuning-log.md"))
    data, code = board.api_weight({"id": heuristic.id, "weight": 7.25})
    assert code == 200 and data["line"].startswith("tuned %s: weight" % heuristic.id)
    assert data["change"]["new"] == "7.25"
    stored = next(h for h in catalog.load(str(tmp_path)) if h.id == heuristic.id)
    assert stored.weight == 7.25
    assert next(h for h in catalog.load(catalog.SHIPPED_DIR)   # the repo's file is untouched
                if h.id == heuristic.id).weight == heuristic.weight
    log = (tmp_path / "tuning-log.md").read_text(encoding="utf-8")
    assert board.STORE_REASON in log and heuristic.id in log and "[the board]" in log
    data, code = board.api_weight({"id": "no-such-strategy", "weight": 2})
    assert code == 400 and "no strategy" in data["error"]
