"""The USER LAYER's board: a map selector and a red and a blue roster,
organised and styled like the game's hero select, over the facts engine
and the inference layer.

    python -m user.board            # serves http://localhost:8017

Standard library only. Every click re-reads the database: the facts
panel is the FactSet for (map, red, blue), the optimal-comp panel is the
inference layer's answer around the locked blue picks (or the evaluation
of a full five), and the playbook panel is the heuristics catalog as it
sits on disk. JSON endpoints under /api/ serve the same three things.
"""

import html
import json
import os
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import psycopg

from data import common
from user.facts import engine as facts_engine
from user.facts import model
from inference import catalog as catalog_module
from inference import engine as inference_engine
from inference import record as record_module

PORT = int(os.environ.get("OVERWATCH_DB_UI_PORT", "8017"))

# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
INFERENCE_URL = os.environ.get("INFERENCE_URL", "").rstrip("/")


def dsn():
    return common.default_dsn()


def remote(path, query=None, payload=None):
    """Forward to the inference service -> (json, status)."""
    url = INFERENCE_URL + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode("utf-8")), error.code
        except ValueError:
            return {"error": "inference service returned %d" % error.code}, error.code
    except (urllib.error.URLError, OSError) as error:
        return {"error": "inference service unreachable: %s" % error}, 502


def esc(x):
    return html.escape(str(x if x is not None else ""))


# --- JSON endpoints ---------------------------------------------------------

def _board(query):
    map_name = (query.get("map") or [None])[0] or None
    red = [x for x in query.get("red", []) if x]
    blue = [x for x in query.get("blue", []) if x]
    return map_name, red, blue


def api_roster(cx):
    world = model.load(cx)
    heroes = [{"name": h.name, "slug": h.slug, "role": h.role, "subrole": h.subrole,
               "pool": h.pool, "portrait": h.portrait,
               "subrole_icon": (world.subrole_passives.get(h.subrole) or (None, None, None))[2]}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode, "style": m.style_top}
            for m in world.maps_sorted()]
    return {"heroes": heroes, "maps": maps, "role_icons": world.role_icons,
            "snapshots": world.snapshots, "newer_patches": world.newer_patches}


def api_facts(cx, query):
    map_name, red, blue = _board(query)
    world = model.load(cx)
    try:
        fs = facts_engine.generate(world, map_name, red, blue)
    except ValueError as error:
        return {"error": str(error)}, 400
    return fs.to_dict(), 200


def api_infer(cx, query):
    map_name, red, blue = _board(query)
    if INFERENCE_URL:
        return remote("/infer", {"map": map_name or "", "red": red, "blue": blue})
    world = model.load(cx)
    try:
        if len(blue) == 5:
            result = inference_engine.evaluate(world, map_name, red, blue)
        else:
            result = inference_engine.infer(world, map_name, red, blue)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def api_heuristics():
    if INFERENCE_URL:
        return remote("/heuristics")[0]
    catalog = catalog_module.load()
    return {"heuristics": [h.to_dict() for h in catalog]}


def api_recs(cx):
    row = cx.execute("""select r.rec_id, r.playstyle,
            (select string_agg(h.name, ', ' order by p.position)
             from recommendation_picks p join heroes h using(hero_id)
             where p.rec_id = r.rec_id)
            from recommendations r order by rec_id desc limit 1""").fetchone()
    if not row:
        return {"latest": 0, "summary": ""}
    rec_id, playstyle, picks = row
    return {"latest": rec_id, "summary": "%s (%s)" % (picks or "", playstyle)}


def api_record(cx, payload):
    if INFERENCE_URL:
        return remote("/record", payload=payload)
    try:
        rec_id, path = record_module.record(
            cx, payload.get("question") or "recorded from the board",
            payload["answer"], payload.get("map"), payload.get("red", []),
            payload.get("blue", []), payload.get("model", "board"))
    except (ValueError, KeyError) as error:
        return {"error": str(error)}, 400
    return {"rec_id": rec_id, "transcript": os.path.relpath(path, common.ROOT)}, 200


# --- the board page ---------------------------------------------------------

STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap');
:root { color-scheme: dark; --bg:#0d1017; --panel:#151a23; --panel2:#1b212c;
  --line:#2a3240; --text:#e9ecf1; --muted:#8d97a8; --red:#ff4b57; --red2:#a8232d;
  --blue:#3ea6ff; --blue2:#1f5fa8; --gold:#f5a623; --green:#5ad17a; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg) fixed; color:var(--text);
  font:14px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif;
  background-image: repeating-linear-gradient(115deg, transparent 0 46px,
    rgba(255,255,255,.018) 46px 48px); }
