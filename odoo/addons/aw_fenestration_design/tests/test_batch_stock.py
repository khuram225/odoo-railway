# -*- coding: utf-8 -*-
"""Plan from stock: a batch cuts from what earlier Final batches left."""
from odoo.addons.aw_fenestration_design.models.cut_algorithm import (
    piece_demand_mm)
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchStock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Stock customer'}).id,
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
        cls.manager = env['res.users'].create({
            'name': 'Stock manager', 'login': 'stock_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_fenestration_manager').id,
            ])]})
        cls.seller = env['res.users'].create({
            'name': 'Stock seller', 'login': 'stock_seller',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_design.group_fenestration_sales').id,
            ])]})

    def _batch(self, design):
        """A batch of one window."""
        action = self.order.action_new_batch()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.line_ids.filtered(
            lambda l: l.design_id != design).selected = False
        wizard.action_create()
        return self.order.aw_cut_plan_ids.filtered(
            lambda p: design in p.design_ids and p.state != 'cancel')

    def _final_batch_with_a_big_offcut(self):
        """Hall's batch, Final, with one bar left holding 3000 mm."""
        first = self._batch(self.hall)
        bar = first.group_ids[:1].bar_ids[:1]
        bar.write({'remainder_mm': 3000.0, 'is_returnable': True})
        first.action_mark_bought()
        return first, bar

    # -- using the offcut ----------------------------------------------------
    def test_a_later_batch_cuts_from_the_offcut_before_buying(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)
        used = second.group_ids.bar_ids.filtered(
            lambda b: b.from_bar_id == bar)
        self.assertTrue(used, "the 3000 mm offcut should have been used")
        for stock_bar in used:
            demand = sum(piece_demand_mm(c.length_mm, second.kerf_mm,
                                         c.cut_angle or '45')
                         for c in stock_bar.cut_ids)
            self.assertLessEqual(
                demand, stock_bar.stock_mm - second.start_trim_mm + 1e-6)
        self.assertEqual(second.stock_bars_used, len(
            second.group_ids.bar_ids.filtered('from_bar_id')))
        self.assertTrue(second.stock_planned)

    def test_stock_takes_pieces_off_the_bars_to_buy(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)

        def bought_cuts():
            return len(second.group_ids.bar_ids.filtered(
                lambda b: not b.from_bar_id).cut_ids)
        with_stock, feet_with = bought_cuts(), second.feet_bought
        second.with_user(self.manager).write({
            'plan_without_stock': True, 'no_stock_reason': 'offcut is bent'})
        second.action_generate()
        self.assertEqual(second.stock_bars_used, 0)
        self.assertGreater(bought_cuts(), with_stock)
        self.assertGreaterEqual(second.feet_bought, feet_with)
        second.with_user(self.manager).write({'plan_without_stock': False})
        second.action_generate()
        self.assertEqual(bought_cuts(), with_stock)

    def test_every_piece_is_still_cut_exactly_once(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)
        planned = second.group_ids.bar_ids.cut_ids.bom_line_id
        want = sum(max(1, l.qty or 1) for l in second._profile_lines())
        self.assertEqual(len(second.group_ids.bar_ids.cut_ids), want)
        self.assertTrue(planned <= self.kitchen.bom_line_ids)

    def test_an_offcut_serves_one_active_batch_and_is_freed_by_a_cancel(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)
        third = self._batch(self.study)
        active = self.env['aw.cut.plan.bar'].search_count([
            ('from_bar_id', '=', bar.id),
            ('group_id.plan_id.state', '!=', 'cancel')])
        self.assertEqual(active, 1)
        product = bar.group_id.product_id
        self.assertNotIn(bar, third._stock_for(product))
        second.action_cancel_batch()
        self.assertIn(bar, third._stock_for(product))

    def test_only_final_batches_offer_stock(self):
        first = self._batch(self.hall)
        first.group_ids[:1].bar_ids[:1].write(
            {'remainder_mm': 3000.0, 'is_returnable': True})
        second = self._batch(self.kitchen)         # first is still Draft
        self.assertFalse(second.stock_bars_used)

    def test_choosing_an_option_keeps_the_offcuts_in_use(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)
        group = second.group_ids.filtered(
            lambda g: g.bar_ids.filtered('from_bar_id'))[:1]
        before = group.bar_ids.filtered('from_bar_id')
        group.action_clear_override()
        self.assertEqual(group.bar_ids.filtered('from_bar_id'), before)

    # -- the rule before a batch is final ----------------------------------------
    def test_a_batch_not_planned_from_stock_cannot_be_bought(self):
        batch = self._batch(self.hall)
        batch.stock_planned = False
        with self.assertRaises(UserError):
            batch.action_mark_bought()
        batch.action_generate()
        batch.action_mark_bought()
        self.assertEqual(batch.state, 'confirmed')

    def test_planning_without_stock_needs_a_manager_and_a_reason(self):
        batch = self._batch(self.hall)
        with self.assertRaises(UserError):
            batch.with_user(self.seller).write({'plan_without_stock': True})
        batch.with_user(self.manager).write({'plan_without_stock': True})
        batch.action_generate()
        self.assertFalse(batch.stock_planned)
        with self.assertRaises(UserError):
            batch.action_mark_bought()                  # no reason yet
        batch.with_user(self.manager).write({'no_stock_reason': 'no stock'})
        batch.action_mark_bought()
        self.assertEqual(batch.state, 'confirmed')

    def test_a_batch_whose_offcuts_are_in_use_cannot_be_reopened(self):
        first, bar = self._final_batch_with_a_big_offcut()
        second = self._batch(self.kitchen)
        self.assertTrue(second.stock_bars_used)
        with self.assertRaises(UserError):
            first.with_user(self.manager).action_reopen_batch()
        second.action_cancel_batch()
        first.with_user(self.manager).action_reopen_batch()
