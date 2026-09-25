"""Pull + clean + store: overwatch.fandom.com - hero match-ups.

Every hero article's "Match-Ups and Team Synergy" section has, per other
hero, a Match-Up cell: advice to the article's hero about that enemy, in
either markup synergies.py reads. A cell becomes a verdict from the
article hero's seat: +1 the hero answers the enemy, -1 the enemy answers
the hero, 0 neither.

    1   The wiki's MATCHUP or VS. rating decides: STRONG is +1, WEAK is -1,
        EVEN, NEUTRAL, MEDIUM and MIRROR are 0. A range ("EVEN -> WEAK")
        that averages under one step leaves the prose to decide.
    2   Otherwise the prose is scored. The article hero's name becomes
        "you" and the enemy's "foe"; he and she go to the one whose article
        uses that pronoun of its hero. Each cue adds its weight: whole
        in the first sentence, less in each later one, a fraction in a
        concession ("While ...,"), reversed at half weight after a negation.
        A RISK rating is one more cue. A PRIORITY TARGET rating is kill
        order, not a verdict. A margin under MARGIN is 0.

A pair both articles speak about keeps its edge when they agree or one
says neither; when they contradict there is no edge. `counters` is
reloaded wholesale: one row means countered_by_id answers hero_id.
"""

import re
from collections.abc import Mapping
from typing import NamedTuple

import psycopg

from db import psql
from db.data import ArticlePullSummary, fetch
from db.data.names import RENAMED, hero_key, index, name_key, unaccented
from db.data.wiki import WIKI, WikiError, fetch_articles, synergies

# --- extract: markup -> Python ---------------------------------------------

# verdict +1, 0 or -1; basis "rating", "prose" or None for an unwritten cell.
class Reading(NamedTuple):
    verdict: int
    basis: str | None


UNWRITTEN = Reading(0, None)


# What the roster and a hero's own article say of it: its name, 'he' or 'she'.
class Known(NamedTuple):
    name: str | None
    pronoun: str | None


type Pronouns = tuple[str | None, str | None]

# A cell's leading bold label: '''HIGH RISK''', '''<nowiki>A | B</nowiki>'''.
LABEL_RE = re.compile(r"^(?:\s|<(?!nowiki)[^>]+>)*'''\s*(?:<nowiki>)?(.*?)(?:</nowiki>)?\s*'''",
                      re.S)
# The MATCHUP / VS. scale, in steps from even.
MATCHUP_STEPS = {"very strong": 2, "strong": 1, "even": 0, "neutral": 0, "medium": 0,
                 "mirror": 0, "weak": -1, "very weak": -2}
MATCHUP_RATING_RE = re.compile(r"^(.*?)\s*(?:MATCH-?UP|VS\.?)$", re.I)
# The RISK scale: how dangerous the enemy is to the article's hero, as a cue.
RISK_WEIGHTS = {"extreme": -1.0, "extremely high": -1.0, "extermely high": -1.0,
                "very high": -1.0, "high": -0.5, "medium": 0.0, "low": 0.5, "very low": 1.0}
RISK_RATING_RE = re.compile(r"^(.*?)\s*RISK$", re.I)

# Names the wiki's prose uses for a hero besides the article title, its
# name unpunctuated and a former name (names.RENAMED).
NICKNAMES = {
    "soldier76": ("Soldier",), "wreckingball": ("Hammond", "Ball"),
    "junkerqueen": ("Queen",), "reinhardt": ("Rein",), "torbjorn": ("Torb",),
    "roadhog": ("Hog",), "jetpackcat": ("Fika",)}
# "her" before an article, a preposition or a stop is an object: "making her a threat".
PRONOUN_RE = (r"he|she|him|her(?= (?:an?|the|to|at|in|on|with|from|for"
        r"|if|when|and|or|but|as|out|off|down|up|while|before|after|is|are|was|will"
        r"|can|would|should|has|does)\b|[.,;:!?]|$)|(?P<possessive>his|hers?)")
HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
SHE_RE = re.compile(r"\b(?:she|hers?|herself)\b", re.I)
SECOND_PERSON_RE = re.compile(r"\byou(?:r|rself)?\b", re.I)

