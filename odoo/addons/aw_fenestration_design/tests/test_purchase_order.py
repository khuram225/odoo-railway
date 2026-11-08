# -*- coding: utf-8 -*-
"""P2: the purchase order made from a Draft batch."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
import unittest

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPurchaseOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'PO customer'}).id,
            'aw_default_series_id': series.id,
            'aw_profile_vendor_id': env['res.partner'].create(
                {'name': 'PO profile vendor'}).id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        windows = env['aw.design']
        for location in ('Hall', 'Kitchen'):
            design = cls.order._create_fenestration_position(
                series, family=family, location=location)
            design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': 1800.0,
                          'leaves': [dict(leaf), dict(leaf)]}]})
            windows |= design
        cls.hall, cls.kitchen = windows
        cls.manager = env['res.users'].create({
            'name': 'PO manager', 'login': 'po_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_core.group_fenestration_manager').id,
            ])]})
        cls.seller = env['res.users'].create({
            'name': 'PO seller', 'login': 'po_seller',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('aw_fenestration_design.group_fenestration_sales').id,
            ])]})

    def _batch(self, design):
        action = self.order.action_new_batch()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.line_ids.filtered(
            lambda l: l.design_id != design).selected = False
        wizard.action_create()
        return self.order.aw_cut_plan_ids.filtered(
            lambda p: design in p.design_ids and p.state != 'cancel')

    def _rated(self, batch, rate=2.5):
        """Give every group a vendor rate in force, as a real one would."""
        batch.group_ids.write({
            'rate_per_ft': rate, 'rate_date': '2026-01-01'})

    def test_one_line_per_profile_and_length_with_bars_times_length(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        order = batch.purchase_order_id
        self.assertEqual(order.partner_id, batch.profile_vendor_id)
        self.assertEqual(order.state, 'draft')
        want = {}
        for group in batch.group_ids:
            for bar in group.bar_ids.filtered(lambda b: not b.from_bar_id):
                key = (group.product_id, round(bar.stock_mm / 304.8, 4))
                want[key] = want.get(key, 0) + 1
        got = {(l.product_id, l.aw_bar_length_ft): l.aw_bar_count
               for l in order.order_line}
        self.assertEqual(got, want)
        foot = self.env.ref('uom.product_uom_foot')
        self.assertTrue(foot.active)
        for line in order.order_line:
            self.assertEqual(line.product_uom_id, foot)
            self.assertAlmostEqual(
                line.product_qty, line.aw_bar_count * line.aw_bar_length_ft)
            self.assertEqual(line.price_unit, 2.5)
            self.assertFalse(line.aw_price_note)
        self.assertEqual(
            sum(l.aw_bar_count for l in order.order_line), batch.bar_count)

    def test_the_quote_cost_sits_next_to_the_order_total(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        self.assertAlmostEqual(
            batch.po_total, batch.purchase_order_id.amount_untaxed)
        self.assertAlmostEqual(
            batch.po_vs_quote, batch.po_total - batch.cost_total)

    def test_a_profile_with_no_rate_is_on_the_order_marked_no_price(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        first = batch.group_ids[:1]
        first.write({'rate_date': False, 'rate_per_ft': 7.0})
        batch.action_create_purchase_order()
        lines = batch.purchase_order_id.order_line
        bare = lines.filtered(lambda l: l.product_id == first.product_id)
        self.assertTrue(bare, "the unrated profile must not be left out")
        for line in bare:
            self.assertEqual(line.price_unit, 0.0)
            self.assertEqual(line.aw_price_note, 'No price')
        self.assertEqual(len(lines), len(batch._purchase_lines()))

    def test_changing_the_bars_changes_the_quantity_not_the_price(self):
        batch = self._batch(self.hall)
        self._rated(batch, rate=3.25)
        batch.action_create_purchase_order()
        line = batch.purchase_order_id.order_line[:1]
        line.aw_bar_count += 2
        self.assertAlmostEqual(
            line.product_qty, line.aw_bar_count * line.aw_bar_length_ft)
        self.assertEqual(line.price_unit, 3.25)
        line.product_id.standard_price = 99.0
        line.aw_bar_count += 1
        self.assertEqual(line.price_unit, 3.25)

    def test_a_quantity_that_is_not_bars_times_length_is_refused(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        line = batch.purchase_order_id.order_line[:1]
        with self.assertRaises(ValidationError):
            line.product_qty = line.product_qty + 1.0

    def test_an_ordinary_line_is_untouched(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        product = batch.group_ids[:1].product_id
        order = self.env['purchase.order'].create({
            'partner_id': batch.profile_vendor_id.id,
            'order_line': [(0, 0, {
                'product_id': product.id, 'product_qty': 5.0})]})
        line = order.order_line
        self.assertFalse(line.aw_is_bars)
        self.assertEqual(line.product_qty, 5.0)

    def test_stock_bars_are_not_bought(self):
        first = self._batch(self.hall)
        first.group_ids[:1].bar_ids[:1].write(
            {'remainder_mm': 3000.0, 'is_returnable': True})
        first.action_mark_bought()
        second = self._batch(self.kitchen)
        self._rated(second)
        second.action_create_purchase_order()
        bought = second.group_ids.bar_ids.filtered(
            lambda b: not b.from_bar_id)
        self.assertEqual(
            sum(second.purchase_order_id.order_line.mapped('aw_bar_count')),
            len(bought))

    def test_one_order_and_only_for_a_current_draft_batch(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.action_create_purchase_order()
        with self.assertRaises(UserError):
            batch.action_create_purchase_order()
        batch.purchase_order_id.button_cancel()
        batch.action_create_purchase_order()     # a cancelled one is replaced
        self.assertEqual(batch.purchase_order_id.state, 'draft')
        stale = self._batch(self.kitchen)
        stale.bom_fingerprint = 'old'
        with self.assertRaises(UserError):
            stale.action_create_purchase_order()

    def test_a_final_batch_gets_no_new_order(self):
        batch = self._batch(self.hall)
        batch.action_mark_bought()
        with self.assertRaises(UserError):
            batch.action_create_purchase_order()

    def test_a_manager_without_purchase_rights_can_make_it(self):
        batch = self._batch(self.hall)
        self._rated(batch)
        batch.with_user(self.manager).action_create_purchase_order()
        self.assertTrue(batch.purchase_order_id)
        self.assertEqual(batch.purchase_order_id.create_uid, self.manager)

    def test_the_button_is_only_in_a_managers_form(self):
        Plan = self.env['aw.cut.plan']
        manager = Plan.with_user(self.manager).get_view(
            view_type='form')['arch']
        seller = Plan.with_user(self.seller).get_view(
            view_type='form')['arch']
        self.assertIn('action_create_purchase_order', manager)
        self.assertNotIn('action_create_purchase_order', seller)


@tagged('post_install', '-at_install')
class TestPurchaseLineEntry(TransactionCase):
    """A profile line typed by hand."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        category = env.ref('aw_fenestration_core.product_category_profiles')
        cls.template = env['product.template'].search(
            [('categ_id', 'child_of', category.id)], limit=1)
        cls.vendor = env['res.partner'].create({'name': 'Entry vendor'})
        cls.product = cls.template.sudo()._create_first_product_variant()
        cls.thickness = cls.finish = env['product.attribute.value']
        for value in cls.product.product_template_variant_value_ids:
            if value.attribute_id.name == 'Thickness':
                cls.thickness = value.product_attribute_value_id
            elif value.attribute_id.name == 'Finish':
                cls.finish = value.product_attribute_value_id
        cls.rate = env['aw.profile.rate'].create({
            'product_tmpl_id': cls.template.id,
            'thickness_id': cls.thickness.id, 'finish_id': cls.finish.id,
            'vendor_id': cls.vendor.id, 'price': 4.0,
            'date_from': '2000-01-01'})
        cls.plain = env['product.product'].create({
            'name': 'Plain test part', 'type': 'consu'})

    def _order(self):
        return self.env['purchase.order'].create({
            'partner_id': self.vendor.id})

    def _line(self, order, product=None, **extra):
        return self.env['purchase.order.line'].create(dict({
            'order_id': order.id, 'product_id': (product or self.product).id,
            'product_qty': 1.0}, **extra))

    def test_a_profile_opens_the_one_variant_picker_not_the_grid(self):
        answer = self.template.get_single_product_variant()
        self.assertTrue(answer.get('product_id'))
        self.assertEqual(
            self.env['product.product'].browse(answer['product_id']).product_tmpl_id,
            self.template)

    def test_another_product_is_left_as_it_was(self):
        answer = self.plain.product_tmpl_id.get_single_product_variant()
        self.assertEqual(answer.get('product_id'), self.plain.id)

    def test_a_single_active_length_is_filled_in(self):
        Length = self.env['aw.vendor.bar.length']
        Length.create({'vendor_id': self.vendor.id,
                       'product_tmpl_id': self.template.id, 'length_ft': 16})
        line = self.env['purchase.order.line'].new({
            'order_id': self._order().id, 'product_id': self.product.id})
        line._onchange_aw_profile_length()
        self.assertEqual(line.aw_bar_length_ft, 16.0)
        Length.create({'vendor_id': self.vendor.id,
                       'product_tmpl_id': self.template.id, 'length_ft': 18})
        again = self.env['purchase.order.line'].new({
            'order_id': self._order().id, 'product_id': self.product.id})
        again._onchange_aw_profile_length()
        self.assertFalse(again.aw_bar_length_ft)

    def test_a_profile_line_without_bars_says_so(self):
        line = self._line(self._order())
        self.assertEqual(line.aw_price_note, 'Enter bars and bar length')
        line.write({'aw_bar_length_ft': 16.0})
        self.assertEqual(line.aw_price_note, 'Enter bars and bar length')
        line.write({'aw_bar_count': 3})
        self.assertNotEqual(line.aw_price_note, 'Enter bars and bar length')
        other = self._line(self._order(), product=self.plain)
        self.assertFalse(other.aw_price_note)

    def test_bars_and_length_on_an_unpriced_line_take_the_vendor_rate(self):
        line = self._line(self._order(), price_unit=0.0)
        line.write({'price_unit': 0.0, 'technical_price_unit': 0.0})
        line.write({'aw_bar_length_ft': 16.0, 'aw_bar_count': 5})
        self.assertEqual(line.price_unit, 4.0)
        self.assertEqual(line.product_uom_id, self.env.ref('uom.product_uom_foot'))
        self.assertAlmostEqual(line.product_qty, 80.0)
        self.assertFalse(line.aw_price_note)
        line.aw_bar_count = 6
        self.assertEqual(line.price_unit, 4.0)
        self.assertAlmostEqual(line.product_qty, 96.0)

    def test_a_price_that_is_there_is_kept_and_follows_the_unit(self):
        line = self._line(self._order(), price_unit=3.048)   # per metre
        line.write({'price_unit': 3.048, 'technical_price_unit': 3.048})
        uom = line.product_uom_id
        line.write({'aw_bar_length_ft': 16.0, 'aw_bar_count': 2})
        foot = self.env.ref('uom.product_uom_foot')
        self.assertAlmostEqual(
            line.price_unit, uom._compute_price(3.048, foot), places=4)


