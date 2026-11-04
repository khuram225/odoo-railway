# -*- coding: utf-8 -*-
"""Multi-vendor rate lists with paste-in entry.

A vendor's sheet layout is described once (aw.vendor.layout). A rate list
(aw.vendor.rate.list) is one entry of that vendor's prices: paste rows,
type them, or prefill them from the rates in force. Applying it writes
ordinary aw.profile.rate rows -- vendor, finish, thickness, price per
foot, valid from the list's date -- and the existing validity chain
closes whatever each one replaces.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .finish_names import norm_name
from .glass_paste import (
    norm_type, parse_glass_paste_report, parse_thickness)
from .rate_paste import normalise_code, normalise_text, parse_paste

_logger = logging.getLogger(__name__)

MAX_FINISH_COLUMNS = 10
THICKNESS_ALIASES = ('NOR', '1.6MM', '2MM', '1.4MM', '2.5MM', '3MM',
                     '6MM', '3.8MM', '1.90MM', '1.80MM')
PREMIUM_FIX_PARAM = 'aw_fenestration.premium_layout_fixed'
PREMIUM_FIX_REPORT_PARAM = 'aw_fenestration.premium_layout_fix_report'
PREMIUM_PARAM = 'aw_fenestration.premium_layout_seeded'
PREMIUM_REPORT_PARAM = 'aw_fenestration.premium_layout_report'
CHAWLA_PARAM = 'aw_fenestration.chawla_layout_seeded'
CHAWLA_REPORT_PARAM = 'aw_fenestration.chawla_layout_report'
# Chawla's sheet, with the headers exactly as it has them: profile_code and
# thickness, then one column per finish. Each rate header is matched to the
# finish value of that name, ignoring case and spacing.
CHAWLA_CODE_HEADER = 'profile_code'
CHAWLA_THICKNESS_HEADER = 'thickness'
CHAWLA_RATE_COLUMNS = (
    ('natural', 'Natural'),
    ('h23_pc_ral', 'H23 PC RAL'),
    ('brown_pc_sahara', 'Brown PC Sahara'),
    ('black_multi_ss_dull', 'Black Multi SS Dull'),
    ('designer', 'Designer'),
    ('c_shine', 'C-Shine'),
)
CHAWLA_THICKNESS_ALIASES = (
    'Nor', '1.4MM', '1.6MM', '2MM', '2.2MM', '3MM', '3.2MM')
LEGACY_VENDOR_PARAM = 'aw_fenestration.legacy_rate_vendor_id'


class AwVendorLayout(models.Model):
    """How one vendor's rate sheet is laid out, set once."""
    _name = 'aw.vendor.layout'
    _description = 'Vendor Rate Sheet Layout'
    _rec_name = 'vendor_id'

    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True)
    column_ids = fields.One2many(
        'aw.vendor.layout.column', 'layout_id', string='Columns', copy=True)
    thickness_alias_ids = fields.One2many(
        'aw.vendor.thickness.alias', 'layout_id', string='Thickness aliases',
        copy=True)
    note = fields.Char()

    @api.constrains('vendor_id')
    def _check_one_layout(self):
        for layout in self:
            if self.search_count([('vendor_id', '=', layout.vendor_id.id),
                                  ('id', '!=', layout.id)]):
                raise ValidationError(_(
                    "%s already has a layout.", layout.vendor_id.display_name))

    @api.constrains('column_ids')
    def _check_columns(self):
        for layout in self:
            kinds = layout.column_ids.mapped('kind')
            if kinds.count('code') != 1:
                raise ValidationError(_(
                    "A layout needs exactly one Code column."))
            if kinds.count('finish') > MAX_FINISH_COLUMNS:
                raise ValidationError(_(
                    "At most %s rate columns.", MAX_FINISH_COLUMNS))

    def _kinds(self):
        self.ensure_one()
        return self.column_ids.sorted('sequence').mapped('kind')

    def _register_hook(self):
        """Seed Premium's layout once every module has loaded (a partner
        created while modules are still loading can miss NOT NULL columns
        that later modules add). Savepoint, and logged rather than raised:
        this also runs on every ordinary start."""
        super()._register_hook()
        # Each seed in its own savepoint: one failing must not undo or
        # block the other.
        for name, seeds in (
                ('Premium', ('_seed_premium_layout', '_fix_premium_layout')),
                ('Chawla', ('_seed_chawla_layout',))):
            try:
                with self.env.cr.savepoint():
                    for seed in seeds:
                        getattr(self, seed)()
            except Exception:
                _logger.exception(
                    "aw_fenestration_core: %s seed failed", name)

    @api.model
    def _seed_chawla_layout(self):
        """Chawla's rate sheet layout, CREATE-IF-MISSING and ONCE.

        The partner is the one the legacy rates already belong to; a
        partner is created only if there is none. If Chawla already has a
        layout nothing is created or changed.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(CHAWLA_PARAM):
            return None
        report = {'partner': None, 'layout': None, 'finishes_set': [],
                  'finishes_unmapped': [], 'thickness_set': [],
                  'thickness_unmapped': []}
        Partner = self.env['res.partner'].with_context(active_test=False)
        partner = self.env['aw.profile.rate']._legacy_vendor()
        if partner:
            report['partner'] = 'reused: %s (id %s)' % (
                partner.name, partner.id)
        else:
            partner = Partner.search([('name', 'ilike', 'chawla')], limit=1)
            if partner:
                report['partner'] = 'reused: %s (id %s)' % (
                    partner.name, partner.id)
            else:
                partner = Partner.create(
                    {'name': 'Chawla', 'is_company': True})
                report['partner'] = 'created: Chawla (id %s)' % partner.id

        if self.with_context(active_test=False).search_count(
                [('vendor_id', '=', partner.id)]):
            report['layout'] = 'already exists; nothing created'
        else:
            finish_attr = self.env.ref(
                'aw_fenestration_core.aw_attribute_finish')
            thick_attr = self.env.ref(
                'aw_fenestration_core.aw_attribute_thickness')

            def squash(text):
                return ''.join((text or '').lower().split())

            columns = [
                (0, 0, {'sequence': 10, 'kind': 'code',
                        'header': CHAWLA_CODE_HEADER}),
                (0, 0, {'sequence': 20, 'kind': 'thickness',
                        'header': CHAWLA_THICKNESS_HEADER}),
            ]
            for index, (header, finish_name) in enumerate(
                    CHAWLA_RATE_COLUMNS, start=1):
                finish = finish_attr.value_ids.filtered(
                    lambda v, w=squash(finish_name.replace('_', ' ')):
                    squash(v.name) == w)[:1]
                columns.append((0, 0, {
                    'sequence': 20 + 10 * index, 'header': header,
                    'kind': 'finish',
                    'finish_id': finish.id if finish else False}))
                if finish:
                    report['finishes_set'].append(
                        '%s -> %s' % (header, finish.name))
                else:
                    report['finishes_unmapped'].append(header)
            aliases = []
            for alias in CHAWLA_THICKNESS_ALIASES:
                if alias.upper() == 'NOR':
                    # Chawla's own default thickness is Normal, not the
                    # Standard that Premium's NOR maps to.
                    value = thick_attr.value_ids.filtered(
                        lambda v: v.name == 'Normal')[:1]
                else:
                    value = self._thickness_for_alias(thick_attr, alias)
                if value:
                    aliases.append((0, 0, {
                        'alias': alias, 'thickness_id': value.id}))
                    report['thickness_set'].append(
                        '%s -> %s' % (alias, value.name))
                else:
                    report['thickness_unmapped'].append(alias)
            layout = self.create({
                'vendor_id': partner.id, 'column_ids': columns,
                'thickness_alias_ids': aliases,
                'note': 'Seeded from the Chawla price list.'})
            report['layout'] = 'created (id %s)' % layout.id

        param.set_param(CHAWLA_PARAM, '1')
        param.set_param(CHAWLA_REPORT_PARAM, repr(report))
        _logger.info("aw_fenestration_core: Chawla seed: %s", report)
        return report

    PREMIUM_RATE_HEADERS = (
        'DULL', 'BRO', 'H.23', 'RAL P.C', 'BLACK', 'SHARA', 'WOOD')

    @api.model
    def _premium_finishes(self, finish_attr):
        """DULL -> Natural, H.23 -> H23 PC RAL, SHARA -> Brown PC Sahara,
        matched on the finish value's name ignoring case and spacing."""
        def squash(text):
            return ''.join((text or '').lower().split())

        def find(test):
            return finish_attr.value_ids.filtered(
                lambda v: test(squash(v.name)))[:1]

        return {
            'DULL': find(lambda n: n == 'natural'),
            'H.23': find(lambda n: n.startswith('h23')),
            'SHARA': find(lambda n: n == 'brownpcsahara'),
        }

    @api.model
    def _fix_premium_layout(self):
        """A Premium layout that exists but has no rate columns gets them,
        ONCE: the seed leaves an existing layout alone, and this one was
        made by hand with the code, thickness and series columns only, so
        no pasted number could be read as a rate. Only what is missing is
        added; no column or alias that exists is changed."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PREMIUM_FIX_PARAM):
            return None
        report = {'layouts_fixed': [], 'columns_added': [],
                  'aliases_added': []}
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        thick_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        finishes = self._premium_finishes(finish_attr)
        for layout in self.with_context(active_test=False).search(
                [('vendor_id.name', 'ilike', 'premium')]):
            if not layout._finish_columns():
                start = max(layout.column_ids.mapped('sequence') or [0])
                vals = []
                for index, header in enumerate(self.PREMIUM_RATE_HEADERS, 1):
                    finish = finishes.get(header)
                    vals.append((0, 0, {
                        'sequence': start + 10 * index, 'header': header,
                        'kind': 'finish',
                        'finish_id': finish.id if finish else False}))
                    report['columns_added'].append(
                        '%s -> %s' % (header, finish.name if finish
                                      else 'no finish set'))
                layout.write({'column_ids': vals})
                report['layouts_fixed'].append(layout.id)
            have = {a.alias.upper() for a in layout.thickness_alias_ids}
            for alias in THICKNESS_ALIASES:
                if alias.upper() in have:
                    continue
                value = self._thickness_for_alias(thick_attr, alias)
                if value:
                    layout.write({'thickness_alias_ids': [(0, 0, {
                        'alias': alias, 'thickness_id': value.id})]})
                    report['aliases_added'].append(
                        '%s -> %s' % (alias, value.name))
        param.set_param(PREMIUM_FIX_PARAM, '1')
        param.set_param(PREMIUM_FIX_REPORT_PARAM, repr(report))
        _logger.info("aw_fenestration_core: Premium layout fix: %s", report)
        return report

    @api.model
    def _thickness_for_alias(self, thick_attr, alias):
        values = thick_attr.value_ids
        if alias == 'NOR':
            return values.filtered(lambda v: v.name == 'Standard')[:1]
        try:
            wanted = float(alias.upper().replace('MM', ''))
        except ValueError:
            return values.browse()
        for value in values:
            try:
                if float((value.name or '').upper().replace(
                        'MM', '')) == wanted:
                    return value
            except ValueError:
                continue
        return values.browse()

    @api.model
    def _seed_premium_layout(self):
        """Premium and its rate sheet layout, CREATE-IF-MISSING and ONCE.

        Nothing that exists is changed: a partner whose name contains
        "premium" (archived included) is reused, and if Premium already
        has a layout nothing is created at all. The rate columns whose
        finish is not known are left as Ignore columns with the vendor's
        header, so a pasted row still lines up; the user turns each into a
        rate column by choosing its finish in the UI.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PREMIUM_PARAM):
            return None
        report = {'partner': None, 'layout': None, 'finishes_set': [],
                  'finishes_unmapped': [], 'thickness_set': [],
                  'thickness_unmapped': []}
        Partner = self.env['res.partner'].with_context(active_test=False)
        partner = Partner.search([('name', 'ilike', 'premium')], limit=1)
        if partner:
            report['partner'] = 'reused: %s (id %s)' % (
                partner.name, partner.id)
        else:
            partner = Partner.create({'name': 'Premium', 'is_company': True})
            report['partner'] = 'created: Premium (id %s)' % partner.id

        if self.with_context(active_test=False).search_count(
                [('vendor_id', '=', partner.id)]):
            report['layout'] = 'already exists; nothing created'
        else:
            finish_attr = self.env.ref(
                'aw_fenestration_core.aw_attribute_finish')
            thick_attr = self.env.ref(
                'aw_fenestration_core.aw_attribute_thickness')

            finishes = self._premium_finishes(finish_attr)
            columns = [
                (0, 0, {'sequence': 10, 'kind': 'code', 'header': 'SEC.NO.'}),
                (0, 0, {'sequence': 20, 'kind': 'thickness',
                        'header': 'Thickness'}),
                (0, 0, {'sequence': 30, 'kind': 'series',
                        'header': 'Series'}),
            ]
            for index, header in enumerate(
                    ('DULL', 'BRO', 'H.23', 'RAL P.C', 'BLACK', 'SHARA',
                     'WOOD')):
                finish = finishes.get(header)
                columns.append((0, 0, {
                    'sequence': 40 + 10 * index, 'header': header,
                    'kind': 'finish',
                    'finish_id': finish.id if finish else False}))
                if finish:
                    report['finishes_set'].append(
                        '%s -> %s' % (header, finish.name))
                else:
                    report['finishes_unmapped'].append(header)

            def thickness_for(alias):
                return self._thickness_for_alias(thick_attr, alias)

            aliases = []
            for alias in THICKNESS_ALIASES:
                value = thickness_for(alias)
                if value:
                    aliases.append((0, 0, {
                        'alias': alias, 'thickness_id': value.id}))
                    report['thickness_set'].append(
                        '%s -> %s' % (alias, value.name))
                else:
                    report['thickness_unmapped'].append(alias)
            layout = self.create({
                'vendor_id': partner.id, 'column_ids': columns,
                'thickness_alias_ids': aliases,
                'note': 'Seeded; map the unmapped rate columns in the UI.'})
            report['layout'] = 'created (id %s)' % layout.id

        param.set_param(PREMIUM_PARAM, '1')
        param.set_param(PREMIUM_REPORT_PARAM, repr(report))
        _logger.info("aw_fenestration_core: Premium seed: %s", report)
        return report

    unmapped_note = fields.Char(compute='_compute_unmapped_note')

    @api.depends('column_ids.kind', 'column_ids.finish_id',
                 'column_ids.header')
    def _compute_unmapped_note(self):
        for layout in self:
            missing = layout.column_ids.filtered(
                lambda c: c.kind == 'finish' and not c.finish_id)
            layout.unmapped_note = _(
                "These columns have no finish and their prices will be "
                "skipped: %s", ', '.join(
                    c.header or '?' for c in missing)) if missing else ''

    def _finish_columns(self):
        """The rate columns, in order."""
        self.ensure_one()
        return self.column_ids.sorted('sequence').filtered(
            lambda c: c.kind == 'finish')


