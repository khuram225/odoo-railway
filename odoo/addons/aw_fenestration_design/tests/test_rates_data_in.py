# -*- coding: utf-8 -*-
"""The Data in screen: a second upload is refused, Clear all lines, and a row
repeated with the same price counts once while two prices stay a problem."""
import base64
import io
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesDataIn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Data in vendor'})
        Type = env['aw.glass.type']
        cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        if not cls.clear:
            Type._seed_glass_types()
            cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        env['aw.glass.rate'].create({
            'glass_type_id': cls.clear.id, 'thickness_mm': 5,
            'vendor_id': cls.vendor.id, 'price': 90.0,
            'date_from': date(2025, 6, 1)})
        cls.plain = env['res.users'].create({
            'name': 'Plain', 'login': 'datain_plain',
            'group_ids': [(6, 0, [env.ref('base.group_user').id])]})
        cls.manager = env['res.users'].create({
            'name': 'Rates clearer', 'login': 'datain_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_rates_manager').id])]})

    def _list(self):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'glass',
            'date': date(2026, 11, 1)})
        rate_list.action_next_step()
        return rate_list

    def _upload(self, rate_list):
        action = rate_list.action_template_current()
        wiz = self.env[action['res_model']].browse(action['res_id'])
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(base64.b64decode(wiz.file_data)))
        book['Rates'].cell(row=2, column=3).value = 95.0
        out = io.BytesIO()
        book.save(out)
        up = self.env['aw.vendor.rate.upload.wizard'].create({
            'list_id': rate_list.id, 'file_name': 'f.xlsx',
            'file_data': base64.b64encode(out.getvalue())})
        return up.action_read()

    def _line(self, rate_list, price, mm='6mm'):
        return self.env['aw.vendor.rate.list.line'].create({
            'list_id': rate_list.id, 'code': 'Clear', 'thickness_text': mm,
            'rate_1': price})

    def test_a_second_upload_is_refused(self):
        rate_list = self._list()
        self._upload(rate_list)
        self.assertEqual(len(rate_list.line_ids), 1)
        with self.assertRaises(UserError) as caught:
            self._upload(rate_list)
        self.assertIn('already has lines. Clear them first',
                      str(caught.exception))
        with self.assertRaises(UserError):
            rate_list.action_upload_template()
        self.assertEqual(len(rate_list.line_ids), 1)

    def test_clear_all_lines_then_upload_again(self):
        rate_list = self._list()
        self._upload(rate_list)
        rate_list.with_user(self.manager).action_clear_lines()
        self.assertFalse(rate_list.line_ids)
        self.assertFalse(rate_list.upload_summary)
        self.assertIn('cleared all 1 line', ' '.join(
            rate_list.message_ids.mapped('body')))
        self._upload(rate_list)
        self.assertEqual(len(rate_list.line_ids), 1)

    def test_only_a_rates_manager_clears_and_not_an_applied_list(self):
        rate_list = self._list()
        self._line(rate_list, 100.0)
        with self.assertRaises(UserError):
            rate_list.with_user(self.plain).action_clear_lines()
        rate_list.state = 'applied'
        with self.assertRaises(UserError):
            rate_list.with_user(self.manager).action_clear_lines()

    def test_clearing_sends_a_review_back_to_data_in(self):
        rate_list = self._list()
        self._line(rate_list, 100.0)
        rate_list.action_open_review()
        rate_list.with_user(self.manager).action_clear_lines()
        self.assertEqual(rate_list.step, 'data')
        self.assertFalse(rate_list.review_ids)

    def test_the_same_price_twice_counts_once_in_review(self):
        rate_list = self._list()
        self._line(rate_list, 100.0, '8mm')
        self._line(rate_list, 100.0, '8mm')
        rate_list.action_open_review()
        self.assertEqual(rate_list.review_problem, 0)
        self.assertEqual(rate_list.review_new, 1)
        self.assertEqual(rate_list.review_duplicates, 1)
        self.assertIn('counted once', rate_list.review_big_text)
        rate_list.action_confirm_rates()
        self.assertEqual(self.env['aw.glass.rate'].search_count([
            ('rate_list_id', '=', rate_list.id)]), 1)

    def test_two_prices_for_one_key_stay_a_problem(self):
        rate_list = self._list()
        self._line(rate_list, 100.0, '8mm')
        self._line(rate_list, 110.0, '8mm')
        rate_list.action_open_review()
        self.assertEqual(rate_list.review_problem, 2)
        self.assertEqual(rate_list.review_duplicates, 0)
        with self.assertRaises(UserError):
            rate_list.action_confirm_rates()

    def test_the_button_is_only_in_the_form_of_a_rates_manager(self):
        List = self.env['aw.vendor.rate.list']
        manager = List.with_user(self.manager).get_view(
            view_type='form')['arch']
        plain = List.with_user(self.plain).get_view(view_type='form')['arch']
        self.assertIn('action_clear_lines', manager)
        self.assertNotIn('action_clear_lines', plain)
        # hiding is cosmetic: the server still refuses a non-manager
        rate_list = self._list()
        with self.assertRaises(UserError):
            rate_list.with_user(self.plain).action_clear_lines()
