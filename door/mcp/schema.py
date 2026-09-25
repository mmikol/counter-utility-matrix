"""A tool as the protocol serves it: its arguments declared as JSON Schema -
a ToolSchema of one Property per argument, which tool_schema builds - what
it answers (ToolReply), and the Tool that checks every call against its
schema before the function runs, so a call the schema refuses never
reaches the tool, whichever door it came in by.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple, TypedDict

from db import Refusal


class ToolReply(NamedTuple):
    """What a tool returns: its text, and the same as a JSON object for a
    structured reply. The database's writers - the pulls, load_authored,
    sync_all, export_csv, db_init, db_migrate and db_rebuild - open the text
    with one headline line, "<tool>: <what it did>", and the refresher logs
    that line alone."""
    text: str
    data: Mapping[str, object]


class Property(TypedDict, total=False):
    """One argument in a tool's JSON schema: its type - one name, or a list
    of the names it admits - an array's item type, the values it admits and
    what it means. One that declares no type admits any value."""
    type: str | list[str]
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


def tool_schema(properties: Properties | None = None, required: Sequence[str] = ()) -> ToolSchema:
    """A tool's schema: the named properties, the required ones present, no
    other admitted."""
    return ToolSchema(type="object", properties=properties or {}, required=list(required),
                      additionalProperties=False)


class ToolDescription(TypedDict):
    """A tool as tools/list lists it: its name, what it does and its schema."""
    name: str
    description: str
    inputSchema: ToolSchema


# The Python values each JSON schema type admits. A bool is an int to Python
# and neither an integer nor a number here; None is no type at all.
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
    "array": (list, tuple), "object": (dict,)}


def _types(spec: Property) -> list[str]:
    """The JSON schema types a property admits; none when it declares none."""
    kind = spec.get("type")
    if kind is None:
        return []
    return [kind] if isinstance(kind, str) else kind


def type_text(spec: Property) -> str | None:
    """A property's type as the refusals and the reference word it: its
    types joined with 'or' ('string or number'), None when it declares none."""
    return " or ".join(_types(spec)) or None


def _is_a(value: object, kinds: list[str]) -> bool:
    """Whether a value is of any of these JSON schema types."""
    if isinstance(value, bool):
        return "boolean" in kinds
    return any(isinstance(value, JSON_TYPES[kind]) for kind in kinds)


def _misfit(spec: Property, value: object) -> str | None:
    """What a value must be to fit the property that declares it, or None when
    it fits: one of its types (an array's items too, where they declare one)
    and its enum. A property that declares neither admits anything."""
    kinds, items = _types(spec), _types(spec.get("items", {}))
    wanted = "%s of %s" % (type_text(spec), " or ".join(items)) if items else type_text(spec)
    if kinds and not _is_a(value, kinds):
        return wanted
    if items and isinstance(value, (list, tuple)) and not all(_is_a(v, items) for v in value):
        return wanted
    if "enum" in spec and value not in spec["enum"]:
        return "one of %s" % ", ".join(repr(v) for v in spec["enum"])
    return None


class Tool:
    """A callable with the description and JSON schema the host needs. Every
    call is checked against the schema before the function runs, so a call
    the schema refuses never reaches the tool, whichever door it came in by."""

    def __init__(self, name: str, description: str, schema: ToolSchema,
                 fn: Callable[..., ToolReply]) -> None:
        self.name, self.description, self.schema, self.fn = (
            name, description, schema, fn)

    def describe(self) -> ToolDescription:
        return ToolDescription(name=self.name, description=self.description,
                               inputSchema=self.schema)

    def __call__(self, arguments: Mapping[str, object]) -> ToolReply:
        """Call the tool once its schema allows the call."""
        self.check(arguments)
        return self.fn(**arguments)

    def check(self, arguments: Mapping[str, object]) -> None:
        """Refuse a call the schema does not allow. An argument it does not
        declare, one it requires left out, and a value that is not the
        declared type or not one of the declared values are each a Refusal."""
        properties = self.schema["properties"]
        unknown = set(arguments) - set(properties)
        if unknown:
            raise Refusal("%s: unknown argument(s) %s" % (
                self.name, ", ".join(sorted(unknown))))
        for required in self.schema["required"]:
            if required not in arguments:
                raise Refusal("%s: missing %r" % (self.name, required))
        for argument, value in arguments.items():
            wanted = _misfit(properties[argument], value)
            if wanted is not None:
                raise Refusal("%s: %r must be %s" % (self.name, argument, wanted))