FOE = r"(?:the |an? )?(?:enemy )?foe"
# A subject with what it owns: "foe", "foe's Defense Matrix".
FOES = r"foe(?:'s [\w' -]{1,40}?)?"
YOURS = r"you(?:r [\w' -]{1,40}?)?"
BE = (r"(?:is|are|'s|'re|be|being|was|becomes?|remains?|serves?(?: as)?|acts? as|makes?"
        r"|makes? for|can be|will be|can prove|will prove|proves?)(?: to be)?")
# Words between a verb and its cue word: "one of the most", "a very".
VERY = r"(?:\w+ly |very |quite |too |so |much |far |a |an |the |of |one |most |more ){0,4}"
# One describing word, not one that denies the noun: "huge", not "little".
ADJ = r"(?:(?!no |little |minimal |less |zero )\w+ )?"
# Words between a subject and its verb; a negation among them reverses the cue.
MODAL = (r"(?:(?P<neg>can't|cannot|can not|won't|will not|doesn't|does not|don't|do not"
        r"|isn't|is not|aren't|are not|never|rarely|hardly|no longer) |can |will |would |may "
        r"|might |could |should |often |usually |generally |still |also |easily |simply "
        r"|is able to |are able to |be able to )*")
DENIES = (r"(?:negates?|nullif(?:y|ies)|eats?|absorbs?|deletes?|deflects?|denies|deny|cancels?"
        r"|interrupts?|blocks?|cleanses?|shuts? down|counters?|stops?|ruins?|ignores?"
        r"|pierces?|bypass(?:es)?)")
DENIED = (r"(?:negated|nullified|eaten|absorbed|deleted|deflected|denied|cancelled|canceled"
        r"|interrupted|blocked|cleansed|shut down|countered|stopped|ruined|ignored)")
WINS = (r"(?:(?:has|have|holds?|gets?|gains?) (?:\w+ ){0,3}(?:advantage|upper hand|edge"
        r"|superiority|better chance)|wins?|beats?|excels?|outclass(?:es)?|outranges?|outguns?"
        r"|out-?damages?|out-?duels?|dominates?|outlasts?|out-?sustains?|thrives?)")
KILL = (r"(?:kill|eliminate|shred|melt|destroy|dispatch|finish(?: off)?|pick off|hunt|bully"
        r"|bombard|pressure|punish|take (?:out|down)|deal with|one-?shot|burst(?: down)?)")
KILLS = (r"(?:kills?|eliminates?|shreds?|melts?|destroys?|dispatch(?:es)?|finish(?:es)?"
        r"|one-?shots?|bursts?|overpowers?|outguns?|outranges?|outclass(?:es)?|out-?duels?"
        r"|out-?damages?|tears? through|rips? through|guns?|runs?)")
EASY = r"(?:easy|easier|prime|perfect|juicy|free|ideal)"
WEAK = (r"(?:vulnerable|susceptible|helpless|defenceless|defenseless|useless|powerless"
        r"|harmless|outmatched|outclassed|outgunned|weak)")
HARD = (r"(?:dangerous|deadly|lethal|difficult|tough|troublesome|problematic|annoying"
        r"|frustrating|challenging|formidable|hard to (?:kill|deal with|fight))")
MENACE = r"(?:threat|problem|danger|menace|nightmare)"
BAD_FIGHT = (r"(?:difficult|tough|dangerous|formidable|hard|tricky|bad|poor|unfavou?rable"
        r"|challenging|frustrating|annoying) (?:opponent|match-?up|enemy|adversary)")
WORST = (r"(?:worst|biggest|greatest|main|primary|strongest|hardest|toughest|deadliest|top"
        r"|number one|most \w+)")

# The weight of a cue about one exchange in the fight, not the fight: "kills
# you", "blocks your". A verdict cue ("counters you", "easy target") weighs 1 to 2.
DETAIL = 0.5


def _compiled_cues(cues: list[tuple[str, float]]) -> list[tuple[re.Pattern[str], float]]:
    return [(re.compile(pattern, re.I), weight) for pattern, weight in cues]


