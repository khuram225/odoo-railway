# -*- coding: utf-8 -*-
"""A pasted rate sheet goes through the safe reader (rate_paste.validate_paste)
and the original text stays attached to the list."""
import unittest

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSafeRateParse(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        finishes = env.ref('aw_fenestration_core.aw_attribute_finish').value_ids[:2]
        if len(finishes) < 2:
            raise unittest.SkipTest("Fewer than two finishes here")
        cls.vendor = env['res.partner'].create({'name': 'Safe parse vendor'})
        cls.layout = env['aw.vendor.layout'].create({
            'vendor_id': cls.vendor.id,
            'column_ids': [
                (0, 0, {'sequence': 10, 'header': 'Code', 'kind': 'code'}),
                (0, 0, {'sequence': 20, 'header': 'Thickness', 'kind': 'thickness'}),
                (0, 0, {'sequence': 30, 'header': 'One', 'kind': 'finish',
                        'finish_id': finishes[0].id}),
                (0, 0, {'sequence': 40, 'header': 'Two', 'kind': 'finish',
                        'finish_id': finishes[1].id}),
            ]})

    def _list(self, text):
        return self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'profile', 'paste_text': text})

    def _attachments(self, rate_list):
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'aw.vendor.rate.list'), ('res_id', '=', rate_list.id)])

    def test_a_good_paste_is_read_and_the_original_is_kept(self):
        text = 'Code\tThickness\tOne\tTwo\nD-38\t1.6MM\t100\t110\n'
        rate_list = self._list(text)
        rate_list.action_parse_paste()
        self.assertEqual(len(rate_list.line_ids), 1)
        self.assertEqual(rate_list.line_ids.rate_1, 100.0)
        self.assertFalse(rate_list.paste_text)
        kept = self._attachments(rate_list)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept.raw.decode('utf-8'), text)

    def test_a_missing_code_column_stops_everything(self):
        text = 'Thickness\tOne\tTwo\n1.6MM\t100\t110\n'
        rate_list = self._list(text)
        with self.assertRaises(UserError) as caught:
            rate_list.action_parse_paste()
        self.assertIn('no code column', str(caught.exception))
        self.assertFalse(rate_list.line_ids)
        self.assertFalse(self._attachments(rate_list))
        self.assertEqual(rate_list.paste_text, text)       # nothing lost

    def test_a_dropped_cell_names_the_row_and_writes_nothing(self):
        text = 'D-38\t1.6MM\t100\t110\nD-39\t1.6MM\t100\n'
        rate_list = self._list(text)
        with self.assertRaises(UserError) as caught:
            rate_list.action_parse_paste()
        self.assertIn('Row 2', str(caught.exception))
        self.assertFalse(rate_list.line_ids)

    def test_an_empty_price_is_never_written_as_a_price(self):
        rate_list = self._list('Code\tThickness\tOne\tTwo\nD-38\t1.6MM\t100\t\n')
        rate_list.action_parse_paste()
        line = rate_list.line_ids
        self.assertEqual((line.rate_1, line.rate_2), (100.0, 0.0))
        note = ' '.join(rate_list.message_ids.mapped('body'))
        self.assertIn('no price', note)
        self.assertIn('1 price cell', note)

    def test_a_refusal_names_the_vendor_and_layout_and_keeps_the_text(self):
        text = 'a\tb\tc\nD-1\t2MM\t5\n'                      # nobody's sheet
        rate_list = self._list(text)
        with self.assertRaises(UserError) as caught:
            rate_list.action_parse_paste()
        message = str(caught.exception)
        self.assertIn('Safe parse vendor', message)         # the vendor
        self.assertIn('4 columns', message)                 # the layout
        self.assertIn('All rows have 3 cells', message)
        self.assertIn('still in the box', message)
        self.assertEqual(rate_list.paste_text, text)

    def test_only_five_rows_are_listed_then_and_n_more(self):
        rows = ''.join('D-%d\t1.6MM\t100\n' % n for n in range(1, 9))
        rows += 'D-99\t1.6MM\t100\t110\n'
        rate_list = self._list(rows)
        with self.assertRaises(UserError) as caught:
            rate_list.action_parse_paste()
        message = str(caught.exception)
        self.assertIn('Row 5', message)
        self.assertNotIn('Row 6 ', message)
        self.assertIn('and 3 more', message)
