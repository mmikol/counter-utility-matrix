"""The one registry the door lists its tools from, with no database: the
families in FAMILIES' order whichever imports first, each family's tools in
the order its module declares them, a registry's refusal of a name twice or
a tool outside its families, and the name a tool's call of another is
audited under."""

import functools
import inspect
import json
import subprocess
import sys

import pytest

from db import ROOT
from door.mcp import registry, tools
from door.mcp.registry import Registry


def test_the_registry_lists_the_families_in_the_stated_order():
    """Family by family in FAMILIES' order, every family imported and holding
    tools, a board or pull tool in the family of the module that defines its
    function, and each family's tools in the order its module declares them."""
    families = [spec.family for spec in tools.REGISTRY]
    assert families == sorted(families, key=registry.FAMILIES.index)
    assert set(families) == set(registry.FAMILIES)
    assert tools.REGISTRY.get("facts").family == "door.mcp.facts"
    assert tools.REGISTRY.get("pull_heroes").family == "door.mcp.pulls"
    for family in registry.FAMILIES:
        lines = [inspect.unwrap(spec.fn).__code__.co_firstlineno
                 for spec in tools.REGISTRY if spec.family == family]
        assert lines == sorted(lines), family
    assert tools.Context.tools is tools.REGISTRY


def test_the_order_holds_whichever_family_imports_first():
    """A process that imports a later family before the rest lists the same
    tools in the same order."""
    script = "\n".join((
        "from door.mcp import playbook, solver",
        "from door.mcp import tools",
        "print(' '.join(tools.REGISTRY.names()))"))
    listed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    assert listed.returncode == 0, listed.stderr          # a child that died says why
    assert listed.stdout.split() == tools.REGISTRY.names()


def test_a_registry_refuses_a_tool_name_twice_and_a_tool_outside_its_families():
    local = Registry([__name__])

    @local.tool("twice", "the first")
    def first(ctx):
        return "first", {}
    with pytest.raises(ValueError, match="'twice'"):
        @local.tool("twice", "the second")
        def second(ctx):
            return "second", {}
    assert local.names() == ["twice"] and local.get("twice").fn is first
    # a wrapper that does not wear its function's module is in no family
    with pytest.raises(ValueError, match="functools, which is not a family"):
        local.tool("wrapped", "d")(functools.partial(first))
    assert local.names() == ["twice"]


def test_a_tool_calling_another_is_audited_as_nested_under_its_name(tmp_path, monkeypatch):
    """The outer call is audited as its caller's, and the call the tool makes
    inside it as nested:<tool>, on a copy of the context that keeps its class."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("COUNTRIX_AUDIT", str(path))
    local = Registry([__name__])

    @local.tool("outer", "calls inner")
    def outer(ctx):
        assert isinstance(ctx, Local) and ctx.client == "nested:outer"
        return ctx.call("inner")

    @local.tool("inner", "answers")
    def inner(ctx):
        return "inner", {}

    class Local(tools.Context):
        tools = local

    ctx = Local(dsn="postgresql://nowhere", client="shell")
    assert ctx.call("outer") == ("inner", {})
    assert ctx.client == "shell"                          # the caller's own context is untouched
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(e["tool"], e["client"]) for e in lines] == [
        ("inner", "nested:outer"), ("outer", "shell")]


def test_a_registry_lists_a_family_in_its_place_whenever_it_registers():
    ordered = Registry(["tests.earlier", "tests.later"])
    for name, family in (("b", "tests.later"), ("a", "tests.earlier"), ("c", "tests.later")):
        def fn(ctx):
            return "", {}
        fn.__module__ = family
        ordered.tool(name, "d")(fn)
    assert ordered.names() == ["a", "b", "c"]
