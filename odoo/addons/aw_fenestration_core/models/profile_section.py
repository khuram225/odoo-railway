# -*- coding: utf-8 -*-
from odoo import fields, models


class AwProfileSection(models.Model):
    """A named set of profile products covering every position needed for
    one Window Series -- e.g. frame/sash/mesh/bead pieces, each tagged
    with where in the frame it sits (aw.profile.position).

    This is the Odoo-native equivalent of the prototype's
    SERIES.roles / ROLE_VARIANTS: instead of a hard-coded JS object, each
    position -> product mapping is a real, editable line, and a Series can
    have several sections (Standard / Heavy Duty / Economy) to choose from.
    aw.profile.position is open-ended (add a row, no schema change) --
    replaces the earlier fixed 5-value role Selection, which couldn't
    express e.g. a different drainage profile on the sill vs. head/jambs.
    """
    _name = 'aw.profile.section'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Profile Section'
    _order = 'window_type_id, name'

    name = fields.Char(required=True, tracking=True)
    window_type_id = fields.Many2one(
        'aw.window.series', required=True, ondelete='restrict', index=True,
        tracking=True)
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
    position_id = fields.Many2one('aw.profile.position', required=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )],
        help="The profile product filling this position. Thickness/Finish "
             "are expected to be product variant attributes on this "
             "product.")
    is_optional = fields.Boolean(
        default=False,
        help="If checked, a sales user may drop this position from a "
             "design (e.g. an interlock on a single-slider + fixed "
             "layout, or mesh when no screen is wanted).")

    _sql_constraints = [
        ('section_position_uniq', 'unique(section_id, position_id)',
         'Each position can only appear once per Profile Section.'),
    ]
