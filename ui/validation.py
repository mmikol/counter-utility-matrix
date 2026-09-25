"""The validation report: the playbook against the recorded matches, as
text on stdout and as a page of charts written to db/raw (gitignored).

    .venv/bin/python -m ui.validation                       # the playbook in force
    .venv/bin/python -m ui.validation --playbook tests/fixtures/playbook --all

inference.validate does the work; this module loads the World, the
recorded matches and the playbook, runs it and draws the result: the maps
against what an effect needs, each model's log loss against the coin
flip's, what each strategy family carries, how well the chances land, the
playbook score difference by result, the hero effects, the digests and
every judged map. The page carries rate-derived figures (M2, the map win
difference): it is for the owner's own use and is never published.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence

import psycopg

from db import RAW_DIR, ROOT, Refusal, psql, to_stderr
from facts import tables
from facts.matches import load_matches
from inference import catalog, validate
from inference.fit import Estimate
from inference.report import SplitReport, Validation, rendered
from ui import charts
from ui.charts import esc

DEFAULT_OUT = os.path.join(RAW_DIR, "validation.html")
# a model's name where a chart row has room for a few words
SHORT = {"M1": "map and side", "M2": "map win rates", "M3": "heroes", "M4": "heroes + playbook"}

STYLE = """
:root {
    color-scheme: light;
    --surface: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
    --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11, 11, 11, 0.10);
    --better: #2a78d6; --worse: #e34948; --track: #cde2fb;
}
@media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
        color-scheme: dark;
        --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
        --muted: #898781; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255, 255, 255, 0.10);
        --better: #3987e5; --worse: #e66767; --track: #184f95;
    }
}
:root[data-theme="dark"] {
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255, 255, 255, 0.10);
    --better: #3987e5; --worse: #e66767; --track: #184f95;
}
* { box-sizing: border-box; }
body {
    margin: 0; background: var(--page); color: var(--ink);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 880px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 40px 0 8px; }
