# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo import _, api, fields, models

# The same four roles aw.window.series.system_role offers. Duplicated as
# a Selection rather than reached through a Many2one because the dialog
# shows the SHORT name -- "Openable", not "Double Glaze - Openable",
# which is what a Many2one would display and is redundant one line under
# the family that already says "Double Glaze".
FRAME_ROLES = [
    ('sliding', 'Sliding'),
    ('openable', 'Openable'),
    ('tiltturn', 'Tilt & Turn'),
    ('fixed', 'Fixed'),
]


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
    _description = 'Add Fenestration Window'

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
    frame_role = fields.Selection(
        FRAME_ROLES, string='Frame Type',
        help="Optional. Leave empty to let the frame be decided from "
             "the panels you draw, as before. Choosing one starts the "
             "design on that system and keeps it there.")
    # Not stored: it is a lookup from family + role, and storing it
    # would be a second place for the same answer to live.
    window_system_id = fields.Many2one(
        'aw.window.series', string='Window System',
        compute='_compute_window_system_id')
    # store=True is load-bearing, not habit. A non-stored editable
    # compute is recomputed on the next request, so the spec picked by
    # hand in the dialog would be silently discarded and replaced by the
    # system's default the moment Confirm ran. A transient model has a
    # real table, so storing it keeps the choice.
    template_id = fields.Many2one(
        'aw.window.template', string='Spec',
        compute='_compute_template_id', readonly=False, store=True,
        domain="[('window_type_id', '=', window_system_id)]",
        help="Defaults to that system's default specification.")

    name = fields.Char(
        string='Design Ref',
        help="Leave blank to auto-number (W1, W2, ...).")
    location = fields.Char(help="e.g. 'Drawing room', 'Bathroom'.")
    set_as_default = fields.Boolean(
        string='Use as default for this quote', default=True,
        help="Sets this family as the quote's default, so further "
             "windows skip this dialog. Each design's own family can "
             "still be changed afterwards.")

    @api.depends('family_id', 'frame_role')
    def _compute_window_system_id(self):
        for wizard in self:
            wizard.window_system_id = wizard._role_system()

    def _role_system(self):
        """The family's active system with the chosen role, or empty."""
        self.ensure_one()
        if not (self.family_id and self.frame_role):
            return self.env['aw.window.series']
        return self.family_id.series_ids.filtered(
            lambda s: s.active and s.system_role == self.frame_role)[:1]

    @api.depends('window_system_id')
    def _compute_template_id(self):
        """Propose the system's default spec, leaving it editable.

        `readonly=False` on a compute is what makes this a DEFAULT
        rather than a verdict: it recomputes when the frame type
        changes, and a spec picked by hand afterwards stands.
        """
        Spec = self.env['aw.window.template']
        for wizard in self:
            wizard.template_id = (
                Spec._default_for_system(wizard.window_system_id)
                if wizard.window_system_id else Spec)

    def _chosen_system(self):
        """The explicitly chosen system, erroring if it cannot be used.

        Both messages name what the family DOES have, because the
        dialog offers all four roles whatever the family carries -- a
        Selection's options cannot depend on another field's value.
        """
        self.ensure_one()
        system = self._role_system()
        if not system:
            available = self.family_id.series_ids.filtered('active')
            roles = dict(FRAME_ROLES)
            has = ', '.join(sorted(
                roles.get(r, r) for r in set(
                    available.mapped('system_role')) if r))
            raise UserError(_(
                "'%(family)s' has no %(role)s system. It has: %(has)s.",
                family=self.family_id.display_name,
                role=dict(FRAME_ROLES)[self.frame_role],
                has=has or _('no systems with a role set')))
        if not self.template_id:
            raise UserError(_(
                "%(system)s has no specification yet; choose another "
                "frame type or set one up for it first.",
                system=system.display_name))
        return system

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
        if self.frame_role:
            # Explicit choice: that system, its spec, and locked so the
            # panels drawn afterwards cannot move it.
            system = self._chosen_system()
            design = self.order_id._create_fenestration_position(
                system, name=self.name, location=self.location,
                family=self.family_id, spec=self.template_id,
                lock_system=True)
        else:
            # Unchanged: a starting system purely so the required field
            # is satisfied, corrected from the panels on the first save.
            design = self.order_id._create_fenestration_position(
                self._starting_system(), name=self.name,
                location=self.location, family=self.family_id)
        # Straight into the configurator (spec 4.4). The raw form stays
        # reachable from there and from the Designs menu for admins.
        return design.action_open_configurator()
