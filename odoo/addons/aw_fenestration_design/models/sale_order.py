# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # aw.design.sale_order_id is a stored related on sale_order_line_id.order_id,
    # so it's a real column and can carry this One2many.
    aw_design_ids = fields.One2many(
        'aw.design', 'sale_order_id', string='Fenestration Designs')

    def action_add_position(self):
        """Create the quote line and its design together, then drop the
        user straight into the design form to fill in the geometry. The
        line is created first because aw.design.sale_order_line_id is
        what ties the two together."""
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                "Positions can only be added while the order is still a "
                "quotation."))

        product = self.env.ref(
            'aw_fenestration_design.product_fenestration_position')
        # aw.design.window_series_id is required, and a design has to exist
        # before the form can open on it -- so one has to be picked here.
        # Erroring is better than inventing a Series record.
        series = self.env['aw.window.series'].search([], limit=1)
        if not series:
            raise UserError(_(
                "No Window Series exists yet. Create at least one under "
                "Fenestration before adding positions to a quote."))

        # Counted before the line exists, and by search rather than off
        # self.aw_design_ids, so a stale cache can't hand two positions
        # the same ref.
        position_no = self.env['aw.design'].search_count([
            ('sale_order_id', '=', self.id),
        ]) + 1

        line = self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_id': product.product_variant_id.id,
            'product_uom_qty': 1,
        })
        design = self.env['aw.design'].create({
            'name': 'D%s' % position_no,
            'qty': 1,
            'window_series_id': series.id,
            'sale_order_line_id': line.id,
        })
        return design.action_open_design()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    aw_design_ids = fields.One2many(
        'aw.design', 'sale_order_line_id', string='Fenestration Design')

    def action_open_design(self):
        self.ensure_one()
        return self.aw_design_ids[:1].action_open_design()
