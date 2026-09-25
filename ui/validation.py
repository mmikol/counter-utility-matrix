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
import html
import json
import math
import os
import sys
from collections.abc import Callable, Sequence
from typing import NamedTuple

import psycopg

from db import RAW_DIR, Refusal, psql, to_stderr
from facts import tables
from facts.matches import load_matches
from inference import catalog, validate
from inference.fit import Estimate
from inference.strategy import CatalogError
from inference.validate import SplitReport, Validation

DEFAULT_OUT = os.path.join(RAW_DIR, "validation.html")
CALIBRATION_BINS = 10       # the calibration chart's bins of predicted chance
HERO_ROWS = 20              # the hero chart's largest effects, either sign

WIDTH = 760                 # every chart's viewBox width
LABEL = 170                 # the left column a row's label sits in
VALUES = 200                # the right column a row's value sits in
# a model's name where a chart row has room for a few words
SHORT = {"M1": "map and side", "M2": "map win rates", "M3": "heroes", "M4": "heroes + playbook"}
ROW = 30                    # a row's height in the interval and hero charts
AXIS = 34                   # the band under a plot that holds its ticks and caption

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
svg { display: block; width: 100%; height: auto; }
svg text { font: 12px system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink-2); }
svg .tick { fill: var(--muted); font-variant-numeric: tabular-nums; }
svg .value { fill: var(--ink-2); font-variant-numeric: tabular-nums; }
svg .grid { stroke: var(--grid); stroke-width: 1; }
svg .axis { stroke: var(--axis); stroke-width: 1; }
svg .better { fill: var(--better); stroke: var(--better); }
svg .worse { fill: var(--worse); stroke: var(--worse); }
svg .even { fill: var(--muted); stroke: var(--muted); }
svg .dot { stroke: var(--surface); stroke-width: 2; }
svg .span { stroke-width: 2; stroke-linecap: round; fill: none; }
svg .bar { stroke: none; }
svg .hit { fill: transparent; stroke: none; }
svg .row:hover .dot, svg .row:focus .dot, svg .row:hover .bar, svg .row:focus .bar {
    opacity: 0.75;
}
svg .row:focus { outline: none; }
svg .row:focus .hit { stroke: var(--axis); stroke-width: 1; }
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


def _e(text: object) -> str:
    """Text for HTML or SVG, quotes included."""
    return html.escape(str(text), quote=True)


def _nice_step(span: float, ticks: int = 5) -> float:
    """A round tick step - 1, 2 or 5 times a power of ten - that cuts
    `span` into about `ticks` parts."""
    if span <= 0:
        return 1.0
    raw = span / ticks
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 5, 10) if m * power >= raw)


class Scale(NamedTuple):
    """A linear map from data to x (or y): the domain's ends, the pixels'
    ends, and the ticks on round values between them."""
    low: float
    high: float
    start: float
    end: float
    ticks: tuple[float, ...]

    def at(self, value: float) -> float:
        span = self.high - self.low or 1.0
        return self.start + (value - self.low) / span * (self.end - self.start)


def scale(
        values: Sequence[float], start: float, end: float, *,
        include: Sequence[float] = (0.0,)) -> Scale:
    """The scale over `values` and `include`, widened to round ticks."""
    everything = [*values, *include] or [0.0]
    low, high = min(everything), max(everything)
    if high == low:
        low, high = low - 1.0, high + 1.0
    step = _nice_step(high - low)
    low, high = math.floor(low / step) * step, math.ceil(high / step) * step
    count = round((high - low) / step)
    return Scale(low, high, start, end, tuple(low + i * step for i in range(count + 1)))


