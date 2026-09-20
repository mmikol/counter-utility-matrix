import json
import psycopg
from db import psql
from ui.facts import model
from inference import reach
cx=psycopg.connect(psql.default_dsn()); w=model.load(cx)
out, un = [], []
for h in sorted((x for x in w.heroes.values() if x.released), key=lambda x: x.name):
    r = reach.search(w, h.name)
    if r["bans"] is None: un.append((h.name, round(r["gap"],3)))
    else: out.append(r)
json.dump(out, open("tests/fixtures/reach.json","w"), indent=1)
print("SEATED %d | UNSEATED %s | needing bans %d" % (len(out), un, sum(1 for b in out if b["bans"])))
