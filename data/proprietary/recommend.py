"""The inference layer: strategies in, a cited team composition out.

    python -m data.proprietary.recommend --map "King's Row" \\
        --enemy Zarya --enemy Mei --ask "we keep losing first fight"

The deterministic half (data/proprietary/dossier.py) assembles numbered
evidence from the whole database; this half shows it to Claude alongside the
authored strategy notes and requires a structured answer in which every pick
cites the evidence tags that justify it. The full exchange is stored in the
inference tables and written as a markdown transcript into
data/proprietary/recommendations/, so a recommendation is reproducible and
inspectable, never just trusted.

Model: claude-opus-5 (override with --model or OVERWATCH_DB_MODEL). Credentials
resolve the way the SDK always does - ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
or an `ant auth login` profile.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import psycopg

from data.proprietary import dossier, pipeline
from data.proprietary.pipeline import USER

# Claude Fable 5.1 at maximum reasoning. Thinking is always on for this
# model (the parameter is omitted by design - explicit configs are rejected);
# depth is driven by output_config.effort = "max". Server-side refusal
# fallbacks are enabled by default per Anthropic's guidance for this model:
# on a policy decline the API re-runs the request on a fallback model inside
# the same call, routed by refusal category.
DEFAULT_MODEL = os.environ.get("OVERWATCH_DB_MODEL", "claude-fable-5-1")
EFFORT = os.environ.get("OVERWATCH_DB_EFFORT", "max")

REC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "recommendations")

# strict tool: the comp comes back schema-valid or not at all
COMP_TOOL = {
    "name": "propose_composition",
    "description": "Propose the five-hero composition, citing evidence tags.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["playstyle", "picks", "reasoning"],
        "properties": {
            "playstyle": {"type": "string",
                          "description": "the archetype the comp commits to"},
            "picks": {
                "type": "array", "minItems": 5, "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["hero", "why", "evidence"],
                    "properties": {
                        "hero": {"type": "string"},
                        "why": {"type": "string",
                                "description": "one sentence for this pick"},
                        "evidence": {
                            "type": "array", "minItems": 1,
                            "items": {"type": "string",
                                      "description": "an evidence tag, e.g. E7"},
                        },
                    },
                },
            },
            "reasoning": {"type": "string",
                          "description": "the overall argument, briefly"},
        },
    },
}

SYSTEM = """You are the inference layer of overwatch-db, recommending an Open
Queue Competitive five-hero composition.

Ground rules:
- Choose ONLY from the roster names that appear in the evidence or roster
  list; never invent a hero.
- Every pick must cite the evidence tags that justify it. Cite only tags that
  genuinely support the pick - an uncited good reason is better than a cited
  bad one, and there is no credit for citation count.
- Evidence tagged `strategies` and the synergy notes are the operator's own
  judgement: weight them above scraped rates when they conflict, say so, and
  cite them like any other line.
- The `+` lines (counters+map_meta, playstyle+map_meta) are pre-computed
  intersections - who answers the enemy AND holds up on this ground. They are
  usually where the comp's core comes from.
- Rates are Role Queue on console, a stated proxy for Open Queue - lean on
  them for direction, not decimals.
- Respect ban pressure: if a hero is banned in a large share of lobbies, the
  comp must not depend on them; prefer a stable core.
- The dossier opens with its own vintage; if it warns that patches shipped
  since capture, say so and lean harder on kit facts and the playbook.
- `candidates` lines are full profiles - kit, rates, RANK-SENSITIVE spreads.
  A CAUTION line means a known enemy answers that candidate: picking them
  anyway needs an argument, not silence.
- Use enemy cooldown and pierces-defenses lines to justify HOW a pick wins,
  not just that it does.

When your analysis is complete, call the propose_composition tool exactly
once with your final comp - the tool call IS the answer.
"""


def ask(cx, question, map_name=None, enemies=(), model=DEFAULT_MODEL):
    """-> (structured answer dict, Evidence, prompt string, model response)."""
    import anthropic

    ev, ctx = dossier.build(cx, map_name, enemies)
    roster = [n for n, in cx.execute("select name from heroes order by name")]

    parts = ["# Question\n%s" % question]
    if ctx["map_name"]:
        parts.append("Map: %s" % ctx["map_name"])
    if enemies:
        parts.append("Known enemy heroes: %s" % ", ".join(enemies))
    parts.append("# Evidence\n" + ev.rendered())
    parts.append("# Roster\n" + ", ".join(roster))
    prompt = "\n\n".join(parts)

    client = anthropic.Anthropic()
    # Fable 5.1 rejects forced tool_choice ("any"/"tool" return 400), so the
    # tool call is requested by instruction under "auto"; strict: true on the
    # tool still guarantees schema-valid arguments when it is called.
    with client.beta.messages.stream(
        model=model,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": EFFORT},
        system=SYSTEM,
        tools=[COMP_TOOL],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("the model (and its fallbacks) declined: %s" % (
            response.stop_details and response.stop_details.explanation))
    answer = next((b.input for b in response.content if b.type == "tool_use"),
                  None)
    if answer is None:
        text = " ".join(b.text for b in response.content
                        if b.type == "text")[:300]
        raise RuntimeError("the model answered without calling"
                           " propose_composition: %s" % text)
    return answer, ev, prompt, response


def persist(cx, question, answer, ev, ctx_map_id, prompt, model, raw_json):
    """Store the exchange; returns rec_id. Raises on citations of nothing.

    Does not commit - the caller owns the transaction, which is what lets a
    test exercise this whole path and roll it back."""
    cursor = cx.cursor()
    source_id = pipeline.register_source(cursor, USER, pipeline.now())
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


def main():
    parser = pipeline.build_parser(__doc__)
    parser.add_argument("--ask", required=True, help="the question, in prose")
    parser.add_argument("--map", dest="map_name", help="the map, if known")
    parser.add_argument("--enemy", action="append", default=[],
                        help="a known enemy hero (repeatable)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    import orchestrator
    orchestrator.load_env()
    with psycopg.connect(pipeline.resolve_dsn(args)) as cx:
        answer, ev, prompt, response = ask(
            cx, args.ask, args.map_name, args.enemy, args.model)
        _, ctx = dossier.build(cx, args.map_name, args.enemy)
        served_by = response.model
        rec_id = persist(cx, args.ask, answer, ev, ctx["map_id"], prompt,
                         served_by, json.dumps(answer))
        cx.commit()
        path = transcript(rec_id, args.ask, args.map_name, args.enemy,
                          answer, ev, served_by)
        if served_by != args.model:
            print("note: %s declined; served by fallback %s"
                  % (args.model, served_by))

    print("comp (%s):" % answer["playstyle"])
    for p in answer["picks"]:
        print("  %-14s %s  [%s]" % (p["hero"], p["why"],
                                    ", ".join(p["evidence"])))
    print("\n%s" % answer["reasoning"])
    print("\nstored as recommendation %d; transcript: %s"
          % (rec_id, os.path.relpath(path)))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        sys.exit("error: %s" % error)
    except psycopg.Error as error:
        sys.exit("error: %s" % error)
    except Exception as error:                      # SDK/auth errors, plainly
        kind = type(error).__name__
        if "Authentication" in kind or "apiKey" in str(error) or "api_key" in str(error):
            sys.exit("error: no Claude API credentials - put ANTHROPIC_API_KEY"
                     " in .env (copy .env.example) or run `ant auth login`")
        sys.exit("error (%s): %s" % (kind, error))
