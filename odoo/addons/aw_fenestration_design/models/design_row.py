# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AwDesignRow(models.Model):
    """Direct port of the prototype's d.rows[] — a horizontal band with
    its own height, containing one or more leaves side by side. Multiple
    rows are what let a design represent stacked layouts (hopper over
    fixed, a 3-tier curtain wall column) that a flat single-row model
    couldn't — this was the real finding from the 169 M1 drawing set.

    The prototype's "Automatic" dimension-lock mechanism (exactly one
    row's height absorbs the remainder so W/H edits can't silently
    desync the geometry, borrowed from how Logikal actually does it) is
    NOT implemented at the model level here — is_auto below is just the
    flag; the actual recompute-on-edit logic belongs in the form view /
    a controller method once the UI for this is built, not in this bare
    data layer.
    """
    _name = 'aw.design.row'
    _description = 'Fenestration Design Row'
    _order = 'sequence, id'

    design_id = fields.Many2one('aw.design', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    height_mm = fields.Float(string='Height (mm)', required=True)
    is_auto = fields.Boolean(
        string='Automatic',
        help="If checked, this row's height is the one that absorbs "
             "whatever the other rows don't use, keeping the total equal "
             "to the design's overall Height. Exactly one row should be "
             "marked Automatic at a time — not enforced at this layer "
             "yet, needs a constraint or UI-level guard once built.")

    leaf_ids = fields.One2many('aw.design.leaf', 'row_id', string='Leaves')
    leaf_count = fields.Integer(compute='_compute_leaf_count')

    @api.depends('leaf_ids')
    def _compute_leaf_count(self):
        for rec in self:
            rec.leaf_count = len(rec.leaf_ids)
