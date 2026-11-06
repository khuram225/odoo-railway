# -*- coding: utf-8 -*-
"""Download of the Excel rate template: what the wizard puts in the file."""
import base64
import io
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Template glass vendor'})
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
        # not in force yet: must not be offered
        env['aw.glass.rate'].create({
            'glass_type_id': cls.clear.id, 'thickness_mm': 8,
            'vendor_id': cls.vendor.id, 'price': 150.0,
            'date_from': date(2099, 1, 1)})

    def _list(self):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'glass',
            'date': date(2026, 11, 1)})
        rate_list.action_next_step()
        return rate_list

    def _book(self, action):
        import openpyxl
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertTrue(wizard.file_data)
        return wizard, openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(wizard.file_data)))

    def test_blank_glass_file_is_a_header_row(self):
        wizard, book = self._book(self._list().action_template_blank())
        sheet = book['Rates']
        self.assertEqual([c.value for c in sheet[1]],
                         ['Glass type', 'Thickness (mm)', 'Price per sqft'])
        self.assertEqual(sheet.max_row, 1)
        self.assertTrue(wizard.file_name.endswith('_glass_2026-11-01_blank.xlsx'))

    def test_current_glass_file_holds_rates_in_force_only(self):
        rate_list = self._list()
        wizard, book = self._book(rate_list.action_template_current())
        sheet = book['Rates']
        rows = [(sheet.cell(row=r, column=2).value,
                 sheet.cell(row=r, column=3).value)
                for r in range(2, 2 + 2)]
        self.assertEqual(sorted(rows), [(5, 90.0), (6, 100.0)])   # not the 2099 one
        info = {a.value: b.value for a, b in book['Info'].iter_rows(
            min_col=1, max_col=2) if a.value}
        self.assertEqual(info['List id'], str(rate_list.id))
        self.assertEqual(info['Vendor id'], str(self.vendor.id))
        self.assertEqual(info['Effective date'], '2026-11-01')
        self.assertEqual(info['Template version'], '1')

    def test_downloading_writes_no_rate(self):
        before = self.env['aw.glass.rate'].search_count([])
        rate_list = self._list()
        rate_list.action_template_current()
        self.assertEqual(self.env['aw.glass.rate'].search_count([]), before)
        self.assertFalse(rate_list.line_ids)

    def test_profile_current_needs_a_series_or_everything(self):
        layout_vendor = self.env['res.partner'].create({'name': 'Profile vendor'})
        self.env['aw.vendor.layout'].create({
            'vendor_id': layout_vendor.id,
            'column_ids': [(0, 0, {'sequence': 10, 'header': 'Code',
                                   'kind': 'code'})]})
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': layout_vendor.id, 'kind': 'profile',
            'date': date(2026, 11, 1)})
        rate_list.action_next_step()
        action = rate_list.action_template_current()   # asks first: no file yet
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertFalse(wizard.file_data)
        with self.assertRaises(UserError) as caught:
            wizard.action_make_file()
        self.assertIn('Which series?', str(caught.exception))

    def test_an_applied_list_gives_no_template(self):
        rate_list = self._list()
        rate_list.state = 'applied'
        with self.assertRaises(UserError):
            rate_list.action_template_blank()