def _tick(value: float) -> str:
    """A tick's label: no more decimals than the value needs, up to three."""
    text = ("%.3f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _x_axis(x: Scale, top: float, bottom: float, caption: str) -> str:
    """Vertical gridlines at the ticks, their labels under the plot and a
    caption under those."""
    out = []
    for value in x.ticks:
        at = x.at(value)
        out.append(_line("grid", at, top, at, bottom))
        out.append('<text class="tick" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                   % (at, bottom + 14, _tick(value)))
    out.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (
        (x.start + x.end) / 2, bottom + 30, _e(caption)))
    return "".join(out)


def _line(kind: str, x1: float, y1: float, x2: float, y2: float) -> str:
    """A hairline: a gridline or an axis."""
    return '<line class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (kind, x1, y1, x2, y2)


def _svg(height: float, body: str, label: str) -> str:
    return ('<svg viewBox="0 0 %d %.0f" role="img" aria-label="%s">%s</svg>'
            % (WIDTH, height, _e(label), body))


def _tone(e: Estimate, lower_is_better: bool = True) -> str:
    """A difference's class: better where its interval lies wholly on the
    good side of 0, worse wholly on the other, even across it."""
    side = validate.reading(e) * (-1 if lower_is_better else 1)
    return {1: "better", -1: "worse", 0: "even"}[side]


class IntervalRow(NamedTuple):
    """One row of an interval chart: its label, the estimate, and the words
    its tooltip opens with."""
    label: str
    estimate: Estimate
    tip: str


def interval_chart(rows: Sequence[IntervalRow], caption: str, label: str,
                   lower_is_better: bool = True) -> str:
    """A dot and its 95% interval per row, against a line at 0: a
    difference in log loss, read as better where it lies wholly below 0."""
    if not rows:
        return ""
    ends = [v for r in rows for v in (r.estimate["low"], r.estimate["high"])]
    x = scale(ends, LABEL + 10, WIDTH - VALUES)
    top, bottom = 8.0, 8.0 + ROW * len(rows)
    out = [_x_axis(x, top, bottom, caption)]
    zero = x.at(0.0)
    out.append(_line("axis", zero, top, zero, bottom))
    for i, row in enumerate(rows):
        e, y = row.estimate, top + ROW * i + ROW / 2
        tone = _tone(e, lower_is_better)
        tip = "%+.3f [%+.3f, %+.3f]\n%s" % (e["value"], e["low"], e["high"], row.tip)
        out.append(
            '<g class="row" tabindex="0" data-tip="%s">'
            '<rect class="hit" x="0" y="%.1f" width="%d" height="%d"/>'
            '<text x="%d" y="%.1f" text-anchor="end">%s</text>'
            '<line class="span %s" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
            '<circle class="dot %s" cx="%.1f" cy="%.1f" r="5"/>'
            '<text class="value" x="%d" y="%.1f">%s</text></g>' % (
                _e(tip), y - ROW / 2, WIDTH, ROW, LABEL, y + 4, _e(row.label),
                tone, x.at(e["low"]), x.at(e["high"]), y, y, tone, x.at(e["value"]), y,
                WIDTH - VALUES + 12, y + 4,
                _e("%+.3f [%+.3f, %+.3f]" % (e["value"], e["low"], e["high"]))))
    return _svg(bottom + AXIS, "".join(out), label)


def _rounded_bar(x0: float, x1: float, y: float, height: float) -> str:
    """A bar from x0 (the baseline, square) to x1 (the data end, rounded 4px)."""
    width = abs(x1 - x0)
    r = min(4.0, width, height / 2)
    if x1 >= x0:
        return ("M%.1f,%.1f h%.1f a%.1f,%.1f 0 0 1 %.1f,%.1f v%.1f a%.1f,%.1f 0 0 1 %.1f,%.1f"
                " h%.1f z" % (x0, y, width - r, r, r, r, r, height - 2 * r, r, r, -r, r,
                              -(width - r)))
    return ("M%.1f,%.1f h%.1f a%.1f,%.1f 0 0 0 %.1f,%.1f v%.1f a%.1f,%.1f 0 0 0 %.1f,%.1f"
            " h%.1f z" % (x0, y, -(width - r), r, r, -r, r, height - 2 * r, r, r, r, r,
                          width - r))


def hero_chart(v: Validation) -> str:
    """Each hero's effect in M3 on every decided map: bars from 0, blue for
    a hero who wins blue maps, red for one who loses them; the largest
    HERO_ROWS by size."""
    heroes = sorted(v["heroes"], key=lambda h: -abs(h["effect"]))[:HERO_ROWS]
    heroes.sort(key=lambda h: -h["effect"])
    if not heroes:
        return ""
    x = scale([h["effect"] for h in heroes], LABEL + 10, WIDTH - VALUES)
    top, bottom = 8.0, 8.0 + ROW * len(heroes)
    out = [_x_axis(x, top, bottom, "log-odds a hero adds to blue's chance, M3 on every"
                                   " decided map")]
    zero = x.at(0.0)
    for i, h in enumerate(heroes):
        y = top + ROW * i + (ROW - 14) / 2
        tone = "better" if h["effect"] >= 0 else "worse"
        tip = "%+.2f log-odds\n%s, on %d maps" % (h["effect"], h["hero"], h["maps"])
        out.append(
            '<g class="row" tabindex="0" data-tip="%s">'
            '<rect class="hit" x="0" y="%.1f" width="%d" height="%d"/>'
            '<text x="%d" y="%.1f" text-anchor="end">%s</text>'
            '<path class="bar %s" d="%s"/>'
            '<text class="value" x="%d" y="%.1f">%+.2f</text></g>' % (
                _e(tip), top + ROW * i, WIDTH, ROW, LABEL, y + 11, _e(h["hero"]), tone,
                _rounded_bar(zero, x.at(h["effect"]), y, 14), WIDTH - VALUES + 12, y + 11,
                h["effect"]))
    out.append(_line("axis", zero, top, zero, bottom))
    return _svg(bottom + AXIS, "".join(out), "hero effects")


class Bin(NamedTuple):
    """One calibration bin: the maps in it, their mean predicted chance and
    the share blue won."""
    maps: int
    predicted: float
    won: float


def calibration(v: Validation, split: str, model: str) -> list[Bin]:
    """The decided maps `split` scored under `model`, binned by predicted
    chance into CALIBRATION_BINS: where the chances land."""
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(CALIBRATION_BINS)]
    for row in v["matches"]:
        chance = row["predictions"].get(split, {}).get(model)
        if chance is None or row["result"] not in (validate.WIN, validate.LOSS):
            continue
        i = min(CALIBRATION_BINS - 1, int(chance * CALIBRATION_BINS))
        buckets[i].append((chance, 1 if row["result"] == validate.WIN else 0))
    return [Bin(len(b), sum(p for p, _ in b) / len(b), sum(w for _, w in b) / len(b))
            for b in buckets if b]


