# -*- coding: utf-8 -*-
"""The job's cut list: what is stale, and the two buttons.

The cut list is the bill of materials' profile lines. Generating and
recomputing are the same operation -- the explosion -- because it
already keeps every line edited by hand and never touches one added by
hand; "Generate" is just the first time.
"""
from odoo import api, fields, models


class AwDesign(models.Model):
    _inherit = 'aw.design'

    cut_line_ids = fields.One2many(
        'aw.design.bom.line', 'design_id', string='Cut List',
        domain=[('kind', '=', 'profile')])
    orphan_count = fields.Integer(
        compute='_compute_orphan_count',
        help="Manual cut lines whose piece no longer exists.")
    cut_list_stale = fields.Boolean(
        string='Cut List Out of Date', default=False, copy=False,
        help="The window's size changed after the cut list was made. "
             "Recompute brings it up to date; until then it still shows "
             "the old lengths.")

    @api.depends('cut_line_ids.is_orphan')
    def _compute_orphan_count(self):
        for design in self:
            design.orphan_count = len(
                design.cut_line_ids.filtered('is_orphan'))

    def write(self, vals):
        stale = self.env['aw.design']
        if 'width_mm' in vals or 'height_mm' in vals:
            stale = self.filtered('bom_line_ids')
        res = super().write(vals)
        if stale:
            stale.cut_list_stale = True
        return res

    def action_generate_cut_list(self):
        self.ensure_one()
        self._explode()
        return True

    def action_recompute_cut_list(self):
        self.ensure_one()
        self._explode()
        return True
