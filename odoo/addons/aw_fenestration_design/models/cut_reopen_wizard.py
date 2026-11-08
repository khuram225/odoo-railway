# -*- coding: utf-8 -*-
"""Reopen a Final batch: back to Draft, with a reason, for managers only."""
from odoo import _, fields, models
from odoo.exceptions import UserError

MANAGER = 'aw_fenestration_core.group_fenestration_manager'


class AwCutReopenWizard(models.TransientModel):
    _name = 'aw.cut.reopen.wizard'
    _description = 'Reopen a Final Cutting Batch'

    plan_id = fields.Many2one(
        'aw.cut.plan', string='Batch', required=True, ondelete='cascade')
    reason = fields.Text(required=True)

    def action_reopen(self):
        self.ensure_one()
        if not self.env.user.has_group(MANAGER):
            raise UserError(_("Only a Fenestration manager can reopen a batch."))
        plan = self.plan_id
        if plan.state != 'confirmed':
            raise UserError(_("Only a Final batch can be reopened."))
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("Say why the batch is reopened."))
        bought = _("bought %(when)s by %(who)s") % {
            'when': plan.bought_on or '', 'who': plan.bought_by.name or ''}
        plan.write({'state': 'draft', 'bought_on': False, 'bought_by': False})
        plan.sale_order_id.message_post(body=_(
            "%(who)s reopened %(batch)s on %(date)s (it was %(bought)s). "
            "Reason: %(reason)s",
            who=self.env.user.name, batch=plan.name,
            date=fields.Datetime.now(), bought=bought, reason=reason))
        return plan.action_open()
