# -*- coding: utf-8 -*-
"""Design Ref order: W1, W2 ... W10, W11 (Odoo-free, so
`scripts/check_natural_order.py` runs the real function)."""
import re


def natural_key(name, ident=0):
    """Digits compare as numbers, the rest as lower case, so W2 comes before W10
    and W1 before W1.1; a ref with no digits at all (GF-BATH) comes after the
    numbered ones; ties by id."""
    text = (name or '').lower()
    parts = re.split(r'(\d+)', text)
    return (0 if re.search(r'\d', text) else 1,
            [(0, int(p)) if p.isdigit() else (1, p) for p in parts],
            ident)
