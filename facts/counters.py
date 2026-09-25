"""The mechanical counter matrix: who answers whom by the kit alone, for every
ordered pair of released heroes, and the counter graph the default engine
reads - the wiki's edges, and the matrix's where the wiki has none.

    counters.derive(world)                  the load runs it after derive_scalars
    counters.weight(world, loser, winner)   2 a wiki edge, 1 a derived one, 0 none

Thirteen mechanisms each read a strength in [0, 1] off the two heroes' kit
facts; one under FLOOR does not fire, and a pair's score is the fired
strengths' sum, capped at 1. A pair's net is its score less the reverse
pair's. Nothing is fitted to the wiki: every constant below is set from the
kit, the wiki's own rules or the game's roles, and the matrix is measured
against the wiki's graph (AUC) afterwards, never tuned to it.

    antiair     hitscan or fast projectiles at range against a light flier
    flyer       a light flier over a hero with little to shoot up with
    barrier     a weapon or tool that passes barriers against a hero whose
                hit points lean on a placed barrier
    antiheal    anti-heal against self-sustain or healing output
    burst       a single hit of half a non-tank's pool or more, full at a
                one-shot; a movement tool's hit is the dash, read as control
    cc          stun, sleep, hack, knockdown or a damaging grab against a
                channel; those, roots and knockbacks against mobility
    eater       a projectile eater against a main weapon it takes
    eaterproof  a main weapon the loser's eater cannot take
    armor       armor against a main weapon of small hits
    dive        a mobile Initiator or Flanker that kills against an
                immobile backliner
    save        invulnerability and cleanse against anti-heal, control and
                big hits
    range       a reach gap past RANGE_GAP against an immobile hero without
                a barrier
    tankbust    sustained damage through armor against a big tank pool

Against a light flier, cc, burst and dive count only as far as the winner's
anti-air reaches.

Three rules are fixed against the research that first derived the matrix.
An eater reads the per-weapon flags of its own family, which the wiki
publishes for two eaters, each named for it - Defense Matrix
(ignores_matrix) and Deflect (ignores_deflect). Javelin Spin, Kekkai
Sanctuary and Kinetic Grasp have none; their descriptions say what they
take, projectiles ("destroy projectiles", "absorbs enemy projectiles"), so
a hitscan, beam or melee weapon passes them whole, where the research read
Defense Matrix's flags for them and counted a hitscan shot eaten. A weapon
that publishes no reach is guessed at what it covers in PROJECTILE_WINDOW,
or MAX_REACH for hitscan, only where the hero's primary fire publishes none
either: where it does, the kit has said how far the hero fights, and a
secondary fire's silence is unknown, not 57.5 m (Mei's Icicle beside the
Endothermic Blaster's 12). A movement tool's hit (Reinhardt's Charge, 300
pinned to a wall) is not burst: the dash is control, which the cc
mechanism reads, and counting it twice made the charge a one-shot.

The graph. The wiki decides every pair it has an edge on, either way. On a
pair it has none on, the loser's TOP_ANSWERS best derived answers - score
at least THRESHOLD, net above 0, ranked by score, then net, then name -
count at DERIVED_WEIGHT against a wiki edge's WIKI_WEIGHT, so every tally
stays an integer.
"""

import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE
from facts.kit import KitPiece
from facts.model import Hero, World
from facts.records import DerivedEdge, Fired, Pairing
from facts.scalars import CLEANSE_KEYWORDS, FLIGHT_KEYWORDS, FORM_GATED, PILOT_GUNS, PRIMARY_SLOTS
from facts.team import FLIER_REACH

# --- the matrix's rules --------------------------------------------------------
FLOOR = 0.10            # a mechanism weaker than this does not fire
THRESHOLD = 0.50        # a derived edge scores this or more
ULT = 0.30              # an ultimate's tool, against an ability's 1: once a fight at best
# --- the graph -------------------------------------------------------------------
TOP_ANSWERS = 6         # each loser's derived answers, the wiki's 340 edges over 53 heroes
WIKI_WEIGHT = 2         # a wiki edge in a counter tally
DERIVED_WEIGHT = 1      # a derived edge: half a wiki edge, so tallies stay integers
# --- control and saves -----------------------------------------------------------
CD_FULL = 8.0           # s: a control tool on this cooldown or less counts whole; longer, 8/cd
SAVE_CD_FULL = 10.0     # s: the same for an invulnerability or a cleanse
KNOCK = 0.40            # a knockback is soft control: this share of a stun
ROOT_WEIGHT = 0.75      # a root or hinder stops movement, not a channel: this share of a stun
CLEANSE_SAVE = 1.0      # a cleanse's worth as a save
INVULN_SAVE = 0.7       # an invulnerability's: it saves the one who has it, not what is on them
BURST_SAVE = 0.5        # how far a big hit leans on the loser's saves, against control's 1
# a channelled ultimate's share of a hero's reliance on channels, and an ability's
CHANNEL_ULT, CHANNEL_ABILITY = 0.5, 0.5
# a hero's own healing over a fight: a per-second heal for this many seconds,
# its lifesteal over this many seconds of its weapon
SELF_HPS_SECONDS, LIFESTEAL_SECONDS = 3.0, 2.0
# --- eaters ----------------------------------------------------------------------
EATER_UPTIME = 0.20     # a projectile eater up this share of the time counts whole
EAT_FULL_HIT = 60.0     # hp: a main weapon's hit this big is all the eater has to take
EAT_SMALL_SHARE = 0.25  # the least an eater takes from a weapon of small hits
PARTIAL = 0.5           # a flag the wiki writes "partial": the explosion passes
PELLET_SLACK = 1.05     # a pellet's row may run this far over the shot's share of the whole
# the flag family an eater reads, by the word its name holds: the wiki
# publishes these two per weapon; an eater with none takes projectiles alone
FLAG_FAMILIES = {"matrix": "ignores_matrix", "deflect": "ignores_deflect"}
PROJECTILES_RE = re.compile(r"\bprojectiles?\b", re.I)
# the weapons every eater's details say it cannot block, the eaterproof ones
UNBLOCKED = ("beam", "melee")
# --- reach -----------------------------------------------------------------------
FAST_PROJECTILE = 100.0     # m/s: at or above, a projectile hits a flier nearly as hitscan
PROJECTILE_WINDOW = 0.5     # s: a projectile with no published reach reaches what it covers
                            # in this, where the primary fire publishes none either
