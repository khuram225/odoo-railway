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
