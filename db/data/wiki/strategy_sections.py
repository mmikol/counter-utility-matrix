"""A hero article's ==Strategy== section: the counters its sentences state,
and which way each runs.

The Match-Up column says what one hero does against one enemy, cell by
cell. The Strategy section is prose about the hero, and a sentence may name
several heroes - enemies, allies, heroes it is compared with - so a hero is
read into an edge only by its place around a cue. The article's hero is the
sentence's own side: its names, its pronoun (he or she, as its article uses
it, where the sentence says no "you"), "you" and "your", and, as the one who
acts, its abilities' names; "an opposing Juno" in Juno's article is a
mirror, and no side. Every other released hero named is a foe. A cue's
object is the first hero named after it past three short words at most
("nullify anything Doomfist wants", "stun and kill you"); a list runs on
from a named hero through commas, "and", "or" and two words at most
("Winston, Roadhog, unshielded Reinhardt, and a flying Pharah").

    act         "counter(s) to", "counters", "interrupts", "cancels",
                "nullifies", "denies", "negates", "punishes", "used
                against", "effective against": the hero's own side as the
                object - the foes before it answer the hero (or the foes
                after, where none come before: "counter you (such as with
                a mobile tank like Winston)"); a foe as the object, the
                hero or nothing named before - the hero answers its list;
                no object, the hero or nothing named before - the hero
                answers the first list after ("Pharah is a good counter to
                enemies ... that can't hit her in the air, such as Reaper,
                Mei, Junkrat").
    hit         "stuns", "prevents", "stops", "kills", "eliminates",
                "destroys", "beats", "shuts down", "takes out", "picks
                off": as act, but only with an object - these words are
                nouns too ("Stuns, such as those from Roadhog") and an act
                with no object says nothing of whom.
    avoid       "Try to avoid Sombra": a foe as the object and no foe
                before - its list answers the hero; the hero's side as the
                object ("to avoid your Scrap Gun") - the foes before
                answer it.
    patient     "vulnerable to", "weak to", "easy target for", "countered
                by", "suffers from": the hero, or nothing named, before and
                a list after - they answer it; foes before and none after -
                the hero answers them ("Targets like Mercy and Zenyatta are
                vulnerable to well-executed attacks").
    threatens   "the hero's counters", "your biggest threat", "a threat to
                you": every foe in the clause answers the hero.
    strong      "troublesome", "dangerous for", "poses a threat",
                "difficult to deal with": the foes before answer the hero.
    weak        "vulnerable", "an easy target", "has trouble", "struggles",
                "easy to kill": a list it names at once ("vulnerable
                targets like Mercy", "vulnerable (such as a lone
                Widowmaker)"), or foes before, are answered by the hero, and
                so is the list after where nothing is named before; the
                hero before and a list after "with", "by" or "for" answer
                it ("easy to burst down with heroes like Widowmaker").

A cue is read inside its clause - a sentence splits at ";" and at "but",
"while", "though", "although", "however", "whereas" and ", as well as" - and
not at all after a negation six words back at most ("they don't have the
burst damage needed to kill you") or a "from" ("preventing any stuns from
interrupting Deadeye"). A sentence that hedges ("may seem like
simple counters") or compares ("Like Widowmaker, Hanzo ...") reads no edge.
One that speaks of allies (synergy, ally, friendly, teammate, paired
together), or sits under a bullet that does ("Tidal Blast synergies:"),
reads only a foe it calls an enemy or opposing. A pair a sentence names
beside a cue that reads no edge, or reads both ways within one article, is
ambiguous and dropped; so is a pair two articles' sections read opposite
ways.
"""

import itertools
import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from db.data.names import name_key
from db.data.wiki import markup
from db.data.wiki.matchup_tables import SENTENCE_END_RE

STRATEGY_RE = re.compile(r"^==\s*Strategy\s*==[ \t]*$", re.M)
# wiki furniture left in a line once its markup is text: a heading, a bullet
HEADING_RE = re.compile(r"={2,}[^=\n]*={2,}")
BULLET_RE = re.compile(r"^[\s*#:;)]+")
CLAUSE_RE = re.compile(r";|\s(?:but|while|though|although|however|whereas)\b|,\s+as well as\b",
                       re.I)
