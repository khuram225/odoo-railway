# -*- coding: utf-8 -*-
"""The cost basis: list rate only (the default) or the cost rule.

* A QUOTE follows its own Price Structure's basis (`costing._rule_pick`).
* The COST FIELD of a profile variant (`standard_price`, what stock is valued
  at) follows the DEFAULT structure's basis, and is written by the cost
  sync: the "Update costs from rates" button, a new variant, and a confirmed
  purchase order (its last purchase prices are new), series' default vendor.
* The sync never overwrites a cost somebody typed without saying so: a cost
  that is not any known rate or last price of the profile and was not
  written by the sync is "typed by hand", kept, and listed. Every write the
  sync makes is tagged `[rates sync]` in the product's value history.
* Stock is valued at `standard_price` times the quantity (Standard Price,
  periodic valuation): changing the cost moves the value of stock on hand
  and leaves a dated row in the history; nothing else.
"""
from odoo import _, api, fields, models
from odoo.tools import float_compare

from .cost_rule import money

SYNC_TAG = '[rates sync] '


class AwPriceStructure(models.Model):
    _inherit = 'aw.price.structure'

    def action_open_cost_preview(self):
        """What the cost rule would do, before the basis is switched on."""
        self.ensure_one()
        return self.env['aw.cost.preview.wizard'].action_open()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _aw_default_cost_basis(self):
        return self.env['aw.price.structure']._default_structure().cost_basis \
            or 'list'

    def _aw_target_cost(self, basis):
        """(cost per ft, where it comes from) by `basis`, or None when
        there is no source to cost from."""
        self.ensure_one()
        if basis == 'rule':
            result = self._aw_current_cost()
            if result['kind'] == 'none':
                return None
            return result['cost'], result['text']
        if not self.aw_has_rate:
            return None
        return self.aw_rate_per_ft, 'list %s' % money(self.aw_rate_per_ft)

    def _aw_known_prices(self):
        """Every list rate and last purchase price of this profile, rounded:
        a cost equal to one of them was written by a sync, not typed."""
        template = self.product_tmpl_id
        prices = {round(p, 4) for p in self.env['aw.profile.rate'].sudo(
        ).search([('product_tmpl_id', '=', template.id)]).mapped('price')}
        prices |= {round(p, 4) for p in self.env['aw.profile.lpp'].sudo(
        ).search([('product_tmpl_id', '=', template.id)]).mapped('price_ft')}
        return prices

    def _aw_cost_typed_by_hand(self):
        self.ensure_one()
        if not self.standard_price:
            return False
        if round(self.standard_price, 4) in self._aw_known_prices():
            return False
        if 'product.value' not in self.env:
            return True
        last = self.env['product.value'].sudo().search([
            ('product_id', '=', self.id), ('move_id', '=', False)],
            order='id desc', limit=1)
        return not (last and (last.description or '').startswith(SYNC_TAG))

    def _aw_tag_sync(self, text):
        if 'product.value' not in self.env:
            return
        last = self.env['product.value'].sudo().search([
            ('product_id', '=', self.id), ('move_id', '=', False)],
            order='id desc', limit=1)
        if last:
            last.description = '%s%s (%s)' % (
                SYNC_TAG, last.description or '', text)

    def _aw_sync_cost_from_rate(self):
        """Write standard_price from the cost basis: the list rate, or the
        cost rule. Returns (updated, blocked). Never written: a variant with
        nothing to cost from (left alone, not zeroed); one costed AVCO or
        FIFO (stock valuation owns it); one whose cost was typed by hand
        (kept, and listed in context `aw_kept_costs` when the caller gave a
        list)."""
        updated = blocked = self.browse()
        kept = self.env.context.get('aw_kept_costs')
        basis = self._aw_default_cost_basis()
        for variant in self:
            target = variant._aw_target_cost(basis)
            if target is None:
                continue
            if not variant.aw_cost_sync_allowed:
                blocked |= variant
                continue
            cost, text = target
            if float_compare(variant.standard_price, cost,
                             precision_digits=4) == 0:
                continue
            if variant._aw_cost_typed_by_hand():
                if kept is not None:
                    kept.append((variant, variant.standard_price, cost, text))
                continue
            variant.standard_price = cost
            variant._aw_tag_sync(text)
            updated |= variant
        return updated, blocked

    def action_aw_update_costs_from_rates(self):
        kept = []
        action = super(ProductProduct, self.with_context(
            aw_kept_costs=kept)).action_aw_update_costs_from_rates()
        if kept:
            text = _("Kept, typed by hand and not overwritten: %s.") % '; '.join(
                "%s: %s (the basis gives %s, %s)" % (
                    v.display_name, money(now), money(new), why)
                for v, now, new, why in kept)
            params = action['params']
            params['message'] = '%s %s' % (params['message'], text)
            params['type'] = 'warning'
            params['sticky'] = True
        return action

    @api.model_create_multi
    def create(self, vals_list):
        variants = super().create(vals_list)
        # a profile variant made any way (the PO line picker, a receipt, the
        # bars grid, a design) is costed from the basis at once; one made
        # during an upgrade is left to the cost sync
        if not self.pool._init:
            profiles = variants.filtered(
                lambda v: v.product_tmpl_id.aw_is_profile
                and not v.standard_price)
            if profiles:
                profiles.sudo()._aw_sync_cost_from_rate()
        return variants


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _aw_refresh_costs(self):
        """A confirmed (or cancelled) order changes the last purchase
        prices of its profiles: with the rule on, their cost follows."""
        if self.env['product.product']._aw_default_cost_basis() != 'rule':
            return
        for order in self:
            variants = order._aw_print_bar_lines().product_id
            if not variants:
                continue
            kept = []
            variants.sudo().with_context(
                aw_kept_costs=kept)._aw_sync_cost_from_rate()
            if kept:
                order.message_post(
                    body=_("Cost kept, typed by hand and not overwritten: "
                           "%s.") % '; '.join(
                        "%s: %s (the rule gives %s)" % (
                            v.display_name, money(now), money(new))
                        for v, now, new, _why in kept),
                    subtype_xmlid='mail.mt_note')
