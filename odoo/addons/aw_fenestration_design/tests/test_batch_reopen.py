# -*- coding: utf-8 -*-
"""Reopen batch: a Final batch back to Draft, for managers, with a reason."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchReopen(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Reopen customer'}).id,
            'aw_default_series_id': series.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        design = cls.order._create_fenestration_position(
            series, family=family, location='Hall')
        design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        action = cls.order.action_new_batch()
        env[action['res_model']].browse(action['res_id']).action_create()
        cls.batch = cls.order.aw_cut_plan_ids
        cls.manager = env['res.users'].create({
            'name': 'Fen manager', 'login': 'reopen_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_fenestration_manager').id,
            ])]})
        cls.seller = env['res.users'].create({
            'name': 'Fen seller', 'login': 'reopen_seller',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_design.group_fenestration_sales').id,
            ])]})

    def _final(self):
        self.batch.action_mark_bought()
        self.assertEqual(self.batch.state, 'confirmed')

    def _reopen(self, user, reason='A window was added'):
        wizard = self.env['aw.cut.reopen.wizard'].with_user(user).create({
            'plan_id': self.batch.id, 'reason': reason})
        return wizard.action_reopen()

    def test_a_manager_reopens_a_final_batch_with_a_reason(self):
        self._final()
        self._reopen(self.manager, 'Customer added a window')
        self.assertEqual(self.batch.state, 'draft')
        self.assertFalse(self.batch.bought_on or self.batch.bought_by)
        body = ' '.join(self.order.message_ids.mapped('body'))
        self.assertIn('reopened', body)
        self.assertIn('Customer added a window', body)
        self.assertIn('Fen manager', body)

    def test_after_reopening_the_batch_can_be_changed_again(self):
        self._final()
        self._reopen(self.manager)
        self.batch.action_generate()
        self.batch.action_mark_bought()
        self.assertEqual(self.batch.state, 'confirmed')

    def test_someone_who_is_not_a_manager_cannot(self):
        self._final()
        with self.assertRaises(UserError):
            self.batch.with_user(self.seller).action_reopen_batch()
        wizard = self.env['aw.cut.reopen.wizard'].create({
            'plan_id': self.batch.id, 'reason': 'because'})
        with self.assertRaises(UserError):
            wizard.with_user(self.seller).action_reopen()
        self.assertEqual(self.batch.state, 'confirmed')

    def test_a_reason_is_required(self):
        self._final()
        wizard = self.env['aw.cut.reopen.wizard'].with_user(
            self.manager).create({'plan_id': self.batch.id, 'reason': '  '})
        with self.assertRaises(UserError):
            wizard.action_reopen()
        self.assertEqual(self.batch.state, 'confirmed')

    def test_only_a_final_batch_can_be_reopened(self):
        with self.assertRaises(UserError):
            self.batch.with_user(self.manager).action_reopen_batch()

    def test_the_button_is_only_in_a_managers_form(self):
        Plan = self.env['aw.cut.plan']
        manager = Plan.with_user(self.manager).get_view(
            view_type='form')['arch']
        seller = Plan.with_user(self.seller).get_view(
            view_type='form')['arch']
        self.assertIn('action_reopen_batch', manager)
        self.assertNotIn('action_reopen_batch', seller)
