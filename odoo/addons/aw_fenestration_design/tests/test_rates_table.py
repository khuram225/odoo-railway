# -*- coding: utf-8 -*-
"""The cross-table of current rates on a profile's product form."""
from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesTable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.a = env['res.partner'].create({'name': 'Table vendor A'})
        cls.b = env['res.partner'].create({'name': 'Table vendor B'})
        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        thick_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        cls.finishes = finish_attr.value_ids[:2]
        cls.standard = env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_standard')
        categ = env.ref('aw_fenestration_core.product_category_profiles')
        attrs = [
            (0, 0, {'attribute_id': thick_attr.id,
                    'value_ids': [(6, 0, cls.standard.ids)]}),
            (0, 0, {'attribute_id': finish_attr.id,
                    'value_ids': [(6, 0, cls.finishes.ids)]})]
        cls.both = env['product.template'].create({
            'name': 'TBL-BOTH', 'default_code': 'TBL-BOTH',
            'aw_catalogue_code': 'TBL-BOTH', 'categ_id': categ.id,
            'attribute_line_ids': attrs})
        cls.only_a = env['product.template'].create({
            'name': 'TBL-A', 'default_code': 'TBL-A',
            'aw_catalogue_code': 'TBL-A', 'categ_id': categ.id,
            'attribute_line_ids': [(0, 0, dict(attrs[0][2])),
                                   (0, 0, dict(attrs[1][2]))]})
        cls.plain = env['product.template'].create({'name': 'Not a profile'})
        first, second = cls.finishes
        rates = env['aw.profile.rate']
        long_ago = date(2020, 1, 1)
        for tmpl, vendor, finish, price in (
                (cls.both, cls.a, first, 100.0),
                (cls.both, cls.b, first, 90.0),
                (cls.both, cls.a, second, 110.0),
                (cls.only_a, cls.a, first, 80.0)):
            rates.create({
                'product_tmpl_id': tmpl.id, 'thickness_id': cls.standard.id,
                'finish_id': finish.id, 'vendor_id': vendor.id,
                'price': price, 'date_from': long_ago})
        # a superseded and a future rate must not appear
        rates.create({
            'product_tmpl_id': cls.both.id, 'thickness_id': cls.standard.id,
            'finish_id': first.id, 'vendor_id': cls.b.id, 'price': 1.0,
            'date_from': date.today() + timedelta(days=30)})

    def test_both_vendors_in_one_table(self):
        data = self.both._aw_rates_table_data()
        self.assertEqual({v['name'] for v in data['vendors']},
                         {'Table vendor A', 'Table vendor B'})
        self.assertEqual([t['id'] for t in data['thicknesses']],
                         [self.standard.id])
        self.assertEqual({f['id'] for f in data['finishes']},
                         set(self.finishes.ids))
        first = self.finishes[0]
        at_first = {c['v']: c['price'] for c in data['cells']
                    if c['f'] == first.id}
        self.assertEqual(at_first, {self.a.id: 100.0, self.b.id: 90.0})
        self.assertEqual(len(data['cells']), 3)

    def test_a_profile_with_one_vendor_shows_only_it(self):
        data = self.only_a._aw_rates_table_data()
        self.assertEqual([v['id'] for v in data['vendors']], [self.a.id])
        self.assertEqual(len(data['cells']), 1)

    def test_empty_cell_and_variant_dot(self):
        second = self.finishes[1]
        self.both._create_variant_ids()
        data = self.both._aw_rates_table_data()
        # no rate at vendor B for the second finish, but the combination
        # is in the table, and the variant (if made) is flagged
        self.assertFalse([c for c in data['cells']
                          if c['f'] == second.id and c['v'] == self.b.id])
        self.assertEqual(
            '%s-%s' % (self.standard.id, second.id) in data['variants'],
            bool(self.both.product_variant_ids.filtered(
                lambda v: v._aw_attribute_values()[1] == second)))

    def test_default_vendor_and_flags(self):
        self.assertTrue(self.both.aw_is_profile)
        self.assertFalse(self.plain.aw_is_profile)
        self.assertEqual(self.plain.aw_rates_table['vendors'], [])

    def test_click_opens_that_cells_history(self):
        first = self.finishes[0]
        action = self.both.aw_rates_action(
            self.standard.id, first.id, self.b.id)
        found = self.env['aw.profile.rate'].search(action['domain'])
        self.assertTrue(found)
        self.assertEqual(set(found.mapped('vendor_id')), self.b)
        self.assertEqual(set(found.mapped('finish_id')), first)
        self.assertTrue(action['views'])
