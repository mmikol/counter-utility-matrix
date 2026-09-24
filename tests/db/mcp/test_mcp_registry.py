"""The one registry the door lists its tools from, with no database: the
families in FAMILIES' order whichever imports first, each family's tools in
the order its module declares them, and a registry's refusal of a name
twice or a tool outside its families."""

import functools
import inspect
import subprocess
import sys

import pytest

from db import ROOT
from db.mcp import registry, tools
from db.mcp.registry import Registry


def test_the_registry_lists_the_families_in_the_stated_order():
    """Family by family in FAMILIES' order, every family imported and holding
    tools, a board or pull tool in the family of the module that defines its
    function, and each family's tools in the order its module declares them."""
    families = [spec.family for spec in tools.REGISTRY]
    assert families == sorted(families, key=registry.FAMILIES.index)
    assert set(families) == set(registry.FAMILIES)
    assert tools.REGISTRY.get("facts").family == "db.mcp.facts"
    assert tools.REGISTRY.get("pull_heroes").family == "db.mcp.pulls"
    for family in registry.FAMILIES:
        lines = [inspect.unwrap(spec.fn).__code__.co_firstlineno
                 for spec in tools.REGISTRY if spec.family == family]
        assert lines == sorted(lines), family
    assert tools.Context.tools is tools.REGISTRY


def test_the_order_holds_whichever_family_imports_first():
    """A process that imports a later family before the rest lists the same
    tools in the same order."""
    script = "\n".join((
        "from db.mcp import playbook, solver",
        "from db.mcp import tools",
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


def test_a_registry_lists_a_family_in_its_place_whenever_it_registers():
    ordered = Registry(["tests.earlier", "tests.later"])
    for name, family in (("b", "tests.later"), ("a", "tests.earlier"), ("c", "tests.later")):
        def fn(ctx):
            return "", {}
        fn.__module__ = family
        ordered.tool(name, "d")(fn)
    assert ordered.names() == ["a", "b", "c"]