# What the enemy does to the hero. Each: (pattern over the normalised text, weight).
THREAT_CUES = _compiled_cues([
    # "Sombra is one of your biggest counters", "a hard counter to you"
    (r"\byour (?:\w+ ){0,2}counters?\b|\byour %s (?:\w+ )?(?:threats?|nightmares?"
        r"|enem(?:y|ies)|problems?|fears?|match-?ups?)\b" % WORST, 2.0),
    (r"\bcounters? (?:to|for|against) you\b", 2.0),
    (r"\bfoe %scounters? you\b" % MODAL, 2.0),
    (r"\b%s %s%s %s(?:\w+ ){0,2}counters?\b(?! (?:to|for|against) foe)"
        % (FOES, MODAL, BE, VERY), 1.5),
    (r"\byou(?:r \w+)? (?:is|are|'re) (?:\w+ ){0,3}countered by\b", 2.0),
    # "D.Va is a significant threat", "poses an extreme threat", "will prove dangerous"
    (r"\b%s %s(?:%s|poses?) %s%s%s\b(?! (?:to|for) foe)"
        % (FOES, MODAL, BE, VERY, ADJ, MENACE), 1.5),
    (r"\b%s (?:to|for) you\b" % MENACE, 1.5),
    (r"\b%s %s%s %s%s\b(?! (?:to|for) foe)" % (FOES, MODAL, BE, VERY, HARD), 1.0),
    (r"\b%s\b(?! (?:to|for) foe)" % BAD_FIGHT, 1.0),
    # "you will struggle", "there is little you can do", "you are unlikely to win"
    (r"\b%s %sstruggles?\b" % (YOURS, MODAL), 1.5),
    (r"\b(?:little|not much|nothing) (?:that )?you can do\b", 1.5),
    (r"\byou (?:stands?|ha(?:s|ve)) (?:no|little) chance\b|\bfavou?rs? foe\b"
        r"|\bin foe's favou?r\b", 1.5),
    (r"\byou (?:are |'re |will be )?(?:unlikely|unable) to (?:win|kill|beat|reach|hit|escape"
        r"|do much)\b", 1.5),
    (r"\byou (?:can ?not|can't|won't|will not) (?:win|beat|kill|reach|hit|escape|out-?damage"
        r"|outrun|do (?:much|anything))\b", 1.0),
    (r"\bat a (?:\w+ )?disadvantage\b(?! against you)", 1.0),
    # "shuts you down", "can easily kill you", "tear through you", "has you beat"
    (r"\b(?:shuts?|shutting) (?:you|your [\w' -]{1,30}?) down\b", 1.5),
    (r"\b(?:easily|quickly|instantly|simply|just) %s you\b" % KILLS, 1.5),
    (r"\b%s you\b" % KILLS, DETAIL),
    (r"\bha(?:s|ve) you beat(?:en)?\b|\bthe (?:end|death) of you\b|\bdeath sentence\b"
        r"|\b(?:quick|short) work of you\b", 1.0),
    # "can negate your", "eats your", "deflects your", "absorbed by her"
    (r"\b%s %s%s (?:all (?:of )?|most (?:of )?|much (?:of )?)?your\b" % (FOES, MODAL, DENIES),
        DETAIL),
    (r"\b%s by foe" % DENIED, DETAIL),
    # "you make for an easy target", "you are extremely vulnerable to"
    (r"\b%s %s%s %s(?:%s|big|large) (?:target|prey|kill|pick)\b" % (YOURS, MODAL, BE, VERY, EASY),
        1.5),
    (r"\b%s (?:target|prey|kill|pick) for foe\b" % EASY, 1.5),
    (r"\byou %s%s %s%s\b" % (MODAL, BE, VERY, WEAK), 1.5),
    # "avoid him", "keep your distance", "stay away", "switch heroes"
    (r"\bavoid (?:foe(?!'s)|fighting|duel+ing|engaging|confront|facing|close|1v1|a 1v1)", 1.0),
    (r"\bstay(?:ing)? (?:far )?away from foe\b"
        r"|\b(?:do not|don't|never) (?:try to )?(?:solo kill or )?(?:fight|duel|engage"
        r"|challenge|chase|1v1) foe\b", 1.0),
    (r"\bkeep(?:ing)? (?:your|a safe|a) distance\b", DETAIL),
    (r"\b(?:switch(?:ing)?|swap(?:ping)?|chang(?:e|ing)) (?:heroes|off|to (?:another|a "
        r"different))\b", 1.5),
    # "has the advantage over you", "superior to you", "beats you"
    (r"\b%s %s%s\b(?! against foe)" % (FOES, MODAL, WINS), 1.5),
    (r"\bsuperior(?:ity)? (?:to|over) you\b|\badvantage over you\b|\bbetter of you\b", 1.5),
    (r"\bfoe (?:will |can )?ha(?:s|ve) (?:no|little) (?:trouble|difficulty|problems?)\b", 1.0),
])