DEFAULT_PSPEED = 40.0       # m/s: a projectile publishing no speed
MAX_REACH = 60.0            # m: no weapon counts further; a hitscan with no limit reaches it
MELEE_REACH = 4.0           # m: a melee weapon publishing no range
BEAM_REACH = 15.0           # m: a beam publishing no range
MIN_FALLOFF_START = 10.0    # m: a shotgun's falloff starting nearer is a splash, not a reach
# --- anti-air and fliers ---------------------------------------------------------
LIGHT_POOL = 300        # hp: a flier over this pool (D.Va) is no light flier
AA_KIND = {"hitscan": 1.0, "fast projectile": 0.75, "projectile": 0.4, "beam": 0.2,
            "melee": 0.0}    # how well each kind of weapon hits a target in the air
AA_DPS_FULL = 100.0     # dps that makes anti-air whole
AA_BURST_FULL = 150.0   # a hit that makes anti-air whole
FLIGHT_PASSIVE, FLIGHT_ABILITY, FLIGHT_DASH, FLIGHT_ULT = 1.0, 0.6, 0.3, 0.2   # flight's uptime
FLYER_DPS_FULL = 90.0   # dps a flier needs to punish what cannot shoot up
# --- armor, as Orisa's Fortify details state it ------------------------------------
ARMOR_FLAT = 5.0        # hp a hit loses to armor
ARMOR_CAP = 0.5         # at most this share of it
ARMOR_BEAM = 0.30       # a beam's share lost
ARMOR_EFFECT = 0.5      # a piercing effect halves the loss
# --- tanks -----------------------------------------------------------------------
TANK_POOL_LOW, TANK_POOL_SPAN = 400.0, 200.0    # tankness: 0 at 400 hp, 1 at 600
BUST_DPS_LOW, BUST_DPS_SPAN = 90.0, 60.0        # tank-busting: 0 at 90 dps, 1 at 150
# --- burst -----------------------------------------------------------------------
BURST_FROM, BURST_SPAN = 0.5, 0.5   # a hit of half the pool starts it, the whole pool fills it
MELEE_BURST = 0.5       # a melee-only hero's hit must be walked to
MOBILE_DODGE = 0.5      # a mobile target dodges this share of it
ONESHOT_FROM, ONESHOT_SPAN = 150.0, 150.0   # a hit over 150 starts to threaten a one-shot
# --- mobility and dive -------------------------------------------------------------
MOVE_STRONG = frozenset({"strong movement", "flight", "strong flight"})
MOVE_WEAK = frozenset({"movement", "evasive", "active movement", "partial movement"})
STRONG_MOVE, WEAK_MOVE = 1.0, 0.5   # a movement tool's worth
MOBILITY_FULL = 1.5     # one strong tool and one weak one make a hero fully mobile
MOBILE_FROM = 0.34      # mobility under this (one weak tool) is nothing a lock takes away
KILL_WINDOW = 1.5       # s of sustained fire a diver lands, plus its biggest hit
KILL_FROM, KILL_SPAN = 0.4, 0.6     # a combo of 40% of the pool starts it, 100% fills it
ESCAPE_KEEPS = 0.5      # an invulnerable escape halves a backliner's exposure
# the Sub-Roles article: Initiators and Flankers go in for key or low-health
# targets; Sharpshooters hold the back line; Tacticians and Medics heal from it
DIVERS = ("Initiator", "Flanker")
BACKLINE = ("Sharpshooter", "Tactician", "Medic")
BACKLINE_REACH, MIDLINE_REACH = 40.0, 30.0  # m: a weapon this long holds the back, the middle
# --- range -----------------------------------------------------------------------
RANGE_GAP = 10.0        # m: a reach gap this small is none
RANGE_SPAN = 30.0       # m: a gap this much past RANGE_GAP is whole
RANGE_DPS_FULL = 90.0   # dps that makes the range whole
# --- keyword families ----------------------------------------------------------------
INTERRUPT = frozenset({"stun", "sleep", "hacked", "knockdown"})
ROOT = frozenset({"immobilize", "hinder"})
GRAB = frozenset({"displace", "break"})
SAVE = frozenset({"invulnerable", "phased"})
CLEANSE = frozenset(CLEANSE_KEYWORDS)
FLIGHT = frozenset(FLIGHT_KEYWORDS)
# a damage row that is a sum, a damage over time or the hero's own
SUMMED_RE = re.compile(r"total|over time|\bdot\b|burn|wound|self|if all|both|maximum", re.I)


