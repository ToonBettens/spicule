"""Expressions and numbers as text (spec 7.2 and 7.3).

The IR holds expressions as trees. Text is how the HDL spells them:
`parse_expression` builds a tree from text, `format_expression` writes it back.

    expr    := term (("+" | "-") term)*
    term    := unary (("*" | "/") unary)*
    unary   := ("+" | "-") unary | atom
    atom    := NUMBER | IDENTIFIER | IDENTIFIER "(" expr ("," expr)* ")" | "(" expr ")"
"""

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import NoReturn

from spicule.ir.model import IDENTIFIER, Binary, Call, Expr, Expression, Neg, Number, ParamRef

#: Expression functions and their number of arguments.
FUNCTIONS: dict[str, int] = {
    "abs": 1,
    "sqrt": 1,
    "exp": 1,
    "ln": 1,
    "log10": 1,
    "min": 2,
    "max": 2,
    "pow": 2,
}

#: A number as text: optional sign, digits with an optional fraction, an optional exponent.
NUMBER_PATTERN = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$")


class ExpressionError(ValueError):
    """Text that doesn't follow the expression or number grammar."""


# Numbers


def parse_number(text: str) -> Decimal:
    """Parse a number in the grammar of spec 7.3 into an exact `Decimal`. No scale factors."""
    if not NUMBER_PATTERN.match(text):
        raise ExpressionError(f"not a number: {text!r}")
    try:
        return Decimal(text)
    except InvalidOperation as error:  # An exponent beyond what `Decimal` can hold.
        raise ExpressionError(f"not a number: {text!r}") from error


def format_number(value: Decimal) -> str:
    """
    The canonical text of a number (spec 7.3): engineering notation, with the fewest exact mantissa digits,
    1 <= |mantissa| < 1000 and an exponent that is a multiple of 3. Exponent 0 is written plainly, zero as `0`.
    """
    if not value.is_finite():
        raise ValueError(f"not a finite number: {value}")
    if value.is_zero():
        return "0"
    value = value.normalize()
    lead = value.adjusted()  # exponent of the leading digit
    exponent = (lead // 3) * 3
    mantissa = format(value.scaleb(-exponent).normalize(), "f")
    return mantissa if exponent == 0 else f"{mantissa}e{exponent}"


# Parsing

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    rf"|(?P<name>{IDENTIFIER})"
    r"|(?P<op>[-+*/(),])"
    r")"
)


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens: list[tuple[str, str, int]] = []  # (kind, text, position)
        pos = 0
        end = len(text.rstrip())
        while pos < end:
            match = _TOKEN.match(text, pos)
            if match is None or match.end() == pos or match.lastgroup is None:
                self.fail(f"unexpected character {text[pos:].lstrip()[:1]!r}", pos)
            kind = match.lastgroup
            self.tokens.append((kind, match.group(kind), match.start(kind)))
            pos = match.end()
        for (k1, v1, _), (k2, v2, p2) in zip(self.tokens, self.tokens[1:], strict=False):
            if k1 == "number" and k2 == "name":
                self.fail(f"scale factors are not allowed: {v1}{v2}", p2)
        self.pos = 0

    def fail(self, message: str, position: int | None = None) -> NoReturn:
        at = f" at column {position + 1}" if position is not None else ""
        raise ExpressionError(f"{message}{at} in {self.text!r}")

    def peek(self) -> tuple[str, str, int] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str, int]:
        token = self.peek()
        if token is None:
            self.fail("unexpected end")
        self.pos += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] in ops

    def expect(self, op: str) -> None:
        kind, value, position = self.take()
        if kind != "op" or value != op:
            self.fail(f"expected {op!r}, found {value!r}", position)

    def parse(self) -> Expr:
        if not self.tokens:
            self.fail("empty expression")
        tree = self.expr()
        token = self.peek()
        if token is not None:
            self.fail(f"unexpected {token[1]!r}", token[2])
        return tree

    def expr(self) -> Expr:
        left = self.term()
        while self.at_op("+", "-"):
            op = self.take()[1]
            left = Binary(op=op, left=left, right=self.term())  # ty: ignore[invalid-argument-type]
        return left

    def term(self) -> Expr:
        left = self.unary()
        while self.at_op("*", "/"):
            op = self.take()[1]
            left = Binary(op=op, left=left, right=self.unary())  # ty: ignore[invalid-argument-type]
        return left

    def unary(self) -> Expr:
        if self.at_op("+"):
            self.take()
            return self.unary()
        if self.at_op("-"):
            self.take()
            return Neg(operand=self.unary())
        return self.atom()

    def atom(self) -> Expr:
        kind, value, position = self.take()
        if kind == "number":
            return Number(value=parse_number(value))
        if kind == "name":
            if not self.at_op("("):
                return ParamRef(name=value)
            self.take()
            args = [self.expr()]
            while self.at_op(","):
                self.take()
                args.append(self.expr())
            self.expect(")")
            if value not in FUNCTIONS:
                self.fail(f"unknown function {value!r}", position)
            if len(args) != FUNCTIONS[value]:
                self.fail(f"{value}() takes {FUNCTIONS[value]} argument(s), got {len(args)}", position)
            return Call(function=value, args=tuple(args))
        if kind == "op" and value == "(":
            inner = self.expr()
            self.expect(")")
            return inner
        self.fail(f"unexpected {value!r}", position)