# What the hero does to the enemy.
ADVANTAGE_CUES = _compiled_cues([
    # "you counter", "Pharah is the ultimate hard counter to Junkrat"
    (r"\byou %s(?:hard[- ]?|directly |completely |heavily )?counters? "
        r"(?:foe|(?:most|all|many) of foe)" % MODAL, 2.0),
    (r"\bcounters? (?:to|for|against) %s\b" % FOE, 2.0),
    (r"\bfoe's (?!an? |the )(?:\w+ ){0,2}counters?\b|\bfoe's %s (?:\w+ )?(?:threats?"
        r"|nightmares?|enem(?:y|ies)|problems?|fears?|match-?ups?)\b" % WORST, 2.0),
    (r"\b%s %s%s %s(?:\w+ ){0,2}counters?\b(?! (?:to|for|against) you)"
        % (YOURS, MODAL, BE, VERY), 1.5),
    (r"\bfoe (?:is|are) (?:\w+ ){0,3}countered by you\b", 2.0),
    # "easy target", "free kill", "easy prey", "prime target for you"
    (r"\b%s %s%s %s(?:%s|good|great|excellent) (?:target|prey|kill|pick)"
        r"(?! for foe)" % (FOES, MODAL, BE, VERY, EASY), 1.5),
    (r"\b(?:%s|good|great) (?:target|prey|kill|pick)(?: to \w+)? (?:for|with) you" % EASY, 1.5),
    (r"\bfoe %s%s %s(?:easy|simple|easier|simpler) (?:enough )?(?:to|for you to) %s"
        % (MODAL, BE, VERY, KILL), 1.5),
    (r"\bmak(?:es?|ing) foe'?s? (?:a |an )?(?:\w+ly )?%s" % EASY, 1.5),
    # "vulnerable to your", "cannot escape your", "helpless against you", "struggles"
    (r"\b%s %s%s %s%s\b" % (FOES, MODAL, BE, VERY, WEAK), 1.5),
    (r"\b%s %s(?:fundamentally |traditionally )?struggles?\b" % (FOES, MODAL), 1.5),
    (r"\bfoe (?:can ?not|can't|won't|will not|is unable to|has no (?:way|means|tools?) (?:to"
        r"|of)|lacks? (?:the |any )?(?:\w+ )?(?:means |tools? |options? |abilit\w+ )?(?:to|of)) "
        r"(?:escap|flee|run|out-?run|get away|avoid|reach|hit|contest|deal with|touch|fight"
        r"|retaliat|disengag|protect|defend|do (?:much|anything))", 1.0),
    (r"\bfoe (?:lacks?|has no|does not have|doesn't have) (?:any |a |the |good |reliable )*"
        r"(?:mobility|escapes?|range|way|means|self-?heal|defen[cs]e)", DETAIL),
    # "is not a threat to you", "poses little threat", "no match for you"
    (r"(?:\bnot|n't|\bnever|\bhardly|\brarely) (?:\w+ ){0,5}(?:threat|problem|danger)\b"
        r"(?: (?:to|for) you)?", 1.5),
    (r"\b(?:no|little|minimal|almost no|barely any|low) (?:real |actual |direct )?"
        r"(?:threat|danger|risk)\b(?: (?:to|for) you)?", 1.5),
    (r"\bno match for you\b|\bat your mercy\b|\bfavou?rs? you\b"
        r"|\bin your favou?r\b", 1.5),
    (r"\b(?:little|not much|nothing) (?:that )?foe can do\b"
        r"|\bfoe (?:stands?|ha(?:s|ve)) (?:no|little) chance\b", 1.5),
    # "you have the advantage", "you excel", "one of your best match-ups"
    (r"\b(?<!has )(?<!have )%s %s%s\b(?! against you)" % (YOURS, MODAL, WINS), 1.5),
    (r"\badvantage (?:over|against) foe\b|\bsuperior(?:ity)? (?:to|over) foe\b", 1.5),
    (r"\byour (?:\w+ )?(?:best|favou?rite|easiest|favou?rable) (?:match-?ups?|targets?|prey)\b"
        r"|\b(?:easy|favou?rable|good|great|strong) match-?up\b", 1.5),
    (r"\b(?:%s|trouble) (?:to|for) %s\b" % (MENACE, FOE), 1.5),
    (r"\b%s (?:to|for) foe\b" % BAD_FIGHT, 1.5),
    # "you can shut down", "easily kill him", "your X negates his", "absorbed by your"
    (r"\b%s %s%s (?:all (?:of )?|most (?:of )?|much (?:of )?)?foe" % (YOURS, MODAL, DENIES),
        DETAIL),
    (r"\b%s by you" % DENIED, DETAIL),
    (r"\b(?:easily|quickly|instantly|simply|effortlessly|freely) %s foe" % KILL, 1.5),
    (r"\b(?:quick|short) work of foe\b", 1.0),
    (r"\bfoe (?:will |should |may |might )?ha(?:s|ve) (?:a )?(?:hard|difficult|tough|rough)"
        r" time\b|\bfoe (?:will |can )?ha(?:s|ve) (?:trouble|difficulty|problems?)\b", 1.0),
    (r"\bat a (?:\w+ )?disadvantage against you\b", 1.5),
])

