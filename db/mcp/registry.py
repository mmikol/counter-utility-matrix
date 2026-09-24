"""What a tool is, the registry a family of tools is declared into, and the
context a call lands in.

    Property         one argument in a tool's JSON schema
    ToolSchema       a tool's arguments as JSON Schema
    ToolReply        what every tool returns: its text, and the same as a JSON
                     object for a structured reply
    ToolSpec         a tool as registered: its name, description, schema and
                     function, and for a pull the source whose cache it reads
    Registry         tools in registration order, each name once: joined()
                     assembles the families, bind() hands a server its Tools,
                     run() is the audited in-process call, write_docs() the
                     tool reference in docs/mcp.md
    Context          where a call lands: the database, the page caches, the
                     log, and the joined registry one tool calls another
                     through (call)
    REFRESH          the refresh argument of every pull and of the rebuild

Each family module - pulls, lifecycle, layers, playbook - declares its tools
into a Registry of its own and imports no other family. tools.py joins them
and gives the Context its registry.
"""

import functools
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, NamedTuple, TypedDict

import psycopg

from db import CACHE_DIRS, ROOT, embed, psql
from db.data import fetch
from db.data.fetch import Log
from db.mcp.server import Tool, audited


class Property(TypedDict, total=False):
    """One argument in a tool's JSON schema: its type, an array's item type,
    the values it admits and what it means. One that declares no type admits
    any value."""
    type: str
    items: "Property"
    enum: list[str]
    description: str


# A tool's arguments by name, in the order the reference lists them.
type Properties = dict[str, Property]


class ToolSchema(TypedDict):
    """A tool's arguments as JSON Schema: an object of the named properties,
    the required ones present and no other admitted."""
    type: str
    properties: Properties
    required: list[str]
    additionalProperties: bool


class ToolReply(NamedTuple):
    """What a tool returns: its text, and the same as a JSON object for a
    structured reply."""
    text: str
    data: Mapping[str, object]


# A tool's function: its context first, its arguments by name.
type ToolFn = Callable[..., ToolReply]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as registered: its name, description, JSON schema and function,
    and for a pull, the source whose page cache it reads."""
    name: str
    description: str
    schema: ToolSchema
    fn: ToolFn
    source: str | None = None


class NoSuchToolError(KeyError):
    """No registered tool has the name a caller asked for - told apart from a
    KeyError raised inside a tool, which is the server's fault."""

    def __str__(self) -> str:
        return "no tool named %r" % self.args[0]


REFRESH: Properties = {
    "refresh": {"type": "boolean",
                "description": "fetch every page again instead of reading the cache; a page"
                               " that fails to fetch keeps its cached copy"}}