def _clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def _cd_weight(piece: KitPiece, full: float) -> float:
    """A tool's weight by its cooldown: whole at `full` seconds or less, an
    ultimate's ULT."""
    if piece.kind == KIND_ULTIMATE:
        return ULT
    cooldown = piece.max_stat("cooldown")
    return _clamp(full / cooldown) if cooldown else 1.0


def _kind(piece: KitPiece) -> str:
    """melee, beam, hitscan or projectile, by the wiki's weapon type."""
    typed = piece.weapon_kind
    for kind in ("melee", "beam", "hitscan"):
        if kind in typed:
            return kind
    return "projectile"


def _flag(piece: KitPiece, code: str) -> float:
    """The share of the piece an eater of `code`'s family takes: no row, 0
    or 'no' whole; 'partial' (the explosion passes) PARTIAL; 1 none."""
    rows = piece.stats.get(code, ())
    if not rows:
        return 1.0
    first = rows[0]
    if first.value is not None:
        return 0.0 if first.value >= 1 else 1.0
    return PARTIAL if (first.text or "").strip().lower() == "partial" else 1.0


def _per_hit(piece: KitPiece) -> float | None:
    """The damage one instance of a weapon deals at its best - a pellet, a
    bullet, a shot - not a sum, a damage over time or a row on the hero."""
    values = [s.value for s in piece.stats.get("damage", ())
                if s.value is not None and s.unit_den is None and s.unit_num != "percent"
                and not SUMMED_RE.search("%s %s" % (s.condition or "", s.text or ""))]
    if not values:
        return None
    pellets = piece.max_stat("pellets") or 1
    if pellets >= 2:
        cap = max(values) / pellets * PELLET_SLACK
        small = [v for v in values if v <= cap]
        return max(small) if small else max(values) / pellets
    return max(values)


class Reach(NamedTuple):
    """How far a weapon fights, in metres, and whether the kit publishes it
    (a range, a falloff, a melee's or a beam's reach) or it is guessed."""
    metres: float
    published: bool


def _reach(piece: KitPiece) -> Reach:
    """A melee or beam weapon's range; a shotgun's where its falloff starts;
    else the published limit; else a guess - MAX_REACH for hitscan, what a
    projectile covers in PROJECTILE_WINDOW."""
    kind = _kind(piece)
    if kind == "melee":
        return Reach(piece.reach or MELEE_REACH, True)
    if "shotgun" in piece.weapon_kind and not piece.stats.get("range"):
        starts = [s.value for s in piece.stats.get("damage_falloff_range", ())
                  if s.value is not None and s.value >= MIN_FALLOFF_START
                  and "min" in (s.condition or "") and "simultaneous" not in (s.condition or "")]
        if starts:
            return Reach(min(starts), True)
    if piece.reach:
        return Reach(min(MAX_REACH, piece.reach), True)
    if kind == "beam":
        return Reach(BEAM_REACH, True)
    if kind == "hitscan":
        return Reach(MAX_REACH, False)
    speed = piece.max_stat("pspeed") or DEFAULT_PSPEED
    return Reach(min(MAX_REACH, speed * PROJECTILE_WINDOW), False)


def _fights(guns: Sequence[KitPiece]) -> list[tuple[KitPiece, float]]:
    """Each weapon the hero fights with and its reach. A guessed reach stands
    only where no primary fire publishes one: the kit has said how far the
    hero fights."""
    reaches = [(g, _reach(g)) for g in guns]
    said = any(r.published for g, r in reaches if g.extra.get("slot") in PRIMARY_SLOTS)
    return [(g, r.metres) for g, r in reaches if r.published or not said]


@dataclass(frozen=True, slots=True, kw_only=True)
class Features:
    """What the mechanisms read of one hero: its kit facts, each strength in
    [0, 1] unless a unit says otherwise, and the pieces that set them."""
    id: int
    name: str
    role: str
    subrole: str
    pool: int
    armor: float
    armor_share: float
    dps: float
    burst: float
    burst_piece: str
    melee_only: bool
    main: KitPiece | None
    main_kind: str
    main_hit: float
    instance: float
    armor_loss: float
    range: float
    range_weapon: str
    aa: float
    aa_weapon: str
    aa_kind: str
    aa_reach: float
    flight: float
    flight_piece: str
    mobility: float
    mobile: float
    mobility_pieces: tuple[str, ...]
    diver: float
    escape: tuple[str, ...]
    cc_int: float
    cc_deny: float
    cc_int_pieces: tuple[str, ...]
    cc_deny_pieces: tuple[str, ...]
    channel: float
    channel_pieces: tuple[str, ...]
    save: float
    save_pieces: tuple[str, ...]
    antiheal: float
    antiheal_piece: str
    self_sustain: float
    heal_out: float
    heal_rel: float
    barrier: float
    barrier_piece: str
    barrier_share: float
    pierce: float
    pierce_piece: str
    eater: float
    eater_piece: str
    eater_family: str | None
    eaten: float            # the share of the main weapon a matrix-family eater takes
    deflected: float        # a deflect-family eater's
    projectile_main: bool   # the main weapon is a projectile, all a family-less eater takes
    percent_ult: str
    tankness: float
    backline: float
    oneshot_risk: float


