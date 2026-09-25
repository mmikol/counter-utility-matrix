"""A hero article's 6v6 kit: what the wiki says changes when the game is
played six a side.

The Cargo table publishes the 5v5 kit. The article carries the 6v6 one
beside it: the infobox's health6v6, shield6v6 and armor6v6, and a
6v6_details field in an Ability_details block, a bullet a change ("Cooldown
increased from 7 to 8 seconds.", "No longer shares a cooldown with Projected
Barrier."). parse_six_a_side reads both off the wikitext the kits pull
already fetched; with_stats names the stat each line moves, from the piece's
own Cargo rows. A value that should be a figure and does not parse is
rejected and named, never stored: an infobox pool that is not a whole
number, a "from A to B" line whose A or B is not a number.
"""

import re
from collections.abc import Mapping
from typing import NamedTuple

from db.data.names import ability_key
from db.data.wiki import markup

POOL_FIELDS = ("health", "shield", "armor")
# "Cooldown increased from 7 to 8 seconds", "scalar reduced from 2.5x to 1.75x",
# "Damage amplification reduced from 30% to 25%": the words, the two figures and
# the unit they share, x or %.
CHANGE_RE = re.compile(
    r"^(?P<what>.*?)\s+(?:increased|reduced|decreased|lowered|raised)\s+from\s+"
    r"(?P<before>\d+(?:\.\d+)?)\s*(?P<unit>x|%)?\s*(?:\w+\s+)?to\s+"
    r"(?P<after>\d+(?:\.\d+)?)\s*(?:x|%)?(?![\d.]*\d)", re.I)
# the same wording with figures CHANGE_RE cannot read: a malformed line
LOOSE_CHANGE_RE = re.compile(
    r"\b(?:increased|reduced|decreased|lowered|raised)\s+from\b.+\bto\b", re.I)
# a multiplier the wiki writes 2.5x: the kits hold it as a percent, 250
MULTIPLIER = 100.0
# The stat a line's words name, the first that matches, and the codes it may
# be stored under, in the order a piece's own rows are tried. Temporary health
# is overhealth, so it is read before health; a barrier's health is
# barrier_health where the piece has that row, health where it has that one.
STAT_WORDS = (
    (re.compile(r"cooldown", re.I), ("cooldown",)),
    (re.compile(r"duration", re.I), ("duration",)),
    (re.compile(r"overhealth|temporary health", re.I), ("overhealth",)),
    (re.compile(r"health", re.I), ("barrier_health", "health")),
    (re.compile(r"armor", re.I), ("armor",)),
    (re.compile(r"healing|scalar", re.I), ("heal", "hps")),
    (re.compile(r"amplification", re.I), ("damage_amp",)),
    (re.compile(r"radius", re.I), ("radius",)),
    (re.compile(r"spread", re.I), ("spread",)),
)
BULLET_RE = re.compile(r"^\s*[*#:]+\s*")


class SixLine(NamedTuple):
    """One line of a block's 6v6_details: the piece it changes, the stat its
    words name (None where no STAT_WORDS entry matches, or before
    with_stats has named it), the figures it moves from and to (both None
    for a line with no figure) and the line as the wiki words it."""
    piece: str
    stat: str | None
    before: float | None
    after: float | None
    text: str


class SixKit(NamedTuple):
    """What one article says of its hero in 6v6: each pool the infobox
    gives a 6v6 figure for, the 6v6_details lines, and each value rejected
    as malformed, 'field: value'."""
    pools: dict[str, int]
    lines: list[SixLine]
    rejected: list[str]


def parse_six_a_side(text: str) -> SixKit:
    """The 6v6 kit an article states: its infobox pools and every
    Ability_details block's 6v6_details lines, in the article's order."""
    pools: dict[str, int] = {}
    rejected: list[str] = []
    block = next(markup.find_templates(text, r"Infobox character"), None)
    params = markup.parse_params(block) if block is not None else {}
    for pool in POOL_FIELDS:
        field = pool + "6v6"
        value = markup.wikitext_to_text(params.get(field, ""))
        if re.fullmatch(r"\d+", value):
            pools[pool] = int(value)
        elif value:
            rejected.append("%s: %s" % (field, value))
    lines: list[SixLine] = []
    for block in markup.find_templates(text, r"Ability[ _]details"):
        params = markup.parse_params(block)
        piece = markup.wikitext_to_text(params.get("ability_name", ""))
        details = params.get("6v6_details", "")
        if not piece or not details:
            continue
        for raw in markup.COMMENT_RE.sub("", details).split("\n"):
            said = markup.wikitext_to_text(BULLET_RE.sub("", raw)).rstrip(".").strip()
            if not said:
                continue
            line = _read_line(piece, said)
            if line is None:
                rejected.append("%s 6v6_details: %s" % (piece, said))
            else:
                lines.append(line)
    return SixKit(pools=pools, lines=lines, rejected=rejected)


def _read_line(piece: str, said: str) -> SixLine | None:
    """One line: its figures and its stat's candidate words; a line with
    figures CHANGE_RE cannot read is malformed, None. A line with no
    figure is its words alone."""
    change = CHANGE_RE.match(said)
    if change is None:
        if LOOSE_CHANGE_RE.search(said):
            return None
        return SixLine(piece=piece, stat=None, before=None, after=None, text=said)
    scale = MULTIPLIER if (change.group("unit") or "").lower() == "x" else 1.0
    stat = next((codes[0] for words, codes in STAT_WORDS if words.search(change.group("what"))),
                None)
    return SixLine(piece=piece, stat=stat, before=float(change.group("before")) * scale,
                   after=float(change.group("after")) * scale, text=said)


def _candidates(line: SixLine) -> tuple[str, ...]:
    """The stat codes a line's words may be stored under."""
    return next((codes for words, codes in STAT_WORDS if line.stat in codes), ())


def with_stats(six: SixKit, pieces: Mapping[str, Mapping[str, str]]) -> SixKit:
    """The kit with each line's stat named from its piece's own rows:
    pieces is {ability key: {stat code: value text}}, the piece's Cargo and
    article stats. Of the codes a line's words may mean, the first the piece
    holds with the line's from figure in its text; else the first it holds;
    else the first the words name."""
    named: list[SixLine] = []
    for line in six.lines:
        codes = _candidates(line)
        rows = pieces.get(ability_key(line.piece), {})
        held = [code for code in codes if code in rows]
        figure = "%g" % (line.before or 0.0)
        exact = [code for code in held if re.search(r"(?<![\d.])%s(?![\d])" % re.escape(figure),
                                                     rows[code])]
        chosen = exact or held or list(codes)
        named.append(line._replace(stat=chosen[0] if chosen else None))
    return six._replace(lines=named)
