# -*- coding: utf-8 -*-
"""A gap with no spacer rate, or a gas other than Air with no rate, is named
in Checks, per panel. Nothing about the price changes."""
from datetime import date

from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGapRateWarning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        env['aw.glass.type']._seed_glass_types()
        env['aw.glass.option']._seed_glass_options()
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Gap customer'}).id,
            'aw_default_series_id': series.id})
        cls.design = order._create_fenestration_position(
            series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        # panels follow the window's stack
        cls.design.row_ids.leaf_ids.write({
            'glass_part_ids': [(5, 0, 0)], 'glass_suggested': False,
            'glass_chosen': False})

    def _stack(self, gas='Air', spacer='Aluminium'):
        self.design.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0},
                {'kind': 'gap', 'gap_mm': 12.0, 'spacer_type': spacer,
                 'spacer_colour': 'Silver', 'gas': gas},
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])
        self.design._explode()

    def _warnings(self, word):
        return self.design.check_line_ids.filtered(
            lambda c: c.level == 'warning' and word in c.message)

    def test_a_spacer_with_no_rate_is_named_for_each_panel(self):
        self._stack()
        found = self._warnings("spacer 'Aluminium'")
        self.assertEqual(sorted(found.mapped('panel_no')), [1, 2])
        self.assertTrue(all(c.target_kind == 'glass' for c in found))
        self.assertIn('Panel 1', ' '.join(found.mapped('message')))
        self.assertIn('Glass Extras', found[0].message)

    def test_air_needs_no_rate_but_another_gas_does(self):
        self._stack(gas='Air')
        self.assertFalse(self._warnings('gas'))
        self._stack(gas='Argon')
        found = self._warnings("gas 'Argon'")
        self.assertEqual(sorted(found.mapped('panel_no')), [1, 2])

    def test_a_rate_in_glass_extras_removes_the_warning_and_prices_it(self):
        self._stack(gas='Argon')
        gaps = self.design.bom_line_ids.filtered(
            lambda l: l.glass_part_kind == 'gap')
        self.assertEqual(sum(gaps.mapped('line_cost')), 0.0)
        Extra = self.env['aw.glass.extra']
        Extra.create({'name': 'Aluminium', 'kind': 'spacer',
                      'unit': 'per_ft', 'rate': 10.0,
                      'date_from': date(2000, 1, 1)})
        Extra.create({'name': 'Argon', 'kind': 'gas', 'unit': 'per_unit',
                      'rate': 50.0, 'date_from': date(2000, 1, 1)})
        self.design._explode()
        self.assertFalse(self._warnings("spacer 'Aluminium'"))
        self.assertFalse(self._warnings("gas 'Argon'"))
        gaps = self.design.bom_line_ids.filtered(
            lambda l: l.glass_part_kind == 'gap')
        self.assertGreater(sum(gaps.mapped('line_cost')), 0.0)

    def test_the_warning_changes_no_price(self):
        self._stack()
        cost = self.design.cost_total
        self.design._run_checks()
        self.assertEqual(self.design.cost_total, cost)
