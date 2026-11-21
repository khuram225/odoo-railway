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

    def test_a_cut_that_lost_its_bom_line_finds_its_window_by_reference(self):
        cut = self.batch.group_ids.bar_ids.cut_ids[:1]
        self.assertTrue(cut.piece_ref)
        cut.bom_line_id = False
        data = self.batch._cut_summary_data()
        self.assertNotIn('-', {c['window'] for c in data['cuts']})
        self.assertEqual({c['window'] for c in data['cuts']},
                         {self.design.name})

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

    # -- the Bars sheet ----------------------------------------------------
    def test_the_bars_are_the_plans_in_the_cutting_sheets_order(self):
        data = self.batch._cut_summary_data()
        rows = data['bar_rows']
        bars = self.batch.group_ids.bar_ids
        self.assertEqual(len(rows), len(bars))
        self.assertEqual(len(rows), data['bars'])
        # same order, same piece references and wording as the sheet reads
        for row, bar in zip(rows, bars):
            self.assertEqual([c['ref'] for c in row['cuts']],
                             [cut.piece_ref or '' for cut in bar.cut_ids])
            self.assertEqual([c['text'] for c in row['cuts']],
                             [cut.length_label or '' for cut in bar.cut_ids])
            self.assertEqual(row['remainder_text'], bar.remainder_label or '')
        # pieces and feet equal the Summary and the plan
        blocks = cut_summary_xlsx.blocks_of(data['cuts'])
        self.assertEqual(sum(len(r['cuts']) for r in rows),
                         sum(b['totals']['pieces'] for b in blocks))
        self.assertAlmostEqual(
            sum(r['used_mm'] for r in rows) / MM_PER_FOOT,
            self.batch.feet_used, places=6)
        self.assertEqual(
            sum(len(r['cuts']) for r in rows),
            sum(self.batch.group_ids.mapped('piece_count')))

    def test_a_bars_used_plus_remainder_is_its_length_within_kerf(self):
        plan = self.batch
        for row in plan._cut_summary_data()['bar_rows']:
            lost = row['stock_mm'] - row['used_mm'] - row['remainder_mm']
            allowed = (plan.start_trim_mm + plan.safety_margin_mm
                       + len(row['cuts']) * plan.kerf_mm * 1.5 + 0.01)
            self.assertGreaterEqual(lost, -0.01)
            self.assertLessEqual(lost, allowed)

    def test_the_workbook_has_the_bars_sheet_and_the_references(self):
        import io
        import openpyxl
        _name, content = self.batch._cut_summary_file()
        book = openpyxl.load_workbook(io.BytesIO(content))
        self.assertEqual(book.sheetnames, ['Summary', 'Bars', 'Cut list'])
        rows = [[c.value for c in row] for row in book['Bars'].iter_rows()]
        head = next(i for i, r in enumerate(rows) if r[0] == 'Profile')
        body = [r for r in rows[head + 1:] if r[0]]
        self.assertEqual(len(body), self.batch.bar_count)
        refs = {cut.piece_ref for cut in
                self.batch.group_ids.bar_ids.cut_ids}
        for r in body:
            for part in r[3].split(' + '):
                self.assertIn(part.rsplit('(', 1)[1].rstrip(')'), refs)
        flat = [[c.value for c in row] for row in book['Cut list'].iter_rows()]
        flat_head = next(i for i, r in enumerate(flat) if r[0] == 'Window')
        self.assertEqual(
            {r[2] for r in flat[flat_head + 1:] if r[0]}, refs)

    # -- a piece of length 0 ----------------------------------------------
    def _zero_a_piece(self):
        line = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.piece_key
            and not l.cut_on_site)[:1]
        key, ref = line.piece_key, line.piece_ref
        # how a 0 got onto W21: typed before typing 0 was refused
        line.with_context(aw_bom_generating=True).write(
            {'length_mm': 0.0, 'is_manual': True})
        self.design._explode()
        return key, ref

    def test_typing_zero_is_refused(self):
        line = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and not l.cut_on_site)[:1]
        with self.assertRaises(UserError):
            line.write({'length_mm': 0.0})
        with self.assertRaises(UserError):
            self.design.set_piece_length(line.id, 0)
        self.assertGreater(line.length_mm, 0)

    def test_a_zero_length_piece_is_warned_about_with_a_link(self):
        key, ref = self._zero_a_piece()
        checks = self.design.check_line_ids.filtered(
            lambda c: 'has length 0' in c.message)
        self.assertEqual(len(checks), 1)
        self.assertIn(ref, checks.message)
        self.assertEqual(checks.target_kind, 'piece')
        self.assertEqual(checks.target_key, key)
        self.assertEqual(checks.level, 'warning')

    def test_a_zero_length_piece_is_left_out_of_the_plan_and_listed(self):
        key, ref = self._zero_a_piece()
        self.batch.action_generate()
        self.assertIn('Not planned: length 0', self.batch.blocked_note)
        self.assertIn(ref, self.batch.blocked_note)
        cuts = self.batch.group_ids.bar_ids.cut_ids
        self.assertNotIn(0.0, cuts.mapped('length_mm'))
        self.assertNotIn(ref, cuts.mapped('piece_ref'))
        # and it cannot be bought past
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()

    def test_use_the_rule_clears_a_typed_length(self):
        key, _ref = self._zero_a_piece()
        line = self.design.bom_line_ids.filtered(
            lambda l: l.piece_key == key)
        self.assertEqual(line.length_mm, 0.0)
        self.design.use_piece_rule(line.id)
        line = self.design.bom_line_ids.filtered(
            lambda l: l.piece_key == key)
        self.assertGreater(line.length_mm, 0.0)
        self.assertAlmostEqual(line.length_mm, line.computed_length_mm)
        self.assertFalse(line.is_manual)
        self.assertFalse(self.design.check_line_ids.filtered(
            lambda c: 'has length 0' in c.message))
