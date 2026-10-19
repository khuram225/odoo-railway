# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .formula import validate_formula

_logger = logging.getLogger(__name__)


# The window parts a spec is read by, in the order they are shown.
# Display only: nothing in the BOM, the formulas or the cut list reads it.
PART_GROUPS = [
    ('outer_frame', 'Outer frame'),
    ('sashes', 'Sashes'),
    ('beads', 'Beads'),
    ('dividers', 'Dividers'),
    ('interlock_meeting', 'Interlock & meeting'),
    ('lock', 'Lock'),
    ('fly_screen', 'Fly screen'),
]

# scope -> group, for the seed. Name rules come first (see
# _part_group_for): a lock bar and a Palay Bead share a scope with the
# sash profiles but are different parts of the window.
GROUP_BY_SCOPE = {
    'frame': 'outer_frame',
    'panel_opening': 'sashes',
    'panel_fixed': 'beads',
    'panel_mesh': 'fly_screen',
    'mesh_attachment': 'fly_screen',
    'junction_mullion': 'dividers',
    'transom': 'dividers',
    'junction_meeting': 'interlock_meeting',
    'junction_interlock': 'interlock_meeting',
}


class AwProfilePosition(models.Model):
    """Open-ended replacement for the old hardcoded 5-value role Selection
    (frame/sash/interlock/bead/mesh) on aw.profile.section.line. A real
    fabrication combination can need frame split by top/bottom/sides
    (different drainage profile on the sill than the head/jambs — the
    real detail that came out of the Double Glaze Sliding Profile 1
    breakdown), which a fixed 5-value list can't express. This table can
    grow by adding a row — no schema change, no code change — which is
    the actual point of making it dynamic rather than a longer hardcoded
    list.
    """
    _name = 'aw.profile.position'
    _description = 'Fenestration Profile Position'
    _order = 'sequence, name'

    name = fields.Char(required=True, help="e.g. 'Outer Frame - Top', "
        "'Palay - Bottom', 'Mesh - All Sides'.")
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # -- BOM rules (spec 6.2) ----------------------------------------------
    # scope answers "where does this profile appear at all", which is what
    # lets the explosion engine walk the design once and ask each position
    # whether it applies, instead of hard-coding the frame/sash/bead cases
    # it happens to know about. A position with no scope is simply not
    # reachable by the engine; the checks say so rather than leaving it to
    # be noticed by its absence from a quote.
    scope = fields.Selection([
        ('frame', 'Frame (once per design)'),
        ('panel_opening', 'Opening panel'),
        ('panel_fixed', 'Fixed panel'),
        ('panel_mesh', 'Mesh panel'),
        ('mesh_attachment', 'Attached mesh'),
        ('junction_mullion', 'Mullion junction'),
        ('junction_meeting', 'Meeting junction'),
        ('junction_interlock', 'Interlock junction'),
        ('transom', 'Transom (row boundary)'),
    ], help="Where this profile appears. A position with no scope is "
            "ignored by the BOM, and the checks report it.")
    part_group = fields.Selection(
        PART_GROUPS, string='Part Group',
        help="Which part of the window this position belongs to. Only "
             "how a specification lists its profiles; it changes no "
             "length, quantity or price.")
    edge = fields.Selection([
        ('top', 'Top'),
        ('bottom', 'Bottom'),
        ('sides', 'Sides'),
        ('all', 'All four'),
    ], help="Which edge(s). 'Sides' makes 2 pieces; 'All four' makes 2 of "
            "the width formula and 2 of the height formula.")
    default_length = fields.Char(
        string='Length Formula',
        help="Result in mm. Variables: W H PW PH CW CH N T. "
             "Functions: min max round ceil floor abs.")
    default_length_h = fields.Char(
        string='Height-edge Length Formula',
        help="Only used when Edge is 'All four': the formula for the two "
             "vertical pieces. Empty means use the Length Formula for all "
             "four.")
    default_angle = fields.Selection([
        ('45', '45°'),
        ('90', '90°'),
    ], default='90')
    default_qty = fields.Char(
        string='Quantity Formula', default='1',
        help="Multiplied by however many pieces the Edge implies.")
    # Defaults to True, and that direction is deliberate: a position
    # nobody has configured silently dropping out of the BOM is the
    # failure this flag exists to catch, so a hand-added position warns
    # until someone decides it is genuinely optional.
    is_required = fields.Boolean(
        string='Required', default=True,
        help="A design that needs this position but whose Profile "
             "Section has no line for it is reported by the checks. "
             "Uncheck for a piece that is genuinely optional, such as a "
             "bead on a sash profile that already has the glazing "
             "channel built in.")

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Profile Position code must be unique.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        positions = super().create(vals_list)
        if not self.pool._init:
            positions._sync_catalog()
        return positions

    def write(self, vals):
        res = super().write(vals)
        if 'scope' in vals and not self.pool._init:
            self._sync_catalog()
        return res

    def _sync_catalog(self):
        """A position that has a scope is in the catalog: every series
        gets a row for it, unused until someone maps it."""
        positions = self.filtered('scope')
        if positions:
            self.env['aw.window.template'].with_context(
                active_test=False).search([])._sync_catalog_lines(positions)

    @api.constrains('default_length', 'default_length_h', 'default_qty')
    def _check_formulas(self):
        """Rejected on save, with the reason, so a typo is caught by the
        person who made it rather than by the explosion engine later on
        someone else's quote (spec 6.1)."""
        for rec in self:
            for value, label in (
                (rec.default_length, _('Length Formula')),
                (rec.default_length_h, _('Height-edge Length Formula')),
                (rec.default_qty, _('Quantity Formula')),
            ):
                problem = validate_formula(value)
                if problem:
                    raise ValidationError(_(
                        "%(label)s on '%(name)s': %(problem)s",
                        label=label, name=rec.name, problem=problem))

    @api.model
    def _part_group_for(self, position):
        """The part group a seeded position belongs to, or False.

        Name first: 'Lock Bar' and the Palay Bead set sit in the sash
        scope but are a lock and beads. Then scope.
        """
        name = (position.name or '').lower()
        if 'lock' in name and 'bar' in name:
            return 'lock'
        if 'bead' in name:
            return 'beads'
        return GROUP_BY_SCOPE.get(position.scope, False)

    @api.model
    def _seed_part_groups(self):
        """Group the existing positions, FILLING ONLY EMPTY ones.

        A position somebody has grouped is left alone, so an edit in the
        UI survives an upgrade. Same caveat as the leaf-type seed:
        clearing a group back to empty is not a stable state, since
        empty is the signal for "never configured". Positions that match
        no rule stay empty and are listed under "Other".
        """
        for position in self.with_context(active_test=False).search(
                [('part_group', '=', False)]):
            group = self._part_group_for(position)
            if group:
                position.part_group = group

    @api.model
    def _seed_bom_defaults(self):
        """Give the seeded positions their BOM rules, once.

        Fill-only-if-empty, like every other seed here: a position that
        already has a scope is left exactly as it is, so tuning a length
        formula in the UI survives an upgrade. Positions added by hand
        are never touched and simply have no scope until someone gives
        them one -- which is what the "position has no scope" check
        reports.
        """
        for xmlid, values in BOM_DEFAULTS.items():
            position = self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)
            if position and not position.scope:
                position.write(values)

    @api.model
    def _seed_palay_bead_positions(self):
        """Seed Palay Bead by ADOPTING a position of that name, and
        reconcile the duplicates the first attempt created.

        The first version declared these as plain <record>s. The client
        had already created "Palay Bead - Top / Bottom / Sides" by hand,
        so the upgrade did not recognise them and made a second set --
        two of each, one carrying the seeded rules and one carrying
        whatever the Profile Sections actually point at. Seeding an
        open-ended, user-editable table by xmlid alone cannot see a
        record a user made, so matching on name is the only way to be
        idempotent against one.

        Which of a duplicate pair survives is decided by the section
        lines: re-pointing a live line is the one thing here that could
        change a BOM, so the record already in use wins and the unused
        one is removed. The seed xmlid is then repointed at the
        survivor, so every later seed and every ref() finds the record
        the shop is really using.
        """
        data = self.env['ir.model.data'].sudo()
        lines = self.env['aw.profile.section.line'].sudo()
        adopted = 0
        for xmlid, name, sequence, edge, length in PALAY_BEAD_SEED:
            # =ilike is an exact match that ignores case, so "Palay bead
            # - Top" is recognised as the same position rather than
            # quietly becoming a third one.
            candidates = self.with_context(active_test=False).search(
                [('name', '=ilike', name)], order='id')
            if not candidates:
                position = self.create({'name': name, 'sequence': sequence})
            else:
                in_use = set(lines.search(
                    [('position_id', 'in', candidates.ids)]
                ).mapped('position_id').ids)
                position = next(
                    (c for c in candidates if c.id in in_use), candidates[0])
                duplicates = candidates - position
                if duplicates:
                    lines.search(
                        [('position_id', 'in', duplicates.ids)]
                    ).write({'position_id': position.id})
                    data.search([
                        ('model', '=', 'aw.profile.position'),
                        ('res_id', 'in', duplicates.ids),
                    ]).unlink()
                    duplicates.unlink()
                    adopted += len(duplicates)

            # Fill-only-if-empty, as everywhere else here: a position the
            # client has already configured keeps its own rules.
            if not position.scope:
                position.write({
                    'scope': 'panel_opening', 'edge': edge,
                    'default_length': length, 'default_angle': '45',
                    'is_required': False,
                })

            record = data.search([
                ('module', '=', 'aw_fenestration_core'),
                ('name', '=', xmlid),
            ])
            values = {
                'module': 'aw_fenestration_core', 'name': xmlid,
                'model': 'aw.profile.position', 'res_id': position.id,
                'noupdate': True,
            }
            record.write(values) if record else data.create(values)
        return adopted

    @api.model
    def _seed_catalog(self):
        """Make the positions the one catalog, ONCE per database (rename,
        add the mesh parts, drop the stray, set which are required).

        Renames are by xmlid and only while the name is still the seeded
        one. Nothing is merged: every scope + part + edge already exists
        once. The unscoped "Palay - Hight" is dropped with its spec lines
        (the engine ignored it), unless something else still points at it.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(CATALOG_PARAM):
            return {}
        data = self.env['ir.model.data'].sudo()
        report = {'renamed': 0, 'added': 0, 'dropped': 0}
        for xmlid, (old, new) in CATALOG_RENAMES.items():
            position = self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)
            if position and position.name == old:
                position.name = new
                report['renamed'] += 1

        for xmlid, name, sequence, edge, length, required in \
                MESH_ADDON_POSITIONS:
            position = self.with_context(active_test=False).search(
                [('name', '=ilike', name)], limit=1)
            if not position:
                position = self.create({
                    'name': name, 'sequence': sequence,
                    'scope': 'mesh_attachment', 'part_group': 'fly_screen',
                    'edge': edge, 'default_length': length,
                    'default_angle': '45', 'is_required': required})
                report['added'] += 1
            if not data.search([('module', '=', 'aw_fenestration_core'),
                                ('name', '=', xmlid)]):
                data.create({
                    'module': 'aw_fenestration_core', 'name': xmlid,
                    'model': 'aw.profile.position', 'res_id': position.id,
                    'noupdate': True})

        stray = self.with_context(active_test=False).search(
            [('name', '=ilike', 'Palay - Hight'), ('scope', '=', False)])
        for position in stray:
            lines = self.env['aw.profile.section.line'].with_context(
                active_test=False).search([('position_id', '=', position.id)])
            try:
                with self.env.cr.savepoint():
                    lines.unlink()
                    position.unlink()
                report['dropped'] += 1
            except Exception as error:   # still referenced: leave it
                _logger.warning(
                    "aw_fenestration_core: could not drop '%s': %s",
                    position.name, error)

        for required, xmlids in REQUIRED_CATALOG.items():
            for xmlid in xmlids:
                position = self.env.ref(
                    'aw_fenestration_core.%s' % xmlid,
                    raise_if_not_found=False)
                if position:
                    position.is_required = required
        param.set_param(CATALOG_PARAM, '1')
        _logger.info("aw_fenestration_core: position catalog: %s", report)
        return report

    @api.model
    def _seed_required_flags(self):
        """Mark the optional positions, once per database.

        A Boolean has no "unset" state, so the fill-only-if-empty guard
        used everywhere else here has nothing to test: False is both
        "someone unticked this" and "never configured". Re-asserting the
        list every upgrade would therefore silently revert a UI edit,
        which is the exact trap the leaf-type seed was rewritten to
        avoid. A parameter marking the seed as done is the honest way to
        get one-shot semantics for a Boolean.

        The field defaults to True, so this only has to name the
        exceptions -- and a position added later is required until
        someone says otherwise, which is the safe direction.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(REQUIRED_SEEDED_PARAM):
            return
        for xmlid in OPTIONAL_POSITIONS:
            position = self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)
            if position:
                position.is_required = False
        param.set_param(REQUIRED_SEEDED_PARAM, '1')


