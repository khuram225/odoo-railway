# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Text categories seeded before families existed, mapped onto the family
# they became. Anything else falls back to Other, per spec 4.1.
CATEGORY_TO_FAMILY = {
    'Openable Designs': 'OPN',
    'Sliding Designs': 'SLD',
    'Add-on Mesh Sash': 'MSH',
    'Stick Curtain Wall Designs': 'CW',
}


class AwLayoutFamily(models.Model):
    """How the configurator's library is grouped.

    kind decides what clicking an item DOES, which is why this is a field
    rather than three separate tables: a layout family replaces the
    design's layout, while mesh and infill families apply to the selected
    panel instead (spec 4.1; the applying part lands in Phase 3).

    The families themselves are seeded as XML records rather than created
    here, so presets can reference them by external id.
    """
    _name = 'aw.layout.family'
    _description = 'Fenestration Layout Family'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    kind = fields.Selection([
        ('layout', 'Layout'),
        ('mesh', 'Mesh'),
        ('infill', 'Infill'),
    ], required=True, default='layout',
        help="Layout families replace the whole design layout. Mesh and "
             "infill families apply to the selected panel instead.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    preset_ids = fields.One2many(
        'aw.layout.preset', 'family_id', string='Presets')
    preset_count = fields.Integer(compute='_compute_preset_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Family code must be unique.'),
    ]

    @api.depends('preset_ids')
    def _compute_preset_count(self):
        for rec in self:
            rec.preset_count = len(rec.preset_ids)

    @api.model
    def _migrate_preset_categories(self):
        """Point presets at a family, once, from their old text category.

        Fill-only-if-empty like every other seed here: a preset that
        already has a family is never re-pointed, so an upgrade can't
        undo a regrouping done in the UI. Unknown categories land in
        Other, which is what spec 4.1 asks for -- and is why Other is
        seeded even though 4.1's own table omits it.
        """
        by_code = {
            f.code: f for f in self.with_context(active_test=False).search([])
        }
        fallback = by_code.get('OTH')
        presets = self.env['aw.layout.preset'].with_context(
            active_test=False).search([('family_id', '=', False)])
        for preset in presets:
            family = by_code.get(
                CATEGORY_TO_FAMILY.get((preset.category or '').strip())
            ) or fallback
            if family:
                preset.family_id = family.id
