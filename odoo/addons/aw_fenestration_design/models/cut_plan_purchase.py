# -*- coding: utf-8 -*-
"""Create the purchase order for a Draft batch.

One draft order per profile vendor, one line per profile (thickness and finish
are part of the variant) and bar length: its number of bars, and a price per
ft that is the vendor's profile rate in force when the order is made. A
profile with no rate from that vendor is still on the order, priced 0 and
marked "No price"; leaving it out would buy a batch with a hole in it.

Bars taken from stock (from_bar_id) are not bought and are not on the order.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

MM_PER_FT = 304.8


class AwCutPlan(models.Model):
    _inherit = 'aw.cut.plan'

    purchase_order_id = fields.Many2one(
        'purchase.order', string='Purchase order', readonly=True,
        copy=False, ondelete='set null')
    po_total = fields.Monetary(
        string='Purchase order total', compute='_compute_po_total',
        currency_field='currency_id')
    po_vs_quote = fields.Monetary(
        string='Order vs quote cost', compute='_compute_po_total',
        currency_field='currency_id',
        help="The purchase order total less the cost the quote assumed for "
             "these bars. Positive: the order costs more than quoted.")

    def _compute_po_total(self):
        for plan in self:
            order = plan.purchase_order_id
            plan.po_total = order.amount_untaxed if order else 0.0
            plan.po_vs_quote = (
                plan.po_total - plan.cost_total) if order else 0.0

    def _purchase_lines(self):
        """[(variant, length_ft, bars, rate, rate_date)] for the bars to buy."""
        self.ensure_one()
        lines = []
        for group in self.group_ids:
            bought = group.bar_ids.filtered(lambda b: not b.from_bar_id)
            by_length = {}
            for bar in bought:
                key = round(bar.stock_mm / MM_PER_FT, 4)
                by_length[key] = by_length.get(key, 0) + 1
            for length in sorted(by_length):
                lines.append((group.product_id, length, by_length[length],
                              group.rate_per_ft, group.rate_date))
        return lines

    def action_create_purchase_order(self):
        self.ensure_one()
        self._ensure_draft()
        if self.purchase_order_id and self.purchase_order_id.state != 'cancel':
            raise UserError(_(
                "This batch already has purchase order %s. Cancel or delete "
                "it first to make another.", self.purchase_order_id.name))
        if not self.group_ids:
            raise UserError(_("Nothing is planned in this batch yet."))
        if not self.is_current:
            raise UserError(_(
                "This batch is out of date. Re-plan it before making the "
                "purchase order."))
        if self.oversize_note or self.blocked_note:
            raise UserError(_(
                "Some pieces are not on a bar, or a profile was not planned "
                "(see the notes on the batch). Fix that first."))
        vendor = self.profile_vendor_id or \
            self.sale_order_id.aw_profile_vendor_id
        if not vendor:
            raise UserError(_("This batch has no profile vendor."))
        wanted = self._purchase_lines()
        if not wanted:
            raise UserError(_(
                "Every bar of this batch comes from stock: nothing to buy."))

        foot = self.env.ref('uom.product_uom_foot')
        if not foot.active:
            foot.sudo().active = True
        company = self.env.company
        now = fields.Datetime.now()
        commands, no_price = [], []
        for product, length, bars, rate, rate_date in wanted:
            thickness, finish = self.env['purchase.order']\
                ._aw_variant_values(product)
            price = self.env['purchase.order.line']._aw_start_price(
                product.product_tmpl_id, thickness, finish, vendor,
                now.date(), company.currency_id)[0]
            if not price:
                price = rate if rate_date else 0.0
            if not price:
                no_price.append(product.display_name)
            commands.append((0, 0, {
                'product_id': product.id,
                'name': _("%(product)s: %(bars)s x %(ft)g ft bars",
                          product=product.display_name, bars=bars, ft=length),
                'aw_bar_length_ft': length,
                'aw_bar_count': bars,
                'product_qty': bars * length,
                'product_uom_id': foot.id,
                'price_unit': price,
                'technical_price_unit': price,
                'date_planned': now,
            }))
        # sudo keeps the user id: a Fenestration manager need not be a
        # purchase user, and the order is still created by them.
        order = self.env['purchase.order'].sudo().create({
                'partner_id': vendor.id,
                'currency_id': company.currency_id.id,
                'company_id': company.id,
                'origin': "%s / %s" % (self.sale_order_id.name, self.name),
                'order_line': commands,
            })
        order._aw_sort_bar_lines()
        self.write({'purchase_order_id': order.id})
        note = _("%(who)s made purchase order %(po)s for %(batch)s.",
                 who=self.env.user.name, po=order.name, batch=self.name)
        if no_price:
            note += " " + _(
                "No price from %(vendor)s for: %(products)s.",
                vendor=vendor.display_name, products=", ".join(no_price))
        self.sale_order_id.sudo().message_post(
            body=note, author_id=self.env.user.partner_id.id)
        return self.action_open_purchase_order()

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError(_("This batch has no purchase order yet."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
