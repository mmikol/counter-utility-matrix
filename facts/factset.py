"""The FactSet: a board's facts numbered F1.. and the playbook's record S1..

A Fact is one sentence and the structured claim behind it (scope, subject,
key, value, unit, source); the FactSet numbers them in emission order and
files each under the metrics it states, so the inference layer finds a fact
by metric and a person reads the same facts as numbered sentences.
facts.board_facts writes a board's facts into one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from facts.draft import Draft


@dataclass(frozen=True, slots=True)
class Fact:
    """One numbered fact: the sentence a person reads and the structured claim
    behind it, filed under its scope, subject and key."""
    id: str
    scope: str
    subject: str
    team: str | None
    key: str
    text: str
    # what the fact states - a number, a name, a list or a record of them -
    # and JSON once _plain has read it; arbitrary JSON its readers know the
    # shape of, so Any
    value: Any
    unit: str | None
    source: str

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
    """The facts (F1..) and the playbook's record (S1..) of one board, and
    `draft`, the board they describe with its names resolved. Both live in
    `facts` in order, so a citation of either resolves; `count` is the facts
    alone."""

    def __init__(self, draft: Draft) -> None:
        self.draft = draft
        self.facts: list[Fact] = []
        self._by_key: dict[str, list[Fact]] = {}
        self._n = {"F": 0, "S": 0}

    def add(
            self, scope: str, subject: str, key: str, text: str, *, source: str,
            value: object = None, unit: str | None = None, team: str | None = None,
            also: Sequence[str] = ()) -> str:
        """`also` names the other metrics this one sentence states, so a caller
        looking for one of them finds the fact that carries it. The fact keeps
        the key it is worded around; `also` only adds index entries."""
        prefix = "S" if scope == PLAYBOOK_SCOPE else "F"
        self._n[prefix] += 1
        fid = "%s%d" % (prefix, self._n[prefix])
        fact = Fact(id=fid, scope=scope, subject=subject, team=team, key=key, text=text,
            value=value, unit=unit, source=source)
        self.facts.append(fact)
        for under in dict.fromkeys((key, *also)):
            self._by_key.setdefault(under, []).append(fact)
        return fid

    @property
    def count(self) -> int:
        return self._n["F"]

    @property
    def playbook(self) -> list[Fact]:
        return [f for f in self.facts if f.scope == PLAYBOOK_SCOPE]

    def find(self, key: str, subject: str | None = None) -> list[Fact]:
        """Facts that state this metric - worded around it or carrying it in
        `also` - in id order; a subject narrows them."""
        stating = self._by_key.get(key, [])
        if subject is None:
            return list(stating)
        return [f for f in stating if f.subject == subject]

    def rendered(self) -> str:
        lines = ["[%s] %s" % (f.id, f.text) for f in self.facts if f.scope != PLAYBOOK_SCOPE]
        side = self.playbook
        if side:
            lines += [PLAYBOOK_DIVIDER] + ["[%s] %s" % (f.id, f.text) for f in side]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        draft = self.draft
        return {"map": draft.map_name, "red": list(draft.red), "blue": list(draft.blue),
                "bans": list(draft.bans), "side": draft.side, "count": self.count,
                "playbook_count": self._n["S"],
                "facts": [f.to_dict() for f in self.facts]}
