"""A small, safe expression language for heuristic frontmatter.

    team.tanks == 1 and team.damage == 2
    min(team.hitscan, 2) * 1.5
    matchup.chew_time_ours < params.LIMIT

Python's grammar, parsed with `ast`, checked once against a whitelist of
node types - no attribute access beyond dotted metric names, no calls but
the handful of arithmetic helpers below, no names but the namespaces -
and then compiled to a code object, so evaluating a heuristic on a
candidate is a native expression, not a tree walk. Names are dotted keys
into a namespace of dicts ({"team": {...}, "enemy": {...}, "matchup": ...,
"map": ..., "world": ..., "params": ...}); a key a namespace lacks reads 0.
"""

import ast
import operator

FUNCTIONS = {"min": min, "max": max, "abs": abs, "round": round,
             "len": len, "int": int, "float": float, "bool": bool}

BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
          ast.Mod: operator.mod, ast.Pow: operator.pow}
COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
           ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
           ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
UNARY = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}


class ExprError(ValueError):
    pass


NAMESPACES = ("team", "enemy", "matchup", "map", "world", "params")


class Section(object):
    """A namespace dict read by attribute: missing keys and None read 0."""
    __slots__ = ("_d",)

    def __init__(self, d):
        self._d = d

    def __getattr__(self, key):
        value = self._d.get(key)
        return 0 if value is None else value


class Scope(dict):
    """The eval locals: every namespace a Section, absent ones empty, and
    the arithmetic helpers by name."""

    def __missing__(self, key):
        if key in FUNCTIONS:
            return FUNCTIONS[key]
        return Section({})


_EMPTY = Section({})


class Expr:
    """A compiled expression: its source, the dotted names it reads, and
    eval(namespace)."""

    def __init__(self, source):
        self.source = source.strip()
        try:
            self.tree = ast.parse(self.source, mode="eval").body
        except SyntaxError as error:
            raise ExprError("%r: %s" % (self.source, error.msg))
        self.names = sorted(self._collect_names(self.tree))
        for name in self.names:
            if any(part.startswith("_") for part in name.split(".")):
                raise ExprError("%r: underscore names are not allowed" % name)
        self._check(self.tree)
        self.code = compile(ast.Expression(body=self.tree), "<heuristic>", "eval")

    def __repr__(self):
        return "Expr(%r)" % self.source

    def _collect_names(self, node):
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
    def _dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    def _check(self, node):
        """The whitelist, enforced once at compile time."""
        if isinstance(node, ast.Constant):
            if not (isinstance(node.value, (int, float, str, bool)) or node.value is None):
                raise ExprError("unsupported constant %r" % (node.value,))
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v)
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            self._check(node.left)
            self._check(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
            self._check(node.operand)
        elif isinstance(node, ast.Compare):
            if any(type(op) not in COMPARE for op in node.ops):
                raise ExprError("unsupported comparison in %r" % self.source)
            self._check(node.left)
            for c in node.comparators:
                self._check(c)
        elif isinstance(node, ast.IfExp):
            self._check(node.test)
            self._check(node.body)
            self._check(node.orelse)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ExprError("unsupported call in %r" % self.source)
            if node.keywords:
                raise ExprError("keyword arguments are not supported")
            for a in node.args:
                self._check(a)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for e in node.elts:
                self._check(e)
        elif isinstance(node, ast.Attribute):
            if self._dotted(node) is None:
                raise ExprError("unsupported attribute access in %r" % self.source)
        elif isinstance(node, ast.Name):
            if node.id not in NAMESPACES and node.id not in FUNCTIONS:
                raise ExprError("unknown name %r in %r" % (node.id, self.source))
        else:
            raise ExprError("unsupported syntax %s in %r"
                            % (type(node).__name__, self.source))

    def eval(self, namespace):
        """Evaluate against {"team": {...}, ...}; a Scope is used as is."""
        scope = namespace if isinstance(namespace, Scope) else Scope(
            (k, Section(v)) for k, v in namespace.items())
        try:
            return eval(self.code, _GLOBALS, scope)
        except ZeroDivisionError:
            return 0.0
        except TypeError as error:            # e.g. a text metric in arithmetic
            raise ExprError("%r: %s" % (self.source, error))


_GLOBALS = dict(FUNCTIONS, __builtins__={})


def scope(namespace, params=None):
    """A reusable Scope for many evaluations over one candidate."""
    s = Scope((k, Section(v)) for k, v in namespace.items())
    if params is not None:
        s["params"] = Section(params)
    return s


def lookup(namespace, dotted, default=0):
    """namespace["team"]["dps_floor"] for "team.dps_floor"; None -> default."""
    node = namespace
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return default if node is None else node


def compile_expr(source):
    return Expr(source) if source not in (None, "") else None
