# -*- coding: utf-8 -*-
"""Changing an order's Profile vendor re-costs its windows.

Before this, the vendor was read only when a window was exploded, so
switching it on a quotation changed nothing until each window was saved
again: the Pricing tab compared vendors live while the stored cost, and
the price on the order line, stayed at the old vendor's.
"""
import unittest
from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestVendorRecost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest(
                "No glazing family with a configured profile system")
        cls.chawla = env['res.partner'].create({'name': 'Chawla (test)'})
        cls.premium = env['res.partner'].create({'name': 'Premium (test)'})
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Recost customer'}).id,
            'aw_default_series_id': series.id,
            'aw_profile_vendor_id': cls.chawla.id,
        })
        cls.design = cls.order._create_fenestration_position(
            series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        keys = cls.design._profile_rate_keys()
        if not keys:
            raise unittest.SkipTest("The test window has no profile lines")
        # A rate at both vendors for every profile the window uses, the
        # Premium one twice the Chawla one, so the switch must show.
        seen = set()
        for _line, template, thickness, finish in keys:
            key = (template.id, thickness.id if thickness else 0,
                   finish.id if finish else 0)
            if key in seen:
                continue
            seen.add(key)
            for vendor, price in ((cls.chawla, 100.0), (cls.premium, 200.0)):
                env['aw.profile.rate'].create({
                    'product_tmpl_id': template.id,
                    'thickness_id': thickness.id if thickness else False,
                    'finish_id': finish.id if finish else False,
                    'vendor_id': vendor.id, 'price': price,
                    'date_from': date(2000, 1, 1)})
        cls.design._explode()
        cls.design._sync_sale_order_line()

    def test_switching_vendor_reprices_the_line_and_says_so(self):
        line = self.design.sale_order_line_id
        before = line.price_unit
        self.assertTrue(before)
        self.order.write({'aw_profile_vendor_id': self.premium.id})
        self.assertGreater(line.price_unit, before)
        bodies = ' '.join(self.order.message_ids.mapped('body'))
        self.assertIn('Profile vendor changed to Premium (test)', bodies)
        self.assertIn('1 windows re-costed', bodies)
        # every profile has a Premium rate, so none is named missing
        self.assertFalse(self.design._missing_rate_info()[0])

    def test_no_rate_falls_back_to_the_series_default_and_says_so(self):
        Rate = self.env['aw.profile.rate']
        self.design.template_id.default_vendor_id = self.chawla
        self.order.write({'aw_profile_vendor_id': self.premium.id})
        Rate.search([('vendor_id', '=', self.premium.id)]).unlink()
        self.design._explode()
        texts, line_ids = self.design._missing_rate_info()
        self.assertTrue(texts)
        for text in texts:
            self.assertIn('no Premium (test) rate, Chawla (test) rate used',
                          text)
            self.assertNotIn('cost field', text)
        lines = self.design.bom_line_ids.filtered(
            lambda l: l.id in line_ids)
        self.assertTrue(lines)
        self.assertTrue(all(l.line_cost for l in lines))
        self.assertTrue(all('Chawla (test) rate used' in l.cost_note
                            for l in lines))

    def test_no_rate_anywhere_is_zero_and_incomplete(self):
        self.design.template_id.default_vendor_id = self.chawla
        self.order.write({'aw_profile_vendor_id': self.premium.id})
        self.env['aw.profile.rate'].search([
            ('vendor_id', 'in', [self.premium.id, self.chawla.id])]).unlink()
        self.design._explode()
        texts, line_ids = self.design._missing_rate_info()
        self.assertTrue(texts)
        for text in texts:
            self.assertIn('price incomplete', text)
            self.assertNotIn('cost field', text)
        lines = self.design.bom_line_ids.filtered(
            lambda l: l.id in line_ids)
        self.assertFalse(any(l.line_cost for l in lines))
        self.assertTrue(all('price incomplete' in l.cost_note for l in lines))