@tagged('post_install', '-at_install')
class TestBarsGrid(TransactionCase):
    """The bars grid: thickness x finish x length on one profile."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        category = env.ref('aw_fenestration_core.product_category_profiles')
        thickness_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        cls.template = env['product.template']
        for template in env['product.template'].search(
                [('categ_id', 'child_of', category.id)]):
            lines = template.attribute_line_ids
            if len(lines.filtered(
                    lambda l: l.attribute_id == finish_attr).value_ids) >= 2 \
                    and lines.filtered(
                        lambda l: l.attribute_id == thickness_attr).value_ids:
                cls.template = template
                break
        if not cls.template:
            raise unittest.SkipTest("No profile with two finishes here")
        lines = cls.template.attribute_line_ids
        cls.thickness = lines.filtered(
            lambda l: l.attribute_id == thickness_attr).value_ids[0]
        cls.f1, cls.f2 = lines.filtered(
            lambda l: l.attribute_id == finish_attr).value_ids[:2]
        cls.vendor = env['res.partner'].create({'name': 'Grid vendor'})
        cls.lengths = {}
        for ft in (14.0, 16.0, 18.0):
            cls.lengths[ft] = env['aw.vendor.bar.length'].create({
                'vendor_id': cls.vendor.id,
                'product_tmpl_id': cls.template.id, 'length_ft': ft})
        # a rate for the first finish only: the second shows "no price"
        env['aw.profile.rate'].create({
            'product_tmpl_id': cls.template.id,
            'thickness_id': cls.thickness.id, 'finish_id': cls.f1.id,
            'vendor_id': cls.vendor.id, 'price': 2.5,
            'date_from': '2000-01-01'})

    def _order(self):
        return self.env['purchase.order'].create({
            'partner_id': self.vendor.id})

    def _cell(self, finish, length, bars):
        return {'thickness_id': self.thickness.id, 'finish_id': finish.id,
                'length_ft': length, 'bars': bars}

    def _apply(self, order, *cells):
        order.aw_bars_grid_apply(self.template.id, list(cells))

    def test_two_finishes_three_lengths_make_the_right_lines(self):
        order = self._order()
        self._apply(
            order, self._cell(self.f1, 14.0, 2), self._cell(self.f1, 16.0, 1),
            self._cell(self.f1, 18.0, 0), self._cell(self.f2, 18.0, 3),
            self._cell(self.f2, 14.0, 0), self._cell(self.f2, 16.0, 0))
        lines = order.order_line
        self.assertEqual(len(lines), 3)
        foot = self.env.ref('uom.product_uom_foot')
        by = {(l.aw_bar_length_ft, l.aw_bar_count): l for l in lines}
        self.assertEqual(set(by), {(14.0, 2), (16.0, 1), (18.0, 3)})
        for line in lines:
            self.assertEqual(line.product_uom_id, foot)
            self.assertAlmostEqual(
                line.product_qty, line.aw_bar_count * line.aw_bar_length_ft)
        self.assertEqual(by[(14.0, 2)].price_unit, 2.5)
        self.assertEqual(by[(16.0, 1)].price_unit, 2.5)
        self.assertEqual(by[(18.0, 3)].price_unit, 0.0)
        self.assertEqual(by[(18.0, 3)].aw_price_note, 'No price')
        self.assertEqual(
            by[(14.0, 2)].product_id,
            self.env['aw.profile.section.line']._variant_for(
                self.template, self.thickness, self.f1))

    def test_data_lists_finishes_rates_lengths_and_the_bars_already_there(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4))
        data = order.aw_bars_grid_data(self.template.id)
        self.assertEqual(data['lengths'], [14.0, 16.0, 18.0])
        self.assertTrue(data['editable'])
        self.assertEqual(
            data['rates']['%s|%s' % (self.thickness.id, self.f1.id)], 2.5)
        self.assertFalse(
            data['rates']['%s|%s' % (self.thickness.id, self.f2.id)])
        self.assertEqual(
            data['cells']['%s|%s|16' % (self.thickness.id, self.f1.id)], 4)
        self.assertIn(self.f2.id, [f['id'] for f in data['finishes']])

    def test_applying_again_updates_and_never_duplicates(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4))
        line = order.order_line
        self._apply(order, self._cell(self.f1, 16.0, 7))
        self.assertEqual(order.order_line, line)
        self.assertEqual(line.aw_bar_count, 7)
        self.assertAlmostEqual(line.product_qty, 7 * 16.0)
        self.assertEqual(line.price_unit, 2.5)

    def test_zero_removes_the_line(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4),
                    self._cell(self.f1, 14.0, 2))
        self._apply(order, self._cell(self.f1, 16.0, 0))
        self.assertEqual(order.order_line.aw_bar_length_ft, 14.0)

    def test_a_length_switched_off_is_not_offered_or_accepted(self):
        self.lengths[18.0].active = False
        order = self._order()
        self.assertEqual(
            order.aw_bars_grid_data(self.template.id)['lengths'], [14.0, 16.0])
        with self.assertRaises(UserError):
            self._apply(order, self._cell(self.f1, 18.0, 2))
        self.assertFalse(order.order_line)

    def test_a_confirmed_order_refuses(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4))
        order.write({'state': 'purchase'})
        self.assertFalse(
            order.aw_bars_grid_data(self.template.id)['editable'])
        with self.assertRaises(UserError):
            self._apply(order, self._cell(self.f1, 16.0, 9))
        with self.assertRaises(UserError):
            self._apply(order, self._cell(self.f1, 16.0, 0))
        self.assertEqual(order.order_line.aw_bar_count, 4)

    def test_bars_are_whole_numbers(self):
        order = self._order()
        with self.assertRaises(UserError):
            self._apply(order, self._cell(self.f1, 16.0, 1.5))
        with self.assertRaises(UserError):
            self._apply(order, self._cell(self.f1, 16.0, -1))

    def test_only_profiles_can_be_picked(self):
        order = self._order()
        other = self.env['product.product'].create(
            {'name': 'Not a profile', 'type': 'consu'}).product_tmpl_id
        with self.assertRaises(UserError):
            order.aw_bars_grid_data(other.id)
        names = [p['id'] for p in order.aw_bars_grid_profiles('')]
        self.assertIn(self.template.id, names)
        self.assertNotIn(other.id, names)

    def test_the_button_opens_the_dialog(self):
        order = self._order()
        action = self.env['purchase.order.line'].with_context(
            order_id=order.id).action_add_profile_bars()
        self.assertEqual(action['params']['order_id'], order.id)
        self.assertEqual(action['tag'], 'aw_po_bars_grid')

    # -- the line tidy -----------------------------------------------------
    def test_the_bars_text_follows_the_numbers(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4))
        line = order.order_line
        self.assertIn('4 bars x 16 ft = 64 ft', line.name)
        self.assertTrue(line.name.startswith(self.template.name))
        line.aw_bar_length_ft = 18.0
        self.assertIn('4 bars x 18 ft = 72 ft', line.name)
        self.assertNotIn('16 ft', line.name)
        self.assertAlmostEqual(line.product_qty, 72.0)
        line.aw_bar_count = 5
        self.assertIn('5 bars x 18 ft = 90 ft', line.name)

    def test_an_old_line_with_stale_text_is_fixed(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 18.0, 28))
        line = order.order_line
        line.name = 'RE-10: 28 x 14 ft bars'
        self.assertIn('14 ft', line.name)
        self.env['purchase.order.line']._aw_refresh_bars_names()
        self.assertIn('28 bars x 18 ft = 504 ft', line.name)
        self.assertNotIn('14 ft', line.name)

    def test_the_price_note_says_when_the_price_is_not_the_list(self):
        order = self._order()
        self._apply(order, self._cell(self.f1, 16.0, 4))
        line = order.order_line
        self.assertFalse(line.aw_price_note)
        line.price_unit = 2.75
        self.assertEqual(line.aw_price_note, 'list 2.50 - +10.0%')
        line.price_unit = 2.25
        self.assertEqual(line.aw_price_note, 'list 2.50 - -10.0%')
        line.price_unit = 2.5
        self.assertFalse(line.aw_price_note)

    def test_lines_are_ordered_by_finish_thickness_and_length(self):
        order = self._order()
        self._apply(
            order, self._cell(self.f2, 14.0, 1), self._cell(self.f1, 18.0, 1),
            self._cell(self.f2, 16.0, 1), self._cell(self.f1, 14.0, 1))

        def label(line):
            finish = order._aw_variant_values(line.product_id)[1]
            return (order._aw_finish_label(finish, order.partner_id),
                    line.aw_bar_length_ft)
        shown = [label(l) for l in order.order_line.sorted('sequence')]
        self.assertEqual(shown, sorted(shown))
        self.assertEqual(len(set(order.order_line.mapped('sequence'))), 4)

    def test_the_grid_shows_only_the_vendors_own_finish_names(self):
        order = self._order()
        self.f1._aw_add_name('VENDORDULL', self.vendor)
        other = self.env['res.partner'].create({'name': 'Another vendor'})
        self.f1._aw_add_name('OTHERSHINE', other)
        names = {f['id']: f['name'] for f in
                 order.aw_bars_grid_data(self.template.id)['finishes']}
        self.assertEqual(names[self.f1.id], 'VENDORDULL')
        self.assertNotIn('OTHERSHINE', names[self.f1.id])
        self.assertEqual(names[self.f2.id], order._aw_finish_label(
            self.f2, self.vendor))
