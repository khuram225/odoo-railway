# -*- coding: utf-8 -*-
"""Glass as products: the Glass Sheet, its variants, and the rates table."""
import os
from datetime import date

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGlassProducts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Type = env['aw.glass.type']
        cls.Type._seed_glass_types()
        cls.Type._seed_glass_vendor()
        cls.Type._seed_glass_sheet()
        cls.sheet = cls.Type._glass_sheet()
        cls.vendor = cls.Type._default_glass_vendor()

    def _apply_real_list(self):
        path = os.path.join(os.path.dirname(__file__), 'data',
                            'ghani_glass_2026_07_01.txt')
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        rate_list = self.env['aw.vendor.rate.list'].create({
            'kind': 'glass', 'vendor_id': self.vendor.id,
            'date': date(2026, 7, 1), 'paste_text': text})
        rate_list.action_parse_paste()
        rate_list.action_apply()
        return rate_list

    def test_the_glass_sheet_product_and_its_unit(self):
        sheet = self.sheet
        self.assertTrue(sheet)
        self.assertEqual(sheet.name, 'Glass Sheet')
        self.assertEqual(sheet.uom_id.name, 'ft²')
        self.assertTrue(sheet.uom_id.active)
        self.assertEqual(sheet.uom_id.relative_uom_id.name, 'm²')
        self.assertAlmostEqual(sheet.uom_id.relative_factor, 0.092903)
        self.assertFalse(sheet.sale_ok)
        self.assertEqual(sheet.list_price, 0.0)
        self.assertEqual(
            sheet.categ_id,
            self.env.ref('aw_fenestration_core.product_category_glass'))
        attributes = sheet.attribute_line_ids.mapped('attribute_id')
        self.assertEqual(sorted(attributes.mapped('name')),
                         ['Colour', 'Glass Thickness', 'Type'])
        self.assertTrue(all(a.create_variant == 'dynamic' for a in attributes))
        # no variants exist until somebody asks for one
        self.assertTrue(sheet.aw_is_glass_sheet)
        self.assertTrue(sheet.aw_priced_by_rates)

    def test_every_type_has_a_colour_and_a_kind(self):
        for glass_type in self.Type.search([]):
            self.assertTrue(glass_type.colour_id, glass_type.name)
            self.assertTrue(glass_type.kind_id, glass_type.name)
        by = {t.name: (t.colour_id.name, t.kind_id.name)
              for t in self.Type.search([])}
        self.assertEqual(by['Clear'], ('Clear', 'Plain'))
        self.assertEqual(by['Ref. Grey'], ('Grey', 'Reflective'))
        self.assertEqual(by['WC Green'], ('Green', 'WC'))
        self.assertEqual(by['CC Grey'], ('Grey', 'CC'))

    def test_a_type_and_thickness_name_one_variant_made_once(self):
        grey = self.Type.search([('name', '=', 'Grey')])
        variant = grey._variant_for(6)
        self.assertEqual(variant.product_tmpl_id, self.sheet)
        self.assertEqual(grey._variant_for(6), variant)
        self.assertNotEqual(grey._variant_for(8), variant)
        self.assertEqual(variant._aw_glass_key(), (grey, 6.0))
        # a thickness the product does not carry gives nothing, not a guess
        self.assertFalse(grey._variant_for(7))
        # a different kind of the same colour is a different variant
        ref_grey = self.Type.search([('name', '=', 'Ref. Grey')])
        self.assertNotEqual(ref_grey._variant_for(6), variant)

    def test_the_variant_rate_is_the_dated_vendor_rate(self):
        self._apply_real_list()
        grey = self.Type.search([('name', '=', 'Grey')])
        self.assertEqual(grey._variant_for(6).aw_glass_rate, 399.91)
        self.assertEqual(
            self.Type.search([('name', '=', 'Ref. Grey')])
            ._variant_for(6).aw_glass_rate, 482.32)
        self.assertEqual(
            self.Type.search([('name', '=', 'WC Green')])
            ._variant_for(6).aw_glass_rate, 248.64)
        clear = self.Type.search([('name', '=', 'Clear')])._variant_for(6)
        self.assertEqual(clear.aw_glass_rate, 265.52)
        self.assertEqual(clear.aw_glass_rate_date, date(2026, 7, 1))

    def test_every_present_glass_rate_maps_to_exactly_one_variant(self):
        self._apply_real_list()
        rates = self.env['aw.glass.rate'].search([])
        self.assertEqual(len(rates), 61)
        seen, unmapped = {}, []
        for rate in rates:
            variant = rate.glass_type_id._variant_for(rate.thickness_mm)
            if not variant:
                unmapped.append((rate.glass_type_id.name, rate.thickness_mm))
                continue
            self.assertNotIn(variant.id, seen, 'two rates, one variant')
            seen[variant.id] = rate
            self.assertEqual(variant._aw_glass_key(),
                             (rate.glass_type_id, rate.thickness_mm))
            self.assertEqual(variant.aw_glass_rate, rate.price)
        self.assertEqual(unmapped, [])
        self.assertEqual(len(seen), 61)

    def test_the_rates_table_has_types_as_rows_and_thicknesses_as_columns(self):
        self._apply_real_list()
        data = self.sheet._aw_rates_table_data()
        self.assertEqual(data['kind'], 'glass')
        self.assertEqual(data['unit'], 'PKR / sqft')
        self.assertEqual(len(data['thicknesses']), 19)       # rows: types
        self.assertEqual([c['name'] for c in data['finishes']],
                         ['2 mm', '3 mm', '4 mm', '5 mm', '6 mm', '8 mm',
                          '10 mm', '12 mm'])
        self.assertEqual(len(data['cells']), 61)
        self.assertEqual([v['id'] for v in data['vendors']], [self.vendor.id])
        self.assertEqual(data['default_vendor_id'], self.vendor.id)
        # a variant that exists is flagged for the dot in an empty cell
        grey = self.Type.search([('name', '=', 'Grey')])
        grey._variant_for(6)
        data = self.sheet._aw_rates_table_data()
        self.assertIn('%s-%g' % (grey.id, 6.0), data['variants'])
        # and the field the widget reads is the same payload
        self.assertEqual(self.sheet.aw_rates_table['kind'], 'glass')

    def test_a_cell_opens_that_rates_history(self):
        self._apply_real_list()
        grey = self.Type.search([('name', '=', 'Grey')])
        action = self.sheet.aw_glass_rates_action(grey.id, 6.0, self.vendor.id)
        found = self.env['aw.glass.rate'].search(action['domain'])
        self.assertEqual(found.mapped('price'), [399.91])
        self.assertTrue(action['views'])

    def test_the_glass_sheet_form_hides_price_cost_and_prices_tab(self):
        arch = etree.fromstring(
            self.env['product.template'].get_view(view_type='form')['arch'])
        rates = arch.xpath("//page[@name='aw_rates']")[0]
        self.assertIn('aw_priced_by_rates', rates.get('invisible'))
        for xpath in ("//page[@name='sales_price']",
                      "//div[@name='list_price_uom']",
                      "//span[@name='sale_option']"):
            self.assertIn('aw_priced_by_rates',
                          arch.xpath(xpath)[0].get('invisible'), xpath)
        # profiles and a plain product keep their own answers
        self.assertFalse(self.env['product.template'].create(
            {'name': 'Plain'}).aw_priced_by_rates)

    def test_the_seed_is_idempotent(self):
        sheet = self.Type._seed_glass_sheet()
        self.assertEqual(sheet, self.sheet)
        self.assertEqual(self.env['product.template'].search_count(
            [('name', '=', 'Glass Sheet')]), 1)
        self.assertEqual(self.env['product.attribute'].search_count(
            [('name', '=', 'Glass Thickness')]), 1)
