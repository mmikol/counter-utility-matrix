"""The board's pages: the shell, the math and tests pages, and the static
files they load. No server and no database - these read ui/pages.py's output
and the scripts' source. The scripts are pinned at their seams - the routes
and query keys they send, the ids they write, the globals and payload keys
they read - against what the shell and the server write. The two decisions
only the client can make, the stale-reply guard and the HTML escape, are
pinned in the script; any other decision worth pinning is made on the
server, as the seat badge is (momentum.badges), and tested there."""

import os
import re

from facts import board_facts
from facts.draft import Draft, board_query
from inference import catalog, engine, tune
from inference.result import Badge, Momentum, Pick
from inference.scoring import Contribution
from inference.strategy import StrategyRecord
from tests.inference import FIXTURE_PLAYBOOK
from ui import board, pages


def scripts():
    """The page's three scripts as one text, in the order the page loads them."""
    return "".join(pages.static_file(name)[0].decode()
                   for name in ("comps.js", "playbook.js", "board.js"))


def function(script, name):
    """One top-level function's source: from its `function name(` to the next
    top-level function, or the end."""
    start = script.index("function %s(" % name)
    end = script.find("\nfunction ", start + 1)
    return script[start:] if end < 0 else script[start:end]


def test_board_page_has_two_rosters_and_the_three_panels():
    body = pages.view_board(True)
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
    assert b".kind.assumption" in pages.static_file("board.css")[0]


def test_the_ban_picker_is_a_roster():
    body = pages.view_board(True)
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    css = pages.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css


def test_every_stylesheet_class_is_used_by_the_page():
    """A class in board.css that no script, template or page names is dead
    styling; the rosters, cards and panels are all rendered from these files."""
    css = pages.static_file("board.css")[0].decode()
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
    sources = scripts() + pages.view_board(True) + pages.view_math()
    assert len(classes) > 50
    assert [c for c in classes if not re.search(r"\b%s\b" % re.escape(c), sources)] == []


def test_the_page_is_a_shell_over_static_files():
    body = pages.view_board(True)
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
    page = pages.view_math()
    assert "<p id='fight-odds'><b>Fight odds.</b>" in page
    # a table of contents: every link resolves to an id on the page
    toc = page[page.index("<nav class='toc'>"):page.index("</nav>")]
    targets = re.findall(r"href='#([^']+)'", toc)
    assert targets and all(("id='%s'" % t) in page for t in targets), targets
    for name in ("likely-comp", "counter", "weights", "what-100-means", "argmax"):
        assert name in targets
    assert "<h2 id='equation'>The Counter Utility Matrix</h2>" in page  # the name is the equation
    # and the page says what the short name stands for
    assert "<b>Countrix</b> is short for <b>Counter Utility Matrix</b>" in page
    assert "likelihood(h) = pick(h, map) + 2 &times; partners(h, the six so far)" in page
    css = pages.static_file("board.css")[0].decode()
    for rule in (".tile.capped", ".tile.soon", ".momentum .verdict", ".inf-six + .inf-six"):
        assert rule in css, rule
    assert "id='clearall'" in body
    header = body.split("</header>")[0]
    # the two pills, pinned top-right
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links
    assert pages.repo_url() in links
    assert "href='/tests'" in links            # the checks, beside the math
    assert links.rstrip().endswith("GitHub</a></span>")
    # the page hands the scripts the board's flag, and the counts they need
    assert "var TEAM = 6, BANS = 5, READ_ONLY = true;" in body
    assert "READ_ONLY = false" in pages.view_board(False)
    data, ctype = pages.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function paint" in data
    data, ctype = pages.static_file("comps.js")
    assert ctype.startswith("application/javascript") and b"function renderResult" in data
    data, ctype = pages.static_file("playbook.js")
    assert ctype.startswith("application/javascript") and b"function renderPlaybook" in data
    assert pages.static_file("math.html") is None          # the article is not served on its own
    data, ctype = pages.static_file("board.css")
    assert ctype.startswith("text/css") and b".tile.banned" in data
    assert pages.static_file("../board.py") is None and pages.static_file("nope.js") is None


def test_the_display_font_ships_with_the_board_and_its_licence():
    """The page loads nothing from another host: the headings' face is served
    from ui/static, and the SIL OFL that lets it travel travels beside it."""
    data, ctype = pages.static_file("bebas-neue.woff2")
    assert ctype == "font/woff2" and data.startswith(b"wOF2")
    css = pages.static_file("board.css")[0].decode()
    assert "@font-face" in css and "url('/static/bebas-neue.woff2')" in css
    assert "fonts.googleapis" not in css and "@import" not in css
    assert pages.static_file("OFL.txt") is None            # beside the font, not served
    with open(os.path.join(pages.STATIC_DIR, "OFL.txt"), encoding="utf-8") as handle:
        licence = handle.read()
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence and "Dharma Type" in licence


