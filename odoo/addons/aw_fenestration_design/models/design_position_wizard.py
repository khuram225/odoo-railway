# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo import _, fields, models


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
    family_id = fields.Many2one(
        'aw.window.family', string='Glazing Family', required=True,
        ondelete='restrict',
        help="The profile system is worked out from the panels you "
             "draw, so this is the only thing to decide up front.")
    # No longer asked for: the family is the question now, and
    # _starting_system() supplies a system so aw.design's required
    # field is satisfied. Kept so a caller that still passes one works.
    window_series_id = fields.Many2one(
        'aw.window.series', string='Profile System')
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
            self.order_id.aw_default_family_id = self.family_id
            self.order_id.aw_default_series_id = self._starting_system()
        design = self.order_id._create_fenestration_position(
            self._starting_system(), name=self.name,
            location=self.location, family=self.family_id)
        # Straight into the configurator (spec 4.4). The raw form stays
        # reachable from there and from the Designs menu for admins.
        return design.action_open_configurator()
