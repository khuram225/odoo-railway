# -*- coding: utf-8 -*-
"""The price build-up: one method returns the lines, and the stored cost and
price are read from it. The numbers are the early S00010 test: profiles
106,233.39 on a 3658 x 2438 window, Standard structure (profile wastage 8%,
glass wastage 5%, fabrication 450 and installation 250 per m2, profit 25%)."""
import unittest

from decimal import ROUND_HALF_UP, Decimal

from odoo.tests import TransactionCase, tagged

PROFILES = 106233.39
AREA_SQM = 3658 * 2438 / 1000000.0
LABOUR = (450.0 + 250.0) * AREA_SQM
COST = PROFILES * 1.08 + LABOUR                  # 120,974.80
PRICE = COST * 1.25                              # 151,218.51
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


def money(value):
    """To 2 decimals, half up, on the number as written (not its binary
    expansion), so 152468.505 is 152468.51."""
    return float(Decimal(repr(round(value, 6))).quantize(
        Decimal('0.01'), ROUND_HALF_UP))



@tagged('post_install', '-at_install')
class TestPriceBuildUp(TransactionCase):
    def assertMoney(self, first, second, places=None):
        """ONE rule for money: two decimals, half up. The stored totals are
        rounded to the cent while the build-up rows carry the unrounded
        intermediates, so a test that asked for 4 or 6 places was comparing
        a rounded number with an unrounded one. `places` is accepted and
        ignored."""
        self.assertEqual(money(first), money(second))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Price customer'}).id,
            'aw_default_series_id': series.id,
        })
        cls.design = cls.order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 3658.0, 'height_mm': 2438.0, 'qty': 1})
        cls.structure = env['aw.price.structure'].create({
            'name': 'S00010 structure',
            'line_ids': [(0, 0, {'name': kind, 'kind': kind, 'value': value})
                         for kind, value in (
                ('profile_wastage', 8.0), ('glass_wastage', 5.0),
                ('mesh_wastage', 0.0), ('fabrication_labour', 450.0),
                ('install_labour', 250.0), ('profit', 25.0))]})
        cls.design.price_structure_id = cls.structure
        cls.design.bom_line_ids.unlink()
        cls.Line = env['aw.design.bom.line']
        cls.Line.create({'design_id': cls.design.id, 'kind': 'profile',
                         'label': 'profiles', 'line_cost': PROFILES})

    def _price(self):
        self.design._compute_pricing()
        return self.design

    def _rows(self):
        return {r['key']: r for r in self.design._price_build_up()['rows']}

    # -- the S00010 numbers ---------------------------------------------------------
    def test_the_s00010_numbers(self):
        design = self._price()
        self.assertMoney(design.cost_total, COST, 2)
        self.assertMoney(design.price_total, PRICE, 2)
        self.assertMoney(design.cost_total, 120974.80, 1)
        self.assertMoney(design.price_total, 151218.51, 1)

    def test_the_rows_add_up_to_the_stored_cost_and_price(self):
        design = self._price()
        rows = design._price_build_up()['rows']
        cost = sum(r['amount'] for r in rows
                   if r['kind'] in ('base', 'labour')
                   or (r['kind'] == 'add' and r['key'] != 'profit'))
        self.assertMoney(cost, design.cost_total, 6)
        by = {r['key']: r for r in rows}
        self.assertMoney(by['cost']['amount'], design.cost_total, 6)
        self.assertMoney(
            by['cost']['amount'] + by['profit']['amount'],
            by['calculated_price']['amount'], 6)
        self.assertMoney(by['price']['amount'], design.price_total, 6)

    def test_every_row_the_pricing_tab_lists_is_there_in_order(self):
        keys = [r['key'] for r in self.design._price_build_up()['rows']]
        self.assertEqual(keys, [
            'profiles', 'profile_wastage', 'glass', 'glass_wastage',
            'mesh_cloth', 'mesh_wastage', 'hardware', 'infill_grid',
            'fabrication_labour', 'install_labour', 'cost', 'profit',
            'calculated_price', 'price'])

    def test_percent_and_rate_rows_carry_their_units(self):
        rows = self._rows()
        self.assertEqual((rows['profile_wastage']['percent'],
                          rows['profile_wastage']['unit']), (8.0, '%'))
        self.assertMoney(
            rows['profile_wastage']['amount'], PROFILES * 0.08, 6)
        self.assertEqual(rows['fabrication_labour']['rate'], 450.0)
        self.assertIn('m', rows['fabrication_labour']['unit'])
        self.assertMoney(
            rows['fabrication_labour']['amount'], 450.0 * AREA_SQM, 6)
        self.assertEqual(rows['profit']['percent'], 25.0)
        self.assertMoney(rows['profit']['amount'], COST * 0.25, 4)

    def test_a_manual_rate_adds_its_row_and_replaces_the_price(self):
        self.assertNotIn('manual_override', self._rows())
        self.design.manual_rate = 50.0
        design = self._price()
        rows = self._rows()
        self.assertIn('manual_override', rows)
        self.assertEqual(rows['manual_override']['unit'], 'per sqft')
        self.assertMoney(
            design.price_total, 50.0 * design.area_sqft, 4)
        self.assertMoney(rows['price']['amount'], design.price_total, 6)
        self.assertMoney(rows['calculated_price']['amount'], PRICE, 2)
        self.design.manual_rate = 0.0

    # -- mesh wastage -------------------------------------------------------------------
    def _cloth(self, cost=1000.0):
        return self.Line.create({
            'design_id': self.design.id, 'kind': 'mesh', 'label': 'cloth',
            'glass_w': 752.0, 'glass_h': 2428.0, 'line_cost': cost})

    def test_prices_do_not_change_with_mesh_wastage_at_zero(self):
        before = self._price().price_total
        cloth = self._cloth()
        with_cloth = self._price()
        self.assertMoney(with_cloth.cost_total, COST + 1000.0, 2)
        self.assertMoney(with_cloth.price_total, (COST + 1000.0) * 1.25, 2)
        # the same with the Mesh Wastage row gone altogether (an older
        # structure): a missing kind reads as 0%
        self.structure.line_ids.filtered(
            lambda l: l.kind == 'mesh_wastage').unlink()
        again = self._price()
        self.assertMoney(again.price_total, with_cloth.price_total, 6)
        cloth.unlink()
        self.assertMoney(self._price().price_total, before, 6)

    def test_mesh_wastage_applies_to_the_cloth_only(self):
        self._cloth(1000.0)
        self.Line.create({'design_id': self.design.id, 'kind': 'hardware',
                          'label': 'roller', 'line_cost': 500.0})
        base = self._price().cost_total
        self.structure.line_ids.filtered(
            lambda l: l.kind == 'mesh_wastage').value = 10.0
        self.assertMoney(self._price().cost_total, base + 100.0, 4)

    def test_hardware_infill_and_grid_have_no_wastage(self):
        for kind in ('hardware', 'infill', 'grid'):
            self.Line.create({'design_id': self.design.id, 'kind': kind,
                              'label': kind, 'line_cost': 100.0})
        self.assertMoney(self._price().cost_total, COST + 300.0, 4)

    def test_the_missing_mesh_wastage_row_is_added_once_at_zero(self):
        old = self.env['aw.price.structure'].create({
            'name': 'Older structure',
            'line_ids': [(0, 0, {'name': 'Profit', 'kind': 'profit', 'value': 20.0})]})
        added = self.env['aw.price.structure']._add_missing_lines()
        self.assertGreaterEqual(added, 1)
        mesh = old.line_ids.filtered(lambda l: l.kind == 'mesh_wastage')
        self.assertEqual(len(mesh), 1)
        self.assertEqual(mesh.value, 0.0)
        self.assertEqual(
            old.line_ids.filtered(lambda l: l.kind == 'profit').value, 20.0)
        self.env['aw.price.structure']._add_missing_lines()
        self.assertEqual(len(old.line_ids.filtered(
            lambda l: l.kind == 'mesh_wastage')), 1)       # never twice

    def test_the_pricing_payload_carries_the_rows_and_the_margins(self):
        self._price()
        data = self.design.get_configurator_data()
        pricing = data['pricing']
        self.assertEqual(
            [r['key'] for r in pricing['build_up']][-1], 'price')
        self.assertIn('margin_pct', pricing)
        self.assertIn('min_margin_pct', pricing)
        self.assertEqual(pricing['wastage']['mesh'], 0.0)