def test_the_scripts_send_the_routes_and_query_keys_the_board_reads():
    """Each route the scripts ask for is the board's own - /api/infer is the
    inference service's, not the page's - and each key of a board's query
    is sent in the spelling parse_board reads back, with the sliders'
    weights and the page's client, which api_board reads beside them."""
    script = scripts()
    for route in ("/api/roster", "/api/facts?", "/api/board?", "/api/strategies", "/api/weight"):
        assert route in script, route
    assert "/api/infer" not in script
    for key in [*board_query(Draft()), "weights", "client"]:
        assert "'%s='" % key in script, key


def test_the_scripts_write_the_ids_and_read_the_globals_the_shell_holds():
    """Every element a script looks up by a literal id is one the shell
    renders, the data attributes the clicks read are the shell's, each
    global the shell sets is read, and the weight slider and its number box
    carry the bounds tune enforces."""
    script, body = scripts(), pages.view_board(True)
    ids = set(re.findall(r"\bel\('([^']+)'\)", script))
    assert len(ids) >= 20
    assert [i for i in sorted(ids) if "id='%s'" % i not in body] == []
    for attribute in ("data-tab", "data-clear", "data-side"):
        assert attribute in script and attribute in body, attribute
    shell = re.search(r"<script>var (.*?);</script>", body).group(1)
    names = [part.split(" = ")[0] for part in shell.split(", ")]
    assert names == ["TEAM", "BANS", "READ_ONLY"]
    for name in names:
        assert re.search(r"\b%s\b" % name, script), name
    assert script.count("min='%g' max='%g' step='0.01'" % tune.WEIGHT_RANGE) == 2


def test_the_scripts_read_payload_keys_the_server_writes(synthetic_world, monkeypatch):
    """Each key a script reads off a payload is one the server writes: the
    board and a seat on it, a pick, a contribution, the momentum and a
    badge, a strategy, a fact, and the roster with its heroes and maps. No
    script reads the raw sum."""
    script = scripts()

    def read(keys, written):
        for key in keys.split():
            assert key in written, key
            assert re.search(r"\.%s\b" % key, script), key
    solved = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ("Balm",)),
                          catalog=catalog.load(FIXTURE_PLAYBOOK)).to_dict()
    read("plan momentum shapes current red_current fill expected blue map side", solved)
    read(
        "picks contributions alternatives considered seconds playstyle cited scoring unscored"
        " blue", solved["current"])
    read("hero role why evidence portrait", Pick.__annotations__)
    read(
        "id applies ok weighted form when bonus penalty norm spread need metric raw confidence"
        " confidence_raw fact text", Contribution.__annotations__)
    read("blue red odds verdict badges", Momentum.__annotations__)
    read("label tip", Badge.__annotations__)
    read(
        "id name kind form weight direction metric need when require soft penalty bonus params"
        " body", StrategyRecord.__annotations__)
    fact = board_facts.generate(synthetic_world, Draft()).to_dict()["facts"][0]
    read("id key subject text scope team source", fact)
    monkeypatch.setattr(board.tables, "load", lambda cx: synthetic_world)
    roster = board.api_roster(None).body
    read("heroes maps role_icons newer_patches", roster)
    read("name role subrole portrait status release_date", roster["heroes"][0])
    read("name mode style sided", roster["maps"][0])
    assert not re.search(r"\.score\b", script)


def test_a_reply_to_an_older_request_is_dropped_and_its_board_cancelled():
    """The guard only the page can keep: each refresh numbers its requests,
    so a reply or a failure from an older one - the facts or the board -
    is dropped, and a newer board request aborts the older one, whose
    server stops solving it."""
    refresh = function(scripts(), "refresh")
    assert refresh.count("mine !== seq") == 4
    assert "solve.abort()" in refresh and "signal" in refresh


def test_an_apostrophe_cannot_close_a_single_quoted_attribute():
    """King's Row in a title='...' attribute, or the label's own "each side's",
    must not end the attribute at the apostrophe."""
    script = scripts()
    esc = function(script, "esc")
    replaced = "King's Row <b> \"x\" & y"
    for pattern, entity in re.findall(r"\.replace\(/(.)/g,\s*'([^']+)'\)", esc):
        replaced = replaced.replace(pattern, entity)
    assert "'" not in replaced and "<" not in replaced and '"' not in replaced
    assert "title='each side\\'s" not in script and "title='each side&#39;s" in script


def test_the_math_page_states_the_equation_and_the_layers():
    page = pages.view_math()
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
    # the counter: blue's own six above the optimal that ignores its picks
    counter = page[page.index("<p id='counter'>"):]
    assert "shows blue's six above the optimal" in counter[:counter.index("</p>")]
    # the page solves no countered case: the hedge is the board tool's
    assert "row is the hedge" not in page and "row is the hedge" not in pages.view_tests()
