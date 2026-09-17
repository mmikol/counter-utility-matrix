"""The board: every JSON endpoint speaks the same facts and inference the
MCP tools serve, and the page carries the two rosters. No HTTP server is
spun up - the handler is thin routing."""

import json
import re

import pytest

from ui import board

pytestmark = pytest.mark.invariant


def scripts():
    """The page's three scripts as one text, in the order the page loads them."""
    return "".join(board.static_file(name)[0].decode()
                   for name in ("comps.js", "playbook.js", "board.js"))


def test_board_page_has_two_rosters_and_the_three_panels():
    body = board.view_board()
    assert "class='team red'" in body and "class='team blue'" in body
    nav = body[body.index("<nav class='tabs'>"):body.index("</nav>")]
    assert nav.count("<button") == 3
    for name in ("comps", "facts", "playbook"):
        assert "<button data-tab='%s'>%s</button>" % (name, name) in nav
        assert "id='tab-%s'" % name in body
    # the facts total sits inside the facts panel, beside the filter - not on the tab
    assert "factsn" not in nav
    facts_panel = body[body.index("id='tab-facts'"):body.index("id='tab-playbook'")]
    assert "id='factsn' class='count'" in facts_panel
    assert "up to five, all optional" not in body            # the bans bar carries no hint
    # a team header is its name, its figure and its clear button: no subtitle, no counter
    for team in ("blue", "red"):
        h2 = body[body.index("<h2>%s team" % team) + len("<h2>"):]
        h2 = h2[:h2.index("</h2>")]
        assert h2.count("<") == 4, h2
        assert "id='%sscore'" % team in h2 and "data-clear='%s'" % team in h2
    assert "ARGMAX[" not in body and "href='/math'" in body   # the equation lives on /math
    assert "<footer" not in body
    assert "id='flash'" in body[:body.index("</header>")]
    comps = body[body.index("id='tab-comps'"):body.index("id='tab-facts'")]
    assert "id='inf-blue'" in comps and "id='inf-red'" in comps
    script = scripts()
    assert "/api/roster" in script and "/api/facts" in script and "/api/infer" in script
    assert "localStorage" in script
    assert "var TABS = ['comps', 'facts', 'playbook']" in script
    # the 0-100 figure and only it: no script reads the raw sum
    assert "normalized" in script and "/ 100" in script
    assert not re.search(r"\.score\b", script)
    assert "r.scoring === false ? (r.unscored || '')" in script   # the engine's reason alone
    # a card's badge is its kind alone; the form is the meta line's to say
    assert "<span class='kind \" + h.kind + \"'>\" + h.kind + '</span><b>'" in script
    # anchors at the top of the playbook, one per group, that scroll to it
    assert "class='pbnav'" in script and "data-group='pb-" in script and "scrollIntoView" in script
    assert "'assumption' ? 'assumption - taken as given" in script
    assert b".kind.assumption" in board.static_file("board.css")[0]


def test_the_ban_picker_is_a_roster():
    body = board.view_board()
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    script = scripts()
    assert "function buildBanPicker" in script and "rosterHTML('ban')" in script
    assert "bansOpen = false" in script                     # collapsed by default
    css = board.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css


def test_an_announced_hero_is_a_coming_soon_tile_in_its_role_column():
    script = scripts()
    # no constant: the roster carries the status
    assert "if (h.status === 'announced') return soonTile(h);" in script
    card = script[script.index("function soonTile"):script.index("function rosterHTML")]
    assert "class='tile soon'" in card and "data-h" not in card and "data-team" not in card
    assert "coming soon" in card and "SILHOUETTE" in card and "releases" in card
    assert 'var SILHOUETTE = "<svg' in script
    assert ".tile.soon" in board.static_file("board.css")[0].decode()


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
    from inference import catalog
    data = board.api_strategies()
    assert len(data["strategies"]) == len(catalog.load()) and data["strategies"]
    assert data["playbook"] == catalog.playbook_name()
    assert json.dumps(data)


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


