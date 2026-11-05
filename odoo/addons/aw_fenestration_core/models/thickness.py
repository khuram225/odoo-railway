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


def choose_thickness(preferred, available):
    """Which thickness to put on a seeded Profile Section line.

    `preferred` and `available` are plain value NAMES, so this stays
    Odoo-free and `scripts/check_section_seed.py` can run the real rule
    against the real seed data rather than a second copy of it. That
    matters here: the rule and the data disagreeing is precisely the
    bug, and a check that reimplemented the rule would agree with
    itself for ever.

    Returns (name, problem). A thickness the product is not sold in
    makes NO variant -- the attribute is Dynamic-creation -- so the
    line silently resolves to no product and nothing can be costed.
    One available thickness is not a choice and is taken. A real
    choice is never guessed: the preference is kept so the line still
    exists, and the problem is returned for the caller to report.
    """
    if preferred and preferred in available:
        return preferred, ''
    if len(available) == 1:
        return available[0], ''
    if not available:
        return preferred, 'offers no thickness at all'
    return preferred, "offers no '%s' thickness, only %s" % (
        preferred, ', '.join(sorted(available)))


def default_thickness(available, used=(), preferred=''):
    """The thickness a component added to a window starts with. Never
    empty while the profile offers any.

    `available` are the value names the profile is sold in; `used` are
    the names the window's other lines use, most common first. In order:
    the preference when the profile offers it, the only one when there is
    one, the first of `used` the profile offers, else the lowest (named
    grades like Normal and Standard have no number and sort after the
    numbered ones). The user can change it afterwards; asking them to
    choose BEFORE the row exists is what this replaces.
    """
    names = sorted(available)
    if not names:
        return ''
    if preferred and preferred in names:
        return preferred
    if len(names) == 1:
        return names[0]
    for name in used:
        if name in names:
            return name

    def lowest(name):
        millimetres = thickness_mm(name)
        return (millimetres is None, millimetres or 0.0, name)

    return min(names, key=lowest)


def implausible_thickness(value):
    """True when a value cannot be a wall thickness.

    Only rejects what is measurably wrong. A name it does not
    recognise is left alone -- being unable to parse something is not
    evidence that it is invalid.
    """
    millimetres = thickness_mm(value)
    return millimetres is not None and millimetres > THICKNESS_MAX_MM
