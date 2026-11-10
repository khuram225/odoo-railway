# -*- coding: utf-8 -*-
"""The cost rule preview: what switching it on would do, writing nothing."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestCostPreview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.family, cls.series = seeded_family_series(cls.env)
        cls.vendor = cls.env['res.partner'].create({'name': 'Preview vendor'})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Preview customer'})
        cls.today = fields.Date.context_today(cls.env['res.partner'])
        cls.env.flush_all()
        cls.env.invalidate_all()

    def _make(self, location='Hall'):
        env = self.env
        order = env['sale.order'].create({
            'partner_id': self.customer.id,
            'aw_default_series_id': self.series.id,
            'aw_profile_vendor_id': self.vendor.id})
        design = order._create_fenestration_position(
            self.series, family=self.family, location=location)
        design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0,
                'leaf_type_id': self.series.leaf_type_ids[0].id}
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        templates = design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.product_id
        ).product_id.product_tmpl_id
        for template in templates:
            env['aw.profile.rate'].create({
                'product_tmpl_id': template.id, 'vendor_id': self.vendor.id,
                'price': 10.0, 'date_from': self.today - timedelta(days=30)})
        design._explode()
        self.assertTrue(design.cost_total, "the window was not costed")
        return order, design

    def _last_prices(self, design, price, days_ago=1):
        for variant in design.bom_line_ids.filtered(
                lambda l: l.kind == 'profile' and l.product_id).product_id:
            thickness, finish = variant._aw_cost_key()
            self.env['aw.profile.lpp'].create({
                'vendor_id': self.vendor.id,
                'product_tmpl_id': variant.product_tmpl_id.id,
                'thickness_id': thickness.id or False,
                'finish_id': finish.id or False, 'bar_length_ft': 18.0,
                'price_ft': price,
                'date': self.today - timedelta(days=days_ago)})

    def _preview(self):
        action = self.env['aw.cost.preview.wizard'].action_open()
        return self.env['aw.cost.preview.wizard'].browse(action['res_id'])

    def _line(self, wizard, design):
        return wizard.line_ids.filtered(lambda l: l.design_id == design)

    def test_a_newer_last_price_shows_as_a_higher_cost_with_the_rule(self):
        _order, design = self._make()
        self._last_prices(design, 20.0)
        line = self._line(self._preview(), design)
        self.assertTrue(line)
        self.assertGreater(line.cost_rule, line.cost_now)
        self.assertGreater(line.difference, 0)
        self.assertIn('LPP', line.changes)

    def test_nothing_is_written(self):
        _order, design = self._make()
        self._last_prices(design, 20.0)
        before = (design.cost_total, design.price_total,
                  sorted(design.bom_line_ids.mapped('unit_cost')),
                  len(design.bom_line_ids))
        self._preview()
        design = self.env['aw.design'].browse(design.id)
        after = (design.cost_total, design.price_total,
                 sorted(design.bom_line_ids.mapped('unit_cost')),
                 len(design.bom_line_ids))
        self.assertEqual(before, after)

    def test_without_a_last_price_the_rule_changes_nothing(self):
        _order, design = self._make()
        line = self._line(self._preview(), design)
        self.assertAlmostEqual(line.cost_rule, line.cost_now)
        self.assertFalse(line.changes)

    def test_a_last_price_older_than_the_maximum_age_changes_nothing(self):
        _order, design = self._make()
        self._last_prices(design, 20.0, days_ago=1)
        # the list rate is 30 days old; make the last price older than the
        # age limit by tightening the limit
        from unittest.mock import patch
        with patch.object(self.registry['product.product'],
                          '_aw_lpp_max_age_days', lambda self: 0):
            line = self._line(self._preview(), design)
        self.assertAlmostEqual(line.cost_rule, line.cost_now)

    def test_a_confirmed_order_is_not_in_the_preview(self):
        order, design = self._make()
        order.state = 'sale'
        self.assertFalse(self._line(self._preview(), design))

    def test_a_window_that_cannot_be_costed_is_listed_not_fatal(self):
        _order, design = self._make()
        _other_order, other = self._make('Kitchen')
        from unittest.mock import patch
        real = type(design)._explode

        def broken(self):
            if self.id == design.id:
                raise ValueError("boom")
            return real(self)

        with patch.object(type(design), '_explode', broken):
            wizard = self._preview()
        self.assertEqual(self._line(wizard, design).error, 'boom')
        self.assertTrue(self._line(wizard, other).cost_now)

    def test_a_variant_with_cost_zero_is_listed_first(self):
        _order, design = self._make()
        variant = design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.product_id)[:1].product_id
        # the vendor of these variants is the series' default: the row is
        # there only when the rule gives a cost, so make the rule give one
        thickness, finish = variant._aw_cost_key()
        vendor = variant.product_tmpl_id._aw_default_vendor()
        if not vendor:
            self.skipTest("no default vendor for the profile")
        self.env['aw.profile.lpp'].create({
            'vendor_id': vendor.id,
            'product_tmpl_id': variant.product_tmpl_id.id,
            'thickness_id': thickness.id or False,
            'finish_id': finish.id or False, 'bar_length_ft': 18.0,
            'price_ft': 777.0, 'date': self.today})
        variant.sudo().with_context(disable_auto_revaluation=True).standard_price = 0.0
        wizard = self._preview()
        row = wizard.variant_ids.filtered(lambda r: r.product_id == variant)
        self.assertTrue(row)
        self.assertTrue(row.zero_cost)
        self.assertEqual(row.cost_rule, 777.0)
        self.assertEqual(wizard.variant_ids[0].zero_cost, True)
