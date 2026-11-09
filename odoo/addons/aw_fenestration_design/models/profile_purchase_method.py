# -*- coding: utf-8 -*-
"""Vendor bills for profiles follow what was RECEIVED.

The control policy (`purchase_method`) of a profile product is "On received
quantities": a bill is made for the feet that arrived, not the feet ordered.
Odoo 19 already defaults a goods product to "receive", so this is a guard
rather than a new default: a profile made without a policy gets it, and the
profiles that had been set to "On ordered quantities" are put right once.
A bill for bars that arrived and were not ordered needs nothing special: a
line "added at receipt" is an ordinary order line with its own received
quantity.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PARAM = 'aw_fenestration.profile_purchase_method_set'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        root = self.env.ref('aw_fenestration_core.product_category_profiles',
                            raise_if_not_found=False)
        for vals in vals_list:
            if 'purchase_method' in vals or not root or not vals.get('categ_id'):
                continue
            path = self.env['product.category'].browse(
                vals['categ_id']).parent_path or ''
            if root.parent_path and path.startswith(root.parent_path) \
                    and vals.get('type', 'consu') != 'service':
                vals['purchase_method'] = 'receive'
        return super().create(vals_list)

    @api.model
    def _aw_set_profile_receive(self):
        """Once: profiles still on "On ordered quantities" go to "On
        received quantities". One-shot by a parameter, so a later deliberate
        change is not undone by an upgrade."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PARAM):
            return
        root = self.env.ref('aw_fenestration_core.product_category_profiles')
        templates = self.sudo().with_context(active_test=False).search([
            ('categ_id', 'child_of', root.id),
            ('purchase_method', '!=', 'receive')])
        templates.write({'purchase_method': 'receive'})
        _logger.info("profile purchase_method: %s template(s) set to receive",
                     len(templates))
        param.set_param(PARAM, '1')
