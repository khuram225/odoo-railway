# -*- coding: utf-8 -*-
from odoo import api, fields, models

NEEDS_HARDWARE_PARAM = 'aw_fenestration.needs_hardware_seeded'
# Panel types that carry no hardware to start with. Editable afterwards.
NO_HARDWARE_CODES = ('FIXED', 'MESH')


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

    needs_hardware = fields.Boolean(
        default=True,
        help="A panel of this type is expected to have hardware. A window "
             "with such a panel and no hardware on it gets a Checks warning "
             "naming the panel.")

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Leaf Type code must be unique.'),
    ]

    @api.model
    def _seed_needs_hardware(self):
        """Switch the flag off for Fixed and Mesh, once.

        A Boolean has no empty state to test (see _seed_required_flags on
        the profile positions), so this marks itself done with a
        parameter: re-asserting it every upgrade would silently undo a
        deliberate change on the Panel Types screen.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(NEEDS_HARDWARE_PARAM):
            return 0
        types = self.with_context(active_test=False).search(
            [('code', 'in', NO_HARDWARE_CODES)])
        types.write({'needs_hardware': False})
        param.set_param(NEEDS_HARDWARE_PARAM, '1')
        return len(types)
