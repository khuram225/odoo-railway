# -*- coding: utf-8 -*-
"""Current cost of a profile variant, with where it came from.

DISPLAY ONLY at this stage: nothing prices or values stock from it. The
rule is `cost_rule.decide()`: the newer of the vendor's list rate and the
last purchase price, the LPP on a tie, an LPP older than the maximum age
ignored, an exact LPP over a list rate found only by fallback. The cost
field of the variant (`standard_price`) is not touched.

The vendor is the series' default vendor, as for the variant's other rate
fields. Non-stored: it changes with the date and with every list and every
confirmed order.
"""
from odoo import api, fields, models

from .cost_rule import DEFAULT_MAX_AGE_DAYS, decide, money

MAX_AGE_PARAM = 'aw_fenestration.lpp_max_age_days'


class ProductProduct(models.Model):
    _inherit = 'product.product'

    aw_current_cost = fields.Float(
        string='Current cost / ft', compute='_compute_aw_current_cost',
        digits='Product Price',
        help="The newer of the default vendor's list rate and the last "
             "purchase price. For information: pricing and stock "
             "valuation do not use it yet.")
    aw_current_cost_source = fields.Char(
        string='Where it comes from', compute='_compute_aw_current_cost')

    @api.model
    def _aw_lpp_max_age_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            MAX_AGE_PARAM, '')
        try:
            return max(int(raw), 0) if str(raw).strip() else \
                DEFAULT_MAX_AGE_DAYS
        except ValueError:
            return DEFAULT_MAX_AGE_DAYS

    def _aw_cost_key(self):
        """(thickness, finish) of this variant as rates and last purchase
        prices are keyed. A profile sold in exactly one thickness, made
        without a thickness value, has that one."""
        self.ensure_one()
        thickness, finish = self._aw_attribute_values()
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness',
            raise_if_not_found=False)
        if not thickness and thickness_attr:
            offered = self.env['aw.profile.section.line']._template_values(
                self.product_tmpl_id, thickness_attr)
            if len(offered) == 1:
                thickness = offered
        return thickness, finish

    def _aw_current_cost(self, vendor=None, on_date=None):
        """cost_rule.decide() for this variant, at `vendor` (default: the
        series' default vendor) on `on_date` (default: today)."""
        self.ensure_one()
        template = self.product_tmpl_id
        vendor = vendor if vendor is not None else template._aw_default_vendor()
        on_date = on_date or fields.Date.context_today(self)
        thickness, finish = self._aw_cost_key()
        rate, level = self.env['aw.profile.rate']._rate_lookup(
            template, thickness, finish, on_date, vendor)
        lpp = self.env['aw.profile.lpp']._last(
            vendor, template, thickness, finish)
        return decide(
            rate.price if rate else 0.0,
            rate.date_from if rate else None, level,
            lpp.price_ft if lpp else 0.0, lpp.date if lpp else None,
            on_date, self._aw_lpp_max_age_days())

    @api.depends('product_template_variant_value_ids', 'product_tmpl_id')
    def _compute_aw_current_cost(self):
        for variant in self:
            if not variant.product_tmpl_id.aw_is_profile:
                variant.aw_current_cost = 0.0
                variant.aw_current_cost_source = False
                continue
            result = variant._aw_current_cost()
            variant.aw_current_cost = result['cost']
            variant.aw_current_cost_source = result['text']


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    aw_cost_range = fields.Char(
        string='Cost', compute='_compute_aw_cost_range',
        help="A product with several variants has no single cost: this is "
             "the range of its variants' costs.")

    @api.depends('product_variant_ids.standard_price')
    def _compute_aw_cost_range(self):
        for template in self:
            costs = [v.standard_price for v in template.product_variant_ids
                     if v.standard_price]
            if len(template.product_variant_ids) > 1 and costs:
                low, high = min(costs), max(costs)
                template.aw_cost_range = money(low) if low == high else \
                    'from %s to %s' % (money(low), money(high))
            else:
                template.aw_cost_range = False
