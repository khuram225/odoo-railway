# -*- coding: utf-8 -*-
"""Profile rates (spec 8, Phase 6a).

Append-only by design: a new price list adds rows with a later
`date_from`, and nothing is ever updated in place. That is what lets a
quote from March still cost at March's rates when someone reopens it in
June -- the lookup asks for the newest rate that was in force on the
quote's own order date, not for "the current price".
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AwProfileRate(models.Model):
    _name = 'aw.profile.rate'
    _description = 'Fenestration Profile Rate'
    _order = 'date_from desc, product_tmpl_id, id desc'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Profile', required=True,
        ondelete='cascade', index=True)
    # Nullable on purpose: some profiles have no thickness dimension at
    # all (the melt writes those with an empty thickness), and a rate
    # with no finish is the fallback for every finish.
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness', ondelete='restrict',
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_thickness').id,
        )])
    finish_id = fields.Many2one(
        'product.attribute.value', string='Finish', ondelete='restrict',
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_finish').id,
        )])

    price = fields.Float(
        string='Price / running ft', required=True,
        digits='Product Price',
        help="PKR per running foot, the vendor's own unit -- not a "
             "conversion. Stock lengths are 14/16/18 ft. Confirmed by "
             "the client; still to be had in writing from Chawla.")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    date_from = fields.Date(
        string='Effective From', required=True, index=True,
        default=fields.Date.context_today)
    vendor_id = fields.Many2one('res.partner', string='Vendor', index=True)
    source_note = fields.Char(
        help="Which file this row came from, so a price can always be "
             "traced back to the list it was quoted on.")
    active = fields.Boolean(default=True)

    @api.constrains('price')
    def _check_price(self):
        for rate in self:
            if rate.price < 0:
                raise ValidationError(_("A profile rate cannot be negative."))

    @api.model
    def _rate_for(self, product_tmpl, thickness, finish, on_date):
        """The rate in force on `on_date`, most specific match first.

        Falls back from (thickness + finish) to thickness-only to
        template-only, because a vendor list often prices a profile the
        same in every finish and the melt records that as one row with
        no finish. Returns an empty recordset when nothing matches, and
        the caller reports that -- never a silent zero, which would put
        a free window on a quote.
        """
        if not product_tmpl or not on_date:
            return self.browse()
        base = [
            ('product_tmpl_id', '=', product_tmpl.id),
            ('date_from', '<=', on_date),
        ]
        attempts = [
            base + [('thickness_id', '=', thickness.id if thickness else False),
                    ('finish_id', '=', finish.id if finish else False)],
            base + [('thickness_id', '=', thickness.id if thickness else False),
                    ('finish_id', '=', False)],
            base + [('finish_id', '=', False), ('thickness_id', '=', False)],
        ]
        for domain in attempts:
            rate = self.search(
                domain, order='date_from desc, id desc', limit=1)
            if rate:
                return rate
        return self.browse()
