# -*- coding: utf-8 -*-
"""Review, Confirm and Undo: nothing is written before Confirm, a change over
15% needs a tick, a problem blocks, a row waiting for a product does not."""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesReview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Review glass vendor'})
        Type = env['aw.glass.type']
        cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        if not cls.clear:
            Type._seed_glass_types()
            cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        cls.Rate = env['aw.glass.rate']
        for mm, price in ((4, 80.0), (5, 90.0), (6, 100.0)):
            cls.Rate.create({
                'glass_type_id': cls.clear.id, 'thickness_mm': mm,
                'vendor_id': cls.vendor.id, 'price': price,
                'date_from': date(2025, 6, 1)})

    def _list(self, rows, day=date(2025, 9, 1)):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'glass', 'date': day})
        rate_list.action_next_step()
        for code, thickness, price in rows:
            self.env['aw.vendor.rate.list.line'].create({
                'list_id': rate_list.id, 'code': code,
                'thickness_text': thickness, 'rate_1': price})
        return rate_list

    def _mixed(self):
        return self._list([
            ('Clear', '6mm', 100.0),     # unchanged
            ('Clear', '5mm', 99.0),      # +10%
            ('Clear', '4mm', 100.0),     # +25%: needs a tick
            ('Clear', '8mm', 150.0),     # new
            ('Zorba', '6mm', 100.0),     # no such glass type: not written
            ('Clear', '10mm', 0.0),      # no price
        ])

    def _count(self, model, **domain):
        return self.env[model].search_count(
            [(k, '=', v) for k, v in domain.items()])

    # -- the review ------------------------------------------------------------------
    def test_review_counts_and_lists_only_what_needs_a_look(self):
        rate_list = self._mixed()
        before = self.Rate.search_count([])
        rate_list.action_open_review()
        self.assertEqual(rate_list.step, 'review')
        self.assertEqual(
            (rate_list.review_unchanged, rate_list.review_changed,
             rate_list.review_new, rate_list.review_problem,
             rate_list.review_notwritten, rate_list.review_nopriced,
             rate_list.review_big), (1, 2, 1, 0, 1, 1, 1))
        rows = rate_list.review_ids
        self.assertEqual(len(rows), 4)            # unchanged and no-price are only counted
        self.assertEqual(self.Rate.search_count([]), before)   # nothing written
        changed = rows.filtered(lambda r: r.thickness == '4mm')
        self.assertEqual((changed.old_price, changed.new_price), (80.0, 100.0))
        self.assertAlmostEqual(changed.pct, 25.0, 1)
        self.assertTrue(changed.big)
        small = rows.filtered(lambda r: r.thickness == '5mm')
        self.assertAlmostEqual(small.pct, 10.0, 1)
        self.assertFalse(small.big)
        self.assertEqual(rows.filtered(lambda r: r.thickness == '8mm').status, 'new')
        waiting = rows.filtered(lambda r: r.status == 'notwritten')
        self.assertIn('no glass type Zorba', waiting.message)

    def test_messages_are_plain_words(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        text = ' '.join(rate_list.review_ids.mapped('message')).lower()
        for technical in ('variant', 'foreign key', 'many2one', 'xmlid'):
            self.assertNotIn(technical, text)

    def test_an_empty_review_is_refused_in_plain_words(self):
        rate_list = self._list([])
        with self.assertRaises(UserError) as caught:
            rate_list.action_open_review()
        self.assertIn('no rows to review', str(caught.exception))

    # -- Confirm ---------------------------------------------------------------------
    def test_a_change_over_15_percent_needs_the_tick(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        with self.assertRaises(UserError) as caught:
            rate_list.action_confirm_rates()
        self.assertIn('I checked these price changes', str(caught.exception))
        self.assertEqual(rate_list.state, 'draft')
        rate_list.ack_changes = True
        rate_list.action_confirm_rates()
        self.assertEqual((rate_list.state, rate_list.step), ('applied', 'confirm'))

    def test_confirm_writes_changed_and_new_only(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        rate_list.ack_changes = True
        rate_list.action_confirm_rates()
        written = self.Rate.search([('rate_list_id', '=', rate_list.id)])
        self.assertEqual(
            sorted((r.thickness_mm, r.price) for r in written),
            [(4.0, 100.0), (5.0, 99.0), (8.0, 150.0)])    # not the unchanged 6mm
        self.assertTrue(all(r.date_from == date(2025, 9, 1) for r in written))

    def test_the_original_stays_attached(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        rate_list.ack_changes = True
        rate_list.action_confirm_rates()
        kept = self.env['ir.attachment'].search([
            ('res_model', '=', 'aw.vendor.rate.list'), ('res_id', '=', rate_list.id)])
        self.assertEqual(len(kept), 1)
        self.assertIn('Clear,8mm,150.0', kept.raw.decode('utf-8'))

    def test_a_row_waiting_for_a_product_does_not_block(self):
        rate_list = self._list([('Clear', '8mm', 150.0), ('Zorba', '6mm', 100.0)])
        rate_list.action_open_review()
        self.assertEqual(rate_list.review_problem, 0)
        rate_list.action_confirm_rates()          # no big change: no tick needed
        self.assertEqual(rate_list.state, 'applied')

    # -- problems --------------------------------------------------------------------
    def test_two_prices_for_one_glass_block_confirm(self):
        rate_list = self._list([('Clear', '8mm', 150.0), ('Clear', '8mm', 160.0)])
        rate_list.action_open_review()
        self.assertEqual(rate_list.review_problem, 2)
        with self.assertRaises(UserError) as caught:
            rate_list.action_confirm_rates()
        self.assertIn('problem', str(caught.exception))
        self.assertEqual(rate_list.state, 'draft')
        self.assertFalse(self.Rate.search([('rate_list_id', '=', rate_list.id)]))

    def test_a_newer_rate_in_force_is_a_problem_naming_both_dates(self):
        # the list starts 1 Jan 2025; a 1 Jun 2025 rate is already in force
        rate_list = self._list([('Clear', '6mm', 110.0), ('Clear', '8mm', 150.0)],
                               day=date(2025, 1, 1))
        rate_list.action_open_review()
        self.assertEqual(rate_list.review_problem, 1)       # the 6mm; 8mm is new
        problem = rate_list.review_ids.filtered(lambda r: r.status == 'problem')
        text = problem.message
        self.assertIn('2025-06-01', text)
        self.assertIn('2025-01-01', text)
        self.assertIn('overruled', text)
        with self.assertRaises(UserError):
            rate_list.action_confirm_rates()

    # -- staying true ----------------------------------------------------------------
    def test_changing_a_row_sends_the_review_back_to_data_in(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        rate_list.ack_changes = True
        rate_list.line_ids[0].rate_1 = 101.0
        self.assertEqual(rate_list.step, 'data')
        self.assertFalse(rate_list.ack_changes)
        self.assertFalse(rate_list.review_ids)
        with self.assertRaises(UserError):
            rate_list.action_confirm_rates()                # review first

    def test_bookkeeping_does_not_cancel_a_review(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        rate_list.action_rematch()
        self.assertEqual(rate_list.step, 'review')

    # -- Undo ------------------------------------------------------------------------
    def test_undo_removes_the_rates_and_goes_back_to_data_in(self):
        rate_list = self._mixed()
        rate_list.action_open_review()
        rate_list.ack_changes = True
        rate_list.action_confirm_rates()
        self.assertTrue(self.Rate.search([('rate_list_id', '=', rate_list.id)]))
        rate_list.action_set_to_draft()
        self.assertFalse(self.Rate.search([('rate_list_id', '=', rate_list.id)]))
        self.assertEqual((rate_list.state, rate_list.step), ('draft', 'data'))
        self.assertTrue(rate_list.line_ids)                 # the rows are kept