def calibration_chart(bins: Sequence[Bin], label: str) -> str:
    """Predicted chance against the share won, per bin, beside the diagonal
    a perfectly calibrated model sits on."""
    if not bins:
        return ""
    left, right, top, bottom = 60.0, WIDTH - 40.0, 12.0, 272.0
    x = Scale(0.0, 1.0, left, right, (0.0, 0.25, 0.5, 0.75, 1.0))
    y = Scale(0.0, 1.0, bottom, top, x.ticks)
    out = [_x_axis(x, top, bottom, "the chance the model gave blue")]
    for value in y.ticks:
        out.append(_line("grid", left, y.at(value), right, y.at(value)))
        out.append('<text class="tick" x="%.1f" y="%.1f" text-anchor="end">%s</text>'
                   % (left - 6, y.at(value) + 4, _tick(value)))
    out.append(_line("axis", x.at(0), y.at(0), x.at(1), y.at(1)))
    middle = (top + bottom) / 2
    out.append(
        '<text x="14" y="%.1f" transform="rotate(-90 14 %.1f)" text-anchor="middle">'
        'the share blue won</text>' % (middle, middle))
    for b in bins:
        tip = "won %.0f%% of %d maps\npredicted %.0f%% on average" % (
            100 * b.won, b.maps, 100 * b.predicted)
        out.append('<g class="row" tabindex="0" data-tip="%s">'
                   '<circle class="hit" cx="%.1f" cy="%.1f" r="12"/>'
                   '<circle class="dot better" cx="%.1f" cy="%.1f" r="5"/></g>' % (
                       _e(tip), x.at(b.predicted), y.at(b.won), x.at(b.predicted),
                       y.at(b.won)))
    return _svg(bottom + AXIS, "".join(out), label)


def _jitter(match_id: int) -> float:
    """A map's vertical offset in its strip, from its id: stable across renders."""
    return ((match_id * 2654435761) % 1000) / 1000.0 - 0.5


def score_chart(v: Validation) -> str:
    """Each judged map's playbook score difference (blue's minus red's), in
    a strip per result: where the playbook separates wins from losses."""
    held = {r["result"] for r in v["matches"]}
    strips = [(key, name) for key, name in (
        (validate.WIN, "won"), (validate.LOSS, "lost"), (validate.DRAW, "drawn")) if key in held]
    if not strips:
        return ""
    diffs = [r["blue_score"] - r["red_score"] for r in v["matches"]]
    x = scale(diffs, LABEL + 10, WIDTH - 40)
    band = 44.0
    top, bottom = 8.0, 8.0 + band * len(strips)
    out = [_x_axis(x, top, bottom, "blue's playbook score minus red's")]
    zero = x.at(0.0)
    out.append(_line("axis", zero, top, zero, bottom))
    for i, (key, name) in enumerate(strips):
        middle = top + band * i + band / 2
        out.append('<text x="%d" y="%.1f" text-anchor="end">%s</text>'
                   % (LABEL, middle + 4, _e(name)))
        for r in v["matches"]:
            if r["result"] != key:
                continue
            at, y = x.at(r["blue_score"] - r["red_score"]), middle + _jitter(
                r["match_id"]) * (band - 16)
            tip = "%+.2f\n#%d %s, %s%s: blue %.2f, red %.2f" % (
                r["blue_score"] - r["red_score"], r["match_id"], r["played_on"], r["map"],
                " %s" % r["side"] if r["side"] else "", r["blue_score"], r["red_score"])
            out.append('<g class="row" tabindex="0" data-tip="%s">'
                       '<circle class="hit" cx="%.1f" cy="%.1f" r="12"/>'
                       '<circle class="dot better" cx="%.1f" cy="%.1f" r="4"/></g>'
                       % (_e(tip), at, y, at, y))
    return _svg(bottom + AXIS, "".join(out), "the playbook score difference by result")


