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

    # -- the date check ------------------------------------------------------------------
    def test_a_date_before_the_rates_in_force_stops_with_a_plain_message(self):
        rate_list = self._list(date(2026, 5, 1))
        with self.assertRaises(UserError) as caught:
            rate_list.action_next_step()
        message = str(caught.exception)
        self.assertIn('earlier than the rates already in force', message)
        self.assertIn('Shell glass vendor', message)
        self.assertIn('2026-06-01', message)
        self.assertEqual(rate_list.step, 'choose')

    def test_the_same_day_and_later_days_go_on(self):
        for day in (date(2026, 6, 1), date(2026, 9, 1)):
            rate_list = self._list(day)
            rate_list.action_next_step()
            self.assertEqual(rate_list.step, 'data')

    def test_a_rate_that_has_not_started_is_not_in_force(self):
        # the 2099 rate must not block a list dated this year
        self.assertEqual(self._list(date(2026, 7, 1))._newest_rate_date(),
                         date(2026, 6, 1))

    def test_the_list_does_not_block_itself(self):
        rate_list = self._list(date(2026, 7, 1))
        rate_list.action_next_step()
        self.env['aw.glass.rate'].create({
            'glass_type_id': self.clear.id, 'thickness_mm': 10,
            'vendor_id': self.vendor.id, 'price': 200.0,
            'date_from': date(2026, 7, 1), 'rate_list_id': rate_list.id})
        self.assertEqual(rate_list._newest_rate_date(), date(2026, 6, 1))
        rate_list._check_effective_date()                       # no error

    def test_apply_from_the_button_checks_the_date_too(self):
        rate_list = self._list(date(2026, 5, 1))
        with self.assertRaises(UserError):
            rate_list.action_apply_checked()
        self.assertEqual(rate_list.state, 'draft')

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
