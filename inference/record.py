"""Recording a decided composition: the storage gates, the tables, the
transcript.

The one write path for recommendations, whoever decided them - the solver
(`infer`) or a Claude Code session following the /comp skill. Two gates:

  shape    exactly six picks, each with a hero, a why, and evidence
  meaning  heroes must exist, and every cited fact id must be one the
           board for (map, red, the six picks) actually shows - a
           citation of nothing is refused, not stored

    python -m inference.record < answer.json        # {"question", "map",
        "red", "blue", "model", "answer": {"playstyle", "reasoning",
        "picks": [{"hero", "why", "evidence": ["F7", ...]}]}}
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import psycopg

from data import common
from data.common import ROOT
from data.proprietary.pipeline import USER
from user.facts import engine as facts_engine
from user.facts import model
from user.facts.compute import TEAM_SIZE

REC_DIR = os.path.join(ROOT, "data", "proprietary", "recommendations")


def validate_answer(answer):
    """Raise ValueError unless the answer has the required shape."""
    for key in ("playstyle", "reasoning", "picks"):
        if not answer.get(key):
            raise ValueError("answer is missing %r" % key)
    if len(answer["picks"]) != TEAM_SIZE:
        raise ValueError("a composition is exactly %d picks, got %d"
                         % (TEAM_SIZE, len(answer["picks"])))
    for pick in answer["picks"]:
        for key in ("hero", "why", "evidence"):
            if not pick.get(key):
                raise ValueError("pick %r is missing %r" % (pick.get("hero", "?"), key))
    return answer


def persist(cx, question, answer, fs, map_id, prompt, model_name, raw_json):
    """Store the exchange; returns rec_id. Raises on citations of nothing.
    Does not commit - the caller owns the transaction."""
    cursor = cx.cursor()
    source_id = common.register_source(cursor, USER, common.now())
    hero_ids = common.lookup_ids(cursor, "heroes", "name", "hero_id")
    by_tag = {f.id: f for f in fs.facts}
    unknown_heroes = [p["hero"] for p in answer["picks"]
                      if p["hero"].lower() not in hero_ids]
    if unknown_heroes:
        raise ValueError("invented heroes: %s" % unknown_heroes)
    bad = [t for p in answer["picks"] for t in p["evidence"] if t not in by_tag]
    if bad:
        raise ValueError("cited facts the board never showed: %s" % bad)
    cursor.execute(
        "INSERT INTO recommendations (request, map_id, model, playstyle,"
        " reasoning, prompt, response, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING rec_id",
        (question, map_id, model_name, answer["playstyle"], answer["reasoning"],
         prompt, raw_json, source_id))
    rec_id = cursor.fetchone()[0]
    for position, p in enumerate(answer["picks"], start=1):
        hero_id = hero_ids[p["hero"].lower()]
        cursor.execute(
            "INSERT INTO recommendation_picks (rec_id, position, hero_id, why,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (rec_id, position, hero_id, p["why"], source_id))
        for tag in p["evidence"]:
            f = by_tag[tag]
            cursor.execute(
                "INSERT INTO recommendation_evidence (rec_id, tag, source_table,"
                " description, hero_id, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (rec_id, tag, f.source or f.key, f.text, hero_id, source_id))
    return rec_id


def transcript(rec_id, question, map_name, red, blue, answer, fs, model_name):
    """The durable record: a committed markdown file per recommendation."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", (map_name or "any-map").lower()).strip("-")
    path = os.path.join(REC_DIR, "%s-%s.md" % (stamp, slug))
    by_tag = {f.id: f.text for f in fs.facts}
    cited = sorted({t for p in answer["picks"] for t in p["evidence"]},
                   key=lambda t: int(t[1:]))
    lines = ["# Recommendation %d" % rec_id, "",
             "**Question:** %s" % question,
             "**Map:** %s   **Red:** %s   **Blue locked:** %s   **Model:** %s"
             % (map_name or "-", ", ".join(red) or "-", ", ".join(blue) or "-",
                model_name), "",
             "## Comp - %s" % answer["playstyle"], ""]
    for p in answer["picks"]:
        lines.append("- **%s** - %s _(%s)_" % (p["hero"], p["why"], ", ".join(p["evidence"])))
    lines += ["", "## Reasoning", "", answer["reasoning"], "", "## Facts cited", ""]
    lines += ["- [%s] %s" % (t, by_tag[t]) for t in cited]
    os.makedirs(REC_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def record(cx, question, answer, map_name=None, red=(), blue=(),
           model_name="claude-code-session"):
    """The whole path: gates, tables, mirror, transcript -> (rec_id, path).

    The evidence board is (map, red, the six picks): the facts a pick
    cites are the ones the user layer shows for that exact board."""
    validate_answer(answer)
    world = model.load(cx)
    picks = [p["hero"] for p in answer["picks"]]
    fs = facts_engine.generate(world, map_name, list(red), picks)
    m = world.map(map_name) if map_name else None
    rec_id = persist(cx, question, answer, fs, m.id if m else None,
                     "facts rebuilt at record time:\n\n" + fs.rendered(),
                     model_name, json.dumps(answer))
    cx.commit()
    common.export(cx)
    path = transcript(rec_id, question, map_name, list(red), list(blue), answer,
                      fs, model_name)
    return rec_id, path


def main():
    parser = common.build_parser(__doc__)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    with psycopg.connect(common.resolve_dsn(args)) as cx:
        rec_id, path = record(cx, payload["question"], payload["answer"],
                              payload.get("map"), payload.get("red", []),
                              payload.get("blue", []),
                              payload.get("model", "claude-code-session"))
    print("recorded as recommendation %d; transcript: %s" % (rec_id, path))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
