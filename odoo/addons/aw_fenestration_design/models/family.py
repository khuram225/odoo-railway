# -*- coding: utf-8 -*-
"""Glazing family on a design, and the profile system it implies.

A quote picks a FAMILY ("Double Glaze"). Which profile SYSTEM the frame
is built from follows from the panels that end up in it, so nobody has
to decide it before they have drawn anything.

`window_series_id` stays stored and authoritative: the BOM, the rates,
the cutting plan and everything else downstream read it, and making it
computed-only would have meant touching all of them. It is now
DERIVED from the family plus the panels, but it is still a real field
holding a real system.
"""
from odoo import _, api, fields, models

# Which system role a leaf type needs. Anything not listed is a fixed
# panel as far as the frame is concerned.
ROLE_BY_LEAF_CODE = {
    'SLIDER': 'sliding',
    'MESH': 'sliding',          # a mesh sash runs on a track
    'TILTTURN': 'tiltturn',
    'CASEMENT': 'openable',
    'AWNING': 'openable',
    'HOPPER': 'openable',
}


class AwDesign(models.Model):
    _inherit = 'aw.design'

    family_id = fields.Many2one(
        'aw.window.family', string='Glazing Family', tracking=True,
        ondelete='restrict', index=True,
        help="Chosen up front. The profile system is worked out from "
             "the panels you draw.")
    aw_system_choices = fields.Integer(
        compute='_compute_system_choices',
        help="How many of the family's systems could carry this "
             "layout. More than one means the user has to choose.")

    # ------------------------------------------------------------------
    def _panel_roles(self):
        """The system roles the drawn panels need."""
        self.ensure_one()
        roles = set()
        for leaf in self._all_panels():
            code = (leaf.leaf_type_id.code or '').upper()
            roles.add(ROLE_BY_LEAF_CODE.get(code, 'fixed'))
        return roles

    def _required_role(self):
        """The one system role this layout needs, or None.

        Order matters and is the client's: a tilt & turn panel forces
        the Tilt & Turn system; any other opening panel forces
        Openable; a slider forces Sliding; all-fixed takes the Fixed
        system when one exists and Openable otherwise, because a fixed
        system with no Profile Section cannot produce a BOM.
        """
        self.ensure_one()
        roles = self._panel_roles()
        if not roles:
            return None
        if 'tiltturn' in roles:
            return 'tiltturn'
        if 'openable' in roles:
            return 'openable'
        if 'sliding' in roles:
            return 'sliding'
        return 'fixed'

    def _candidate_systems(self):
        """The family's systems that could carry this layout."""
        self.ensure_one()
        family = self.family_id
        if not family:
            return self.env['aw.window.series']
        systems = family.series_ids.filtered('active')
        role = self._required_role()
        if not role:
            return systems

        matching = systems.filtered(lambda s: s.system_role == role)
        if role == 'fixed':
            # A Fixed system with no Profile Section cannot be costed,
            # so the Openable one carries plain fixed lights instead.
            usable = matching.filtered(lambda s: s.profile_section_ids)
            if usable:
                return usable
            return systems.filtered(
                lambda s: s.system_role == 'openable') or matching
        return matching

    @api.depends('family_id', 'row_ids.leaf_ids.leaf_type_id')
    def _compute_system_choices(self):
        for design in self:
            design.aw_system_choices = len(design._candidate_systems())

    def _resolve_system(self):
        """Pick the system, keeping a deliberate choice that still fits.

        Only ever assigns when the current system does NOT fit: an
        estimator who picked one of two valid systems keeps it.
        """
        for design in self:
            if not design.family_id:
                continue
            candidates = design._candidate_systems()
            if not candidates:
                continue
            if design.window_series_id in candidates:
                continue
            design.window_series_id = candidates[0]

    def _mixed_frame_error(self):
        """Sliding and opening panels cannot share one frame.

        [revisit] The client is to confirm this. It is an error rather
        than a warning because the two need different outer frames, so
        the BOM that would come out of it is not something anyone could
        cut.
        """
        self.ensure_one()
        roles = self._panel_roles()
        if 'sliding' in roles and ({'openable', 'tiltturn'} & roles):
            return _(
                "This design mixes sliding and opening panels, which "
                "cannot share one frame. Make them separate windows.")
        return ''

    # ------------------------------------------------------------------
    @api.onchange('family_id')
    def _onchange_family_clears_glass(self):
        """Drop glass the new family cannot use, and say so."""
        for design in self:
            spec = design.glass_spec_id
            if not (design.family_id and spec):
                continue
            wanted = design.family_id.glazing
            if wanted and wanted != 'none' and spec.glazing \
                    and spec.glazing != wanted:
                design.glass_spec_id = False
                return {'warning': {
                    'title': _("Glass cleared"),
                    'message': _(
                        "'%(glass)s' is %(has)s glazed and %(family)s "
                        "needs %(wants)s. Pick a new glass.",
                        glass=spec.display_name, has=spec.glazing,
                        family=design.family_id.display_name,
                        wants=wanted),
                }}

    @api.model
    def _migrate_family_from_series(self):
        """Give existing designs and quotes a family, once.

        Taken from the system they already use, which is the only
        answer that cannot be wrong: the design was built in that
        system, so its family is that system's.
        """
        param = self.env['ir.config_parameter'].sudo()
        key = 'aw_fenestration.design_family_migrated'
        if param.get_param(key):
            return 0

        migrated = 0
        for design in self.with_context(active_test=False).search(
                [('family_id', '=', False)]):
            family = design.window_series_id.family_id
            if family:
                design.family_id = family
                migrated += 1

        orders = self.env['sale.order'].search(
            [('aw_default_family_id', '=', False),
             ('aw_default_series_id', '!=', False)])
        for order in orders:
            family = order.aw_default_series_id.family_id
            if family:
                order.aw_default_family_id = family

        param.set_param(key, '1')
        return migrated
