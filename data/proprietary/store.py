"""Storing a composition: validation gates, tables, transcript.

The one write path for recommendations, whoever decided them - today that
is a Claude Code session following the /comp skill (data/proprietary/
record.py); the shape is model-agnostic. Two kinds of gate:

  shape    validate_answer: exactly five picks, each with a hero, a why,
           and at least one evidence tag
  meaning  persist: heroes must exist, cited tags must have been shown -
           a citation of nothing is refused, not stored
"""

import os
import re
from datetime import datetime, timezone

from data.proprietary import pipeline

REC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "recommendations")


def validate_answer(answer):
    """Raise ValueError unless the answer has the required shape."""
    for key in ("playstyle", "reasoning", "picks"):
        if not answer.get(key):
            raise ValueError("answer is missing %r" % key)
    if len(answer["picks"]) != 5:
        raise ValueError("a composition is exactly five picks, got %d"
                         % len(answer["picks"]))
    for pick in answer["picks"]:
        for key in ("hero", "why", "evidence"):
            if not pick.get(key):
                raise ValueError("pick %r is missing %r"
                                 % (pick.get("hero", "?"), key))
    return answer


def persist(cx, question, answer, ev, ctx_map_id, prompt, model, raw_json):
    """Store the exchange; returns rec_id. Raises on citations of nothing.

    Does not commit - the caller owns the transaction, which is what lets a
    test exercise this whole path and roll it back."""
    cursor = cx.cursor()
    source_id = pipeline.register_source(cursor, pipeline.USER, pipeline.now())
    hero_ids = pipeline.lookup_ids(cursor, "heroes", "name", "hero_id")
    by_tag = {tag: (table, text) for tag, table, text in ev.lines}

    unknown_heroes = [p["hero"] for p in answer["picks"]
                      if p["hero"].lower() not in hero_ids]
    if unknown_heroes:
        raise ValueError("model invented heroes: %s" % unknown_heroes)
    bad_tags = [t for p in answer["picks"] for t in p["evidence"]
                if t not in by_tag]
    if bad_tags:
        raise ValueError("model cited tags that were never shown: %s" % bad_tags)

    cursor.execute(
        "INSERT INTO recommendations (request, map_id, model, playstyle,"
        " reasoning, prompt, response, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING rec_id",
        (question, ctx_map_id, model, answer["playstyle"],
         answer["reasoning"], prompt, raw_json, source_id))
    rec_id = cursor.fetchone()[0]

    for position, p in enumerate(answer["picks"], start=1):
        hero_id = hero_ids[p["hero"].lower()]
        cursor.execute(
            "INSERT INTO recommendation_picks (rec_id, position, hero_id,"
            " why, source_id) VALUES (%s, %s, %s, %s, %s)",
            (rec_id, position, hero_id, p["why"], source_id))
        for tag in p["evidence"]:
            table, text = by_tag[tag]
            cursor.execute(
                "INSERT INTO recommendation_evidence (rec_id, tag,"
                " source_table, description, hero_id, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (rec_id, tag, table, text, hero_id, source_id))
    return rec_id


def transcript(rec_id, question, map_name, enemies, answer, ev, model):
    """The durable record: a committed markdown file per recommendation."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", (map_name or "any-map").lower()).strip("-")
    path = os.path.join(REC_DIR, "%s-%s.md" % (stamp, slug))
    by_tag = {tag: text for tag, _, text in ev.lines}
    cited = sorted({t for p in answer["picks"] for t in p["evidence"]},
                   key=lambda t: int(t[1:]))
    lines = ["# Recommendation %d" % rec_id, "",
             "**Question:** %s" % question,
             "**Map:** %s   **Enemies:** %s   **Model:** %s"
             % (map_name or "-", ", ".join(enemies) or "-", model), "",
             "## Comp - %s" % answer["playstyle"], ""]
    for p in answer["picks"]:
        lines.append("- **%s** - %s _(%s)_"
                     % (p["hero"], p["why"], ", ".join(p["evidence"])))
    lines += ["", "## Reasoning", "", answer["reasoning"], "",
              "## Evidence cited", ""]
    lines += ["- [%s] %s" % (t, by_tag[t]) for t in cited]
    os.makedirs(REC_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path
