# -*- coding: utf-8 -*-
"""Glass as products, in the same design as profiles.

ONE product template, "Glass Sheet" (square feet, not sold, no sales price,
no cost field shown), with three dynamic attributes: Colour, Type (Plain,
Reflective, WC, CC) and Glass Thickness. A glass type plus a thickness names
one variant; the dated Ghani rate, which stays keyed on type and thickness,
is the variant's price. Processing, gaps and protectors are not variants.

Everything that creates a record here runs from the registry hook, after
every module has loaded: a product created while modules are still loading
misses the NOT NULL columns that purchase and sale add, and that killed two
deploys.
"""
import logging

from odoo import api, fields, models

from .glass_variants import (
    COLOURS, KINDS, THICKNESSES_MM, thickness_mm, thickness_name, type_parts)

_logger = logging.getLogger(__name__)

SHEET_XMLID = 'aw_fenestration_core.product_glass_sheet'
ATTRIBUTES = (
    ('colour', 'Colour', COLOURS),
    ('kind', 'Type', KINDS),
    ('thickness', 'Glass Thickness',
     [thickness_name(mm) for mm in THICKNESSES_MM]),
)


class AwGlassType(models.Model):
    _inherit = 'aw.glass.type'

    colour_id = fields.Many2one(
        'product.attribute.value', string='Colour', ondelete='restrict')
    kind_id = fields.Many2one(
        'product.attribute.value', string='Type', ondelete='restrict',
        help="Plain, Reflective, WC or CC: kept as written.")

    @api.model
    def _glass_sheet(self):
        return self.env.ref(SHEET_XMLID, raise_if_not_found=False) \
            or self.env['product.template']

    @api.model
    def _glass_attribute(self, key):
        return self.env.ref(
            'aw_fenestration_core.aw_attribute_glass_%s' % key,
            raise_if_not_found=False) or self.env['product.attribute']

    @api.model
    def _default_glass_vendor(self):
        """The glass vendor (a setting on the order comes with the stack):
        for now the supplier the first list was loaded for."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'aw_fenestration.glass_vendor_seeded')
        partner = self.env['res.partner'].with_context(active_test=False)
        return partner.browse(int(value)).exists() if value \
            else partner.browse()

    @api.model
    def _seed_glass_sheet(self):
        """The unit, the attributes, the Glass Sheet product and each
        type's colour and kind. Fill-only and idempotent: whatever exists
        is kept, and values added later are added to the product."""
        env = self.env
        Data = env['ir.model.data'].sudo()

        def named(name, model, make):
            found = env.ref('aw_fenestration_core.' + name,
                            raise_if_not_found=False)
            if found:
                return found
            record = make()
            Data.create({'module': 'aw_fenestration_core', 'name': name,
                         'model': model, 'res_id': record.id,
                         'noupdate': True})
            return record

        # Odoo ships ft² (0.092903 m²) switched off; use that one.
        uom = env.ref('uom.product_uom_square_foot',
                      raise_if_not_found=False)
        if uom and not uom.active:
            uom.active = True
        if not uom:
            uom = env['uom.uom'].create({
                'name': 'ft²', 'relative_factor': 0.092903,
                'relative_uom_id': env.ref('uom.product_uom_square_meter').id})

        attributes = {}
        for key, label, values in ATTRIBUTES:
            attribute = named(
                'aw_attribute_glass_%s' % key, 'product.attribute',
                lambda label=label: env['product.attribute'].create({
                    'name': label, 'create_variant': 'dynamic',
                    'display_type': 'radio'}))
            have = {v.name for v in attribute.value_ids}
            for value in values:
                if value not in have:
                    env['product.attribute.value'].create({
                        'attribute_id': attribute.id, 'name': value})
            attributes[key] = attribute

        # Each type's colour and kind, where they are not set yet.
        by_colour = {v.name: v for v in attributes['colour'].value_ids}
        by_kind = {v.name: v for v in attributes['kind'].value_ids}
        for glass_type in self.with_context(active_test=False).search([]):
            if glass_type.colour_id and glass_type.kind_id:
                continue
            try:
                colour, kind = type_parts(glass_type.name)
            except ValueError:
                continue
            glass_type.write({'colour_id': by_colour[colour].id,
                              'kind_id': by_kind[kind].id})

        category = env.ref('aw_fenestration_core.product_category_glass')

        def make_sheet():
            return env['product.template'].create({
                'name': 'Glass Sheet', 'type': 'consu', 'is_storable': False,
                'sale_ok': False, 'purchase_ok': True, 'list_price': 0.0,
                'standard_price': 0.0, 'uom_id': uom.id,
                'categ_id': category.id,
                'attribute_line_ids': [(0, 0, {
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, attribute.value_ids.ids)]})
                    for attribute in attributes.values()]})

        sheet = named('product_glass_sheet', 'product.template', make_sheet)
        # values added to an attribute later reach the product too
        for attribute in attributes.values():
            line = sheet.attribute_line_ids.filtered(
                lambda l, a=attribute: l.attribute_id == a)[:1]
            missing = attribute.value_ids - line.value_ids
            if line and missing:
                line.write({'value_ids': [(4, v.id) for v in missing]})
        return sheet

    def _variant_for(self, mm, create=True):
        """The Glass Sheet variant of this type at `mm`, made on demand
        (dynamic variants). Nothing when the type has no colour or kind, or
        the thickness is not one the product carries: no guessing."""
        self.ensure_one()
        sheet = self._glass_sheet()
        thickness_attr = self._glass_attribute('thickness')
        thickness = thickness_attr.value_ids.filtered(
            lambda v: thickness_mm(v.name) == float(mm))[:1]
        product = self.env['product.product']
        if not (sheet and self.colour_id and self.kind_id and thickness):
            return product
        wanted = self.colour_id | self.kind_id | thickness
        combination = sheet.attribute_line_ids.product_template_value_ids \
            .filtered(lambda v: v.product_attribute_value_id in wanted)
        if len(combination) != 3:
            return product
        if create:
            return sheet._create_product_variant(combination)
        return sheet._get_variant_for_combination(combination)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    aw_glass_type_id = fields.Many2one(
        'aw.glass.type', string='Glass type', compute='_compute_aw_glass')
    aw_glass_thickness_mm = fields.Float(
        string='Glass thickness (mm)', compute='_compute_aw_glass')
    aw_glass_rate = fields.Float(
        string='Rate / sqft', compute='_compute_aw_glass', digits='Product Price',
        help="The glass vendor's rate in force today for this type and "
             "thickness; 0 when there is none.")
    aw_glass_rate_date = fields.Date(
        string='Rate of', compute='_compute_aw_glass')

    def _aw_glass_key(self):
        """(glass type, mm) of a Glass Sheet variant, else (empty, 0.0)."""
        self.ensure_one()
        Type = self.env['aw.glass.type']
        if self.product_tmpl_id != Type._glass_sheet():
            return Type, 0.0
        values = self.product_template_variant_value_ids \
            .product_attribute_value_id
        colour = values.filtered(
            lambda v: v.attribute_id == Type._glass_attribute('colour'))
        kind = values.filtered(
            lambda v: v.attribute_id == Type._glass_attribute('kind'))
        thickness = values.filtered(
            lambda v: v.attribute_id == Type._glass_attribute('thickness'))
        mm = thickness_mm(thickness[:1].name) or 0.0
        glass_type = Type.search([('colour_id', '=', colour.id),
                                  ('kind_id', '=', kind.id)], limit=1) \
            if colour and kind else Type
        return glass_type, mm

    @api.depends('product_template_variant_value_ids')
    def _compute_aw_glass(self):
        today = fields.Date.context_today(self)
        Rate = self.env['aw.glass.rate']
        vendor = self.env['aw.glass.type']._default_glass_vendor()
        for product in self:
            glass_type, mm = product._aw_glass_key()
            rate = Rate._rate_for(glass_type, mm, today, vendor)
            product.aw_glass_type_id = glass_type
            product.aw_glass_thickness_mm = mm
            product.aw_glass_rate = rate.price if rate else 0.0
            product.aw_glass_rate_date = rate.date_from if rate else False


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    aw_is_glass_sheet = fields.Boolean(compute='_compute_aw_is_glass_sheet')
    aw_priced_by_rates = fields.Boolean(
        compute='_compute_aw_priced_by_rates',
        help="A profile or the Glass Sheet: priced from dated vendor rates, "
             "so there is no sales price, cost or Prices tab to fill in.")

    @api.depends()
    def _compute_aw_is_glass_sheet(self):
        sheet = self.env['aw.glass.type']._glass_sheet()
        for template in self:
            template.aw_is_glass_sheet = bool(sheet) and template == sheet

    @api.depends('categ_id')
    def _compute_aw_priced_by_rates(self):
        self._compute_aw_is_profile()
        self._compute_aw_is_glass_sheet()
        for template in self:
            template.aw_priced_by_rates = (
                template.aw_is_profile or template.aw_is_glass_sheet)

    def _aw_glass_rates_table_data(self):
        """The Glass Sheet's rates table: a row per glass type, a column
        per thickness, a cell per vendor, the rate in force today. The
        payload is the profile table's, with the labels changed."""
        self.ensure_one()
        Type = self.env['aw.glass.type']
        today = fields.Date.context_today(self)
        rates = self.env['aw.glass.rate'].search([
            ('date_from', '<=', today),
            '|', ('date_to', '=', False), ('date_to', '>=', today),
        ], order='date_from desc, id desc')
        cells, seen = [], set()
        for rate in rates:
            key = (rate.glass_type_id.id, rate.thickness_mm, rate.vendor_id.id)
            if key in seen:
                continue
            seen.add(key)
            cells.append({'t': key[0], 'f': key[1], 'v': key[2],
                          'price': rate.price, 'date': str(rate.date_from)})
        kinds = {name: index for index, name in enumerate(KINDS)}
        colours = {name: index for index, name in enumerate(COLOURS)}
        types = rates.glass_type_id.sorted(lambda t: (
            kinds.get(t.kind_id.name, 99), colours.get(t.colour_id.name, 99),
            t.id))
        thicknesses = sorted({rate.thickness_mm for rate in rates})
        vendors = rates.vendor_id.sorted(lambda p: (p.name or '').lower())
        variants = set()
        for variant in self.product_variant_ids:
            glass_type, mm = variant._aw_glass_key()
            if glass_type:
                variants.add('%s-%g' % (glass_type.id, mm))
        default = Type._default_glass_vendor()
        return {
            'kind': 'glass', 'row_label': 'Glass type', 'unit': 'PKR / sqft',
            'vendors': [{'id': v.id, 'name': v.name} for v in vendors],
            'default_vendor_id': default.id if default in vendors else 0,
            'thicknesses': [{'id': t.id, 'name': t.name} for t in types],
            'finishes': [{'id': mm, 'name': thickness_name(mm), 'color': '',
                          'names': []} for mm in thicknesses],
            'cells': cells,
            'variants': sorted(variants),
        }

    def aw_glass_rates_action(self, glass_type_id, thickness_mm, vendor_id):
        """The history behind one cell of the Glass Sheet table."""
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'aw_fenestration_core.action_aw_glass_rate')
        glass_type = self.env['aw.glass.type'].browse(glass_type_id)
        action['name'] = '%s %s' % (glass_type.name, thickness_name(thickness_mm))
        action['domain'] = [('glass_type_id', '=', glass_type_id),
                            ('thickness_mm', '=', thickness_mm),
                            ('vendor_id', '=', vendor_id)]
        action['context'] = {}
        action['views'] = [(False, 'list')]
        return action
