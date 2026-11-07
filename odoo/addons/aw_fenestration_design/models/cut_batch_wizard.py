# -*- coding: utf-8 -*-
"""New batch: tick the windows that go into one cutting batch.

A batch is a cutting plan (on screen "Batch 1", "Batch 2"). A window is in
one active batch only, so the dialog lists the windows of the quote that are
not in one yet, all ticked; untick the ones that wait for a later batch.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class AwCutBatchWizard(models.TransientModel):
    _name = 'aw.cut.batch.wizard'
    _description = 'New Cutting Batch'

    order_id = fields.Many2one(
        'sale.order', required=True, ondelete='cascade')
    line_ids = fields.One2many(
        'aw.cut.batch.wizard.line', 'wizard_id', string='Windows')

    def action_create(self):
        self.ensure_one()
        chosen = self.line_ids.filtered('selected').design_id
        if not chosen:
            raise UserError(_("Tick at least one window for this batch."))
        blocking = chosen.filtered(lambda d: d.check_error_count)
        if blocking:
            raise UserError(_(
                "Fix these windows before planning the cuts:\n%s",
                '\n'.join('- %s' % design.display_name
                          for design in blocking)))
        plan = self.env['aw.cut.plan'].create({
            'sale_order_id': self.order_id.id,
            'design_ids': [(6, 0, chosen.ids)],
        })
        plan._generate()
        return plan.action_open()


class AwCutBatchWizardLine(models.TransientModel):
    _name = 'aw.cut.batch.wizard.line'
    _description = 'New Cutting Batch: a window'

    wizard_id = fields.Many2one(
        'aw.cut.batch.wizard', required=True, ondelete='cascade')
    design_id = fields.Many2one('aw.design', required=True, readonly=True)
    selected = fields.Boolean(string='In this batch', default=True)
    location = fields.Char(related='design_id.location')
    size_display = fields.Char(related='design_id.size_display')