class AwVendorLayoutColumn(models.Model):
    _name = 'aw.vendor.layout.column'
    _description = 'Vendor Rate Sheet Column'
    _order = 'sequence, id'

    layout_id = fields.Many2one(
        'aw.vendor.layout', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('code', 'Code'),
        ('thickness', 'Thickness'),
        ('series', 'Series'),
        ('finish', 'Rate for a finish'),
        ('skip', 'Ignore'),
    ], required=True, default='finish')
    header = fields.Char(
        help="What the vendor calls the column, e.g. DULL or SEC.NO.")
    # A rate column may have no finish yet: its numbers are read and kept,
    # and Apply says that column was not applied until a finish is set.
    finish_id = fields.Many2one(
        'product.attribute.value', string='Finish',
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_finish').id)])

    def _add_header_name(self):
        """Picking a finish adds the column's header to the finish's
        names, for this layout's vendor."""
        for column in self:
            if (column.kind == 'finish' and column.finish_id
                    and column.header):
                column.finish_id._aw_add_name(
                    column.header, column.layout_id.vendor_id)

    @api.model_create_multi
    def create(self, vals_list):
        columns = super().create(vals_list)
        columns._add_header_name()
        return columns

    def write(self, vals):
        result = super().write(vals)
        if {'finish_id', 'header', 'kind'} & set(vals):
            self._add_header_name()
        return result

    def action_new_finish(self):
        """A new finish named after the vendor's own header (WOOD),
        owned by this vendor and mapped to this column."""
        self.ensure_one()
        if not self.header:
            raise UserError(_("Give the column a header first."))
        attribute = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        finish = attribute.value_ids.filtered(
            lambda v: norm_name(v.name) == norm_name(self.header))[:1]
        if not finish:
            finish = self.env['product.attribute.value'].create({
                'attribute_id': attribute.id,
                'name': self.header.strip().title(),
                'aw_owner_vendor_id': self.layout_id.vendor_id.id})
        self.finish_id = finish
        return True


class AwVendorThicknessAlias(models.Model):
    _name = 'aw.vendor.thickness.alias'
    _description = 'Vendor Thickness Alias'

    layout_id = fields.Many2one(
        'aw.vendor.layout', required=True, ondelete='cascade', index=True)
    alias = fields.Char(required=True, help='e.g. NOR or 1.6MM')
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Our thickness', required=True,
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_thickness').id)])


class AwVendorAlias(models.Model):
    """A vendor's code (and thickness) mapped to one of our profiles,
    saved the first time somebody picks the product for an unmatched row."""
    _name = 'aw.vendor.alias'
    _description = 'Vendor Profile Alias'

    vendor_id = fields.Many2one(
        'res.partner', required=True, index=True, ondelete='cascade')
    code_norm = fields.Char(
        string='Vendor code (normalised)', required=True, index=True)
    thickness_text = fields.Char(
        help="Normalised thickness text this applies to; empty applies to "
             "every thickness.")
    product_tmpl_id = fields.Many2one(
        'product.template', string='Profile', required=True,
        ondelete='cascade')
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness',
        help="Optional: also fixes the thickness value.")


