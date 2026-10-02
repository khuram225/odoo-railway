# -*- coding: utf-8 -*-
"""Print piece stickers starting part-way down a sheet.

A sheet of precut labels is rarely used up in one job, and throwing
away two thirds of a sheet because the last run needed ten stickers is
the kind of waste a shop notices. This asks which label to start on and
leaves the ones already peeled empty.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AwCutLabelStartWizard(models.TransientModel):
    _name = 'aw.cut.label.start.wizard'
    _description = 'Print Piece Stickers From Label N'

    plan_id = fields.Many2one(
        'aw.cut.plan', required=True, ondelete='cascade')
    start_at = fields.Integer(
        string='Start at label', default=1, required=True,
        help="Counting left to right, top to bottom. 1 is a fresh sheet.")
    per_sheet = fields.Integer(
        string='Labels per sheet', compute='_compute_per_sheet')
    sticker_count = fields.Integer(
        string='Stickers to print', compute='_compute_per_sheet')

    @api.depends('plan_id')
    def _compute_per_sheet(self):
        for wizard in self:
            layout = wizard.plan_id._label_layout()
            wizard.per_sheet = layout['across'] * layout['down']
            wizard.sticker_count = len(wizard.plan_id._sticker_rows())

    def action_print(self):
        self.ensure_one()
        if not 1 <= self.start_at <= self.per_sheet:
            raise UserError(_(
                "This sheet has %(total)s labels, so the start must be "
                "between 1 and %(total)s.", total=self.per_sheet))
        # Through `data`, which ir_actions_report._get_rendering_context
        # merges into the template's own namespace. The report model
        # supplies the default for the plain Print menu, which passes
        # nothing.
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cut_labels'
        ).report_action(self.plan_id, data={'start_at': self.start_at})
