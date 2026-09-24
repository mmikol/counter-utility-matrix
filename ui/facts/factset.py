"""The FactSet: a board's facts numbered F1.. and the playbook's record S1..

A Fact is one sentence and the structured claim behind it (scope, subject,
key, value, unit, source); the FactSet numbers them in emission order and
files each under the metrics it states, so the inference layer finds a fact
by metric and a person reads the same facts as numbered sentences.
ui.facts.board_facts writes a board's facts into one.
"""

from collections.abc import Iterable, Sequence
from typing import Any


class Fact:
    __slots__ = (
        "id",
        "key",
        "scope",
        "source",
        "subject",
        "team",
        "text",
        "unit",
        "value",
    )

    def __init__(self, fid: str, scope: str, subject: str, team: str | None, key: str,
                 text: str, value: Any, unit: str | None, source: str) -> None:
        # value is what the fact states - a number, a name, a list or a record
        # of them - and JSON once _plain has read it; its readers know its shape
        self.id, self.scope, self.subject, self.team = fid, scope, subject, team
        self.key, self.text, self.value, self.unit, self.source = (
            key, text, value, unit, source)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "scope": self.scope, "subject": self.subject,
                "team": self.team, "key": self.key, "text": self.text,
                "value": _plain(self.value), "unit": self.unit,
                "source": self.source}


def _plain(value: object) -> object:
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


PLAYBOOK_SCOPE = "playbook"
PLAYBOOK_DIVIDER = "-- the playbook's record: what it holds - not facts --"


class FactSet:
    """The facts (F1..) and the playbook's record (S1..) of one board. Both
    live in `facts` in order, so a citation of either resolves; `count` is
    the facts alone."""

    def __init__(self, map_name: str | None = None, red: Iterable[str] = (),
                 blue: Iterable[str] = (), bans: Iterable[str] = (), side: str = "") -> None:
        self.map_name, self.red, self.blue = map_name, list(red), list(blue)
        self.bans, self.side = list(bans), side
        self.facts: list[Fact] = []
        self._by_key: dict[tuple[str, str], list[Fact]] = {}
        self._n = {"F": 0, "S": 0}

    def add(self, scope: str, subject: str, key: str, text: str, value: object = None,
            unit: str | None = None, source: str = "", team: str | None = None,
            also: Sequence[str] = ()) -> str:
        """`also` names the other metrics this one sentence states, so a caller
        looking for one of them finds the fact that carries it. The fact keeps
        the key it is worded around; `also` only adds index entries."""
        prefix = "S" if scope == PLAYBOOK_SCOPE else "F"
        self._n[prefix] += 1
        fid = "%s%d" % (prefix, self._n[prefix])
        fact = Fact(fid, scope, subject, team, key, text, value, unit, source)
        self.facts.append(fact)
        for under in (key, *also):
            self._by_key.setdefault((under, subject), []).append(fact)
        return fid

    @property
    def count(self) -> int:
        return self._n["F"]

    @property
    def playbook(self) -> list[Fact]:
        return [f for f in self.facts if f.scope == PLAYBOOK_SCOPE]

    def find(self, key: str, subject: str | None = None) -> list[Fact]:
        """Facts with this key (and subject, if given)."""
        if subject is not None:
            return list(self._by_key.get((key, subject), ()))
        return [f for f in self.facts if f.key == key]

    def rendered(self) -> str:
        lines = ["[%s] %s" % (f.id, f.text) for f in self.facts if f.scope != PLAYBOOK_SCOPE]
        side = self.playbook
        if side:
            lines += [PLAYBOOK_DIVIDER] + ["[%s] %s" % (f.id, f.text) for f in side]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {"map": self.map_name, "red": self.red, "blue": self.blue,
                "bans": self.bans, "side": self.side, "count": self.count,
                "playbook_count": self._n["S"],
                "facts": [f.to_dict() for f in self.facts]}
