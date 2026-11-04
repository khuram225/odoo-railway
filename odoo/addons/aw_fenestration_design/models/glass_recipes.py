# -*- coding: utf-8 -*-
"""A saved glass spec, as the stack of parts it stands for.

Free of Odoo imports, so scripts/check_glass_recipes.py runs this very code
on the real spec names.

Glass is no longer a saved spec: a panel's glass is its own stack of parts.
The 11 specs that exist become data (hidden, kept), and this is the one
place that says what each of them means as a stack:

- "10mm Clear Toughened"      one sheet, 10 mm Clear
- "24mm DGU (6 + 12 + 6)"     sheet 6, gap 12, sheet 6
- "6+10+8 Clear Tempered"     sheet 6, gap 10, sheet 8

Tempered, Toughened and Frosted are processing, which comes later as
services; until then those specs become PLAIN Clear sheets with a REMARK
("was: Clear Tempered") that quotes and shop drawings print, so a frosted
glass is never printed as plain Clear. A migrated gap is a default (Air,
Aluminium spacer, Silver, at the width in the name) and is marked as not
checked. A spec with no price migrates its sheets with a manual rate of 0,
flagged "migrated", so the migration does not change a quote; a spec that
has a price takes the list rate, which is the same number (the old product
price equalled the supplier's list).
"""
import re

COLOUR = 'Clear'
PROCESSING_WORDS = ('tempered', 'toughened', 'frosted')

_SINGLE = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*mm\s+(.+?)\s*$', re.I)
_LAKE_CITY = re.compile(
    r'^\s*(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)\s+(.+?)\s*$', re.I)
_DGU = re.compile(
    r'^\s*\d+\s*mm\s+DGU\s*\(\s*(\d+)\s*\+\s*(\d+)\s*(?:air|argon)?\s*\+\s*(\d+)\s*\)\s*$',
    re.I)


def _remark(rest):
    """'Clear Tempered' -> 'was: Clear Tempered'; plain 'Clear' -> ''."""
    words = (rest or '').lower()
    if any(word in words for word in PROCESSING_WORDS):
        return 'was: %s' % rest.strip()
    return ''


def recipe_for_spec(name, priced=False):
    """The parts a spec name stands for, as plain dicts, in order, or None
    for a name this does not recognise (nothing is guessed).

    `priced` is whether the old spec's product carried a price: then the
    sheets take the list rate; otherwise they get a manual 0, "migrated"."""
    text = (name or '').strip()

    def sheet(mm, remark=''):
        return {'kind': 'sheet', 'glass_type': COLOUR, 'thickness_mm': float(mm),
                'remark': remark, 'manual_zero': not priced,
                'migrated': True}

    def gap(width):
        return {'kind': 'gap', 'gap_mm': float(width), 'spacer_type': 'Aluminium',
                'spacer_colour': 'Silver', 'gas': 'Air',
                'default_gap': True, 'migrated': True}

    match = _DGU.match(text)
    if match:
        first, middle, last = match.groups()
        return [sheet(first), gap(middle), sheet(last)]
    match = _LAKE_CITY.match(text)
    if match:
        first, middle, last, rest = match.groups()
        remark = _remark(rest)
        return [sheet(first, remark), gap(middle), sheet(last, remark)]
    match = _SINGLE.match(text)
    if match:
        mm, rest = match.groups()
        return [sheet(mm, _remark(rest))]
    return None


# What a new "Double Glaze - Openable" window starts with: sheet, gap, sheet,
# a plain sealed unit. Not a migration, so nothing is flagged and the sheets
# take their list rate.
DEFAULT_SEALED_UNIT = [
    {'kind': 'sheet', 'glass_type': COLOUR, 'thickness_mm': 6.0},
    {'kind': 'gap', 'gap_mm': 12.0, 'spacer_type': 'Aluminium',
     'spacer_colour': 'Silver', 'gas': 'Air'},
    {'kind': 'sheet', 'glass_type': COLOUR, 'thickness_mm': 6.0},
]
