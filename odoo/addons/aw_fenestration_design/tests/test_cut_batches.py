# -*- coding: utf-8 -*-
"""A batch is a cutting plan over the windows ticked when it was made."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCutBatches(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Batch customer'}).id,
            'aw_default_series_id': series.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        windows = env['aw.design']
        for location in ('Hall', 'Kitchen', 'Study'):
            design = cls.order._create_fenestration_position(
                series, family=family, location=location)
            design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': 1800.0,
                          'leaves': [dict(leaf), dict(leaf)]}]})
            windows |= design
        cls.hall, cls.kitchen, cls.study = windows
        cls.Plan = env['aw.cut.plan']

    def _wizard(self, leave_out=()):
        action = self.order.action_new_batch()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.line_ids.filtered(
            lambda l: l.design_id in leave_out).selected = False
        return wizard

    # -- making a batch ------------------------------------------------------
    def test_the_dialog_lists_every_free_window_ticked(self):
        wizard = self._wizard()
        self.assertEqual(wizard.line_ids.design_id,
                         self.hall | self.kitchen | self.study)
        self.assertTrue(all(wizard.line_ids.mapped('selected')))

    def test_a_batch_plans_only_its_own_windows(self):
        self._wizard(leave_out=self.study).action_create()
        batch = self.order.aw_cut_plan_ids
        self.assertEqual(batch.design_ids, self.hall | self.kitchen)
        self.assertEqual(batch.name, 'Batch 1 — %s' % self.order.name)
        pieces = batch.group_ids.bar_ids.cut_ids.bom_line_id.design_id
        self.assertTrue(pieces)
        self.assertNotIn(self.study, pieces)

    def test_the_next_batch_offers_only_what_is_left(self):
        self._wizard(leave_out=self.study).action_create()
        wizard = self._wizard()
        self.assertEqual(wizard.line_ids.design_id, self.study)
        wizard.action_create()
        names = sorted(self.order.aw_cut_plan_ids.mapped('name'))
        self.assertEqual(names, ['Batch 1 — %s' % self.order.name,
                                 'Batch 2 — %s' % self.order.name])

    def test_nothing_ticked_and_nothing_free_are_refused(self):
        with self.assertRaises(UserError):
            self._wizard(leave_out=self.hall | self.kitchen
                         | self.study).action_create()
        self._wizard().action_create()
        with self.assertRaises(UserError):
            self.order.action_new_batch()

    def test_the_quote_button_makes_the_first_batch_then_lists(self):
        first = self.order.action_cutting_plan()
        self.assertEqual(first['res_model'], 'aw.cut.batch.wizard')
        self._wizard().action_create()
        listing = self.order.action_cutting_plan()
        self.assertEqual(listing['res_model'], 'aw.cut.plan')
        self.assertEqual(listing['domain'], [('sale_order_id', '=', self.order.id)])

    # -- one active batch per window -------------------------------------------
    def test_a_window_is_in_one_active_batch_only(self):
        self._wizard(leave_out=self.study).action_create()
        other = self.Plan.create({
            'sale_order_id': self.order.id,
            'design_ids': [(6, 0, self.study.ids)]})
        with self.assertRaises(ValidationError):
            other.design_ids = [(4, self.hall.id)]

    def test_a_window_moves_between_draft_batches(self):
        self._wizard(leave_out=self.study).action_create()
        first = self.order.aw_cut_plan_ids
        second = self.Plan.create({
            'sale_order_id': self.order.id,
            'design_ids': [(6, 0, self.study.ids)]})
        first.design_ids = [(3, self.hall.id)]
        second.design_ids = [(4, self.hall.id)]
        self.assertEqual(second.design_ids, self.study | self.hall)
        self.assertEqual(first.design_ids, self.kitchen)

    def test_a_batch_that_is_not_draft_cannot_move_windows(self):
        self._wizard().action_create()
        batch = self.order.aw_cut_plan_ids
        batch.state = 'confirmed'
        with self.assertRaises(UserError):
            batch.design_ids = [(3, self.hall.id)]

    def test_cancelling_a_draft_batch_frees_its_windows(self):
        self._wizard().action_create()
        batch = self.order.aw_cut_plan_ids
        batch.action_cancel_batch()
        self.assertEqual(batch.state, 'cancel')
        self.assertEqual(self.order._batch_free_designs(),
                         self.hall | self.kitchen | self.study)
        self._wizard().action_create()        # the windows can join a new one
        self.assertEqual(len(self.order.aw_cut_plan_ids), 2)
        self.assertIn('cancelled', ' '.join(self.order.message_ids.mapped('body')))

    def test_only_a_draft_batch_can_be_cancelled(self):
        self._wizard().action_create()
        batch = self.order.aw_cut_plan_ids
        batch.state = 'confirmed'
        with self.assertRaises(UserError):
            batch.action_cancel_batch()

    # -- staleness, the drawing, the old plans -------------------------------
    def test_a_partial_batch_goes_stale_when_its_windows_change(self):
        self._wizard(leave_out=self.study).action_create()
        batch = self.order.aw_cut_plan_ids
        self.assertTrue(batch.is_current)
        batch.design_ids = [(4, self.study.id)]
        batch.invalidate_recordset()
        self.assertFalse(batch.is_current)

    def test_a_window_knows_its_batch(self):
        self._wizard(leave_out=self.study).action_create()
        batch = self.order.aw_cut_plan_ids
        self.assertEqual(self.hall._sheet_plan(), batch)
        self.assertFalse(self.study._sheet_plan())

    def test_the_old_plan_gets_the_quotes_windows_and_batch_one(self):
        """The one-time backfill: a plan made before batches existed."""
        legacy = self.Plan.create({'sale_order_id': self.order.id})
        legacy.write({'batch_no': 0})
        self.assertFalse(legacy.design_ids)
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.batches_backfilled', False)
        self.Plan._backfill_batches()
        self.assertEqual(legacy.design_ids,
                         self.hall | self.kitchen | self.study)
        self.assertEqual(legacy.batch_no, 1)
        # once only: a batch emptied by hand stays empty
        legacy.design_ids = [(5, 0, 0)]
        self.assertEqual(self.Plan._backfill_batches(), 0)
        self.assertFalse(legacy.design_ids)
