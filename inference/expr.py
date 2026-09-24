"""A small, safe expression language for strategy frontmatter.

    team.tanks == 1 and team.damage == 2
    min(team.hitscan, 2) * 1.5
    matchup.chew_time_ours < params.LIMIT

Python's grammar, parsed with `ast`, checked once against a whitelist of
node types - no attribute access beyond dotted metric names, no calls but
the handful of arithmetic helpers below, no names but the namespaces -
and then compiled to a code object, so evaluating a strategy on a
candidate is a native expression, not a tree walk. Names are dotted keys
into a namespace of dicts ({"team": {...}, "enemy": {...}, "matchup": ...,
"map": ..., "world": ..., "params": ...}); a key a namespace lacks reads 0.
"""

import ast
from collections.abc import Callable, Iterable, Mapping
from types import CodeType

FUNCTIONS: dict[str, Callable[..., object]] = {
    "min": min, "max": max, "abs": abs, "round": round,
    "len": len, "int": int, "float": float, "bool": bool}

# the operators the whitelist admits; the compiled code object does the arithmetic
BINARY = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
COMPARE = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
UNARY = (ast.Not, ast.USub, ast.UAdd)

# what an expression evaluates to: the whitelist admits no other constant or display
Value = int | float | bool | str | list | tuple | None


class ExprError(ValueError):
    pass


NAMESPACES = ("team", "enemy", "matchup", "map", "world", "params")


class Section:
    """A namespace read by attribute: a key it lacks reads 0.

    The dict becomes the instance's own __dict__, so `team.tanks` in a
    compiled expression is a plain attribute lookup and not a call - the
    solver makes millions of them. The values are the namespace's own:
    compute fills every key it declares with a number, a name or a list,
    never None."""

    def __init__[V](self, values: dict[str, V]) -> None:
        self.__dict__ = values

    def __getattr__(self, key: str) -> int:
        if key.startswith("__"):
            raise AttributeError(key)
        return 0


class Scope(dict[str, Section]):
    """The eval locals: every namespace a Section, absent ones empty, and
    the arithmetic helpers by name."""

    def __missing__(self, key: str) -> Section | Callable[..., object]:
        if key in FUNCTIONS:
            return FUNCTIONS[key]
        return Section({})


