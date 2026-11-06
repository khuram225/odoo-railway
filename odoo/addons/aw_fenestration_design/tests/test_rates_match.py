# -*- coding: utf-8 -*-
"""Match a Review row to a product on the spot, and remember the code."""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatesMatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.vendor = env['res.partner'].create({'name': 'Match vendor'})
        finish = env.ref('aw_fenestration_core.aw_attribute_finish').value_ids[:1]
        env['aw.vendor.layout'].create({
            'vendor_id': cls.vendor.id,
            'column_ids': [
                (0, 0, {'sequence': 10, 'header': 'Code', 'kind': 'code'}),
                (0, 0, {'sequence': 20, 'header': 'Thickness',
                        'kind': 'thickness'}),
                (0, 0, {'sequence': 30, 'header': 'Series', 'kind': 'series'}),
                (0, 0, {'sequence': 40, 'header': 'One', 'kind': 'finish',
                        'finish_id': finish.id})]})
        categ = env.ref('aw_fenestration_core.product_category_profiles')
        cls.profile = env['product.template'].search(
            [('categ_id', 'child_of', categ.id)], limit=1)
        cls.rates_user = env['res.users'].create({
            'name': 'Rates matcher', 'login': 'match_rates',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_rates_manager').id])]})
        cls.plain_user = env['res.users'].create({
            'name': 'Plain', 'login': 'match_plain',
            'group_ids': [(6, 0, [env.ref('base.group_user').id])]})

    def _review(self, series='DG.SERIES'):
        if not self.profile:
            self.skipTest("no profile product in this database")
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'profile',
            'date': date(2026, 11, 1)})
        rate_list.action_next_step()
        self.env['aw.vendor.rate.list.line'].create({
            'list_id': rate_list.id, 'code': 'ZZ-VENDOR-ONLY',
            'thickness_text': 'Std', 'series': series, 'rate_1': 100.0})
        rate_list.action_open_review()
        row = rate_list.review_ids.filtered(lambda r: r.can_match)
        self.assertEqual(len(row), 1)
        return rate_list, row

    def _wizard(self, row, **values):
        return self.env['aw.vendor.rate.match.wizard'].with_user(
            self.rates_user).create(dict(
                review_id=row.id, product_tmpl_id=self.profile.id, **values))

    def test_only_a_row_without_a_product_can_be_matched(self):
        rate_list, row = self._review()
        self.assertTrue(row.can_match)
        self.assertEqual(row.status, 'notwritten')

    def test_matching_sets_the_product_and_rebuilds_the_review(self):
        rate_list, row = self._review()
        before = rate_list.review_ids.ids
        self._wizard(row).action_match()
        line = rate_list.line_ids
        self.assertEqual(line.product_tmpl_id, self.profile)
        self.assertEqual(line.match_source, 'manual')
        self.assertEqual(rate_list.step, 'review')          # not sent back
        self.assertNotEqual(rate_list.review_ids.ids, before)   # rebuilt
        self.assertFalse(rate_list.review_ids.filtered('can_match'))

    def test_remember_is_off_by_default_and_saves_nothing(self):
        rate_list, row = self._review()
        wizard = self._wizard(row)
        self.assertFalse(wizard.remember)
        wizard.action_match()
        self.assertFalse(self.env['aw.vendor.alias'].search([
            ('vendor_id', '=', self.vendor.id)]))
        self.assertIn('not remembered', ' '.join(
            rate_list.message_ids.mapped('body')))

    def test_remember_saves_an_alias_logged_with_user_and_date(self):
        rate_list, row = self._review()
        self._wizard(row, remember=True).action_match()
        alias = self.env['aw.vendor.alias'].search([
            ('vendor_id', '=', self.vendor.id)])
        self.assertEqual(len(alias), 1)
        self.assertEqual(alias.product_tmpl_id, self.profile)
        self.assertEqual(alias.code, 'ZZ-VENDOR-ONLY')
        self.assertEqual(alias.rate_list_id, rate_list)
        self.assertEqual(alias.added_by, self.rates_user)
        body = ' '.join(rate_list.message_ids.mapped('body'))
        self.assertIn('Rates matcher', body)
        self.assertIn(date.today().isoformat()[:4], body)
        self.assertIn('Remembered for this vendor', body)
        self.assertIn('ZZ-VENDOR-ONLY', rate_list.remembered_summary)
        # and the next list matches the same code by itself
        other = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'kind': 'profile',
            'date': date(2026, 12, 1)})
        line = self.env['aw.vendor.rate.list.line'].create({
            'list_id': other.id, 'code': 'zz vendor only',
            'thickness_text': 'Std', 'rate_1': 50.0})
        self.assertEqual(line.product_tmpl_id, self.profile)
        self.assertEqual(line.match_source, 'alias')

    def test_a_different_series_warns_but_does_not_stop(self):
        rate_list, row = self._review(series='WRONG.SERIES')
        finish = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish').value_ids[:1]
        thick = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness').value_ids[:1]
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': self.profile.id, 'thickness_id': thick.id,
            'finish_id': finish.id, 'price': 10.0, 'vendor_id': self.vendor.id,
            'vendor_series': 'DG.SERIES', 'date_from': date(2025, 1, 1)})
        wizard = self._wizard(row)
        self.assertIn('DG.SERIES', wizard.series_warning)
        self.assertIn('WRONG.SERIES', wizard.series_warning)
        wizard.action_match()                                # still goes through
        self.assertEqual(rate_list.line_ids.product_tmpl_id, self.profile)

    def test_the_same_series_does_not_warn(self):
        rate_list, row = self._review(series='DG.SERIES')
        finish = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish').value_ids[:1]
        thick = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness').value_ids[:1]
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': self.profile.id, 'thickness_id': thick.id,
            'finish_id': finish.id, 'price': 10.0, 'vendor_id': self.vendor.id,
            'vendor_series': 'dg.series', 'date_from': date(2025, 1, 1)})
        self.assertFalse(self._wizard(row).series_warning)

    def test_only_a_rates_manager_can_match(self):
        rate_list, row = self._review()
        wizard = self.env['aw.vendor.rate.match.wizard'].create({
            'review_id': row.id, 'product_tmpl_id': self.profile.id})
        with self.assertRaises(UserError):
            wizard.with_user(self.plain_user).action_match()
        with self.assertRaises(UserError):
            row.with_user(self.plain_user).action_match_product()

    def test_the_layout_lists_remembered_codes(self):
        rate_list, row = self._review()
        self._wizard(row, remember=True).action_match()
        layout = self.env['aw.vendor.layout'].search([
            ('vendor_id', '=', self.vendor.id)])
        self.assertEqual(layout.alias_count, 1)
        action = layout.action_open_aliases()
        self.assertEqual(
            self.env['aw.vendor.alias'].search(action['domain']).code,
            'ZZ-VENDOR-ONLY')
