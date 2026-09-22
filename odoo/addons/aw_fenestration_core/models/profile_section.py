# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

ROLE_SELECTION = [
    ('frame', 'Frame'),
    ('sash', 'Sash'),
    ('interlock', 'Interlock'),
    ('bead', 'Glazing Bead'),
    ('mesh', 'Mesh'),
]


class AwProfileSection(models.Model):
    """A named set of profile products covering every structural role for
    one Window Type — e.g. 'Box Series - Standard' = DC-30 BA (frame) +
    M-23 (sash) + M-28 (interlock) + D-29 (bead) + EM-29 (mesh).

    This is the Odoo-native equivalent of the prototype's
    SERIES.roles / ROLE_VARIANTS: instead of a hard-coded JS object, each
    role -> product mapping is a real, editable line, and a Window Type can
    have several sections (Standard / Heavy Duty / Economy) to choose from.
    """
    _name = 'aw.profile.section'
    _description = 'Fenestration Profile Section'
    _order = 'window_type_id, name'

    name = fields.Char(required=True)
    window_type_id = fields.Many2one(
        'aw.window.type', required=True, ondelete='restrict', index=True)
    active = fields.Boolean(default=True)
    notes = fields.Text()

    line_ids = fields.One2many(
        'aw.profile.section.line', 'section_id', string='Profile Lines')

    _sql_constraints = [
        ('name_type_uniq', 'unique(name, window_type_id)',
         'A profile section name must be unique per Window Type.'),
    ]


class AwProfileSectionLine(models.Model):
    _name = 'aw.profile.section.line'
    _description = 'Fenestration Profile Section Line'
    _order = 'sequence, id'

    section_id = fields.Many2one(
        'aw.profile.section', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    role = fields.Selection(ROLE_SELECTION, required=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )],
        help="The profile product filling this role. Thickness/Finish are "
             "expected to be product variant attributes on this product.")
    is_optional = fields.Boolean(
        default=False,
        help="If checked, a sales user may drop this role from a design "
             "(e.g. Interlock on a single-slider + fixed layout, or Mesh "
             "when no screen is wanted). Frame, Sash and Bead are normally "
             "structural and should stay unchecked.")

    _sql_constraints = [
        ('section_role_uniq', 'unique(section_id, role)',
         'Each role can only appear once per Profile Section.'),
    ]

    @api.constrains('role', 'is_optional')
    def _check_structural_roles(self):
        for line in self:
            if line.is_optional and line.role not in ('interlock', 'mesh'):
                raise ValidationError(
                    "Only Interlock and Mesh are normally optional — Frame, "
                    "Sash and Bead are structural to the leaf that owns "
                    "them. If this is a deliberate exception, remove "
                    "this constraint or extend it for your use case."
                )
