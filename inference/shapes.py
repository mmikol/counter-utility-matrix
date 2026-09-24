"""The legal shapes: the (tanks, damage, supports) triples the queue allows -
at most MAX_TANKS tanks, whatever the playbook holds - and the playbook's
shape-only hard limits allow (its own rule of form, 2-2-2 say), around
whatever picks are locked.
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from inference.expr import Expr, scope
from inference.strategy import Strategy
from ui.facts.draft import MAX_TANKS, TEAM_SIZE

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size", "team.open_slots"}


class Shape(NamedTuple):
    """A team's count per role: a six's shape, or the picks locked so far."""
    tanks: int
    damage: int
    supports: int


NO_PICKS = Shape(0, 0, 0)


def legal_shapes(catalog: Iterable[Strategy], locked: Shape = NO_PICKS) -> list[Shape]:
    """(tanks, damage, supports) triples the queue allows - at most MAX_TANKS
    tanks, whatever the playbook holds - and the catalog's shape-only hard
    limits allow (a playbook's own rule of form, 2-2-2 say), only those that
    can still seat the `locked` picks. The board carries the full list so the
    roster can refuse a pick no legal six could seat."""
    limits = _shape_limits(catalog)
    out: list[Shape] = []
    for t in range(MAX_TANKS + 1):
        for d in range(TEAM_SIZE + 1 - t):
            s = TEAM_SIZE - t - d
            if t < locked.tanks or d < locked.damage or s < locked.supports:
                continue
            if _shape_allowed(t, d, s, limits):
                out.append(Shape(t, d, s))
    return out


def _shape_limits(catalog: Iterable[Strategy]) -> list[tuple[Strategy, Expr]]:
    """The catalog's hard limits that read only a six's shape, each with its
    require."""
    return [(h, h.require) for h in catalog
            if h.form == "limit" and not h.soft and h.require
            and set(h.require.names) <= SHAPE_KEYS
            and (h.when is None or set(h.when.names) <= SHAPE_KEYS)]


def _shape_allowed(t: int, d: int, s: int, limits: Sequence[tuple[Strategy, Expr]]) -> bool:
    """Whether a (tanks, damage, supports) triple meets every shape limit whose
    `when` holds on it."""
    stub = scope({"team": {"tanks": t, "damage": d, "supports": s,
                           "size": TEAM_SIZE, "open_slots": 0}})
    for h, require in limits:
        stub["params"] = h.params_section
        if (h.when is None or bool(h.when.evaluate(stub))) and not bool(require.evaluate(stub)):
            return False
    return True