REQUIRED_SEEDED_PARAM = 'aw_fenestration.position_required_seeded'
CATALOG_PARAM = 'aw_fenestration.position_catalog_seeded'

# xmlid -> (name it was seeded with, English catalog name). A position is
# renamed only if it still carries the old seeded name, so a name somebody
# chose is never overwritten. Names stay UNIQUE; the short label shown on a
# piece is the side only (see part_structure.side_of).
CATALOG_RENAMES = {
    'pos_frame_sides': ('Outer Frame - Sides', 'Outer Frame - Side'),
    'pos_palay_top': ('Palay - Top', 'Sash Frame - Top'),
    'pos_palay_bottom': ('Palay - Bottom', 'Sash Frame - Bottom'),
    'pos_palay_sides': ('Palay - Sides', 'Sash Frame - Side'),
    'pos_palay_bead_top': ('Palay Bead - Top', 'Sash Bead - Top'),
    'pos_palay_bead_bottom': ('Palay Bead - Bottom', 'Sash Bead - Bottom'),
    'pos_palay_bead_sides': ('Palay Bead - Sides', 'Sash Bead - Side'),
    'pos_bead_sides': ('Fixed Bead - Sides', 'Fixed Bead - Side'),
    'pos_mesh_all': ('Mesh - All Sides', 'Mesh Panel Frame - All Sides'),
    'pos_lock_bar': ('Lock Bar', 'Sash Lock Bar'),
}

