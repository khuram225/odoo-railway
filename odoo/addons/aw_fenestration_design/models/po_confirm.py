# -*- coding: utf-8 -*-
"""Confirming an order whose prices are far from the list.

A bars line priced more than 15% from the vendor's list rate stops the
confirm with a dialog that names the lines; "Confirm anyway" goes on and the
choice is written on the order's chatter. Nothing is blocked: a price agreed
on the phone is a normal reason to leave the list.
"""
from markupsafe import Markup, escape

from odoo import _, fields, models

THRESHOLD_PCT = 15.0


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _aw_lines_far_from_list(self):
        """[(line, list rate, % from list)] for the priced bars lines more
        than THRESHOLD_PCT from the vendor's list rate."""
        self.ensure_one()
        far = []
        for line in self._aw_print_bar_lines():
            rate = line._aw_vendor_rate()
            if line.price_unit > 0 and rate:
                pct = (line.price_unit - rate) / rate * 100.0
                if abs(pct) > THRESHOLD_PCT:
                    far.append((line, rate, pct))
        return far

    def button_confirm(self):
        if len(self) == 1 and self.state in ('draft', 'sent') \
                and not self.env.context.get('aw_confirm_anyway') \
                and self._aw_lines_far_from_list():
            wizard = self.env['aw.po.confirm.wizard'].create({
                'order_id': self.id})
            return {
                'type': 'ir.actions.act_window',
                'name': _("Prices far from the list"),
                'res_model': 'aw.po.confirm.wizard',
                'res_id': wizard.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'new',
            }
        return super().button_confirm()


class AwPoConfirmWizard(models.TransientModel):
    _name = 'aw.po.confirm.wizard'
    _description = 'Confirm a Purchase Order with Prices Far From the List'

    order_id = fields.Many2one(
        'purchase.order', required=True, ondelete='cascade')
    summary = fields.Html(compute='_compute_summary', sanitize=False)

    def _compute_summary(self):
        for wizard in self:
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td class="text-end">%.2f</td>'
                       '<td class="text-end">%.2f</td>'
                       '<td class="text-end">%+.1f%%</td></tr>') % (
                    escape(line.product_id.display_name), line.price_unit,
                    rate, pct)
                for line, rate, pct in wizard.order_id._aw_lines_far_from_list())
            wizard.summary = Markup(
                '<table class="table table-sm"><thead><tr><th>Line</th>'
                '<th class="text-end">Price / ft</th>'
                '<th class="text-end">List / ft</th>'
                '<th class="text-end">vs list today</th></tr></thead>'
                '<tbody>%s</tbody></table>') % rows

    def action_confirm(self):
        self.ensure_one()
        order = self.order_id
        far = order._aw_lines_far_from_list()
        order.with_context(aw_confirm_anyway=True).button_confirm()
        order.message_post(body=_(
            "%(who)s confirmed with %(count)s line(s) more than %(pct).0f%% "
            "from the list rate: %(lines)s.", who=self.env.user.name,
            count=len(far), pct=THRESHOLD_PCT, lines="; ".join(
                "%s %.2f vs list %.2f (%+.1f%%)" % (
                    line.product_id.display_name, line.price_unit, rate, pct)
                for line, rate, pct in far)))
        return {'type': 'ir.actions.act_window_close'}