HEDGE_RE = re.compile(r"\bseem(?:s|ing)?\b", re.I)
COMPARISON_RE = re.compile(r"^Like\b")
ALLY_RE = re.compile(r"\b(?:synerg\w*|all(?:y|ies|ied)|friendly|teammates?|paired together)\b",
                     re.I)
ENEMY_BEFORE_RE = re.compile(r"\b(?:enemy|opposing)\s+$", re.I)
MIRROR_BEFORE_RE = re.compile(r"\b(?:enemy|opposing|another)\s+$", re.I)
# a negation up to six words before a cue, with no stop between: "they
# don't have the burst damage needed to kill you"
NEGATED_RE = re.compile(r"(?:\bnot|n't|\bcannot|\bnever|\bno longer|\bunable to|\bfails? to"
                        r"|\black(?:s|ing)?|\bwithout)(?:\s+[\w'-]+){0,6}\s*$", re.I)
FROM_RE = re.compile(r"\bfrom\s+$", re.I)
# a cue's object: the first hero named after it past at most three of these
# words, no stop between - "nullify anything Doomfist wants", "stun and
# kill you", "cancel out your push"; "kill them and chain your" has an
# object of its own before the hero
OBJECT_GAP_RE = re.compile(
    r"\s*(?:(?:a|an|the|any|all|anything|every|of|out|off|down|to|for|against|and|or"
    r"|enemy|opposing|another|kill|stun|stop|cancel)\s+){0,3}", re.I)
# a subject pronoun: a weak cue with nothing named before it and one of
# these has a subject the sentence does not name
SUBJECT_RE = re.compile(r"\b(?:he|she|they|it)\b", re.I)
# between two heroes of one list: a possessive and three words ("Roadhog's
# Take a Breather"), a comma, and, or, an ampersand or a slash, then at most
# two words
LIST_GAP_RE = re.compile(r"(?:'s(?:\s+[\w-]+){0,3})?\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+"
                         r"|\s*[&/]\s*)(?:[\w-]+\s+){0,2}")
SUCH_AS_RE = re.compile(r"^[\s(]*(?:(?:targets?|enemies|heroes|characters)\s+)?(?:such as|like)\s",
                        re.I)
BY_WITH_RE = re.compile(r"^\s*(?:\w+\s+){0,4}?(?:with|by|for)\s", re.I)
SECOND_PERSON_RE = re.compile(r"\byou(?:r|rself)?\b", re.I)
PRONOUNS = {"he": ("he", "him", "his", "himself"), "she": ("she", "her", "hers", "herself")}

ACT, HIT, AVOID, PATIENT, THREATENS, STRONG, WEAK = (
    "act", "hit", "avoid", "patient", "threatens", "strong", "weak")
# Each cue's class and pattern, the specific before the general: where two
# overlap, the first listed is read. THREATENS names the hero's own side,
# which read_article fills in as %(self)s.
CUES = (
    (PATIENT,
        r"\b(?:vulnerable|weak(?:ness)?|susceptible) (?:to|against)\b"
        r"|\b(?:easy|easier|prime|perfect|free) (?:targets?|prey|kills?),? "
        r"(?:especially |particularly |even )?for\b"
        r"|\b(?:hard )?countered (?:\w+ )?by\b|\bsuffers? from\b"),
    (THREATENS,
        r"(?:%(self)s's|\byour) (?:\w+ ){0,2}(?:counters?|threats?)\b"
        r"|\b(?:threats?|dangers?|problems?) (?:to|for) (?:you\b|%(self)s)"),
    (STRONG,
        r"\btroublesome\b|\b(?:dangerous|deadly) (?:for|to)\b"
        r"|\bposes? an? (?:\w+ ){0,2}threat\b"
        r"|\b(?:difficult|hard|tough) to (?:flank|kill|fight|deal with)\b"),
    (WEAK,
        r"\bvulnerable\b|\b(?:easy|easier|prime|perfect|free) (?:targets?|prey|kills?)\b"
        r"|\b(?:ha(?:s|ve|ving)|will have) (?:\w+ )?(?:trouble|difficulty)\b|\bstruggles?\b"
        r"|\b(?:easy|easier) to (?:kill|burst down|pick off|take out)\b"),
    (ACT,
        r"\bcounter(?:-charge|s|ing)?(?: (?:to|for|against))?\b|\binterrupt(?:s|ing)?\b"
        r"|\b(?:force-)?cancel(?:s|ling|ing)?\b|\bnullif(?:y|ies|ying)\b"
        r"|\bden(?:y|ies|ying)\b|\bnegat(?:e|es|ing)\b|\bpunish(?:es|ing)?\b"
        r"|\b(?:used|effective|good|strong|great) against\b"),
    (HIT,
        r"\bstun(?:s|ning)?\b|\bprevent(?:s|ing)?\b|\bstop(?:s|ping)?\b"
        r"|\bkill(?:s|ing)?\b|\beliminat(?:e|es|ing)\b|\bdestroy(?:s|ing)?\b"
        r"|\bbeat(?:s|ing)?\b|\bshut(?:s|ting)? down\b|\btakes? out\b"
        r"|\bpick(?:s|ing)? off\b"),
    (AVOID, r"\bavoid\b"),
)


