# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .formula import validate_formula


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

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Profile Position code must be unique.'),
    ]

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
    # Same deductions as Fixed Bead: it is the same bead doing the same
    # job, just in an opening sash rather than a fixed panel.
    'pos_palay_bead_top': {
        'scope': 'panel_opening', 'edge': 'top',
        'default_length': 'PW - 40', 'default_angle': '45'},
    'pos_palay_bead_bottom': {
        'scope': 'panel_opening', 'edge': 'bottom',
        'default_length': 'PW - 40', 'default_angle': '45'},
    'pos_palay_bead_sides': {
        'scope': 'panel_opening', 'edge': 'sides',
        'default_length': 'PH - 40', 'default_angle': '45'},
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
}
