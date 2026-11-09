# -*- coding: utf-8 -*-
"""Current cost of a profile variant: the newer of list and LPP."""
import unittest
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCurrentCost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        category = env.ref('aw_fenestration_core.product_category_profiles')
        thickness_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        cls.template = env['product.template']
        for template in env['product.template'].search(
                [('categ_id', 'child_of', category.id)]):
            lines = template.attribute_line_ids
            if len(lines.filtered(
                    lambda l: l.attribute_id == finish_attr).value_ids) >= 2 \
                    and lines.filtered(
                        lambda l: l.attribute_id == thickness_attr).value_ids:
                cls.template = template
                break
        if not cls.template:
            raise unittest.SkipTest("No profile with two finishes here")
        lines = cls.template.attribute_line_ids
        cls.thickness = lines.filtered(
            lambda l: l.attribute_id == thickness_attr).value_ids[0]
        cls.f1, cls.f2 = lines.filtered(
            lambda l: l.attribute_id == finish_attr).value_ids[:2]
        cls.vendor = env['res.partner'].create({'name': 'Cost vendor'})
        cls.today = fields.Date.context_today(env['res.partner'])
        env['aw.profile.rate'].create({
            'product_tmpl_id': cls.template.id,
            'thickness_id': cls.thickness.id, 'finish_id': cls.f1.id,
            'vendor_id': cls.vendor.id, 'price': 765.0,
            'date_from': cls.today - timedelta(days=100)})
        cls.v1 = env['aw.profile.section.line']._variant_for(
            cls.template, cls.thickness, cls.f1)
        cls.v2 = env['aw.profile.section.line']._variant_for(
            cls.template, cls.thickness, cls.f2)
        env.flush_all()

    def _lpp(self, price, days_ago, finish=None):
        return self.env['aw.profile.lpp'].create({
            'vendor_id': self.vendor.id,
            'product_tmpl_id': self.template.id,
            'thickness_id': self.thickness.id,
            'finish_id': (finish or self.f1).id, 'bar_length_ft': 18.0,
            'price_ft': price, 'date': self.today - timedelta(days=days_ago)})

    def _cost(self, variant=None):
        return (variant or self.v1)._aw_current_cost(vendor=self.vendor)

    def test_a_list_rate_alone_is_the_cost(self):
        result = self._cost()
        self.assertEqual(result['kind'], 'list')
        self.assertEqual(result['cost'], 765.0)
        self.assertTrue(result['text'].startswith('list 765 from '))

    def test_a_newer_last_purchase_price_wins(self):
        self._lpp(812.0, 10)
        result = self._cost()
        self.assertEqual((result['kind'], result['cost']), ('lpp', 812.0))
        self.assertTrue(result['text'].startswith('LPP 812 from '))

    def test_an_older_last_purchase_price_loses_to_the_list(self):
        self._lpp(812.0, 150)           # the list rate is 100 days old
        result = self._cost()
        self.assertEqual((result['kind'], result['cost']), ('list', 765.0))

    def test_the_last_price_wins_on_the_same_day(self):
        self._lpp(812.0, 100)
        self.assertEqual(self._cost()['kind'], 'lpp')

    def test_the_age_limit_ignores_an_old_last_price(self):
        self._lpp(812.0, 60)
        self.assertEqual(self._cost()['kind'], 'lpp')     # within 180 days
        with patch.object(self.registry['product.product'],
                          '_aw_lpp_max_age_days', lambda self: 30):
            result = self._cost()
        self.assertEqual(result['kind'], 'list', result['text'])
        self.assertIn('ignored', result['text'])

    def test_the_maximum_age_is_a_setting_with_a_default_of_180_days(self):
        product = self.env['product.product']
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.lpp_max_age_days', '')
        self.assertEqual(product._aw_lpp_max_age_days(), 180)
        param.set_param('aw_fenestration.lpp_max_age_days', '30')
        self.assertEqual(product._aw_lpp_max_age_days(), 30)

    def test_only_a_last_price_is_the_cost(self):
        self._lpp(900.0, 5, finish=self.f2)         # no list rate for f2
        result = self._cost(self.v2)
        self.assertEqual((result['kind'], result['cost']), ('lpp', 900.0))

    def test_no_rate_and_no_last_price_is_zero(self):
        result = self._cost(self.v2)
        self.assertEqual((result['kind'], result['cost']), ('none', 0.0))

    def test_an_exact_last_price_beats_a_list_rate_found_by_fallback(self):
        other = self.env['res.partner'].create({'name': 'Fallback vendor'})
        # the vendor lists the profile by thickness only (any finish)
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': self.template.id,
            'thickness_id': self.thickness.id, 'vendor_id': other.id,
            'price': 700.0, 'date_from': self.today})
        self.env['aw.profile.lpp'].create({
            'vendor_id': other.id, 'product_tmpl_id': self.template.id,
            'thickness_id': self.thickness.id, 'finish_id': self.f1.id,
            'bar_length_ft': 18.0, 'price_ft': 650.0,
            'date': self.today - timedelta(days=20)})
        result = self.v1._aw_current_cost(vendor=other)
        self.assertEqual((result['kind'], result['cost']), ('lpp', 650.0))
        self.assertIn('list was an estimate', result['text'])

    def test_the_variant_shows_its_cost_and_source(self):
        self._lpp(812.0, 1)
        self.v1.invalidate_recordset(
            ['aw_current_cost', 'aw_current_cost_source'])
        # the default vendor is not this test's vendor: the field must
        # still compute without error
        self.assertTrue(isinstance(self.v1.aw_current_cost, float))
        self.assertTrue(self.v1.aw_current_cost_source)

    def test_the_template_list_shows_a_range_not_zero(self):
        self.v1.sudo().standard_price = 765.0
        self.v2.sudo().standard_price = 884.0
        self.template.invalidate_recordset(['aw_cost_range'])
        self.assertEqual(self.template.aw_cost_range, 'from 765 to 884')
        self.v2.sudo().standard_price = 765.0
        self.template.invalidate_recordset(['aw_cost_range'])
        self.assertEqual(self.template.aw_cost_range, '765')

    def test_the_rates_tab_carries_the_current_cost_of_a_cell(self):
        self._lpp(812.0, 2)
        data = self.template._aw_rates_table_data()
        mine = [c for c in data['current'] if c['v'] == self.vendor.id
                and c['f'] == self.f1.id and c['t'] == self.thickness.id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]['cost'], 812.0)
        self.assertTrue(mine[0]['text'].startswith('LPP 812'))