class Side(NamedTuple):
    """The article's own hero as a sentence can name it: its roster name,
    every name the prose may use for it (matchups.aliases), its pronoun
    ('he', 'she' or None) and its abilities' names."""
    name: str
    names: tuple[str, ...]
    pronoun: str | None
    kit: tuple[str, ...]


class Mention(NamedTuple):
    """A hero named in a sentence: where, whom (a foe's roster name, or None
    for the article's own side), and how - "self" for the hero's name, its
    pronoun or "you", "kit" for one of its abilities, "mirror" for its name
    as an enemy's, "foe" for another released hero, "enemy" for one the
    sentence calls an enemy."""
    start: int
    end: int
    hero: str | None
    kind: str


class Claim(NamedTuple):
    """An edge a sentence states: the winner answers the loser."""
    winner: str
    loser: str
    sentence: str


class Reading(NamedTuple):
    """What one article's Strategy section states: its edges, and each
    (article hero, other hero) pair a cue named without one."""
    claims: list[Claim]
    ambiguous: list[tuple[str, str]]


class Said(NamedTuple):
    """One sentence of the section, and whether it sits under a bullet that
    speaks of allies."""
    text: str
    allied: bool


class _Patterns(NamedTuple):
    """One article's compiled patterns: the foes' names (a group per foe, in
    `order`), the hero's own names and abilities, its pronoun, and the cues."""
    foes: re.Pattern[str]
    order: list[str]
    own: re.Pattern[str]
    pronoun: re.Pattern[str] | None
    cues: list[tuple[str, re.Pattern[str]]]


def sentences(text: str) -> list[Said]:
    """The Strategy section's sentences as plain text, in order; none
    without one. A bullet that speaks of allies and ends in a colon puts
    the deeper bullets under it in the allies' context."""
    found = STRATEGY_RE.search(text)
    if found is None:
        return []
    body = markup.REF_RE.sub("", markup.section_body(text, found.end(), top_level=True))
    out: list[Said] = []
    allied_at: int | None = None
    for raw in body.split("\n"):
        stripped = raw.lstrip()
        depth = len(stripped) - len(stripped.lstrip("*"))
        line = BULLET_RE.sub("", HEADING_RE.sub(" ", markup.wikitext_to_text(raw)))
        line = line.replace("’", "'").strip()
        if allied_at is not None and depth <= allied_at:
            allied_at = None
        allied = allied_at is not None
        start = 0
        for end in SENTENCE_END_RE.finditer(line):
            out.append(Said(line[start:end.end()].strip(), allied))
            start = end.end()
        out.append(Said(line[start:].strip(), allied))
        if ALLY_RE.search(line) and line.endswith(":") and allied_at is None:
            allied_at = depth
    return [s for s in out if s.text]


def _alternation(names: Sequence[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))