def _movement(piece: KitPiece) -> bool:
    return bool(piece.keywords & (MOVE_STRONG | MOVE_WEAK))


def _main(steady: Sequence[KitPiece]) -> KitPiece | None:
    """The weapon the hero fights with: the highest sustained rate, then
    name; a scoped config of it that hits harder in its place."""
    rated = [(w.rate("dps", "damage") or 0.0, w.name, i) for i, w in enumerate(steady)]
    if not rated:
        return None
    main = steady[max(rated)[2]]
    for w in steady:
        if (w.extra.get("slot") == "ads" and w.rate("dps", "damage")
                and w.name.startswith(main.name)
                and max(w.hits() or [0.0]) > max(main.hits() or [0.0])):
            main = w
    return main


def _burst(h: Hero) -> tuple[float, str]:
    """The biggest single hit of a piece that is not a movement tool, a
    headshot where one counts, and the piece."""
    best, where = 0.0, ""
    for piece in (*h.weapons, *(a for a in h.abilities if a.kind != KIND_ULTIMATE)):
        if piece.name in PILOT_GUNS or (piece.kind == KIND_ABILITY and _movement(piece)):
            continue
        hits = [*piece.hits(), *([c] if (c := piece.cast_hit()) else [])]
        if hits and max(hits) > best:
            best, where = max(hits), piece.name
    return best, where


def _anti_air(h: Hero, fights: Sequence[tuple[KitPiece, float]],
                burst: float) -> tuple[float, str, str, float]:
    """The best weapon against a target in the air: (strength, weapon, kind,
    reach)."""
    best = (0.0, "", "", 0.0)
    for w, metres in fights:
        kind = _kind(w)
        if kind == "projectile" and (w.max_stat("pspeed") or 0.0) >= FAST_PROJECTILE:
            kind = "fast projectile"
        best = max(best, (AA_KIND[kind] * _clamp(metres / FLIER_REACH), w.name, kind, metres))
    punch = _clamp(max(h.dps / AA_DPS_FULL, burst / AA_BURST_FULL))
    return best[0] * punch, best[1], best[2], best[3]


def _flight(h: Hero) -> tuple[float, str]:
    """How much of a fight the hero spends in the air, and the piece."""
    best, where = 0.0, ""
    for a in h.abilities:
        if not a.keywords & FLIGHT:
            continue
        up = (FLIGHT_PASSIVE if a.kind == KIND_PASSIVE else FLIGHT_ULT if a.kind == KIND_ULTIMATE
                else FLIGHT_DASH if "evasive" in a.keywords else FLIGHT_ABILITY)
        if up > best:
            best, where = up, a.name
    return (0.0, "") if h.pool > LIGHT_POOL else (best, where)


def _control(h: Hero) -> tuple[float, float, tuple[str, ...], tuple[str, ...]]:
    """(interrupt, deny, the interrupting pieces, every controlling piece):
    each tool by its cooldown, summed and capped."""
    interrupt = deny = 0.0
    by_interrupt: list[str] = []
    by_deny: list[str] = []
    for a in h.abilities:
        if a.kind not in (KIND_ABILITY, KIND_ULTIMATE) or a.for_allies:
            continue
        w = _cd_weight(a, CD_FULL)
        if a.keywords & INTERRUPT or (a.keywords & GRAB and a.damages):
            interrupt += w
            deny += w
            by_interrupt.append("%s (%s)" % (
                a.name, "/".join(sorted(a.keywords & (INTERRUPT | GRAB)))))
        elif a.keywords & ROOT:
            deny += ROOT_WEIGHT * w
            by_deny.append("%s (%s)" % (a.name, "/".join(sorted(a.keywords & ROOT))))
        elif a.shoves and a.damages and not _movement(a):
            deny += KNOCK * w
            by_deny.append("%s (knockback)" % a.name)
    return _clamp(interrupt), _clamp(deny), tuple(by_interrupt), tuple(by_interrupt + by_deny)


