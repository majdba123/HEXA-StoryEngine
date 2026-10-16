"""Evaluate the FFmpeg expressions the renderer itself writes, in Python.

Only the subset HEXA generates is accepted (numbers, ``t``, ``overlay_w``/``overlay_h``,
``+ - * /``, and ``if``/``lt``/``lte``/``gt``/``gte``/``between``/``pow``/``clip``/``max``/
``min``/``abs``). The expression is parsed into a closure over a whitelisted syntax tree,
never ``eval``-ed, so renderer-side measurements (e.g. motion-blur exposure) use exactly
the position FFmpeg draws.
"""
from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable

_FUNCTIONS: dict[str, Callable[..., float]] = {
    "_if": lambda condition, then, otherwise: then if condition else otherwise,
    "lt": lambda a, b: 1.0 if a < b else 0.0,
    "lte": lambda a, b: 1.0 if a <= b else 0.0,
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "gte": lambda a, b: 1.0 if a >= b else 0.0,
    "between": lambda x, a, b: 1.0 if a <= x <= b else 0.0,
    # C pow(): a negative base with a fractional exponent is NaN, never a complex number
    "pow": lambda a, b: math.nan if a < 0 and not float(b).is_integer() else float(a ** b),
    "clip": lambda x, a, b: max(a, min(b, x)),
    "max": max,
    "min": min,
    "abs": abs,
}
_VARIABLES = {"t", "overlay_w", "overlay_h"}


def compile_expression(text: str) -> Callable[..., float]:
    """Return ``f(t, overlay_w=0, overlay_h=0)`` for one FFmpeg expression string."""
    source = re.sub(r"\bif\(", "_if(", text.strip().strip("'"))
    tree = ast.parse(source, mode="eval")

    def build(node: ast.AST) -> Callable[[dict[str, float]], float]:
        if isinstance(node, ast.Expression):
            return build(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            value = float(node.value)
            return lambda env: value
        if isinstance(node, ast.Name) and node.id in _VARIABLES:
            name = node.id
            return lambda env: env[name]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            operand = build(node.operand)
            if isinstance(node.op, ast.USub):
                return lambda env: -operand(env)
            return operand
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = build(node.left), build(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return lambda env: left(env) + right(env)
            if isinstance(op, ast.Sub):
                return lambda env: left(env) - right(env)
            if isinstance(op, ast.Mult):
                return lambda env: left(env) * right(env)
            return lambda env: left(env) / right(env) if right(env) != 0 else math.nan
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCTIONS and not node.keywords):
            function = _FUNCTIONS[node.func.id]
            arguments = [build(argument) for argument in node.args]
            if node.func.id == "_if":
                condition, then, otherwise = arguments
                return lambda env: then(env) if condition(env) else otherwise(env)
            return lambda env: function(*(argument(env) for argument in arguments))
        raise ValueError(f"unsupported FFmpeg expression element: {ast.dump(node)[:80]}")

    evaluate = build(tree)

    def call(t: float, overlay_w: float = 0.0, overlay_h: float = 0.0) -> float:
        return float(evaluate({"t": float(t), "overlay_w": float(overlay_w), "overlay_h": float(overlay_h)}))

    return call
