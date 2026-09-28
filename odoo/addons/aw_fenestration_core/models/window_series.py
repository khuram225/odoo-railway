# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .formula import validate_formula

# Starting leaf types per seeded Series, applied ONCE per Series by
# _seed_default_leaf_types() below. Keyed by XML id so it doesn't depend
# on names, which are editable.
DEFAULT_LEAF_TYPES = {
    'window_series_dg_sliding': ('fixed', 'slider', 'mesh'),
    'window_series_sg_sliding': ('fixed', 'slider', 'mesh'),
    'window_series_dg_fix': ('fixed',),
    'window_series_sg_fix': ('fixed',),
    'window_series_curtain_wall_fix': ('fixed', 'casement', 'awning', 'hopper'),
    'window_series_tiltturn': ('fixed', 'tiltturn'),
    'window_series_casement_sg': ('fixed', 'casement', 'mesh'),
    'window_series_casement_dg': ('fixed', 'casement', 'mesh'),
}

# The 169 M1 job puts awnings and hoppers in bathrooms, so an Openable
# system has to host them. ADDED to whatever a system already allows,
# never replacing -- the same fill-only rule as everywhere else here.
EXTRA_LEAF_TYPES = {
    'window_series_casement_sg': ('awning', 'hopper'),
    'window_series_casement_dg': ('awning', 'hopper'),
}

# xmlid -> (name as seeded, new name, family code, system role).
# The rename only fires where the name is STILL the seeded one: a
# system someone has renamed by hand is theirs, not ours.
SYSTEM_IDENTITY = {
    'window_series_dg_sliding':
        ('Double Glaze Sliding', 'Double Glaze \u2013 Sliding', 'DG', 'sliding'),
    'window_series_dg_fix':
        ('Double Glaze Fix', 'Double Glaze \u2013 Fixed', 'DG', 'fixed'),
    'window_series_casement_dg':
        ('Casement Double Glaze', 'Double Glaze \u2013 Openable', 'DG',
         'openable'),
    'window_series_sg_sliding':
        ('Single Glaze Sliding', 'Single Glaze \u2013 Sliding', 'SG', 'sliding'),
    'window_series_sg_fix':
        ('Single Glaze Fix', 'Single Glaze \u2013 Fixed', 'SG', 'fixed'),
    'window_series_casement_sg':
        ('Casement Single Glaze', 'Single Glaze \u2013 Openable', 'SG',
         'openable'),
    # [revisit] Single glaze tilt & turn: the client has only confirmed
    # a double-glazed one.
    'window_series_tiltturn':
        ('Tilt & Turn Series', 'Tilt & Turn', 'DG', 'tiltturn'),
    'window_series_curtain_wall_fix':
        ('Curtain Wall Fix', 'Curtain Wall', 'CW', 'fixed'),
}

FAMILY_SEEDED_PARAM = 'aw_fenestration.series_family_seeded'