h3 { font-size: 15px; margin: 24px 0 4px; }
p { margin: 8px 0; color: var(--ink-2); }
.sub { color: var(--muted); margin: 0 0 16px; }
.note {
    border: 1px solid var(--ring); border-radius: 8px; padding: 8px 12px;
    background: var(--surface); color: var(--ink-2);
}
.verdict { font-size: 16px; color: var(--ink); }
.tiles {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 8px; margin: 16px 0;
}
.tile {
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    padding: 10px 12px;
}
.tile .label { color: var(--ink-2); font-size: 13px; }
.tile .value { font-size: 24px; font-weight: 600; }
.meter { margin: 8px 0; }
.meter .bar { height: 10px; border-radius: 5px; background: var(--track); overflow: hidden; }
.meter .fill { height: 100%; background: var(--better); border-radius: 5px; }
.meter .caption { font-size: 13px; color: var(--ink-2); }
.card {
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    padding: 8px; margin: 8px 0;
}
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td {
    text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--grid);
    vertical-align: top;
}
th { color: var(--ink-2); font-weight: 600; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
#tip {
    position: fixed; pointer-events: none; background: var(--surface); color: var(--ink);
    border: 1px solid var(--ring); border-radius: 6px; padding: 6px 8px; font-size: 13px;
    white-space: pre-line; max-width: 320px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
"""

# every mark with a data-tip shows it beside the pointer, or above itself on focus
SCRIPT = """
(function () {
    var tip = document.getElementById("tip");
    function place(x, y) {
        tip.hidden = false;
        var w = tip.offsetWidth, h = tip.offsetHeight;
        tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 12)) + "px";
        tip.style.top = Math.max(8, y - h - 12) + "px";
    }
    document.querySelectorAll("[data-tip]").forEach(function (el) {
        el.addEventListener("pointermove", function (e) {
            tip.textContent = el.getAttribute("data-tip");
            place(e.clientX, e.clientY);
        });
        el.addEventListener("pointerleave", function () { tip.hidden = true; });
        el.addEventListener("focus", function () {
            var r = el.getBoundingClientRect();
            tip.textContent = el.getAttribute("data-tip");
            place(r.left + r.width / 2, r.top);
        });
        el.addEventListener("blur", function () { tip.hidden = true; });
    });
})();
"""


def _cell(e: Estimate | None, signed: bool = False) -> str:
    if e is None:
        return '<td class="num">-</td>'
    form = "%+.3f [%+.3f, %+.3f]" if signed else "%.3f [%.3f, %.3f]"
    return '<td class="num">%s</td>' % (form % (e["value"], e["low"], e["high"]))


def _table(head: Sequence[str], rows: Sequence[str]) -> str:
    return ('<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            '</table></div>' % ("".join("<th>%s</th>" % esc(h) for h in head), "".join(rows)))


def _split_section(split: SplitReport) -> str:
    """One split: each model's log loss against the coin flip's, the table
    of every score, and the ablations."""
    out = ['<h3>The %s split</h3><p>%s: %d folds, %d maps over %d sessions scored.</p>' % (
        esc(split["name"]), esc(split["meaning"].capitalize()), split["folds"],
        split["scored"], split["sessions"])]
    if not split["models"]:
        return "".join(out) + "<p>Nothing to score: the split needs two sessions.</p>"
    rows = [charts.IntervalRow(
        "%s %s" % (m["id"], SHORT.get(m["id"], "")), m["vs_coin"],
        "%s %s: log loss minus the coin flip's" % (m["id"], m["label"]))
        for m in split["models"] if m["id"] != "M0"]
    if split["playbook_adds"] is not None:
        rows.append(charts.IntervalRow(
            "M4 - M3", split["playbook_adds"],
            "what the playbook score and the matchups add to the heroes"))
    out.append('<div class="card">%s</div>' % charts.interval_chart(
        rows, "log loss minus the baseline's: below 0 is better",
        "%s split: models against the coin flip" % split["name"]))
    out.append(_table(("model", "log loss", "Brier", "vs coin flip"), [
        "<tr><td>%s %s</td>%s%s%s</tr>" % (
            esc(m["id"]), esc(m["label"]), _cell(m["log_loss"]), _cell(m["brier"]),
            _cell(m["vs_coin"], True)) for m in split["models"]]))
    if split["ablations"]:
        out.append("<p>Each family dropped from M4's playbook score: above 0, the maps"
                   " miss it - the family was carrying weight.</p>")
        cuts = [charts.IntervalRow("without %s" % a["family"], a["vs_full"],
                                   "drops %s" % ", ".join(a["ids"])) for a in split["ablations"]]
        out.append('<div class="card">%s</div>' % charts.interval_chart(
            cuts, "log loss without the family minus M4's: above 0, it carried weight",
            "%s split: ablations" % split["name"], lower_is_better=False))
        out.append(_table(("dropped", "strategies", "log loss", "minus M4's"), [
            "<tr><td>%s</td><td>%s</td>%s%s</tr>" % (
                esc(a["family"]), esc(", ".join(a["ids"])), _cell(a["log_loss"]),
                _cell(a["vs_full"], True)) for a in split["ablations"]]))
    if split["verdict"]:
        out.append('<p class="verdict">%s</p>' % esc(split["verdict"]))
    return "".join(out)


def _meter(decided: int, needed: int, effect: str) -> str:
    share = min(1.0, decided / needed) if needed else 1.0
    return ('<div class="meter"><div class="caption">50%% -> %s: %d of %d decided maps</div>'
            '<div class="bar" role="meter" aria-valuemin="0" aria-valuemax="%d"'
            ' aria-valuenow="%d"><div class="fill" style="width:%.1f%%"></div></div></div>'
            % (esc(effect), decided, needed, needed, min(decided, needed), 100 * share))


def _match_rows(v: Validation) -> list[str]:
    """Every judged map as a table row: M4's chance on the sessions split
    where it scored the map."""
    out = []
    for r in v["matches"]:
        chance = r["predictions"].get("sessions", {}).get("M4")
        out.append(
            '<tr><td class="num">%d</td><td class="num">%s</td><td>%s%s</td><td>%s</td>'
            '<td>%s</td><td>%s</td><td class="num">%.2f</td><td class="num">%.2f</td>'
            '<td class="num">%+.2f</td><td class="num">%s</td><td class="num">%s</td>'
            '<td>%s</td></tr>' % (
                r["match_id"], esc(r["played_on"]), esc(r["map"]),
                esc(" (%s)" % r["side"]) if r["side"] else "", esc(r["result"]),
                esc(", ".join(r["blue"])), esc(", ".join(r["red"])), r["blue_score"],
                r["red_score"], r["map_win_diff"],
                "-" if chance is None else "%.0f%%" % (100 * chance), esc(r["digest"][:12]),
                esc(r["note"])))
    return out


def page(v: Validation) -> str:
    """The report as one self-contained page: no request leaves it."""
    c, g, book = v["counts"], v["guard"], v["playbook"]
    tiles = [
        ("recorded maps", c["recorded"]), ("judged", c["judged"]), ("decided", c["decided"]),
        ("won - lost", "%d - %d" % (c["won"], c["lost"])), ("drawn", c["drawn"]),
        ("sessions", c["sessions"])]
    meters = [
        _meter(c["decided"], needed, "%d%%" % round(100 * float(effect)))
        for effect, needed in g["reference"].items()]
    # a verdict per split where the guard gave them, else the run's one line
    verdicts = ['<p class="verdict">The %s split: %s</p>' % (esc(s["name"]), esc(s["verdict"]))
                for s in v["splits"] if s["verdict"]]
    verdicts = verdicts or ['<p class="verdict">%s</p>' % esc(v["verdict"])]
    body = [
        "<h1>The playbook against the recorded matches</h1>",
        '<p class="sub">%s · digest %s · %s</p>' % (
            esc(book["name"]), esc(book["digest"][:12]),
            "pinned: judged from its first map on" if v["pinned"] else
            "unpinned: every map, the ones it was tuned on included"),
        '<p class="note">For the owner\'s own use. M2 and the map win difference read'
        " Blizzard's rates, which are licensed for personal use: this page is never"
        " published or shared.</p>",
        *verdicts,
        '<div class="tiles">%s</div>' % "".join(
            '<div class="tile"><div class="label">%s</div><div class="value">%s</div></div>'
            % (esc(label), esc(value)) for label, value in tiles),
        "<h2>The data guard</h2>",
        "<p>A verdict needs (5.6 / b)<sup>2</sup> decided maps for an effect of b log-odds"
        " per sd. Below that the scores are what the maps say so far, not a finding.</p>",
        *meters,
        "<p>%s</p>" % esc(g["text"]),
        "<h2>The models</h2>",
        "<p>M0 a coin flip; M1 the map and side's base rate; M2 blue's map win rate minus"
        " red's (rate-derived); M3 one effect per hero; M4 M3 plus the playbook score"
        " difference and the matchup metrics. Each is scored on maps it was not fitted"
        " on; an interval is 95%, resampling whole sessions.</p>",
        *[_split_section(split) for split in v["splits"]],
    ]
    bins = charts.calibration(v, "sessions", "M4")
    if bins:
        body += ["<h2>The calibration</h2>",
                 "<p>M4 on the sessions split: a well-calibrated model's dots sit on the"
                 " diagonal.</p>",
                 '<div class="card">%s</div>' % charts.calibration_chart(bins, "calibration of M4")]
    if v["matches"]:
        effect = v["score_effect"]
        body += ["<h2>The playbook score and the results</h2>",
                 "<p>%s</p>" % esc(
                     "Fitted on every decided map, the score difference moves blue's"
                     " log-odds %+.3f per sd; an effect that size needs %d maps."
                     % (effect["log_odds"], effect["needed"]) if effect else
                     "The score difference never varies: the playbook scores every map"
                     " alike."),
                 '<div class="card">%s</div>' % charts.score_chart(v)]
    if v["heroes"]:
        body += ["<h2>The heroes</h2>",
                 "<p>Descriptive: M3 fitted on every decided map, not scored out of"
                 " sample.</p>", '<div class="card">%s</div>' % charts.hero_chart(v)]
    body += [
        "<h2>The digests</h2>",
        _table(("digest", "maps", "first", "last", ""), [
            '<tr><td class="num">%s</td><td class="num">%d</td><td class="num">%s</td>'
            '<td class="num">%s</td><td>%s</td></tr>' % (
                esc(p["digest"][:12]), p["maps"], esc(p["first"]), esc(p["last"]),
                "judged" if p["judged"] else "") for p in v["pins"]]),
        "<h2>The maps</h2>",
        _table(("#", "played", "map", "result", "blue", "red", "blue score", "red score",
                "map win diff (rates)", "M4 chance", "digest", "note"), _match_rows(v)),
    ]
    if v["refused"]:
        body += ["<h2>The refused maps</h2>", _table(("#", "why"), [
            '<tr><td class="num">%d</td><td>%s</td></tr>' % (r["match_id"], esc(r["reason"]))
            for r in v["refused"]])]
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Playbook validation</title><style>%s</style></head><body><main>%s"
            "</main><div id=\"tip\" role=\"tooltip\" hidden></div><script>%s</script>"
            "</body></html>\n" % (STYLE + charts.STYLE, "".join(body), SCRIPT))


def write(v: Validation, path: str) -> str:
    """The page, and the report as JSON beside it (.json) -> the page's path."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(page(v))
    with open(os.path.splitext(path)[0] + ".json", "w", encoding="utf-8") as handle:
        json.dump(v, handle, indent=1)
    return path


