"""The board's pages: the shell, the math and tests pages, and the static
files they load. No server and no database - these read ui/pages.py's output
and the scripts' source. What a script says in JavaScript is its own:
grepping it proves the source says what the page needs, not that the page
runs, so each test pins the line a behaviour hangs on."""

import os
import re

from ui import pages


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


def local(body, name):
    """A function assigned to `var name` inside another: from there to the
    line that closes it."""
    start = body.index("var %s = function" % name)
    return body[start:body.index("\n  };", start)]


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
    assert "renderResult(d.expected, el('inf-red')" in script and "d.momentum" in script
    # neither seat carries a score: its head is the title alone and the renderer
    # never reads a figure; the picks' scores are the badges above the pickers
    fn = script[script.index("function renderResult"):script.index("function weightRow")]
    assert "normalized" not in fn and "unscored" not in fn
    # the strip is two bars, blue's and red's, empty until a seat has a figure
    assert "mo.blue" in script and "mo.red" in script and "d.red_current" in script
    assert ">fight odds</span>" in script and "class='mbars'" in script   # stacked, one track width
    assert "mo.odds" in script          # the bars are the odds when both seats score
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
    # the payload keys the page reads, the wire it calls, the bounds it honours
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
    six = function(script, "resultHTML")
    cards, meta, met = (six.index("<div class='comp'>"), six.index("class='legend meta'"),
                        six.index("bars(d.contributions)"))
    assert cards < meta < met
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
    suggestions = function(script, "paintSuggestions")
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


def test_a_seat_that_cannot_score_reads_unscored_with_or_without_picks():
    """A playbook that scores nothing reads unscored, never 100 / 100: the
    badge asks whether the seat's current comp can score before it asks
    whether the seat holds picks, and a strip bar reads the word for an empty
    seat too, the engine's reason in its tooltip."""
    script = scripts()
    badge = local(function(script, "renderInf"), "badge")
    assert badge.index("cur.scoring === false") < badge.index("picks yet")
    assert "return ['unscored', cur.unscored || ''];" in badge
    bar = local(function(script, "renderInf"), "bar")
    assert "unscored = !!res && res.scoring === false" in bar
    assert "res.blue" not in bar                        # picks or not
    assert "var tip = unscored ? res.unscored || ''" in bar


def test_the_strip_says_the_verdict_while_neither_bar_has_a_figure():
    script = scripts()
    render = function(script, "renderInf")
    assert "var figureless = typeof mo.blue !== 'number' && typeof mo.red !== 'number';" in render
    assert "(figureless && mo.verdict ? \"<span class='verdict'>\" + esc(mo.verdict)" in render
    assert ".momentum .verdict" in pages.static_file("board.css")[0].decode()


def test_a_half_drafted_seat_reads_the_share_its_picks_reach():
    """A partial team's own share is null by design; its badge reads the share
    its fill reaches - the momentum's figure for that seat - and says so."""
    script = scripts()
    render = function(script, "renderInf")
    assert "badge(d.current, mo.blue, 'blue'), r = badge(d.red_current, mo.red, 'red')" in render
    meaning = function(script, "meaning")
    assert "d.partial ? 'the best six from ' + whose + ' picks reaches '" in meaning


def test_blue_seat_draws_its_own_six_above_the_optimal():
    """With one to five blue picks the seat draws the fill, at six the picks
    themselves, and the optimal that ignores them below - the six the plan
    describes on top, so blue's picks never seem to have gone missing."""
    render = function(scripts(), "renderInf")
    assert "d.fill ? resultHTML(d.fill, 'blue - your picks, the rest filled')" in render
    assert "held >= TEAM ? resultHTML(d.current, 'blue - your six')" in render
    assert "el('inf-blue').innerHTML = ours + resultHTML(d.blue, 'blue - optimal vs red\\'s '" \
        in render
    assert "optimal counter to current picks" not in render
    assert ".inf-six + .inf-six" in pages.static_file("board.css")[0].decode()
    page = pages.view_math()
    counter = page[page.index("<p id='counter'>"):]
    assert "shows blue's six above the optimal" in counter[:counter.index("</p>")]


def test_a_pick_leaves_red_likely_six_standing():
    """Red's likely six changes only with the map, the side and the bans: a
    pick does not blank it to searching."""
    refresh = function(scripts(), "refresh")
    assert "var key = [st.map, st.side].concat(st.bans).join('|');" in refresh
    assert "if (key !== redKey) el('inf-red').innerHTML" in refresh
    assert "redKey = d.error ? null : key;" in refresh


def test_a_newer_board_request_aborts_the_older_and_names_the_page():
    refresh = function(scripts(), "refresh")
    assert "if (solve) solve.abort();" in refresh
    assert "'client=' + CLIENT" in refresh and "{ signal: solve.signal }" in refresh


def test_a_failed_board_request_leaves_nothing_of_the_last_board():
    """No board back - the server down, a reply that is not JSON - blanks the
    badges, the plan and the suggestions, says the board is not answering in
    the strip and the seat, and retries when the page is back in view."""
    script = scripts()
    failed = function(script, "boardFailed")
    for line in ("INF = null; paint();", "el('plan').innerHTML = '';",
                 "<span class='legend'>the board is not answering</span>",
                 "el(id).textContent = ''; el(id).title = '';"):
        assert line in failed, line
    assert "boardFailed();" in function(script, "refresh")
    assert "if (node.textContent !== '…') node.dataset.was = node.textContent;" in \
        function(script, "solving")
    error = function(script, "renderInf")
    error = error[:error.index("return;")]
    assert "paint();" in error                         # an error reply drops the suggestions
    assert "['online', 'focus'].forEach" in script and "if (STALE) refresh();" in script
    assert "the database is not answering" not in script


def test_a_facts_error_replaces_the_rows_it_leaves_behind():
    script = scripts()
    assert "FACTS = null;" in function(script, "factsFailed")
    refresh = function(script, "refresh")
    assert "if (d.error) { factsFailed(d.error); return; }" in refresh
    catch = refresh[refresh.index("fetch('/api/facts?'"):refresh.index("solving(true)")]
    assert catch.count("if (mine !== seq) return;") == 2   # a stale failure is dropped too


def test_a_failed_roster_load_is_said_and_retried():
    script = scripts()
    boot = function(script, "boot")
    assert "if (!r.ok || d.error || !d.heroes) throw" in boot
    assert "setTimeout(boot, bootWait);" in boot and "bootWait * 2" in boot
    assert "if (!ROSTER) return;" in function(script, "paint")
    assert "if (!ROSTER) return;" in function(script, "refresh")


def test_a_filled_slot_carries_its_own_reason():
    script = scripts()
    paint = function(script, "paint")
    assert "s.title = pickReason(team, name);" in paint and "s.title = '';" in paint
    reason = function(script, "pickReason")
    assert "(d.fill || d.current)" in reason and "d.red_current" in reason


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


def test_a_weight_whose_heuristic_is_gone_is_dropped():
    script = scripts()
    prune = function(script, "pruneWeights")
    assert "if (h.form === 'heuristic') live[h.id] = true;" in prune
    assert "delete st.weights[id]" in prune and "save()" in prune
    render = function(script, "renderPlaybook")
    # a catalog that did not answer returns before anything is pruned
    assert render.index("return; }") < render.index("pruneWeights(d);")


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
    # the page solves no countered case: the hedge is the board tool's
    assert "row is the hedge" not in page and "row is the hedge" not in pages.view_tests()