class AwVendorRateList(models.Model):
    _name = 'aw.vendor.rate.list'
    _description = 'Vendor Rate List'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    kind = fields.Selection([
        ('profile', 'Profiles'), ('glass', 'Glass'),
    ], required=True, default='profile', index=True,
        help="What the list prices. A glass list has one rate column, in "
             "PKR per sqft, and no finish.")
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, tracking=True,
        index=True)
    date = fields.Date(
        string='Effective date', required=True, tracking=True,
        default=fields.Date.context_today)
    note = fields.Char()
    state = fields.Selection([
        ('draft', 'Draft'), ('applied', 'Applied'),
    ], default='draft', required=True, tracking=True)
    line_ids = fields.One2many(
        'aw.vendor.rate.list.line', 'list_id', string='Lines')
    paste_text = fields.Text(
        help="Rows copied from the vendor's sheet, tab separated, with or "
             "without the header row.")
    fill_series = fields.Char(
        string='Series',
        help="The vendor's series name, for Fill from current rates.")
    layout_id = fields.Many2one(
        'aw.vendor.layout', compute='_compute_layout')
    columns_legend = fields.Char(compute='_compute_layout')
    # What the grid on the form draws: one entry per rate column of the
    # layout, in order, read each time the list is opened. Display only.
    grid_meta = fields.Json(compute='_compute_grid_meta')
    line_count = fields.Integer(compute='_compute_counts')
    unmatched_count = fields.Integer(compute='_compute_counts')
    need_product_count = fields.Integer(compute='_compute_counts')
    need_thickness_count = fields.Integer(compute='_compute_counts')
    unknown_thickness_count = fields.Integer(compute='_compute_counts')
    need_finish_count = fields.Integer(compute='_compute_counts')
    need_glass_type_count = fields.Integer(compute='_compute_counts')
    need_summary = fields.Char(compute='_compute_counts')
    conflict_count = fields.Integer(compute='_compute_counts')
    # The grid's own field is a computed, so Odoo gives it readonly=True
    # and a widget cannot tell that from "this list may not be edited".
    # The rule lives here instead: rows can be added and removed on a draft.
    grid_editable = fields.Boolean(compute='_compute_grid_editable')

    @api.depends('state')
    def _compute_grid_editable(self):
        for rec in self:
            rec.grid_editable = rec.state == 'draft'

    @api.depends('name', 'note')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                '%s (%s)' % (rec.name, rec.note) if rec.note
                else rec.name or '')

    @api.depends('vendor_id', 'date')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s - %s' % (
                rec.vendor_id.display_name or '', rec.date or '')

    @api.depends('vendor_id', 'kind')
    def _compute_layout(self):
        for rec in self:
            if rec.kind == 'glass':
                rec.layout_id = False
                rec.columns_legend = _('Rate 1 = PKR per sqft')
                continue
            layout = self.env['aw.vendor.layout'].search(
                [('vendor_id', '=', rec.vendor_id.id)], limit=1)
            rec.layout_id = layout
            if not layout:
                rec.columns_legend = _('No layout for this vendor')
            else:
                columns = layout._finish_columns()
                rec.columns_legend = ' | '.join(
                    'Rate %s = %s (%s)' % (
                        index, column.header or column.finish_id.name,
                        column.finish_id.name or _('no finish set'))
                    for index, column in enumerate(columns, start=1)
                ) or _('This layout has no rate columns')

    @api.depends('vendor_id', 'kind')
    def _compute_grid_meta(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles',
            raise_if_not_found=False)
        for rec in self:
            if rec.kind == 'glass':
                rec.grid_meta = {
                    'kind': 'glass', 'has_layout': True,
                    'thickness_options': [], 'series_options': [],
                    'glass_type_options': self.env['aw.glass.type'].search(
                        []).mapped('name'),
                    'columns': [{'index': 1, 'header': 'PKR / sqft',
                                 'finish': '', 'mapped': True}],
                }
                continue
            layout = self.env['aw.vendor.layout'].search(
                [('vendor_id', '=', rec.vendor_id.id)], limit=1)
            rec.grid_meta = {
                'thickness_options': sorted(
                    {a.alias for a in layout.thickness_alias_ids if a.alias}
                ) if layout else [],
                'series_options': rec._series_seen(),
                'has_layout': bool(layout),
                'profile_category_id': category.id if category else False,
                'columns': [{
                    'index': index,
                    'header': column.header or column.finish_id.name or '',
                    'finish': column.finish_id.name or '',
                    'mapped': bool(column.finish_id),
                } for index, column in enumerate(
                    layout._finish_columns(), start=1)] if layout else [],
            }

    def _series_seen(self):
        """Series names already seen for this vendor, on any of its rate
        lists or rates."""
        self.ensure_one()
        if not self.vendor_id:
            return []
        names = set()
        for model, domain, field in (
                ('aw.vendor.rate.list.line',
                 [('list_id.vendor_id', '=', self.vendor_id.id)], 'series'),
                ('aw.profile.rate',
                 [('vendor_id', '=', self.vendor_id.id)], 'vendor_series')):
            for (value,) in self.env[model].sudo().with_context(
                    active_test=False)._read_group(
                        domain + [(field, '!=', False)], [field]):
                if value:
                    names.add(value)
        return sorted(names, key=str.lower)

    @api.depends('line_ids.product_tmpl_id', 'line_ids.problem',
                 'line_ids.cells_conflict', 'line_ids.need')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.unmatched_count = len(rec.line_ids.filtered('problem'))
            by_need = rec.line_ids.mapped('need')
            rec.need_product_count = by_need.count('product')
            rec.need_thickness_count = by_need.count('thickness')
            rec.unknown_thickness_count = by_need.count('unknown_thickness')
            rec.need_finish_count = by_need.count('finish')
            rec.need_glass_type_count = by_need.count('glass_type')
            if rec.kind == 'glass':
                rec.need_summary = _(
                    "%(types)s need a glass type, %(unknown)s unknown "
                    "thickness",
                    types=rec.need_glass_type_count,
                    unknown=rec.unknown_thickness_count) if any(by_need) \
                    else ''
                rec.conflict_count = len(
                    rec.line_ids.filtered('cells_conflict'))
                continue
            rec.need_summary = _(
                "%(product)s need a product, %(thickness)s need a "
                "thickness, %(unknown)s unknown thickness, %(finish)s need "
                "a finish",
                product=rec.need_product_count,
                thickness=rec.need_thickness_count,
                unknown=rec.unknown_thickness_count,
                finish=rec.need_finish_count) if any(by_need) else ''
            rec.conflict_count = len(
                rec.line_ids.filtered('cells_conflict'))

    def _require_layout(self):
        self.ensure_one()
        if not self.layout_id:
            raise UserError(_(
                "%s has no rate sheet layout yet. Describe its columns "
                "under Vendor Layouts first.", self.vendor_id.display_name))
        return self.layout_id

    # ------------------------------------------------------------ entry 1
    def action_parse_paste(self):
        """Paste box -> lines, in the vendor's layout."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("An applied list is read only."))
        if self.kind == 'glass':
            return self._parse_glass_paste()
        layout = self._require_layout()
        rows = parse_paste(self.paste_text, layout._kinds())
        if not rows:
            columns = layout.column_ids.sorted('sequence')
            described = ', '.join(
                '%s = %s' % (c.header or '?', dict(
                    c._fields['kind'].selection).get(c.kind, c.kind))
                for c in columns) or _('no columns')
            if not layout._finish_columns():
                raise UserError(_(
                    "%(vendor)s's layout has no rate columns, so no number "
                    "in a pasted row can be read as a rate. Its columns: "
                    "%(columns)s. Add the rate columns (one per finish) "
                    "under Vendor Layouts.",
                    vendor=self.vendor_id.display_name, columns=described))
            raise UserError(_(
                "No row has a number under any of the layout's rate "
                "columns. Its columns, in order: %(columns)s.",
                columns=described))
        count = len(layout._finish_columns())
        start = (self.line_ids[-1:].sequence or 0) + 10 if self.line_ids else 10
        self.env['aw.vendor.rate.list.line'].create([dict(
            list_id=self.id, sequence=start + 10 * index,
            code=row['code'], thickness_text=row['thickness'],
            series=row['series'],
            ambiguous_code=bool(row.get('ambiguous')),
            **{'rate_%s' % (i + 1): (rate or 0.0)
               for i, rate in enumerate(row['rates'][:count])})
            for index, row in enumerate(rows)])
        self.paste_text = False
        return True

    def _parse_glass_paste(self):
        """Glass type, thickness, price per sqft: one line per type and
        thickness. A colour list or "5mm/6mm" is split into its rates."""
        self.ensure_one()
        rows, skipped = parse_glass_paste_report(self.paste_text)
        if not rows:
            raise UserError(_(
                "No row reads as a glass type, a thickness (like 5mm) and "
                "a price. Paste rows such as: Clear  6mm  265.52") + (
                    ' ' + _("Not read: %s", ' | '.join(skipped[:5]))
                    if skipped else ''))
        start = (self.line_ids[-1:].sequence or 0) + 10 \
            if self.line_ids else 10
        self.env['aw.vendor.rate.list.line'].create([{
            'list_id': self.id, 'sequence': start + 10 * index,
            'code': row['type'], 'thickness_text': row['thickness'],
            'rate_1': row['price']} for index, row in enumerate(rows)])
        self.paste_text = False
        if skipped:
            # A line with a number that is not type + thickness + price is
            # never guessed at, and never dropped quietly either.
            message = _(
                "%(count)s line(s) were NOT read (each needs a glass type, "
                "a thickness with mm, and one price): %(lines)s",
                count=len(skipped), lines=' | '.join(skipped))
            self.message_post(body=message)
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("Some lines were not read"),
                           'message': message, 'type': 'warning',
                           'sticky': True,
                           'next': {'type': 'ir.actions.client',
                                    'tag': 'soft_reload'}}}
        return True

    # ------------------------------------------------------------ entry 3
    def action_fill_from_current(self):
        """Prefill rows with this vendor's rates in force today for a
        series, so only the changed numbers are typed over."""
        self.ensure_one()
        if self.kind == 'glass':
            raise UserError(_("Fill from current rates is for profile lists."))
        if self.state != 'draft':
            raise UserError(_("An applied list is read only."))
        layout = self._require_layout()
        if not self.fill_series:
            raise UserError(_("Enter the series to fill first."))
        today = fields.Date.context_today(self)
        rates = self.env['aw.profile.rate'].search([
            ('vendor_id', '=', self.vendor_id.id),
            ('vendor_series', '=ilike', self.fill_series),
            ('date_from', '<=', today),
            '|', ('date_to', '=', False), ('date_to', '>=', today)])
        if not rates:
            raise UserError(_(
                "%(vendor)s has no current rates for series '%(series)s'.",
                vendor=self.vendor_id.display_name, series=self.fill_series))
        finish_columns = layout._finish_columns()
        by_row = {}
        for rate in rates:
            by_row.setdefault(
                (rate.product_tmpl_id, rate.thickness_id), []).append(rate)
        thickness_names = {
            alias.thickness_id.id: alias.alias
            for alias in layout.thickness_alias_ids}
        start = (self.line_ids[-1:].sequence or 0) if self.line_ids else 0
        vals = []
        for index, ((template, thickness), group) in enumerate(
                sorted(by_row.items(), key=lambda kv: (
                    kv[0][0].display_name, kv[0][1].id or 0)), start=1):
            values = {
                'list_id': self.id, 'sequence': start + 10 * index,
                'code': template.default_code or template.name,
                'thickness_text': thickness_names.get(
                    thickness.id, thickness.name or ''),
                'series': self.fill_series,
                'product_tmpl_id': template.id,
                'thickness_id': thickness.id,
                'match_source': 'direct',
            }
            for i, column in enumerate(finish_columns, start=1):
                hit = next((r for r in group
                            if r.finish_id == column.finish_id), None)
                values['rate_%s' % i] = hit.price if hit else 0.0
            vals.append(values)
        self.env['aw.vendor.rate.list.line'].with_context(
            aw_no_alias=True).create(vals)
        return True

    # -------------------------------------------------------------- apply
    def _show_need(self, need, title):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'aw.vendor.rate.list.line',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('list_id', '=', self.id), ('need', '=', need)],
            'context': {},
        }

    def action_show_need_product(self):
        return self._show_need('product', _("Rows that need a product"))

    def action_show_need_thickness(self):
        return self._show_need('thickness', _("Rows that need a thickness"))

    def action_show_unknown_thickness(self):
        return self._show_need(
            'unknown_thickness', _("Rows with an unknown thickness"))

    def action_show_need_glass_type(self):
        return self._show_need('glass_type', _("Rows that need a glass type"))

    def action_show_need_finish(self):
        return self._show_need('finish', _("Rows that need a finish"))

    def action_rematch(self):
        """Match again. On a draft that is every row; on an applied list
        only the rows with a problem, so a row whose rates were already
        written to a profile is never quietly pointed at another. Rates
        are not touched either way: this changes matching and status."""
        self.ensure_one()
        if self.state == 'draft':
            self.line_ids._auto_match(force=True)
        else:
            self.line_ids.filtered(
                lambda l: l.problem or l.need)._auto_match()
        self.line_ids._refresh_need()
        return True

    def _rate_model(self):
        return 'aw.glass.rate' if self.kind == 'glass' else 'aw.profile.rate'

    def action_reapply(self):
        """Applied lists only: delete the rates this list wrote, then run
        Apply again. One transaction, so a failure leaves the old rates."""
        self.ensure_one()
        if self.state != 'applied':
            raise UserError(_("Only an applied list can be applied again."))
        old = self.env[self._rate_model()].with_context(
            active_test=False).search([('rate_list_id', '=', self.id)])
        deleted = len(old)
        affected = old.product_tmpl_id if self.kind == 'profile' \
            else self.env['product.template']
        old.unlink()
        summary = self._apply()
        summary['deleted'] = deleted
        self._follow_variant_costs(affected)
        message = _(
            "Re-applied: %(deleted)s old rate(s) deleted, %(applied)s "
            "written, %(conflicts)s finish(es) in conflict, "
            "%(rows_not_applied)s row(s) not applied.", **summary)
        self.message_post(body=message)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("Re-applied"), 'message': message,
                       'type': 'success', 'sticky': True,
                       'next': {'type': 'ir.actions.client',
                                'tag': 'soft_reload'}},
        }

    def action_set_to_draft(self):
        """Applied lists only: delete the rates this list wrote, keep
        every line, and make the whole list editable again."""
        self.ensure_one()
        if self.state != 'applied':
            raise UserError(_("Only an applied list can be set to draft."))
        old = self.env[self._rate_model()].with_context(
            active_test=False).search([('rate_list_id', '=', self.id)])
        deleted = len(old)
        affected = old.product_tmpl_id if self.kind == 'profile' \
            else self.env['product.template']
        old.unlink()
        self.line_ids.write({
            'result': False, 'detail': False, 'cells_applied': 0,
            'cells_skipped': 0, 'cells_failed': 0, 'cells_conflict': 0})
        self.state = 'draft'
        self._follow_variant_costs(affected)
        self.message_post(body=_(
            "Set to draft: %s rate(s) removed; the lines are kept.",
            deleted))
        return True

    def action_apply(self):
        """Write the rates. Unmatched rows are never applied."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("This list is already applied."))
        self._apply()
        return True

    def _apply(self):
        """The work of Apply, repeatable: a rate is looked up by profile,
        thickness, finish, vendor and date, so writing a list again
        updates what it wrote and adds what it could not before."""
        self.ensure_one()
        if self.kind == 'glass':
            return self._apply_glass()
        layout = self._require_layout()
        finish_columns = layout._finish_columns()
        Rate = self.env['aw.profile.rate']
        written = skipped = skipped_cells = failed_cells = 0
        conflict_cells = conflict_rows = 0
        affected = self.env['product.template']
        for line in self.line_ids.sorted('sequence'):
            if line.problem:
                line.write({
                    'result': _("Not applied: %s", line.problem),
                    'cells_applied': 0, 'cells_skipped': 0,
                    'cells_failed': 0, 'cells_conflict': 0,
                    'detail': line.problem})
                skipped += 1
                continue
            line._refresh_need()
            offered_thickness = self.env['aw.profile.section.line'] \
                ._template_values(
                    line.product_tmpl_id,
                    self.env.ref('aw_fenestration_core.aw_attribute_thickness'))
            offered_finish = self.env['aw.profile.section.line'] \
                ._template_values(
                    line.product_tmpl_id,
                    self.env.ref('aw_fenestration_core.aw_attribute_finish'))
            notes = []
            line_applied = line_skipped = line_failed = line_conflict = 0
            # Two columns can map to one finish (BRO and SHARA both Brown
            # PC Sahara): one number is used, equal numbers are one, and
            # different numbers write nothing rather than guess.
            by_finish = {}
            for index, column in enumerate(finish_columns, start=1):
                price = line['rate_%s' % index]
                if not price:
                    continue            # empty cells create nothing
                if not column.finish_id:
                    notes.append(_(
                        "%s: no finish set", column.header or index))
                    line_skipped += 1
                    continue
                by_finish.setdefault(column.finish_id, []).append(
                    (column, price))
            for finish, cells in by_finish.items():
                if len({price for _col, price in cells}) > 1:
                    notes.append(_(
                        "Conflict: %(cells)s both map to %(finish)s",
                        cells=' / '.join(
                            '%s %s' % (col.header or finish.name, price)
                            for col, price in cells),
                        finish=finish.name))
                    line_conflict += 1
                    continue
                column, price = cells[0]
                finish_attr = self.env.ref(
                    'aw_fenestration_core.aw_attribute_finish')
                if (column.finish_id not in offered_finish
                        and column.finish_id.aw_owner_vendor_id
                        == self.vendor_id
                        and not (line.thickness_id
                                 and line.thickness_id
                                 not in offered_thickness)
                        and line.product_tmpl_id.attribute_line_ids.filtered(
                            lambda l: l.attribute_id == finish_attr)):
                    # Only a finish made from THIS vendor's own header
                    # (Wood) is added; every other missing finish still
                    # stops the cell. The attribute-line guard merges it
                    # into the profile's existing Finish line.
                    line.product_tmpl_id.write({'attribute_line_ids': [(0, 0, {
                        'attribute_id': finish_attr.id,
                        'value_ids': [(4, column.finish_id.id)]})]})
                    offered_finish = self.env['aw.profile.section.line'] \
                        ._template_values(line.product_tmpl_id, finish_attr)
                    notes.append(_(
                        "%(finish)s added to this profile",
                        finish=column.finish_id.name))
                if (line.thickness_id
                        and line.thickness_id not in offered_thickness) or (
                        column.finish_id not in offered_finish):
                    line_failed += 1
                    continue
                key = [
                    ('product_tmpl_id', '=', line.product_tmpl_id.id),
                    ('thickness_id', '=', line.thickness_id.id or False),
                    ('finish_id', '=', column.finish_id.id),
                    ('vendor_id', '=', self.vendor_id.id),
                    ('date_from', '=', self.date)]
                existing = Rate.search(key, limit=1)
                values = {
                    'price': price, 'vendor_series': line.series,
                    'source_note': self.name, 'rate_list_id': self.id}
                if existing:
                    existing.write(values)
                else:
                    Rate.create(dict(
                        values,
                        product_tmpl_id=line.product_tmpl_id.id,
                        thickness_id=line.thickness_id.id or False,
                        finish_id=column.finish_id.id,
                        vendor_id=self.vendor_id.id,
                        date_from=self.date))
                written += 1
                line_applied += 1
                affected |= line.product_tmpl_id
            if line.need in ('thickness', 'finish') and line.need_text:
                notes.insert(0, line.need_text)
            skipped_cells += line_skipped
            failed_cells += line_failed
            conflict_cells += line_conflict
            conflict_rows += 1 if line_conflict else 0
            line.write({
                'result': '; '.join(notes) if notes else _("Applied"),
                'cells_applied': line_applied,
                'cells_skipped': line_skipped,
                'cells_failed': line_failed,
                'cells_conflict': line_conflict,
                'detail': '; '.join(notes)})
        self.state = 'applied'
        self._follow_variant_costs(affected)
        summary = {'applied': written, 'skipped': skipped_cells,
                   'failed': failed_cells, 'rows_not_applied': skipped,
                   'conflicts': conflict_cells,
                   'conflict_rows': conflict_rows}
        self.message_post(body=_(
            "Applied: %(applied)s rate(s) written, %(skipped)s column(s) "
            "skipped (no finish), %(failed)s could not be applied (no such "
            "variant), %(conflicts)s finish(es) in conflict on "
            "%(conflict_rows)s row(s), %(rows_not_applied)s row(s) not "
            "applied.", **summary))
        return summary

    def _apply_glass(self):
        """Glass rates: one per row, by type, thickness, vendor and the
        list's date. A row needing a glass type, or with a thickness that
        is not a number, is not applied; nothing is created."""
        self.ensure_one()
        Rate = self.env['aw.glass.rate']
        written = skipped = conflict_rows = 0
        # Two rows for one type and thickness with different prices are a
        # Conflict: both are marked and neither is written (equal prices
        # are one price), as for profiles.
        priced = {}
        for line in self.line_ids:
            line._refresh_need()
            if not line.need and line.rate_1:
                priced.setdefault(
                    (line.glass_type_id.id,
                     parse_thickness(line.thickness_text)[0]),
                    []).append(line)
        in_conflict = self.env['aw.vendor.rate.list.line']
        for lines in priced.values():
            if len({round(l.rate_1, 4) for l in lines}) > 1:
                in_conflict |= self.env['aw.vendor.rate.list.line'].concat(
                    *lines)
        for line in self.line_ids.sorted('sequence'):
            line._refresh_need()
            if line in in_conflict:
                same = in_conflict.filtered(
                    lambda l: l.glass_type_id == line.glass_type_id
                    and parse_thickness(l.thickness_text)
                    == parse_thickness(line.thickness_text))
                detail = _(
                    "Conflict: %(type)s %(thickness)s has %(prices)s in this "
                    "list; nothing written",
                    type=line.glass_type_id.name,
                    thickness=line.thickness_text,
                    prices=' and '.join(
                        '%g' % p for p in sorted({l.rate_1 for l in same})))
                line.write({
                    'result': detail, 'cells_applied': 0,
                    'cells_skipped': 0, 'cells_failed': 0,
                    'cells_conflict': 1, 'detail': detail})
                conflict_rows += 1
                continue
            reason = line.need_text if line.need else (
                False if line.rate_1 else _("no price"))
            if reason:
                line.write({
                    'result': _("Not applied: %s", reason),
                    'cells_applied': 0, 'cells_skipped': 0,
                    'cells_failed': 0, 'cells_conflict': 0,
                    'detail': reason})
                skipped += 1
                continue
            thickness = parse_thickness(line.thickness_text)[0]
            key = [('glass_type_id', '=', line.glass_type_id.id),
                   ('thickness_mm', '=', thickness),
                   ('vendor_id', '=', self.vendor_id.id),
                   ('date_from', '=', self.date)]
            values = {'price': line.rate_1, 'source_note': self.name,
                      'rate_list_id': self.id}
            existing = Rate.search(key, limit=1)
            if existing:
                existing.write(values)
            else:
                Rate.create(dict(
                    values, glass_type_id=line.glass_type_id.id,
                    thickness_mm=thickness, vendor_id=self.vendor_id.id,
                    date_from=self.date))
            line.write({'result': _("Applied"), 'cells_applied': 1,
                        'cells_skipped': 0, 'cells_failed': 0,
                        'cells_conflict': 0, 'detail': False})
            written += 1
        self.state = 'applied'
        summary = {'applied': written, 'skipped': 0, 'failed': 0,
                   'rows_not_applied': skipped, 'conflicts': conflict_rows,
                   'conflict_rows': conflict_rows}
        self.message_post(body=_(
            "Applied: %(applied)s glass rate(s) written, %(conflicts)s "
            "row(s) in conflict, %(rows_not_applied)s row(s) not applied.",
            **summary))
        return summary

    def _follow_variant_costs(self, templates):
        """A variant's cost field follows its series' default vendor, so
        stock valuation stays sensible. Only for profiles whose default
        vendor is the one just applied."""
        variants = self.env['product.product']
        for template in templates:
            if template._aw_default_vendor() == self.vendor_id:
                variants |= template.product_variant_ids
        if variants:
            variants.invalidate_recordset()
            variants._aw_sync_cost_from_rate()


