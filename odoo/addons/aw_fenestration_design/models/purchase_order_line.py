# -*- coding: utf-8 -*-
"""A profile bought as bars: a bar length and a number of bars.

The quantity of the line stays what Odoo reads everywhere (receipts, billing),
in ft, and is bars x length. The price is pinned: the standard price rule
re-prices a line whenever its quantity changes, and a price taken from the
vendor's profile rate on the day the order was made must not move because
somebody changed the number of bars.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    aw_bar_length_ft = fields.Float(string='Bar length (ft)', copy=False)
    aw_bar_count = fields.Integer(string='Bars', copy=False)
    aw_is_bars = fields.Boolean(compute='_compute_aw_bars')
    aw_price_note = fields.Char(string='Price note', compute='_compute_aw_bars')

    @api.depends('aw_bar_count', 'aw_bar_length_ft', 'price_unit')
    def _compute_aw_bars(self):
        for line in self:
            line.aw_is_bars = bool(
                line.aw_bar_count and line.aw_bar_length_ft)
            line.aw_price_note = _("No price") if (
                line.aw_is_bars and not line.price_unit) else False

    @api.model
    def _aw_bar_qty(self, count, length):
        return float(count or 0) * float(length or 0.0)

    @api.onchange('aw_bar_count', 'aw_bar_length_ft')
    def _onchange_aw_bars(self):
        for line in self:
            if line.aw_bar_count and line.aw_bar_length_ft:
                line.product_qty = line._aw_bar_qty(
                    line.aw_bar_count, line.aw_bar_length_ft)

    @api.constrains('aw_bar_count', 'aw_bar_length_ft', 'product_qty')
    def _check_aw_bars(self):
        for line in self:
            if not (line.aw_bar_count or line.aw_bar_length_ft):
                continue
            if line.aw_bar_count < 1 or line.aw_bar_length_ft <= 0:
                raise ValidationError(_(
                    "A bars line needs both a bar length and a number of "
                    "bars."))
            want = line._aw_bar_qty(line.aw_bar_count, line.aw_bar_length_ft)
            if line.product_uom_id == self.env.ref(
                    'uom.product_uom_foot') \
                    and abs(line.product_qty - want) > 1e-6:
                raise ValidationError(_(
                    "%(product)s: %(bars)s bars of %(ft)g ft is %(want)g ft, "
                    "not %(qty)g ft.", product=line.product_id.display_name,
                    bars=line.aw_bar_count, ft=line.aw_bar_length_ft,
                    want=want, qty=line.product_qty))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('aw_bar_count') and vals.get('aw_bar_length_ft'):
                vals['product_qty'] = self._aw_bar_qty(
                    vals['aw_bar_count'], vals['aw_bar_length_ft'])
        return super().create(vals_list)

    def write(self, vals):
        if 'aw_bar_count' in vals or 'aw_bar_length_ft' in vals:
            for line in self:
                one = dict(vals)
                count = one.get('aw_bar_count', line.aw_bar_count)
                length = one.get('aw_bar_length_ft', line.aw_bar_length_ft)
                if count and length:
                    one['product_qty'] = self._aw_bar_qty(count, length)
                super(PurchaseOrderLine, line).write(one)
            return True
        return super().write(vals)

    def _compute_price_unit_and_date_planned_and_name(self):
        """A bars line keeps the price it was made with."""
        bars = self.filtered('aw_is_bars')
        return super(PurchaseOrderLine, self - bars)\
            ._compute_price_unit_and_date_planned_and_name()

    @api.depends('product_id', 'product_id.uom_id', 'product_id.uom_ids',
                 'product_id.seller_ids', 'product_id.seller_ids.product_uom_id',
                 'aw_bar_count')
    def _compute_allowed_uom_ids(self):
        super()._compute_allowed_uom_ids()
        foot = self.env.ref('uom.product_uom_foot', raise_if_not_found=False)
        if foot:
            for line in self.filtered('aw_bar_count'):
                line.allowed_uom_ids |= foot
