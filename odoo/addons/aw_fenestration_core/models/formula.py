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
    # Only meaningful on a panel: the length of the SASH profile piece
    # already generated for this panel's lock side. The lock bar is
    # specified as a fraction of the stile it is fitted to, so it has
    # to be that piece's length and not PH -- the stile is PH less the
    # section's own deduction, and 0.8 of the wrong one is 8mm out on
    # a 1m sash. Zero anywhere a panel has no lock side.
    'LS': 'sash length on the lock side',
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


def substitute_formula(expression, context):
    """The formula with its variables replaced by the values used.

    "PW - 10" becomes "1066.8 - 10": the arithmetic a person can check
    by hand against the drawing, which is the whole point of the
    calculation sheet.

    Rendered from the SAME validated AST `evaluate_formula` compiles, so
    the two cannot describe different sums. It deliberately does not
    evaluate anything: no folding of "2 * 3" into "6", because the
    reader is checking the working, not the answer. Operator precedence
    is preserved with brackets only where the tree says they are needed,
    so "(PW - 10) / 2" keeps them and "PW - 10 / 2" does not gain any.

    Returns '' for an empty formula and the expression unchanged if it
    will not parse -- this is for reading, and a reader is better served
    by the raw text than by a blank.
    """
    if expression is None or not str(expression).strip():
        return ''
    text = str(expression).strip()
    if validate_formula(text) is not None:
        return text
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        return text

    def number(value):
        # Two decimals, trailing zeros trimmed: integers stay integers so
        # "2" does not read as "2.0", and a panel height of 1400.25 is
        # not shown as 1400.2. That mattered -- at one decimal the
        # rendered sum came to 4934.0 where the real answer was 4934.1,
        # and a verification sheet whose working does not reproduce its
        # own result is worse than no sheet.
        if isinstance(value, bool):
            return '1' if value else '0'
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return ('%.2f' % value).rstrip('0').rstrip('.') or '0'
        return str(value)

    binary = {
        ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
        ast.FloorDiv: '//', ast.Mod: '%', ast.Pow: '**',
    }
    compare = {
        ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.LtE: '<=',
        ast.Gt: '>', ast.GtE: '>=',
    }

    def render(node, parent=None):
        if isinstance(node, ast.Expression):
            return render(node.body)
        if isinstance(node, ast.Name):
            if node.id in VARIABLES:
                return number(context.get(node.id, 0))
            return node.id
        if isinstance(node, ast.Constant):
            return number(node.value)
        if isinstance(node, ast.BinOp):
            inner = '%s %s %s' % (render(node.left, node),
                                  binary.get(type(node.op), '?'),
                                  render(node.right, node))
            # Bracket only when the parent binds tighter, which is what
            # keeps the rendering faithful without littering it.
            return '(%s)' % inner if isinstance(parent, ast.BinOp) else inner
        if isinstance(node, ast.UnaryOp):
            sign = '-' if isinstance(node.op, ast.USub) else (
                'not ' if isinstance(node.op, ast.Not) else '+')
            return '%s%s' % (sign, render(node.operand, node))
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else '?'
            return '%s(%s)' % (name, ', '.join(
                render(arg) for arg in node.args))
        if isinstance(node, ast.Compare):
            parts = [render(node.left, node)]
            for operator, right in zip(node.ops, node.comparators):
                parts.append(compare.get(type(operator), '?'))
                parts.append(render(right, node))
            return ' '.join(parts)
        if isinstance(node, ast.BoolOp):
            joiner = ' and ' if isinstance(node.op, ast.And) else ' or '
            return joiner.join(render(value, node) for value in node.values)
        if isinstance(node, ast.IfExp):
            return '%s if %s else %s' % (render(node.body, node),
                                         render(node.test, node),
                                         render(node.orelse, node))
        return '?'

    try:
        return render(tree)
    except Exception:
        return text


def formula_truthy(expression, context):
    """A condition formula. Empty means 'always', per spec 6.3."""
    if expression is None or not str(expression).strip():
        return True
    return bool(evaluate_formula(expression, context, default=0.0))
