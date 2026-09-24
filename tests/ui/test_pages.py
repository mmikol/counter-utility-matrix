"""The board's pages: the shell, the math and tests pages, and the static
files they load. No server and no database - these read ui/pages.py's output
and the scripts' source. What a script says in JavaScript is its own:
grepping it proves the source says what the page needs, not that the page
runs, so each test pins the line a behaviour hangs on."""

import re

from ui import pages


def scripts():
    """The page's three scripts as one text, in the order the page loads them."""
    return "".join(pages.static_file(name)[0].decode()
                   for name in ("comps.js", "playbook.js", "board.js"))


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
    script = scripts()
    assert "/api/roster" in script and "/api/facts" in script and "fetch('/api/board?'" in script
    assert "/api/infer" not in script                  # the board's route is named for a board
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
    assert b".kind.assumption" in pages.static_file("board.css")[0]


def test_the_ban_picker_is_a_roster():
    body = pages.view_board(True)
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    script = scripts()
    assert "function buildBanPicker" in script and "rosterHTML('ban')" in script
    assert "bansOpen = false" in script                     # collapsed by default
    css = pages.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css


def test_an_announced_hero_is_a_coming_soon_tile_in_its_role_column():
    script = scripts()
    # no constant: the roster carries the status
    assert "if (h.status === 'announced') return soonTile(h);" in script
    card = script[script.index("function soonTile"):script.index("function rosterHTML")]
    assert "class='tile soon'" in card and "data-h" not in card and "data-team" not in card
    assert "coming soon" in card and "SILHOUETTE" in card and "releases" in card
    assert 'var SILHOUETTE = "<svg' in script
    assert ".tile.soon" in pages.static_file("board.css")[0].decode()


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
    script = scripts()
    assert "'red - most likely starting comp'" in script
    assert "'blue - optimal counter to current picks'" in script
    assert "renderResult(d.expected, el('inf-red')" in script and "d.momentum" in script
    # neither seat carries a score: its head is the title alone and the renderer
    # never reads a figure; the picks' scores are the badges above the pickers
    fn = script[script.index("function renderResult"):script.index("function weightRow")]
    assert "normalized" not in fn and "unscored" not in fn
    # the strip is two bars, blue's and red's, empty until a seat has a figure
    assert "mo.blue" in script and "mo.red" in script and "d.red_current" in script
    assert ">fight odds</span>" in script and "class='mbars'" in script   # stacked, one track width
    assert "mo.odds" in script          # the bars are the odds when both seats score
    assert "mo.verdict" not in script                          # no verdict sentence on the board
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
    # the payload keys the page reads, the wire it calls, the bounds it honours.
    # What the scripts say in JavaScript is theirs: grepping an expression proves
    # the source has not been edited, not that the page works
    assert "d.plan" in script and "d.shapes" in script and "d.momentum" in script
    assert ".tile.capped" in pages.static_file("board.css")[0].decode()
    # a heuristic's weight is a slider under its card, bounded like the catalog's
    assert "type='range' min='0' max='10' step='0.01'" in script
    assert "type='number' class='wval' min='0' max='10' step='0.01'" in script
    # the setting rides with each board request, and the one write is one POST
    assert "q.push('weights=' + " in script and "st.weights" in script
    assert "fetch('/api/weight', { method: 'POST'" in script
    # *store* is rendered only on a writable board
    assert "READ_ONLY ? ''" in script and "class='wstore'" in script
    # the playbook is grouped by kind, in the equation's order
    kinds = script[script.index("var KINDS = ["):script.index("function renderPlaybook")]
    assert kinds.index("'constraint'") < kinds.index("'heuristic'") < kinds.index("'assumption'")
    # three panes now - satisfied, costing, did not read - each filterable
    assert "' off'" in script                  # the list keeps its grey-out
    assert "'costing'" in script and "'unread'" in script
    assert "class='barfind'" in script
    # the search's numbers sit under the cards and above the strategies met, not in the head
    cards, meta, met = (fn.index("<div class='comp'>"), fn.index("class='legend meta'"),
                        fn.index("bars(d.contributions)"))
    assert cards < meta < met
    # a playbook that scores nothing reads unscored, never 100 / 100
    assert "r.scoring" in script and "'unscored'" in script
    assert "el('clearall').onclick" in script and "id='clearall'" in body
    header = body.split("</header>")[0]
    # the two pills, pinned top-right
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links
    assert pages.repo_url() in links
    assert "href='/tests'" in links            # the checks, beside the math
    assert links.rstrip().endswith("GitHub</a></span>")
    # a team's clear button empties that team only
    assert "near('[data-clear]')" in script
    # the suggestions fill blue's empty slots alone
    suggestions = script[script.index("function paintSuggestions"):script.index("function showTab")]
    assert "el('blueslots')" in suggestions and "el('redslots')" not in suggestions
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
