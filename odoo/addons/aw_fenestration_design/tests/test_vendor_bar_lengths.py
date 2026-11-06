# -*- coding: utf-8 -*-
"""A quote plans with its profile vendor's bar lengths; no rows, the global list."""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVendorBarLengths(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Bar vendor'})
        cls.Plan = cls.env['aw.cut.plan']
        cls.Length = cls.env['aw.vendor.bar.length']

    def test_no_rows_means_the_global_list(self):
        self.assertEqual(self.Plan._settings(self.vendor)['stock_ft'],
                         self.Plan._settings()['stock_ft'])

    def test_vendor_rows_replace_the_global_list(self):
        for ft in (20, 12):
            self.Length.create({'vendor_id': self.vendor.id, 'length_ft': ft})
        self.assertEqual(self.Plan._settings(self.vendor)['stock_ft'],
                         [12.0, 20.0])
        self.assertNotEqual(self.Plan._settings()['stock_ft'], [12.0, 20.0])

    def test_longest_piece_follows_the_vendor(self):
        Design = self.env['aw.design']
        base = Design._max_piece_mm()
        self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 30})
        self.assertGreater(Design._max_piece_mm(self.vendor), base)
        self.assertEqual(Design._max_piece_mm(), base)

    def test_rows_must_be_positive_and_unique(self):
        self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 16})
        with self.assertRaises(ValidationError):
            self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 16})
        with self.assertRaises(ValidationError):
            self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 0})

    def test_seed_is_once_and_only_for_vendors_with_profile_rates(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.vendor_bar_lengths_seeded', '')
        glass_only = self.env['res.partner'].create({'name': 'Glass only'})
        self.Length.search([]).unlink()
        self.Length._seed_vendor_bar_lengths()
        seeded = self.Length.search([]).mapped('vendor_id')
        rated = self.env['aw.profile.rate'].search(
            [('vendor_id', '!=', False)]).mapped('vendor_id')
        self.assertEqual(set(seeded.ids), set(rated.ids))
        self.assertNotIn(glass_only, seeded)
        for vendor in seeded:
            self.assertEqual(self.Plan._settings(vendor)['stock_ft'],
                             self.Plan._settings()['stock_ft'])
        self.Length.search([]).unlink()
        self.assertFalse(self.Length._seed_vendor_bar_lengths())
        self.assertFalse(self.Length.search([]))
