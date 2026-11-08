# -*- coding: utf-8 -*-
"""What the RFQ / purchase order prints for a profile order.

The numbers are worked out here, in one place, and the template only lays
them out (report/report_purchase_order.xml): a matrix of profile, finish and
thickness by bar length, a summary by profile and by length, and the order's
own totals. Nothing is recalculated in the template, so the printed amounts
are the lines' amounts and cannot drift from the order's totals.
"""
from odoo import api, fields, models

PRICES_PARAM = 'aw_fenestration.po_show_prices_backfilled'


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    aw_show_prices = fields.Boolean(
        string='Show prices', compute='_compute_aw_show_prices',
        store=True, readonly=False,
        help="Prices on the printout. On for a purchase order, off for a "
             "request for quotation; tick it to override until the state "
             "changes.")

    @api.depends('state')
    def _compute_aw_show_prices(self):
        for order in self:
            order.aw_show_prices = order.state in ('purchase', 'done')

    def _aw_print_bar_lines(self):
        return self.order_line.filtered(
            lambda l: not l.display_type and l.aw_bar_count
            and l.aw_bar_length_ft and l.product_qty)

    def _aw_print_other_lines(self):
        """The lines the standard table still prints: everything but the
        bars lines the matrix takes over."""
        self.ensure_one()
        bars = self._aw_print_bar_lines()
        return self.order_line.filtered(
            lambda l: (l.display_type or l.product_qty != 0)
            and l not in bars)

    def aw_print_data(self):
        """The matrix and the summaries, as plain numbers."""
        self.ensure_one()
        lines = self._aw_print_bar_lines().sorted(self._aw_bar_line_key)
        lengths = sorted(set(lines.mapped('aw_bar_length_ft')))
        rows, by_key = [], {}
        for line in lines:
            thickness, finish = self._aw_variant_values(line.product_id)
            key = (line.product_id.product_tmpl_id.id, finish.id,
                   thickness.id)
            row = by_key.get(key)
            if row is None:
                row = by_key[key] = {
                    'code': line.product_id.product_tmpl_id.name,
                    'finish': self._aw_finish_label(finish, self.partner_id),
                    'thickness': thickness.name or '',
                    'cells': {}, 'bars': 0, 'feet': 0.0, 'amount': 0.0}
                rows.append(row)
            row['cells'][line.aw_bar_length_ft] = \
                row['cells'].get(line.aw_bar_length_ft, 0) + line.aw_bar_count
            row['bars'] += line.aw_bar_count
            row['feet'] += line.product_qty
            row['amount'] += line.price_subtotal
        for row in rows:
            row['rate'] = row['amount'] / row['feet'] if row['feet'] else 0.0
        bars_amount = sum(r['amount'] for r in rows)
        bars_feet = sum(r['feet'] for r in rows)

        profiles, by_code = [], {}
        for row in rows:
            item = by_code.get(row['code'])
            if item is None:
                item = by_code[row['code']] = {
                    'code': row['code'], 'bars': 0, 'feet': 0.0,
                    'amount': 0.0}
                profiles.append(item)
            item['bars'] += row['bars']
            item['feet'] += row['feet']
            item['amount'] += row['amount']
        for item in profiles:
            whole = bars_amount if bars_amount else bars_feet
            part = item['amount'] if bars_amount else item['feet']
            item['share'] = part / whole * 100.0 if whole else 0.0

        by_length = [{
            'length': length,
            'bars': sum(r['cells'].get(length, 0) for r in rows),
            'feet': sum(r['cells'].get(length, 0) * length for r in rows),
        } for length in lengths]
        other_amount = sum(self._aw_print_other_lines().mapped(
            'price_subtotal'))
        return {
            'lengths': lengths, 'rows': rows, 'profiles': profiles,
            'by_length': by_length,
            'bars': sum(r['bars'] for r in rows), 'feet': bars_feet,
            'bars_amount': bars_amount, 'other_amount': other_amount,
            'subtotal': bars_amount + other_amount,
            'tax': self.amount_tax, 'total': self.amount_total,
        }

    @api.model
    def _aw_backfill_show_prices(self):
        """Orders confirmed before the tick existed print their prices."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PRICES_PARAM):
            return 0
        orders = self.with_context(active_test=False).search([
            ('state', 'in', ('purchase', 'done')),
            ('aw_show_prices', '=', False)])
        orders.write({'aw_show_prices': True})
        param.set_param(PRICES_PARAM, '1')
        return len(orders)