# A cue this close after a negation reads the other way, at this fraction.
NEGATION_RE = re.compile(r"(?:\bnot|n't|\bcannot|\bnever|\bno longer|\bhardly|\brarely|\bseldom"
                         r"|\bneither|\bnor)(?: \w+){0,3} ?$", re.I)
NEGATED = 0.5
# A concession gives ground before the point: its cues weigh this fraction.
CONCESSION_RE = re.compile(r"\b(?:while|although|though|even if|despite|unless|if|should"
                           r"|as long as|provided|without|once|when|until)\b[^,;:]*", re.I)
CONCEDED = 0.5
# A sentence's weight by its place: the first whole, each later one less.
PLACE_WEIGHTS = (1.0, 0.6, 0.4, 0.3)
LATER_WEIGHT = 0.2
# The least margin between the two sides a verdict needs.
MARGIN = 1.0


def split_label(cell: str) -> tuple[list[str], str]:
    """'''A | B''' advice -> (['a', 'b'], advice). No label -> ([], cell)."""
    match = LABEL_RE.match(cell)
    if not match or not re.search(r"MATCH-?UP|VS\.?$|RISK|PRIORITY|^TBA", match.group(1), re.I):
        return [], cell
    parts = [part.strip() for part in match.group(1).split("|")]
    return [part for part in parts if part], cell[match.end():]


def _steps(scale: str, vocabulary: Mapping[str, float]) -> float | None:
    """'EVEN -> WEAK' -> the mean of its ends on a vocabulary; None off it."""
    ends = [vocabulary.get(end.strip().lower()) for end in scale.split("->")]
    known = [end for end in ends if end is not None]
    return sum(known) / len(known) if len(known) == len(ends) else None


def read_label(parts: list[str]) -> tuple[float | None, float]:
    """Label parts -> (matchup steps or None, risk weight or 0.0)."""
    steps: float | None = None
    risk = 0.0
    for part in parts:
        matchup, danger = MATCHUP_RATING_RE.match(part), RISK_RATING_RE.match(part)
        if matchup and steps is None:
            steps = _steps(matchup.group(1), MATCHUP_STEPS)
        elif danger:
            risk = _steps(danger.group(1), RISK_WEIGHTS) or 0.0
    return steps, risk


def prose(cell: str) -> str:
    """Every paragraph of a cell's advice as one line of plain text."""
    return " ".join(" ".join(synergies.paragraphs(cell)).split())


def _aliases(hero: str) -> list[str]:
    """What the prose may call a hero, longest first: its name, that name without
    accents and without punctuation, a former name, its nicknames. A former name
    is its name_key, which the aliases' re.I match reads in any case."""
    plain, key = unaccented(hero), name_key(hero)
    names = {hero, plain, "".join(c for c in plain if c.isalnum() or c in " -")}
    names |= {former for former, current in RENAMED.items() if current == key}
    return sorted(names | set(NICKNAMES.get(key, ())), key=len, reverse=True)


