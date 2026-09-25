# -*- coding: utf-8 -*-
"""Canonical thickness spelling, and what is not a thickness at all.

This is the SINGLE source of the mapping. It used to live only in
`scripts/rebuild_melt_and_import.py`, which was fine while the price
list was the only thing that produced thickness values; the catalogue
import needs the same rule, and two copies of it would eventually
disagree and silently mis-key attribute values against each other.
That script now imports this, following the same pattern as
`layout_rules.py` and `formula.py`.

Odoo-free on purpose so the script can use it without an Odoo
environment.
"""
import re

# An aluminium extrusion's wall thickness. The largest value in the
# imported price list is 21.5 mm, so anything above this is not a
# thickness -- it is a length or a section dimension that has landed in
# the wrong column. Two rows of the catalogue do exactly that:
# VARIOLINE-09 carries "2300MM", and UNEQUAL ANGLE ... carries
# "130MM; 50MM" while its own dimensions column is empty.
#
# Creating those as Thickness attribute values would put them in every
# thickness dropdown in the system for ever, so they are rejected and
# reported instead.
THICKNESS_MAX_MM = 25.0


def norm_thickness(raw):
    """Canonicalize a raw thickness string to one spelling per concept.

    Verified exhaustively against the 33 distinct raw strings in the
    price list: no lowercase 'mm', no space/comma variants, no
    trailing-zero numeric duplicates (e.g. no '1.60MM' alongside
    '1.6MM') exist beyond the Std/STD/Std. case handled here.
    """
    raw = (raw or '').strip()
    if raw == '-':
        return ''          # no thickness dimension applies to this profile
    if raw == 'Nor':
        return 'Normal'
    if raw in ('Std', 'STD', 'Std.'):
        return 'Standard'
    match = re.match(r'^(\d+(?:\.\d+)?)\s*MM?$', raw, re.IGNORECASE)
    if match:
        return '%sMM' % match.group(1)
    return raw             # unrecognized -- surfaced by review, not guessed


def thickness_mm(value):
    """The numeric millimetres in a canonical value, or None.

    'Normal' and 'Standard' are named grades rather than measurements,
    so they have no number and are always plausible.
    """
    match = re.match(r'^(\d+(?:\.\d+)?)MM$', (value or '').strip(),
                     re.IGNORECASE)
    return float(match.group(1)) if match else None


def implausible_thickness(value):
    """True when a value cannot be a wall thickness.

    Only rejects what is measurably wrong. A name it does not
    recognise is left alone -- being unable to parse something is not
    evidence that it is invalid.
    """
    millimetres = thickness_mm(value)
    return millimetres is not None and millimetres > THICKNESS_MAX_MM