class Expr:
    """A compiled expression: its source, the dotted names it reads, and
    evaluate(namespace)."""

    def __init__(self, source: str) -> None:
        self.source = source.strip()
        try:
            tree = ast.parse(self.source, mode="eval").body
        except SyntaxError as error:
            raise ExprError("%r: %s" % (self.source, error.msg)) from error
        self.names = sorted(self._collect_names(tree))
        for name in self.names:
            if any(part.startswith("_") for part in name.split(".")):
                raise ExprError("%r: underscore names are not allowed" % name)
        self._check(tree)
        self._guard(tree, 0)
        # the code object is what a candidate is evaluated against; the tree
        # is dropped, so a playbook keeps no syntax trees in any worker
        self.code: CodeType = compile(ast.Expression(body=tree), "<strategy>", "eval")

    def __repr__(self) -> str:
        return "Expr(%r)" % self.source

    def _collect_names(self, node: ast.AST) -> set[str]:
        found = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                dotted = self._dotted(child)
                if dotted:
                    found.add(dotted)
            elif isinstance(child, ast.Name) and child.id not in FUNCTIONS:
                found.add(child.id)
        # an Attribute walk also yields its inner Name; drop bare prefixes
        return {n for n in found if not any(o != n and o.startswith(n + ".")
                                            for o in found)}

    @staticmethod
    def _dotted(node: ast.expr) -> str | None:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    # --- the guards ------------------------------------------------------------

    def _guard(self, node: ast.AST, depth: int) -> None:
        """What the whitelist alone would let through: an exponent tower, a
        string multiplied a billion times, an expression nested past reason -
        each a way to hang or exhaust the solver from one frontmatter line."""
        if depth > 40:
            raise ExprError("%r: nested too deep" % self.source)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 200:
            raise ExprError("%r: a string constant over 200 characters" % self.source)
        if isinstance(node, ast.BinOp):
            self._guard_binop(node)
        for child in ast.iter_child_nodes(node):
            self._guard(child, depth + 1)

    def _guard_binop(self, node: ast.BinOp) -> None:
        """An exponent is a small constant; strings are compared, never added or
        multiplied."""
        if isinstance(node.op, ast.Pow):
            exp = node.right
            if not (isinstance(exp, ast.Constant) and isinstance(exp.value, (int, float))
                    and not isinstance(exp.value, bool) and 0 <= exp.value <= 8):
                raise ExprError("%r: an exponent must be a number between 0 and 8"
                                % self.source)
        if isinstance(node.op, (ast.Mult, ast.Add)):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    raise ExprError("%r: strings are compared, not added or multiplied"
                                    % self.source)

    # --- the whitelist: one rule per node type -------------------------------

    def _check(self, node: ast.AST) -> None:
        """The whitelist, enforced once at compile time: the node type's rule
        checks the node and names the children to walk; a type with no rule is
        refused."""
        rule = _RULES.get(type(node))
        if rule is None:
            raise self._unsupported(node)
        for child in rule(self, node):
            self._check(child)

    def _unsupported(self, node: ast.AST) -> ExprError:
        return ExprError("unsupported syntax %s in %r" % (type(node).__name__, self.source))

    def _constant(self, node: ast.Constant) -> Iterable[ast.AST]:
        if not (isinstance(node.value, (int, float, str, bool)) or node.value is None):
            raise ExprError("unsupported constant %r" % (node.value,))
        return ()

    def _boolop(self, node: ast.BoolOp) -> Iterable[ast.AST]:
        return node.values

    def _binop(self, node: ast.BinOp) -> Iterable[ast.AST]:
        if type(node.op) not in BINARY:
            raise self._unsupported(node)
        return (node.left, node.right)

    def _unaryop(self, node: ast.UnaryOp) -> Iterable[ast.AST]:
        if type(node.op) not in UNARY:
            raise self._unsupported(node)
        return (node.operand,)

    def _compare(self, node: ast.Compare) -> Iterable[ast.AST]:
        if any(type(op) not in COMPARE for op in node.ops):
            raise ExprError("unsupported comparison in %r" % self.source)
        return (node.left, *node.comparators)

    def _ifexp(self, node: ast.IfExp) -> Iterable[ast.AST]:
        return (node.test, node.body, node.orelse)

    def _call(self, node: ast.Call) -> Iterable[ast.AST]:
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError("unsupported call in %r" % self.source)
        if node.keywords:
            raise ExprError("keyword arguments are not supported")
        return node.args

    def _sequence(self, node: ast.List | ast.Tuple) -> Iterable[ast.AST]:
        return node.elts

    def _attribute(self, node: ast.Attribute) -> Iterable[ast.AST]:
        # the value is not walked: an unknown namespace is the catalog's
        # registry check to refuse, by the dotted name
        if self._dotted(node) is None:
            raise ExprError("unsupported attribute access in %r" % self.source)
        return ()

    def _name(self, node: ast.Name) -> Iterable[ast.AST]:
        if node.id not in NAMESPACES and node.id not in FUNCTIONS:
            raise ExprError("unknown name %r in %r" % (node.id, self.source))
        return ()

    # --- evaluation ----------------------------------------------------------

    def evaluate[V](self, namespace: Mapping[str, dict[str, V]] | Scope) -> Value:
        """Evaluate against {"team": {...}, ...}; a Scope is used as is."""
        scope = namespace if isinstance(namespace, Scope) else Scope(
            (k, Section(v)) for k, v in namespace.items())
        try:
            return eval(self.code, _GLOBALS, scope)  # nosec B307  # whitelisted AST, no builtins
        except ZeroDivisionError:
            return 0.0
        except TypeError as error:            # e.g. a text metric in arithmetic
            raise ExprError("%r: %s" % (self.source, error)) from error
        except (RecursionError, MemoryError, OverflowError) as error:
            raise ExprError("%r: %s" % (self.source, type(error).__name__)) from error


# each node type the whitelist admits, and the rule that checks it
_RULES: dict[type[ast.AST], Callable[..., Iterable[ast.AST]]] = {
    ast.Constant: Expr._constant, ast.BoolOp: Expr._boolop, ast.BinOp: Expr._binop,
    ast.UnaryOp: Expr._unaryop, ast.Compare: Expr._compare, ast.IfExp: Expr._ifexp,
    ast.Call: Expr._call, ast.List: Expr._sequence, ast.Tuple: Expr._sequence,
    ast.Attribute: Expr._attribute, ast.Name: Expr._name,
}

_GLOBALS: dict[str, object] = dict(FUNCTIONS, __builtins__={})


def scope[V](namespace: Mapping[str, dict[str, V]]) -> Scope:
    """A reusable Scope for many evaluations over one candidate; the caller
    sets its `params` slot per strategy."""
    return Scope((k, Section(v)) for k, v in namespace.items())


def compile_expr(source: str | None) -> Expr | None:
    """The expression a frontmatter value holds, or None for none."""
    return Expr(source) if source else None
