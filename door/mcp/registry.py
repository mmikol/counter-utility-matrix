"""The one registry every family declares its tools into, and the context a
call lands in.

    ToolSpec         a tool as registered: its name, description, schema (a
                     schema.ToolSchema), function and family, and for a pull
                     the source whose cache it reads
    Registry         tools family by family, each name once: bind() hands a
                     server its Tools, run() is the audited in-process call,
                     write_docs() the tool reference in docs/mcp.md
    FAMILIES         the family modules, in the order the registry lists them
    REGISTRY, tool   the one registry, and the decorator a family declares
                     each of its tools with
    Context          where a call lands: the database, the page caches, the
                     log, the caller the audit line names (board, refresher,
                     shell, nested:<tool>), and the registry one tool calls
                     another through (call)
    REFRESH          the refresh argument of every pull and of the rebuild

A family module - pulls, lifecycle, facts, solver, playbook - declares its
tools with @tool and imports no other family. A tool's family is the module
its function is defined in, so the registry lists the same order whichever
family imports first; a decorator that registers a wrapper gives it its
function's module with functools.update_wrapper. tools.py imports every
family. A tool declares its arguments in schema.py's JSON Schema vocabulary
(Properties), the one every call is checked against, and answers a
schema.ToolReply.
"""

import copy
import functools
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Self

import psycopg

from db import CACHE_DIRS, ROOT, embed, psql
from db.data import fetch
from db.data.fetch import Log
from door.mcp.audit import audited
from door.mcp.schema import (
    Properties,
    Property,
    Tool,
    ToolReply,
    ToolSchema,
    tool_schema,
    type_text,
)

# A tool's function: its context first, its arguments by name.
type ToolFn = Callable[..., ToolReply]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as registered: its name, description, JSON schema, function and
    family - the module the function is defined in - and for a pull, the
    source whose page cache it reads."""
    name: str
    description: str
    schema: ToolSchema
    fn: ToolFn
    family: str
    source: str | None = None


class NoSuchToolError(KeyError):
    """No registered tool has the name a caller asked for - told apart from a
    KeyError raised inside a tool, which is the server's fault."""

    def __str__(self) -> str:
        return "no tool named %r" % self.args[0]


REFRESH: Properties = {
    "refresh": {"type": "boolean",
                "description": "fetch every page again instead of reading the cache; a page"
                               " that fails to fetch keeps its cached copy and is listed"
                               " under stale"}}


class Registry:
    """Tools listed family by family, in the order `families` names their
    modules, and each family's in the order it declared them - the same
    whichever family imports first. Each name is registered once. The pulls
    are the tools that name a source, in the same order."""

    def __init__(self, families: Sequence[str]) -> None:
        self.families = tuple(families)
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Add a tool in its family's place. A name registered twice, or a
        tool defined outside the families, is a programmer's error, raised at
        import."""
        if spec.name in self._specs:
            raise ValueError("tool %r is registered twice" % spec.name)
        if spec.family not in self.families:
            raise ValueError("tool %r is defined in %s, which is not a family: %s" % (
                spec.name, spec.family, ", ".join(self.families)))
        specs = sorted([*self._specs.values(), spec], key=self._rank)
        self._specs = {s.name: s for s in specs}

    def _rank(self, spec: ToolSpec) -> int:
        """Where a tool's family lists: its place in `families`."""
        return self.families.index(spec.family)

    def tool(
            self, name: str, description: str, properties: Properties | None = None,
            required: Sequence[str] = (), *,
            source: str | None = None) -> Callable[[ToolFn], ToolFn]:
        """The decorator that registers a function as a tool: its arguments
        are the named properties, the required ones must be present, and no
        other is accepted."""
        schema = tool_schema(properties, required)

        def decorate(fn: ToolFn) -> ToolFn:
            self.register(ToolSpec(name=name, description=description, schema=schema, fn=fn,
                                   family=fn.__module__, source=source))
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
        board's and one tool's call of another - audited under the caller
        ctx.client names. The call is validated against the tool's schema,
        like a call through either door: a call the schema refuses is a
        Refusal, and a name no tool has is a NoSuchToolError, which reaches no
        tool and leaves no audit line. The name is positional only, so a tool
        argument called `name` (add_strategy has one) reaches the tool
        instead of colliding here."""
        tool = _bind(ctx, self.get(name))
        return audited(name, arguments, lambda: tool(arguments), "in-process", ctx.client)

    def write_docs(self, path: str | None = None) -> str:
        """The tool reference - every tool, its description and its arguments -
        generated into docs/mcp.md between its markers -> the path written."""
        path = path or os.path.join(ROOT, "docs", "mcp.md")
        out = [
            "%d tools, in the order the server lists them. Regenerated by"
            " `.venv/bin/python -m door.mcp call db_docs`." % len(self), "",
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
    against the tool's schema, over the function with a copy of ctx named
    after the tool filled in - so a call the tool makes to another is
    audited as nested:<tool>, whichever door the outer call came through."""
    return Tool(spec.name, spec.description, spec.schema,
                functools.partial(spec.fn, ctx.nested(spec.name)))


