# -*- coding: utf-8 -*-
"""Glazing family (spec 9, Phase 7a).

The layer above the profile system. A quote starts by choosing
"Double Glaze", not "Double Glaze - Openable": which SYSTEM is needed
follows from the panels drawn, and the estimator should not have to
work it out before they have drawn anything.

`aw.window.series` keeps its model name -- renaming it would break
every stored reference, every view and the whole BOM chain for a label
-- but is presented as "Profile system" throughout the UI.
"""
from odoo import api, fields, models

# code -> (name, glazing, sequence)
SEEDED_FAMILIES = (
    ('DG', 'Double Glaze', 'double', 10),
    ('SG', 'Single Glaze', 'single', 20),
    ('CW', 'Curtain Wall', 'none', 30),
)


class AwWindowFamily(models.Model):
    _name = 'aw.window.family'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Glazing Family'
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True,
                       help="Short code, e.g. DG, SG, CW.")
    glazing = fields.Selection([
        ('single', 'Single glazed'),
        ('double', 'Double glazed'),
        ('none', 'Not glazing-specific'),
    ], required=True, default='single', tracking=True,
        help="Which glass specs this family can use. 'Not "
             "glazing-specific' accepts any, which is what Curtain Wall "
             "needs.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    series_ids = fields.One2many(
        'aw.window.series', 'family_id', string='Profile Systems')
    series_count = fields.Integer(compute='_compute_series_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Family code must be unique.'),
    ]

    @api.depends('series_ids')
    def _compute_series_count(self):
        for family in self:
            family.series_count = len(family.series_ids)

    def _glass_domain(self):
        """Which glass specs this family may use.

        A family with no glazing preference takes anything, which is
        the point of 'none' -- curtain wall is glazed to whatever the
        job needs.
        """
        self.ensure_one()
        if not self.glazing or self.glazing == 'none':
            return []
        return [('glazing', 'in', (self.glazing, False))]

    @api.model
    def _seed_families(self):
        """Fill-only-if-empty, by code, once per database."""
        created = 0
        for code, name, glazing, sequence in SEEDED_FAMILIES:
            if self.with_context(active_test=False).search_count(
                    [('code', '=', code)]):
                continue
            self.create({'code': code, 'name': name,
                         'glazing': glazing, 'sequence': sequence})
            created += 1
        return created