def test_every_stylesheet_class_is_used_by_the_page():
    """A class in board.css that no script, template or page names is dead
    styling; the rosters, cards and panels are all rendered from these files."""
    css = board.static_file("board.css")[0].decode()
    selectors, depth, buf = [], 0, ""
    for ch in css:
        if ch == "{":
            if depth == 0:
                selectors.append(buf)
            depth, buf = depth + 1, ""
        elif ch == "}":
            depth, buf = depth - 1, ""
        else:
            buf += ch
    classes = set()
    for selector in selectors:
        if selector.lstrip().startswith("@"):        # an at-rule, not a selector
            continue
        classes.update(re.findall(r"\.([A-Za-z_][\w-]*)", re.sub(r"/\*.*?\*/", "", selector)))
    sources = scripts() + board.view_board() + board.view_math()
    assert len(classes) > 50
    assert [c for c in classes if not re.search(r"\b%s\b" % re.escape(c), sources)] == []


def test_the_page_is_a_shell_over_static_files():
    body = board.view_board()
    assert "/static/board.css" in body and "/static/board.js" in body
    order = [body.index("/static/%s.js" % n) for n in ("comps", "playbook", "board")]
    assert order == sorted(order)      # board.js loads last: it calls the others
    assert "id='momentum'" in body and "id='plan'" in body
    # scores live in the boxes
    assert "id='bluescore'" in body and "id='redscore'" in body
    assert "data-clear='red'" in body and "data-clear='blue'" in body
    # the momentum strip sits above both boxes
    assert body.index("id='momentum'") < body.index("id='blueslots'")
    assert "id='momentum'" not in body[body.index("id='tab-comps'"):]
    # blue on the left, red on the right, like the boxes
    assert body.index("id='inf-blue'") < body.index("id='inf-red'")
    assert body.index("id='blueslots'") < body.index("id='redslots'")
    script = scripts()
    assert "'red - most likely starting comp'" in script
    assert "'blue - optimal counter to current picks'" in script
    assert "renderResult(d.expected, el('inf-red')" in script and "d.momentum" in script
    # neither seat carries a score: its head is the title alone and the renderer
    # never reads a figure; the picks' scores are the badges above the pickers
    fn = script[script.index("function renderResult"):script.index("function weightRow")]
    assert "<div class='inf-head'><h3>\" + esc(title) + '</h3></div>'" in fn
    assert "normalized" not in fn and "unscored" not in fn
    assert "function meaning(d)" in script
    # the strip is two bars, blue's and red's, empty until a seat has a figure
    assert "bar('blue', mo.blue, d.current) + bar('red', mo.red, d.red_current)" in script
    assert ">fight odds</span>" in script and "class='mbars'" in script   # stacked, one track width
    assert "mo.odds ? mo.odds[side] : null" in script      # the bars are the odds when both score
    assert "mo.verdict" not in script                          # no verdict sentence on the board
    page = board.view_math()
    assert "<p id='fight-odds'><b>Fight odds.</b>" in page
    # a table of contents: every link resolves to an id on the page
    toc = page[page.index("<nav class='toc'>"):page.index("</nav>")]
    targets = re.findall(r"href='#([^']+)'", toc)
    assert targets and all(("id='%s'" % t) in page for t in targets), targets
    for name in ("likely-comp", "counter", "weights", "what-100-means", "argmax"):
        assert name in targets
    assert "<h2 id='equation'>The Counter Utility Matrix</h2>" in page   # the name is the equation
    assert "likelihood(h) = pick(h, map) + 2 &times; partners(h, the six so far)" in page
    assert "game plan" in script and "d.plan" in script
    assert "paintSuggestions" in script and "slot suggested" in script and "bluescore" in script
    # the playbook's shape limits hold on the roster: a capped role dims and refuses
    assert "function roleCap" in script and "' capped'" in script and "d.shapes" in script
    assert "the playbook allows at most" in script
    assert ".tile.capped" in board.static_file("board.css")[0].decode()
    # a heuristic's weight is a slider under its card; the setting rides with each request
    assert "function weightRow" in script and "type='range' min='1' max='10' step='0.01'" in script
    assert "type='number' class='wval' min='1' max='10' step='0.01'" in script
    assert "q.push('weight=' + " in script and "st.weights" in script
    assert "function setWeight" in script
    assert "h.form === 'heuristic' ? weightRow(h)" in script     # only heuristics have weights
    assert "function storeWeight" in script and "fetch('/api/weight', { method: 'POST'" in script
    # the card is its kind, its name, its metric line and, for a heuristic, the weight row
    assert "(h.form === 'heuristic' ? weightRow(h) : '') + '</div>'" in script
    # the playbook is grouped by kind, in the equation's order, each group headed by its count alone
    kinds = script[script.index("var KINDS = ["):script.index("function renderPlaybook")]
    assert kinds.index("'constraint'") < kinds.index("'heuristic'") < kinds.index("'assumption'")
    assert "class='pbgroup " in script and "none in the playbook in force" in script
    assert "<h3>\" + k[1] + \" <span class='n'>\" + these.length + '</span></h3>'" in script
    assert "commas(shown) + ' of ' + commas(total) + ' facts'" in script   # the total, with commas
    assert "function commas(n)" in script and "commas(d.considered)" in script
    assert "strategies satisfied" in script and "' off'" in script  # the list keeps its grey-out
    # the search's numbers sit under the cards and above the strategies met, not in the head
    cards, meta, met = (fn.index("<div class='comp'>"), fn.index("class='legend meta'"),
                        fn.index("bars(d.contributions)"))
    assert cards < meta < met
    assert "var badge = function (cur, optimal, who)" in script    # a figure even with no picks
    # a playbook that scores nothing reads unscored, never 100 / 100
    assert "r.scoring === false ? 'unscored'" in script
    assert "el('clearall').onclick" in script and "id='clearall'" in body
    header = body.split("</header>")[0]
    # the two pills, pinned top-right
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links
    assert board.REPO_URL in links
    assert links.rstrip().endswith("GitHub</a></span>")
    # a team's clear button empties that team only
    assert "near('[data-clear]')" in script
    # the suggestions fill blue's empty slots alone
    suggestions = script[script.index("function paintSuggestions"):script.index("function showTab")]
    assert "el('blueslots')" in suggestions and "el('redslots')" not in suggestions
    assert "var TEAM = 6, BANS = 5;" in body
    data, ctype = board.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function paint" in data
    data, ctype = board.static_file("comps.js")
    assert ctype.startswith("application/javascript") and b"function renderResult" in data
    data, ctype = board.static_file("playbook.js")
    assert ctype.startswith("application/javascript") and b"function renderPlaybook" in data
    assert board.static_file("math.html") is None          # the article is not served on its own
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
    assert "When nothing scores" in page
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
    from tests.inference import FIXTURE_PLAYBOOK
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name.endswith(".md"):
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    heuristic = next(h for h in catalog.load(FIXTURE_PLAYBOOK) if h.kind == "heuristic")
    monkeypatch.setattr(board, "MCP_URL", "")
    monkeypatch.setattr(board, "tool_context", lambda: Sandbox(dsn=dsn))
    monkeypatch.setattr(catalog, "STRATEGIES_DIR", str(tmp_path))
    monkeypatch.setattr(tune, "LOG_PATH", str(tmp_path / "tuning-log.md"))
    data, code = board.api_weight({"id": heuristic.id, "weight": 7.25})
    assert code == 200 and data["line"].startswith("tuned %s: weight" % heuristic.id)
    assert data["change"]["new"] == "7.25"
    stored = next(h for h in catalog.load(str(tmp_path)) if h.id == heuristic.id)
    assert stored.weight == 7.25
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)   # the reference file is untouched
                if h.id == heuristic.id).weight == heuristic.weight
    log = (tmp_path / "tuning-log.md").read_text(encoding="utf-8")
    assert board.STORE_REASON in log and heuristic.id in log and "[the board]" in log
    data, code = board.api_weight({"id": "no-such-strategy", "weight": 2})
    assert code == 400 and "no strategy" in data["error"]
