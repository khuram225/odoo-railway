# -*- coding: utf-8 -*-
"""Receiving bars: lots per variant and length, one receipt per delivery."""
import unittest

from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_design.models.po_receipt import length_mm


@tagged('post_install', '-at_install')
class TestReceiveBars(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        category = env.ref('aw_fenestration_core.product_category_profiles')
        thickness_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        cls.template = env['product.template']
        for template in env['product.template'].search(
                [('categ_id', 'child_of', category.id)]):
            lines = template.attribute_line_ids
            if lines.filtered(lambda l: l.attribute_id == finish_attr).value_ids \
                    and lines.filtered(
                        lambda l: l.attribute_id == thickness_attr).value_ids:
                cls.template = template
                break
        if not cls.template:
            raise unittest.SkipTest("No profile here")
        lines = cls.template.attribute_line_ids
        cls.thickness = lines.filtered(
            lambda l: l.attribute_id == thickness_attr).value_ids[0]
        cls.finish = lines.filtered(
            lambda l: l.attribute_id == finish_attr).value_ids[0]
        cls.template.sudo().is_storable = True
        cls.vendor = env['res.partner'].create({'name': 'Receive vendor'})
        for ft in (14.0, 16.0, 18.0):
            env['aw.vendor.bar.length'].create({
                'vendor_id': cls.vendor.id,
                'product_tmpl_id': cls.template.id, 'length_ft': ft})
        env['aw.profile.rate'].create({
            'product_tmpl_id': cls.template.id,
            'thickness_id': cls.thickness.id, 'finish_id': cls.finish.id,
            'vendor_id': cls.vendor.id, 'price': 2.5,
            'date_from': '2000-01-01'})

    def _order(self, cells):
        """A confirmed order: cells = [(length_ft, bars)]."""
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id})
        order.aw_bars_grid_apply(self.template.id, [
            {'thickness_id': self.thickness.id, 'finish_id': self.finish.id,
             'length_ft': length, 'bars': bars} for length, bars in cells])
        order.with_context(aw_confirm_anyway=True).button_confirm()
        self.assertEqual(order.state, 'purchase')
        self.product = order.order_line[:1].product_id
        return order

    def _row(self, length, bars, product=None):
        return {'product_id': (product or self.product).id,
                'bar_length_ft': length, 'bars': bars}

    def _open_ft(self, order):
        moves = order.order_line.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel'))
        return sum(moves.mapped('product_uom_qty'))

    # -- the lot ------------------------------------------------------------
    def test_length_in_whole_millimetres(self):
        self.assertEqual(length_mm(14.0), 4267)
        self.assertEqual(length_mm(16.0), 4877)
        self.assertEqual(length_mm(18.0), 5486)

    def test_a_full_delivery_makes_lots_and_one_receipt(self):
        order = self._order([(14.0, 10), (18.0, 4)])
        receipt = order._aw_receive_bars(
            [self._row(14.0, 10), self._row(18.0, 4)])
        self.assertEqual(receipt.picking_id.state, 'done')
        self.assertEqual(len(order.picking_ids), 1)
        lots = receipt.line_ids.lot_id
        self.assertEqual(sorted(lots.mapped('length_mm')), [4267, 5486])
        self.assertEqual(set(lots.mapped('profile_source')), {'purchased'})
        feet = {line.bar_length_ft: line.feet for line in receipt.line_ids}
        self.assertEqual(feet, {14.0: 140.0, 18.0: 72.0})
        lines = order.order_line.sorted('aw_bar_length_ft')
        self.assertEqual(lines.mapped('qty_received'), [140.0, 72.0])
        self.assertEqual(order.receipt_status, 'full')
        self.assertEqual(receipt.counted_by_id, self.env.user)

    def test_a_partial_delivery_leaves_the_order_open(self):
        order = self._order([(14.0, 10), (18.0, 4)])
        first = order._aw_receive_bars([self._row(14.0, 6)])
        self.assertEqual(first.picking_id.state, 'done')
        self.assertEqual(order.receipt_status, 'partial')
        self.assertAlmostEqual(self._open_ft(order), 56.0 + 72.0)
        second = order._aw_receive_bars(
            [self._row(14.0, 4), self._row(18.0, 4)])
        self.assertNotEqual(second.picking_id, first.picking_id)
        self.assertEqual(second.picking_id.state, 'done')
        self.assertEqual(order.receipt_status, 'full')
        self.assertEqual(len(order.aw_receipt_ids), 2)

    # -- any mix ------------------------------------------------------------
    def test_another_length_is_added_at_receipt_and_the_open_demand_follows(self):
        order = self._order([(14.0, 10), (18.0, 4)])       # 212 ft
        price = order.order_line[:1].price_unit
        receipt = order._aw_receive_bars([self._row(16.0, 13)])   # 208 ft
        added = order.order_line.filtered('aw_added_at_receipt')
        self.assertEqual(len(added), 1)
        self.assertEqual(added.aw_bar_length_ft, 16.0)
        self.assertEqual(added.aw_bar_count, 13)
        self.assertEqual(added.price_unit, price)
        self.assertIn('Added at receipt', added.aw_price_note)
        self.assertEqual(receipt.line_ids.lot_id.length_mm, 4877)
        self.assertTrue(receipt.line_ids.added_at_receipt)
        # 212 ordered, 208 arrived: 4 ft still to come, not 212
        self.assertAlmostEqual(self._open_ft(order), 4.0)
        body = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('4 ft short', body)
        self.assertIn('Line added at receipt', body)

    def test_a_different_mix_of_the_same_feet_closes_the_order(self):
        order = self._order([(16.0, 9)])                   # 144 ft
        order._aw_receive_bars([self._row(18.0, 8)])        # 144 ft
        self.assertAlmostEqual(self._open_ft(order), 0.0)
        self.assertEqual(order.receipt_status, 'full')
        body = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('complete', body)

    def test_more_bars_than_ordered_go_on_an_added_line(self):
        order = self._order([(14.0, 10)])
        order._aw_receive_bars([self._row(14.0, 12)])
        added = order.order_line.filtered('aw_added_at_receipt')
        self.assertEqual((added.aw_bar_length_ft, added.aw_bar_count),
                         (14.0, 2))
        body = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('28 ft over', body)

    # -- guards ---------------------------------------------------------------
    def test_nothing_to_receive_is_refused(self):
        order = self._order([(14.0, 10)])
        with self.assertRaises(UserError):
            order._aw_receive_bars([self._row(14.0, 0)])
        wizard = self.env['aw.po.receive.wizard'].browse(
            order.action_receive_bars()['res_id'])
        self.assertTrue(wizard.all_zero)
        with self.assertRaises(UserError):
            wizard.action_validate()

    def test_a_large_row_must_be_confirmed(self):
        order = self._order([(14.0, 10)])
        wizard = self.env['aw.po.receive.wizard'].browse(
            order.action_receive_bars()['res_id'])
        row = wizard.line_ids.filtered(
            lambda l: l.kind == 'length' and l.bar_length_ft == 14.0)
        row.bars = 101
        self.assertTrue(wizard.has_large)
        with self.assertRaises(UserError):
            wizard.action_validate()

    # -- the screen -----------------------------------------------------------
    def test_every_active_length_is_a_ready_row_with_a_subtotal(self):
        order = self._order([(14.0, 10), (18.0, 4)])
        wizard = self.env['aw.po.receive.wizard'].browse(
            order.action_receive_bars()['res_id'])
        rows = wizard.line_ids.filtered(lambda l: l.kind == 'length')
        self.assertEqual(sorted(rows.mapped('bar_length_ft')),
                         [14.0, 16.0, 18.0])
        self.assertEqual(set(rows.mapped('bars')), {0})
        total = wizard.line_ids.filtered(lambda l: l.kind == 'total')
        self.assertEqual(len(total), 1)
        self.assertEqual(total.ordered_ft, 212.0)
        rows.filtered(lambda l: l.bar_length_ft == 16.0).bars = 5
        self.assertEqual(total.arriving_ft, 80.0)
        self.assertIn('short', total.status)

    def test_a_variant_that_is_not_on_the_order_can_be_added(self):
        order = self._order([(14.0, 10)])
        attr_lines = self.template.attribute_line_ids
        finishes = attr_lines.filtered(
            lambda l: l.attribute_id == self.env.ref(
                'aw_fenestration_core.aw_attribute_finish')).value_ids
        thicknesses = attr_lines.filtered(
            lambda l: l.attribute_id == self.env.ref(
                'aw_fenestration_core.aw_attribute_thickness')).value_ids
        other = self.env['product.product']
        for finish in finishes:
            for thickness in thicknesses:
                variant = self.env['aw.profile.section.line']._variant_for(
                    self.template, thickness, finish)
                if variant and variant != self.product:
                    other = variant
                    break
            if other:
                break
        if not other:
            self.skipTest("This profile has a single variant")
        receipt = order._aw_receive_bars([self._row(16.0, 2, product=other)])
        self.assertEqual(receipt.picking_id.state, 'done')

    # -- the group and the setting ----------------------------------------------
    def test_the_group_brings_purchase_and_stock_and_the_manager_has_it(self):
        group = self.env.ref(
            'aw_fenestration_design.group_fenestration_purchasing')
        implied = group.implied_ids
        self.assertIn(self.env.ref('purchase.group_purchase_user'), implied)
        self.assertIn(self.env.ref('stock.group_stock_user'), implied)
        manager = self.env.ref('aw_fenestration_core.group_fenestration_manager')
        self.assertIn(group, manager.implied_ids)

    def test_prices_can_be_hidden_from_people_who_only_count(self):
        counter = self.env['res.users'].create({
            'name': 'Counter', 'login': 'bars_counter',
            'group_ids': [(6, 0, [self.env.ref(
                'aw_fenestration_design.group_fenestration_purchasing').id])]})
        order = self._order([(14.0, 10)])
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.receive_hide_prices', '1')
        shown = self.env['aw.po.receive.wizard'].browse(
            order.action_receive_bars()['res_id'])
        self.assertFalse(shown.hide_prices)          # the test user is admin
        self.assertTrue(shown.with_user(counter).hide_prices)
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.receive_hide_prices', '')
        shown.invalidate_recordset(['hide_prices'])    # the setting is not a dependency
        self.assertFalse(shown.with_user(counter).hide_prices)

    # -- vendor bills follow what was received -------------------------------
    def _bill_quantities(self, order):
        """What the bill takes, per line: Odoo's own line values (needs no
        chart of accounts), and the real bill when this database can make
        one."""
        wanted = {}
        for line in order.order_line:
            if line.qty_to_invoice:
                values = line._prepare_account_move_line()
                wanted[line] = values['quantity']
        return wanted

    def test_the_control_policy_of_a_profile_is_receive(self):
        self.assertEqual(self.template.purchase_method, 'receive')
        new = self.env['product.template'].create({
            'name': 'Bills test profile', 'type': 'consu',
            'categ_id': self.template.categ_id.id})
        self.assertEqual(new.purchase_method, 'receive')
        stale = self.env['product.template'].create({
            'name': 'Bills stale profile', 'type': 'consu',
            'categ_id': self.template.categ_id.id,
            'purchase_method': 'purchase'})
        self.assertEqual(stale.purchase_method, 'purchase')   # asked for
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.profile_purchase_method_set', '')
        self.env['product.template']._aw_set_profile_receive()
        self.assertEqual(stale.purchase_method, 'receive')
        stale.purchase_method = 'purchase'
        self.env['product.template']._aw_set_profile_receive()
        self.assertEqual(stale.purchase_method, 'purchase')   # once only

    def test_the_bill_takes_the_received_quantity(self):
        order = self._order([(14.0, 10), (18.0, 4)])
        self.assertEqual(self._bill_quantities(order), {})   # nothing yet
        order._aw_receive_bars([self._row(14.0, 6)])          # 84 ft
        quantities = self._bill_quantities(order)
        self.assertEqual(sorted(quantities.values()), [84.0])
        line = list(quantities)[0]
        self.assertEqual(line.qty_received, 84.0)
        try:
            order.action_create_invoice()
        except (UserError, RedirectWarning):
            return          # this database has no accounts to bill into
        bill = order.invoice_ids
        self.assertEqual(sum(bill.invoice_line_ids.mapped('quantity')), 84.0)

    def test_bars_that_were_not_ordered_are_billed_and_the_rest_is_not(self):
        order = self._order([(14.0, 10)])
        order._aw_receive_bars([self._row(16.0, 2)])          # 32 ft
        quantities = self._bill_quantities(order)
        self.assertEqual(
            {l.aw_added_at_receipt: q for l, q in quantities.items()},
            {True: 32.0})
