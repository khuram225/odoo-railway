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
from odoo.exceptions import UserError

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

# The leaf types that are opening sashes (everything but sliders and
# fixed lights): what an "opening sashes only" fly screen may go on.
OPENING_LEAF_CODES = tuple(sorted(
    code for code, role in ROLE_BY_LEAF_CODE.items()
    if role in ('openable', 'tiltturn')))


class AwDesign(models.Model):
    _inherit = 'aw.design'

    @api.model
    def _opening_leaf_codes(self):
        # The leaf type codes that are opening sashes. A method rather
        # than an import so design.py does not have to import family.py
        # (which extends the model design.py defines).
        return list(OPENING_LEAF_CODES)

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
            if design.system_locked:
                # The frame type was chosen in Add Position. An explicit
                # choice is not a guess to be corrected, so the panels
                # do not move it -- the Checks still report a panel the
                # system cannot host, which is the honest way to tell
                # someone the two disagree.
                continue
            if not design.family_id:
                continue
            candidates = design._candidate_systems()
            if not candidates:
                continue
            if design.window_series_id in candidates:
                continue
            design.window_series_id = candidates[0]

    def _frame_roles(self):
        """(value, label) for each role the family has an active system
        for -- what the Frame type dropdown offers besides Auto."""
        self.ensure_one()
        labels = dict(
            self.env['aw.window.series']._fields['system_role'].selection)
        roles = []
        for system in self.family_id.series_ids.filtered('active'):
            role = system.system_role
            if role and role not in [r[0] for r in roles]:
                roles.append((role, labels.get(role, role)))
        return roles

    def set_frame_role(self, role=False, keep_changes=True):
        """Choose the frame type from the configurator, or hand it back
        to the panels with a falsy `role` ("Auto").

        A role LOCKS the design to that role's system in its family and
        to the system's default spec, so drawing panels afterwards
        cannot move it. Panels the system cannot host become Fixed and
        are listed in the returned `frame_notice`, never dropped
        silently. Works on the STORED layout, so the configurator saves
        first when it has unsaved edits.
        """
        self.ensure_one()
        if not keep_changes:
            # Asked of the user, as for a spec change: a per-window
            # change may belong to the old system's spec.
            self.override_ids.unlink()
        converted = self.env['aw.design.leaf']
        system = self.env['aw.window.series']
        if not role:
            self.system_locked = False
            self._resolve_system()
            self._resolve_spec()
        else:
            if role not in dict(self._frame_roles()):
                labels = ', '.join(l for _r, l in self._frame_roles())
                raise UserError(_(
                    "'%(family)s' has no %(role)s system. It has: %(has)s.",
                    family=self.family_id.display_name or '', role=role,
                    has=labels or _('no systems with a role set')))
            system = self.family_id.series_ids.filtered(
                lambda s: s.active and s.system_role == role)[:1]
            spec = self.env['aw.window.template']._default_for_system(system)
            if not spec:
                raise UserError(_(
                    "%s has no specification yet; choose another frame "
                    "type or set one up for it first.",
                    system.display_name))
            self.write({
                'system_locked': True,
                'window_series_id': system.id,
                'template_id': spec.id,
            })
            self._apply_spec(force=True)
            converted = self._convert_unhostable_panels(system)
        self._explode()
        self._sync_sale_order_line()
        data = self.get_configurator_data()
        data['frame_notice'] = (_(
            "%(system)s cannot host the type of panel(s) %(numbers)s; "
            "they are now Fixed.",
            system=system.display_name,
            numbers=', '.join(str(n) for n in sorted(
                converted.mapped('panel_no')))) if converted else '')
        return data

    def _convert_unhostable_panels(self, system):
        """Make every panel whose type `system` cannot host Fixed."""
        self.ensure_one()
        fixed = self.env['aw.leaf.type'].search([('code', '=', 'FIXED')],
                                                limit=1)
        bad = self._all_panels().filtered(
            lambda l: l.leaf_type_id
            and l.leaf_type_id not in system.leaf_type_ids)
        if not bad or not fixed:
            return self.env['aw.design.leaf']
        bad.write({
            'leaf_type_id': fixed.id, 'hinge_side': False,
            'swing': False, 'slide_dir': False,
        })
        # Only the boundaries touching a converted panel: a junction
        # somebody set by hand elsewhere in the row stays.
        Leaf = self.env['aw.design.leaf']
        for row in bad.mapped('row_id'):
            leaves = row.leaf_ids.sorted('sequence')
            for index, leaf in enumerate(leaves):
                after = leaves[index + 1] if index + 1 < len(leaves)                     else Leaf
                if leaf not in bad and after not in bad:
                    continue
                as_dict = lambda l: {
                    'leaf_type_code': l.leaf_type_id.code,
                    'hinge_side': l.hinge_side}
                leaf.junction_after = Leaf._default_junction(
                    as_dict(leaf), as_dict(after) if after else None)
        return bad

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
