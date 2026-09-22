# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowType(models.Model):
    """A fenestration system family: Box Series, Collar Box Series, Round Series,
    GSL Slim, Hinged/Casement, Curtain Wall, etc.

    'kind' governs which leaf types (fixed/slider/casement/awning/hopper/mesh)
    are legal on a design built against this type — sliding systems can't host
    a casement leaf and vice versa. This mirrors SERIES.kind from the
    prototype 1:1.
    """
    _name = 'aw.window.type'
    _description = 'Fenestration Window Type (System)'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(help="Short code, e.g. BOX, COLLAR, ROUND, GSL, HINGED, CURTAIN")
    kind = fields.Selection([
        ('sliding', 'Sliding'),
        ('hinged', 'Hinged / Casement'),
        ('fixed', 'Fixed only'),
    ], required=True, default='sliding',
       help="Which leaf types this system can host. Sliding systems take "
            "Fixed/Slider/Mesh leaves; Hinged systems take Fixed/Casement/"
            "Awning/Hopper/Mesh leaves.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')

    product_category_id = fields.Many2one(
        'product.category', string='Profile Product Category',
        help="Where this type's profile products live in the Inventory "
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
        ('code_uniq', 'unique(code)', 'Window Type code must be unique.'),
    ]
