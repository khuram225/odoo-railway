# -*- coding: utf-8 -*-
"""The chatter says what was done to the glass and hardware, by whom, on
which panel. It does not log the price, and a save that changes nothing
posts nothing."""
import unittest

from odoo.tests import TransactionCase, tagged
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestChatterGlassHardware(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        env['aw.glass.type']._seed_glass_types()
        env['aw.glass.option']._seed_glass_options()
        env['aw.glass.type']._seed_glass_sheet()
        cls.product = env['product.product'].create({
            'name': 'Chatter roller', 'standard_price': 50.0,
            'categ_id': env.ref('aw_fenestration_core.product_category_hardware').id})
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Chatter customer'}).id,
            'aw_default_series_id': series.id})
        cls.design = order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [dict(leaf), dict(leaf)]}]})

    def _save(self, edit):
        data = self.design.get_configurator_data()
        edit(data)
        self.design.save_layout({'header': data['header'], 'rows': data['rows']})

    def _notes(self):
        return self.design.message_ids.filtered(
            lambda m: 'Glass and hardware changed' in (m.body or ''))

    def _last(self):
        notes = self._notes().sorted('id')
        return notes[-1:] if notes else notes

    def _text(self, message):
        return message.body or ''

    def _row(self, qty=2, **extra):
        return dict({'product_id': self.product.id, 'name': 'Chatter roller',
                     'qty': qty, 'rate_manual': False, 'manual_rate': 0.0,
                     'list_rate': 50.0}, **extra)

    # -- hardware ----------------------------------------------------------------------
    def test_a_hardware_row_added_is_logged_with_the_panel_and_the_user(self):
        count = len(self._notes())
        self._save(lambda d: d['rows'][0]['leaves'][1].update(hardware=[self._row()]))
        notes = self._notes()
        self.assertEqual(len(notes), count + 1)
        note = self._last()
        self.assertIn('Panel 2 hardware: added Chatter roller x2', self._text(note))
        self.assertEqual(note.author_id, self.env.user.partner_id)

    def test_quantity_product_and_a_typed_rate_are_logged_then_reset(self):
        self._save(lambda d: d['rows'][0]['leaves'][0].update(hardware=[self._row(1)]))
        self._save(lambda d: d['rows'][0]['leaves'][0]['hardware'][0].update(qty=3))
        self.assertIn('qty 1 → 3', self._text(self._last()))
        self._save(lambda d: d['rows'][0]['leaves'][0]['hardware'][0].update(
            rate_manual=True, manual_rate=70.0))
        text = self._text(self._last())
        self.assertIn('typed rate 70.00', text)
        self.assertIn('product cost was 50.00', text)
        self._save(lambda d: d['rows'][0]['leaves'][0]['hardware'][0].update(
            rate_manual=False, manual_rate=0.0))
        self.assertIn('rate reset to the product cost', self._text(self._last()))
        self._save(lambda d: d['rows'][0]['leaves'][0].update(hardware=[]))
        self.assertIn('Panel 1 hardware: removed Chatter roller', self._text(self._last()))

    def test_a_save_that_changes_nothing_posts_nothing(self):
        self._save(lambda d: d['rows'][0]['leaves'][0].update(hardware=[self._row()]))
        count = len(self._notes())
        self._save(lambda d: None)
        self.assertEqual(len(self._notes()), count)

    # -- glass ---------------------------------------------------------------------------
    def test_the_window_default_and_a_panels_glass_are_logged(self):
        Product = self.env['product.product']
        category = self.env.ref('aw_fenestration_core.product_category_glass')
        unit = Product.create({'name': 'Chatter unit 6+12+6', 'categ_id': category.id})
        thick = Product.create({'name': 'Chatter unit 8+8+8', 'categ_id': category.id})

        def window(data):
            data['header']['glass_product_id'] = unit.id
        self._save(window)
        text = self._text(self._last())
        self.assertIn('Window glass: added Chatter unit 6+12+6', text)

        def panel(data):
            leaf = data['rows'][0]['leaves'][1]
            leaf['glass_chosen'] = True
            leaf['glass_product_id'] = thick.id
            leaf['glass_rate_manual'] = True
            leaf['glass_manual_rate'] = 55.0
        self._save(panel)
        text = self._text(self._last())
        self.assertIn('Panel 2 glass: added Chatter unit 8+8+8', text)

        def change(data):
            leaf = data['rows'][0]['leaves'][1]
            leaf['glass_chosen'] = True
            leaf['glass_product_id'] = unit.id
            leaf['glass_rate_manual'] = False
            leaf['glass_manual_rate'] = 0.0
        self._save(change)
        text = self._text(self._last())
        self.assertIn('Chatter unit 8+8+8 → Chatter unit 6+12+6', text)
        self.assertIn('rate reset to the', text)

    def test_the_price_is_not_logged(self):
        self._save(lambda d: d['rows'][0]['leaves'][0].update(hardware=[self._row()]))
        for message in self.design.message_ids:
            fields = message.tracking_value_ids.mapped('field_id.name')
            self.assertNotIn('price_total', fields)
            self.assertNotIn('cost_total', fields)
            self.assertNotIn('Price', message.body or '')
