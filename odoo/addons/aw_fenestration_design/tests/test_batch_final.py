# -*- coding: utf-8 -*-
"""Mark bars bought: a batch becomes Final and is locked."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchFinal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Final customer'}).id,
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

    def test_marking_bought_makes_it_final_and_says_who(self):
        self.batch.action_mark_bought()
        self.assertEqual(self.batch.state, 'confirmed')
        self.assertEqual(self.batch.bought_by, self.env.user)
        self.assertTrue(self.batch.bought_on)
        self.assertIn('marked the bars bought',
                      ' '.join(self.order.message_ids.mapped('body')))

    def test_a_final_batch_is_locked(self):
        self.batch.action_mark_bought()
        with self.assertRaises(UserError):
            self.batch.action_generate()
        with self.assertRaises(UserError):
            self.batch.group_ids.action_clear_override()
        with self.assertRaises(UserError):
            self.batch.design_ids = [(5, 0, 0)]
        with self.assertRaises(UserError):
            self.batch.action_cancel_batch()
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()

    def test_an_option_cannot_be_chosen_on_a_final_batch(self):
        scenario = self.batch.group_ids.scenario_ids.filtered(
            lambda s: s.feasible and not s.is_chosen)[:1]
        self.batch.action_mark_bought()
        if scenario:
            with self.assertRaises(UserError):
                scenario.action_use()

    def test_an_out_of_date_batch_cannot_be_bought(self):
        self.design.write({'width_mm': 2500.0})
        self.design._explode()
        self.batch.invalidate_recordset()
        self.assertFalse(self.batch.is_current)
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()
        self.batch.action_generate()
        self.batch.action_mark_bought()
        self.assertEqual(self.batch.state, 'confirmed')

    def test_a_batch_with_pieces_off_the_bars_cannot_be_bought(self):
        self.batch.oversize_note = 'P1 is longer than any bar'
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()
        self.batch.oversize_note = False
        self.batch.blocked_note = 'RE-8 has no active bar length'
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()

    def test_a_batch_with_nothing_planned_cannot_be_bought(self):
        self.batch.group_ids.unlink()
        with self.assertRaises(UserError):
            self.batch.action_mark_bought()

    def test_a_final_batch_that_goes_stale_says_so_but_stays_final(self):
        self.batch.action_mark_bought()
        self.design.write({'width_mm': 2500.0})
        self.design._explode()
        self.batch.invalidate_recordset()
        self.assertFalse(self.batch.is_current)
        self.assertEqual(self.batch.state, 'confirmed')