def parse_expression(text: str) -> Expression:
    """Parse text in the grammar of spec 7.2 into an `Expression`. Raises `ExpressionError` with the column."""
    return Expression(root=_Parser(text).parse())


# Printing

# Binding strength: higher binds tighter. A node is wrapped in parentheses when its context needs more.
_STRENGTH = {"+": 1, "-": 1, "*": 2, "/": 2, "neg": 3, "atom": 4}


def format_expression(expression: Expression | Expr, *, functions: Mapping[str, str] | None = None) -> str:
    """
    The text of an expression, with only the parentheses it needs. `parse_expression` reads it back.

    `functions` lets a dialect spell a function differently: a template per function name, with `{0}`, `{1}` for
    the arguments, e.g. `{"pow": "({0})**({1})"}`. The result is treated as an atom.
    """
    root = expression.root if isinstance(expression, Expression) else expression
    return _render(root, 0, functions or {})


def _render(node: Expr, needed: int, functions: Mapping[str, str]) -> str:
    match node:
        case Number(value=v):
            text, strength = format_number(v), _STRENGTH["atom"]
        case ParamRef(name=n):
            text, strength = n, _STRENGTH["atom"]
        case Call(function=f, args=args):
            parts = [_render(a, 0, functions) for a in args]
            template = functions.get(f)
            text = template.format(*parts) if template else f"{f}({', '.join(parts)})"
            strength = _STRENGTH["atom"]
        case Neg(operand=operand):
            text, strength = f"-{_render(operand, _STRENGTH['neg'], functions)}", _STRENGTH["neg"]
        case Binary(op=op, left=left, right=right):
            # Left associative: the right operand needs parentheses at the same strength (a - (b - c)).
            strength = _STRENGTH[op]
            space = " " if op in "+-" else ""
            left_text = _render(left, strength, functions)
            text = f"{left_text}{space}{op}{space}{_render(right, strength + 1, functions)}"
    return f"({text})" if strength < needed else text


# Inspection and helpers


def param_refs(expression: Expression | Expr) -> list[str]:
    """The parameter names an expression uses, in order of first appearance."""
    found: list[str] = []

    def walk(node: Expr) -> None:
        match node:
            case ParamRef(name=n):
                if n not in found:
                    found.append(n)
            case Neg(operand=operand):
                walk(operand)
            case Binary(left=left, right=right):
                walk(left)
                walk(right)
            case Call(args=args):
                for arg in args:
                    walk(arg)

    walk(expression.root if isinstance(expression, Expression) else expression)
    return found


def number(value: str | int | Decimal) -> Expression:
    """
    A plain number as an `Expression`. A negative number becomes a negation of its magnitude. A float is refused: its
    binary value isn't the number it prints as.
    """
    if isinstance(value, str):
        d = parse_number(value)
    elif isinstance(value, Decimal | int) and not isinstance(value, bool):
        d = Decimal(value)
    else:
        raise ExpressionError(f"not a str, int or Decimal: {value!r}")
    if not d.is_finite():
        raise ExpressionError(f"not a finite number: {value!r}")
    root: Expr = Number(value=abs(d))
    return Expression(root=Neg(operand=root) if d < 0 else root)


def expr(text: str) -> Expression:
    """Shorthand for `parse_expression`, for building IR by hand: `expr("2*l/w")`."""
    return parse_expression(text)