def command_line(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ui.validation",
        description="Judge a playbook against the recorded matches; print the report and"
                    " write it as a page of charts.")
    parser.add_argument("--playbook", default=None,
                        help="a playbook folder inside the repo (default: the one in force)")
    parser.add_argument("--all", action="store_true",
                        help="judge every map, the ones the playbook may have been tuned on"
                             " included (default: from its digest's first map on)")
    parser.add_argument("--effect", type=float, default=validate.EFFECT,
                        help="the win chance an effect moves an even map to, which the guard"
                             " sizes the sample for (default %(default)s)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="the page to write, the JSON beside it (default db/raw/"
                             "validation.html, gitignored)")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, out: Callable[[str], None] = print) -> Validation:
    """The validation the arguments ask for, printed and written."""
    subject = validate.Subject.of(catalog.named_dir(args.playbook))
    validate.check_effect(args.effect)
    with psycopg.connect(psql.default_dsn()) as cx:
        world = tables.load(cx)
        recorded = load_matches(cx)
    report = validate.validate(world, recorded, subject, validate.Options(
        pin=not args.all, effect=args.effect, log=to_stderr))
    out(rendered(report))
    path = os.path.abspath(write(report, args.out))
    inside = os.path.commonpath([path, ROOT]) == ROOT
    out("the report: %s" % (os.path.relpath(path, ROOT) if inside else path))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the validation from the shell -> 0, or 2 on a refusal: a folder
    outside the repo, a playbook that does not load, an effect that is not a
    win chance."""
    try:
        run(command_line(argv))
    except Refusal as refused:
        sys.stderr.write("validation: %s\n" % refused)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
