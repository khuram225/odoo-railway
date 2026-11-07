# -*- coding: utf-8 -*-
"""A panel's own hardware.

A panel with rows here is built from THEM and the spec's per-panel
hardware lines are not used for it; a panel with none follows the spec.
Window-level and junction lines always come from the spec. Same shape as
the glass stack: own, else the spec's.

The quantity is a plain number. The rate used defaults to the product's
cost and is typed per row (flagged manual, Reset returns to the product
cost).
"""
from odoo import api, fields, models


class AwDesignHardware(models.Model):
    _name = 'aw.design.hardware'
    _description = 'Panel Hardware'
    _order = 'sequence, id'

    leaf_id = fields.Many2one(
        'aw.design.leaf', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_hardware').id,
        )])
    qty = fields.Float(default=1.0)
    rate_manual = fields.Boolean(
        string='Manual rate',
        help="The rate was typed for this panel, not taken from the "
             "product's cost. Reset returns it.")
    manual_rate = fields.Float(digits='Product Price')
    list_rate = fields.Float(
        string='Product cost', compute='_compute_list_rate',
        digits='Product Price')

    @api.depends('product_id.standard_price')
    def _compute_list_rate(self):
        for row in self:
            row.list_rate = row.product_id.standard_price or 0.0

    def _as_dict(self):
        self.ensure_one()
        return {
            'id': self.id,
            'product_id': self.product_id.id,
            'name': self.product_id.display_name or '',
            'qty': self.qty,
            'rate_manual': self.rate_manual,
            'manual_rate': self.manual_rate,
            'list_rate': self.product_id.standard_price or 0.0,
        }

    @api.model
    def _commands_from(self, items):
        """Create commands for the rows a client sent. A row with no
        product is dropped rather than failing the whole save."""
        commands = []
        for index, item in enumerate(items or [], start=1):
            if not item.get('product_id'):
                continue
            manual = bool(item.get('rate_manual'))
            commands.append((0, 0, {
                'sequence': index * 10,
                'product_id': int(item['product_id']),
                'qty': float(item.get('qty') or 0.0),
                'rate_manual': manual,
                'manual_rate': float(item.get('manual_rate') or 0.0)
                if manual else 0.0,
            }))
        return commands

    @api.model
    def _hardware_category(self):
        return self.env.ref('aw_fenestration_core.product_category_hardware')

    @api.model
    def _product_catalogue(self):
        """The products a panel's hardware can be picked from."""
        products = self.env['product.product'].search([
            ('categ_id', 'child_of', self._hardware_category().id)],
            order='name', limit=500)
        return [{'id': p.id, 'name': p.display_name,
                 'cost': p.standard_price or 0.0} for p in products]

    @api.model
    def _create_product(self, name):
        """Quick create: a name makes a service-free, price-free product in
        Fenestration / Hardware. Done as sudo with fixed values, since a
        quoting user may not have the right to create products."""
        name = (name or '').strip()
        if not name:
            return False
        existing = self.env['product.product'].search([
            ('name', '=ilike', name),
            ('categ_id', 'child_of', self._hardware_category().id)], limit=1)
        product = existing or self.env['product.product'].sudo().create({
            'name': name,
            'categ_id': self._hardware_category().id,
            'type': 'consu',
            'sale_ok': False,
        })
        return {'id': product.id, 'name': product.display_name,
                'cost': product.standard_price or 0.0}
