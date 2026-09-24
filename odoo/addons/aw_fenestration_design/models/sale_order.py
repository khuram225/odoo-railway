# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # aw.design.sale_order_id is a stored related on sale_order_line_id.order_id,
    # so it's a real column and can carry this One2many.
    aw_design_ids = fields.One2many(
        'aw.design', 'sale_order_id', string='Fenestration Designs')
    aw_default_series_id = fields.Many2one(
        'aw.window.series', string='Default Window Series',
        ondelete='restrict',
        help="Series every new position on this quote starts from. Leave "
             "blank to be asked each time. A position's own Series can "
             "always be changed afterwards on the design itself.")

    def _confirmation_error_message(self):
        """Core's own pre-confirmation hook (sale.order.action_confirm
        loops over it and raises whatever it returns), so this rides
        along with core's "some lines are missing a product" check
        rather than wrapping action_confirm itself."""
        self.ensure_one()
        error = super()._confirmation_error_message()
        if error:
            return error
        incomplete = self.aw_design_ids._incomplete_dimension_designs()
        if incomplete:
            return _(
                "These positions still need a width and a height before "
                "the order can be confirmed:\n%s",
                '\n'.join('- %s' % d.display_name for d in incomplete))
        return False

    def _create_fenestration_position(self, series, name=None, location=None):
        """Create the quote line and its design together. The line comes
        first because aw.design.sale_order_line_id is what ties the two
        together. Shared by both entry points -- the direct button when
        the quote has a default Series, and the wizard when it doesn't."""
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                "Positions can only be added while the order is still a "
                "quotation."))

        product = self.env.ref(
            'aw_fenestration_design.product_fenestration_position')
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
            'name': name or 'D%s' % position_no,
            'location': location or False,
            'qty': 1,
            'window_series_id': series.id,
            'sale_order_line_id': line.id,
        })
        # A design with no rows at all gives the configurator nothing to
        # draw or select, so it opens on an empty frame with no way in.
        # One row, one leaf of the Series' first allowed type is the
        # smallest thing that's actually editable. Sizes stay 0 -- they're
        # filled in on the configurator, and the leaf inherits whatever
        # the design's width/height become.
        leaf_type = series.leaf_type_ids[:1]
        if leaf_type:
            self.env['aw.design.row'].create({
                'design_id': design.id,
                'height_mm': design.height_mm,
                'leaf_ids': [(0, 0, {
                    'width_mm': design.width_mm,
                    'leaf_type_id': leaf_type.id,
                })],
            })
        return design

    def action_add_position(self):
        """Straight through when the quote has a default Series, otherwise
        via the wizard -- aw.design.window_series_id is required and the
        design has to exist before its form can open, so the Series has to
        be settled one way or the other up front."""
        self.ensure_one()
        if self.aw_default_series_id:
            design = self._create_fenestration_position(
                self.aw_default_series_id)
            return design.action_open_design()

        if not self.env['aw.window.series'].search_count([]):
            raise UserError(_(
                "No Window Series exists yet. Create at least one under "
                "Fenestration before adding positions to a quote."))

        return {
            'type': 'ir.actions.act_window',
            'name': _("Add Position"),
            'res_model': 'aw.design.position.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'aw_fenestration_design.view_aw_design_position_wizard_form').id,
            'target': 'new',
            'context': {'default_order_id': self.id},
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    aw_design_ids = fields.One2many(
        'aw.design', 'sale_order_line_id', string='Fenestration Design')

    def action_open_design(self):
        self.ensure_one()
        return self.aw_design_ids[:1].action_open_design()