class Registry:
    """Tools in the order they were registered, each name once. The pulls are
    the tools that name a source, in the same order."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    @classmethod
    def joined(cls, *families: "Registry") -> "Registry":
        """One registry of every family's tools, family by family in the order
        given; a name two families register raises, at import."""
        joined = cls()
        for family in families:
            for spec in family:
                joined.add(spec)
        return joined

    def add(self, spec: ToolSpec) -> None:
        # a name registered twice is a programmer's error, raised at import
        if spec.name in self._specs:
            raise ValueError("tool %r is registered twice" % spec.name)
        self._specs[spec.name] = spec

    def tool(
            self, name: str, description: str, properties: Properties | None = None,
            required: Sequence[str] = (), *,
            source: str | None = None) -> Callable[[ToolFn], ToolFn]:
        """The decorator that registers a function as a tool: its arguments
        are the named properties, the required ones must be present, and no
        other is accepted."""
        schema = ToolSchema(type="object", properties=properties or {},
                            required=list(required), additionalProperties=False)

        def decorate(fn: ToolFn) -> ToolFn:
            self.add(ToolSpec(name, description, schema, fn, source))
            return fn
        return decorate

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def names(self) -> list[str]:
        return list(self._specs)

    def get(self, name: str) -> ToolSpec:
        """The tool of that name; a name no tool has is a NoSuchToolError."""
        try:
            return self._specs[name]
        except KeyError:
            raise NoSuchToolError(name) from None

    def pulls(self) -> list[ToolSpec]:
        """The tools that pull a source, in registration order: the
        dependency order sync_all runs them in."""
        return [spec for spec in self if spec.source is not None]

    def bind(self, ctx: "Context") -> list[Tool]:
        """Every tool bound to a context, for a server to serve -> [Tool]."""
        return [_bind(ctx, spec) for spec in self]

    def run(self, ctx: "Context", name: str, /, **arguments: object) -> ToolReply:
        """Call a tool by name, in-process - the refresher's, the shell's, the
        board's and one tool's call of another. The call is validated against
        the tool's schema and audited, like a call through either door: a call
        the schema refuses is a Refusal, and a name no tool has is a
        NoSuchToolError, which reaches no tool and leaves no audit line. The
        name is positional only, so a tool argument called `name` (add_strategy
        has one) reaches the tool instead of colliding here."""
        spec = self.get(name)
        tool = _bind(ctx, spec)

        def call() -> ToolReply:
            tool.check(arguments)
            return spec.fn(ctx, **arguments)
        return audited(name, arguments, call, "in-process")

    def write_docs(self, path: str | None = None) -> str:
        """The tool reference - every tool, its description and its arguments -
        generated into docs/mcp.md between its markers -> the path written."""
        path = path or os.path.join(ROOT, "docs", "mcp.md")
        out = ["%d tools, in the order the server lists them. Regenerated by"
               " `python -m db.mcp call db_docs`." % len(self), "",
               "| tool | does | arguments |", "| --- | --- | --- |"]
        for spec in self:
            required = set(spec.schema["required"])
            arguments = [_argument(arg, prop, arg in required)
                         for arg, prop in spec.schema["properties"].items()]
            out.append("| `%s` | %s | %s |" % (spec.name, _escaped(spec.description),
                                              "<br>".join(arguments) or "none"))
        embed(path, "tools", "\n".join(out))
        return path


def _bind(ctx: "Context", spec: ToolSpec) -> Tool:
    """One tool bound to a context: the wrapper that checks every call
    against the tool's schema, over the function with ctx filled in."""
    return Tool(spec.name, spec.description, spec.schema, functools.partial(spec.fn, ctx))


def _escaped(text: str) -> str:
    """Text for a markdown table cell: its pipes escaped."""
    return text.replace("|", "\\|")


def _argument(name: str, prop: Property, required: bool) -> str:
    """One argument as the reference lists it: its name, whether it is
    required, its type or the values it admits, and what it means."""
    kind = " \\| ".join(prop["enum"]) if "enum" in prop else prop.get("type") or "any"
    meaning = ": " + _escaped(prop["description"]) if prop.get("description") else ""
    return "`%s`%s (%s)%s" % (name, " *required*" if required else "", kind, meaning)


class Context:
    """Where a tool call lands: the database, the page caches and the log, and
    the registry of every tool, which one tool reaches another through. A
    subclass names the registry: tools.Context holds the joined one."""

    tools: ClassVar[Registry]

    def __init__(
            self, dsn: str | None = None, caches: Mapping[str, str] | None = None,
            log: Log | None = None) -> None:
        self._dsn = dsn
        self.caches: dict[str, str] = dict(CACHE_DIRS, **(caches or {}))
        self.log: Log = log or fetch.to_stderr

    @property
    def dsn(self) -> str:
        if self._dsn is None:
            self._dsn = psql.default_dsn()
        return self._dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    def cache(self, source: str) -> str | None:
        return fetch.prepare_cache(self.caches[source])

    def call(self, name: str, /, **arguments: object) -> ToolReply:
        """Another tool by name, validated and audited as an in-process call."""
        return self.tools.run(self, name, **arguments)
