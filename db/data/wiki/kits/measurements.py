"""Splits a wiki stat value into individual measurements.

Wiki stat values are rarely a single number. They carry conditions
("0.67 shots/s (max charge); 3.33 shots/s (min charge)"), ranges
("10 - 20 meters"), durations ("75 over 0.59 seconds") and yes/no glyphs.

Each measurement becomes one row, so `value` and `unit` are genuinely
queryable and no variant is thrown away. The original string is always kept
alongside, so anything this misreads stays recoverable.
"""

import re
from typing import NamedTuple

SPLIT_RE = re.compile(r"\s*;\s*")
# Perk stats read "radius = 5 -> 7 meters": the value before the perk and the
# value with it. Both are kept, told apart by `condition`.
ARROW_RE = re.compile(r"\s*(?:\u2192|->)\s*")
# "10/20/30 per second" packs several values into one field.
TIERED_RE = re.compile(r"^([\d.]+(?:/[\d.]+)+)\s*(.*)$")
# Wiki template failures occasionally leak into a value.
TEMPLATE_ERROR_RE = re.compile(r"expression error|#invoke|script error", re.I)
CONDITION_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
# "75 over 0.59 seconds"
OVER_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*over\s*([\d.]+)\s*seconds?\b", re.I)
# "10 - 20 meters", including the en dash the wiki sometimes uses
RANGE_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*[-–]\s*([+-]?\d+(?:\.\d+)?)\s*(.*)$")
# "125 m/s", "14 seconds", "-50%"
NUMBER_UNIT_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([%a-zA-Z/]*)")

# A bare 1 or 0 is a number, in the stat's unit like any other.
TRUE_VALUES = {"✓", "yes", "true"}
FALSE_VALUES = {"✕", "✗", "no", "false"}

# Units are always base quantities, never rates. A rate is split into the unit
# on top and the unit underneath, so "125 m/s" is 125 meters per second and
# nothing has to parse a "/" to know that.
CANONICAL_UNITS = frozenset(
    {
        "seconds", "meters", "degrees", "percent", "hp", "rounds", "pellets",
        "charges", "shots", "volleys", "swings", "points", "multiplier",
    }
)

# Spellings the wiki mixes for the same unit.
UNIT_ALIASES = {
    "s": "seconds", "second": "seconds", "sec": "seconds", "secs": "seconds",
    "m": "meters", "meter": "meters", "metre": "meters", "metres": "meters",
    "degree": "degrees", "°": "degrees",
    "%": "percent",
    "health": "hp", "damage": "hp",
    "round": "rounds", "ammo": "rounds", "pellet": "pellets",
    "charge": "charges", "shot": "shots", "volley": "volleys", "swing": "swings",
    "point": "points",
}

# Rate spellings -> (unit on top, unit underneath). The denominator's own
# magnitude is 1 for these: "125 m/s" is 125 meters per *one* second.
RATE_UNITS: dict[str, tuple[str | None, str]] = {
    "m/s": ("meters", "seconds"),
    "meters/s": ("meters", "seconds"), "meters/second": ("meters", "seconds"),
    "shots/s": ("shots", "seconds"), "shot/s": ("shots", "seconds"),
    "shots/second": ("shots", "seconds"), "shot/second": ("shots", "seconds"),
    "rounds/s": ("rounds", "seconds"), "round/s": ("rounds", "seconds"),
    "rounds/second": ("rounds", "seconds"),
    "volleys/s": ("volleys", "seconds"), "volley/s": ("volleys", "seconds"),
    "swings/s": ("swings", "seconds"), "swings/sec": ("swings", "seconds"),
    "swing/s": ("swings", "seconds"),
    "hp/s": ("hp", "seconds"), "dps": ("hp", "seconds"),
    # "185/s": the unit on top is the stat's own
    "/s": (None, "seconds"),
}


class Measurement(NamedTuple):
    """One row of a stat: its value (None when the text holds no number), the
    unit on top and underneath, the magnitude underneath (1 for a plain rate,
    0.59 for "75 over 0.59 seconds"), the condition it holds under, and the
    text it was read from."""
    value: float | None
    numerator: str | None
    denominator: str | None
    window: float | None
    condition: str | None
    text: str


def normalise_unit(unit: str | None) -> tuple[str | None, str | None]:
    """Recognised units: (numerator, denominator). Denominator None if not a rate."""
    unit = (unit or "").strip().lower()
    if unit in RATE_UNITS:
        return RATE_UNITS[unit]
    unit = UNIT_ALIASES.get(unit, unit)
    return (unit, None) if unit in CANONICAL_UNITS else (None, None)


PER_SECOND_RE = re.compile(r"\bper\s+([\d.]*)\s*seconds?\b", re.I)


