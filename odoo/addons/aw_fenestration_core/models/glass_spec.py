# -*- coding: utf-8 -*-
from odoo import fields, models


class AwGlassSpec(models.Model):
    """A named glass option, e.g. '8mm Clear Toughened' or '24mm DGU
    6+12+6', pointing at one glass product. Kept single-line by design —
    gaskets are Hardware Set lines, not part of the glass spec. If a real
    DGU build-up ever needs multiple priced components, extend this model
    with a line table then; don't build it speculatively now.
    """
    _name = 'aw.glass.spec'
    _description = 'Fenestration Glass Specification'
    _order = 'name'

    name = fields.Char(required=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_glass').id,
        )])
    thickness_mm = fields.Float(string='Thickness (mm)')
    notes = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A glass spec name must be unique.'),
    ]
