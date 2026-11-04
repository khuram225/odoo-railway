# -*- coding: utf-8 -*-
"""A panel's glass is its own stack of parts.

Sheet 1, an optional Gap, Sheet 2, an optional Protector. A window has a
HEADER default stack, copied into new panels and again by "Apply to all
panels"; a panel can then be changed alone. A profile spec carries a default
stack that a new window starts from. There are no saved glass specs.

A part that is a SHEET names a glass type and a thickness (so one Glass
Sheet variant); its price is the dated vendor rate for them, unless somebody
typed another rate for this panel, which is flagged manual. A GAP has a
width, a spacer type and colour, and a gas. A PROTECTOR is a sheet, or a
film priced from the Glass extras table.

Until a window has any stack of its own it is still read through the old
spec it points at (see _glass_stack_dicts), so nothing costs differently
before the migration has run.
"""
from odoo import _, api, fields, models

from .glass_recipes import recipe_for_spec


class AwGlassPart(models.Model):
    _name = 'aw.glass.part'
    _description = 'Glass Build-up Part'
    _order = 'sequence, id'

    # exactly one owner: a panel, a window's header default, or a spec
    leaf_id = fields.Many2one(
        'aw.design.leaf', ondelete='cascade', index=True)
    design_id = fields.Many2one(
        'aw.design', ondelete='cascade', index=True,
        help="Set on a window's HEADER stack, the default new panels copy.")
    template_id = fields.Many2one(
        'aw.window.template', ondelete='cascade', index=True,
        help="Set on a spec's default stack.")
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('sheet', 'Sheet'), ('gap', 'Gap'), ('protector', 'Protector'),
    ], required=True, default='sheet')
    glass_type_id = fields.Many2one(
        'aw.glass.type', string='Glass type', ondelete='restrict')
    thickness_mm = fields.Float(string='Thickness (mm)')
    gap_mm = fields.Float(string='Gap (mm)')
    spacer_type_id = fields.Many2one(
        'aw.glass.option', string='Spacer', ondelete='restrict',
        domain=[('kind', '=', 'spacer_type')])
    spacer_colour_id = fields.Many2one(
        'aw.glass.option', string='Spacer colour', ondelete='restrict',
        domain=[('kind', '=', 'spacer_colour')])
    gas_id = fields.Many2one(
        'aw.glass.option', string='Gas', ondelete='restrict',
        domain=[('kind', '=', 'gas')])
    extra_id = fields.Many2one(
        'aw.glass.extra', string='Film', ondelete='restrict',
        domain=[('kind', '=', 'protector_film')],
        help="A protector made of film is priced from the Glass extras.")
    rate_manual = fields.Boolean(
        string='Manual rate',
        help="Somebody typed the rate for this panel. Reset returns it to "
             "the list rate.")
    manual_rate = fields.Float(digits='Product Price')
    part_design_id = fields.Many2one(
        'aw.design', string='Window', compute='_compute_owner', store=False)
    panel_no = fields.Integer(string='Panel', compute='_compute_owner')
    order_id = fields.Many2one(
        'sale.order', string='Quote', compute='_compute_owner')
    label = fields.Char(compute='_compute_owner')
    remark = fields.Char(
        help="Printed on quotes and shop drawings, e.g. 'was: Clear "
             "Tempered', until the processing is a service of its own.")
    migrated = fields.Boolean(
        help="Made by the migration from a saved glass spec.")
    default_gap = fields.Boolean(
        string='Default gap, not checked',
        help="The migration filled this gap with defaults.")

    @api.depends('leaf_id.row_id.design_id', 'design_id', 'leaf_id.panel_no',
                 'kind', 'glass_type_id', 'thickness_mm', 'gap_mm')
    def _compute_owner(self):
        for part in self:
            design = part.design_id or part.leaf_id.row_id.design_id
            part.part_design_id = design
            part.panel_no = part.leaf_id.panel_no
            part.order_id = design.sale_order_id
            part.label = self._label_of(part._as_dict())

    def _as_dict(self):
        """The canonical, Odoo-free shape the explosion and costing read."""
        self.ensure_one()
        return {
            'kind': self.kind,
            'glass_type_id': self.glass_type_id.id,
            'glass_type': self.glass_type_id.name or '',
            'thickness_mm': self.thickness_mm,
            'gap_mm': self.gap_mm,
            'spacer_type': self.spacer_type_id.name or '',
            'spacer_colour': self.spacer_colour_id.name or '',
            'gas': self.gas_id.name or '',
            'extra_id': self.extra_id.id,
            'extra': self.extra_id.name or '',
            'rate_manual': self.rate_manual,
            'manual_rate': self.manual_rate,
            'remark': self.remark or '',
            'migrated': self.migrated,
            'default_gap': self.default_gap,
        }

    @api.model
    def _vals_from_dict(self, item, sequence=10):
        """Field values (names resolved to records) from a canonical dict
        or a recipe part. Names the lists do not know are left empty."""
        Type = self.env['aw.glass.type']
        Option = self.env['aw.glass.option']

        def option(kind, name):
            return Option.search(
                [('kind', '=', kind), ('name', '=ilike', name or '')],
                limit=1).id if name else False

        glass_type = item.get('glass_type_id') and item['glass_type_id']
        if not glass_type and item.get('glass_type'):
            glass_type = Type.search(
                [('name', '=ilike', item['glass_type'])], limit=1).id
        manual_zero = item.get('manual_zero')
        return {
            'sequence': sequence,
            'kind': item['kind'],
            'glass_type_id': glass_type or False,
            'thickness_mm': item.get('thickness_mm') or 0.0,
            'gap_mm': item.get('gap_mm') or 0.0,
            'spacer_type_id': item.get('spacer_type_id')
            or option('spacer_type', item.get('spacer_type')),
            'spacer_colour_id': item.get('spacer_colour_id')
            or option('spacer_colour', item.get('spacer_colour')),
            'gas_id': item.get('gas_id')
            or option('gas', item.get('gas')),
            'extra_id': item.get('extra_id') or False,
            'rate_manual': bool(item.get('rate_manual') or manual_zero),
            'manual_rate': 0.0 if manual_zero
            else (item.get('manual_rate') or 0.0),
            'remark': item.get('remark') or '',
            'migrated': bool(item.get('migrated')),
            'default_gap': bool(item.get('default_gap')),
        }

    @api.model
    def _commands_from(self, items):
        """(0, 0, vals) commands for a list of dicts, in order."""
        return [(0, 0, self._vals_from_dict(item, sequence=10 * index))
                for index, item in enumerate(items, start=1)]

    @api.model
    def _label_of(self, item):
        """'6 mm Clear', '12 mm gap, Argon' for one canonical dict."""
        if item['kind'] == 'gap':
            gas = item.get('gas')
            return ('%g mm gap' % item.get('gap_mm', 0)) + (
                ', %s' % gas if gas and gas.lower() != 'air' else '')
        if item.get('extra'):
            return item['extra']
        return '%g mm %s' % (item.get('thickness_mm', 0),
                             item.get('glass_type') or '?')

    @api.model
    def _summary_of(self, items):
        """'6 mm Clear + 12 mm gap + 6 mm Clear'."""
        return ' + '.join(self._label_of(item) for item in items)

    @api.model
    def _remarks_of(self, items):
        seen = []
        for item in items:
            if item.get('remark') and item['remark'] not in seen:
                seen.append(item['remark'])
        return seen

    @api.model
    def _signature(self, items):
        """What makes two stacks the same glass (rates and remarks aside)."""
        return tuple((i['kind'], i.get('glass_type', ''),
                      i.get('thickness_mm', 0), i.get('gap_mm', 0))
                     for i in items)


