# -*- coding: utf-8 -*-
"""A quote plans with its profile vendor's bar lengths; no rows, the global list."""
import unittest

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
        self.assertIn('18 ft (All profiles) switched off by', body)
        self.assertIn(self.env.user.name, body)


@tagged('post_install', '-at_install')
class TestVendorBarLengthProfile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Profile vendor'})
        cls.Length = env['aw.vendor.bar.length']
        cls.Plan = env['aw.cut.plan']
        cls.tmpl_a = env['product.template'].create({'name': 'RE-A profile'})
        cls.tmpl_b = env['product.template'].create({'name': 'RE-B profile'})
        for ft in (14, 16, 18):
            cls.Length.create({'vendor_id': cls.vendor.id, 'length_ft': ft})
        cls.own = {ft: cls.Length.create({
            'vendor_id': cls.vendor.id, 'product_tmpl_id': cls.tmpl_a.id,
            'length_ft': ft}) for ft in (12, 20)}

    def _ft(self, template, strict=True):
        return self.Plan._settings(
            self.vendor, strict=strict, template=template)['stock_ft']

    def test_profile_exception_overrides_the_vendor_list(self):
        self.assertEqual(self._ft(self.tmpl_a), [12.0, 20.0])

    def test_blank_row_applies_to_all_other_profiles(self):
        self.assertEqual(self._ft(self.tmpl_b), [14.0, 16.0, 18.0])
        self.assertEqual(self._ft(None), [14.0, 16.0, 18.0])

    def test_profile_with_all_rows_off_stops_only_itself(self):
        for row in self.own.values():
            row.active = False
        with self.assertRaises(UserError) as caught:
            self._ft(self.tmpl_a)
        self.assertIn('Profile vendor has no active bar length for RE-A',
                      str(caught.exception))
        self.assertEqual(self._ft(self.tmpl_b), [14.0, 16.0, 18.0])
        # non-strict (fingerprint, longest piece) falls back to the vendor
        self.assertEqual(self._ft(self.tmpl_a, strict=False),
                         [14.0, 16.0, 18.0])

    def test_vendor_with_only_other_profiles_rows_uses_global(self):
        other = self.env['res.partner'].create({'name': 'Exceptions only'})
        self.Length.create({'vendor_id': other.id,
                            'product_tmpl_id': self.tmpl_a.id,
                            'length_ft': 12})
        self.assertEqual(
            self.Plan._settings(other, template=self.tmpl_b)['stock_ft'],
            self.Plan._settings()['stock_ft'])

    def test_duplicate_check_includes_the_profile(self):
        # 12 ft for another profile, and 14 ft vendor-wide, are fine ...
        self.Length.create({'vendor_id': self.vendor.id,
                            'product_tmpl_id': self.tmpl_b.id,
                            'length_ft': 12})
        self.Length.create({'vendor_id': self.vendor.id,
                            'product_tmpl_id': self.tmpl_a.id,
                            'length_ft': 14})
        # ... the same profile and length twice is not
        with self.assertRaises(ValidationError):
            self.Length.create({'vendor_id': self.vendor.id,
                                'product_tmpl_id': self.tmpl_a.id,
                                'length_ft': 12})

    def test_longest_piece_follows_the_profile(self):
        Design = self.env['aw.design']
        self.assertGreater(Design._max_piece_mm(self.vendor, self.tmpl_a),
                           Design._max_piece_mm(self.vendor, self.tmpl_b))
        self.assertEqual(
            Design._max_piece_mm(self.vendor, any_profile=True),
            Design._max_piece_mm(self.vendor, self.tmpl_a))

    def test_label_and_log_name_the_profile(self):
        wide = self.Length.search([('vendor_id', '=', self.vendor.id),
                                   ('product_tmpl_id', '=', False)])[:1]
        self.assertEqual(wide.profile_label, 'All profiles')
        self.assertEqual(self.own[12].profile_label, 'RE-A profile')
        self.own[12].active = False
        body = ' '.join(self.vendor.message_ids.mapped('body'))
        self.assertIn('12 ft (RE-A profile) switched off by', body)


