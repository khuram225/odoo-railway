# -*- coding: utf-8 -*-
"""The last purchase price beside the list rate on a profile's Rates tab.

The tab is core's (aw_fenestration_core cannot see a purchase price), so the
design module adds a `lpp` list to the payload and the widget shows it under
the cell it belongs to: price, date, purchase order and the difference "vs
list today".
"""
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # The Purchase tab lists these. A One2many has no column of its own, and
    # nothing is written to product.supplierinfo (Odoo's vendor list).
    aw_lpp_ids = fields.One2many(
        'aw.profile.lpp', 'product_tmpl_id', string='Last purchase prices',
        readonly=True)

    def _aw_rates_table_data(self):
        data = super()._aw_rates_table_data()
        if self.aw_is_glass_sheet or 'cells' not in data:
            return data
        listed = {(c['t'], c['f'], c['v']): c['price']
                  for c in data['cells']}
        seen, rows = set(), []
        for row in self.env['aw.profile.lpp'].sudo().search(
                [('product_tmpl_id', '=', self.id)])._latest_first():
            key = (row.thickness_id.id, row.finish_id.id, row.vendor_id.id)
            if key in seen:
                continue
            seen.add(key)
            rate = listed.get(key)
            rows.append({
                't': key[0], 'f': key[1], 'v': key[2],
                'price': row.price_ft, 'date': str(row.date),
                'po': row.order_id.name or '',
                'length': row.bar_length_ft,
                'pct': (row.price_ft - rate) / rate * 100.0 if rate else None,
            })
        data['lpp'] = rows
        return data
