"""Record a composition decided OUTSIDE the API path - e.g. by the /comp
skill in a Claude Code session - into the same inference tables and
transcript the API path uses, under the same validation gates: citations of
evidence never shown and heroes that do not exist are refused, not stored.

Reads the answer as JSON on stdin:

    {"question": "...", "map": "King's Row", "enemies": ["Zarya"],
     "model": "claude-code-session",
     "answer": {"playstyle": "...", "reasoning": "...",
                "picks": [{"hero": "...", "why": "...", "evidence": ["E7"]}]}}

    python -m data.proprietary.record < answer.json
"""

import json
import sys

import psycopg

import orchestrator
from data.proprietary import dossier, pipeline
from data.proprietary.recommend import persist, transcript


def main():
    orchestrator.load_env()
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    question = payload["question"]
    map_name = payload.get("map")
    enemies = payload.get("enemies", [])
    model = payload.get("model", "claude-code-session")

    with psycopg.connect(pipeline.resolve_dsn(args)) as cx:
        # the same dossier the answer was reasoned over, rebuilt for the gates
        ev, ctx = dossier.build(cx, map_name, enemies)
        rec_id = persist(cx, question, payload["answer"], ev, ctx["map_id"],
                         "recorded from a session; dossier rebuilt at record"
                         " time:\n\n" + ev.rendered(),
                         model, json.dumps(payload["answer"]))
        cx.commit()
    path = transcript(rec_id, question, map_name, enemies,
                      payload["answer"], ev, model)
    print("recorded as recommendation %d; transcript: %s" % (rec_id, path))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
