# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AwDesignLeaf(models.Model):
    """Direct port of the prototype's row.leaves[] entries. leaf_type is
    now a Many2one to aw.leaf.type (aw_fenestration_core) instead of a
    hardcoded Selection — single source of truth, same table Window
    Series and Hardware Set lines both reference. Adding a new leaf
    mechanism no longer touches this file at all.

    Legality (which leaf types a given row's design.window_series_id
    actually allows, via window_series_id.leaf_type_ids) is still NOT
    enforced at this layer — that's the checks/validation step, not
    part of this bare data model.
    """
    _name = 'aw.design.leaf'
    _description = 'Fenestration Design Leaf'
    _order = 'sequence, id'

    row_id = fields.Many2one('aw.design.row', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    length_uom = fields.Selection(related='row_id.length_uom', string='Length Unit')

    # Not required, same reason as aw.design.width_mm: a new leaf entered
    # in the ft/in pair would trip the NOT NULL constraint at INSERT,
    # before the inverse that fills this in gets to run.
    width_mm = fields.Float(string='Width (mm)', default=0.0)
    width_ft = fields.Integer(string='Width (ft)',
        compute='_compute_width_ftin', inverse='_inverse_width_ftin')
    width_in = fields.Float(string='Width (in)',
        compute='_compute_width_ftin', inverse='_inverse_width_ftin',
        help="Decimals allowed, e.g. 6.5.")
    width_inch_total = fields.Float(string='Width (in)',
        compute='_compute_width_inch_total', inverse='_inverse_width_inch_total')

    is_auto = fields.Boolean(
        string='Automatic',
        help="Same mechanism as aw.design.row.is_auto, one level down: "
             "exactly one leaf per row should absorb the remainder so "
             "the row's leaf widths always sum to the design's overall "
             "Width. Not enforced at this layer yet.")

    leaf_type_id = fields.Many2one(
        'aw.leaf.type', required=True, ondelete='restrict')
    # convenience related fields so the view can decide which direction
    # fields to show without re-deriving the leaf-type -> field-visibility
    # rule in XML — single source of truth stays on aw.leaf.type itself
    leaf_has_hinge_side = fields.Boolean(related='leaf_type_id.has_hinge_side', readonly=True)
    leaf_has_slide_dir = fields.Boolean(related='leaf_type_id.has_slide_dir', readonly=True)

    hinge_side = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
        ('top', 'Top'), ('bottom', 'Bottom'),
    ], help="Shown only for leaf types with has_hinge_side set.")
    swing = fields.Selection([
        ('in', 'In'), ('out', 'Out'),
    ], help="Shown only for leaf types with has_hinge_side set.")
    slide_dir = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
    ], help="Shown only for leaf types with has_slide_dir set.")

    @api.depends('width_mm')
    def _compute_width_ftin(self):
        for rec in self:
            total_in = rec.width_mm / 25.4
            ft = int(total_in // 12)
            rec.width_ft = ft
            rec.width_in = total_in - ft * 12

    def _inverse_width_ftin(self):
        for rec in self:
            rec.width_mm = rec.width_ft * 304.8 + rec.width_in * 25.4

    @api.depends('width_mm')
    def _compute_width_inch_total(self):
        for rec in self:
            rec.width_inch_total = rec.width_mm / 25.4

    def _inverse_width_inch_total(self):
        for rec in self:
            rec.width_mm = rec.width_inch_total * 25.4
