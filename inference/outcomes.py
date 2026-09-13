"""Recording what happened: the match after the recommendation.

    record_outcome(cx, "win", map_name="King's Row", side="attack",
                   blue=[...six...], red=[...], bans=[...], rec_id=21,
                   note="won the first fight every round")

One row in `outcomes`, the picks and bans in `outcome_picks`. Gates: a
real result, real heroes, six blue picks (red may be partial - you do not
always see all of them), no banned pick, an existing recommendation when
rec_id is given. Does not commit: the caller owns the transaction (the
tool commits and re-exports the mirror; a test rolls back).
"""


from data import db
from data.authored import AUTHORED
from ui.facts import model
from ui.facts.compute import TEAM_SIZE

RESULTS = ("win", "loss", "draw")


def record_outcome(cx, result, map_name=None, side="", blue=(), red=(), bans=(),
                   rec_id=None, note=None):
    """-> outcome_id (uncommitted). Raises ValueError on anything the gates refuse."""
    if result not in RESULTS:
        raise ValueError("result must be one of %s" % "/".join(RESULTS))
    if side not in ("", "attack", "defense"):
        raise ValueError("side must be attack, defense or empty")
    world = model.load(cx)
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    if len(blue_h) != TEAM_SIZE:
        raise ValueError("an outcome needs blue's full %d picks (got %d)"
                         % (TEAM_SIZE, len(blue_h)))
    if len(red_h) > TEAM_SIZE:
        raise ValueError("more than %d red picks" % TEAM_SIZE)
    cursor = cx.cursor()
    if rec_id is not None and not cursor.execute(
            "select 1 from recommendations where rec_id = %s", (rec_id,)).fetchone():
        raise ValueError("no recommendation #%s to link" % rec_id)
    source_id = db.register_source(cursor, AUTHORED, db.now())
    cursor.execute(
        "insert into outcomes (rec_id, map_id, side, result, note, source_id)"
        " values (%s, %s, %s, %s, %s, %s) returning outcome_id",
        (rec_id, m.id if m else None, side or None, result, note or None, source_id))
    outcome_id = cursor.fetchone()[0]
    for team, heroes in (("blue", blue_h), ("red", red_h), ("ban", bans_h)):
        for position, h in enumerate(heroes, start=1):
            cursor.execute(
                "insert into outcome_picks (outcome_id, team, position, hero_id,"
                " source_id) values (%s, %s, %s, %s, %s)",
                (outcome_id, team, position, h.id, source_id))
    return outcome_id


def commit_and_mirror(cx):
    """What every real recording does after the gates: commit, then keep
    the data/raw mirror (the rebuild's backup) in step."""
    cx.commit()
    db.export(cx)


def summary(cx):
    """Counts the tools and the board report."""
    rows = cx.execute("select result, count(*) from outcomes group by result").fetchall()
    counts = {r: 0 for r in RESULTS}
    counts.update(dict(rows))
    return dict(counts, total=sum(counts.values()))
