# -*- coding: utf-8 -*-
"""How a glass TYPE and a thickness name one Glass Sheet variant.

Free of Odoo imports, so scripts/check_glass_variants.py runs this very
code against the real Ghani list.

A glass type is a colour and a kind: "Grey" is Grey + Plain, "Ref. Grey" is
Grey + Reflective, "WC Green" is Green + WC, "CC Grey" is Grey + CC ("WC" and
"CC" are kept as written, with no guess at what they stand for). Together
with a thickness in mm that is one variant of the one Glass Sheet product.
"""
import re

COLOURS = ['Clear', 'Green', 'Brown', 'Blue', 'Ford Blue', 'Grey']
KINDS = ['Plain', 'Reflective', 'WC', 'CC']
THICKNESSES_MM = [2, 3, 4, 5, 6, 8, 10, 12]


def type_parts(name):
    """'Ref. Grey' -> ('Grey', 'Reflective'). Raises ValueError for a
    type that is not a known colour with a known kind: nothing is guessed."""
    text = (name or '').strip()
    kind = 'Plain'
    match = re.match(r'(?i)^ref\.?\s*(.*)$', text)
    if match:
        kind, text = 'Reflective', match.group(1).strip()
    else:
        match = re.match(r'(?i)^(WC|CC)\b\s*(.*)$', text)
        if match:
            kind, text = match.group(1).upper(), match.group(2).strip()
    for colour in COLOURS:
        if colour.lower() == text.lower():
            return colour, kind
    raise ValueError('glass type %r has no known colour' % name)


def type_name(colour, kind):
    """The inverse of type_parts."""
    if kind == 'Reflective':
        return 'Ref. %s' % colour
    if kind in ('WC', 'CC'):
        return '%s %s' % (kind, colour)
    return colour


def thickness_name(mm):
    """The value name of a thickness: 6 -> '6 mm'."""
    return '%g mm' % mm


def thickness_mm(name):
    """'6 mm' -> 6.0, or None when it is not a thickness value name."""
    match = re.match(r'^\s*(\d+(?:\.\d+)?)\s*mm\s*$', name or '', re.I)
    return float(match.group(1)) if match else None