def _eater(h: Hero) -> tuple[float, str, str | None]:
    """The hero's best projectile eater: its strength (uptime over
    EATER_UPTIME, an ultimate ULT), its evidence and its flag family (None:
    it takes projectiles alone)."""
    best: tuple[float, str, str | None] = (0.0, "", None)
    for a in h.abilities:
        if "negate projectile" not in a.keywords or a.kind not in (KIND_ABILITY, KIND_ULTIMATE):
            continue
        if a.kind == KIND_ULTIMATE:
            strength, said = ULT, "ultimate"
        else:
            lasts, wait = a.max_stat("duration") or 0.0, a.max_stat("cooldown") or 0.0
            up = lasts / (lasts + wait) if lasts + wait else 0.0
            strength, said = _clamp(up / EATER_UPTIME), "up %.0f%%" % (100 * up)
        words = set(a.name.lower().split())
        family = next((code for word, code in FLAG_FAMILIES.items() if word in words), None)
        if family is None and not PROJECTILES_RE.search(a.description or ""):
            continue
        if strength > best[0]:
            verb = "reflects" if family == "ignores_deflect" else "eats"
            best = (strength, "%s (%s projectiles, %s)" % (a.name, verb, said), family)
    return best


def features(h: Hero, support_hps: float) -> Features:
    """The facts every mechanism reads of one hero. support_hps is the
    roster's best support's sustained healing, which heal_out is a share of."""
    steady = [w for w in h.weapons if w.damages and w.name not in FORM_GATED]
    main = _main(steady)
    fights = _fights(steady)
    burst, burst_piece = _burst(h)
    reach, range_weapon = max(((m, w.name) for w, m in fights), default=(0.0, ""))
    aa, aa_weapon, aa_kind, aa_reach = _anti_air(h, fights, burst)
    flight, flight_piece = _flight(h)
    moves = [a for a in h.abilities
                if a.kind in (KIND_ABILITY, KIND_PASSIVE) and not a.for_allies and _movement(a)]
    mobility = _clamp(sum(STRONG_MOVE if a.keywords & MOVE_STRONG else WEAK_MOVE for a in moves)
                      / MOBILITY_FULL)
    cc_int, cc_deny, int_pieces, deny_pieces = _control(h)
    ult_channels = [a.name for a in h.abilities
                    if a.kind == KIND_ULTIMATE and "channel" in a.keywords]
    channels = [a.name for a in h.abilities if a.kind == KIND_ABILITY and "channel" in a.keywords
                and not a.for_allies and not _movement(a)]
    saves = [a for a in h.abilities if a.kind in (KIND_ABILITY, KIND_ULTIMATE)
                and a.keywords & (SAVE | CLEANSE)]
    save = _clamp(sum((CLEANSE_SAVE if a.keywords & CLEANSE else INVULN_SAVE)
                      * _cd_weight(a, SAVE_CD_FULL) for a in saves))
    antiheal, antiheal_piece = 0.0, ""
    for a in h.abilities:
        for s in a.stats.get("healing_mod", ()):
            if s.value is not None and s.value < 0 and (s.condition or "") != "allies":
                strength = -s.value / 100.0 * (ULT if a.kind == KIND_ULTIMATE else 1.0)
                if strength > antiheal:
                    antiheal, antiheal_piece = strength, "%s (%+g%% healing received)" % (
                        a.name, s.value)
    own = h.self_heal + SELF_HPS_SECONDS * h.self_hps + LIFESTEAL_SECONDS * h.lifesteal * h.dps
    self_sustain = _clamp(own / h.pool) if h.pool else 0.0
    heal_out = _clamp(h.hps / support_hps) if support_hps else 0.0
    barriers = [(a.max_stat("barrier_health") or 0.0, a.name) for a in h.abilities
                if a.kind == KIND_ABILITY and "barrier" in a.keywords
                and not a.keywords & {"bubble", "attached"}]
    barrier, barrier_piece = max(barriers, default=(0.0, ""))
    pierce, pierce_piece = _pierce(steady, h.abilities)
    eater, eater_piece, eater_family = _eater(h)
    hit = (max(main.hits() or [0.0]) or _per_hit(main) or 0.0) if main else 0.0
    instance = (_per_hit(main) or hit or 1.0) if main else 0.0
    main_kind = _kind(main) if main else "none"
    armor = h.armor + h.form_armor
    return Features(
        id=h.id, name=h.name, role=h.role, subrole=h.subrole, pool=h.pool, armor=armor,
        armor_share=armor / (h.pool + h.form_armor) if h.pool else 0.0, dps=h.dps,
        burst=burst, burst_piece=burst_piece, melee_only=h.melee_only, main=main,
        main_kind=main_kind, main_hit=hit, instance=instance,
        armor_loss=_armor_loss(main, main_kind, instance) if main else 0.0,
        range=reach, range_weapon=range_weapon, aa=aa, aa_weapon=aa_weapon, aa_kind=aa_kind,
        aa_reach=aa_reach, flight=flight, flight_piece=flight_piece, mobility=mobility,
        mobile=_clamp((mobility - MOBILE_FROM) / (1.0 - MOBILE_FROM)),
        mobility_pieces=tuple(a.name for a in moves),
        diver=1.0 if h.subrole in DIVERS else 0.0,
        escape=tuple(sorted(a.name for a in h.abilities if a.kind == KIND_ABILITY
                            and a.keywords & SAVE and not a.for_allies)),
        cc_int=cc_int, cc_deny=cc_deny, cc_int_pieces=int_pieces, cc_deny_pieces=deny_pieces,
        channel=CHANNEL_ULT * bool(ult_channels) + CHANNEL_ABILITY * bool(channels),
        channel_pieces=tuple(ult_channels + channels), save=save,
        save_pieces=tuple(a.name for a in saves),
        antiheal=_clamp(antiheal), antiheal_piece=antiheal_piece, self_sustain=self_sustain,
        heal_out=heal_out, heal_rel=max(self_sustain, heal_out), barrier=barrier,
        barrier_piece=barrier_piece,
        barrier_share=barrier / (barrier + h.pool) if barrier else 0.0, pierce=pierce,
        pierce_piece=pierce_piece, eater=eater, eater_piece=eater_piece,
        eater_family=eater_family,
        eaten=_flag(main, "ignores_matrix") * _clamp(hit / EAT_FULL_HIT, EAT_SMALL_SHARE)
        if main else 0.0,
        deflected=_flag(main, "ignores_deflect") * _clamp(hit / EAT_FULL_HIT, EAT_SMALL_SHARE)
        if main else 0.0,
        projectile_main=main_kind == "projectile",
        percent_ult=next((u.name for u in h.ults if any(
            s.unit_num == "percent" for s in u.stats.get("damage", ()))), ""),
        tankness=_clamp((h.pool - TANK_POOL_LOW) / TANK_POOL_SPAN) if h.role == "tank" else 0.0,
        backline=1.0 if h.subrole in BACKLINE or reach >= BACKLINE_REACH else (
            0.5 if reach >= MIDLINE_REACH else 0.0),
        oneshot_risk=_clamp((burst - ONESHOT_FROM) / ONESHOT_SPAN))


