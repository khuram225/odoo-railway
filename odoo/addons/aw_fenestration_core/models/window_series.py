# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowSeries(models.Model):
    """A specific product family: Double Glaze Sliding, Single Glaze Fix,
    Curtain Wall Fix, Tilt & Turn Series, Casement Single Glaze, etc.

    Series is now the only classification layer -- the intermediate
    aw.window.type/aw.window.kind layers were dropped per the structure
    design consolidation. leaf_type_ids replaces that whole chain
    directly: which leaf mechanisms (Fixed, Slider, Casement, ...) this
    Series can host, a real Many2many to aw.leaf.type instead of an
    inherited-through-two-models Kind lookup.
    """
    _name = 'aw.window.series'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Series'
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True, help="Short code, e.g. BOX, COLLAR, ROUND, GSL, HINGED, CURTAIN")
    leaf_type_ids = fields.Many2many('aw.leaf.type', tracking=True,
        help="Which leaf mechanisms this Series can host.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')

    product_category_id = fields.Many2one(
        'product.category', string='Profile Product Category',
        help="Where this series's profile products live in the Inventory "
             "category tree, e.g. Fenestration / Profiles / Box Series.")

    profile_section_ids = fields.One2many(
        'aw.profile.section', 'window_type_id', string='Profile Sections')
    hardware_set_ids = fields.One2many(
        'aw.hardware.set', 'window_type_id', string='Hardware Sets')
    template_ids = fields.One2many(
        'aw.window.template', 'window_type_id', string='Templates')

    profile_section_count = fields.Integer(compute='_compute_counts')
    hardware_set_count = fields.Integer(compute='_compute_counts')
    template_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for rec in self:
            rec.profile_section_count = len(rec.profile_section_ids)
            rec.hardware_set_count = len(rec.hardware_set_ids)
            rec.template_count = len(rec.template_ids)

    def _view_related(self, model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [('window_type_id', '=', self.id)],
            'context': {'default_window_type_id': self.id},
        }

    def action_view_profile_sections(self):
        return self._view_related('aw.profile.section', 'Profile Sections')

    def action_view_hardware_sets(self):
        return self._view_related('aw.hardware.set', 'Hardware Sets')

    def action_view_templates(self):
        return self._view_related('aw.window.template', 'Templates')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Window Series code must be unique.'),
    ]
