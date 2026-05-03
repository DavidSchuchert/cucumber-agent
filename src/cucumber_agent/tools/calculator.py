"""Safe calculator tool — evaluates mathematical expressions without eval()."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

# Allowed binary operators
_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

# Allowed unary operators
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Allowed functions (safe math functions only)
_SAFE_FUNCTIONS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "factorial": lambda n: math.factorial(int(n)),  # float→int since eval returns floats
    "gcd": math.gcd,
    "pow": math.pow,
    "hypot": math.hypot,
}

# Allowed constants
_SAFE_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}

# Maximum recursion depth to prevent deeply nested expressions
_MAX_DEPTH = 50


def _safe_eval(node: ast.AST, depth: int = 0) -> float:
    """Recursively evaluate an AST node. Raises ValueError on disallowed constructs."""
    if depth > _MAX_DEPTH:
        raise ValueError("Expression is too deeply nested")

    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, depth + 1)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        name = node.id
        if name in _SAFE_CONSTANTS:
            return _SAFE_CONSTANTS[name]
        raise ValueError(f"Unknown name: '{name}'. Allowed constants: {', '.join(_SAFE_CONSTANTS)}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left, depth + 1)
        right = _safe_eval(node.right, depth + 1)
        try:
            return float(_BIN_OPS[op_type](left, right))
        except ZeroDivisionError:
            raise ValueError("Division by zero")
        except OverflowError:
            raise ValueError("Result is too large (overflow)")

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand, depth + 1)
        return float(_UNARY_OPS[op_type](operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed (e.g. sqrt(2))")
        func_name = node.func.id
        if func_name not in _SAFE_FUNCTIONS:
            raise ValueError(
                f"Unknown function: '{func_name}'. Allowed: {', '.join(sorted(_SAFE_FUNCTIONS))}"
            )
        args = [_safe_eval(arg, depth + 1) for arg in node.args]
        if node.keywords:
            raise ValueError("Keyword arguments in function calls are not supported")
        try:
            result = _SAFE_FUNCTIONS[func_name](*args)
            return float(result)
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            raise ValueError(f"Math error in {func_name}(): {exc}") from exc

    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def safe_calculate(expression: str) -> float:
    """Parse and evaluate a mathematical expression safely (no eval())."""
    expression = expression.strip()
    if not expression:
        raise ValueError("Empty expression")
    if len(expression) > 500:
        raise ValueError("Expression is too long (max 500 characters)")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in expression: {exc}") from exc

    return _safe_eval(tree)


class CalculatorTool(BaseTool):
    """Safe mathematical expression evaluator."""

    name = "calculator"
    description = (
        "Evaluates mathematical expressions safely. Supports +, -, *, /, ** (power), "
        "// (floor division), % (modulo), and functions: sqrt, sin, cos, tan, "
        "asin, acos, atan, log, log2, log10, exp, abs, ceil, floor, round, "
        "factorial, gcd, hypot, pow. Constants: pi, e, tau. "
        "Use this for any arithmetic or mathematical computation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "Mathematical expression to evaluate. "
                    "Examples: '2 + 3 * 4', 'sqrt(2)', 'sin(pi/2)', '2**10'"
                ),
            }
        },
        "required": ["expression"],
    }
    auto_approve = True

    async def execute(self, expression: str) -> ToolResult:
        try:
            result = safe_calculate(expression)
            # Format result: show integer if no fractional part, else float
            if result == int(result) and not math.isinf(result) and not math.isnan(result):
                formatted = str(int(result))
            else:
                formatted = f"{result:.10g}"
            return ToolResult(success=True, output=f"{expression} = {formatted}")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Calculation error: {exc}")


ToolRegistry.register(CalculatorTool())
