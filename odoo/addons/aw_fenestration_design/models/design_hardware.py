# -*- coding: utf-8 -*-
"""A panel's own hardware, and the FRAME's.

The frame (the window itself) has a section of its own, the same as a
panel's: rows with a product, a quantity and a rate. Those rows belong to
the window (`design_id`) instead of a panel (`leaf_id`); with none, the
window's hardware is what the spec gives it.

A panel with rows here is built from THEM and the spec's per-panel
hardware lines are not used for it; a panel with none follows the spec.
Window-level and junction lines always come from the spec. Same shape as
the glass stack: own, else the spec's.

The quantity is a plain number. The rate used defaults to the product's
cost and is typed per row (flagged manual, Reset returns to the product
cost).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AwDesignHardware(models.Model):
    _name = 'aw.design.hardware'
    _description = 'Panel Hardware'
    _order = 'sequence, id'

    # exactly one owner: a panel, or the window's frame
    leaf_id = fields.Many2one(
        'aw.design.leaf', ondelete='cascade', index=True)
    design_id = fields.Many2one(
        'aw.design', string='Window (frame hardware)', ondelete='cascade',
        index=True,
        help="Set on the FRAME's own hardware; a panel's rows have a panel.")
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

    @api.model_create_multi
    def create(self, vals_list):
        rows = super().create(vals_list)
        # a constraint runs only for the fields given, and a row with
        # neither owner gives neither
        rows._check_one_owner()
        return rows

    @api.constrains('leaf_id', 'design_id')
    def _check_one_owner(self):
        for row in self:
            if bool(row.leaf_id) == bool(row.design_id):
                raise ValidationError(_(
                    "Hardware belongs to a panel or to the frame, not both "
                    "and not neither."))

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


class AwDesign(models.Model):
    _inherit = 'aw.design'

    frame_hardware_ids = fields.One2many(
        'aw.design.hardware', 'design_id', string='Frame hardware',
        copy=False,
        help="The window's own hardware. With rows here the spec's "
             "window-level hardware lines are not used.")
