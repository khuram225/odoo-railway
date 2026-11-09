# -*- coding: utf-8 -*-
"""The receive screen: a list of rows, grouped by variant.

Each ordered variant has a ready row for every active length with bars at 0
and a subtotal row (ordered, received and arriving feet, and whether it is
short or over). A variant that is not on the order is added as a row. The
person types only numbers; Validate hands the rows to
`purchase.order._aw_receive_bars`.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .po_receipt import LARGE_ROW, ft_status

HIDE_PRICES = 'aw_fenestration.receive_hide_prices'


class AwPoReceiveWizard(models.TransientModel):
    _name = 'aw.po.receive.wizard'
    _description = 'Receive bars'

    order_id = fields.Many2one(
        'purchase.order', string='Purchase order', required=True,
        readonly=True)
    counted_by_id = fields.Many2one(
        'res.users', string='Counted by', required=True,
        default=lambda self: self.env.user)
    count_date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        'aw.po.receive.line', 'wizard_id', string='Bars')
    hide_prices = fields.Boolean(compute='_compute_hide_prices')
    has_large = fields.Boolean(compute='_compute_flags')
    all_zero = fields.Boolean(compute='_compute_flags')
    confirm_large = fields.Boolean(string='I checked the large rows')

    @api.depends_context('uid')
    def _compute_hide_prices(self):
        hide = bool(self.env['ir.config_parameter'].sudo().get_param(
            HIDE_PRICES))
        # a buyer or a manager still sees the prices
        counts_only = not (
            self.env.user.has_group('purchase.group_purchase_manager')
            or self.env.user.has_group(
                'aw_fenestration_core.group_fenestration_manager'))
        for wizard in self:
            wizard.hide_prices = hide and counts_only

    @api.depends('line_ids.bars', 'line_ids.kind')
    def _compute_flags(self):
        for wizard in self:
            counted = wizard.line_ids.filtered(lambda l: l.kind != 'total')
            wizard.has_large = any(l.bars > LARGE_ROW for l in counted)
            wizard.all_zero = not any(l.bars > 0 for l in counted)

    def action_validate(self):
        self.ensure_one()
        counted = self.line_ids.filtered(lambda l: l.kind != 'total')
        if any(l.bars < 0 for l in counted):
            raise UserError(_("Bars cannot be negative."))
        if not any(l.bars > 0 for l in counted):
            raise UserError(_("Nothing to receive: every row is 0."))
        for line in counted.filtered(lambda l: l.bars > 0):
            if not line.product_id or line.bar_length_ft <= 0:
                raise UserError(_("Every row needs a profile and a length."))
        if self.has_large and not self.confirm_large:
            raise UserError(_(
                "A row has more than %(n)s bars. Check the count and tick "
                "'I checked the large rows'.", n=LARGE_ROW))
        self.order_id._aw_receive_bars(
            [{'product_id': l.product_id.id,
              'bar_length_ft': l.bar_length_ft, 'bars': l.bars}
             for l in counted if l.bars > 0],
            counted_by=self.counted_by_id, count_date=self.count_date)
        return {
            'type': 'ir.actions.act_window', 'res_model': 'purchase.order',
            'res_id': self.order_id.id, 'view_mode': 'form',
            'views': [(False, 'form')], 'target': 'main'}


class AwPoReceiveLine(models.TransientModel):
    _name = 'aw.po.receive.line'
    _description = 'Receive bars, one row'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'aw.po.receive.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=1000)
    kind = fields.Selection(
        [('length', 'Length'), ('total', 'Subtotal'), ('added', 'Added')],
        default='added', required=True)
    product_id = fields.Many2one(
        'product.product', string='Profile variant',
        domain="[('categ_id.complete_name', 'like', 'Fenestration / Profiles')]")
    bar_length_ft = fields.Float(string='Length (ft)')
    ordered_bars = fields.Integer(string='Ordered bars')
    received_bars = fields.Integer(string='Received bars')
    bars = fields.Integer(string='Bars arriving now')
    ordered_ft = fields.Float(string='Ordered ft')
    received_ft = fields.Float(string='Received ft')
    arriving_ft = fields.Float(
        string='Arriving ft', compute='_compute_arriving')
    price_ft = fields.Float(string='Price / ft')
    status = fields.Char(compute='_compute_arriving')

    @api.depends('bars', 'bar_length_ft', 'kind', 'product_id',
                 'ordered_ft', 'received_ft',
                 'wizard_id.line_ids.bars', 'wizard_id.line_ids.bar_length_ft',
                 'wizard_id.line_ids.kind', 'wizard_id.line_ids.product_id')
    def _compute_arriving(self):
        for line in self:
            if line.kind == 'total':
                siblings = line.wizard_id.line_ids.filtered(
                    lambda l: l.kind != 'total'
                    and l.product_id == line.product_id)
                arriving = sum(s.bars * s.bar_length_ft for s in siblings)
                line.arriving_ft = arriving
                line.status = ft_status(
                    line.ordered_ft, line.received_ft + arriving) \
                    if line.ordered_ft else ''
            else:
                line.arriving_ft = line.bars * line.bar_length_ft
                line.status = False

    @api.onchange('product_id', 'kind')
    def _onchange_added_price(self):
        for line in self:
            if line.kind == 'added' and line.product_id \
                    and line.wizard_id.order_id:
                line.price_ft = line.wizard_id.order_id._aw_receipt_price(
                    line.product_id)[0]
