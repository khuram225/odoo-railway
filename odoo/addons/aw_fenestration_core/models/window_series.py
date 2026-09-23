# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowSeries(models.Model):
    """A specific product family within a Window Type: Box Series, Collar
    Box Series, Round Series, GSL Slim, Hinged/Casement, Curtain Wall, etc.
    This was the original 'aw.window.type' model -- renamed when a real
    Type layer was inserted above it (aw.window.type is now the broader
    category, e.g. 'Sliding Window', that several Series belong to).

    kind_id is no longer set directly here -- it's derived from
    window_type_id.kind_id, since the leaf-type rule genuinely belongs to
    the Type, not the Series.
    """
    _name = 'aw.window.series'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Series'
    _order = 'window_type_id, sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True, help="Short code, e.g. BOX, COLLAR, ROUND, GSL, HINGED, CURTAIN")
    window_type_id = fields.Many2one('aw.window.type', required=True,
        ondelete='restrict', tracking=True,
        help="The broader category this Series belongs to, e.g. Sliding "
             "Window, Curtain Wall Fix Window, Door.")
    kind_id = fields.Many2one(related='window_type_id.kind_id', store=True,
        string='Kind',
        help="Which leaf types this system can host -- inherited from "
             "the Window Type above, not set directly here.")
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