def _pierce(steady: Sequence[KitPiece], abilities: Sequence[KitPiece]) -> tuple[float, str]:
    """How the hero passes a barrier: its weapon whole, else a damaging
    ability at half, else an ultimate at ULT."""
    for w in steady:
        if (w.max_stat("ignores_barrier") or 0) >= 1 or "barrier piercing" in w.keywords:
            return 1.0, "%s (weapon passes barriers)" % w.name
    best, where = 0.0, ""
    for a in abilities:
        if a.kind in (KIND_ABILITY, KIND_ULTIMATE) and a.damages and not a.for_allies and (
                "barrier piercing" in a.keywords or (a.max_stat("ignores_barrier") or 0) >= 1):
            strength = ULT if a.kind == KIND_ULTIMATE else PARTIAL
            if strength > best:
                best, where = strength, "%s (passes barriers)" % a.name
    return best, where


def _armor_loss(main: KitPiece, kind: str, instance: float) -> float:
    """The share of the main weapon's hit armor takes."""
    piercing = main.qualifiers("armor piercing") if "armor piercing" in main.keywords else None
    if piercing is not None and "effect" not in piercing:
        return 0.0
    loss = ARMOR_BEAM if kind == "beam" else min(ARMOR_FLAT, ARMOR_CAP * instance) / instance
    return loss * ARMOR_EFFECT if piercing is not None else loss


# --- the mechanisms: each (winner, loser) -> its strength and what fired it -------

class Reading(NamedTuple):
    """What one mechanism reads of a pair: its strength, the words the board
    says it with, and the numbers that fired it."""
    strength: float
    phrase: str
    numbers: str


type Mechanism = Callable[[Features, Features], Reading]
NONE = Reading(0.0, "", "")


def _main_name(hero: Features) -> str:
    return hero.main.name if hero.main is not None else "-"


def _reachable(win: Features, lose: Features) -> float:
    """The share of the loser in reach: a light flier only as far as the
    winner's anti-air."""
    return 1.0 - lose.flight * (1.0 - win.aa)


def m_antiair(win: Features, lose: Features) -> Reading:
    return Reading(win.aa * lose.flight, "%s against a flier" % (win.aa_kind or "fire"),
                   "%s, %s, %.0f m; %s flies with %s" % (
                       win.aa_weapon, win.aa_kind, win.aa_reach, lose.name, lose.flight_piece))


def m_flyer(win: Features, lose: Features) -> Reading:
    return Reading(win.flight * (1.0 - lose.aa) * _clamp(win.dps / FLYER_DPS_FULL),
                   "a flier over a hero that cannot shoot up",
                   "%s flies with %s; %s's best anti-air %s, %.2f" % (
                       win.name, win.flight_piece, lose.name, lose.aa_weapon or "none", lose.aa))


def m_barrier(win: Features, lose: Features) -> Reading:
    return Reading(win.pierce * lose.barrier_share, "passes the barrier it leans on",
                   "%s; %s's %s, %.0f hp, %.0f%% of its hit points" % (
                       win.pierce_piece, lose.name, lose.barrier_piece, lose.barrier,
                       100 * lose.barrier_share))


def m_antiheal(win: Features, lose: Features) -> Reading:
    what = ("self-sustain %.0f%% of its pool" % (100 * lose.self_sustain)
            if lose.self_sustain >= lose.heal_out else "healing %.0f%% of the best support's"
            % (100 * lose.heal_out))
    return Reading(win.antiheal * lose.heal_rel, "anti-heal against its healing",
                   "%s; %s's %s" % (win.antiheal_piece, lose.name, what))


