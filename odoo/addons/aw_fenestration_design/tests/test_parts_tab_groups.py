# -*- coding: utf-8 -*-
"""The Parts tab: how many pieces each part made, and a thickness for a group
of lines at once."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestPartsTabGroups(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Parts customer'}).id,
            'aw_default_series_id': series.id})
        cls.design = order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        env.flush_all()
        env.invalidate_all()

    def test_the_payload_says_how_many_pieces_each_part_made(self):
        parts = self.design._spec_parts_payload()
        self.assertTrue(parts['has_pieces'])
        frame = [r for r in parts['profiles'] if r['scope'] == 'frame']
        self.assertTrue(frame)
        self.assertTrue(any(r['pieces'] > 0 for r in frame),
                        "the outer frame made pieces")
        for row in parts['profiles']:
            self.assertIn('pieces', row)
        # a one-row window made no horizontal divider
        transom = [r for r in parts['profiles'] if r['scope'] == 'transom']
        for row in transom:
            self.assertEqual(row['pieces'], 0)

    def test_a_window_with_no_bom_lists_every_part(self):
        self.design.bom_line_ids.filtered(
            lambda b: not b.is_free_form).unlink()
        self.assertFalse(self.design._spec_parts_payload()['has_pieces'])

    def test_a_thickness_needs_choosing(self):
        with self.assertRaises(UserError):
            self.design.apply_thickness_rows(0, [1])

    def test_only_the_listed_lines_take_the_thickness(self):
        parts = self.design._spec_parts_payload()
        rows = [r for r in parts['profiles'] if len(r['thickness_options']) > 1]
        if len(rows) < 2:
            self.skipTest("no two lines with a choice of thickness here")
        first, second = rows[0], rows[1]
        wanted = next(t for t in first['thickness_options']
                      if t['id'] != first['thickness_id'])
        before = {r['position_id']: r['thickness_id'] for r in parts['profiles']}
        result = self.design.apply_thickness_rows(
            wanted['id'], [first['position_id']])
        after = {r['position_id']: r['thickness_id']
                 for r in result['spec_parts']['profiles']}
        self.assertEqual(after[first['position_id']], wanted['id'])
        self.assertEqual(after[second['position_id']],
                         before[second['position_id']])
