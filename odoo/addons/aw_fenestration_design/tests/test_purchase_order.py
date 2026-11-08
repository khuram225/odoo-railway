# -*- coding: utf-8 -*-
"""P2: the purchase order made from a Draft batch."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPurchaseOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'PO customer'}).id,
            'aw_default_series_id': series.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        windows = env['aw.design']
        for location in ('Hall', 'Kitchen'):
            design = cls.order._create_fenestration_position(
                series, family=family, location=location)
            design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': 1800.0,
                          'leaves': [dict(leaf), dict(leaf)]}]})
            windows |= design
        cls.hall, cls.kitchen = windows
        cls.manager = env['res.users'].create({
            'name': 'PO manager', 'login': 'po_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_fenestration_manager').id,
            ])]})
        cls.seller = env['res.users'].create({
            'name': 'PO seller', 'login': 'po_seller',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_design.group_fenestration_sales').id,
            ])]})

    def _batch(self, design):
        action = self.order.action_new_batch()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.line_ids.filtered(
            lambda l: l.design_id != design).selected = False
        wizard.action_create()
        return self.order.aw_cut_plan_ids.filtered(
            lambda p: design in p.design_ids and p.state != 'cancel')

    def _rated(self, batch, rate=2.5):
        """Give every group a vendor rate in force, as a real one would."""
        batch.group_ids.write({
            'rate_per_ft': rate, 'rate_date': '2026-01-01'})

    def test_one_line_per_profile_and_length_with_bars_times_length(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        order = batch.purchase_order_id
        self.assertEqual(order.partner_id, batch.profile_vendor_id)
        self.assertEqual(order.state, 'draft')
        want = {}
        for group in batch.group_ids:
            for bar in group.bar_ids.filtered(lambda b: not b.from_bar_id):
                key = (group.product_id, round(bar.stock_mm / 304.8, 4))
                want[key] = want.get(key, 0) + 1
        got = {(l.product_id, l.aw_bar_length_ft): l.aw_bar_count
               for l in order.order_line}
        self.assertEqual(got, want)
        foot = self.env.ref('uom.product_uom_foot')
        self.assertTrue(foot.active)
        for line in order.order_line:
            self.assertEqual(line.product_uom_id, foot)
            self.assertAlmostEqual(
                line.product_qty, line.aw_bar_count * line.aw_bar_length_ft)
            self.assertEqual(line.price_unit, 2.5)
            self.assertFalse(line.aw_price_note)
        self.assertEqual(
            sum(l.aw_bar_count for l in order.order_line), batch.bar_count)

    def test_the_quote_cost_sits_next_to_the_order_total(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        self.assertAlmostEqual(
            batch.po_total, batch.purchase_order_id.amount_untaxed)
        self.assertAlmostEqual(
            batch.po_vs_quote, batch.po_total - batch.cost_total)

    def test_a_profile_with_no_rate_is_on_the_order_marked_no_price(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        first = batch.group_ids[:1]
        first.write({'rate_date': False, 'rate_per_ft': 7.0})
        batch.action_create_purchase_order()
        lines = batch.purchase_order_id.order_line
        bare = lines.filtered(lambda l: l.product_id == first.product_id)
        self.assertTrue(bare, "the unrated profile must not be left out")
        for line in bare:
            self.assertEqual(line.price_unit, 0.0)
            self.assertEqual(line.aw_price_note, 'No price')
        self.assertEqual(len(lines), len(batch._purchase_lines()))

    def test_changing_the_bars_changes_the_quantity_not_the_price(self):
        batch = self._batch(self.hall)
        self._rated(batch, rate=3.25)
        batch.action_create_purchase_order()
        line = batch.purchase_order_id.order_line[:1]
        line.aw_bar_count += 2
        self.assertAlmostEqual(
            line.product_qty, line.aw_bar_count * line.aw_bar_length_ft)
        self.assertEqual(line.price_unit, 3.25)
        line.product_id.standard_price = 99.0
        line.aw_bar_count += 1
        self.assertEqual(line.price_unit, 3.25)

    def test_a_quantity_that_is_not_bars_times_length_is_refused(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        line = batch.purchase_order_id.order_line[:1]
        with self.assertRaises(ValidationError):
            line.product_qty = line.product_qty + 1.0

    def test_an_ordinary_line_is_untouched(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        product = batch.group_ids[:1].product_id
        order = self.env['purchase.order'].create({
            'partner_id': batch.profile_vendor_id.id,
            'order_line': [(0, 0, {
                'product_id': product.id, 'product_qty': 5.0})]})
        line = order.order_line
        self.assertFalse(line.aw_is_bars)
        self.assertEqual(line.product_qty, 5.0)

    def test_stock_bars_are_not_bought(self):
        first = self._batch(self.hall)
        first.group_ids[:1].bar_ids[:1].write(
            {'remainder_mm': 3000.0, 'is_returnable': True})
        first.action_mark_bought()
        second = self._batch(self.kitchen)
        self._rated(second)
        second.action_create_purchase_order()
        bought = second.group_ids.bar_ids.filtered(
            lambda b: not b.from_bar_id)
        self.assertEqual(
            sum(second.purchase_order_id.order_line.mapped('aw_bar_count')),
            len(bought))

    def test_one_order_and_only_for_a_current_draft_batch(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        with self.assertRaises(UserError):
            batch.action_create_purchase_order()
        batch.purchase_order_id.button_cancel()
        batch.action_create_purchase_order()     # a cancelled one is replaced
        self.assertEqual(batch.purchase_order_id.state, 'draft')
        stale = self._batch(self.kitchen)
        stale.bom_fingerprint = 'old'
        with self.assertRaises(UserError):
            stale.action_create_purchase_order()

    def test_a_final_batch_gets_no_new_order(self):
        batch = self._batch(self.hall)
        batch.action_mark_bought()
        with self.assertRaises(UserError):
            batch.action_create_purchase_order()

    def test_a_manager_without_purchase_rights_can_make_it(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.with_user(self.manager).action_create_purchase_order()
        self.assertTrue(batch.purchase_order_id)
        self.assertEqual(batch.purchase_order_id.create_uid, self.manager)

    def test_the_button_is_only_in_a_managers_form(self):
        Plan = self.env['aw.cut.plan']
        manager = Plan.with_user(self.manager).get_view(
            view_type='form')['arch']
        seller = Plan.with_user(self.seller).get_view(
            view_type='form')['arch']
        self.assertIn('action_create_purchase_order', manager)
        self.assertNotIn('action_create_purchase_order', seller)
