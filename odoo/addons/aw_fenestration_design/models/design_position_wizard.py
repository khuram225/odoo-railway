# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo import _, fields, models


class AwDesignPositionWizard(models.TransientModel):
    """Asks for the glazing FAMILY when the quote has no default one.

    The profile system is no longer asked for: it is derived from the
    panels drawn (see aw.design._resolve_system). This wizard still
    exists because aw.design.window_series_id is required and Add
    Position opens the design immediately, so a starting system has to
    be supplied before the user sees anything -- see _starting_system.
    Name and location are a convenience, editable on the design form
    right afterwards."""
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
        help="Sets this family as the quote's default, so further "
             "positions skip this dialog. Each design's own family can "
             "still be changed afterwards.")

    def _starting_system(self):
        """A profile system to create the design in, before anything is
        drawn.

        aw.design.window_series_id is required and the design must
        exist before its configurator can open, so something has to be
        chosen now. The family's Openable system is the safe starting
        point: it hosts fixed lights as well as opening ones, so the
        first panel rarely forces a change, and _resolve_system()
        corrects it on the first save regardless.
        """
        self.ensure_one()
        systems = self.family_id.series_ids.filtered('active')
        if not systems:
            raise UserError(_(
                "'%s' has no profile systems yet. Add one under "
                "Fenestration before quoting it.",
                self.family_id.display_name))
        openable = systems.filtered(lambda s: s.system_role == 'openable')
        return (openable or systems)[0]

    def action_confirm(self):
        self.ensure_one()
        if self.set_as_default:
            # The FAMILY is the quote's default now. The system is
            # derived per design from the panels drawn, so pinning one
            # on the quote would be recording a guess as a decision.
            self.order_id.aw_default_family_id = self.family_id
        design = self.order_id._create_fenestration_position(
            self._starting_system(), name=self.name,
            location=self.location, family=self.family_id)
        # Straight into the configurator (spec 4.4). The raw form stays
        # reachable from there and from the Designs menu for admins.
        return design.action_open_configurator()