def pronoun(text: str) -> str | None:
    """'he' or 'she': the pronoun an article uses of its hero, counted outside
    the match-up section, where the enemies are. None when neither leads."""
    rest = text.replace(synergies.synergy_section(text), "")
    he, she = len(HE_RE.findall(rest)), len(SHE_RE.findall(rest))
    return "he" if he > 2 * she else "she" if she > 2 * he else None


def normalise(text: str, hero: str, other: str, pronouns: Pronouns = (None, None)) -> str:
    """The article hero -> you / your; the enemy -> foe / foe's. he, she, him,
    his, her -> the one of the two whose pronoun it is; where that does not
    tell them apart, the enemy where the text says you, else the last named."""
    sides = [("you", "your", _aliases(hero)), ("foe", "foe's", _aliases(other))]
    named = "|".join("(?P<side%d>%s)" % (i, "|".join(re.escape(n) for n in names))
                     for i, (_, _, names) in enumerate(sides))
    token = re.compile(r"\b(?:(?:%s)|%s)(?P<owns>'s)?(?!\w)" % (named, PRONOUN_RE), re.I)
    text = text.replace("\u2019", "'")
    second_person = bool(SECOND_PERSON_RE.search(text))
    last = sides[-1]

    def replace(match: re.Match[str]) -> str:
        nonlocal last
        for i, side in enumerate(sides):
            if match.group("side%d" % i):
                last = side
                return side[1] if match.group("owns") else side[0]
        said = "he" if HE_RE.fullmatch(match.group(0).split("'")[0]) else "she"
        if pronouns[0] != pronouns[1] and said in pronouns:
            plain, owned, _ = sides[pronouns.index(said)]
        else:
            plain, owned, _ = sides[-1] if second_person else last
        if match.group("owns"):                       # "he's" is "he is"
            return plain + " is"
        return owned if match.group("possessive") else plain

    return token.sub(replace, text)


def sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for end in synergies.SENTENCE_END_RE.finditer(text):
        parts.append(text[start: end.end()])
        start = end.end()
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def score_sentence(sentence: str) -> tuple[float, float]:
    """(advantage, threat) a normalised sentence's cues add, before its place.
    Where cues overlap one counts: a plain one before a negated one, then the
    heavier, then the longer."""
    found = []
    for side, cues in enumerate((ADVANTAGE_CUES, THREAT_CUES)):
        for pattern, weight in cues:
            for match in pattern.finditer(sentence):
                negated = bool(match.groupdict().get("neg")
                               or NEGATION_RE.search(sentence[: match.start()]))
                found.append((negated, -weight, match.start() - match.end(), match.start(),
                              side, match.end()))
    conceded = [m.span() for m in CONCESSION_RE.finditer(sentence)]
    totals = [0.0, 0.0]
    counted: list[tuple[int, int]] = []
    for negated, weight, _, start, side, end in sorted(found):
        if any(start < b and a < end for a, b in counted):
            continue
        counted.append((start, end))
        weight = -weight * (CONCEDED if any(a <= start < b for a, b in conceded) else 1)
        totals[1 - side if negated else side] += weight * (NEGATED if negated else 1)
    return totals[0], totals[1]


def read_cell(cell: str, hero: str, other: str, pronouns: Pronouns = (None, None)) -> Reading:
    """One Match-Up cell -> Reading, from `hero`'s seat about the enemy `other`.
    pronouns is (the hero's, the enemy's), each 'he', 'she' or None."""
    label, advice = split_label(cell)
    steps, risk = read_label(label)
    text = prose(advice)
    if name_key(text) in synergies.PLACEHOLDERS and steps is None and not risk:
        return UNWRITTEN
    if steps is not None and (abs(steps) >= 1 or steps == 0):
        return Reading((steps > 0) - (steps < 0), "rating")

    advantage, threat = max(risk, 0.0), max(-risk, 0.0)
    said = sentences(text)
    read = normalise("\n".join(said), hero, other, pronouns).split("\n") if said else []
    for place, normalised in enumerate(read):
        gained, lost = score_sentence(normalised)
        weight = PLACE_WEIGHTS[place] if place < len(PLACE_WEIGHTS) else LATER_WEIGHT
        advantage, threat = advantage + gained * weight, threat + lost * weight
    margin = advantage - threat
    verdict = ((margin > 0) - (margin < 0)) if abs(margin) >= MARGIN else 0
    return Reading(verdict, "prose")


