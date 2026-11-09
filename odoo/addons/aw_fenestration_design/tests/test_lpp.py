# -*- coding: utf-8 -*-
"""Last purchase price (LPP): written at confirm, shown, and used to start
a new line."""
import unittest
from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLastPurchasePrice(TransactionCase):

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
            if len(lines.filtered(
                    lambda l: l.attribute_id == finish_attr).value_ids) >= 2 \
                    and lines.filtered(
                        lambda l: l.attribute_id == thickness_attr).value_ids:
                cls.template = template
                break
        if not cls.template:
            raise unittest.SkipTest("No profile with two finishes here")
        lines = cls.template.attribute_line_ids
        cls.thickness = lines.filtered(
            lambda l: l.attribute_id == thickness_attr).value_ids[0]
        cls.f1, cls.f2 = lines.filtered(
            lambda l: l.attribute_id == finish_attr).value_ids[:2]
        cls.vendor = env['res.partner'].create({'name': 'LPP vendor'})
        for ft in (14.0, 16.0):
            env['aw.vendor.bar.length'].create({
                'vendor_id': cls.vendor.id,
                'product_tmpl_id': cls.template.id, 'length_ft': ft})
        cls.rate = env['aw.profile.rate'].create({
            'product_tmpl_id': cls.template.id,
            'thickness_id': cls.thickness.id, 'finish_id': cls.f1.id,
            'vendor_id': cls.vendor.id, 'price': 2.5,
            'date_from': '2000-01-01'})
        cls.manager = env['res.users'].create({
            'name': 'LPP rates manager', 'login': 'lpp_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_fenestration_manager').id,
            ])]})
        cls.buyer = env['res.users'].create({
            'name': 'LPP buyer', 'login': 'lpp_buyer',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('purchase.group_purchase_user').id])]})

    def _cell(self, finish, length, bars):
        return {'thickness_id': self.thickness.id, 'finish_id': finish.id,
                'length_ft': length, 'bars': bars}

    def _order(self, f1_price=None, cells=None):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id})
        order.aw_bars_grid_apply(self.template.id, cells or [
            self._cell(self.f1, 14.0, 2), self._cell(self.f2, 16.0, 1)])
        if f1_price is not None:
            order.order_line.filtered(
                lambda l: l.aw_bar_length_ft == 14.0).price_unit = f1_price
        return order

    def _confirm(self, order):
        order.with_context(aw_confirm_anyway=True).button_confirm()
        self.assertEqual(order.state, 'purchase')
        return order

    def _lpp(self, order=None):
        domain = [('vendor_id', '=', self.vendor.id)]
        if order:
            domain.append(('order_id', '=', order.id))
        return self.env['aw.profile.lpp'].search(domain)

    # -- written at confirm --------------------------------------------------
    def test_confirming_writes_a_row_per_priced_bars_line(self):
        order = self._order()
        self.assertFalse(self._lpp(order))
        self._confirm(order)
        rows = self._lpp(order)
        # f2 has no rate: priced 0, so no row
        self.assertEqual(len(rows), 1)
        row = rows
        self.assertEqual(row.vendor_id, self.vendor)
        self.assertEqual(row.product_tmpl_id, self.template)
        self.assertEqual(row.thickness_id, self.thickness)
        self.assertEqual(row.finish_id, self.f1)
        self.assertEqual(row.bar_length_ft, 14.0)
        self.assertAlmostEqual(row.price_ft, 2.5)
        self.assertEqual(row.date, order.date_approve.date())
        self.assertEqual(row.order_id, order)

    def test_a_discount_is_taken_off_and_the_price_is_per_ft(self):
        order = self._order()
        order.order_line.filtered(
            lambda l: l.aw_bar_length_ft == 14.0).discount = 10.0
        self._confirm(order)
        self.assertAlmostEqual(self._lpp(order).price_ft, 2.25)

    def test_last_is_the_latest_date_then_the_highest_line(self):
        first = self._confirm(self._order(f1_price=2.6))
        second = self._confirm(self._order(f1_price=2.7))
        Lpp = self.env['aw.profile.lpp']
        last = Lpp._last(self.vendor, self.template, self.thickness, self.f1)
        self.assertEqual(last.order_id, second)       # same day: higher line
        self._lpp(second).date = date(2000, 1, 1)
        last = Lpp._last(self.vendor, self.template, self.thickness, self.f1)
        self.assertEqual(last.order_id, first)
        self.assertEqual(len(self._lpp()), 2)         # history is kept

    def test_a_foreign_currency_is_converted_at_the_order_date(self):
        company = self.env.company
        foreign = self.env.ref('base.EUR')
        if company.currency_id == foreign:
            raise unittest.SkipTest("company is in EUR")
        foreign.active = True
        self.env['res.currency.rate'].create({
            'currency_id': foreign.id, 'company_id': company.id,
            'name': '2000-01-01', 'rate': 2.0})
        order = self._order()
        order.currency_id = foreign
        order.order_line.filtered(
            lambda l: l.aw_bar_length_ft == 14.0).price_unit = 5.0
        self._confirm(order)
        expected = foreign._convert(
            5.0, company.currency_id, company,
            order.date_order.date(), round=False)
        self.assertAlmostEqual(self._lpp(order).price_ft, expected, places=4)
        self.assertEqual(self._lpp(order).currency_id, company.currency_id)

    # -- cancel and delete -------------------------------------------------
    def test_a_cancelled_order_takes_its_rows_and_logs_it(self):
        order = self._confirm(self._order())
        self.assertTrue(self._lpp(order))
        order.button_unlock()
        order.button_cancel()
        self.assertFalse(self._lpp(order))
        body = ' '.join(self.vendor.message_ids.mapped('body'))
        self.assertIn('order cancelled', body)

    def test_a_rates_manager_can_delete_one_and_a_buyer_cannot(self):
        order = self._confirm(self._order())
        row = self._lpp(order)
        with self.assertRaises(AccessError):
            row.with_user(self.buyer).unlink()
        row.with_user(self.manager).unlink()
        self.assertFalse(self._lpp(order))
        body = ' '.join(self.vendor.message_ids.mapped('body'))
        self.assertIn('deleted', body)

    # -- starting a new line -----------------------------------------------
    def test_a_new_line_starts_at_the_last_paid_price(self):
        self._confirm(self._order(f1_price=2.9))
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id})
        order.aw_bars_grid_apply(self.template.id, [
            self._cell(self.f1, 16.0, 3)])
        line = order.order_line
        self.assertAlmostEqual(line.price_unit, 2.9)
        # the other figure is in the note
        self.assertIn('list 2.50', line.aw_price_note)
        data = order.aw_bars_grid_data(self.template.id)
        key = '%s|%s' % (self.thickness.id, self.f1.id)
        self.assertEqual(data['sources'][key], 'lpp')
        self.assertAlmostEqual(data['rates'][key], 2.9)

    def test_with_no_last_price_a_line_starts_at_the_list_and_notes_the_last(self):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id})
        order.aw_bars_grid_apply(self.template.id, [
            self._cell(self.f1, 16.0, 3)])
        line = order.order_line
        self.assertEqual(line.price_unit, 2.5)
        self.assertFalse(line.aw_price_note)
        self._confirm(self._order(f1_price=2.9))
        line.invalidate_recordset(['aw_price_note'])
        self.assertIn('last paid 2.90', line.aw_price_note)
        self.assertIn(self.thickness.name, line.aw_price_note)

    # -- the dialog at confirm ---------------------------------------------
    def test_a_price_far_from_the_list_asks_before_confirming(self):
        order = self._order(f1_price=4.0)              # list 2.5: +60%
        action = order.button_confirm()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(action['res_model'], 'aw.po.confirm.wizard')
        wizard = self.env['aw.po.confirm.wizard'].browse(action['res_id'])
        self.assertIn('+60.0%', wizard.summary)
        wizard.action_confirm()
        self.assertEqual(order.state, 'purchase')
        body = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('more than 15% from the list rate', body)

    def test_a_price_near_the_list_confirms_without_asking(self):
        order = self._order(f1_price=2.8)               # +12%
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')

    # -- the Rates tab -----------------------------------------------------
    def test_the_rates_tab_carries_the_last_price_and_the_difference(self):
        self._confirm(self._order(f1_price=2.75))
        data = self.template._aw_rates_table_data()
        mine = [r for r in data['lpp'] if r['v'] == self.vendor.id
                and r['t'] == self.thickness.id and r['f'] == self.f1.id]
        self.assertEqual(len(mine), 1)
        self.assertAlmostEqual(mine[0]['price'], 2.75)
        self.assertAlmostEqual(mine[0]['pct'], 10.0)
        self.assertTrue(mine[0]['po'])
        self.assertTrue(mine[0]['date'])

    # -- the list, the vendor button and the note ---------------------------
    def test_the_list_row_shows_the_variant_and_the_difference(self):
        self.env['aw.finish.name'].create({
            'finish_id': self.f1.id, 'vendor_id': self.vendor.id,
            'name': 'VND FINISH'})
        self._confirm(self._order(f1_price=2.75))
        row = self._lpp()
        self.assertEqual(row.finish_label, 'VND FINISH')
        self.assertAlmostEqual(row.list_rate, 2.5)
        self.assertAlmostEqual(row.vs_list_pct, 10.0)

    def test_the_vendor_button_counts_and_opens_its_prices(self):
        self.assertEqual(self.vendor.aw_lpp_count, 0)
        self._confirm(self._order())
        self.vendor.invalidate_recordset(['aw_lpp_count'])
        self.assertEqual(self.vendor.aw_lpp_count, 1)
        action = self.vendor.action_open_lpp()
        rows = self.env['aw.profile.lpp'].search(action['domain'])
        self.assertEqual(rows, self._lpp())

    def test_the_price_note_names_finish_thickness_and_date(self):
        self._confirm(self._order(f1_price=2.9))
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id})
        order.aw_bars_grid_apply(self.template.id, [
            self._cell(self.f1, 16.0, 3)])
        line = order.order_line
        line.price_unit = 2.5
        line.invalidate_recordset(['aw_price_note'])
        note = line.aw_price_note
        self.assertIn('last paid 2.90 (', note)
        self.assertIn(self.thickness.name, note)
        self.assertIn(' on ', note)
