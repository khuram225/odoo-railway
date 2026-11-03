# -*- coding: utf-8 -*-
"""The one-time merge of the legacy "Chawla" partner into CHAWLA ALUMINIUM.

Same price -> the old copy is dropped, so the survivor's earlier start
date stays; a different price -> both kept as a dated chain; only the old
partner has one -> it moves. Series defaults, orders (confirmed ones
included, without a re-cost) and the legacy parameter follow, the old
partner is archived rather than deleted, and a second run does nothing.
"""
import json
import unittest
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChawlaMerge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Partner = env['res.partner'].with_context(active_test=False)
        if Partner.search_count([('name', '=ilike', 'CHAWLA ALUMINIUM')]):
            raise unittest.SkipTest("A real CHAWLA ALUMINIUM exists here")
        cls.old = Partner.create({'name': 'Chawla', 'is_company': True})
        cls.new = Partner.create(
            {'name': 'CHAWLA ALUMINIUM', 'is_company': True})
        cls.other = Partner.create({'name': 'Other (merge test)'})
        param = env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.legacy_rate_vendor_id', cls.old.id)
        param.set_param('aw_fenestration.chawla_vendor_merged', '')

        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        thick_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        cls.finishes = finish_attr.value_ids[:3]
        cls.standard = env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_standard')
        cls.product = env['product.template'].create({
            'name': 'MERGE-1', 'default_code': 'MERGE-1',
            'categ_id': env.ref(
                'aw_fenestration_core.product_category_profiles').id,
            'attribute_line_ids': [
                (0, 0, {'attribute_id': thick_attr.id,
                        'value_ids': [(6, 0, cls.standard.ids)]}),
                (0, 0, {'attribute_id': finish_attr.id,
                        'value_ids': [(6, 0, cls.finishes.ids)]}),
            ]})
        same, differs, only_old = cls.finishes
        cls.rates = {}
        for name, vendor, finish, price, start in (
                ('new_same', cls.new, same, 100.0, date(2026, 1, 1)),
                ('old_same', cls.old, same, 100.0, date(2026, 9, 24)),
                ('new_diff', cls.new, differs, 100.0, date(2026, 1, 1)),
                ('old_diff', cls.old, differs, 120.0, date(2026, 9, 24)),
                ('old_only', cls.old, only_old, 90.0, date(2026, 9, 24)),
                ('other', cls.other, same, 55.0, date(2026, 9, 24))):
            cls.rates[name] = env['aw.profile.rate'].create({
                'product_tmpl_id': cls.product.id,
                'thickness_id': cls.standard.id, 'finish_id': finish.id,
                'vendor_id': vendor.id, 'price': price,
                'date_from': start})
        # B-6 Normal: a different price at the old partner is test data
        cls.normal = thick_attr.value_ids.filtered(
            lambda v: v.name == 'Normal')[:1]
        cls.b6 = env['product.template'].create({
            'name': 'B-6 (merge test)', 'default_code': 'B-6',
            'categ_id': cls.product.categ_id.id,
            'attribute_line_ids': [
                (0, 0, {'attribute_id': thick_attr.id,
                        'value_ids': [(6, 0, (cls.normal or cls.standard).ids)]}),
                (0, 0, {'attribute_id': finish_attr.id,
                        'value_ids': [(6, 0, same.ids)]})]})
        cls.b6_thickness = cls.normal or cls.standard
        for name, vendor, price, start in (
                ('b6_new', cls.new, 112.0, date(2026, 1, 1)),
                ('b6_old_sep', cls.old, 112.0, date(2026, 9, 24)),
                ('b6_old_oct', cls.old, 122.0, date(2026, 10, 1))):
            cls.rates[name] = env['aw.profile.rate'].create({
                'product_tmpl_id': cls.b6.id,
                'thickness_id': cls.b6_thickness.id, 'finish_id': same.id,
                'vendor_id': vendor.id, 'price': price, 'date_from': start})
        cls.template = env['aw.window.template'].search([], limit=1)
        if cls.template:
            cls.template.default_vendor_id = cls.old
        customer = Partner.create({'name': 'Merge customer'})
        cls.draft = env['sale.order'].create({
            'partner_id': customer.id, 'aw_profile_vendor_id': cls.old.id})
        cls.confirmed = env['sale.order'].create({
            'partner_id': customer.id, 'aw_profile_vendor_id': cls.old.id})
        env.cr.execute(
            "UPDATE sale_order SET state = 'sale' WHERE id = %s",
            (cls.confirmed.id,))
        cls.confirmed.invalidate_recordset(['state'])
        cls.confirmed_total = cls.confirmed.amount_total

    def test_merge(self):
        Rate = self.env['aw.profile.rate'].with_context(active_test=False)
        report = Rate._merge_chawla_vendor()
        self.assertEqual(report['dropped'], 3)
        self.assertEqual(report['moved'], 2)
        self.assertEqual(report['chained_keys'], 1)

        # same price: the old copy is gone, the survivor's date stands
        self.assertFalse(self.rates['old_same'].exists())
        self.assertEqual(self.rates['new_same'].date_from, date(2026, 1, 1))
        self.assertFalse(self.rates['new_same'].date_to)
        # different price: both kept, the older closed the day before
        self.assertEqual(self.rates['old_diff'].vendor_id, self.new)
        self.assertEqual(self.rates['new_diff'].date_to, date(2026, 9, 23))
        self.assertFalse(self.rates['old_diff'].date_to)
        # only the old partner: moved unchanged
        self.assertEqual(self.rates['old_only'].vendor_id, self.new)
        self.assertEqual(self.rates['old_only'].price, 90.0)
        self.assertEqual(self.rates['old_only'].date_from, date(2026, 9, 24))
        # B-6 Normal test values: both old rows gone, only 2026-01-01 stays
        self.assertFalse(self.rates['b6_old_sep'].exists())
        self.assertFalse(self.rates['b6_old_oct'].exists())
        self.assertEqual(self.rates['b6_new'].price, 112.0)
        self.assertFalse(self.rates['b6_new'].date_to)
        # another vendor's rate is untouched
        self.assertEqual(self.rates['other'].vendor_id, self.other)
        self.assertEqual(self.rates['other'].price, 55.0)
        # nothing is left on the old partner
        self.assertFalse(Rate.search_count([('vendor_id', '=', self.old.id)]))

        # follow-ups
        if self.template:
            self.assertEqual(self.template.default_vendor_id, self.new)
        self.assertEqual(self.draft.aw_profile_vendor_id, self.new)
        self.assertEqual(self.confirmed.aw_profile_vendor_id, self.new)
        self.assertEqual(self.confirmed.state, 'sale')
        self.assertEqual(self.confirmed.amount_total, self.confirmed_total)
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param(
                'aw_fenestration.legacy_rate_vendor_id'), str(self.new.id))
        self.assertFalse(self.old.active)
        self.assertTrue(self.old.exists())
        stored = json.loads(self.env['ir.config_parameter'].sudo().get_param(
            'aw_fenestration.chawla_vendor_merged'))
        self.assertEqual(stored['dropped'], 3)

        # a second run changes nothing
        self.assertFalse(Rate._merge_chawla_vendor())
        self.assertEqual(
            Rate.search_count([('vendor_id', '=', self.new.id)]), 5)
