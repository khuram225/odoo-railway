# -*- coding: utf-8 -*-
"""Glass rates: types, dated rates, and the glass rate list.

The Ghani Glass Ltd list of 1 July 2026 is the fixture. A glass list has
one rate column and no finish, and follows the same rules as a profile
list: paste, Re-match, Apply, Re-apply, Set to draft, and the same-date
rewrite.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

GHANI = '\n'.join([
    'Clear\t2mm\t127.39', 'Clear\t6mm\t265.52', 'Clear\t10mm\t611.92',
    'Clear\t12mm\t745.04',
    'WC (Grn, Brw, Blue)\t5mm\t231.88',
    'Green/Brown\t8mm\t948.13', 'Blue\t8mm\t971.78',
    'Ref. Green/Brown/Blue/Ford Blue\t4mm\t336.95',
    'CC (Grey)\t5mm/6mm\t389.29',
    'Ref. Clear\t6mm\t384.57',
])
# 4 + 3 + 2 + 1 + 4 + 2 + 1 = 17 rates from 10 rows


@tagged('post_install', '-at_install')
class TestGlassRates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['aw.glass.type']._seed_glass_types()
        cls.ghani = env['res.partner'].search(
            [('name', '=', 'Ghani Glass Ltd')], limit=1)
        cls.other = env['res.partner'].create({'name': 'Other glass vendor'})
        cls.Type = env['aw.glass.type']

    def _list(self, day, text, vendor=None):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'kind': 'glass', 'vendor_id': (vendor or self.ghani).id,
            'date': day})
        rate_list.paste_text = text
        rate_list.action_parse_paste()
        return rate_list

    def _rate(self, type_name, mm, day, vendor=None):
        glass = self.Type.search([('name', '=', type_name)])
        return self.env['aw.glass.rate']._rate_for(
            glass, mm, day, vendor or self.ghani)

    def test_the_types_and_the_supplier_are_seeded_once(self):
        self.assertTrue(self.ghani)
        names = set(self.Type.mapped('name'))
        for name in ('Clear', 'WC Green', 'CC Grey', 'Ref. Ford Blue'):
            self.assertIn(name, names)
        self.assertTrue(self.Type.search([('name', '=', 'Ref. Grey')]).reflective)
        self.assertFalse(self.Type.search([('name', '=', 'Grey')]).reflective)
        before = self.Type.search_count([])
        self.assertEqual(self.Type._seed_glass_types(), 0)
        self.assertEqual(self.Type.search_count([]), before)

    def test_a_paste_splits_into_one_row_per_type_and_thickness(self):
        rate_list = self._list(date(2026, 7, 1), GHANI)
        self.assertEqual(len(rate_list.line_ids), 17)
        self.assertEqual(rate_list.kind, 'glass')
        by = {(l.code, l.thickness_text): l.rate_1 for l in rate_list.line_ids}
        self.assertEqual(by[('WC Brown', '5mm')], 231.88)
        self.assertEqual(by[('Green', '8mm')], 948.13)
        self.assertEqual(by[('Brown', '8mm')], 948.13)
        self.assertEqual(by[('Ref. Ford Blue', '4mm')], 336.95)
        self.assertEqual(by[('CC Grey', '5mm')], by[('CC Grey', '6mm')])
        self.assertFalse(rate_list.need_summary)
        self.assertTrue(all(l.glass_type_id for l in rate_list.line_ids))

    def test_apply_writes_dated_rates_for_the_vendor(self):
        rate_list = self._list(date(2026, 7, 1), GHANI)
        rate_list.action_apply()
        self.assertEqual(rate_list.state, 'applied')
        rates = self.env['aw.glass.rate'].search(
            [('rate_list_id', '=', rate_list.id)])
        self.assertEqual(len(rates), 17)
        self.assertEqual(set(rates.mapped('vendor_id')), self.ghani)
        self.assertEqual(self._rate('Clear', 10, date(2026, 7, 1)).price, 611.92)
        self.assertEqual(self._rate('Clear', 6, date(2026, 12, 1)).price, 265.52)
        # before the list starts there is no rate; another vendor has none
        self.assertFalse(self._rate('Clear', 6, date(2026, 6, 30)))
        self.assertFalse(self._rate('Clear', 6, date(2026, 8, 1), self.other))
        # a thickness nobody priced is no rate
        self.assertFalse(self._rate('Clear', 7, date(2026, 8, 1)))

    def test_a_newer_list_closes_the_old_rate_the_day_before(self):
        self._list(date(2026, 7, 1), 'Clear\t6mm\t265.52').action_apply()
        self._list(date(2026, 10, 1), 'Clear\t6mm\t280').action_apply()
        old = self.env['aw.glass.rate'].search([
            ('glass_type_id.name', '=', 'Clear'), ('thickness_mm', '=', 6),
            ('date_from', '=', date(2026, 7, 1))])
        self.assertEqual(old.date_to, date(2026, 9, 30))
        self.assertEqual(self._rate('Clear', 6, date(2026, 9, 1)).price, 265.52)
        self.assertEqual(self._rate('Clear', 6, date(2026, 10, 2)).price, 280)

    def test_the_same_date_rewrites_instead_of_adding(self):
        first = self._list(date(2026, 7, 1), 'Clear\t6mm\t265.52')
        first.action_apply()
        second = self._list(date(2026, 7, 1), 'Clear\t6mm\t270')
        second.action_apply()
        rates = self.env['aw.glass.rate'].search([
            ('glass_type_id.name', '=', 'Clear'), ('thickness_mm', '=', 6),
            ('vendor_id', '=', self.ghani.id)])
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates.price, 270)

    def test_unknown_type_and_thickness_are_named_and_not_applied(self):
        rate_list = self._list(
            date(2026, 7, 1),
            'Clear\t6mm\t265.52\nMystery\t6mm\t100')
        by = {l.code: l for l in rate_list.line_ids}
        self.assertEqual(
            by['Mystery'].need_text,
            'No glass type Mystery: add it under Glass Types, then Re-match')
        self.assertEqual(rate_list.need_summary,
                         '1 need a glass type, 0 unknown thickness')
        rate_list.action_apply()
        self.assertEqual(self.env['aw.glass.rate'].search_count(
            [('rate_list_id', '=', rate_list.id)]), 1)
        self.assertEqual(by['Mystery'].status_code, 'unmatched')
        # add the type, Re-match, Re-apply: the row now writes
        self.Type.create({'name': 'Mystery'})
        rate_list.action_rematch()
        self.assertFalse(by['Mystery'].need)
        rate_list.action_reapply()
        self.assertEqual(self.env['aw.glass.rate'].search_count(
            [('rate_list_id', '=', rate_list.id)]), 2)

    def test_set_to_draft_removes_the_rates_and_keeps_the_lines(self):
        rate_list = self._list(date(2026, 7, 1), GHANI)
        rate_list.action_apply()
        rate_list.action_set_to_draft()
        self.assertEqual(rate_list.state, 'draft')
        self.assertEqual(len(rate_list.line_ids), 17)
        self.assertFalse(self.env['aw.glass.rate'].search_count(
            [('rate_list_id', '=', rate_list.id)]))
        with self.assertRaises(UserError):
            rate_list.action_set_to_draft()

    def test_a_glass_list_leaves_profile_lists_alone(self):
        profile = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.other.id, 'date': date(2026, 7, 1)})
        self.assertEqual(profile.kind, 'profile')
        self.assertEqual(profile._rate_model(), 'aw.profile.rate')
        self.assertEqual(self._list(date(2026, 7, 1), 'Clear\t6mm\t1')
                         ._rate_model(), 'aw.glass.rate')