def m_burst(win: Features, lose: Features) -> Reading:
    if lose.role == "tank" or not win.burst:
        return NONE
    strength = (_clamp((win.burst / lose.pool - BURST_FROM) / BURST_SPAN)
                * (MELEE_BURST if win.melee_only else 1.0) * (1.0 - MOBILE_DODGE * lose.mobile)
                * _reachable(win, lose))
    return Reading(strength, "burst against its pool", "%s %.0f in one hit; %s %d hp%s" % (
        win.burst_piece or "a hit", win.burst, lose.name, lose.pool,
        ", mobile %.2f" % lose.mobile if lose.mobile else ""))


def m_cc(win: Features, lose: Features) -> Reading:
    interrupt = win.cc_int * lose.channel * _reachable(win, lose)
    deny = win.cc_deny * lose.mobile * _reachable(win, lose)
    if interrupt >= deny:
        return Reading(interrupt, "control against its channel", "%s; %s channels %s" % (
            ", ".join(win.cc_int_pieces), lose.name, ", ".join(lose.channel_pieces)))
    return Reading(deny, "control against its mobility", "%s; %s moves with %s" % (
        ", ".join(win.cc_deny_pieces), lose.name, ", ".join(lose.mobility_pieces)))


def _taken(eater_family: str | None, lose: Features) -> float:
    """The share of the loser's main weapon an eater of this family takes: a
    family's own flags, else projectiles alone, read by Defense Matrix's."""
    if eater_family == "ignores_deflect":
        return lose.deflected
    return lose.eaten if eater_family is not None or lose.projectile_main else 0.0


def m_eater(win: Features, lose: Features) -> Reading:
    return Reading(win.eater * _taken(win.eater_family, lose), "eats its main weapon",
                   "%s; %s's %s, %s, %.0f a hit" % (
                       win.eater_piece, lose.name, _main_name(lose), lose.main_kind,
                       lose.main_hit))


def m_eaterproof(win: Features, lose: Features) -> Reading:
    """The eater's mirror: a main weapon the loser's eater cannot take,
    against a hero that leans on its eater."""
    if not lose.eater or win.main is None:
        return NONE
    family = lose.eater_family
    if family is not None:
        passes = 1.0 - _flag(win.main, family)
    elif win.main_kind in UNBLOCKED:
        passes = 1.0
    else:
        # a family-less eater's domain is projectiles: a hitscan weapon is
        # outside it, neither taken nor proof against it
        passes = 1.0 - _flag(win.main, "ignores_matrix") if win.projectile_main else 0.0
    return Reading(lose.eater * passes, "a weapon its eater cannot take", "%s's %s, %s; %s's %s" % (
        win.name, win.main.name, win.main_kind, lose.name, lose.eater_piece))


def m_armor(win: Features, lose: Features) -> Reading:
    return Reading(win.armor_share * lose.armor_loss / ARMOR_CAP, "armor against its small hits",
                   "%s armor %.0f; %s's %s, %s, %.1f a hit, %.0f%% lost to armor" % (
                       win.name, win.armor, lose.name, _main_name(lose), lose.main_kind,
                       lose.instance, 100 * lose.armor_loss))


def m_dive(win: Features, lose: Features) -> Reading:
    kill = _clamp(((win.dps * KILL_WINDOW + win.burst) / lose.pool - KILL_FROM) / KILL_SPAN)
    exposed = lose.backline * (1.0 - lose.mobility) * (ESCAPE_KEEPS if lose.escape else 1.0)
    return Reading(win.diver * win.mobility * exposed * kill * _reachable(win, lose),
                   "dives its back line", "%s (%s) moves with %s; %s holds %.0f m, mobility "
                   "%.2f%s; %.0f dps + %.0f against %d hp" % (
                       win.name, win.subrole, ", ".join(win.mobility_pieces), lose.name, lose.range,
                       lose.mobility, ", escape " + "/".join(lose.escape) if lose.escape else "",
                       win.dps, win.burst, lose.pool))


def m_save(win: Features, lose: Features) -> Reading:
    reliance = max(lose.antiheal, lose.cc_int, BURST_SAVE * lose.oneshot_risk)
    if reliance == lose.antiheal:
        phrase, what = "saves against its anti-heal", lose.antiheal_piece
    elif reliance == lose.cc_int:
        phrase, what = "saves against its control", ", ".join(lose.cc_int_pieces)
    else:
        phrase, what = "saves against its burst", "a %.0f hit" % lose.burst
    return Reading(win.save * reliance, phrase, "%s; %s's %s" % (
        "/".join(win.save_pieces), lose.name, what))


def m_range(win: Features, lose: Features) -> Reading:
    gap = win.range - lose.range - RANGE_GAP
    strength = (_clamp(gap / RANGE_SPAN) * (1.0 - lose.mobility) * (1.0 - lose.barrier_share)
                * _clamp(win.dps / RANGE_DPS_FULL))
    return Reading(strength, "outranges it", "%s %.0f m; %s's %s %.0f m, mobility %.2f" % (
        win.range_weapon, win.range, lose.name, lose.range_weapon, lose.range, lose.mobility))


