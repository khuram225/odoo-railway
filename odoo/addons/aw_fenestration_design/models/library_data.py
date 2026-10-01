# -*- coding: utf-8 -*-
"""The Layout Library's seeded Shapes and Designs, as plain data.

Odoo-free on purpose, like `layout_rules.py` and `formula.py`:
`scripts/check_preset_layouts.py` runs every one of these through the
SAME validator the upgrade uses, so a malformed layout here fails
before it can fail an install. The XML-seeded presets were already
checked that way; these were seeded from Python and would not have
been.
"""

# The mechanism-based codes the revised library replaces. Prefix match,
# because every one of them is <MECH>-<something>.
RETIRED_PREFIXES = ('OPN-', 'SLD-', 'TT-', 'TWN-', 'CW-')


def _row(*weights_and_leaves):
    """A row: (height weight, [leaf dicts])."""
    height, leaves = weights_and_leaves
    return {'h': height, 'leaves': leaves}


def _fixed(count=1, weight=1):
    return [{'w': weight, 'type': 'FIXED'} for _ in range(count)]


# -- Shapes: geometry only, every panel Fixed -------------------------
# A top light is weight 1 against 3, which reads as a light rather than
# as a half-height row; equal rows use equal weights.
SHAPES = (
    ('1 panel', 'SHP-1', 10, [_row(1, _fixed(1))]),
    ('2 across', 'SHP-2A', 20, [_row(1, _fixed(2))]),
    ('3 across', 'SHP-3A', 30, [_row(1, _fixed(3))]),
    ('4 across', 'SHP-4A', 40, [_row(1, _fixed(4))]),
    ('1 above 1 below', 'SHP-1A1B', 50,
     [_row(1, _fixed(1)), _row(1, _fixed(1))]),
    ('Top light over 2 across', 'SHP-TL2A', 60,
     [_row(1, _fixed(1)), _row(3, _fixed(2))]),
    ('Top light over 3 across', 'SHP-TL3A', 70,
     [_row(1, _fixed(1)), _row(3, _fixed(3))]),
    ('2 above 1 below', 'SHP-2A1B', 80,
     [_row(1, _fixed(2)), _row(1, _fixed(1))]),
    ('2 x 2', 'SHP-2X2', 90,
     [_row(1, _fixed(2)), _row(1, _fixed(2))]),
    ('3 stacked', 'SHP-3S', 100,
     [_row(1, _fixed(1)), _row(1, _fixed(1)), _row(1, _fixed(1))]),
)

# -- Designs: from the client's 169 M1 list ---------------------------
# [revisit] The client is to correct these names and the panel types.
# "Openable" is seeded as CASEMENT because that is the openable
# mechanism his Double Glaze - Openable system hosts; a tilt & turn or
# an awning is the same layout with a different panel type, and
# changing it is one click in the configurator rather than a new preset.
_CASE_L = {'w': 1, 'type': 'CASEMENT', 'hinge': 'left', 'swing': 'out'}
_CASE_R = {'w': 1, 'type': 'CASEMENT', 'hinge': 'right', 'swing': 'out'}

DESIGNS = (
    ('Fixed', 'DSN-FIX', 10, [_row(1, _fixed(1))]),
    ('Fixed + Sliding', 'DSN-FSL', 20,
     [_row(1, [{'w': 1, 'type': 'FIXED'},
               {'w': 1, 'type': 'SLIDER', 'slide': 'left'}])]),
    ('Fixed + Openable', 'DSN-FOP', 30,
     [_row(1, [{'w': 1, 'type': 'FIXED'}, dict(_CASE_R)])]),
    ('Top-hung over Fixed', 'DSN-THF', 40,
     [_row(1, [{'w': 1, 'type': 'AWNING', 'swing': 'out'}]),
      _row(3, _fixed(1))]),
    ('Openable + Fixed + Openable', 'DSN-OFO', 50,
     [_row(1, [dict(_CASE_L), {'w': 2, 'type': 'FIXED'}, dict(_CASE_R)])]),
    ('Openable pair over Fixed', 'DSN-OPF', 60,
     [_row(1, [dict(_CASE_L), dict(_CASE_R)]), _row(2, _fixed(1))]),
    ('Fixed + Openable + Openable + Fixed', 'DSN-FOOF', 70,
     [_row(1, [{'w': 1, 'type': 'FIXED'}, dict(_CASE_L), dict(_CASE_R),
               {'w': 1, 'type': 'FIXED'}])]),
    ('3 stacked', 'DSN-3S', 80,
     [_row(1, _fixed(1)), _row(1, _fixed(1)), _row(1, _fixed(1))]),
    ('Curtain wall 3 stacked', 'DSN-CW3S', 90,
     [_row(1, _fixed(1)), _row(1, _fixed(1)), _row(1, _fixed(1))]),
)