class AwDesignLeaf(models.Model):
    _inherit = 'aw.design.leaf'

    glass_part_ids = fields.One2many(
        'aw.glass.part', 'leaf_id', string='Glass stack')
    glass_summary = fields.Char(compute='_compute_glass_summary')

    @api.depends('glass_part_ids', 'glass_part_ids.glass_type_id',
                 'glass_part_ids.thickness_mm', 'glass_part_ids.gap_mm',
                 'row_id.design_id.glass_part_ids')
    def _compute_glass_summary(self):
        Part = self.env['aw.glass.part']
        for leaf in self:
            design = leaf.row_id.design_id
            items = design._glass_stack_dicts(leaf) if design else []
            leaf.glass_summary = Part._summary_of(items)


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    glass_part_ids = fields.One2many(
        'aw.glass.part', 'template_id', string='Default glass stack')


class AwDesign(models.Model):
    _inherit = 'aw.design'

    glass_part_ids = fields.One2many(
        'aw.glass.part', 'design_id', string='Window glass stack')
    glass_summary = fields.Char(compute='_compute_glass_summary')

    @api.depends('glass_part_ids', 'glass_part_ids.glass_type_id',
                 'glass_part_ids.thickness_mm', 'glass_part_ids.gap_mm',
                 'glass_spec_id')
    def _compute_glass_summary(self):
        Part = self.env['aw.glass.part']
        for design in self:
            design.glass_summary = Part._summary_of(
                design._glass_stack_dicts())

    def _has_glass_stacks(self):
        """Has this window been given any stack of its own (header or a
        panel)? Then the old specs are no longer read."""
        self.ensure_one()
        if self.glass_part_ids:
            return True
        if not isinstance(self.id, int):
            return False          # an unsaved record: nothing to search
        return bool(self.env['aw.glass.part'].search_count([
            ('leaf_id.row_id.design_id', '=', self.id)]))

    def _glass_stack_dicts(self, leaf=None):
        """The stack a panel is glazed with, as canonical dicts, in order.

        A panel's own parts, else the window's header stack. A window with
        no stack anywhere yet is read through the old spec it points at
        (its panel's override, else its own), then the spec's default
        stack, so nothing costs differently before the migration has run;
        once ANY stack exists on the window the old pointers are ignored,
        and a panel with none simply has no glass.
        """
        self.ensure_one()
        Part = self.env['aw.glass.part']
        own = leaf.glass_part_ids if leaf else Part
        parts = own or self.glass_part_ids
        if parts:
            return [p._as_dict() for p in parts.sorted('sequence')]
        if self._has_glass_stacks():
            return []
        spec = (leaf and leaf.glass_spec_id) or self.glass_spec_id
        if spec:
            return self._spec_stack_dicts(spec)
        if self.template_id.glass_part_ids:
            return [p._as_dict() for p in
                    self.template_id.glass_part_ids.sorted('sequence')]
        return self._spec_stack_dicts(self.template_id.glass_spec_id)

    def _spec_stack_dicts(self, spec):
        """A saved spec read as a stack (see glass_recipes); nothing for a
        spec whose name is not one it knows."""
        if not spec:
            return []
        recipe = recipe_for_spec(
            spec.name, priced=spec.product_id.standard_price > 0)
        return [self._recipe_dict(part) for part in (recipe or [])]

    @api.model
    def _recipe_dict(self, part):
        """A recipe part, as the canonical dict (types resolved by name)."""
        glass_type = self.env['aw.glass.type'].search(
            [('name', '=ilike', part.get('glass_type') or '')], limit=1)
        item = dict(part)
        item.update({
            'glass_type_id': glass_type.id,
            'glass_type': glass_type.name or part.get('glass_type') or '',
            'rate_manual': bool(part.get('manual_zero')),
            'manual_rate': 0.0,
        })
        item.setdefault('thickness_mm', 0.0)
        item.setdefault('gap_mm', 0.0)
        for key in ('spacer_type', 'spacer_colour', 'gas', 'extra', 'remark'):
            item.setdefault(key, '')
        item.setdefault('extra_id', False)
        item.setdefault('migrated', False)
        item.setdefault('default_gap', False)
        return item

    @api.model
    def _glass_stack_client(self, items):
        """The stack as the configurator holds it: field values with ids,
        plus a label to show."""
        Part = self.env['aw.glass.part']
        out = []
        for item in items:
            vals = Part._vals_from_dict(item)
            vals.pop('sequence', None)
            vals['label'] = Part._label_of(item)
            out.append(vals)
        return out

    def _glass_catalog(self):
        """What the stack editor picks from, and the list rates it shows
        beside each row. The rates are the glass vendor's, in force today;
        the cost itself is always worked out on the server."""
        Type = self.env['aw.glass.type']
        vendor = self._glass_vendor() if len(self) == 1 and self.id \
            else Type._default_glass_vendor()
        today = fields.Date.context_today(self)
        types = Type.search([])
        rates = {}
        for rate in self.env['aw.glass.rate'].search([
                ('vendor_id', '=', vendor.id), ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today)],
                order='date_from desc, id desc'):
            rates.setdefault(
                '%s-%g' % (rate.glass_type_id.id, rate.thickness_mm),
                rate.price)
        thickness_attr = Type._glass_attribute('thickness')

        def options(kind):
            return [{'id': o.id, 'name': o.name} for o in
                    self.env['aw.glass.option'].search([('kind', '=', kind)])]

        films = {}
        for extra in self.env['aw.glass.extra'].search(
                [('kind', '=', 'protector_film')], order='date_from desc'):
            films.setdefault(extra.name.lower(), {
                'id': extra.id, 'name': extra.name, 'rate': extra.rate})
        spacer_rates = {}
        for extra in self.env['aw.glass.extra'].search(
                [('kind', 'in', ('spacer', 'gas')),
                 ('date_from', '<=', today)], order='date_from desc'):
            spacer_rates.setdefault(
                '%s:%s' % (extra.kind, extra.name.lower()), extra.rate)
        return {
            'types': [{
                'id': t.id, 'name': t.name, 'colour': t.colour_id.name or '',
                'kind': t.kind_id.name or ''} for t in types],
            'thicknesses': sorted(
                v for v in (self.env['aw.glass.type']._thickness_values(
                    thickness_attr))),
            'spacer_types': options('spacer_type'),
            'gap_widths': [float(o['name']) for o in options('gap_mm')
                           if o['name'].replace('.', '', 1).isdigit()],
            'spacer_colours': options('spacer_colour'),
            'gases': options('gas'),
            'films': list(films.values()),
            'rates': rates,
            'extra_rates': spacer_rates,
            'vendor': vendor.display_name or '',
        }

    def _glass_vendor(self):
        """Whose glass rates this window is costed at: the order's glass
        vendor, else the supplier the first list was loaded for."""
        self.ensure_one()
        return (self.sale_order_id.aw_glass_vendor_id
                or self.env['aw.glass.type']._default_glass_vendor())

    def _glass_stack_text(self, leaf=None):
        """Stack summary plus any remarks, as printed on a quote or a
        shop drawing: a frosted glass is never printed as plain Clear."""
        self.ensure_one()
        Part = self.env['aw.glass.part']
        items = self._glass_stack_dicts(leaf)
        text = Part._summary_of(items)
        remarks = Part._remarks_of(items)
        return '%s (%s)' % (text, '; '.join(remarks)) if remarks and text \
            else text