def _measure(text: str, condition: str | None, default_unit: str | None) -> list[Measurement]:
    """One variant's text, stripped -> its measurements, each read from it.

    window carries the magnitude underneath: 1 for a plain rate ("125 m/s"),
    0.59 for a burst measured over a window ("75 over 0.59 seconds"). The
    rate is always value / window per denominator.
    """
    if not text:
        return []

    lowered = text.lower()
    if lowered in TRUE_VALUES:
        return [Measurement(1, None, None, None, condition, text)]
    if lowered in FALSE_VALUES:
        return [Measurement(0, None, None, None, condition, text)]

    rate = _measure_rate(text, condition, default_unit)
    if rate is not None:
        return [rate]

    spread = _measure_range(text, condition, default_unit)
    if spread is not None:
        return spread

    number = NUMBER_UNIT_RE.match(text)
    if number:
        numerator, denominator = normalise_unit(number.group(2))
        return [Measurement(float(number.group(1)), numerator or default_unit, denominator,
                            1 if denominator else None, condition, text)]

    # Non-numeric (shot types, "partial"): keep the row, leave value NULL.
    return [Measurement(None, None, None, None, condition, text)]


def _measure_rate(
        text: str, condition: str | None, default_unit: str | None) -> Measurement | None:
    """A quantity over a window of seconds; None when the text states none."""
    over = OVER_RE.match(text)
    if over:
        # "75 over 0.59 seconds": 75 hp across a 0.59 second window.
        return Measurement(float(over.group(1)), default_unit, "seconds",
                           float(over.group(2)), condition, text)

    # "15 per 0.5 seconds", "33.3% per second"
    window = PER_SECOND_RE.search(text)
    if window:
        head = text[: window.start()].strip()
        number = NUMBER_UNIT_RE.match(head)
        if number:
            numerator, _ = normalise_unit(number.group(2))
            seconds = float(window.group(1)) if window.group(1) else 1.0
            return Measurement(float(number.group(1)), numerator or default_unit,
                               "seconds", seconds, condition, text)
    return None


def _measure_range(
        text: str, condition: str | None, default_unit: str | None) -> list[Measurement] | None:
    """A range, "10 - 20 meters" -> its low end and its high end, in that
    order; None when the text is no range."""
    spread = RANGE_RE.match(text)
    if not spread:
        return None
    numerator, denominator = normalise_unit(
        spread.group(3).split()[0] if spread.group(3) else ""
    )
    low, high = sorted((float(spread.group(1)), float(spread.group(2))))
    window = 1 if denominator else None
    return [
        Measurement(low, numerator or default_unit, denominator, window,
                    _join(condition, "min"), text),
        Measurement(high, numerator or default_unit, denominator, window,
                    _join(condition, "max"), text),
    ]


def _join(condition: str | None, extra: str) -> str:
    return "%s, %s" % (condition, extra) if condition else extra


def _variants(part: str, condition: str | None) -> list[tuple[str, str | None]]:
    """Split one part into the states it describes: [(text, condition)].

    Two shapes carry more than one measurement. "5 -> 7 meters" is a perk's
    before and after; "10/20/30 per second" is a set of alternatives. Splitting
    them keeps the values that would otherwise be dropped on the floor - only
    the first number of each survived before.
    """
    sides = ARROW_RE.split(part)
    if len(sides) == 2:
        before, after = (side.strip() for side in sides)
        if before and after:
            return [(before, _join(condition, "before perk")),
                    (after, _join(condition, "with perk"))]

    tiered = TIERED_RE.match(part)
    if tiered:
        numbers = tiered.group(1).split("/")
        trailing = tiered.group(2).strip()
        return [
            (("%s %s" % (number, trailing)).strip(), _join(condition, "variant %d" % index))
            for index, number in enumerate(numbers, start=1)
        ]

    return [(part, condition)]


def parse_measurements(value_text: str | None,
                       default_unit: str | None = None) -> list[Measurement]:
    """Stat value -> [Measurement(value, numerator, denominator, window,
                                  condition, text)].

    default_unit is the stat's canonical unit, applied when the value carries
    no unit of its own ("damage = 90" is 90 hp).
    """
    if not value_text:
        return []
    # the wiki sometimes writes a minus as U+2212
    value_text = value_text.replace("\u2212", "-")

    measurements: list[Measurement] = []
    for part in SPLIT_RE.split(value_text):
        part = part.strip()
        if not part:
            continue
        condition = None
        match = CONDITION_RE.match(part)
        if match and match.group(1).strip():
            part, condition = match.group(1).strip(), match.group(2).strip()

        for text, text_condition in _variants(part, condition):
            if TEMPLATE_ERROR_RE.search(text):
                # A broken template is not a measurement; keep the text only.
                measurements.append(Measurement(
                    value=None, numerator=None, denominator=None, window=None,
                    condition=text_condition, text=text))
                continue
            measurements.extend(_measure(text, text_condition, default_unit))
    return measurements
