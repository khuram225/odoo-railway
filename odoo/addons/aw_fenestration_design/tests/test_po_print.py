# -*- coding: utf-8 -*-
"""The RFQ / purchase order printout for a profile order."""
import unittest

from odoo.tests import TransactionCase, tagged


def _grouped(value):
    return '{:,.2f}'.format(value)


@tagged('post_install', '-at_install')
class TestPurchaseOrderPrint(TransactionCase):

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
        cls.vendor = env['res.partner'].create({'name': 'Print vendor'})
        for ft in (14.0, 16.0, 18.0):
            env['aw.vendor.bar.length'].create({
                'vendor_id': cls.vendor.id,
                'product_tmpl_id': cls.template.id, 'length_ft': ft})
        for finish, price in ((cls.f1, 2.5), (cls.f2, 3.25)):
            env['aw.profile.rate'].create({
                'product_tmpl_id': cls.template.id,
                'thickness_id': cls.thickness.id, 'finish_id': finish.id,
                'vendor_id': cls.vendor.id, 'price': price,
                'date_from': '2000-01-01'})
        cls.plain = env['product.product'].create({
            'name': 'Plain printed part', 'type': 'consu'})

    def _cell(self, finish, length, bars):
        return {'thickness_id': self.thickness.id, 'finish_id': finish.id,
                'length_ft': length, 'bars': bars}

    def _order(self, with_plain=False):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id, 'origin': 'S00099 / Batch 2'})
        order.aw_bars_grid_apply(self.template.id, [
            self._cell(self.f1, 14.0, 2), self._cell(self.f1, 16.0, 1),
            self._cell(self.f2, 18.0, 3), self._cell(self.f2, 14.0, 4)])
        if with_plain:
            self.env['purchase.order.line'].create({
                'order_id': order.id, 'product_id': self.plain.id,
                'product_qty': 2.0, 'price_unit': 10.0})
        return order

    def _html(self, order, report='purchase.report_purchaseorder'):
        return self.env['ir.actions.report']._render_qweb_html(
            report, order.ids)[0].decode()

    def test_the_matrix_has_a_row_per_finish_and_a_column_per_length(self):
        order = self._order()
        data = order.aw_print_data()
        self.assertEqual(data['lengths'], [14.0, 16.0, 18.0])
        self.assertEqual(len(data['rows']), 2)
        by_finish = {r['finish']: r for r in data['rows']}
        first = by_finish[order._aw_finish_label(self.f1, self.vendor)]
        self.assertEqual(first['cells'], {14.0: 2, 16.0: 1})
        self.assertEqual(first['bars'], 3)
        self.assertAlmostEqual(first['feet'], 2 * 14 + 16)
        second = by_finish[order._aw_finish_label(self.f2, self.vendor)]
        self.assertEqual(second['cells'], {14.0: 4, 18.0: 3})
        self.assertAlmostEqual(first['rate'], 2.5)

    def test_the_summaries_add_up(self):
        data = self._order().aw_print_data()
        self.assertEqual(data['bars'], 10)
        self.assertEqual(
            [(i['length'], i['bars']) for i in data['by_length']],
            [(14.0, 6), (16.0, 1), (18.0, 3)])
        self.assertAlmostEqual(
            sum(i['feet'] for i in data['by_length']), data['feet'])
        self.assertAlmostEqual(sum(i['share'] for i in data['profiles']), 100.0)
        self.assertAlmostEqual(
            sum(i['amount'] for i in data['profiles']), data['bars_amount'])

    def test_the_printed_totals_equal_the_order_totals(self):
        order = self._order(with_plain=True)
        data = order.aw_print_data()
        self.assertAlmostEqual(data['subtotal'], order.amount_untaxed)
        self.assertAlmostEqual(data['tax'], order.amount_tax)
        self.assertAlmostEqual(data['total'], order.amount_total)
        self.assertAlmostEqual(
            data['bars_amount'] + data['other_amount'], order.amount_untaxed)
        order.aw_show_prices = True
        html = self._html(order)
        self.assertIn('o_aw_matrix', html)
        self.assertIn(_grouped(order.amount_total), html)
        self.assertIn(_grouped(order.amount_untaxed), html)
        for row in data['rows']:
            self.assertIn(_grouped(row['amount']), html)
        # the line the matrix does not take over is still printed
        self.assertIn('Plain printed part', html)

    def test_prices_follow_the_state_and_the_tick(self):
        order = self._order()
        self.assertFalse(order.aw_show_prices)
        order.write({'state': 'purchase'})
        self.assertTrue(order.aw_show_prices)
        order.aw_show_prices = False
        html = self._html(order)
        self.assertIn('o_aw_matrix', html)
        self.assertNotIn(_grouped(order.amount_total), html)

    def test_the_header_carries_the_source_and_the_terms(self):
        order = self._order()
        term = self.env['account.payment.term'].search([], limit=1)
        order.payment_term_id = term
        html = self._html(order)
        self.assertIn('S00099 / Batch 2', html)
        if term:
            self.assertIn(term.name, html)
        self.assertIn(order.name, html)

    def test_the_request_for_quotation_prints_the_matrix_without_prices(self):
        order = self._order()
        html = self._html(order, 'purchase.report_purchasequotation')
        self.assertIn('o_aw_matrix', html)
        self.assertNotIn(_grouped(order.amount_total), html)

    def test_an_order_without_bars_prints_as_before(self):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id, 'order_line': [(0, 0, {
                'product_id': self.plain.id, 'product_qty': 3.0,
                'price_unit': 7.0})]})
        order.aw_show_prices = True
        html = self._html(order)
        self.assertNotIn('o_aw_matrix', html)
        self.assertIn('Plain printed part', html)
        self.assertIn(_grouped(order.amount_total), html)
