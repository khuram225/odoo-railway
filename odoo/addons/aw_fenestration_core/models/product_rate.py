# -*- coding: utf-8 -*-
"""What a profile variant costs per foot, and the cost field it feeds.

The rate lives on `aw.profile.rate` and is looked up per
template + thickness + finish. A variant IS that combination, so it can
show its own rate without anyone joining the two by hand.

Computed and NOT stored on purpose: the rate in force changes with the
date and with every price-list import, and a stored copy would be
quietly wrong the morning after. `standard_price` is the stored one,
and it is only ever written deliberately -- by the import, by the
button, or when a variant is first created.
"""
from odoo import _, api, fields, models
from odoo.tools import float_compare

# Stock UoM for profiles is the metre; rates are quoted per running
# foot. Exact by definition: 1 m = 1 / 0.3048 ft.
FEET_PER_METRE = 3.280839895013123


class ProductProduct(models.Model):
    _inherit = 'product.product'

    aw_rate_per_ft = fields.Float(
        string='Rate / ft', compute='_compute_aw_rate',
        digits='Product Price',
        help="The profile rate in force today for this exact "
             "thickness and finish. Zero means no rate covers it.")
    aw_rate_date = fields.Date(
        string='Rate Of', compute='_compute_aw_rate',
        help="Effective date of the rate above, so an unexpected cost "
             "can be traced to the list it came from.")
    aw_has_rate = fields.Boolean(compute='_compute_aw_rate')
    aw_thickness_name = fields.Char(
        string='Thickness', compute='_compute_aw_attribute_names')
    aw_finish_name = fields.Char(
        string='Finish', compute='_compute_aw_attribute_names')

    @api.depends('product_template_variant_value_ids')
    def _compute_aw_attribute_names(self):
        for variant in self:
            thickness = finish = ''
            for value in variant.product_template_variant_value_ids:
                if value.attribute_id.name == 'Thickness':
                    thickness = value.name
                elif value.attribute_id.name == 'Finish':
                    finish = value.name
            variant.aw_thickness_name = thickness
            variant.aw_finish_name = finish

    def _aw_attribute_values(self):
        """The plain attribute values behind this variant's combination.

        `product.template.attribute.value` is the template-scoped
        wrapper; `aw.profile.rate` stores the plain
        `product.attribute.value`, so the mapping has to be made here
        rather than comparing the two directly.
        """
        self.ensure_one()
        empty = self.env['product.attribute.value']
        thickness = finish = empty
        for value in self.product_template_variant_value_ids:
            name = value.attribute_id.name
            if name == 'Thickness':
                thickness = value.product_attribute_value_id
            elif name == 'Finish':
                finish = value.product_attribute_value_id
        return thickness, finish

    @api.depends('product_template_variant_value_ids', 'product_tmpl_id')
    def _compute_aw_rate(self):
        today = fields.Date.context_today(self)
        rates = self.env['aw.profile.rate']
        for variant in self:
            thickness, finish = variant._aw_attribute_values()
            rate = rates._rate_for(
                variant.product_tmpl_id, thickness, finish, today)
            variant.aw_rate_per_ft = rate.price if rate else 0.0
            variant.aw_rate_date = rate.date_from if rate else False
            variant.aw_has_rate = bool(rate)
            variant.aw_cost_from_rate = (
                rate.price * FEET_PER_METRE) if rate else 0.0

    # ------------------------------------------------------------------
    aw_cost_from_rate = fields.Float(
        string='Cost / m from rate', compute='_compute_aw_rate',
        digits='Product Price',
        help="What the cost would be if written from the current rate. "
             "Shown even when the costing method forbids writing it.")
    aw_cost_sync_allowed = fields.Boolean(
        compute='_compute_aw_cost_sync_allowed')
    aw_cost_method = fields.Char(
        string='Costing Method', compute='_compute_aw_cost_sync_allowed')

    # NOT @api.depends('cost_method'): that field belongs to
    # stock_account, which this module does not depend on, and naming a
    # field that may not exist breaks the registry at load. See
    # _aw_cost_method().
    @api.depends('product_tmpl_id')
    def _compute_aw_cost_sync_allowed(self):
        """Only Standard Price costing owns standard_price.

        Under AVCO the field IS the running average that stock
        valuation maintains, and under FIFO it is a leftover that
        valuation ignores. Writing either from a supplier rate does not
        just put a wrong number on screen -- `_change_standard_price()`
        turns a change under AVCO into an inventory revaluation, so the
        stock ledger would move because a price list was imported.
        """
        for variant in self:
            method = variant.product_tmpl_id._aw_cost_method()
            variant.aw_cost_method = method
            variant.aw_cost_sync_allowed = method == 'standard'

    def _aw_sync_cost_from_rate(self):
        """Write standard_price from the rate, per metre.

        Returns (updated, blocked). Two things are deliberately never
        written:

        - a variant with NO rate is left alone rather than zeroed: a
          hand-entered cost is worth more than a zero this module is
          confident about;
        - a variant whose product is costed AVCO or FIFO is left alone
          whatever its rate, because there standard_price belongs to
          stock valuation.
        """
        updated = blocked = self.env['product.product']
        for variant in self:
            if not variant.aw_has_rate:
                continue
            if not variant.aw_cost_sync_allowed:
                blocked |= variant
                continue
            cost = variant.aw_rate_per_ft * FEET_PER_METRE
            if float_compare(variant.standard_price, cost,
                             precision_digits=4) != 0:
                variant.standard_price = cost
                updated |= variant
        return updated, blocked

    def action_aw_update_costs_from_rates(self):
        """Cost from the current rate, for these variants."""
        variants = self
        updated, blocked = variants._aw_sync_cost_from_rate()

        if blocked:
            labels = {'average': 'AVCO', 'fifo': 'FIFO',
                      'standard': 'Standard Price'}
            methods = ', '.join(sorted({
                labels.get(variant.aw_cost_method, variant.aw_cost_method)
                for variant in blocked}))
            message = _(
                "Nothing written: %(count)s variant(s) are costed by "
                "%(methods)s, where stock valuation owns the Cost field. "
                "Writing it from a supplier rate would revalue your "
                "stock. The rate per foot is still shown for reference.",
                count=len(blocked), methods=methods)
            kind = 'warning'
        else:
            message = _(
                "%(done)s variant cost(s) updated from the current "
                "rates.", done=len(updated))
            kind = 'success' if updated else 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': kind,
                'message': message,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    aw_current_rate_ids = fields.One2many(
        'aw.profile.rate', compute='_compute_aw_current_rate_ids',
        string='Current Rates')

    # No depends: this reads a whole other table on today's date, which
    # @api.depends cannot express. Same pattern as aw.design.length_uom
    # reading ir.config_parameter -- a compute whose input is context
    # rather than sibling fields.
    @api.depends()
    def _compute_aw_current_rate_ids(self):
        """Every rate in force today for this profile.

        Built from aw.profile.rate, NOT from the variants that happen to
        exist: the question a buyer asks is "what does Chawla price this
        profile at", and answering it from variants would silently omit
        every combination nobody has quoted yet. `variant_exists` says
        which ones have been used, rather than the table quietly
        dropping them.
        """
        today = fields.Date.context_today(self)
        rates = self.env['aw.profile.rate']
        for template in self:
            template.aw_current_rate_ids = rates.search([
                ('product_tmpl_id', '=', template.id),
                ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
            ], order='thickness_id, finish_id, date_from desc')

    aw_cost_sync_allowed = fields.Boolean(
        compute='_compute_aw_cost_sync_allowed',
        help="False when the costing method is AVCO or FIFO, where "
             "stock valuation owns the cost field.")
    aw_cost_method = fields.Char(
        string='Costing Method', compute='_compute_aw_cost_sync_allowed')

    def _aw_cost_method(self):
        """The costing method, safely.

        `cost_method` is defined by **stock_account**, which this module
        deliberately does not depend on -- pulling in stock valuation
        and its accounting just to read one selection would be a heavy
        price. Without that module there is no valuation to corrupt, so
        the cost field is ours to write and 'standard' is the honest
        answer.

        Checking `_fields` rather than try/except because a missing
        field is a normal configuration here, not an error.
        """
        self.ensure_one()
        if 'cost_method' not in self._fields:
            return 'standard'
        return self.cost_method or 'standard'

    # No depends on cost_method, for the reason above.
    @api.depends()
    def _compute_aw_cost_sync_allowed(self):
        for template in self:
            method = template._aw_cost_method()
            template.aw_cost_method = method
            template.aw_cost_sync_allowed = method == "standard"

    def action_aw_update_costs_from_rates(self):
        """Cost from the current rate, for this template's variants.

        Delegates to product.product so there is ONE implementation.
        The button also has to exist here because
        `product.product_normal_form_view` is a primary inherit of the
        product.template form on model product.product -- a button
        added to the template form lands on the variant form too, and
        the Upgrade refuses it if the method is missing there.
        """
        return self.mapped(
            'product_variant_ids').action_aw_update_costs_from_rates()
