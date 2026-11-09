# -*- coding: utf-8 -*-
"""A confirmed order's cost does not move by itself."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestCostFreeze(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.family, cls.series = seeded_family_series(cls.env)
        cls.vendor = cls.env['res.partner'].create({'name': 'Freeze vendor'})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Freeze customer'})
        cls.today = fields.Date.context_today(cls.env['res.partner'])

    def _make(self, location='Hall'):
        """(order, design): a window with a layout, costed at rates of 10
        per ft thirty days ago."""
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
        self._rate(design, 10.0, 30)
        design._explode()
        design._sync_sale_order_line()
        self.assertTrue(design.cost_total, "the window was not costed")
        return order, design

    def _rate(self, design, price, days_ago):
        """A vendor rate for every profile of the window, for any thickness
        and finish, in force since `days_ago` days."""
        vendor = design.sale_order_id.aw_profile_vendor_id
        templates = design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.product_id
        ).product_id.product_tmpl_id
        for template in templates:
            self.env['aw.profile.rate'].create({
                'product_tmpl_id': template.id, 'vendor_id': vendor.id,
                'price': price,
                'date_from': self.today - timedelta(days=days_ago)})

    def _units(self, design):
        return {line.id: line.unit_cost for line in design.bom_line_ids
                if line.kind == 'profile'}

    def _unit_by_variant(self, design):
        return {line.product_id.id: line.unit_cost
                for line in design.bom_line_ids if line.kind == 'profile'}

    # -- a rate dated before the order ----------------------------------------
    def test_a_list_rate_entered_later_does_not_move_a_confirmed_design(self):
        order, design = self._make()
        cost, price = design.cost_total, design.price_total
        units = self._unit_by_variant(design)
        order.state = 'sale'
        self._rate(design, 99.0, 10)         # dated before the order
        design._explode()
        self.assertEqual(self._unit_by_variant(design), units)
        self.assertAlmostEqual(design.cost_total, cost)
        self.assertAlmostEqual(design.price_total, price)

    def test_the_same_re_explode_of_a_quote_does_follow_the_new_rate(self):
        _order, design = self._make('Kitchen')
        cost = design.cost_total
        self._rate(design, 99.0, 10)
        design._explode()
        self.assertGreater(design.cost_total, cost)

    # -- a re-save ----------------------------------------------------------------
    def test_a_re_save_keeps_the_stored_cost_and_the_quote_line_price(self):
        order, design = self._make()
        order.state = 'sale'
        cost, price = design.cost_total, design.price_total
        line_price = design.sale_order_line_id.price_unit
        self._rate(design, 99.0, 10)
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [
                {'width_mm': 1200.0,
                 'leaf_type_id': self.series.leaf_type_ids[0].id},
                {'width_mm': 1200.0,
                 'leaf_type_id': self.series.leaf_type_ids[0].id}]}]})
        self.assertAlmostEqual(design.cost_total, cost)
        self.assertAlmostEqual(design.price_total, price)
        self.assertAlmostEqual(
            design.sale_order_line_id.price_unit, line_price)

    # -- the price structure ------------------------------------------------------
    def _raise_profit(self, design, by=10.0):
        line = design.price_structure_id.line_ids.filtered(
            lambda l: l.kind == 'profit')[:1]
        line.value = line.value + by

    def test_a_structure_change_reprices_a_quote_but_not_a_confirmed_design(self):
        order, design = self._make()
        _quote_order, quote = self._make('Kitchen')
        order.state = 'sale'
        price, quote_price = design.price_total, quote.price_total
        self._raise_profit(design)
        self.env.flush_all()
        self.assertAlmostEqual(design.price_total, price)
        self.assertGreater(quote.price_total, quote_price)

    def test_an_unchanged_re_explode_puts_the_price_back_after_a_structure_change(self):
        order, design = self._make()
        order.state = 'sale'
        price, cost = design.price_total, design.cost_total
        self._raise_profit(design)
        design._explode()
        self.assertAlmostEqual(design.price_total, price)
        self.assertAlmostEqual(design.cost_total, cost)

    # -- a changed window ---------------------------------------------------------
    def test_a_longer_window_keeps_the_unit_costs_and_costs_the_extra_length(self):
        order, design = self._make()
        order.state = 'sale'
        cost = design.cost_total
        units = self._unit_by_variant(design)
        self._rate(design, 99.0, 10)
        design.write({'width_mm': 3000.0})
        design._explode()
        self.assertEqual(self._unit_by_variant(design), units)
        self.assertGreater(design.cost_total, cost)

    def test_a_piece_that_is_new_is_costed_fresh(self):
        order, design = self._make()
        order.state = 'sale'
        stored = self._unit_by_variant(design)
        snapshot = design._freeze_snapshot()
        # forget one profile: it is "a new piece" as far as the freeze goes
        forgotten = next(iter(snapshot))
        snapshot.pop(forgotten)
        self._rate(design, 99.0, 10)
        design.with_context(aw_frozen_costs=snapshot)._cost_bom_lines()
        units = self._unit_by_variant(design)
        for variant_id, unit in units.items():
            if (design.bom_line_ids.filtered(
                    lambda l: l.product_id.id == variant_id)[:1].kind,
                    variant_id) == forgotten:
                self.assertEqual(unit, 99.0)
            else:
                self.assertEqual(unit, stored[variant_id])
