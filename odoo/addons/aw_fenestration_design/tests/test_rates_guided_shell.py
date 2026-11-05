# -*- coding: utf-8 -*-
"""The guided rate screen's shell: the Rates manager group, Choose with no
default date, the date check, and the paste box kept under Advanced."""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesGuidedShell(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Shell glass vendor'})
        cls.clear = env['aw.glass.type'].search([('name', '=', 'Clear')], limit=1)
        if not cls.clear:
            env['aw.glass.type']._seed_glass_types()
            cls.clear = env['aw.glass.type'].search([('name', '=', 'Clear')], limit=1)
        env['aw.glass.rate'].create({
            'glass_type_id': cls.clear.id, 'thickness_mm': 6,
            'vendor_id': cls.vendor.id, 'price': 100.0,
            'date_from': date(2026, 6, 1)})
        # a rate that has not started yet is not "in force"
        env['aw.glass.rate'].create({
            'glass_type_id': cls.clear.id, 'thickness_mm': 8,
            'vendor_id': cls.vendor.id, 'price': 150.0,
            'date_from': date(2099, 1, 1)})
        group_user = env.ref('base.group_user')
        cls.sales = env['res.users'].create({
            'name': 'Sales only', 'login': 'shell_sales',
            'group_ids': [(6, 0, [group_user.id])]})
        cls.rates = env['res.users'].create({
            'name': 'Rates user', 'login': 'shell_rates',
            'group_ids': [(6, 0, [
                group_user.id,
                env.ref('aw_fenestration_core.group_rates_manager').id])]})

    def _list(self, day, **extra):
        return self.env['aw.vendor.rate.list'].create(dict({
            'vendor_id': self.vendor.id, 'kind': 'glass', 'date': day}, **extra))

    # -- the group -------------------------------------------------------------------
    def test_the_fenestration_manager_includes_the_rates_manager(self):
        manager = self.env.ref('aw_fenestration_core.group_fenestration_manager')
        rates = self.env.ref('aw_fenestration_core.group_rates_manager')
        self.assertIn(rates, manager.all_implied_ids)

    def test_only_a_rates_manager_loads_rates_and_everyone_else_reads(self):
        for model in ('aw.vendor.rate.list', 'aw.vendor.rate.list.line',
                      'aw.profile.rate', 'aw.glass.rate', 'aw.vendor.layout'):
            sales = self.env[model].with_user(self.sales)
            rates = self.env[model].with_user(self.rates)
            self.assertTrue(sales.has_access('read'), model)
            for mode in ('write', 'create', 'unlink'):
                self.assertFalse(sales.has_access(mode), (model, mode))
                self.assertTrue(rates.has_access(mode), (model, mode))

    # -- Choose --------------------------------------------------------------------------
    def test_a_new_list_from_the_menu_has_no_date(self):
        action = self.env.ref('aw_fenestration_core.action_aw_vendor_rate_list')
        self.assertIn('default_date', action.context)
        defaults = self.env['aw.vendor.rate.list'].with_context(
            default_date=False).default_get(['date'])
        self.assertFalse(defaults.get('date'))

    def test_next_moves_from_choose_to_data_in(self):
        rate_list = self._list(date(2026, 7, 1))
        self.assertEqual(rate_list.step, 'choose')
        rate_list.action_next_step()
        self.assertEqual(rate_list.step, 'data')
        rate_list.action_back_to_choose()
        self.assertEqual(rate_list.step, 'choose')

    def test_a_profile_list_needs_the_vendors_layout_to_go_on(self):
        rate_list = self._list(date(2026, 7, 1), kind='profile')
        with self.assertRaises(UserError) as caught:
            rate_list.action_next_step()
        self.assertIn('no rate sheet layout', str(caught.exception))
        self.assertEqual(rate_list.step, 'choose')

    # -- the date: a warning at Choose, never a stop ---------------------------------------
    def test_a_date_before_the_rates_in_force_warns_but_goes_on(self):
        rate_list = self._list(date(2026, 5, 1))
        self.assertIn('Newest rate in force for this vendor: 1 Jun 2026',
                      rate_list.date_warning)
        self.assertIn('Your date is earlier', rate_list.date_warning)
        rate_list.action_next_step()                    # not stopped
        self.assertEqual(rate_list.step, 'data')

    def test_a_later_date_still_names_the_newest_rate(self):
        rate_list = self._list(date(2026, 9, 1))
        self.assertIn('1 Jun 2026', rate_list.date_warning)
        self.assertNotIn('Your date is earlier', rate_list.date_warning)
        rate_list.action_next_step()
        self.assertEqual(rate_list.step, 'data')

    def test_no_warning_when_the_vendor_has_no_rates(self):
        other = self.env['res.partner'].create({'name': 'Nobody yet'})
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': other.id, 'kind': 'glass', 'date': date(2026, 5, 1)})
        self.assertFalse(rate_list.date_warning)

    def test_a_rate_that_has_not_started_is_not_in_force(self):
        # the 2099 rate must not be named
        self.assertEqual(self._list(date(2026, 7, 1))._newest_rate_date(),
                         date(2026, 6, 1))

    def test_the_list_does_not_count_its_own_rates(self):
        rate_list = self._list(date(2026, 7, 1))
        self.env['aw.glass.rate'].create({
            'glass_type_id': self.clear.id, 'thickness_mm': 10,
            'vendor_id': self.vendor.id, 'price': 200.0,
            'date_from': date(2026, 7, 1), 'rate_list_id': rate_list.id})
        self.assertEqual(rate_list._newest_rate_date(), date(2026, 6, 1))

    def test_a_list_dated_before_newer_rates_passes_next_like_chawla_jan_over_oct(self):
        """The Chawla case in the abstract: rates dated 1 Oct exist, and a
        list dated 1 Jan still goes through Choose."""
        env = self.env
        template = env['aw.profile.section.line'].search(
            [('product_tmpl_id', '!=', False), ('thickness_id', '!=', False)],
            limit=1)
        finish = env.ref('aw_fenestration_core.aw_attribute_finish').value_ids[:1]
        if not (template and finish):
            self.skipTest("no profile with a thickness here")
        vendor = env['res.partner'].create({'name': 'Chawla-like vendor'})
        env['aw.vendor.layout'].create({
            'vendor_id': vendor.id,
            'column_ids': [
                (0, 0, {'sequence': 10, 'header': 'Code', 'kind': 'code'}),
                (0, 0, {'sequence': 20, 'header': 'Thickness', 'kind': 'thickness'}),
                (0, 0, {'sequence': 30, 'header': 'One', 'kind': 'finish',
                        'finish_id': finish.id})]})
        env['aw.profile.rate'].create({
            'product_tmpl_id': template.product_tmpl_id.id,
            'thickness_id': template.thickness_id.id, 'finish_id': finish.id,
            'price': 500.0, 'vendor_id': vendor.id,
            'date_from': date(2026, 10, 1)})
        january = env['aw.vendor.rate.list'].create({
            'vendor_id': vendor.id, 'kind': 'profile', 'date': date(2026, 1, 1)})
        self.assertIn('1 Oct 2026', january.date_warning)
        january.action_next_step()
        self.assertEqual(january.step, 'data')

    def test_applying_and_reapplying_are_never_date_blocked(self):
        rate_list = self._list(date(2026, 5, 1))            # before the 1 Jun rate
        self.env['aw.vendor.rate.list.line'].create({
            'list_id': rate_list.id, 'code': 'Clear', 'thickness_text': '5mm',
            'rate_1': 90.0})
        rate_list.action_apply()                            # the button path too
        self.assertEqual(rate_list.state, 'applied')
        rate_list.action_reapply()                          # not blocked
        self.assertEqual(rate_list.state, 'applied')
        rate_list.action_rematch()                          # nor re-match

    # -- Advanced ------------------------------------------------------------------------
    def test_the_paste_box_is_under_advanced_for_a_rates_manager_only(self):
        View = self.env['aw.vendor.rate.list']
        manager_arch = View.with_user(self.rates).get_view(view_type='form')['arch']
        self.assertIn('Advanced', manager_arch)
        self.assertIn('paste_text', manager_arch)
        sales_arch = View.with_user(self.sales).get_view(view_type='form')['arch']
        self.assertNotIn('paste_text', sales_arch)
        self.assertNotIn('Advanced', sales_arch)

    # -- lists from before the steps -----------------------------------------------------
    def test_old_lists_are_put_at_the_right_step_once(self):
        draft = self._list(date(2026, 7, 1))
        applied = self._list(date(2026, 8, 1))
        applied.state = 'applied'
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.rate_list_steps_migrated', '')
        self.env['aw.vendor.rate.list']._migrate_steps()
        self.assertEqual(draft.step, 'choose')                  # no rows yet
        self.assertEqual(applied.step, 'confirm')
        self.assertEqual(self.env['aw.vendor.rate.list']._migrate_steps(), 0)
