"""The validation report's charts, as inline SVG: each a function from the
report's numbers to one <svg>, drawn on the viewBox's WIDTH and styled by
STYLE's classes, which the page's own style carries. Every mark is a
keyboard-reachable group whose data-tip the page's script shows.

    interval_chart     a dot and its 95% interval per row, against 0
    hero_chart         each hero's effect as a bar from 0
    calibration_chart  predicted chance against the share won, per bin
    score_chart        each map's playbook score difference, a strip per result
    scale              a linear map with round ticks
"""

import html
import math
from collections.abc import Sequence
from typing import NamedTuple

from inference import predict, validate
from inference.fit import Estimate
from inference.report import Validation

CALIBRATION_BINS = 10       # the calibration chart's bins of predicted chance
HERO_ROWS = 20              # the hero chart's largest effects, either sign

WIDTH = 760                 # every chart's viewBox width
LABEL = 170                 # the left column a row's label sits in
VALUES = 200                # the right column a row's value sits in
ROW = 30                    # a row's height in the interval and hero charts
AXIS = 34                   # the band under a plot that holds its ticks and caption
KNUTH = 2654435761          # Knuth's multiplicative hash: a stable spread of match ids
JITTER_STEPS = 1000         # the distinct heights a map may sit at within its strip

STYLE = """
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
"""


def esc(text: object) -> str:
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
        (x.start + x.end) / 2, bottom + 30, esc(caption)))
    return "".join(out)


def _line(kind: str, x1: float, y1: float, x2: float, y2: float) -> str:
    """A hairline: a gridline or an axis."""
    return '<line class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (kind, x1, y1, x2, y2)


def _svg(height: float, body: str, label: str) -> str:
    return ('<svg viewBox="0 0 %d %.0f" role="img" aria-label="%s">%s</svg>'
            % (WIDTH, height, esc(label), body))


def _tone(e: Estimate, lower_is_better: bool = True) -> str:
    """A difference's class: better where its interval lies wholly on the
    good side of 0, worse wholly on the other, even across it."""
    side = predict.reading(e) * (-1 if lower_is_better else 1)
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
                esc(tip), y - ROW / 2, WIDTH, ROW, LABEL, y + 4, esc(row.label),
                tone, x.at(e["low"]), x.at(e["high"]), y, y, tone, x.at(e["value"]), y,
                WIDTH - VALUES + 12, y + 4,
                esc("%+.3f [%+.3f, %+.3f]" % (e["value"], e["low"], e["high"]))))
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
                esc(tip), top + ROW * i, WIDTH, ROW, LABEL, y + 11, esc(h["hero"]), tone,
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
                       esc(tip), x.at(b.predicted), y.at(b.won), x.at(b.predicted),
                       y.at(b.won)))
    return _svg(bottom + AXIS, "".join(out), label)


def _jitter(match_id: int) -> float:
    """A map's vertical offset in its strip, from its id: stable across renders."""
    return (match_id * KNUTH % JITTER_STEPS) / JITTER_STEPS - 0.5


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
                   % (LABEL, middle + 4, esc(name)))
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
                       % (esc(tip), at, y, at, y))
    return _svg(bottom + AXIS, "".join(out), "the playbook score difference by result")