class AwWindowSeries(models.Model):
    """A specific product family: Double Glaze Sliding, Single Glaze Fix,
    Curtain Wall Fix, Tilt & Turn Series, Casement Single Glaze, etc.

    Series is now the only classification layer -- the intermediate
    aw.window.type/aw.window.kind layers were dropped per the structure
    design consolidation. leaf_type_ids replaces that whole chain
    directly: which leaf mechanisms (Fixed, Slider, Casement, ...) this
    Series can host, a real Many2many to aw.leaf.type instead of an
    inherited-through-two-models Kind lookup.
    """
    _name = 'aw.window.series'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Series'
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True, help="Short code, e.g. BOX, COLLAR, ROUND, GSL, HINGED, CURTAIN")
    # The UI calls this a Profile system; the model name is unchanged
    # because renaming it would break every stored reference and the
    # whole BOM chain for the sake of a label.
    family_id = fields.Many2one(
        'aw.window.family', string='Glazing Family', tracking=True,
        ondelete='restrict', index=True)
    system_role = fields.Selection([
        ('sliding', 'Sliding'),
        ('openable', 'Openable'),
        ('tiltturn', 'Tilt & Turn'),
        ('fixed', 'Fixed'),
    ], string='System Role', tracking=True,
        help="What this system is FOR, which is how a design picks one "
             "from the panels that have been drawn. Without it the "
             "choice would have to be guessed from the name.")
    leaf_type_ids = fields.Many2many('aw.leaf.type', tracking=True,
        help="Which leaf mechanisms this Series can host.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')

    @api.model
    def _seed_default_leaf_types(self):
        """Give each seeded Series a starting set of leaf types, once.

        Called from a <function> in data/window_series_data.xml, which is
        an updatable block, so this runs on install and on every upgrade.
        That is safe, and deliberate, because of the guard below: a Series
        that already has leaf types is skipped entirely. The whole point
        of leaf types being data-driven is that they're editable, so an
        upgrade must never overwrite what someone set in the UI.

        This replaced a plain record-based data file that re-asserted the
        full mapping on every upgrade and would have silently reverted any
        such edit.

        One consequence worth knowing: deliberately clearing a Series'
        leaf types to none is not a stable state -- the next upgrade will
        refill it from here, because "empty" is exactly the signal this
        uses for "never configured". Archive the Series instead if it
        shouldn't be used.
        """
        leaf_types = {}
        for code in {c for codes in DEFAULT_LEAF_TYPES.values() for c in codes}:
            record = self.env.ref(
                'aw_fenestration_core.leaf_type_%s' % code,
                raise_if_not_found=False)
            if record:
                leaf_types[code] = record.id

        for series_xmlid, codes in DEFAULT_LEAF_TYPES.items():
            series = self.env.ref(
                'aw_fenestration_core.%s' % series_xmlid,
                raise_if_not_found=False)
            if not series or series.leaf_type_ids:
                continue
            ids = [leaf_types[c] for c in codes if c in leaf_types]
            if ids:
                series.leaf_type_ids = [(6, 0, ids)]

    # -- 6.4 deductions and limits ----------------------------------------
    # Placeholders, marked [revisit] in the spec: plausible round numbers,
    # not shop-measured ones. A limit of 0 means "not checked", so a
    # Series nobody has tuned never raises a false alarm.
    default_glass_spec_id = fields.Many2one(
        'aw.glass.spec', string='Default Glass', tracking=True,
        ondelete='restrict',
        help="A new design in this Series starts with this glass. Only "
             "fills a design that has none, so it never overrides a "
             "choice someone has made.")

    glass_fixed_w = fields.Char(string='Fixed Glass Width', default='PW - 60')
    glass_fixed_h = fields.Char(string='Fixed Glass Height', default='PH - 60')
    glass_sash_w = fields.Char(string='Sash Glass Width', default='PW - 80')
    glass_sash_h = fields.Char(string='Sash Glass Height', default='PH - 80')
    mesh_w = fields.Char(string='Mesh Width', default='PW - 10')
    mesh_h = fields.Char(string='Mesh Height', default='PH - 10')
    max_panel_w = fields.Float(
        string='Max Panel Width (mm)', help="0 means not checked.")
    max_panel_h = fields.Float(
        string='Max Panel Height (mm)', help="0 means not checked.")
    max_panel_kg = fields.Float(
        string='Max Panel Weight (kg)', help="0 means not checked.")

    product_category_id = fields.Many2one(
        'product.category', string='Profile Product Category',
        help="Where this series's profile products live in the Inventory "
             "category tree, e.g. Fenestration / Profiles / Box Series.")

    profile_section_ids = fields.One2many(
        'aw.profile.section', 'window_type_id', string='Profile Sections')
    hardware_set_ids = fields.One2many(
        'aw.hardware.set', 'window_type_id', string='Hardware Sets')
    template_ids = fields.One2many(
        'aw.window.template', 'window_type_id', string='Templates')

    profile_section_count = fields.Integer(compute='_compute_counts')
    hardware_set_count = fields.Integer(compute='_compute_counts')
    template_count = fields.Integer(compute='_compute_counts')

    @api.depends('profile_section_ids', 'hardware_set_ids', 'template_ids')
    def _compute_counts(self):
        for rec in self:
            rec.profile_section_count = len(rec.profile_section_ids)
            rec.hardware_set_count = len(rec.hardware_set_ids)
            rec.template_count = len(rec.template_ids)

    def _view_related(self, model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('window_type_id', '=', self.id)],
            'context': {'default_window_type_id': self.id},
        }

    def action_view_profile_sections(self):
        return self._view_related('aw.profile.section', 'Profile Sections')

    def action_view_hardware_sets(self):
        return self._view_related('aw.hardware.set', 'Hardware Sets')

    def action_view_templates(self):
        return self._view_related('aw.window.template', 'Templates')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Window Series code must be unique.'),
    ]

    @api.constrains('glass_fixed_w', 'glass_fixed_h', 'glass_sash_w',
                    'glass_sash_h', 'mesh_w', 'mesh_h')
    def _check_deduction_formulas(self):
        for rec in self:
            for value, label in (
                (rec.glass_fixed_w, 'Fixed Glass Width'),
                (rec.glass_fixed_h, 'Fixed Glass Height'),
                (rec.glass_sash_w, 'Sash Glass Width'),
                (rec.glass_sash_h, 'Sash Glass Height'),
                (rec.mesh_w, 'Mesh Width'),
                (rec.mesh_h, 'Mesh Height'),
            ):
                problem = validate_formula(value)
                if problem:
                    raise ValidationError(_(
                        "%(label)s on '%(name)s': %(problem)s",
                        label=label, name=rec.name, problem=problem))

    # ------------------------------------------------------------------
    @api.model
    def _seed_family_and_names(self):
        """Give each seeded system its family, role and new name, once.

        Guarded by a parameter rather than fill-only-if-empty because
        the rename has no "empty" state to test -- a name is always
        set. The name is only changed where it still EQUALS the seeded
        one, so a system someone has renamed keeps their name and still
        gets its family and role.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(FAMILY_SEEDED_PARAM):
            return 0

        families = {
            family.code: family
            for family in self.env['aw.window.family'].with_context(
                active_test=False).search([])}
        leaf_types = {
            leaf.code.lower(): leaf
            for leaf in self.env['aw.leaf.type'].with_context(
                active_test=False).search([]) if leaf.code}

        touched = 0
        for xmlid, (seeded, new_name, code, role) in SYSTEM_IDENTITY.items():
            series = self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)
            if not series:
                continue
            values = {}
            if series.name == seeded:
                values['name'] = new_name
            if not series.family_id and families.get(code):
                values['family_id'] = families[code].id
            if not series.system_role:
                values['system_role'] = role
            if values:
                series.write(values)
                touched += 1

        # Awning and hopper on the Openable systems, added never removed.
        for xmlid, codes in EXTRA_LEAF_TYPES.items():
            series = self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)
            if not series:
                continue
            wanted = self.env['aw.leaf.type']
            for code in codes:
                leaf = leaf_types.get(code)
                if leaf and leaf not in series.leaf_type_ids:
                    wanted |= leaf
            if wanted:
                series.leaf_type_ids = [(4, leaf.id) for leaf in wanted]

        param.set_param(FAMILY_SEEDED_PARAM, '1')
        return touched