def _cell(e: Estimate | None, signed: bool = False) -> str:
    if e is None:
        return '<td class="num">-</td>'
    form = "%+.3f [%+.3f, %+.3f]" if signed else "%.3f [%.3f, %.3f]"
    return '<td class="num">%s</td>' % (form % (e["value"], e["low"], e["high"]))


def _table(head: Sequence[str], rows: Sequence[str]) -> str:
    return ('<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            '</table></div>' % ("".join("<th>%s</th>" % _e(h) for h in head), "".join(rows)))


def _split_section(split: SplitReport) -> str:
    """One split: each model's log loss against the coin flip's, the table
    of every score, and the ablations."""
    out = ['<h3>The %s split</h3><p>%s: %d folds, %d maps over %d sessions scored.</p>' % (
        _e(split["name"]), _e(split["meaning"].capitalize()), split["folds"],
        split["scored"], split["sessions"])]
    if not split["models"]:
        return "".join(out) + "<p>Nothing to score: the split needs two sessions.</p>"
    rows = [IntervalRow("%s %s" % (m["id"], SHORT.get(m["id"], "")), m["vs_coin"],
                        "%s %s: log loss minus the coin flip's" % (m["id"], m["label"]))
            for m in split["models"] if m["id"] != "M0"]
    if split["playbook_adds"] is not None:
        rows.append(IntervalRow("M4 - M3", split["playbook_adds"],
                                "what the playbook score and the matchups add to the heroes"))
    out.append('<div class="card">%s</div>' % interval_chart(
        rows, "log loss minus the baseline's: below 0 is better",
        "%s split: models against the coin flip" % split["name"]))
    out.append(_table(("model", "log loss", "Brier", "vs coin flip"), [
        "<tr><td>%s %s</td>%s%s%s</tr>" % (
            _e(m["id"]), _e(m["label"]), _cell(m["log_loss"]), _cell(m["brier"]),
            _cell(m["vs_coin"], True)) for m in split["models"]]))
    if split["ablations"]:
        out.append("<p>Each family dropped from M4's playbook score: above 0, the maps"
                   " miss it - the family was carrying weight.</p>")
        out.append('<div class="card">%s</div>' % interval_chart(
            [IntervalRow("without %s" % a["family"], a["vs_full"],
                         "drops %s" % ", ".join(a["ids"])) for a in split["ablations"]],
            "log loss without the family minus M4's: above 0, it carried weight",
            "%s split: ablations" % split["name"], lower_is_better=False))
        out.append(_table(("dropped", "strategies", "log loss", "minus M4's"), [
            "<tr><td>%s</td><td>%s</td>%s%s</tr>" % (
                _e(a["family"]), _e(", ".join(a["ids"])), _cell(a["log_loss"]),
                _cell(a["vs_full"], True)) for a in split["ablations"]]))
    if split["verdict"]:
        out.append('<p class="verdict">%s</p>' % _e(split["verdict"]))
    return "".join(out)


def _meter(decided: int, needed: int, effect: str) -> str:
    share = min(1.0, decided / needed) if needed else 1.0
    return ('<div class="meter"><div class="caption">50%% -> %s: %d of %d decided maps</div>'
            '<div class="bar" role="meter" aria-valuemin="0" aria-valuemax="%d"'
            ' aria-valuenow="%d"><div class="fill" style="width:%.1f%%"></div></div></div>'
            % (_e(effect), decided, needed, needed, min(decided, needed), 100 * share))


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
                r["match_id"], _e(r["played_on"]), _e(r["map"]),
                _e(" (%s)" % r["side"]) if r["side"] else "", _e(r["result"]),
                _e(", ".join(r["blue"])), _e(", ".join(r["red"])), r["blue_score"],
                r["red_score"], r["map_win_diff"],
                "-" if chance is None else "%.0f%%" % (100 * chance), _e(r["digest"][:12]),
                _e(r["note"])))
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
    verdicts = ['<p class="verdict">The %s split: %s</p>' % (_e(s["name"]), _e(s["verdict"]))
                for s in v["splits"] if s["verdict"]]
    verdicts = verdicts or ['<p class="verdict">%s</p>' % _e(v["verdict"])]
    body = [
        "<h1>The playbook against the recorded matches</h1>",
        '<p class="sub">%s · digest %s · %s</p>' % (
            _e(book["name"]), _e(book["digest"][:12]),
            "pinned: judged from its first map on" if v["pinned"] else
            "unpinned: every map, the ones it was tuned on included"),
        '<p class="note">For the owner\'s own use. M2 and the map win difference read'
        " Blizzard's rates, which are licensed for personal use: this page is never"
        " published or shared.</p>",
        *verdicts,
        '<div class="tiles">%s</div>' % "".join(
            '<div class="tile"><div class="label">%s</div><div class="value">%s</div></div>'
            % (_e(label), _e(value)) for label, value in tiles),
        "<h2>The data guard</h2>",
        "<p>A verdict needs (5.6 / b)<sup>2</sup> decided maps for an effect of b log-odds"
        " per sd. Below that the scores are what the maps say so far, not a finding.</p>",
        *meters,
        "<p>%s</p>" % _e(g["text"]),
        "<h2>The models</h2>",
        "<p>M0 a coin flip; M1 the map and side's base rate; M2 blue's map win rate minus"
        " red's (rate-derived); M3 one effect per hero; M4 M3 plus the playbook score"
        " difference and the matchup metrics. Each is scored on maps it was not fitted"
        " on; an interval is 95%, resampling whole sessions.</p>",
        *[_split_section(split) for split in v["splits"]],
    ]
    bins = calibration(v, "sessions", "M4")
    if bins:
        body += ["<h2>The calibration</h2>",
                 "<p>M4 on the sessions split: a well-calibrated model's dots sit on the"
                 " diagonal.</p>",
                 '<div class="card">%s</div>' % calibration_chart(bins, "calibration of M4")]
    if v["matches"]:
        effect = v["score_effect"]
        body += ["<h2>The playbook score and the results</h2>",
                 "<p>%s</p>" % _e(
                     "Fitted on every decided map, the score difference moves blue's"
                     " log-odds %+.3f per sd; an effect that size needs %d maps."
                     % (effect["log_odds"], effect["needed"]) if effect else
                     "The score difference never varies: the playbook scores every map"
                     " alike."),
                 '<div class="card">%s</div>' % score_chart(v)]
    if v["heroes"]:
        body += ["<h2>The heroes</h2>",
                 "<p>Descriptive: M3 fitted on every decided map, not scored out of"
                 " sample.</p>", '<div class="card">%s</div>' % hero_chart(v)]
    body += [
        "<h2>The digests</h2>",
        _table(("digest", "maps", "first", "last", ""), [
            '<tr><td class="num">%s</td><td class="num">%d</td><td class="num">%s</td>'
            '<td class="num">%s</td><td>%s</td></tr>' % (
                _e(p["digest"][:12]), p["maps"], _e(p["first"]), _e(p["last"]),
                "judged" if p["judged"] else "") for p in v["pins"]]),
        "<h2>The maps</h2>",
        _table(("#", "played", "map", "result", "blue", "red", "blue score", "red score",
                "map win diff (rates)", "M4 chance", "digest", "note"), _match_rows(v)),
    ]
    if v["refused"]:
        body += ["<h2>The refused maps</h2>", _table(("#", "why"), [
            '<tr><td class="num">%d</td><td>%s</td></tr>' % (r["match_id"], _e(r["reason"]))
            for r in v["refused"]])]
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Playbook validation</title><style>%s</style></head><body><main>%s"
            "</main><div id=\"tip\" role=\"tooltip\" hidden></div><script>%s</script>"
            "</body></html>\n" % (STYLE, "".join(body), SCRIPT))


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
    directory = catalog.named_dir(args.playbook)
    playbook = catalog.load(directory)
    with psycopg.connect(psql.default_dsn()) as cx:
        world = tables.load(cx)
        recorded = load_matches(cx)
    report = validate.validate(
        world, recorded, playbook, digest=catalog.playbook_digest(directory),
        name=catalog.playbook_name(directory), pin=not args.all, effect=args.effect,
        log=to_stderr)
    out(validate.rendered(report))
    out("the report: %s" % os.path.relpath(write(report, args.out)))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the validation from the shell -> 0, or 2 on a refusal or a playbook
    that does not load."""
    try:
        run(command_line(argv))
    except (Refusal, CatalogError) as refused:
        sys.stderr.write("validation: %s\n" % refused)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