h1,h2,h3,.ow { font-family:"Bebas Neue",Impact,"Arial Narrow",sans-serif;
  letter-spacing:.06em; text-transform:uppercase; font-weight:400; }
a { color:var(--blue); text-decoration:none; } a:hover { text-decoration:underline; }
main { max-width:1440px; margin:0 auto; padding:14px 18px 60px; }
header.top { display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  padding:10px 16px; background:linear-gradient(90deg,#161c27,#10141c);
  border:1px solid var(--line); border-radius:10px; }
header.top h1 { margin:0; font-size:30px; }
header.top h1 span { color:var(--gold); }
header.top .sub { color:var(--muted); font-size:13px; }
.mapsel { margin-left:auto; display:flex; align-items:center; gap:10px; }
.mapsel select { background:#0b0e14; color:var(--text); border:1px solid var(--line);
  border-radius:6px; padding:9px 12px; font-family:"Bebas Neue",Impact,sans-serif;
  font-size:22px; letter-spacing:.06em; min-width:280px; }
.mode { font-family:"Bebas Neue",Impact,sans-serif; font-size:18px; letter-spacing:.1em;
  color:var(--gold); border:1px solid var(--gold); border-radius:4px; padding:3px 10px; }
button { background:#263041; color:#fff; border:1px solid #35435a; border-radius:6px;
  padding:8px 14px; font:inherit; cursor:pointer; }
button:hover { background:#31405a; }
button.primary { background:var(--blue2); border-color:var(--blue); }
.status { color:var(--muted); font-size:12px; min-width:160px; text-align:right; }

/* --- the two hero-select screens --------------------------------------- */
.teams { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px; }
@media (max-width:1100px) { .teams { grid-template-columns:1fr; } }
.team { border-radius:12px; border:1px solid var(--line); padding:12px 14px 10px;
  position:relative; overflow:hidden; }
.team.red { background:linear-gradient(170deg,#2b141a 0%,#151a23 55%); border-color:#5a2730; }
.team.blue { background:linear-gradient(170deg,#12233a 0%,#151a23 55%); border-color:#254a70; }
.team h2 { margin:0 0 6px; font-size:26px; display:flex; align-items:baseline; gap:10px; }
.team.red h2 { color:var(--red); } .team.blue h2 { color:var(--blue); }
.team h2 small { font:12px/1 -apple-system,"Segoe UI",sans-serif; letter-spacing:0;
  text-transform:none; color:var(--muted); }
.slots { display:flex; gap:8px; margin:4px 0 12px; }
.slot { flex:1; aspect-ratio:3/4; max-width:110px; border-radius:6px; position:relative;
  overflow:hidden; background:#0b0e14; border:2px dashed #3a4457; cursor:pointer;
  clip-path:polygon(9% 0,100% 0,91% 100%,0 100%); }
.slot.full { border-style:solid; }
.team.red .slot.full { border-color:var(--red); box-shadow:0 0 16px rgba(255,75,87,.35); }
.team.blue .slot.full { border-color:var(--blue); box-shadow:0 0 16px rgba(62,166,255,.35); }
.slot img { width:100%; height:100%; object-fit:cover; display:block; }
.slot .nm, .tile .nm { position:absolute; left:0; right:0; bottom:0; padding:3px 6px;
  font-family:"Bebas Neue",Impact,sans-serif; font-size:15px; letter-spacing:.08em;
  text-transform:uppercase; background:linear-gradient(transparent,rgba(0,0,0,.85));
  text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.slot .idx { position:absolute; top:4px; left:12px; color:var(--muted); font-size:11px; }
.roles { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.rolecol h4 { margin:0 0 6px; display:flex; align-items:center; justify-content:center;
  gap:6px; color:var(--muted); font-family:"Bebas Neue",Impact,sans-serif; font-size:16px;
  letter-spacing:.2em; border-bottom:1px solid var(--line); padding-bottom:4px; }
.rolecol h4 img { width:16px; height:16px; opacity:.8; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(64px,1fr)); gap:6px; }
.tile { position:relative; aspect-ratio:3/4; border-radius:5px; overflow:hidden;
  background:#0b0e14; border:2px solid #2a3240; cursor:pointer; user-select:none;
  transition:transform .08s,border-color .08s,box-shadow .08s; }
.tile img { width:100%; height:100%; object-fit:cover; display:block; opacity:.92; }
.tile .nm { font-size:11px; padding:2px 3px; }
.tile:hover { transform:scale(1.06); z-index:2; border-color:#8892a6; }
.team.red .tile.on { border-color:var(--red); box-shadow:0 0 12px rgba(255,75,87,.55); }
.team.blue .tile.on { border-color:var(--blue); box-shadow:0 0 12px rgba(62,166,255,.55); }
.tile.on img { opacity:1; }
.tile.other::after { content:""; position:absolute; top:4px; right:4px; width:8px;
  height:8px; border-radius:50%; }
.team.red .tile.other::after { background:var(--blue); }
.team.blue .tile.other::after { background:var(--red); }
.tile .ph, .slot .ph { position:absolute; inset:0; display:flex; align-items:center;
  justify-content:center; font-family:"Bebas Neue",Impact,sans-serif; font-size:26px;
  color:#5b6577; }

/* --- the panels -------------------------------------------------------- */
nav.tabs { display:flex; gap:6px; margin:18px 0 0; }
nav.tabs button { font-family:"Bebas Neue",Impact,sans-serif; font-size:19px;
  letter-spacing:.08em; padding:9px 18px; border-radius:8px 8px 0 0; background:#141922;
  border-bottom:0; }
nav.tabs button.active { background:var(--panel2); color:var(--gold); border-color:var(--gold); }
.panel { display:none; background:var(--panel2); border:1px solid var(--line);
  border-radius:0 10px 10px 10px; padding:14px 16px; }
.panel.active { display:block; }
.tools { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
.tools input { flex:1; min-width:240px; background:#0b0e14; color:var(--text);
  border:1px solid var(--line); border-radius:6px; padding:8px 10px; font:inherit; }
.chip { border:1px solid var(--line); border-radius:99px; padding:3px 11px; font-size:12px;
  cursor:pointer; color:var(--muted); background:transparent; }
.chip.on { color:#fff; border-color:var(--gold); background:#2a2416; }
table.facts { width:100%; border-collapse:collapse; font-family:ui-monospace,SFMono-Regular,
  Menlo,monospace; font-size:12.5px; }
table.facts td { padding:3px 8px 3px 0; border-bottom:1px solid #202733; vertical-align:top; }
table.facts td.tag { color:var(--gold); white-space:nowrap; width:56px; }
table.facts td.src { color:#5f6a7c; white-space:nowrap; font-size:11px; }
table.facts tr.h td.head { font-family:"Bebas Neue",Impact,sans-serif; font-size:17px;
  letter-spacing:.12em; color:#c8cfdb; padding-top:14px; border-bottom:1px solid var(--line); }
table.facts tr.red td.tag { color:var(--red); } table.facts tr.blue td.tag { color:var(--blue); }
table.facts tr.warn td { color:#ff9d8f; } table.facts tr.derived td.text { color:#ffd67a; }
.inf-head { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
.inf-head h3 { margin:0; font-size:24px; color:var(--gold); }
.inf-head .score { font-family:"Bebas Neue",Impact,sans-serif; font-size:24px; }
.comp { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin:12px 0; }
@media (max-width:900px) { .comp { grid-template-columns:repeat(2,1fr); } }
.card { background:#10141c; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.card .pic { aspect-ratio:3/4; position:relative; background:#0b0e14;
  border-bottom:2px solid var(--blue); }
.card .pic img { width:100%; height:100%; object-fit:cover; display:block; }
.card .pic .role { position:absolute; top:6px; left:6px; font-size:10px; letter-spacing:.14em;
  text-transform:uppercase; background:rgba(0,0,0,.6); padding:2px 6px; border-radius:3px; }
.card .pic .lock { position:absolute; top:6px; right:6px; color:var(--gold); font-size:11px; }
.card .body { padding:8px 10px 10px; }
.card .body b { font-family:"Bebas Neue",Impact,sans-serif; font-size:19px; letter-spacing:.06em; }
.card .why { color:#c9d0db; font-size:12.5px; margin:4px 0 6px; }
.ev { display:inline-block; background:#1d2430; color:var(--gold); border-radius:3px;
  padding:0 5px; font-size:11px; margin:1px 3px 1px 0; font-family:ui-monospace,monospace;
  cursor:help; }
.bars { display:grid; grid-template-columns:1fr 1fr; gap:4px 22px; margin-top:10px; }
@media (max-width:900px) { .bars { grid-template-columns:1fr; } }
.bar { display:grid; grid-template-columns:150px 1fr 54px; align-items:center; gap:8px;
  font-size:12px; }
.bar .lbl { color:#c9d0db; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar .trk { height:9px; background:#0b0e14; border-radius:4px; overflow:hidden; position:relative; }
.bar .fill { height:100%; background:var(--green); }
.bar.neg .fill { background:var(--red); } .bar.off { opacity:.4; }
.bar .val { text-align:right; font-family:ui-monospace,monospace; color:var(--muted); }
.alts { margin-top:12px; color:#c9d0db; font-size:13px; }
.alts li { margin:3px 0; }
.notice { background:#12301f; border:1px solid #2e6b45; border-radius:8px; padding:8px 12px;
  margin:10px 0; display:none; }
.warnbox { background:#3a2026; border:1px solid #6b2f3a; border-radius:8px; padding:8px 12px;
  margin:10px 0; }
.hcards { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:10px; }
.hcard { background:#10141c; border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.hcard .kind { display:inline-block; font-size:10px; letter-spacing:.14em; text-transform:uppercase;
  padding:2px 7px; border-radius:3px; margin-right:6px; }
.kind.goal { background:#1d3a2a; color:var(--green); } .kind.constraint { background:#3a1d22; color:var(--red); }
.kind.strategy { background:#1d2a3a; color:var(--blue); }
.hcard b { font-family:"Bebas Neue",Impact,sans-serif; font-size:18px; letter-spacing:.05em; }
.hcard .meta { font-family:ui-monospace,monospace; font-size:11.5px; color:var(--muted); margin:4px 0; }
.hcard p { margin:6px 0 0; color:#c9d0db; font-size:12.5px; }
.legend { color:var(--muted); font-size:12px; margin:6px 0 0; }
.rec-list td { padding:4px 10px 4px 0; border-bottom:1px solid #202733; }
"""

SCRIPT = r"""
var el = function (id) { return document.getElementById(id); };
var ROSTER = null, st = { map: '', red: [], blue: [] };
try { var saved = JSON.parse(localStorage.getItem('owdb-board2'));
      if (saved && saved.red && saved.blue) st = saved; } catch (e) {}

function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }
function save() { try { localStorage.setItem('owdb-board2', JSON.stringify(st)); } catch (e) {} }
function hero(name) { return ROSTER.byName[name]; }
function portrait(h, cls) {
  var initials = h.name.split(/[\s:.]+/).map(function (w) { return w[0]; }).join('').slice(0, 2);
  return h.portrait
    ? "<img src='" + esc(h.portrait) + "' alt='' loading='lazy' onerror=\"this.style.display='none';this.nextSibling.style.display='flex'\"><span class='ph' style='display:none'>" + esc(initials) + '</span>'
    : "<span class='ph'>" + esc(initials) + '</span>';
}

function buildTeam(team) {
  var slots = '';
  for (var i = 0; i < 5; i++) slots += "<div class='slot' data-team='" + team + "' data-i='" + i + "'></div>";
  el(team + 'slots').innerHTML = slots;
  var cols = '';
  ['tank', 'damage', 'support'].forEach(function (role) {
    var icon = ROSTER.role_icons[role] ? "<img src='" + esc(ROSTER.role_icons[role]) + "' alt=''>" : '';
    cols += "<div class='rolecol'><h4>" + icon + role + "</h4><div class='grid'>";
    ROSTER.heroes.filter(function (h) { return h.role === role; }).forEach(function (h) {
      cols += "<div class='tile' data-team='" + team + "' data-h=\"" + esc(h.name) + "\" title=\"" + esc(h.name + ' - ' + h.subrole) + "\">" + portrait(h) + "<span class='nm'>" + esc(h.name) + '</span></div>';
    });
    cols += '</div></div>';
  });
  el(team + 'roster').innerHTML = cols;
}

function toggle(team, name) {
  var arr = st[team], at = arr.indexOf(name);
  if (at >= 0) arr.splice(at, 1);
  else if (arr.length < 5) arr.push(name);
  else { flash((team === 'red' ? 'red' : 'blue') + ' already has five - click a lit hero to free the slot'); return; }
  save(); paint(); refresh();
}

function paint() {
  ['red', 'blue'].forEach(function (team) {
    var other = team === 'red' ? 'blue' : 'red';
    var slots = el(team + 'slots').children;
    for (var i = 0; i < 5; i++) {
      var name = st[team][i], s = slots[i];
      if (name) { var h = hero(name); s.className = 'slot full'; s.setAttribute('data-h', name);
        s.innerHTML = portrait(h) + "<span class='nm'>" + esc(name) + '</span>'; }
      else { s.className = 'slot'; s.removeAttribute('data-h'); s.innerHTML = "<span class='idx'>" + (i + 1) + '</span>'; }
    }
    var tiles = el(team + 'roster').querySelectorAll('.tile');
    for (var t = 0; t < tiles.length; t++) {
      var n = tiles[t].getAttribute('data-h');
      tiles[t].className = 'tile' + (st[team].indexOf(n) >= 0 ? ' on' : '') + (st[other].indexOf(n) >= 0 ? ' other' : '');
    }
    el(team + 'count').textContent = st[team].length + '/5';
  });
  el('mapsel').value = st.map;
  var m = ROSTER.maps.filter(function (x) { return x.name === st.map; })[0];
  el('mode').textContent = m ? m.mode + (m.style ? ' · rewards ' + m.style : '') : 'map unknown';
}

document.addEventListener('click', function (e) {
  var hit = e.target.closest ? e.target.closest('[data-h][data-team]') : null;
  if (hit) toggle(hit.getAttribute('data-team'), hit.getAttribute('data-h'));
  var tab = e.target.closest ? e.target.closest('nav.tabs button') : null;
  if (tab) showTab(tab.getAttribute('data-tab'));
});

var flashTimer = null;
function flash(msg) { el('status').textContent = msg; clearTimeout(flashTimer);
  flashTimer = setTimeout(function () { el('status').textContent = ''; }, 3000); }

function qs() {
  var q = [];
  if (st.map) q.push('map=' + encodeURIComponent(st.map));
  st.red.forEach(function (h) { q.push('red=' + encodeURIComponent(h)); });
  st.blue.forEach(function (h) { q.push('blue=' + encodeURIComponent(h)); });
  return q.join('&');
}

var pending = null, seq = 0, FACTS = null, INF = null;
function refresh() {
  clearTimeout(pending);
  el('status').textContent = 'reading the database…';
  pending = setTimeout(function () {
    var mine = ++seq, q = qs();
    fetch('/api/facts?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      if (d.error) { flash(d.error); return; }
      FACTS = d; renderFacts(); el('factsn').textContent = d.count;
      el('status').textContent = d.count + ' facts · ' + new Date().toLocaleTimeString();
    }).catch(function () { flash('the database is not answering'); });
    el('inf').innerHTML = "<p class='legend'>searching compositions…</p>";
    fetch('/api/infer?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      INF = d; renderInf();
    }).catch(function () { el('inf').innerHTML = "<p class='legend'>inference is not answering</p>"; });
  }, 200);
}

var SCOPES = ['meta', 'map', 'hero', 'team', 'matchup', 'playbook'];
var scopeOn = { meta: true, map: true, hero: true, team: true, matchup: true, playbook: true };
function renderFacts() {
  if (!FACTS) return;
  var f = el('filter').value.toLowerCase(), out = '', last = null;
  FACTS.facts.forEach(function (x) {
    if (!scopeOn[x.scope]) return;
    if (f && (x.id + ' ' + x.key + ' ' + x.subject + ' ' + x.text).toLowerCase().indexOf(f) < 0) return;
    var head = x.scope === 'hero' ? (x.team + ' · ' + x.subject) : x.scope === 'team' ? (x.subject + ' team') : x.scope;
    if (head !== last) { out += "<tr class='h'><td colspan='3' class='head'>" + esc(head) + '</td></tr>'; last = head; }
    var cls = (x.team || '') + (/^(WARNING|CAUTION)/.test(x.text) ? ' warn' : '') + (x.source.indexOf('derived:') === 0 ? ' derived' : '');
    out += "<tr class='" + cls + "'><td class='tag'>[" + x.id + "]</td><td class='text'>" + esc(x.text) + "</td><td class='src'>" + esc(x.source) + '</td></tr>';
  });
  el('factbody').innerHTML = out || "<tr><td class='src'>nothing matches</td></tr>";
}

function bars(contribs) {
  var mx = 0.01;
  contribs.forEach(function (c) { mx = Math.max(mx, Math.abs(c.weighted || 0)); });
  var out = "<div class='bars'>";
  contribs.forEach(function (c) {
    var w = Math.abs(c.weighted || 0) / mx * 100;
    var detail = c.kind === 'goal' ? (c.applies ? c.metric + ' = ' + (typeof c.raw === 'number' ? +c.raw.toFixed(2) : c.raw) + ' · norm ' + (+c.norm).toFixed(2) : 'not applicable here')
               : c.kind === 'strategy' ? (c.applies ? 'bonus ' + c.bonus + ' − penalty ' + c.penalty : 'condition not met')
               : (c.ok ? 'satisfied' : 'VIOLATED');
    out += "<div class='bar" + ((c.weighted || 0) < 0 ? ' neg' : '') + (c.applies === false ? ' off' : '') + "' title=\"" + esc(detail + (c.text ? ' — ' + c.text : '')) + "\"><span class='lbl'>" + esc(c.id) + (c.fact ? " <span class='ev'>" + c.fact + '</span>' : '') + "</span><span class='trk'><span class='fill' style='width:" + w.toFixed(1) + "%'></span></span><span class='val'>" + ((c.weighted || 0) >= 0 ? '+' : '') + (+(c.weighted || 0)).toFixed(2) + '</span></div>';
  });
  return out + '</div>';
}

function renderInf() {
  var d = INF;
  if (!d || d.error) { el('inf').innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; return; }
  var title = d.kind === 'infer' ? 'optimal comp' : 'your five, evaluated';
  var out = "<div class='inf-head'><h3>" + title + "</h3><span class='score'>score " + (+d.score).toFixed(2) + "</span><span class='legend'>" +
    (d.rank ? 'rank ' + d.rank + ' among the feasible field · ' : '') + d.considered + ' candidates · ' + d.seconds + 's · ' +
    d.heuristics.constraint + ' constraints, ' + d.heuristics.goal + ' goals, ' + d.heuristics.strategy + ' strategies' +
    (d.playstyle ? ' · leans ' + d.playstyle : '') + '</span>' +
    (d.kind === 'infer' ? "<button class='primary' id='recbtn'>record this comp</button>" : '') + '</div>';
  if (d.violations && d.violations.length) out += "<div class='warnbox'>violates: " + esc(d.violations.join(', ')) + '</div>';
  out += "<div class='comp'>";
  d.picks.forEach(function (p) {
    var h = hero(p.hero) || { name: p.hero, portrait: p.portrait };
    out += "<div class='card'><div class='pic'>" + portrait(h) + "<span class='role'>" + esc(p.role) + '</span>' + (p.locked ? "<span class='lock'>LOCKED</span>" : '') +
      "</div><div class='body'><b>" + esc(p.hero) + "</b><div class='why'>" + esc(p.why) + '</div>' +
      p.evidence.map(function (id) { return "<span class='ev' title=\"" + esc(d.cited[id] || id) + "\">" + id + '</span>'; }).join('') + '</div></div>';
  });
  out += '</div>' + bars(d.contributions);
  if (d.alternatives && d.alternatives.length) {
    out += "<div class='alts'><b>" + (d.kind === 'infer' ? 'alternatives' : 'the field’s best') + "</b><ol>" +
      d.alternatives.map(function (a) { return '<li>' + esc(a.blue.join(', ')) + " <span class='legend'>(" + (+a.score).toFixed(2) + ')</span></li>'; }).join('') + '</ol></div>';
  }
  out += "<div class='notice' id='recnote'></div>";
  el('inf').innerHTML = out;
  var btn = el('recbtn');
  if (btn) btn.onclick = function () { recordComp(d); };
}

function recordComp(d) {
  var answer = { playstyle: d.playstyle || 'balanced', reasoning: 'solver optimum under the catalog: score ' + (+d.score).toFixed(2) + ' over ' + d.considered + ' candidates',
    picks: d.picks.map(function (p) { return { hero: p.hero, why: p.why, evidence: p.evidence }; }) };
  fetch('/api/record', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'board: ' + (st.map || 'any map') + ' vs ' + st.red.join(', '), map: st.map || null, red: st.red, blue: st.blue, model: 'inference-engine', answer: answer }) })
    .then(function (r) { return r.json(); }).then(function (r) {
      var n = el('recnote'); n.style.display = 'block';
      n.innerHTML = r.error ? 'refused: ' + esc(r.error) : 'recorded as <a href="/rec/' + r.rec_id + '">recommendation #' + r.rec_id + '</a> - ' + esc(r.transcript);
    });
}

function renderPlaybook(d) {
  var out = "<div class='hcards'>";
  d.heuristics.forEach(function (h) {
    var meta = h.kind === 'goal' ? h.direction + ' ' + h.metric + ' · weight ' + h.weight
             : h.kind === 'constraint' ? 'require ' + h.require + (h.soft ? ' · soft, penalty ' + h.penalty : ' · hard') + (h.when ? ' · when ' + h.when : '')
             : (h.bonus || h.penalty) ? [h.when ? 'when ' + h.when : '', h.bonus ? 'bonus ' + h.bonus : '', h.penalty ? 'penalty ' + h.penalty : ''].filter(Boolean).join(' · ') + ' · weight ' + h.weight
             : 'prose - read by the session, shown here, not scored';
    var params = Object.keys(h.params || {}).map(function (k) { return k + '=' + h.params[k]; }).join(', ');
    var body = h.body.replace(/^#[^\n]*\n/, '').split(/\n\s*\n/).map(function (p) { return '<p>' + esc(p.replace(/\s+/g, ' ')) + '</p>'; }).join('');
    out += "<div class='hcard'><span class='kind " + h.kind + "'>" + h.kind + '</span><b>' + esc(h.name) + "</b><div class='meta'>" + esc(meta) + (params ? ' · params ' + esc(params) : '') + '</div>' + body +
      "<div class='legend'>inference/heuristics/" + esc(h.id) + '.md · ' + esc(h.category) + '</div></div>';
  });
  el('playbook').innerHTML = out + '</div>';
}

function showTab(name) {
  document.querySelectorAll('nav.tabs button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === name); });
  document.querySelectorAll('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'tab-' + name); });
  try { localStorage.setItem('owdb-tab', name); } catch (e) {}
}

var lastRec = null;
function pollRecs() {
  fetch('/api/recs').then(function (r) { return r.json(); }).then(function (d) {
    if (lastRec !== null && d.latest > lastRec) { var n = el('newrec'); n.style.display = 'block';
      n.innerHTML = 'the session just recorded <a href="/rec/' + d.latest + '">recommendation #' + d.latest + '</a> - ' + esc(d.summary); }
    lastRec = d.latest;
  }).catch(function () {});
}

fetch('/api/roster').then(function (r) { return r.json(); }).then(function (d) {
  ROSTER = d; ROSTER.byName = {};
  d.heroes.forEach(function (h) { ROSTER.byName[h.name] = h; });
  el('mapsel').innerHTML = "<option value=''>MAP UNKNOWN / ANY</option>" + d.maps.map(function (m) { return "<option value=\"" + esc(m.name) + "\">" + esc(m.name) + '</option>'; }).join('');
  st.red = st.red.filter(function (h) { return ROSTER.byName[h]; });
  st.blue = st.blue.filter(function (h) { return ROSTER.byName[h]; });
  if (!d.maps.some(function (m) { return m.name === st.map; })) st.map = '';
  buildTeam('red'); buildTeam('blue'); paint();
  var blz = (d.snapshots || []).filter(function (s) { return s.source === 'blizzard'; })[0];
  if (blz) el('captured').textContent = 'rates captured ' + blz.captured + ' (' + (blz.patch || 'unknown patch') + ')';
  if (d.newer_patches && d.newer_patches.length) { var w = el('vintage'); w.style.display = 'block';
    w.textContent = d.newer_patches.length + ' patch(es) shipped since the rates were captured (newest ' + d.newer_patches[0][0] + ') - rates are pre-patch; run pull_rates'; }
  el('mapsel').onchange = function () { st.map = this.value; save(); paint(); refresh(); };
  el('filter').oninput = renderFacts;
  el('clearbtn').onclick = function () { st = { map: '', red: [], blue: [] }; save(); paint(); refresh(); };
  el('swapbtn').onclick = function () { var r = st.red; st.red = st.blue; st.blue = r; save(); paint(); refresh(); };
  var chips = el('chips'); chips.innerHTML = SCOPES.map(function (s) { return "<button class='chip on' data-scope='" + s + "'>" + s + '</button>'; }).join('');
  chips.onclick = function (e) { var c = e.target.closest('.chip'); if (!c) return; var s = c.getAttribute('data-scope');
    scopeOn[s] = !scopeOn[s]; c.classList.toggle('on', scopeOn[s]); renderFacts(); };
  fetch('/api/heuristics').then(function (r) { return r.json(); }).then(renderPlaybook);
  showTab((function () { try { return localStorage.getItem('owdb-tab') || 'facts'; } catch (e) { return 'facts'; } })());
  refresh(); pollRecs(); setInterval(pollRecs, 8000);
});
"""


def view_board():
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>overwatch-db board</title><style>" + STYLE + "</style><main>"
            "<header class='top'><h1>overwatch<span>-db</span></h1>"
            "<span class='sub'>COMP = ARGMAX[ STRATEGIES( FACTS ) ] &nbsp;·&nbsp; "
            "<a href='/recs'>recorded comps</a> &nbsp;·&nbsp; <span id='captured'></span></span>"
            "<div class='mapsel'><select id='mapsel'></select><span class='mode' id='mode'></span>"
            "<button id='swapbtn' title='swap red and blue'>swap sides</button>"
            "<button id='clearbtn'>new game</button><span class='status' id='status'></span></div>"
            "</header>"
            "<div class='warnbox' id='vintage' style='display:none'></div>"
            "<div class='notice' id='newrec'></div>"
            "<div class='teams'>"
            "<section class='team red'><h2>red team <small>the enemy - click their heroes as they reveal</small>"
            "<small style='margin-left:auto' id='redcount'></small></h2>"
            "<div class='slots' id='redslots'></div><div class='roles' id='redroster'></div></section>"
            "<section class='team blue'><h2>blue team <small>your locked picks - the inference layer fills the rest</small>"
            "<small style='margin-left:auto' id='bluecount'></small></h2>"
            "<div class='slots' id='blueslots'></div><div class='roles' id='blueroster'></div></section>"
            "</div>"
            "<nav class='tabs'><button data-tab='facts'>facts <span id='factsn'></span></button>"
            "<button data-tab='inf'>optimal comp</button><button data-tab='playbook'>playbook</button></nav>"
            "<section class='panel' id='tab-facts'><div class='tools'>"
            "<input type='text' id='filter' placeholder='filter facts - try a hero, CAUTION, derived:, team.'>"
            "<span id='chips'></span></div>"
            "<table class='facts'><tbody id='factbody'></tbody></table>"
            "<p class='legend'>every line is a row or a formula over the database, numbered for citation;"
            " the /comp skill and the inference layer read exactly these.</p></section>"
            "<section class='panel' id='tab-inf'><div id='inf'></div></section>"
            "<section class='panel' id='tab-playbook'><div id='playbook'></div></section>"
            "</main><script>" + SCRIPT + "</script>")


# --- recorded recommendations -------------------------------------------------

def _page(title, body):
    return ("<!doctype html><meta charset='utf-8'><title>%s</title><style>%s</style>"
            "<main><header class='top'><h1><a href='/'>overwatch<span>-db</span></a></h1>"
            "<span class='sub'>%s</span></header>%s</main>" % (esc(title), STYLE, esc(title), body))


def view_recs(cx):
    rows = cx.execute("""select rec_id, created_at::date, request, playstyle, model
                         from recommendations order by rec_id desc limit 50""").fetchall()
    body = "".join("<tr><td><a href='/rec/%d'>#%d</a></td><td>%s</td><td>%s</td><td>%s</td>"
                   "<td>%s</td></tr>" % (r, r, d, esc(q[:80]), esc(p), esc(m))
                   for r, d, q, p, m in rows) or "<tr><td>none yet</td></tr>"
    return _page("recorded compositions", "<table class='rec-list'><tr><th>id</th><th>date</th>"
                 "<th>question</th><th>comp</th><th>model</th></tr>%s</table>" % body)


def view_rec(cx, rec_id):
    rec = cx.execute("""select request, coalesce(m.name,'-'), model, playstyle,
                   reasoning, created_at::date from recommendations r
                   left join maps m using(map_id) where rec_id=%s""", (rec_id,)).fetchone()
    if not rec:
        return _page("not found", "<p>No recommendation #%d.</p>" % rec_id)
    request, map_name, model_name, playstyle, reasoning, day = rec
    picks = cx.execute("""select h.name, p.why,
        coalesce((select string_agg(e.tag, ', ' order by length(e.tag), e.tag)
            from recommendation_evidence e
            where e.rec_id=p.rec_id and e.hero_id=p.hero_id), '')
        from recommendation_picks p join heroes h using(hero_id)
        where p.rec_id=%s order by p.position""", (rec_id,)).fetchall()
    cited = cx.execute("""select distinct tag, source_table, description
                     from recommendation_evidence where rec_id=%s
                     order by length(tag), tag""", (rec_id,)).fetchall()
    picks_html = "".join(
        "<div class='hcard'><b>%s</b> <span class='ev'>%s</span><p>%s</p></div>"
        % (esc(h), esc(tags), esc(why)) for h, why, tags in picks)
    ev = "".join("<tr><td class='tag'>[%s]</td><td class='text'>%s</td><td class='src'>%s</td></tr>"
                 % (esc(t), esc(d), esc(tb)) for t, tb, d in cited)
    return _page("recommendation #%d" % rec_id, """
        <h2>Recommendation #%d - %s</h2>
        <p class='legend'>%s &nbsp;·&nbsp; map: %s &nbsp;·&nbsp; %s</p>
        <p>%s</p><h3>Comp - %s</h3><div class='hcards'>%s</div>
        <h3>Facts cited</h3><table class='facts'>%s</table>""" % (
        rec_id, day, esc(model_name), esc(map_name), esc(request),
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

    def _json(self, payload, code=200):
        self._send(json.dumps(payload, ensure_ascii=False), code, "application/json")

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                return self._send(view_board())
            if path == "/api/heuristics":
                return self._json(api_heuristics())
            with psycopg.connect(dsn()) as cx:
                if path == "/api/roster":
                    return self._json(api_roster(cx))
                if path == "/api/facts":
                    return self._json(*api_facts(cx, query))
                if path == "/api/infer":
                    return self._json(*api_infer(cx, query))
                if path == "/api/recs":
                    return self._json(api_recs(cx))
                if path == "/recs":
                    return self._send(view_recs(cx))
                if path.startswith("/rec/"):
                    return self._send(view_rec(cx, int(path[5:])))
            self._send(_page("not found", "<p>Nothing here.</p>"), 404)
        except Exception:
            self._send(_page("error", "<pre class='warnbox'>%s</pre>"
                             % esc(traceback.format_exc())), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/record":
                with psycopg.connect(dsn()) as cx:
                    return self._json(*api_record(cx, payload))
            self._json({"error": "nothing here"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("OVERWATCH_DB_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("overwatch-db board: http://%s:%d" % (args.host, args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
