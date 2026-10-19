# -*- coding: utf-8 -*-
"""Scope -> Part -> Piece: the one structure the template form, the
configurator's Profiles tab and its Pieces block all list a window by.

Odoo-free so the three can be held to the same answer by a test (the same
reason as formula.py and layout_rules.py). DISPLAY ONLY: nothing here
changes a length, a quantity or a price.

  Scope  where on the window a profile applies: Outer frame, Dividers,
         Sash (or Sliding, for a sliding system), Fixed, Mesh.
  Part   what it is within that scope: Frame, Bead, Lock bar, Interlock,
         Divider; and in the Mesh scope Frame, Bead and Mesh (the cloth).
  Piece  Top, Bottom, Side, or the position's name when it has no edge.
"""

SCOPES = [
    ('outer', 'Outer frame'),
    ('dividers', 'Dividers'),
    ('sash', 'Sash'),
    ('sliding', 'Sliding'),
    ('fixed', 'Fixed'),
    ('mesh', 'Mesh'),
    ('other', 'Other'),
]

PARTS = [
    ('frame', 'Frame'),
    ('bead', 'Bead'),
    ('lock', 'Lock bar'),
    ('interlock', 'Interlock'),
    ('divider', 'Divider'),
    # Inside the Mesh scope the header already says Mesh, so the parts
    # read the same as a sash's: Frame, Bead, and the cloth itself.
    ('mesh_frame', 'Frame'),
    ('mesh_bead', 'Bead'),
    ('mesh_cloth', 'Mesh'),
    ('other', 'Other'),
]

SCOPE_LABELS = dict(SCOPES)
PART_LABELS = dict(PARTS)

# position scope -> window scope. panel_opening is Sash or Sliding by the
# system's role (see scope_of).
_BY_POSITION_SCOPE = {
    'frame': 'outer',
    'junction_mullion': 'dividers',
    'transom': 'dividers',
    'junction_meeting': 'dividers',
    'junction_interlock': 'dividers',
    'panel_fixed': 'fixed',
    'panel_mesh': 'mesh',
    'mesh_attachment': 'mesh',
}

_BY_PART_GROUP = {
    'outer_frame': 'frame',
    'sashes': 'frame',
    'beads': 'bead',
    'lock': 'lock',
    'interlock_meeting': 'interlock',
    'dividers': 'divider',
}


def scope_of(position_scope, system_role=None):
    """The window scope of a position. A position with no scope (or one
    this does not know) is 'other': reported, never guessed."""
    if position_scope == 'panel_opening':
        return 'sliding' if system_role == 'sliding' else 'sash'
    return _BY_POSITION_SCOPE.get(position_scope or '', 'other')


def part_of(part_group, name, scope):
    """The part of a position. Inside the Mesh scope the part group is
    always fly_screen at best, so Mesh bead is told from Mesh frame by the
    position's NAME containing "bead" -- the same rule the seed uses for
    beads and lock bars. If that ever misfires, a part-group value is the
    fix."""
    if scope == 'mesh':
        if 'bead' in (name or '').lower() or part_group == 'beads':
            return 'mesh_bead'
        return 'mesh_frame'
    return _BY_PART_GROUP.get(part_group or '', 'other')


def side_of(edge, ordinal):
    """The side a piece sits on. Pieces of one line are numbered in the
    order the engine makes them: for 'all' the two horizontal ones first,
    then the two verticals."""
    if edge == 'top':
        return 'Top'
    if edge == 'bottom':
        return 'Bottom'
    if edge == 'sides':
        return 'Side'
    if edge == 'all':
        return ('Top', 'Bottom', 'Side', 'Side')[min(max(ordinal, 1), 4) - 1]
    return ''