def _patterns(
        side: Side, others: Sequence[str], aliases: Mapping[str, Sequence[str]]) -> _Patterns:
    """The patterns one article is read with."""
    order = sorted(others)
    groups = "|".join("(?P<h%d>%s)" % (i, _alternation(aliases.get(h, (h,))))
                      for i, h in enumerate(order))
    own = "(?:%s)" % _alternation(side.names)
    return _Patterns(
        foes=re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % groups),
        order=order,
        own=re.compile(r"(?<![\w-])(?:(?P<self>%s)|(?P<kit>%s))(?![\w-])"
                       % (_alternation(side.names), _alternation(side.kit) or "(?!)")),
        pronoun=(re.compile(r"\b(?:%s)\b" % "|".join(PRONOUNS[side.pronoun]), re.I)
                 if side.pronoun in PRONOUNS else None),
        cues=[(kind, re.compile(pattern % {"self": own} if kind == THREATENS else pattern,
                                re.I)) for kind, pattern in CUES])


def _mentions(sentence: str, patterns: _Patterns) -> list[Mention]:
    """The heroes a sentence names, in order; a name inside a longer one is
    dropped. The hero's pronoun is its own side only where the sentence
    says no "you": beside "you", he and she are someone else."""
    found: list[Mention] = []
    for m in patterns.foes.finditer(sentence):
        group = next(k for k, v in m.groupdict().items() if v)
        kind = "enemy" if ENEMY_BEFORE_RE.search(sentence[:m.start()]) else "foe"
        found.append(Mention(m.start(), m.end(), patterns.order[int(group[1:])], kind))
    for m in patterns.own.finditer(sentence):
        kind = "kit" if m.group("kit") else (
            "mirror" if MIRROR_BEFORE_RE.search(sentence[:m.start()]) else "self")
        found.append(Mention(m.start(), m.end(), None, kind))
    second = list(SECOND_PERSON_RE.finditer(sentence))
    if patterns.pronoun is not None and not second:
        found += [Mention(m.start(), m.end(), None, "self")
                  for m in patterns.pronoun.finditer(sentence)]
    found += [Mention(m.start(), m.end(), None, "self") for m in second]
    found.sort(key=lambda x: (x.start, x.start - x.end))
    kept: list[Mention] = []
    for mention in found:
        if not kept or mention.start >= kept[-1].end:
            kept.append(mention)
    return kept


def _clauses(sentence: str) -> list[tuple[int, int]]:
    """The sentence's clauses as (start, end) offsets."""
    cuts = [0, *[m.start() for m in CLAUSE_RE.finditer(sentence)], len(sentence)]
    return [(a, b) for a, b in itertools.pairwise(cuts) if b > a]


def _is_foe(m: Mention | None) -> bool:
    return m is not None and m.kind in ("foe", "enemy")


def _foes(mentions: Sequence[Mention]) -> list[str]:
    return [m.hero for m in mentions if _is_foe(m) and m.hero is not None]


def _run(sentence: str, mentions: Sequence[Mention], i: int) -> list[str]:
    """The list of foes that starts at mentions[i]."""
    run = [mentions[i]]
    for nxt in mentions[i + 1:]:
        if not _is_foe(nxt) or not LIST_GAP_RE.fullmatch(sentence[run[-1].end:nxt.start]):
            break
        run.append(nxt)
    return _foes(run)


def _first_list(sentence: str, after: Sequence[Mention]) -> list[str]:
    """The first list of foes after a cue."""
    first = next((i for i, m in enumerate(after) if _is_foe(m)), None)
    return [] if first is None else _run(sentence, after, first)


def _read_cue(
        kind: str, sentence: str, span: tuple[int, int], cue: re.Match[str],
        before: list[Mention], after: list[Mention],
        clause: list[Mention]) -> list[tuple[str, str]]:
    """(winner, loser) pairs one cue reads, the article's hero written ''.
    span is the cue's clause."""
    last = before[-1] if before else None
    rest = sentence[cue.end():span[1]]
    near = after[0] if after and OBJECT_GAP_RE.fullmatch(
        sentence[cue.end():after[0].start]) else None
    if kind in (ACT, HIT, AVOID):
        if near is not None and near.kind == "self":
            return [(foe, "") for foe in (_foes(before) or _foes(after))]
        if _is_foe(near) and not _is_foe(last):
            ran = _run(sentence, after, 0)
            return [(foe, "") for foe in ran] if kind == AVOID else [("", foe) for foe in ran]
        if kind == ACT and near is None and not _is_foe(last):
            return [("", foe) for foe in _first_list(sentence, after)]
        return []
    if kind == PATIENT:
        if not _is_foe(last):
            return [(foe, "") for foe in _first_list(sentence, after)]
        return [] if _foes(after) else [("", foe) for foe in _foes(before)]
    if kind == THREATENS:
        return [(foe, "") for foe in _foes(clause)]
    if kind == STRONG:
        return [(foe, "") for foe in _foes(before)]
    if SUCH_AS_RE.match(rest) and _foes(after):
        return [("", foe) for foe in _first_list(sentence, after)]
    if _is_foe(last):
        return [("", foe) for foe in _foes(before)]
    if last is None:
        # a pronoun no side owns is a subject the sentence does not name
        unnamed = SUBJECT_RE.search(sentence[span[0]:cue.start()])
        return [] if unnamed else [("", foe) for foe in _first_list(sentence, after)]
    if BY_WITH_RE.match(rest):
        return [(foe, "") for foe in _first_list(sentence, after)]
    return []