def _escaped(text: str) -> str:
    """Text for a markdown table cell: its pipes escaped."""
    return text.replace("|", "\\|")


def _argument(name: str, prop: Property, required: bool) -> str:
    """One argument as the reference lists it: its name, whether it is
    required, its type or the values it admits, and what it means."""
    kind = " \\| ".join(prop["enum"]) if "enum" in prop else type_text(prop) or "any"
    meaning = ": " + _escaped(prop["description"]) if prop.get("description") else ""
    return "`%s`%s (%s)%s" % (name, " *required*" if required else "", kind, meaning)


# The family modules, in the order the server lists their tools.
FAMILIES = ("door.mcp.pulls", "door.mcp.lifecycle", "door.mcp.facts", "door.mcp.solver",
            "door.mcp.playbook")

REGISTRY = Registry(FAMILIES)
tool = REGISTRY.tool


class Context:
    """Where a tool call lands: the database, the page caches, the log, the
    caller its in-process calls are audited as, and the registry of every
    tool, which one tool reaches another through. It is whole once tools.py
    has imported every family.

    The client is required, so no in-process call is anonymous: 'board',
    'refresher' or 'shell' where one is built, and 'nested:<tool>' on the
    copy a tool is handed (nested), whichever door the tool's own call came
    through."""

    tools: ClassVar[Registry] = REGISTRY

    def __init__(
            self, dsn: str | None = None, caches: Mapping[str, str] | None = None,
            log: Log | None = None, *, client: str) -> None:
        self._dsn = dsn
        self.caches: dict[str, str] = dict(CACHE_DIRS, **(caches or {}))
        self.log: Log = log or fetch.to_stderr
        self.client = client

    def nested(self, tool: str) -> Self:
        """A copy for `tool` to call others through, audited as nested:<tool>.
        A copy keeps its class - a test's connect() with it - and shares the
        caches and the log; one made before this context resolved its dsn
        resolves the same one on first use (psql.default_dsn is idempotent)."""
        copied = copy.copy(self)
        copied.client = "nested:%s" % tool
        return copied

    @property
    def dsn(self) -> str:
        if self._dsn is None:
            self._dsn = psql.default_dsn()
        return self._dsn

    def connect(self, boot: bool = False) -> psycopg.Connection:
        """A connection to the database; `boot`, passed only by db_init and
        db_rebuild, creates the embedded cluster first when the Context was
        given no dsn."""
        if boot and self._dsn is None:
            self._dsn = psql.boot()
        return psycopg.connect(self.dsn)

    def cache(self, source: str) -> str | None:
        return fetch.prepare_cache(self.caches[source])

    def call(self, name: str, /, **arguments: object) -> ToolReply:
        """A tool by name, in-process - the refresher's, the shell's, the
        board's and one tool's call of another - audited as this context's
        client (Registry.run)."""
        return self.tools.run(self, name, **arguments)
