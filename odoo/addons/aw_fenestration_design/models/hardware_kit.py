# -*- coding: utf-8 -*-
"""Hardware Sets saved from the configurator.

A set is a named list of hardware (product, quantity, and a rate only when it
was saved with rates) that a panel or the frame can take in one click. It is
COPIED onto the panel's own hardware rows (`aw.design.hardware`), so editing or
deleting a set later changes nothing already on a window.

Not `aw.hardware.set`: that model belongs to a Series and carries scope,
condition and leaf-type triggers for the explosion engine, and since phase 7d
it is only a legacy link kept for the spec and two reports. A set here is a
plain list, the same shape as a panel's rows; the model is called `kit` so the
two cannot be mistaken in code, while the screen says "Hardware Sets".
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

MANAGER_GROUP = 'aw_fenestration_core.group_fenestration_manager'


class AwHardwareKit(models.Model):
    _name = 'aw.hardware.kit'
    _description = 'Hardware Set (saved from the configurator)'
    _order = 'name, id'

    name = fields.Char(required=True)
    leaf_type_id = fields.Many2one(
        'aw.leaf.type', string='Panel type', ondelete='set null',
        help="Optional. The configurator lists the sets of the panel's own "
             "type first; a set with no type suits any panel and the frame.")
    active = fields.Boolean(default=True)
    notes = fields.Text()
    line_ids = fields.One2many(
        'aw.hardware.kit.line', 'kit_id', string='Hardware', copy=True)
    line_count = fields.Integer(compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for kit in self:
            kit.line_count = len(kit.line_ids)

    @api.constrains('name')
    def _check_name(self):
        for kit in self:
            name = (kit.name or '').strip()
            if not name:
                raise ValidationError(_("A hardware set needs a name."))
            twin = self.with_context(active_test=False).search([
                ('name', '=ilike', name), ('id', '!=', kit.id)], limit=1)
            if twin:
                raise ValidationError(_(
                    "There is already a hardware set called '%s'.", twin.name))

    # -- what the configurator reads ---------------------------------------
    def _payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'leaf_type_id': self.leaf_type_id.id or False,
            'leaf_type_name': self.leaf_type_id.name or '',
            'rows': [{
                'product_id': line.product_id.id,
                'name': line.product_id.display_name or '',
                'qty': line.qty,
                'rate_manual': line.rate_manual,
                'manual_rate': line.manual_rate if line.rate_manual else 0.0,
                'list_rate': line.product_id.standard_price or 0.0,
            } for line in self.line_ids.sorted(lambda l: (l.sequence, l.id))],
        }

    @api.model
    def _configurator_payload(self):
        """Every active set, for the Hardware section's dropdown."""
        return [kit._payload() for kit in self.search([])]

    @api.model
    def _can_edit(self):
        return self.env.user.has_group(MANAGER_GROUP)

    @api.model
    def create_from_rows(self, name, leaf_type_id, rows, with_rates=False):
        """Save a panel's (or the frame's) hardware rows as a set.

        Fenestration managers only. The rate is kept only with `with_rates`
        and only for a row whose rate was typed (a row on the product's cost
        has nothing to save: the set follows the product's cost when used).
        """
        if not self._can_edit():
            raise AccessError(_(
                "Only a Fenestration manager can save a hardware set."))
        name = (name or '').strip()
        if not name:
            raise UserError(_("Give the set a name."))
        lines = []
        for item in rows or []:
            if not item.get('product_id'):
                continue
            keep_rate = bool(with_rates and item.get('rate_manual'))
            lines.append((0, 0, {
                'sequence': (len(lines) + 1) * 10,
                'product_id': int(item['product_id']),
                'qty': float(item.get('qty') or 0.0),
                'rate_manual': keep_rate,
                'manual_rate': float(item.get('manual_rate') or 0.0)
                if keep_rate else 0.0,
            }))
        if not lines:
            raise UserError(_("There is no hardware to save."))
        kit = self.create({
            'name': name,
            'leaf_type_id': int(leaf_type_id) if leaf_type_id else False,
            'line_ids': lines,
        })
        return kit._payload()


class AwHardwareKitLine(models.Model):
    _name = 'aw.hardware.kit.line'
    _description = 'Hardware Set line'
    _order = 'sequence, id'

    kit_id = fields.Many2one(
        'aw.hardware.kit', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_hardware').id,
        )])
    qty = fields.Float(string='Quantity', default=1.0)
    rate_manual = fields.Boolean(
        string='Saved rate',
        help="Tick to carry a rate with this line. Left off, a panel uses "
             "the product's cost.")
    manual_rate = fields.Float(string='Rate', digits='Product Price')