# The mesh add-on parts, which the catalog did not have. xmlid, name,
# sequence, edge, length formula, required. Frame is required once a mesh
# is fitted; the bead is optional (a mesh frame often has none).
MESH_ADDON_POSITIONS = (
    ('pos_mesh_frame_top', 'Mesh Frame - Top', 80, 'top', 'PW - 10', True),
    ('pos_mesh_frame_bottom', 'Mesh Frame - Bottom', 82, 'bottom', 'PW - 10', True),
    ('pos_mesh_frame_sides', 'Mesh Frame - Side', 84, 'sides', 'PH - 10', True),
    ('pos_mesh_bead_top', 'Mesh Bead - Top', 86, 'top', 'PW - 40', False),
    ('pos_mesh_bead_bottom', 'Mesh Bead - Bottom', 88, 'bottom', 'PW - 40', False),
    ('pos_mesh_bead_sides', 'Mesh Bead - Side', 90, 'sides', 'PH - 40', False),
)

# Required means: a window that needs this scope and whose series has no
# used line for it is warned. The checks only look at scopes the layout
# actually demands, so dividers warn only with more than one panel and
# the mesh parts only when a mesh is fitted.
REQUIRED_CATALOG = {
    True: (
        'pos_frame_top', 'pos_frame_bottom', 'pos_frame_sides',
        'pos_palay_top', 'pos_palay_bottom', 'pos_palay_sides',
        'pos_divider_vertical', 'pos_divider_horizontal',
        'pos_interlock', 'pos_meeting_stile', 'pos_mesh_all',
        'pos_mesh_frame_top', 'pos_mesh_frame_bottom', 'pos_mesh_frame_sides',
    ),
    # Beads are optional: a sliding sash or a fixed light often has the
    # glazing channel built in, and warning on every such window teaches
    # people to ignore the warnings.
    False: (
        'pos_lock_bar',
        'pos_palay_bead_top', 'pos_palay_bead_bottom', 'pos_palay_bead_sides',
        'pos_bead_top', 'pos_bead_bottom', 'pos_bead_sides',
        'pos_mesh_bead_top', 'pos_mesh_bead_bottom', 'pos_mesh_bead_sides',
    ),
}

