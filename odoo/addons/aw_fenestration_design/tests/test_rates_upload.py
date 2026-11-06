# -*- coding: utf-8 -*-
"""Upload of the filled-in Excel template: lines, never rates; bad cells load
nothing; a file from another list is refused."""
import base64
import io
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesUpload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Upload glass vendor'})
        Type = env['aw.glass.type']
        cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        if not cls.clear:
            Type._seed_glass_types()
            cls.clear = Type.search([('name', '=', 'Clear')], limit=1)
        for mm, price in ((5, 90.0), (6, 100.0)):
            env['aw.glass.rate'].create({
                'glass_type_id': cls.clear.id, 'thickness_mm': mm,
                'vendor_id': cls.vendor.id, 'price': price,
                'date_from': date(2025, 6, 1)})

    def _list(self):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'glass',
            'date': date(2026, 11, 1)})
        rate_list.action_next_step()
        return rate_list

    def _template(self, rate_list):
        action = rate_list.action_template_current()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        return base64.b64decode(wizard.file_data)

    def _edited(self, data, change):
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(data))
        change(book)
        out = io.BytesIO()
        book.save(out)
        return out.getvalue()

    def _upload(self, rate_list, data):
        wizard = self.env['aw.vendor.rate.upload.wizard'].create({
            'list_id': rate_list.id, 'file_name': 'filled.xlsx',
            'file_data': base64.b64encode(data)})
        return wizard.action_read()

    def _fill(self, book):
        sheet = book['Rates']
        rows = {sheet.cell(row=r, column=2).value: r for r in (2, 3)}
        sheet.cell(row=rows[5], column=3).value = 95.0          # changed
        sheet.cell(row=rows[6], column=3).value = None          # left alone
        for r in range(1, sheet.max_row + 1):
            if sheet.cell(row=r, column=1).value == 'New items':
                sheet.cell(row=r + 1, column=1).value = 'Clear'
                sheet.cell(row=r + 1, column=2).value = 8
                sheet.cell(row=r + 1, column=3).value = 150.0

    def test_a_filled_file_becomes_lines_and_no_rates(self):
        rate_list = self._list()
        before = self.env['aw.glass.rate'].search_count([])
        self._upload(rate_list, self._edited(
            self._template(rate_list), self._fill))
        lines = rate_list.line_ids
        # the blank 6mm price is not a line
        self.assertEqual(sorted((l.thickness_text, l.rate_1) for l in lines),
                         [('5mm', 95.0), ('8mm', 150.0)])
        self.assertEqual(self.env['aw.glass.rate'].search_count([]), before)
        self.assertIn('left unchanged', rate_list.upload_summary)
        self.assertTrue(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'aw.vendor.rate.list'),
            ('res_id', '=', rate_list.id), ('name', '=', 'filled.xlsx')]))
        # and it goes on to Review like any other lines
        rate_list.action_open_review()
        self.assertEqual(
            (rate_list.review_changed, rate_list.review_new), (1, 1))

    def test_a_bad_cell_loads_nothing_and_names_the_row(self):
        rate_list = self._list()

        def bad(book):
            book['Rates'].cell(row=2, column=3).value = '1,234.50'
        with self.assertRaises(UserError) as caught:
            self._upload(rate_list, self._edited(
                self._template(rate_list), bad))
        self.assertIn('Row 2', str(caught.exception))
        self.assertIn('thousands separator', str(caught.exception))
        self.assertFalse(rate_list.line_ids)

    def test_a_file_from_another_list_is_refused(self):
        first, second = self._list(), self._list()
        with self.assertRaises(UserError) as caught:
            self._upload(second, self._template(first))
        self.assertIn('another list', str(caught.exception))
        self.assertFalse(second.line_ids)

    def test_a_key_that_disagrees_with_its_code_is_refused(self):
        rate_list = self._list()

        def moved(book):
            book['Rates'].cell(row=2, column=1).value = 'Green'
        with self.assertRaises(UserError) as caught:
            self._upload(rate_list, self._edited(
                self._template(rate_list), moved))
        self.assertIn('hidden key', str(caught.exception))

    def test_something_that_is_not_excel_is_refused(self):
        rate_list = self._list()
        with self.assertRaises(UserError):
            self._upload(rate_list, b'not a spreadsheet')
