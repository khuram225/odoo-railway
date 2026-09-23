# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )],
        help="The profile filling this position. Pick a Thickness and "
             "Finish below to resolve (or create) the exact variant.")
    thickness_attribute_value_ids = fields.Many2many(
        'product.attribute.value', compute='_compute_available_attribute_values')
    finish_attribute_value_ids = fields.Many2many(
        'product.attribute.value', compute='_compute_available_attribute_values')
    thickness_id = fields.Many2one(
        'product.attribute.value', required=True,
        domain="[('id', 'in', thickness_attribute_value_ids)]")
    finish_id = fields.Many2one(
        'product.attribute.value', required=True,
        domain="[('id', 'in', finish_attribute_value_ids)]")

    product_id = fields.Many2one(
        'product.product', compute='_compute_product_id', store=True,
        readonly=True,
        help="Resolved automatically from Profile + Thickness + Finish "
             "above: found if that exact variant already exists, created "
             "if not. Thickness/Finish are Dynamic-creation attributes on "
             "these products, so no variant exists until a combination is "
             "actually requested -- this is the general version of what "
             "the old post_init_hook did by hand for 5 hardcoded cases.")

    is_optional = fields.Boolean(
        default=False,
        help="If checked, a sales user may drop this position from a "
             "design (e.g. an interlock on a single-slider + fixed "
             "layout, or mesh when no screen is wanted).")

    _sql_constraints = [
        ('section_position_uniq', 'unique(section_id, position_id)',
         'Each position can only appear once per Profile Section.'),
    ]

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        # thickness_id/finish_id's domain only restricts NEW picks -- it
        # doesn't retroactively clear an already-set value that no longer
        # belongs to the newly chosen template's own attribute lines.
        # Left stale, _compute_product_id would silently resolve to no
        # product instead of erroring, since the combination would be
        # incomplete.
        self.thickness_id = False
        self.finish_id = False

    @api.depends('product_tmpl_id')
    def _compute_available_attribute_values(self):
        thickness_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        for line in self:
            thickness_vals = self.env['product.attribute.value']
            finish_vals = self.env['product.attribute.value']
            for attr_line in line.product_tmpl_id.attribute_line_ids:
                if attr_line.attribute_id == thickness_attr:
                    thickness_vals |= attr_line.value_ids
                elif attr_line.attribute_id == finish_attr:
                    finish_vals |= attr_line.value_ids
            line.thickness_attribute_value_ids = thickness_vals
            line.finish_attribute_value_ids = finish_vals

    @api.depends('product_tmpl_id', 'thickness_id', 'finish_id')
    def _compute_product_id(self):
        for line in self:
            if not (line.product_tmpl_id and line.thickness_id and line.finish_id):
                line.product_id = False
                continue
            combination = self.env['product.template.attribute.value']
            for attribute_value in (line.thickness_id, line.finish_id):
                combination |= line.product_tmpl_id.attribute_line_ids.product_template_value_ids.filtered(
                    lambda v, attribute_value=attribute_value: v.product_attribute_value_id == attribute_value
                )
            line.product_id = line.product_tmpl_id._create_product_variant(combination)
