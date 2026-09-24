# -*- coding: utf-8 -*-
from odoo import fields, models


class AwDesignPositionWizard(models.TransientModel):
    """Asks for the Window Series when the quote has no default one set.
    Only reason this exists: aw.design.window_series_id is required, and
    Add Position opens the design's form immediately, so the design has
    to be creatable before the user sees it. Name and location are here
    purely as a convenience -- both are editable on the design form right
    afterwards."""
    _name = 'aw.design.position.wizard'
    _description = 'Add Fenestration Position'

    order_id = fields.Many2one(
        'sale.order', required=True, ondelete='cascade')
    window_series_id = fields.Many2one(
        'aw.window.series', string='Window Series', required=True)
    name = fields.Char(
        string='Position Ref',
        help="Leave blank to auto-number (D1, D2, ...).")
    location = fields.Char(help="e.g. 'Drawing room', 'Bathroom'.")
    set_as_default = fields.Boolean(
        string='Use as default for this quote', default=True,
        help="Sets this Series as the quote's default, so further "
             "positions skip this dialog. Each design's own Series can "
             "still be changed afterwards.")

    def action_confirm(self):
        self.ensure_one()
        if self.set_as_default:
            self.order_id.aw_default_series_id = self.window_series_id
        design = self.order_id._create_fenestration_position(
            self.window_series_id, name=self.name, location=self.location)
        # Straight into the configurator (spec 4.4). The raw form stays
        # reachable from there and from the Designs menu for admins.
        return design.action_open_configurator()
