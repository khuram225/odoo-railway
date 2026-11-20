# -*- coding: utf-8 -*-
"""Download cut summary: the data handed to the workbook comes from the
batch's own cuts, so the totals are the plan's."""
from odoo.addons.aw_fenestration_design.models import cut_summary_xlsx
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MM_PER_FOOT = 304.8


@tagged('post_install', '-at_install')
class TestCutSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Summary customer'}).id,
            'aw_default_series_id': series.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design = cls.order._create_fenestration_position(
            series, family=family, location='Hall')
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        action = cls.order.action_new_batch()
        env[action['res_model']].browse(action['res_id']).action_create()
        cls.batch = cls.order.aw_cut_plan_ids

    def test_the_pieces_and_feet_are_the_plans(self):
        data = self.batch._cut_summary_data()
        self.assertTrue(data['cuts'])
        blocks = cut_summary_xlsx.blocks_of(data['cuts'])
        pieces = sum(b['totals']['pieces'] for b in blocks)
        feet = sum(b['totals']['feet'] for b in blocks)
        self.assertEqual(pieces, sum(self.batch.group_ids.mapped('piece_count')))
        self.assertAlmostEqual(feet, self.batch.feet_used, places=6)
        self.assertEqual(data['bars'], self.batch.bar_count)
        self.assertAlmostEqual(data['feet'], self.batch.feet_bought)
        self.assertEqual(data['quote'], self.order.name)
        self.assertEqual(data['batch'], 'Batch %s' % self.batch.batch_no)
        self.assertEqual(data['state'], 'Draft')

    def test_each_cut_traces_to_its_window_and_bar(self):
        data = self.batch._cut_summary_data()
        self.assertEqual({c['window'] for c in data['cuts']},
                         {self.design.name})
        self.assertEqual({c['location'] for c in data['cuts']}, {'Hall'})
        by_block = {}
        for cut in data['cuts']:
            by_block.setdefault(cut['block'], []).append(cut)
        self.assertEqual(set(by_block), set(self.batch.group_ids.ids))
        for group in self.batch.group_ids:
            bars = {c['bar_no'] for c in by_block[group.id]}
            self.assertEqual(bars, set(range(1, len(group.bar_ids) + 1)))

    def test_a_window_with_several_profiles_is_in_each_block(self):
        data = self.batch._cut_summary_data()
        blocks = cut_summary_xlsx.blocks_of(data['cuts'])
        if len(self.batch.group_ids) < 2:
            self.skipTest("this window made a single profile")
        for block in blocks:
            self.assertEqual([r['window'] for r in block['rows']],
                             [self.design.name])

    def test_a_typed_length_is_flagged(self):
        cut = self.batch.group_ids.bar_ids.cut_ids[:1]
        line = cut.bom_line_id
        self.assertFalse(
            [c for c in self.batch._cut_summary_data()['cuts'] if c['typed']])
        line.write({'is_manual': True,
                    'length_mm': (line.computed_length_mm or 1000.0) + 25.0})
        flagged = [c for c in self.batch._cut_summary_data()['cuts']
                   if c['typed']]
        self.assertTrue(flagged)

    def test_a_stale_plan_still_downloads_with_the_note(self):
        self.assertFalse(self.batch._cut_summary_data()['stale'])
        self.design.write({'width_mm': 2600.0})
        self.design._explode()
        data = self.batch._cut_summary_data()
        self.assertTrue(data['stale'])
        name, content = self.batch._cut_summary_file()
        self.assertTrue(content.startswith(b'PK'))
        self.assertIn('batch%s' % self.batch.batch_no, name)
        self.assertTrue(name.startswith('cut_summary_'))
        self.assertTrue(name.endswith('.xlsx'))

    def test_the_button_points_at_the_download(self):
        action = self.batch.action_download_cut_summary()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], '/aw/cut_summary/%s' % self.batch.id)

    def test_an_empty_batch_is_refused_with_a_message(self):
        empty = self.env['aw.cut.plan'].create({
            'sale_order_id': self.order.id})
        with self.assertRaises(UserError) as caught:
            empty.action_download_cut_summary()
        self.assertIn('no cuts', str(caught.exception))
