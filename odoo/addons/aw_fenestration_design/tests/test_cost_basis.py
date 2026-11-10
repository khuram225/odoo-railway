# -*- coding: utf-8 -*-
"""The cost basis: list rate only (default) or the cost rule."""
import unittest
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestCostBasis(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.family, cls.series = seeded_family_series(env)
        cls.vendor = env['res.partner'].create({'name': 'Basis vendor'})
        cls.customer = env['res.partner'].create({'name': 'Basis customer'})
        cls.today = fields.Date.context_today(env['res.partner'])
        cls.structure = env['aw.price.structure']._default_structure()
        env.flush_all()
        env.invalidate_all()

    # -- scaffolding ---------------------------------------------------------
    def _make(self, location='Hall'):
        env = self.env
        order = env['sale.order'].create({
            'partner_id': self.customer.id,
            'aw_default_series_id': self.series.id,
            'aw_profile_vendor_id': self.vendor.id})
        design = order._create_fenestration_position(
            self.series, family=self.family, location=location)
        design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0,
                'leaf_type_id': self.series.leaf_type_ids[0].id}
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        templates = design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.product_id
        ).product_id.product_tmpl_id
        for template in templates:
            env['aw.profile.rate'].create({
                'product_tmpl_id': template.id, 'vendor_id': self.vendor.id,
                'price': 10.0, 'date_from': self.today - timedelta(days=30)})
        design._explode()
        design._sync_sale_order_line()
        self.assertTrue(design.cost_total, "the window was not costed")
        return order, design

    def _last_prices(self, design, price, days_ago=1):
        for variant in design.bom_line_ids.filtered(
                lambda l: l.kind == 'profile' and l.product_id).product_id:
            thickness, finish = variant._aw_cost_key()
            self.env['aw.profile.lpp'].create({
                'vendor_id': self.vendor.id,
                'product_tmpl_id': variant.product_tmpl_id.id,
                'thickness_id': thickness.id or False,
                'finish_id': finish.id or False, 'bar_length_ft': 18.0,
                'price_ft': price,
                'date': self.today - timedelta(days=days_ago)})

    def _profile_variant(self):
        """A profile variant whose default vendor we control: the default
        vendor is patched to this test's vendor."""
        category = self.env.ref('aw_fenestration_core.product_category_profiles')
        variant = self.env['product.product'].search(
            [('categ_id', 'child_of', category.id)], limit=1)
        if not variant:
            self.skipTest("no profile variant here")
        return variant

    def _vendor_patch(self):
        return patch.object(
            self.registry['product.template'], '_aw_default_vendor',
            lambda template: self.vendor)

    def _give_rate_and_last_price(self, variant, list_price=10.0,
                                  lpp_price=20.0):
        thickness, finish = variant._aw_cost_key()
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': variant.product_tmpl_id.id,
            'thickness_id': thickness.id or False,
            'finish_id': finish.id or False, 'vendor_id': self.vendor.id,
            'price': list_price,
            'date_from': self.today - timedelta(days=30)})
        self.env['aw.profile.lpp'].create({
            'vendor_id': self.vendor.id,
            'product_tmpl_id': variant.product_tmpl_id.id,
            'thickness_id': thickness.id or False,
            'finish_id': finish.id or False, 'bar_length_ft': 18.0,
            'price_ft': lpp_price, 'date': self.today})

    # -- the setting ---------------------------------------------------------
    def test_the_basis_is_the_list_rate_unless_somebody_changes_it(self):
        self.assertEqual(self.structure.cost_basis, 'list')
        new = self.env['aw.price.structure'].create({'name': 'Another'})
        self.assertEqual(new.cost_basis, 'list')

    # -- quotes --------------------------------------------------------------
    def test_a_quote_follows_the_basis_of_its_structure(self):
        _order, design = self._make()
        self._last_prices(design, 20.0)
        design._explode()
        listed = design.cost_total
        design.price_structure_id.cost_basis = 'rule'
        design._explode()
        self.assertGreater(design.cost_total, listed)
        design.price_structure_id.cost_basis = 'list'
        design._explode()
        self.assertAlmostEqual(design.cost_total, listed)

    def test_a_confirmed_order_keeps_its_cost_when_the_basis_is_switched_on(self):
        order, design = self._make()
        self._last_prices(design, 20.0)
        order.state = 'sale'
        cost, price = design.cost_total, design.price_total
        design.price_structure_id.cost_basis = 'rule'
        design._explode()
        self.assertAlmostEqual(design.cost_total, cost)
        self.assertAlmostEqual(design.price_total, price)

    def test_the_preview_does_not_depend_on_the_basis_in_force(self):
        _order, design = self._make()
        self._last_prices(design, 20.0)
        design.price_structure_id.cost_basis = 'rule'
        wizard = self.env['aw.cost.preview.wizard'].browse(
            self.env['aw.cost.preview.wizard'].action_open()['res_id'])
        line = wizard.line_ids.filtered(lambda l: l.design_id == design)
        # "today" is always the list; the rule pass is the difference
        self.assertGreater(line.cost_rule, line.cost_now)

    def test_the_structure_form_opens_the_preview(self):
        action = self.structure.action_open_cost_preview()
        self.assertEqual(action['res_model'], 'aw.cost.preview.wizard')

    # -- the cost field -------------------------------------------------------
    def test_the_cost_field_follows_the_list_by_default_and_the_rule_when_on(self):
        variant = self._profile_variant()
        self._give_rate_and_last_price(variant)
        with self._vendor_patch():
            variant.sudo().standard_price = 0.0
            variant._aw_sync_cost_from_rate()
            self.assertEqual(variant.standard_price, 10.0)         # the list
            self.structure.cost_basis = 'rule'
            variant._aw_sync_cost_from_rate()
            self.assertEqual(variant.standard_price, 20.0)         # the rule

    def test_the_sync_tags_what_it_writes_and_leaves_a_typed_cost_alone(self):
        variant = self._profile_variant()
        self._give_rate_and_last_price(variant)
        with self._vendor_patch():
            variant.sudo().standard_price = 0.0
            variant._aw_sync_cost_from_rate()
            last = self.env['product.value'].sudo().search(
                [('product_id', '=', variant.id), ('move_id', '=', False)],
                order='id desc', limit=1)
            self.assertTrue(last.description.startswith('[rates sync]'))
            # somebody types a cost that is no rate and no last price
            variant.sudo().standard_price = 123.45
            kept = []
            updated, _blocked = variant.with_context(
                aw_kept_costs=kept)._aw_sync_cost_from_rate()
            self.assertFalse(updated)
            self.assertEqual(variant.standard_price, 123.45)
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0][0], variant)

    def test_the_update_button_says_what_it_kept(self):
        variant = self._profile_variant()
        self._give_rate_and_last_price(variant)
        with self._vendor_patch():
            variant.sudo().standard_price = 123.45
            action = variant.action_aw_update_costs_from_rates()
        self.assertIn('Kept, typed by hand', action['params']['message'])
        self.assertEqual(variant.standard_price, 123.45)

    def test_a_new_profile_variant_is_costed_when_it_is_made(self):
        variant = self._profile_variant()
        template = variant.product_tmpl_id
        thickness, finish = variant._aw_cost_key()
        # a combination the template carries but has no variant for yet
        attribute_lines = template.attribute_line_ids
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        other_finish = attribute_lines.filtered(
            lambda l: l.attribute_id == finish_attr).value_ids - finish
        if not other_finish:
            self.skipTest("this profile has a single finish")
        other_finish = other_finish[:1]
        self.env['aw.profile.rate'].create({
            'product_tmpl_id': template.id,
            'thickness_id': thickness.id or False,
            'finish_id': other_finish.id, 'vendor_id': self.vendor.id,
            'price': 33.0, 'date_from': self.today - timedelta(days=5)})
        with self._vendor_patch():
            made = self.env['aw.profile.section.line']._variant_for(
                template, thickness, other_finish)
            # made by any other route: the picker's default variant etc.
            self.assertEqual(made.standard_price, 33.0)

    # -- a confirmed purchase order ----------------------------------------------
    def test_confirming_a_purchase_order_moves_the_cost_only_when_the_rule_is_on(self):
        variant = self._profile_variant()
        self._give_rate_and_last_price(variant, 10.0, 10.0)
        thickness, finish = variant._aw_cost_key()
        for ft in (14.0,):
            self.env['aw.vendor.bar.length'].create({
                'vendor_id': self.vendor.id,
                'product_tmpl_id': variant.product_tmpl_id.id,
                'length_ft': ft})
        self.env['aw.profile.lpp'].search(
            [('vendor_id', '=', self.vendor.id)]).unlink()
        with self._vendor_patch():
            variant.sudo().standard_price = 10.0
            order = self.env['purchase.order'].create(
                {'partner_id': self.vendor.id})
            order.aw_bars_grid_apply(variant.product_tmpl_id.id, [{
                'thickness_id': thickness.id, 'finish_id': finish.id,
                'length_ft': 14.0, 'bars': 2}])
            order.order_line.write({'price_unit': 15.0})
            order.with_context(aw_confirm_anyway=True).button_confirm()
            self.assertEqual(variant.standard_price, 10.0)    # rule is off
            order.button_unlock()
            order.button_cancel()
            self.structure.cost_basis = 'rule'
            order2 = self.env['purchase.order'].create(
                {'partner_id': self.vendor.id})
            order2.aw_bars_grid_apply(variant.product_tmpl_id.id, [{
                'thickness_id': thickness.id, 'finish_id': finish.id,
                'length_ft': 14.0, 'bars': 2}])
            order2.order_line.write({'price_unit': 15.0})
            order2.with_context(aw_confirm_anyway=True).button_confirm()
            variant.invalidate_recordset(['standard_price'])
            self.assertEqual(variant.standard_price, 15.0)    # the rule