def read_sentence(said: Said, patterns: _Patterns) -> tuple[set[tuple[str, str]], set[str]]:
    """({(winner, loser)}, {the foes a cue named}) for one sentence, the
    article's hero written ''."""
    sentence = said.text
    mentions = _mentions(sentence, patterns)
    if not _foes(mentions):
        return set(), set()
    hedged = bool(HEDGE_RE.search(sentence) or COMPARISON_RE.match(sentence))
    if said.allied or ALLY_RE.search(sentence):
        mentions = [m for m in mentions if m.kind != "foe"]
    edges: set[tuple[str, str]] = set()
    cued: set[str] = set()
    for start, end in _clauses(sentence):
        clause = [m for m in mentions if start <= m.start < end]
        taken: list[tuple[int, int]] = []
        for kind, pattern in patterns.cues:
            for cue in pattern.finditer(sentence, start, end):
                if any(cue.start() < b and a < cue.end() for a, b in taken):
                    continue
                taken.append(cue.span())
                cued |= set(_foes(clause))
                head = sentence[start:cue.start()]
                if hedged or NEGATED_RE.search(head) or FROM_RE.search(head):
                    continue
                before = [m for m in clause if m.end <= cue.start()]
                after = [m for m in clause if m.start >= cue.end()]
                edges |= set(_read_cue(kind, sentence, (start, end), cue, before, after,
                                       clause))
    return edges, cued


def read_article(text: str, side: Side, released: Sequence[str],
                 aliases: Mapping[str, Sequence[str]]) -> Reading:
    """The edges one article's Strategy section states, and the pairs it
    names beside a cue without one: no edge read, or edges both ways.
    aliases is {roster name: the names the prose may use}."""
    patterns = _patterns(side, [h for h in released if name_key(h) != name_key(side.name)],
                         aliases)
    claims: dict[tuple[str, str], str] = {}
    named: set[str] = set()
    for said in sentences(text):
        edges, cued = read_sentence(said, patterns)
        named |= cued
        for winner, loser in sorted(edges):
            claims.setdefault((winner or side.name, loser or side.name), said.text)
    both = {pair for pair in claims if pair[::-1] in claims}
    kept = [Claim(w, lose, s) for (w, lose), s in sorted(claims.items()) if (w, lose) not in both]
    answered = {c.winner for c in kept} | {c.loser for c in kept}
    return Reading(claims=kept, ambiguous=sorted(
        (side.name, other) for other in named if other not in answered))


def combine(readings: Mapping[str, Reading]) -> tuple[list[Claim], list[tuple[str, str]]]:
    """Every article's reading -> (each edge no other article's section
    reads the other way, with the first article's sentence; every pair
    dropped, its two heroes sorted: ambiguous in an article, or
    contradicted across two)."""
    first: dict[tuple[str, str], Claim] = {}
    for article in sorted(readings):
        for claim in readings[article].claims:
            first.setdefault((claim.winner, claim.loser), claim)
    contradicted = {(min(pair), max(pair)) for pair in first if pair[::-1] in first}
    edges = [c for pair, c in sorted(first.items()) if (min(pair), max(pair)) not in contradicted]
    ambiguous = {(min(a, b), max(a, b)) for r in readings.values() for a, b in r.ambiguous}
    held = {(min(c.winner, c.loser), max(c.winner, c.loser)) for c in edges}
    return edges, sorted((ambiguous - held) | contradicted)