def m_tankbust(win: Features, lose: Features) -> Reading:
    if not lose.tankness:
        return NONE
    through = win.dps * (1.0 - win.armor_loss * lose.armor_share)
    bust = _clamp((through - BUST_DPS_LOW) / BUST_DPS_SPAN)
    if win.percent_ult:
        bust = max(bust, ULT)
    return Reading(lose.tankness * bust, "tank-busting damage", "%.0f dps, %.0f through armor%s; "
                   "%s %d hp" % (win.dps, through, ", %s's percent damage" % win.percent_ult
                                 if win.percent_ult else "", lose.name, lose.pool))


MECHANISMS: tuple[tuple[str, Mechanism], ...] = (
    ("antiair", m_antiair), ("flyer", m_flyer), ("barrier", m_barrier),
    ("antiheal", m_antiheal), ("burst", m_burst), ("cc", m_cc), ("eater", m_eater),
    ("eaterproof", m_eaterproof), ("armor", m_armor), ("dive", m_dive), ("save", m_save),
    ("range", m_range), ("tankbust", m_tankbust))


def pairing(win: Features, lose: Features) -> Pairing:
    """The winner against the loser: every mechanism that fires, strongest
    first, and the score, their sum capped at 1."""
    fired = [Fired(name, round(r.strength, 3), r.phrase, r.numbers)
                for name, fn in MECHANISMS for r in (fn(win, lose),) if r.strength >= FLOOR]
    fired.sort(key=lambda f: (-f.strength, f.mechanism))
    return Pairing(score=round(_clamp(math.fsum(f.strength for f in fired)), 3),
                   fired=tuple(fired))


def derive(world: World) -> None:
    """The matrix over the released heroes (world.matrix, {(winner, loser):
    Pairing}) and the derived edges the graph fills with (world.derived,
    {(loser, winner): DerivedEdge}): each loser's TOP_ANSWERS best answers
    on the pairs the wiki has no edge on. Deterministic: heroes by id,
    ties by name."""
    released = sorted((h for h in world.heroes.values() if h.released), key=lambda h: h.id)
    supports = [h.hps for h in released if h.role == "support"]
    feats = {h.id: features(h, max(supports, default=0.0)) for h in released}
    world.matrix = {(win.id, lose.id): pairing(feats[win.id], feats[lose.id])
                    for win in released for lose in released if win.id != lose.id}
    world.derived = {}
    for loser in released:
        answers = sorted(
            ((pair.score, round(pair.score - world.matrix[(loser.id, w)].score, 3), w)
                for (w, lose), pair in world.matrix.items() if lose == loser.id),
            key=lambda t: (-t[0], -t[1], world.heroes[t[2]].name))
        top = [(score, net, w) for score, net, w in answers
                if score >= THRESHOLD and net > 0][:TOP_ANSWERS]
        for score, net, w in top:
            if (loser.id, w) in world.counters or (w, loser.id) in world.counters:
                continue
            world.derived[(loser.id, w)] = DerivedEdge(
                winner=w, loser=loser.id, score=score, net=net,
                fired=world.matrix[(w, loser.id)].fired)


def weight(world: World, loser: int, winner: int) -> int:
    """How much winner answering loser counts in a tally: WIKI_WEIGHT for
    a wiki edge, DERIVED_WEIGHT for a derived one on a pair the wiki leaves
    out, 0 else - a wiki edge the other way included."""
    if (loser, winner) in world.counters:
        return WIKI_WEIGHT
    if (winner, loser) in world.counters:
        return 0
    return DERIVED_WEIGHT if (loser, winner) in world.derived else 0


def said(world: World, edge: DerivedEdge) -> str:
    """A derived edge as the board words it: 'Soldier: 76 answers Pharah -
    derived: hitscan against a flier (Heavy Pulse Rifle, hitscan, 60 m;
    Pharah flies with Hover Jets)', every mechanism that fired, strongest
    first."""
    return "%s answers %s - derived: %s" % (
        world.heroes[edge.winner].name, world.heroes[edge.loser].name,
        "; ".join("%s (%s)" % (f.phrase, f.numbers) for f in edge.fired))


def auc(world: World, edges: Iterable[tuple[int, int]] | None = None) -> float:
    """How well the matrix's score ranks the wiki's edges above every other
    ordered pair of released heroes: the Mann-Whitney AUC, ties counted
    half. edges are (loser, winner), the wiki's counters by default."""
    wiki = set(world.counters if edges is None else edges)
    scores = [(pair.score, (lose, win) in wiki) for (win, lose), pair in world.matrix.items()]
    scores.sort()
    positives = sum(1 for _, edge in scores if edge)
    negatives = len(scores) - positives
    if not positives or not negatives:
        return math.nan
    rank_sum, i = 0.0, 0
    while i < len(scores):
        j = i
        while j < len(scores) and scores[j][0] == scores[i][0]:
            j += 1
        rank_sum += (i + j + 1) / 2.0 * sum(1 for k in range(i, j) if scores[k][1])
        i = j
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)
