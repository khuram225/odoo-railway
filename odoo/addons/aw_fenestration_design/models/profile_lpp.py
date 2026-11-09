# -*- coding: utf-8 -*-
"""Last purchase price (LPP): what a vendor was actually paid per ft.

One row per bars line of a confirmed purchase order whose price is above 0:
vendor, profile, thickness, finish, price per ft (the vendor's price before
tax and freight, discount taken off, in the company currency at the order
date), the bar length, the confirmation date and the line. History is kept;
"last" is the latest date, then the highest line id. It is not a rate-list
row and never enters the rate chain: the list rate and the LPP sit side by
side, and the person pricing decides which one a line starts from.

A cancelled order takes its rows with it, logged on the vendor's chatter, as
is a row a Rates manager deletes.
"""
from odoo import _, api, fields, models


class AwProfileLpp(models.Model):
    _name = 'aw.profile.lpp'
    _description = 'Last Purchase Price of a Profile'
    _order = 'date desc, id desc'

    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True,
        ondelete='cascade')
    product_tmpl_id = fields.Many2one(
        'product.template', string='Profile', required=True, index=True,
        ondelete='cascade')
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness', ondelete='restrict')
    finish_id = fields.Many2one(
        'product.attribute.value', string='Finish', ondelete='restrict')
    bar_length_ft = fields.Float(string='Bar length (ft)')
    price_ft = fields.Monetary(
        string='Price / ft', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    date = fields.Date(string='Confirmed on', required=True, index=True)
    po_line_id = fields.Many2one(
        'purchase.order.line', string='PO line', index=True,
        ondelete='cascade')
    order_id = fields.Many2one(
        'purchase.order', string='Purchase order', index=True,
        related='po_line_id.order_id', store=True)

    # shown in the list, never stored: both depend on today's date and on the
    # vendor's own finish names
    finish_label = fields.Char(
        string='Finish', compute='_compute_variant_view')
    list_rate = fields.Monetary(
        string='List today', compute='_compute_variant_view',
        currency_field='currency_id')
    vs_list_pct = fields.Float(
        string='vs list today %', compute='_compute_variant_view',
        digits=(16, 1))

    @api.depends('vendor_id', 'product_tmpl_id', 'thickness_id',
                 'finish_id', 'price_ft')
    def _compute_variant_view(self):
        today = fields.Date.context_today(self)
        orders = self.env['purchase.order']
        for row in self:
            row.finish_label = orders._aw_finish_label(
                row.finish_id, row.vendor_id) if row.finish_id else ''
            rate = self.env['aw.profile.rate'].sudo()._rate_for(
                row.product_tmpl_id, row.thickness_id, row.finish_id, today,
                row.vendor_id)
            row.list_rate = rate.price if rate else 0.0
            row.vs_list_pct = (
                (row.price_ft - row.list_rate) / row.list_rate * 100.0
                if row.list_rate else 0.0)

    @api.model
    def _last(self, vendor, template, thickness, finish):
        """The latest LPP for a vendor, profile, thickness and finish."""
        if not (vendor and template):
            return self.browse()
        rows = self.sudo().search([
            ('vendor_id', '=', vendor.id),
            ('product_tmpl_id', '=', template.id),
            ('thickness_id', '=', thickness.id or False),
            ('finish_id', '=', finish.id or False),
        ])
        return rows._latest_first()[:1]

    def _latest_first(self):
        """Latest date first, then the highest line id. Sorted here: a
        Many2one in `_order` sorts by the comodel's own order, not its id."""
        return self.sorted(
            key=lambda r: (r.date, r.po_line_id.id, r.id), reverse=True)

    # -- who changed what, on the vendor's chatter -------------------------
    def _log_removed(self, why):
        for vendor in self.vendor_id:
            rows = self.filtered(lambda r: r.vendor_id == vendor)
            vendor.sudo().message_post(
                body=_("Last purchase price removed (%(why)s) by %(who)s on "
                       "%(when)s: %(what)s.", why=why, who=self.env.user.name,
                       when=fields.Datetime.now(), what="; ".join(
                           "%s %.2f/ft (%s)" % (
                               r.product_tmpl_id.name, r.price_ft,
                               r.sudo().order_id.name or '') for r in rows)),
                author_id=self.env.user.partner_id.id,
                subtype_xmlid='mail.mt_note')

    def unlink(self):
        if not self.env.context.get('aw_lpp_logged'):
            self._log_removed(_("deleted"))
        return super().unlink()


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _aw_record_lpp(self):
        """Write the LPP rows of a confirmed order (idempotent per line)."""
        Lpp = self.env['aw.profile.lpp'].sudo()
        foot = self.env['purchase.order.line']._aw_foot()
        for order in self.filtered(lambda o: o.state == 'purchase'):
            company = order.company_id
            on_date = (order.date_order or fields.Datetime.now()).date()
            date = (order.date_approve or fields.Datetime.now()).date()
            for line in order._aw_print_bar_lines():
                if line.price_unit <= 0:
                    continue
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                if line.product_uom_id and line.product_uom_id != foot:
                    price = line.product_uom_id._compute_price(price, foot)
                price = order.currency_id._convert(
                    price, company.currency_id, company, on_date,
                    round=False)
                thickness, finish = order._aw_variant_values(line.product_id)
                vals = {
                    'vendor_id': order.partner_id.id,
                    'product_tmpl_id': line.product_id.product_tmpl_id.id,
                    'thickness_id': thickness.id or False,
                    'finish_id': finish.id or False,
                    'bar_length_ft': line.aw_bar_length_ft,
                    'price_ft': price, 'currency_id': company.currency_id.id,
                    'date': date, 'po_line_id': line.id}
                row = Lpp.search([('po_line_id', '=', line.id)], limit=1)
                if row:
                    row.write(vals)
                else:
                    Lpp.create(vals)

    def button_approve(self, force=False):
        result = super().button_approve(force=force)
        self._aw_record_lpp()
        return result

    def button_cancel(self):
        result = super().button_cancel()
        rows = self.env['aw.profile.lpp'].sudo().search([
            ('order_id', 'in', self.ids)])
        if rows:
            rows._log_removed(_("order cancelled"))
            rows.with_context(aw_lpp_logged=True).unlink()
        return result
