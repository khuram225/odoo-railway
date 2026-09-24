# -*- coding: utf-8 -*-
"""The BOM formula language (spec 6.1), as plain Python with no Odoo
imports, so scripts/check_formulas.py can validate seeded formulas with
exactly the rules the server enforces.

Deliberately NOT odoo.tools.safe_eval: that allows a far larger language
than this needs, and its error messages are about Python rather than
about a formula someone typed into a form. A tiny AST whitelist gives a
short, closed grammar and messages that name the offending bit.
"""
import ast
import math

# Every variable a formula may use, all in mm except N and T.
VARIABLES = {
    'W': 'design overall width',
    'H': 'design overall height',
    'PW': 'panel width',
    'PH': 'panel height',
    'CW': 'width of the container the panel sits in',
    'CH': 'height of the container the panel sits in',
    'N': 'panels in the row',
    'T': 'tracks (sliding)',
}

FUNCTIONS = {
    'min': min,
    'max': max,
    'round': round,
    'ceil': lambda x: math.ceil(x),
    'floor': lambda x: math.floor(x),
    'abs': abs,
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Constant,
    ast.Compare, ast.BoolOp, ast.IfExp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.Load,
)


def validate_formula(expression, allow_empty=True):
    """Return a problem string, or None when the formula is usable.

    Checked at save time so a typo is caught by the person typing it,
    not by the explosion engine hours later on someone else's quote.
    """
    if expression is None or not str(expression).strip():
        return None if allow_empty else 'Formula is empty.'

    text = str(expression).strip()
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError as exc:
        return "%s is not a valid formula: %s" % (text, exc.msg)

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return (
                "%s uses %s, which formulas don't allow. Use numbers, the "
                "variables %s, the functions %s, and + - * / comparisons."
                % (text, type(node).__name__,
                   ', '.join(sorted(VARIABLES)),
                   ', '.join(sorted(FUNCTIONS)))
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return "%s calls something that isn't a plain function." % text
            if node.func.id not in FUNCTIONS:
                return (
                    "%s calls unknown function %s(). Available: %s."
                    % (text, node.func.id, ', '.join(sorted(FUNCTIONS)))
                )
        if isinstance(node, ast.Name) and node.id not in VARIABLES:
            if node.id not in FUNCTIONS:
                return (
                    "%s uses unknown name %r. Available variables: %s."
                    % (text, node.id, ', '.join(sorted(VARIABLES)))
                )
    return None


def evaluate_formula(expression, context, default=0.0):
    """Evaluate a validated formula. Returns `default` when empty.

    Anything that still blows up here -- a division by zero on a design
    with a zero dimension, say -- returns the default rather than taking
    the whole explosion down with it. The checks report the design; one
    bad line shouldn't lose the other forty.
    """
    if expression is None or not str(expression).strip():
        return default
    if validate_formula(expression) is not None:
        return default
    names = dict(FUNCTIONS)
    for key in VARIABLES:
        names[key] = context.get(key, 0)
    try:
        return eval(  # noqa: S307 - grammar restricted by validate_formula
            compile(ast.parse(str(expression).strip(), mode='eval'),
                    '<formula>', 'eval'),
            {'__builtins__': {}}, names)
    except Exception:
        return default


def formula_truthy(expression, context):
    """A condition formula. Empty means 'always', per spec 6.3."""
    if expression is None or not str(expression).strip():
        return True
    return bool(evaluate_formula(expression, context, default=0.0))
