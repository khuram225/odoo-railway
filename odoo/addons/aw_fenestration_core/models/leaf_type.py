# -*- coding: utf-8 -*-
from odoo import fields, models


class AwLeafType(models.Model):
    """Single source of truth for what a leaf mechanism IS — replaces three
    places that used to each hardcode their own copy of the same list:
    aw.window.type's allow_fixed/allow_slider/... booleans, aw.design.leaf's
    leaf_type Selection, and aw.hardware.set.line's applies_to Selection.
    All three now point here instead. Add a new leaf mechanism once, and
    every screen that offers a leaf-type choice picks it up automatically.

    has_hinge_side / has_slide_dir drive which direction fields a Design
    Leaf's form shows for a given type (hinge_side+swing for anything
    hinged, slide_dir for a slider) — data-driven instead of Python
    branching on a hardcoded type string.
    """
    _name = 'aw.leaf.type'
    _description = 'Fenestration Leaf Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    has_hinge_side = fields.Boolean(
        help="This leaf type is hinged — its Design Leaf form should show "
             "hinge_side (left/right/top/bottom) and swing (in/out).")
    has_slide_dir = fields.Boolean(
        help="This leaf type slides — its Design Leaf form should show "
             "slide_dir (left/right).")
    is_glazed = fields.Boolean(
        default=True,
        help="Carries glass (everything except Mesh). Used by the "
             "explosion engine to decide whether to generate a glass "
             "line for this leaf.")

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Leaf Type code must be unique.'),
    ]
