# -*- coding: utf-8 -*-
"""A quote plans with its profile vendor's bar lengths; no rows, the global list."""
from odoo.exceptions import UserError, ValidationError
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


@tagged('post_install', '-at_install')
class TestVendorBarLengthActive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Active vendor'})
        cls.Length = env['aw.vendor.bar.length']
        cls.rows = {ft: cls.Length.create(
            {'vendor_id': cls.vendor.id, 'length_ft': ft})
            for ft in (14, 16, 18)}
        customer = env['res.partner'].create({'name': 'Active customer'})
        cls.order = env['sale.order'].create({
            'partner_id': customer.id,
            'aw_profile_vendor_id': cls.vendor.id})
        cls.plan = env['aw.cut.plan'].create({'sale_order_id': cls.order.id})

    def _lengths(self):
        return self.plan._settings(self.vendor, strict=True)['stock_ft']

    def test_switch_off_18_then_all_off_then_back_on(self):
        self.assertEqual(self._lengths(), [14.0, 16.0, 18.0])
        self.rows[18].active = False
        self.assertEqual(self._lengths(), [14.0, 16.0])
        self.rows[14].active = False
        self.rows[16].active = False
        with self.assertRaises(UserError) as caught:
            self.plan._generate()
        self.assertIn('Active vendor has no active bar length',
                      str(caught.exception))
        for ft in (14, 16, 18):
            self.rows[ft].active = True
        self.assertEqual(self._lengths(), [14.0, 16.0, 18.0])
        self.plan._generate()

    def test_all_off_does_not_fall_back_but_no_rows_does(self):
        self.Length.search([('vendor_id', '=', self.vendor.id)]).write(
            {'active': False})
        with self.assertRaises(UserError):
            self.plan._settings(self.vendor, strict=True)
        # the fingerprint and the piece limit never stop
        self.plan._live_fingerprint()
        self.env['aw.design']._max_piece_mm(self.vendor)
        self.Length.with_context(active_test=False).search(
            [('vendor_id', '=', self.vendor.id)]).unlink()
        self.assertEqual(self._lengths(),
                         self.plan._settings()['stock_ft'])

    def test_a_change_marks_the_plan_stale(self):
        self.plan._generate()
        self.assertTrue(self.plan.is_current)
        self.rows[18].active = False
        self.plan.invalidate_recordset()
        self.assertFalse(self.plan.is_current)
        self.rows[18].active = True
        self.plan.invalidate_recordset()
        self.assertTrue(self.plan.is_current)

    def test_inactive_hidden_by_default_and_a_twin_is_still_refused(self):
        self.rows[18].active = False
        self.assertNotIn(self.rows[18], self.Length.search(
            [('vendor_id', '=', self.vendor.id)]))
        with self.assertRaises(ValidationError):
            self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 18})

    def test_changes_are_logged_with_user_and_date(self):
        self.rows[18].active = False
        body = ' '.join(self.vendor.message_ids.mapped('body'))
        self.assertIn('18 ft switched off by', body)
        self.assertIn(self.env.user.name, body)
