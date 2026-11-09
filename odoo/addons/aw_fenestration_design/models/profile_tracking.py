# -*- coding: utf-8 -*-
"""Profiles are tracked by lot.

Every delivery of bars is received as lots (one per variant and length, with
`length_mm`), so a profile product is tracked "By Lots". The switch is a
one-time step that REFUSES while there is any stock or an open move of a
profile (Odoo would keep the quantity but leave it without a lot) and is
tried again at the next upgrade; a profile made afterwards, storable and
without a tracking asked for, is tracked by lot from the start.

Lots & Serial Numbers (`stock.group_production_lot`) and "Create New
Lots/Serial Numbers" on the Receipts operation type were already on; nothing
here changes them.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PARAM = 'aw_fenestration.profile_lot_tracking_set'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        root = self.env.ref('aw_fenestration_core.product_category_profiles',
                            raise_if_not_found=False)
        for vals in vals_list:
            if 'tracking' in vals or not root or not vals.get('categ_id') \
                    or not vals.get('is_storable'):
                continue
            path = self.env['product.category'].browse(
                vals['categ_id']).parent_path or ''
            if root.parent_path and path.startswith(root.parent_path):
                vals['tracking'] = 'lot'
        return super().create(vals_list)

    @api.model
    def _aw_switch_profiles_to_lot(self):
        """Once: every storable profile is tracked by lot, if none of them
        has stock or an open move."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PARAM):
            return
        root = self.env.ref('aw_fenestration_core.product_category_profiles')
        templates = self.sudo().with_context(active_test=False).search([
            ('categ_id', 'child_of', root.id), ('is_storable', '=', True)])
        variants = self.env['product.product'].sudo().with_context(
            active_test=False).search([('product_tmpl_id', 'in', templates.ids)])
        quants = self.env['stock.quant'].sudo().search_count([
            ('product_id', 'in', variants.ids), ('quantity', '!=', 0)])
        moves = self.env['stock.move'].sudo().search_count([
            ('product_id', 'in', variants.ids),
            ('state', 'not in', ('done', 'cancel'))])
        if quants or moves:
            _logger.warning(
                "profile lot tracking NOT switched: %s quant(s) with stock "
                "and %s open move(s) on profiles; tried again at the next "
                "upgrade", quants, moves)
            return
        todo = templates.filtered(lambda t: t.tracking != 'lot')
        todo.write({'tracking': 'lot'})
        _logger.info("profile lot tracking: %s of %s template(s) switched",
                     len(todo), len(templates))
        param.set_param(PARAM, '1')
