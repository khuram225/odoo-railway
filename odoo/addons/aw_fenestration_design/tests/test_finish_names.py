# -*- coding: utf-8 -*-
"""A finish has several names; one finish value, no groups."""
import unittest
from datetime import date

from odoo.addons.aw_fenestration_core.models.finish_names import (
    norm_name, order_names)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFinishNames(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        cls.thick = env.ref('aw_fenestration_core.aw_attribute_thickness')
        cls.standard = env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_standard')
        cls.natural = env.ref(
            'aw_fenestration_core.aw_attr_val_finish_natural',
            raise_if_not_found=False) or cls.attr.value_ids[0]
        cls.other_finish = cls.attr.value_ids.filtered(
            lambda v: v != cls.natural)[:1]
        cls.vendor = env['res.partner'].create({'name': 'Names vendor'})
        cls.chawla = env['res.partner'].create({'name': 'Names Chawla'})

    # -- pure helpers ----------------------------------------------------
    def test_spellings_compare_equal(self):
        self.assertEqual(norm_name('h23_pc_ral'), norm_name('H23 PC RAL'))
        self.assertEqual(norm_name('natural'), norm_name('Natural'))
        self.assertNotEqual(norm_name('H.23'), norm_name('RAL P.C'))

    def test_order_is_the_vendors_own_first_once_each(self):
        names = [('Natural', 5, 0, 1), ('DULL', 7, 10, 2),
                 ('natural', 7, 20, 3)]
        self.assertEqual(order_names(names, 7), ['DULL', 'natural'])
        self.assertEqual(order_names(names, 5), ['Natural', 'DULL'])
        self.assertEqual(order_names(names, None), ['Natural', 'DULL'])

    # -- the finish ------------------------------------------------------
    def test_a_new_finish_has_its_own_name_and_a_layout_pick_adds_more(self):
        finish = self.env['product.attribute.value'].create({
            'attribute_id': self.attr.id, 'name': 'Zinc test'})
        self.assertEqual(finish.aw_name_ids.mapped('name'), ['Zinc test'])
        layout = self.env['aw.vendor.layout'].create({
            'vendor_id': self.vendor.id,
            'column_ids': [(0, 0, {
                'kind': 'finish', 'header': 'ZN', 'finish_id': finish.id})]})
        self.assertEqual(layout.column_ids.finish_id, finish)
        names = {n.name: n.vendor_id for n in finish.aw_name_ids}
        self.assertEqual(names['ZN'], self.vendor)
        # the order vendor's name first, the others after, joined
        self.assertEqual(finish.aw_label(self.vendor), 'ZN / Zinc test')
        self.assertEqual(finish.aw_label(), 'Zinc test / ZN')
        # a spelling already there is not added twice
        finish._aw_add_name('zn', self.vendor)
        finish._aw_add_name('zinc  TEST', self.vendor)
        self.assertEqual(len(finish.aw_name_ids), 2)
        # search by any name
        found = self.env['product.attribute.value'].name_search('ZN')
        self.assertIn(finish.id, [f[0] for f in found])

    def test_documents_use_the_customer_name_else_the_first_name(self):
        finish = self.env['product.attribute.value'].create({
            'attribute_id': self.attr.id, 'name': 'Doc finish'})
        finish._aw_add_name('VENDORNAME', self.vendor)
        self.assertEqual(finish.aw_doc_name(), 'Doc finish')
        finish.aw_customer_name = 'Champagne'
        self.assertEqual(finish.aw_doc_name(), 'Champagne')

    def test_new_finish_from_a_header_is_owned_by_the_vendor(self):
        layout = self.env['aw.vendor.layout'].create({
            'vendor_id': self.vendor.id,
            'column_ids': [(0, 0, {'kind': 'finish', 'header': 'WOODX'})]})
        self.assertIn('WOODX', layout.unmapped_note)
        layout.column_ids.action_new_finish()
        finish = layout.column_ids.finish_id
        self.assertEqual(finish.name, 'Woodx')
        self.assertEqual(finish.aw_owner_vendor_id, self.vendor)
        self.assertFalse(layout.unmapped_note)
        self.assertEqual(
            {n.name for n in finish.aw_name_ids}, {'Woodx', 'WOODX'})

    # -- Apply -----------------------------------------------------------
    def _layout(self, finish_columns):
        columns = [
            (0, 0, {'sequence': 10, 'kind': 'code', 'header': 'SEC.NO.'}),
            (0, 0, {'sequence': 20, 'kind': 'thickness'}),
            (0, 0, {'sequence': 30, 'kind': 'series'})]
        for index, (header, finish) in enumerate(finish_columns):
            columns.append((0, 0, {
                'sequence': 40 + index, 'kind': 'finish', 'header': header,
                'finish_id': finish.id}))
        return self.env['aw.vendor.layout'].create({
            'vendor_id': self.vendor.id, 'column_ids': columns,
            'thickness_alias_ids': [(0, 0, {
                'alias': 'NOR', 'thickness_id': self.standard.id})]})

    def _product(self, code, finishes):
        return self.env['product.template'].create({
            'name': code, 'default_code': code,
            'categ_id': self.env.ref(
                'aw_fenestration_core.product_category_profiles').id,
            'attribute_line_ids': [
                (0, 0, {'attribute_id': self.thick.id,
                        'value_ids': [(6, 0, self.standard.ids)]}),
                (0, 0, {'attribute_id': self.attr.id,
                        'value_ids': [(6, 0, finishes.ids)]})]})

    def _apply(self, text):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.vendor.id, 'date': date(2026, 11, 4),
            'paste_text': text})
        rate_list.action_parse_paste()
        rate_list.action_apply()
        return rate_list

    def test_apply_adds_only_a_finish_the_vendor_created(self):
        wood = self.env['product.attribute.value'].create({
            'attribute_id': self.attr.id, 'name': 'Wood test',
            'aw_owner_vendor_id': self.vendor.id})
        foreign = self.env['product.attribute.value'].create({
            'attribute_id': self.attr.id, 'name': 'Foreign test'})
        self._layout([('WOOD', wood), ('FOREIGN', foreign),
                      ('NAT', self.natural)])
        product = self._product('FN-1', self.natural)
        rate_list = self._apply('FN-1  NOR  100 200 300')
        rates = self.env['aw.profile.rate'].search([
            ('product_tmpl_id', '=', product.id)])
        by_finish = {r.finish_id: r.price for r in rates}
        # Wood was added to the profile and priced; Foreign was not
        self.assertEqual(by_finish.get(wood), 100.0)
        self.assertNotIn(foreign, by_finish)
        self.assertEqual(by_finish.get(self.natural), 300.0)
        offered = product.attribute_line_ids.filtered(
            lambda l: l.attribute_id == self.attr).value_ids
        self.assertIn(wood, offered)
        self.assertNotIn(foreign, offered)
        self.assertEqual(len(product.attribute_line_ids.filtered(
            lambda l: l.attribute_id == self.attr)), 1)
        self.assertIn('added to this profile', rate_list.line_ids.detail)
        # a second apply creates nothing new
        before = len(rates)
        self._apply('FN-1  NOR  100 200 300')
        self.assertEqual(self.env['aw.profile.rate'].search_count([
            ('product_tmpl_id', '=', product.id)]), before)

    # -- migration -------------------------------------------------------
    def test_migration_maps_premium_and_keeps_what_is_still_used(self):
        names = {v.name for v in self.attr.value_ids}
        if {'Brown', 'RAL P.C'} & names:
            raise unittest.SkipTest("a real stray finish exists here")
        sahara = self.attr.value_ids.filtered(
            lambda v: v.name == 'Brown PC Sahara')
        if not sahara:
            raise unittest.SkipTest("no seeded finishes")
        brown = self.env['product.attribute.value'].create(
            {'attribute_id': self.attr.id, 'name': 'Brown'})
        ral = self.env['product.attribute.value'].create(
            {'attribute_id': self.attr.id, 'name': 'RAL P.C'})
        premium = self.env['res.partner'].create({'name': 'Premium (names)'})
        layout = self.env['aw.vendor.layout'].create({
            'vendor_id': premium.id,
            'column_ids': [
                (0, 0, {'kind': 'finish', 'header': 'BRO',
                        'finish_id': brown.id}),
                (0, 0, {'kind': 'finish', 'header': 'SHARA',
                        'finish_id': sahara.id}),
                (0, 0, {'kind': 'finish', 'header': 'WOOD'})]})
        # something still points at RAL P.C, so it must survive
        product = self._product('RP-1', ral)
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': product.id, 'thickness_id': self.standard.id,
            'finish_id': ral.id, 'vendor_id': premium.id, 'price': 5.0,
            'date_from': date(2026, 1, 1)})
        report = self.attr.value_ids._do_migrate_finish_names()
        by_header = {c.header: c.finish_id for c in layout.column_ids}
        self.assertEqual(by_header['BRO'], sahara)
        self.assertEqual(by_header['WOOD'].name, 'Wood')
        self.assertEqual(by_header['WOOD'].aw_owner_vendor_id, premium)
        self.assertIn('BRO', sahara.aw_label(premium))
        self.assertFalse(brown.exists())
        self.assertIn('Brown', report['deleted'])
        self.assertTrue(ral.exists())
        self.assertIn('RAL P.C', report['kept'])
        self.assertEqual(report['before']['rates'] + 0,
                         report['after']['rates'])
        # a second run changes nothing
        again = self.attr.value_ids._do_migrate_finish_names()
        self.assertEqual(again['deleted'], [])
        self.assertEqual(len(sahara.aw_name_ids),
                         len(sahara.aw_name_ids.exists()))


