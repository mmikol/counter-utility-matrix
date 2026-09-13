"""A local UI over the built database: dashboard, live evidence board, and
recorded-recommendation viewer.

    python ui.py            # serves http://localhost:8017

Standard library only - no framework, no new dependencies. Reads the same
database every other entry point does (db/cluster by default; DATABASE_URL
overrides - ./docker-db points it at the compose database). The chat that
actually decides comps lives in a Claude Code session via the /comp skill;
this UI is the free window onto the same evidence and the same records.

/recommend is built for use DURING a match: click heroes onto their team
and yours as picks reveal themselves, choose the map, and the evidence
dossier - the exact lines the /comp skill reads - rebuilds live on every
click. The board keeps its state across reloads, and a poller surfaces any
comp the skill records mid-game.
"""

import html
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg

from data.proprietary import dossier

PORT = int(os.environ.get("OVERWATCH_DB_UI_PORT", "8017"))


def dsn():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    import pgserver
    root = os.path.dirname(os.path.abspath(__file__))
    return pgserver.get_server(os.path.join(root, "db", "cluster")).get_uri()


STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #14161a; color: #d7dae0;
       font: 15px/1.5 -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }
a { color: #7ab7ff; text-decoration: none; } a:hover { text-decoration: underline; }
h1 { font-size: 22px; margin: 8px 0 2px; } h1 a { color: inherit; }
h2 { font-size: 15px; margin: 28px 0 10px; color: #9aa3b0;
     text-transform: uppercase; letter-spacing: .08em; }
.sub { color: #8a93a1; margin: 0 0 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr));
         gap: 10px; }
.card { background: #1c2027; border: 1px solid #2a303a; border-radius: 8px;
        padding: 12px 14px; }
.card b { display: block; font-size: 22px; }
.card span { color: #8a93a1; font-size: 13px; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 5px 10px 5px 0; border-bottom: 1px solid #232833;
         vertical-align: top; }
th { color: #8a93a1; font-weight: 600; font-size: 13px; }
select, input[type=text] { background: #14161a; color: #d7dae0;
    border: 1px solid #2a303a; border-radius: 6px; padding: 8px 10px;
    font: inherit; }
button { background: #2f6feb; color: white; border: 0; border-radius: 6px;
         padding: 9px 16px; font: inherit; cursor: pointer; }
button.ghost { background: #262c36; }
.err { background: #3a2026; border: 1px solid #6b2f3a; border-radius: 8px;
       padding: 10px 14px; margin: 14px 0; }
.ev { font-family: ui-monospace, monospace; font-size: 13px; }
.tag { color: #e3b341; }
.pick { background: #1c2027; border: 1px solid #2a303a; border-radius: 8px;
        padding: 10px 14px; margin: 8px 0; }
.pick b { font-size: 16px; }
.badge { display: inline-block; background: #262c36; border-radius: 99px;
         padding: 1px 10px; font-size: 12px; color: #9aa3b0; margin-left: 8px; }

/* --- the live board: two hero-select screens, theirs and ours ------- */
.bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
       background: #1c2027; border: 1px solid #2a303a; border-radius: 10px;
       padding: 12px 14px; }
.bar .status { color: #8a93a1; font-size: 13px; margin-left: auto; }
.board { border-radius: 12px; padding: 16px 18px 12px; margin-top: 14px;
         border: 1px solid; position: relative; overflow: hidden; }
.board.enemy { background: linear-gradient(160deg, #2a161b, #1c1114);
               border-color: #5a2833; }
.board.mine { background: linear-gradient(160deg, #14202e, #10161d);
              border-color: #24405e; }
.board h3 { margin: 0 0 4px; font-size: 14px; letter-spacing: .18em;
            text-transform: uppercase; font-weight: 800; }
.board.enemy h3 { color: #ff5c6f; }
.board.mine h3 { color: #4da3ff; }
.picked { min-height: 40px; margin: 6px 0 14px; }
.slot { display: inline-block; margin: 0 8px 6px 0; padding: 7px 16px;
        font-size: 13px; font-weight: 700; letter-spacing: .06em;
        text-transform: uppercase; cursor: pointer; color: #fff;
        transform: skewX(-8deg); border-radius: 4px; }
.slot > span { display: inline-block; transform: skewX(8deg); }
.board.enemy .slot { background: #d63c50; box-shadow: 0 0 12px #d63c5055; }
.board.mine .slot { background: #2f7fd6; box-shadow: 0 0 12px #2f7fd655; }
.slot.empty { background: none; border: 1px dashed; opacity: .35;
              cursor: default; box-shadow: none; }
.board.enemy .slot.empty { border-color: #d63c50; }
.board.mine .slot.empty { border-color: #2f7fd6; }
.roles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
@media (max-width: 760px) { .roles { grid-template-columns: 1fr; } }
.rolecol h4 { margin: 0 0 8px; text-align: center; color: #9aa3b0;
              font-size: 11px; letter-spacing: .22em;
              text-transform: uppercase; border-bottom: 1px solid #333a46;
              padding-bottom: 6px; }
.grid { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.tile { padding: 6px 10px; font-size: 12px; font-weight: 600;
        letter-spacing: .04em; text-transform: uppercase; cursor: pointer;
        border-radius: 3px; transform: skewX(-8deg); user-select: none;
        background: #232833; color: #aeb6c2; border: 1px solid #313847;
        transition: transform .08s, background .08s; }
.tile > span { display: inline-block; transform: skewX(8deg); }
.tile:hover { transform: skewX(-8deg) scale(1.06); color: #fff; }
.board.enemy .tile:hover { border-color: #d63c50; }
.board.mine .tile:hover { border-color: #2f7fd6; }
.board.enemy .tile.on { background: #d63c50; color: #fff;
    border-color: #ff8fa0; box-shadow: 0 0 14px #d63c5088; }
.board.mine .tile.on { background: #2f7fd6; color: #fff;
    border-color: #8fc4ff; box-shadow: 0 0 14px #2f7fd688; }
.legend { color: #8a93a1; font-size: 13px; margin: 10px 0 0; }
.evwrap { margin-top: 18px; }
.evtools { display: flex; gap: 10px; align-items: baseline; }
.evtools input { flex: 1; }
#evbody tr.derived td { color: #ffd67a; }
#evbody tr.warn td { color: #ff9d8f; }
.newrec { display: none; background: #12301f; border: 1px solid #2e6b45;
          border-radius: 8px; padding: 10px 14px; margin: 12px 0; }
"""


def page(title, body):
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style><main>"
            "<h1><a href='/'>overwatch-db</a></h1>"
            "<p class='sub'>COUNTER = MAX[ HEROES ∩ MAPS ∩ META ]"
            " &nbsp;·&nbsp; <a href='/recommend'>live evidence board</a>"
            " &nbsp;·&nbsp; comps: /comp in a Claude Code session</p>"
            "%s</main>" % (html.escape(title), STYLE, body))


def esc(x):
    return html.escape(str(x if x is not None else ""))


def q(cx, sql, *args):
    return cx.execute(sql, args or None).fetchall()


# --- views ----------------------------------------------------------------

def view_home(cx):
    domains = q(cx, """
        select case
          when tablename in ('hero_meta','map_meta','meta_snapshots','regions',
                             'competitive_tiers','patches','seasons') then 'META'
          when tablename in ('playstyle','counters','map_strategy','synergies',
                             'comp_archetypes','map_playstyle','heuristics',
                             'heuristic_params') then 'PLAYBOOK'
          when tablename in ('strategies','recommendations',
                             'recommendation_picks','recommendation_evidence')
               then 'INFERENCE'
          when tablename in ('maps','game_modes','map_modes','map_stages')
               then 'MAPS'
          when tablename = 'sources' then 'foundation'
          else 'HEROES' end, count(*)
        from pg_tables where schemaname='public' group by 1 order by 1""")
    counts = {}
    for t, in q(cx, "select tablename from pg_tables where schemaname='public'"):
        counts[t] = q(cx, "select count(*) from " + t)[0][0]
    snap = q(cx, """select src.code, ms.queue, ms.platform, ms.input,
            p.name, se.name from meta_snapshots ms
            join sources src using(source_id)
            left join patches p using(patch_id)
            left join seasons se using(season_id) order by ms.snapshot_id""")
    recs = q(cx, """select rec_id, created_at::date, request, playstyle
                    from recommendations order by rec_id desc limit 8""")

    cards = "".join(
        "<div class='card'><b>%s</b><span>%s</span></div>" % (counts[t], t)
        for t in ("heroes", "abilities", "maps", "map_stages", "hero_meta",
                  "map_meta", "counters", "synergies", "heuristics",
                  "recommendations"))
    dom = "".join("<tr><td>%s</td><td>%s tables</td></tr>"
                  % (esc(d), n) for d, n in domains)
    snaps = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s / %s</td><td>%s</td><td>%s</td></tr>"
        % tuple(esc(x) for x in row) for row in snap)
    rec_rows = "".join(
        "<tr><td><a href='/rec/%d'>#%d</a></td><td>%s</td><td>%s</td>"
        "<td>%s</td></tr>" % (r, r, d, esc(req[:70]), esc(ps))
        for r, d, req, ps in recs) or \
        "<tr><td colspan=4 class='sub'>none yet - " \
        "ask /comp in a Claude Code session</td></tr>"

    return page("overwatch-db", """
        <h2>The database</h2><div class='cards'>%s</div>
        <h2>Domains</h2><table>%s</table>
        <h2>Snapshots - population, patch, season</h2>
        <table><tr><th>source</th><th>queue</th><th>platform / input</th>
        <th>patch</th><th>season</th></tr>%s</table>
        <h2>Recommendations</h2>
        <table><tr><th>id</th><th>date</th><th>question</th><th>comp</th></tr>
        %s</table>""" % (cards, dom, snaps, rec_rows))


BOARD_JS = """
var el = function (id) { return document.getElementById(id); };
var st = { map: '', enemy: [], ally: [] };
try {
  var saved = JSON.parse(localStorage.getItem('owdb-board'));
  if (saved && saved.enemy && saved.ally) st = saved;
} catch (e) {}
st.enemy = st.enemy.filter(function (h) { return ROLE[h]; });
st.ally = st.ally.filter(function (h) { return ROLE[h]; });
if (MAPS.indexOf(st.map) < 0) st.map = '';

function save() {
  try { localStorage.setItem('owdb-board', JSON.stringify(st)); } catch (e) {}
}

function toggle(team, name) {
  var arr = team === 'enemy' ? st.enemy : st.ally;
  var at = arr.indexOf(name);
  if (at >= 0) arr.splice(at, 1);
  else if (arr.length < 5) arr.push(name);
  else {
    flash((team === 'enemy' ? 'their' : 'your') +
          ' team already has five - click a lit hero to free the slot');
    return;
  }
  save(); paint(); refresh();
}

function chips(teamEl, team, arr) {
  var out = '', i;
  for (i = 0; i < 5; i++)
    out += arr[i]
      ? "<span class='slot' data-team='" + team + "' data-h='" + arr[i] +
        "'><span>" + arr[i] + '</span></span>'
      : "<span class='slot empty'><span>&ndash;</span></span>";
  teamEl.innerHTML = out;
}

document.addEventListener('click', function (e) {
  var hit = e.target.closest ? e.target.closest('.slot[data-h]') : null;
  if (hit) toggle(hit.getAttribute('data-team'), hit.getAttribute('data-h'));
});

function paint() {
  chips(el('enemypicked'), 'enemy', st.enemy);
  chips(el('mypicked'), 'ally', st.ally);
  var tiles = document.querySelectorAll('.tile'), i;
  for (i = 0; i < tiles.length; i++) {
    var team = tiles[i].getAttribute('data-team');
    var arr = team === 'enemy' ? st.enemy : st.ally;
    tiles[i].className =
      'tile' + (arr.indexOf(tiles[i].getAttribute('data-h')) >= 0 ? ' on' : '');
  }
  el('mapsel').value = st.map;
}

var flashTimer = null;
function flash(msg) {
  el('status').textContent = msg;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(function () { el('status').textContent = ''; }, 2500);
}

var pending = null, seq = 0;
function refresh() {
  clearTimeout(pending);
  el('status').textContent = 'rebuilding evidence…';
  pending = setTimeout(function () {
    var mine = ++seq;
    var qs = [];
    if (st.map) qs.push('map=' + encodeURIComponent(st.map));
    st.enemy.forEach(function (h) { qs.push('enemy=' + encodeURIComponent(h)); });
    st.ally.forEach(function (h) { qs.push('ally=' + encodeURIComponent(h)); });
    fetch('/api/dossier?' + qs.join('&')).then(function (r) { return r.json(); })
      .then(function (d) {
        if (mine !== seq) return;      /* a newer click superseded this one */
        if (d.error) { el('status').textContent = ''; flash(d.error); return; }
        renderEv(d.lines);
        el('status').textContent = d.lines.length +
          ' evidence lines · rebuilt ' + new Date().toLocaleTimeString();
      })
      .catch(function () { flash('the database is not answering'); });
  }, 250);
}

var LINES = [];
function renderEv(lines) {
  LINES = lines;
  var f = el('evfilter').value.toLowerCase();
  var out = '';
  lines.forEach(function (l) {
    if (f && (l.tag + ' ' + l.table + ' ' + l.text).toLowerCase()
             .indexOf(f) < 0) return;
    var cls = l.table.indexOf('derived:') === 0 ? 'derived'
            : /^(WARNING|CAUTION)/.test(l.text) ? 'warn' : '';
    out += "<tr class='" + cls + "'><td class='tag'>[" + l.tag + ']</td><td>' +
           l.text.replace(/&/g, '&amp;').replace(/</g, '&lt;') +
           "</td><td class='sub'>" + l.table + '</td></tr>';
  });
  el('evbody').innerHTML =
    out || "<tr><td class='sub'>nothing matches the filter</td></tr>";
}

var lastRec = null;
function pollRecs() {
  fetch('/api/recs').then(function (r) { return r.json(); })
    .then(function (d) {
      if (lastRec !== null && d.latest > lastRec)
        el('newrec').innerHTML = 'the session just recorded ' +
          "<a href='/rec/" + d.latest + "'>recommendation #" + d.latest +
          '</a> - ' + d.summary,
        el('newrec').style.display = 'block';
      lastRec = d.latest;
    }).catch(function () {});
}

el('mapsel').onchange = function () { st.map = this.value; save(); refresh(); };
el('evfilter').oninput = function () { renderEv(LINES); };
el('clearbtn').onclick = function () {
  st = { map: '', enemy: [], ally: [] };
  save(); paint(); refresh();
};
paint(); refresh(); pollRecs(); setInterval(pollRecs, 8000);
"""


def view_live(cx):
    """Two hero-select screens - theirs in red, ours in blue - over one
    dossier: every click rebuilds the evidence both the board and the /comp
    skill read."""
    maps = [m for m, in q(cx, "select name from maps order by name")]
    roster = q(cx, """select h.name, r.code from heroes h
                      join roles r using(role_id)
                      order by r.role_id, h.name""")
    opts = "<option value=''>map unknown / any</option>" + "".join(
        "<option>%s</option>" % esc(m) for m in maps)

    def select_screen(team, title, sub):
        cols = "".join(
            "<div class='rolecol'><h4>%s</h4><div class='grid'>%s</div></div>"
            % (role, "".join(
                "<span class='tile' data-team='%s' data-h=\"%s\""
                " onclick=\"toggle('%s', this.getAttribute('data-h'))\">"
                "<span>%s</span></span>"
                % (team, esc(n), team, esc(n))
                for n, r in roster if r == role))
            for role in ("tank", "damage", "support"))
        return ("<div class='board %s'><h3>%s</h3>"
                "<div class='picked' id='%spicked'></div>"
                "<div class='roles'>%s</div>"
                "<div class='legend'>%s</div></div>"
                % ("enemy" if team == "enemy" else "mine", title,
                   "enemy" if team == "enemy" else "my", cols, sub))

    boards = (
        select_screen("enemy", "their team",
                      "click their heroes as the enemy reveals them") +
        select_screen("ally", "your team",
                      "click the picks you and your group are locked on"))
    data = ("var MAPS = %s;\nvar ROLE = %s;\n"
            % (json.dumps(maps), json.dumps({n: r for n, r in roster})))
    return page("live evidence board", """
        <div class='bar'>
          <select id='mapsel'>%s</select>
          <button class='ghost' id='clearbtn'>new game</button>
          <span class='status' id='status'></span>
        </div>
        %s
        <div class='legend'>the evidence below is exactly what the /comp
        skill reads - it rebuilds on every click, and the board survives a
        page reload.</div>
        <div class='newrec' id='newrec'></div>
        <div class='evwrap'>
          <div class='evtools'><h2 style='margin:0'>Evidence</h2>
            <input type='text' id='evfilter'
                   placeholder='filter - try derived:, CAUTION, a hero…'></div>
          <table class='ev'><tbody id='evbody'></tbody></table>
        </div>
        <script>%s%s</script>""" % (opts, boards, data, BOARD_JS))


def api_dossier(cx, query):
    """The dossier as JSON: the same lines the /comp skill reads."""
    map_name = (query.get("map") or [None])[0] or None
    enemies = [e for e in query.get("enemy", []) if e]
    allies = [a for a in query.get("ally", []) if a]
    try:
        ev, ctx = dossier.build(cx, map_name, enemies, allies)
    except ValueError as error:
        return json.dumps({"error": str(error)}), 400
    return json.dumps({
        "map": ctx["map_name"],
        "lines": [{"tag": t, "table": tb, "text": x}
                  for t, tb, x in ev.lines],
    }), 200


def api_recs(cx):
    """The newest recorded recommendation, for the board's live poll."""
    row = q(cx, """select r.rec_id, r.playstyle,
            (select string_agg(h.name, ', ' order by p.position)
             from recommendation_picks p join heroes h using(hero_id)
             where p.rec_id = r.rec_id)
            from recommendations r order by rec_id desc limit 1""")
    if not row:
        return json.dumps({"latest": 0, "summary": ""}), 200
    rec_id, playstyle, picks = row[0]
    return json.dumps({"latest": rec_id,
                       "summary": "%s (%s)" % (picks or "", playstyle)}), 200


def view_rec(cx, rec_id):
    rec = q(cx, """select request, coalesce(m.name,'-'), model, playstyle,
                   reasoning, created_at::date from recommendations r
                   left join maps m using(map_id) where rec_id=%s""", rec_id)
    if not rec:
        return page("not found", "<p>No recommendation #%d.</p>" % rec_id)
    request, map_name, model, playstyle, reasoning, day = rec[0]
    picks = q(cx, """select h.name, p.why,
        coalesce((select string_agg(e.tag, ', ' order by e.tag)
            from recommendation_evidence e
            where e.rec_id=p.rec_id and e.hero_id=p.hero_id), '')
        from recommendation_picks p join heroes h using(hero_id)
        where p.rec_id=%s order by p.position""", rec_id)
    cited = q(cx, """select distinct tag, source_table, description
                     from recommendation_evidence where rec_id=%s
                     order by length(tag), tag""", rec_id)
    picks_html = "".join(
        "<div class='pick'><b>%s</b><span class='badge'>%s</span><br>%s</div>"
        % (esc(h), esc(tags), esc(why)) for h, why, tags in picks)
    ev = "".join("<tr><td class='tag'>[%s]</td><td>%s</td>"
                 "<td class='sub'>%s</td></tr>"
                 % (esc(t), esc(d), esc(tb)) for t, tb, d in cited)
    return page("recommendation #%d" % rec_id, """
        <h2>Recommendation #%d - %s</h2>
        <p class='sub'>%s &nbsp;·&nbsp; map: %s &nbsp;·&nbsp; %s</p>
        <p>%s</p><h2>Comp - %s</h2>%s
        <h2>Evidence cited</h2><table class='ev'>%s</table>""" % (
        rec_id, day, esc(model), esc(map_name), esc(request),
        esc(reasoning), esc(playstyle), picks_html, ev))


# --- server -----------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            with psycopg.connect(dsn()) as cx:
                if path == "/":
                    return self._send(view_home(cx))
                if path == "/recommend":
                    return self._send(view_live(cx))
                if path == "/api/dossier":
                    body, code = api_dossier(cx, parse_qs(parsed.query))
                    return self._send(body, code, "application/json")
                if path == "/api/recs":
                    body, code = api_recs(cx)
                    return self._send(body, code, "application/json")
                if path.startswith("/rec/"):
                    return self._send(view_rec(cx, int(path[5:])))
            self._send(page("not found", "<p>Nothing here.</p>"), 404)
        except Exception:
            self._send(page("error", "<pre class='err'>%s</pre>"
                            % esc(traceback.format_exc())), 500)


def main():
    host = os.environ.get("OVERWATCH_DB_UI_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, PORT), Handler)
    print("overwatch-db ui: http://%s:%d" % (host, PORT))
    server.serve_forever()


if __name__ == "__main__":
    main()
