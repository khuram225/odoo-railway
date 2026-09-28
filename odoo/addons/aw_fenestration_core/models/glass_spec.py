# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AwGlassSpec(models.Model):
    """A named glass option, e.g. '8mm Clear Toughened' or '24mm DGU
    6+12+6', pointing at one glass product. Kept single-line by design —
    gaskets are Hardware Set lines, not part of the glass spec. If a real
    DGU build-up ever needs multiple priced components, extend this model
    with a line table then; don't build it speculatively now.
    """
    _name = 'aw.glass.spec'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Glass Specification'
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict', tracking=True,
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_glass').id,
        )])
    glazing = fields.Selection([
        ('single', 'Single glazed'),
        ('double', 'Double glazed'),
    ], default='single', tracking=True,
        help="Which glazing family may use this spec. A sealed unit is "
             "double; a single pane, however thick, is single.")
    thickness_mm = fields.Float(string='Thickness (mm)')
    weight_kg_m2 = fields.Float(
        string='Weight (kg/m²)',
        help="Used by the manufacturability checks in Phase 4, e.g. sash "
             "weight against the hardware's limit.")
    notes = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A glass spec name must be unique.'),
    ]

    @api.model
    def _seed_glazing(self):
        """Mark the sealed units double, once.

        Everything seeded is a single pane except the DGU, so the
        default already covers the rest; this only has to find the
        units. Matches on "DGU" in the name rather than on thickness,
        because a 24 mm single pane would be a strange thing to own but
        is not impossible, and thickness alone cannot tell them apart.
        """
        param = self.env['ir.config_parameter'].sudo()
        key = 'aw_fenestration.glass_glazing_seeded'
        if param.get_param(key):
            return 0
        marked = 0
        for spec in self.with_context(active_test=False).search([]):
            if spec.glazing == 'double':
                continue
            if 'DGU' in (spec.name or '').upper():
                spec.glazing = 'double'
                marked += 1
        param.set_param(key, '1')
        return marked
