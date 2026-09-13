"""A small, safe expression language for heuristic frontmatter.

    team.tanks == 1 and team.damage == 2
    min(team.hitscan, 2) * 1.5
    matchup.chew_time_ours < params.LIMIT

Python's grammar, parsed with `ast` and evaluated by walking a whitelist of
node types - no eval, no attribute access beyond dotted metric names, no
calls but the handful of arithmetic helpers below. Names are dotted keys
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

    def eval(self, namespace):
        return self._eval(self.tree, namespace)

    def _eval(self, node, ns):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)) or node.value is None:
                return node.value
            raise ExprError("unsupported constant %r" % (node.value,))
        if isinstance(node, ast.BoolOp):
            values = [self._eval(v, ns) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            left, right = self._eval(node.left, ns), self._eval(node.right, ns)
            try:
                return BINARY[type(node.op)](left, right)
            except ZeroDivisionError:
                return 0.0
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
            return UNARY[type(node.op)](self._eval(node.operand, ns))
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, ns)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, ns)
                if type(op) not in COMPARE:
                    raise ExprError("unsupported comparison in %r" % self.source)
                if not COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return (self._eval(node.body, ns) if self._eval(node.test, ns)
                    else self._eval(node.orelse, ns))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ExprError("unsupported call in %r" % self.source)
            if node.keywords:
                raise ExprError("keyword arguments are not supported")
            return FUNCTIONS[node.func.id](*[self._eval(a, ns) for a in node.args])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._eval(e, ns) for e in node.elts]
        if isinstance(node, (ast.Attribute, ast.Name)):
            dotted = self._dotted(node) if isinstance(node, ast.Attribute) else node.id
            if dotted is None:
                raise ExprError("unsupported attribute access in %r" % self.source)
            return lookup(ns, dotted)
        raise ExprError("unsupported syntax %s in %r"
                        % (type(node).__name__, self.source))


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