@tagged('post_install', '-at_install')
class TestVendorBarLengthUi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Ui vendor'})
        cls.Length = cls.env['aw.vendor.bar.length']
        cls.row = cls.Length.create(
            {'vendor_id': cls.vendor.id, 'length_ft': 18})
        cls.row.active = False

    def test_message_says_the_row_is_switched_off_and_where(self):
        with self.assertRaises(ValidationError) as caught:
            self.Length.create({'vendor_id': self.vendor.id, 'length_ft': 18})
        text = str(caught.exception)
        self.assertIn('switched off', text)
        self.assertIn('toggle in the Bar Lengths list', text)

    def test_add_can_switch_the_existing_one_on(self):
        made = self.Length.create({'vendor_id': self.vendor.id,
                                   'length_ft': 18,
                                   'switch_on_existing': True})
        self.assertEqual(made, self.row)
        self.assertTrue(self.row.active)
        self.assertEqual(self.Length.with_context(active_test=False)
                         .search_count([('vendor_id', '=', self.vendor.id)]), 1)

    def test_form_note_appears_only_for_a_switched_off_twin(self):
        draft = self.Length.new({'vendor_id': self.vendor.id, 'length_ft': 18})
        self.assertIn('switched off', draft.inactive_twin_note)
        other = self.Length.new({'vendor_id': self.vendor.id, 'length_ft': 20})
        self.assertFalse(other.inactive_twin_note)

    def test_action_shows_inactive_rows(self):
        action = self.env.ref(
            'aw_fenestration_design.action_aw_vendor_bar_length')
        self.assertIn("'active_test': False", action.context)


@tagged('post_install', '-at_install')
class TestRegenerateUsesTheQuotesVendor(TransactionCase):
    """Cutting plan > Regenerate (aw.cut.plan.action_generate) with the 18 ft
    row of the QUOTE'S profile vendor switched off. The vendor that counts
    is the quote's, not any other vendor's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family = env['aw.window.family'].search([]).filtered(
            lambda f: f.series_ids.filtered('active').filtered(
                lambda s: s.leaf_type_ids))[:1]
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        series = family.series_ids.filtered('active').filtered(
            lambda s: s.leaf_type_ids)[0]
        cls.premium = env['res.partner'].create({'name': 'Premium (regen)'})
        cls.chawla = env['res.partner'].create({'name': 'Chawla (regen)'})
        Length = env['aw.vendor.bar.length']
        cls.rows = {}
        for vendor in (cls.premium, cls.chawla):
            for ft in (14, 16, 18):
                cls.rows[(vendor.id, ft)] = Length.create(
                    {'vendor_id': vendor.id, 'length_ft': ft})
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Regen customer'}).id,
            'aw_default_series_id': series.id,
            'aw_profile_vendor_id': cls.premium.id})
        design = cls.order._create_fenestration_position(series, family=family)
        design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [dict(leaf), dict(leaf)]}]})
        design._explode()
        cls.plan = env['aw.cut.plan'].create({
            'sale_order_id': cls.order.id,
            'design_ids': [(6, 0, cls.order.aw_design_ids.ids)]})
        if not cls.plan._profile_lines():
            raise unittest.SkipTest("The test window has no profile lines")

    def _bar_lengths(self):
        return {round(bar.stock_mm / 304.8) for bar
                in self.plan.group_ids.mapped('bar_ids')}

    def test_switching_off_18_removes_18_from_a_regenerated_plan(self):
        self.plan.action_generate()
        self.assertEqual(self.plan.profile_vendor_id, self.premium)
        self.assertEqual(self.plan.stock_lengths_ft, '14,16,18')
        self.rows[(self.premium.id, 18)].active = False
        self.plan.action_generate()
        self.assertEqual(self.plan.stock_lengths_ft, '14,16')
        self.assertNotIn(18, self._bar_lengths())

    def test_another_vendors_switch_changes_nothing(self):
        self.rows[(self.chawla.id, 18)].active = False
        self.plan.action_generate()
        self.assertEqual(self.plan.stock_lengths_ft, '14,16,18')
