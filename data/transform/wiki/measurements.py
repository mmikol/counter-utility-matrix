"""Splits a wiki stat value into individual measurements.

Wiki stat values are rarely a single number. They carry conditions
("0.67 shots/s (max charge); 3.33 shots/s (min charge)"), ranges
("10 - 20 meters"), durations ("75 over 0.59 seconds") and yes/no glyphs.

Each measurement becomes one row, so `value` and `unit` are genuinely
queryable and no variant is thrown away. The original string is always kept
alongside, so anything this misreads stays recoverable.
"""

import re

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

TRUE_VALUES = {"✓", "yes", "true", "1"}
FALSE_VALUES = {"✕", "✗", "no", "false", "0"}

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
    "health": "hp", "damage": "hp", "hp": "hp",
    "round": "rounds", "ammo": "rounds", "pellet": "pellets",
    "charge": "charges", "shot": "shots", "volley": "volleys", "swing": "swings",
    "point": "points",
}

# Rate spellings -> (unit on top, unit underneath). The denominator's own
# magnitude is 1 for these: "125 m/s" is 125 meters per *one* second.
RATE_UNITS = {
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
}


def normalize_unit(unit):
    """Recognised units: (numerator, denominator). Denominator None if not a rate."""
    unit = (unit or "").strip().lower()
    if unit in RATE_UNITS:
        return RATE_UNITS[unit]
    unit = UNIT_ALIASES.get(unit, unit)
    return (unit, None) if unit in CANONICAL_UNITS else (None, None)


PER_SECOND_RE = re.compile(r"\bper\s+([\d.]*)\s*seconds?\b", re.I)


def _measure(text, condition, default_unit):
    """One part -> [(value, numerator, denominator, denominator_value, condition)].

    denominator_value carries the magnitude underneath: 1 for a plain rate
    ("125 m/s"), 0.59 for a burst measured over a window ("75 over 0.59
    seconds"). The rate is always value / denominator_value per denominator.
    """
    body = text.strip()
    if not body:
        return []

    lowered = body.lower()
    if lowered in TRUE_VALUES:
        return [(1, None, None, None, condition)]
    if lowered in FALSE_VALUES:
        return [(0, None, None, None, condition)]

    over = OVER_RE.match(body)
    if over:
        # "75 over 0.59 seconds": 75 hp across a 0.59 second window.
        return [(float(over.group(1)), default_unit, "seconds",
                 float(over.group(2)), condition)]

    # "15 per 0.5 seconds", "33.3% per second"
    window = PER_SECOND_RE.search(body)
    if window:
        head = body[: window.start()].strip()
        number = NUMBER_UNIT_RE.match(head)
        if number:
            numerator, _ = normalize_unit(number.group(2))
            seconds = float(window.group(1)) if window.group(1) else 1.0
            return [(float(number.group(1)), numerator or default_unit,
                     "seconds", seconds, condition)]

    spread = RANGE_RE.match(body)
    if spread:
        numerator, denominator = normalize_unit(
            spread.group(3).split()[0] if spread.group(3) else ""
        )
        low, high = sorted((float(spread.group(1)), float(spread.group(2))))
        window = 1 if denominator else None
        return [
            (low, numerator or default_unit, denominator, window,
             _join(condition, "min")),
            (high, numerator or default_unit, denominator, window,
             _join(condition, "max")),
        ]

    number = NUMBER_UNIT_RE.match(body)
    if number:
        numerator, denominator = normalize_unit(number.group(2))
        return [(float(number.group(1)), numerator or default_unit, denominator,
                 1 if denominator else None, condition)]

    # Non-numeric (shot types, "partial"): keep the row, leave value NULL.
    return [(None, None, None, None, condition)]


def _join(condition, extra):
    return "%s, %s" % (condition, extra) if condition else extra


def _variants(part, condition):
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
            (("%s %s" % (number, trailing)).strip(),
             _join(condition, "variant %d" % index))
            for index, number in enumerate(numbers, start=1)
        ]

    return [(part, condition)]


def parse_measurements(value_text, default_unit=None):
    """Stat value -> [(value, numerator, denominator, denominator_value,
                       condition, text)].

    default_unit is the stat's canonical unit, applied when the value carries
    no unit of its own ("damage = 90" is 90 hp).
    """
    if not value_text:
        return []

    measurements = []
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
                measurements.append((None, None, None, None, text_condition, text))
                continue
            for value, numerator, denominator, window, cond in _measure(
                text, text_condition, default_unit
            ):
                measurements.append(
                    (value, numerator, denominator, window, cond, text)
                )
    return measurements