@tagged('post_install', '-at_install')
class TestFinishNamesFreshInstall(TransactionCase):
    """The migration runs from a data file that loads BEFORE the Finish
    attribute exists. That is not an error: nothing is logged at ERROR, the
    done-flag stays unset, and the next run migrates."""

    def test_missing_attribute_is_quiet_then_next_run_migrates(self):
        from odoo.addons.aw_fenestration_core.models.finish_names import (
            MIGRATED_PARAM)
        env = self.env
        param = env['ir.config_parameter'].sudo()
        param.set_param(MIGRATED_PARAM, '')
        data = env['ir.model.data'].sudo().search([
            ('module', '=', 'aw_fenestration_core'),
            ('name', '=', 'aw_attribute_finish')])
        self.assertTrue(data)
        data.name = 'aw_attribute_finish_hidden'
        env.registry.clear_cache()
        Value = env['product.attribute.value']
        with self.assertNoLogs('odoo.addons.aw_fenestration_core.models.'
                               'finish_names', level='ERROR'):
            self.assertFalse(Value._migrate_finish_names())
        self.assertFalse(param.get_param(MIGRATED_PARAM))
        data.name = 'aw_attribute_finish'
        env.registry.clear_cache()
        self.assertTrue(Value._migrate_finish_names())
        self.assertTrue(param.get_param(MIGRATED_PARAM))
        attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        self.assertTrue(env['aw.finish.name'].search_count([
            ('finish_id', 'in', attr.value_ids.ids)]))