# xmlid, name, sequence, edge, length formula. Same deductions as Fixed
# Bead: it is the same bead doing the same job, in a sash rather than a
# fixed panel. Seeded by name (see _seed_palay_bead_positions), not as
# <record>s.
PALAY_BEAD_SEED = (
    ('pos_palay_bead_top', 'Palay Bead - Top', 62, 'top', 'PW - 40'),
    ('pos_palay_bead_bottom', 'Palay Bead - Bottom', 64, 'bottom', 'PW - 40'),
    ('pos_palay_bead_sides', 'Palay Bead - Sides', 66, 'sides', 'PH - 40'),
)

# Everything else is required. A sash profile often has the glazing
# channel built in, so a section with no Palay Bead line is normal.
OPTIONAL_POSITIONS = (
    'pos_palay_bead_top',
    'pos_palay_bead_bottom',
    'pos_palay_bead_sides',
    # Confirmed for the RE set only. A system with no lock bar line is
    # normal and must not warn on every opening panel.
    'pos_lock_bar',
)


# Placeholder rules from spec 6.2, marked [revisit] there: the deductions
# are plausible round numbers, not shop-measured ones.
BOM_DEFAULTS = {
    'pos_frame_top': {
        'scope': 'frame', 'edge': 'top',
        'default_length': 'W', 'default_angle': '45'},
    'pos_frame_bottom': {
        'scope': 'frame', 'edge': 'bottom',
        'default_length': 'W', 'default_angle': '45'},
    'pos_frame_sides': {
        'scope': 'frame', 'edge': 'sides',
        'default_length': 'H', 'default_angle': '45'},
    'pos_palay_top': {
        'scope': 'panel_opening', 'edge': 'top',
        'default_length': 'PW - 10', 'default_angle': '45'},
    'pos_palay_bottom': {
        'scope': 'panel_opening', 'edge': 'bottom',
        'default_length': 'PW - 10', 'default_angle': '45'},
    'pos_palay_sides': {
        'scope': 'panel_opening', 'edge': 'sides',
        'default_length': 'PH - 10', 'default_angle': '45'},
    'pos_bead_top': {
        'scope': 'panel_fixed', 'edge': 'top',
        'default_length': 'PW - 40', 'default_angle': '45'},
    'pos_bead_bottom': {
        'scope': 'panel_fixed', 'edge': 'bottom',
        'default_length': 'PW - 40', 'default_angle': '45'},
    'pos_bead_sides': {
        'scope': 'panel_fixed', 'edge': 'sides',
        'default_length': 'PH - 40', 'default_angle': '45'},
    'pos_mesh_all': {
        'scope': 'panel_mesh', 'edge': 'all',
        'default_length': 'PW - 10', 'default_length_h': 'PH - 10',
        'default_angle': '45'},
    'pos_divider_vertical': {
        'scope': 'junction_mullion',
        'default_length': 'CH', 'default_angle': '90'},
    'pos_divider_horizontal': {
        'scope': 'transom',
        'default_length': 'CW', 'default_angle': '90'},
    'pos_interlock': {
        'scope': 'junction_interlock',
        'default_length': 'PH - 10', 'default_angle': '90'},
    'pos_meeting_stile': {
        'scope': 'junction_meeting',
        'default_length': 'PH - 10', 'default_angle': '90'},
    # Edge is deliberately EMPTY, which is what makes one piece rather
    # than a pair: the lock bar sits on ONE side of the sash, and which
    # side is a per-panel decision (opposite the hinge), not a property
    # of the position. See aw.design._lock_edge().
    'pos_lock_bar': {
        'scope': 'panel_opening',
        'default_length': '0.8 * LS', 'default_angle': '90',
        'default_qty': '1'},
}