def parse_matchups(text: str, hero: str,
                   known: Mapping[str, Known]) -> list[tuple[str, Reading]]:
    """[(enemy name, Reading)] - one article's written Match-Up cells. known is
    {name_key: Known}: a template names its rows by key, and the prose is read
    by the roster's name and the pronoun."""
    unknown = Known(name=None, pronoun=None)
    readings = []
    for row in synergies.section_rows(text, synergies.MATCHUP):
        key = hero_key(row.hero)
        if key == name_key(hero):
            continue
        enemy = known.get(key, unknown)
        reading = read_cell(row.cell, hero, enemy.name or row.hero,
                            (known.get(name_key(hero), unknown).pronoun, enemy.pronoun))
        if reading.basis:
            readings.append((row.hero, reading))
    return readings


# (loser id, winner id): a counters row, countered_by_id answering hero_id.
type Edge = tuple[int, int]


def combine(readings_by_hero: Mapping[str, list[tuple[str, Reading]]],
            hero_ids: Mapping[str, int]) -> tuple[set[Edge], list[tuple[int, int]], list[str]]:
    """Readings per article -> ({Edge}, contradicted pairs, unresolved names).
    hero_ids is {name_key: hero_id}."""
    seats: set[Edge] = set()
    unmatched: list[str] = []
    for hero in sorted(readings_by_hero):
        hero_id = hero_ids[name_key(hero)]
        for other, reading in readings_by_hero[hero]:
            other_id = hero_ids.get(hero_key(other))
            if other_id is None:
                unmatched.append("%s: %s" % (hero, other))
            elif other_id != hero_id and reading.verdict:
                winner, loser = ((hero_id, other_id) if reading.verdict > 0
                                 else (other_id, hero_id))
                seats.add((loser, winner))

    contradicted = sorted({(min(pair), max(pair)) for pair in seats if pair[::-1] in seats})
    edges = {pair for pair in seats if pair[::-1] not in seats}
    return edges, contradicted, unmatched


# --- store ---------------------------------------------------------------------

class CountersSummary(ArticlePullSummary):
    counters: int
    articles: int
    cells: int
    rated: int
    no_verdict: int
    contradicted: list[str]
    unwritten: list[str]
    no_edge: list[str]
    unmatched: list[str]


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> CountersSummary:
    """Reload counters from the Match-Up column of every released hero's
    article -> the edges stored, the cells read and what went unanswered."""
    cursor = connection.cursor()
    cursor.execute("SELECT name, hero_id FROM heroes WHERE status = 'released' ORDER BY name")
    released: dict[str, int] = dict(cursor.fetchall())

    articles = fetch_articles(pull, released)
    known = {
        name_key(name): Known(name=name, pronoun=pronoun(articles.found.get(name, "")))
        for name in released}
    readings = {name: parse_matchups(text, name, known) for name, text in articles.found.items()}
    edges, contradicted, unmatched = combine(readings, index(released))
    if not edges:
        raise WikiError("no hero article has a match-up verdict")

    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("DELETE FROM counters")
    for loser, winner in sorted(edges):
        cursor.execute(
            "INSERT INTO counters (hero_id, countered_by_id, source_id) VALUES (%s, %s, %s)",
            (loser, winner, source_id))
    connection.commit()

    names = {hero_id: name for name, hero_id in released.items()}
    cells = [reading for article in readings.values() for _, reading in article]
    in_an_edge = {hero_id for pair in edges for hero_id in pair}
    pull.log(
        "  counters   %d edges from %d articles; %d cells, %d with no verdict;"
        " %d heroes with no edge" % (
            len(edges), sum(1 for r in readings.values() if r), len(cells),
            sum(1 for r in cells if not r.verdict), len(released) - len(in_an_edge)))
    return {"counters": len(edges),
            "articles": sum(1 for r in readings.values() if r),
            "cells": len(cells),
            "rated": sum(1 for r in cells if r.basis == "rating"),
            "no_verdict": sum(1 for r in cells if not r.verdict),
            "contradicted": ["%s / %s" % (names[a], names[b]) for a, b in contradicted],
            "unwritten": sorted(name for name in released if not readings.get(name)),
            "no_edge": sorted(name for name, hero_id in released.items()
                              if hero_id not in in_an_edge),
            "unmatched": unmatched, "missing": articles.missing,
            "tables": ["counters"]}