class AwVendorRateListLine(models.Model):
    _name = 'aw.vendor.rate.list.line'
    _description = 'Vendor Rate List Line'
    _order = 'sequence, id'

    list_id = fields.Many2one(
        'aw.vendor.rate.list', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    state = fields.Selection(related='list_id.state')
    vendor_id = fields.Many2one(related='list_id.vendor_id')
    code = fields.Char(required=True)
    ambiguous_code = fields.Boolean(
        readonly=True,
        help="A code written with a slash that is not clearly two codes.")
    code_norm = fields.Char(compute='_compute_norms', store=True)
    thickness_text = fields.Char(string='Thickness')
    thickness_norm = fields.Char(compute='_compute_norms', store=True)
    series = fields.Char()
    rate_1 = fields.Float(digits='Product Price')
    rate_2 = fields.Float(digits='Product Price')
    rate_3 = fields.Float(digits='Product Price')
    rate_4 = fields.Float(digits='Product Price')
    rate_5 = fields.Float(digits='Product Price')
    rate_6 = fields.Float(digits='Product Price')
    rate_7 = fields.Float(digits='Product Price')
    rate_8 = fields.Float(digits='Product Price')
    rate_9 = fields.Float(digits='Product Price')
    rate_10 = fields.Float(digits='Product Price')
    product_tmpl_id = fields.Many2one(
        'product.template', string='Matched profile',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id)])
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Our thickness')
    glass_type_id = fields.Many2one(
        'aw.glass.type', string='Glass type',
        help="Set on a glass list's rows: the type the first column names.")
    match_source = fields.Selection([
        ('none', 'Not matched'), ('direct', 'By code'),
        ('alias', 'By alias'), ('manual', 'Chosen')], default='none')
    problem = fields.Char(
        compute='_compute_problem', store=True,
        help="Why this row cannot be applied. Empty means ready.")
    # What this row needs before it can be applied in full, written by
    # _refresh_need (on match, on edit, and at Apply). Stored, because the
    # list filters on it, and plain rather than computed: it depends on the
    # product's attribute lines, which a stored compute cannot watch.
    need = fields.Selection([
        ('product', 'Needs a product'),
        ('unknown_thickness', 'Unknown thickness'),
        ('thickness', 'Needs a thickness'),
        ('finish', 'Needs a finish'),
        ('glass_type', 'Needs a glass type'),
    ], index=True, readonly=True)
    need_text = fields.Char(readonly=True)
    result = fields.Char(readonly=True)
    # What Apply did to this row, kept as numbers so the grid can show a
    # badge and keep the full detail for a tooltip.
    cells_applied = fields.Integer(readonly=True)
    cells_skipped = fields.Integer(
        readonly=True, help="Rate columns with no finish set.")
    cells_failed = fields.Integer(
        readonly=True,
        help="Mapped columns the product has no variant for.")
    cells_conflict = fields.Integer(
        readonly=True,
        help="Finishes two columns map to, with different numbers: no "
             "rate is written for them.")
    detail = fields.Char(readonly=True)
    list_state = fields.Selection(related='list_id.state')
    # Every cell of a draft; on an applied list only an unmatched row,
    # since an applied row is the record of what was written.
    grid_editable = fields.Boolean(compute='_compute_grid_editable')

    @api.depends('list_id.state', 'problem')
    def _compute_grid_editable(self):
        for line in self:
            line.grid_editable = (
                line.list_id.state == 'draft' or bool(line.problem))
    status_code = fields.Selection([
        ('applied', 'Applied'),
        ('partial', 'Partly applied'),
        ('conflict', 'Conflict'),
        ('unmatched', 'Unmatched'),
        ('needs_thickness', 'Needs a thickness'),
        ('needs_finish', 'Needs a finish'),
        ('not_applied', 'Not applied'),
    ], compute='_compute_status_code', store=True)

    @api.depends('problem', 'cells_applied', 'cells_failed',
                 'cells_conflict', 'list_id.state', 'need')
    def _compute_status_code(self):
        for line in self:
            if line.problem:
                line.status_code = 'unmatched'
            elif line.need == 'thickness':
                line.status_code = 'needs_thickness'
            elif line.need == 'finish':
                line.status_code = 'needs_finish'
            elif line.list_id.state == 'applied' and line.cells_conflict:
                line.status_code = 'conflict'
            elif line.list_id.state != 'applied' or not line.cells_applied:
                line.status_code = 'not_applied'
            elif line.cells_failed:
                line.status_code = 'partial'
            else:
                line.status_code = 'applied'

    @api.depends('code', 'thickness_text')
    def _compute_norms(self):
        for line in self:
            line.code_norm = normalise_code(line.code)
            line.thickness_norm = normalise_text(line.thickness_text)

    @api.depends('product_tmpl_id', 'thickness_id', 'thickness_text',
                 'ambiguous_code', 'glass_type_id', 'list_id.kind')
    def _compute_problem(self):
        for line in self:
            if line.list_id.kind == 'glass':
                line.problem = line._glass_need()[1] or False
            elif line.ambiguous_code:
                line.problem = _("Ambiguous code '%s'", line.code or '')
            elif not line.product_tmpl_id:
                line.problem = _(
                    "No product %s: create it in Products, then Re-match",
                    line.code or '')
            elif line.thickness_text and not line.thickness_id:
                line.problem = _(
                    "Unknown thickness '%s': not one of ours or an alias "
                    "on this vendor's layout", line.thickness_text)
            else:
                line.problem = False

    def _glass_need(self):
        """(need, text) for a glass row: a type that exists, and a
        thickness that is a number of mm."""
        self.ensure_one()
        if not self.glass_type_id:
            return 'glass_type', _(
                "No glass type %s: add it under Glass Types, then Re-match",
                self.code or '')
        if len(parse_thickness(self.thickness_text)) != 1:
            return 'unknown_thickness', _(
                "Unknown thickness '%s': write it like 5mm",
                self.thickness_text or '')
        return False, False

    def _need_for(self):
        """(need, text) for this row. Nothing is created: a row either
        names what is missing on the product, or is ready."""
        self.ensure_one()
        if self.list_id.kind == 'glass':
            return self._glass_need()
        if self.ambiguous_code:
            return 'product', _("Ambiguous code '%s'", self.code or '')
        if not self.product_tmpl_id:
            return 'product', _(
                "No product %s: create it in Products, then Re-match",
                self.code or '')
        if self.thickness_text and not self.thickness_id:
            return 'unknown_thickness', _(
                "Unknown thickness '%s': not one of ours or an alias "
                "on this vendor's layout", self.thickness_text)
        Section = self.env['aw.profile.section.line']
        template = self.product_tmpl_id
        label = template.default_code or template.name
        if self.thickness_id and self.thickness_id not in \
                Section._template_values(template, self.env.ref(
                    'aw_fenestration_core.aw_attribute_thickness')):
            return 'thickness', _(
                "%(code)s has no thickness %(thickness)s: add it on the "
                "product (Attributes & Variants), then Re-match",
                code=label, thickness=self.thickness_id.name)
        offered = Section._template_values(template, self.env.ref(
            'aw_fenestration_core.aw_attribute_finish'))
        missing = []
        for index, column in enumerate(
                self.list_id.layout_id._finish_columns(), start=1):
            finish = column.finish_id
            if not finish or not self['rate_%s' % index]:
                continue
            # A finish the vendor itself named (Wood) is added by Apply.
            if finish in offered or finish.aw_owner_vendor_id \
                    == self.vendor_id or finish in missing:
                continue
            missing.append(finish)
        if missing:
            return 'finish', _(
                "%(code)s has no finish %(finishes)s: add %(them)s on the "
                "product, then Re-match",
                code=label, finishes=', '.join(f.name for f in missing),
                them=_("them") if len(missing) > 1 else _("it"))
        return False, False

    def _refresh_need(self):
        for line in self:
            need, text = line._need_for()
            if (line.need or False) != need or (line.need_text or False) != text:
                line.with_context(aw_need=True).write(
                    {'need': need, 'need_text': text})

    # --------------------------------------------------------------- match
    def _auto_match(self, force=False):
        """Product by alias then by code; thickness by the vendor's alias
        or by name. A row somebody chose by hand is left alone unless
        forced."""
        glass = self.filtered(lambda l: l.list_id.kind == 'glass')
        if glass:
            Type = self.env['aw.glass.type']
            for line in glass.with_context(aw_auto_match=True):
                line.glass_type_id = Type.search(
                    [('name_norm', '=', norm_type(line.code))], limit=1)
            glass._refresh_need()
            self -= glass
            if not self:
                return
        Template = self.env['product.template']
        # stored norms predate any change to the rule, so refresh them
        self._compute_norms()
        profiles = Template.search([(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id)])
        by_code = {}
        for template in profiles:
            for key in (template.default_code, template.name):
                if key:
                    by_code.setdefault(normalise_code(key), set()).add(
                        template.id)
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        for line in self.with_context(aw_auto_match=True):
            layout = line.list_id.layout_id
            vendor = line.list_id.vendor_id
            if line.match_source == 'manual' and not force:
                pass
            else:
                alias = self.env['aw.vendor.alias'].search([
                    ('vendor_id', '=', vendor.id),
                    ('code_norm', '=', line.code_norm),
                    ('thickness_text', 'in', [line.thickness_norm, False, ''])
                ], order='thickness_text desc', limit=1)
                if alias:
                    line.product_tmpl_id = alias.product_tmpl_id
                    line.match_source = 'alias'
                    if alias.thickness_id:
                        line.thickness_id = alias.thickness_id
                else:
                    ids = by_code.get(line.code_norm, set())
                    if len(ids) == 1:
                        line.product_tmpl_id = Template.browse(next(iter(ids)))
                        line.match_source = 'direct'
                    else:
                        line.product_tmpl_id = False
                        line.match_source = 'none'
            if line.thickness_text and not (
                    line.match_source == 'alias' and line.thickness_id):
                wanted = line.thickness_norm
                found = layout.thickness_alias_ids.filtered(
                    lambda a: normalise_text(a.alias) == wanted)[:1]
                if found:
                    line.thickness_id = found.thickness_id
                else:
                    line.thickness_id = thickness_attr.value_ids.filtered(
                        lambda v: normalise_text(v.name) == wanted)[:1]
            elif not line.thickness_text:
                line.thickness_id = False
        self._refresh_need()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        pending = lines.filtered(
            lambda l: l.match_source == 'none' and not l.product_tmpl_id)
        if pending:
            pending._auto_match()
        lines._refresh_need()
        return lines

    def write(self, vals):
        manual = ('product_tmpl_id' in vals
                  and not self.env.context.get('aw_auto_match'))
        if manual and not self.env.context.get('aw_no_alias'):
            vals = dict(vals, match_source='manual')
        result = super().write(vals)
        if manual and vals.get('product_tmpl_id') \
                and not self.env.context.get('aw_no_alias'):
            for line in self:
                line._save_alias()
        if ('code' in vals or 'thickness_text' in vals) and not manual \
                and not self.env.context.get('aw_auto_match'):
            self._auto_match()
        elif not self.env.context.get('aw_need') \
                and not self.env.context.get('aw_auto_match') \
                and ({'product_tmpl_id', 'thickness_id'} & set(vals)
                     or any(k.startswith('rate_') for k in vals)):
            self._refresh_need()
        return result

    def _save_alias(self):
        """The product was picked by hand: remember it, once."""
        self.ensure_one()
        Alias = self.env['aw.vendor.alias']
        key = [('vendor_id', '=', self.vendor_id.id),
               ('code_norm', '=', self.code_norm),
               ('thickness_text', '=', self.thickness_norm or False)]
        found = Alias.search(key, limit=1)
        values = {'product_tmpl_id': self.product_tmpl_id.id}
        if found:
            found.write(values)
        else:
            Alias.create(dict(
                values, vendor_id=self.vendor_id.id,
                code_norm=self.code_norm,
                thickness_text=self.thickness_norm or False))
        self.with_context(aw_auto_match=True)._auto_match()
