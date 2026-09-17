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

FUNCTIONS = {"min": min, "max": max, "abs": abs, "round": round,
             "len": len, "int": int, "float": float, "bool": bool}

# the operators the whitelist admits; the compiled code object does the arithmetic
BINARY = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
COMPARE = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
UNARY = (ast.Not, ast.USub, ast.UAdd)


class ExprError(ValueError):
    pass


NAMESPACES = ("team", "enemy", "matchup", "map", "world", "params")


class Section:
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


class Expr:
    """A compiled expression: its source, the dotted names it reads, and
    eval(namespace)."""

    def __init__(self, source):
        self.source = source.strip()
        try:
            self.tree = ast.parse(self.source, mode="eval").body
        except SyntaxError as error:
            raise ExprError("%r: %s" % (self.source, error.msg)) from error
        self.names = sorted(self._collect_names(self.tree))
        for name in self.names:
            if any(part.startswith("_") for part in name.split(".")):
                raise ExprError("%r: underscore names are not allowed" % name)
        self._check(self.tree)
        self._guard(self.tree, 0)
        self.code = compile(ast.Expression(body=self.tree), "<strategy>", "eval")

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

    def _guard(self, node, depth):
        """What the whitelist alone would let through: an exponent tower, a
        string multiplied a billion times, an expression nested past reason -
        each a way to hang or exhaust the solver from one frontmatter line."""
        if depth > 40:
            raise ExprError("%r: nested too deep" % self.source)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 200:
            raise ExprError("%r: a string constant over 200 characters" % self.source)
        if isinstance(node, ast.BinOp):
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
        for child in ast.iter_child_nodes(node):
            self._guard(child, depth + 1)

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
            raise ExprError("%r: %s" % (self.source, error)) from error
        except (RecursionError, MemoryError, OverflowError) as error:
            raise ExprError("%r: %s" % (self.source, type(error).__name__)) from error


_GLOBALS = dict(FUNCTIONS, __builtins__={})


def scope(namespace):
    """A reusable Scope for many evaluations over one candidate; the caller
    sets its `params` slot per strategy."""
    return Scope((k, Section(v)) for k, v in namespace.items())


def compile_expr(source):
    return Expr(source) if source not in (None, "") else None
