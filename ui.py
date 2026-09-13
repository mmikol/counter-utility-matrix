"""A local UI over the built database: dashboard, evidence explorer, and
recorded-recommendation viewer.

    python ui.py            # serves http://localhost:8017

Standard library only - no framework, no new dependencies. Reads the same
database every other entry point does (db/cluster by default; DATABASE_URL
overrides - ./docker-db points it at the compose database). The chat that
actually decides comps lives in a Claude Code session via the /comp skill;
this UI is the free window onto the same evidence and the same records.
"""

import html
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
main { max-width: 980px; margin: 0 auto; padding: 24px 20px 60px; }
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
form { background: #1c2027; border: 1px solid #2a303a; border-radius: 8px;
       padding: 16px; }
label { display: block; margin: 10px 0 4px; color: #9aa3b0; font-size: 13px; }
input[type=text], select, textarea { width: 100%; background: #14161a;
    color: #d7dae0; border: 1px solid #2a303a; border-radius: 6px;
    padding: 8px 10px; font: inherit; }
textarea { min-height: 70px; }
button { margin-top: 14px; margin-right: 8px; background: #2f6feb; color: white;
         border: 0; border-radius: 6px; padding: 9px 16px; font: inherit;
         cursor: pointer; }
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
"""


def page(title, body):
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style><main>"
            "<h1><a href='/'>overwatch-db</a></h1>"
            "<p class='sub'>COUNTER = MAX[ HEROES ∩ MAPS ∩ META ]"
            " &nbsp;·&nbsp; <a href='/recommend'>explore evidence</a> &nbsp;·&nbsp; comps: /comp in a Claude Code session</p>"
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
                             'comp_archetypes','map_playstyle') then 'PLAYBOOK'
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
                  "map_meta", "counters", "synergies", "strategies",
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


def form(cx, values=None, error=None, evidence=None):
    v = values or {}
    maps = [m for m, in q(cx, "select name from maps order by name")]
    heroes = [h for h, in q(cx, "select name from heroes order by name")]
    opts = "<option value=''>any / unknown</option>" + "".join(
        "<option %s>%s</option>" % ("selected" if v.get("map") == m else "",
                                    esc(m)) for m in maps)
    err = "<div class='err'>%s</div>" % esc(error) if error else ""
    ev_html = ""
    if evidence is not None:
        ev_html = ("<h2>Evidence preview - %d lines the model would see</h2>"
                   "<table class='ev'>" % len(evidence.lines) + "".join(
                       "<tr><td class='tag'>[%s]</td><td>%s</td><td class='sub'>%s</td></tr>"
                       % (t, esc(x), esc(tb)) for t, tb, x in evidence.lines)
                   + "</table>")
    return page("explore evidence", """
        %s<form method='post' action='/recommend'>
        <label>Map</label><select name='map'>%s</select>
        <label>Known enemy heroes (comma separated)</label>
        <input type='text' name='enemies' list='roster' value='%s'
               placeholder='Zarya, Mei'>
        <datalist id='roster'>%s</datalist>
        <button name='do' value='preview'>Show the evidence</button>
        <span class='badge'>for a decided comp: /comp in a Claude Code
        session reads these same lines</span></form>%s""" % (
        err, opts, esc(v.get("enemies", "")),
        "".join("<option>%s</option>" % esc(h) for h in heroes), ev_html))


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
    def _send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            with psycopg.connect(dsn()) as cx:
                if path == "/":
                    return self._send(view_home(cx))
                if path == "/recommend":
                    return self._send(form(cx))
                if path.startswith("/rec/"):
                    return self._send(view_rec(cx, int(path[5:])))
            self._send(page("not found", "<p>Nothing here.</p>"), 404)
        except Exception:
            self._send(page("error", "<pre class='err'>%s</pre>"
                            % esc(traceback.format_exc())), 500)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        v = {k: vals[0].strip() for k, vals in fields.items()}
        map_name = v.get("map") or None
        enemies = [e.strip() for e in v.get("enemies", "").split(",")
                   if e.strip()]
        try:
            with psycopg.connect(dsn()) as cx:
                ev, _ = dossier.build(cx, map_name, enemies)
                self._send(form(cx, v, evidence=ev))
        except ValueError as error:
            with psycopg.connect(dsn()) as cx:
                self._send(form(cx, v, error=str(error)))


def main():
    host = os.environ.get("OVERWATCH_DB_UI_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, PORT), Handler)
    print("overwatch-db ui: http://%s:%d" % (host, PORT))
    server.serve_forever()


if __name__ == "__main__":
    main()
