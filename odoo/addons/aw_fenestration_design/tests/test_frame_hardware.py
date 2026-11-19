# -*- coding: utf-8 -*-
"""The frame's own hardware (client feedback, Part C): rows owned by the
window, priced and exploded like a panel's, copied with the window, and the
finish colours the drawing paints with."""
import unittest

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestFrameHardware(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest("No family with a system")
        cls.product = env['product.product'].create({
            'name': 'Test frame key',
            'categ_id': env.ref('aw_fenestration_core.product_category_hardware').id,
            'standard_price': 25.0,
        })
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Frame customer'}).id,
            'aw_default_series_id': series.id,
        })
        cls.design = order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [dict(leaf), dict(leaf)]}]})

    def _save_frame(self, rows):
        header = self.design.get_configurator_data()['header']
        header['hardware'] = rows
        self.design.save_layout({
            'header': header,
            'rows': [{'height_mm': r.height_mm, 'leaves': [
                {'width_mm': l.width_mm, 'leaf_type_id': l.leaf_type_id.id}
                for l in r.leaf_ids]} for r in self.design.row_ids]})

    def _frame_lines(self):
        self.design._explode()
        return self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'hardware' and l.product_id == self.product
            and not l.panel_no)

    def test_the_header_carries_the_frames_rows(self):
        self.assertEqual(self.design.get_configurator_data()['header']['hardware'], [])
        self._save_frame([{'product_id': self.product.id, 'qty': 3}])
        rows = self.design.get_configurator_data()['header']['hardware']
        self.assertEqual([(r['product_id'], r['qty']) for r in rows],
                         [(self.product.id, 3.0)])

    def test_a_save_that_does_not_send_them_leaves_them_alone(self):
        self._save_frame([{'product_id': self.product.id, 'qty': 3}])
        header = self.design.get_configurator_data()['header']
        header.pop('hardware')
        self.design.save_layout({'header': header, 'rows': [
            {'height_mm': r.height_mm, 'leaves': [
                {'width_mm': l.width_mm, 'leaf_type_id': l.leaf_type_id.id}
                for l in r.leaf_ids]} for r in self.design.row_ids]})
        self.assertEqual(len(self.design.frame_hardware_ids), 1)

    def test_the_frames_rows_are_priced_in_the_bom(self):
        self._save_frame([{'product_id': self.product.id, 'qty': 3}])
        line = self._frame_lines()
        self.assertEqual(len(line), 1)
        self.assertEqual(line.qty, 3)
        self.assertAlmostEqual(line.line_cost, 75.0)

    def test_a_typed_rate_is_manual(self):
        self._save_frame([{'product_id': self.product.id, 'qty': 2,
                           'rate_manual': True, 'manual_rate': 40.0}])
        line = self._frame_lines()
        self.assertTrue(line.rate_is_manual)
        self.assertAlmostEqual(line.line_cost, 80.0)

    def test_taking_every_row_off_follows_the_spec_again(self):
        self._save_frame([{'product_id': self.product.id, 'qty': 3}])
        self._save_frame([])
        self.assertFalse(self.design.frame_hardware_ids)
        self.assertFalse(self._frame_lines())

    def test_a_row_belongs_to_a_panel_or_the_frame(self):
        leaf = self.design.row_ids.leaf_ids[:1]
        with self.assertRaises(ValidationError):
            self.env['aw.design.hardware'].create({
                'product_id': self.product.id, 'qty': 1,
                'design_id': self.design.id, 'leaf_id': leaf.id})
        with self.assertRaises(ValidationError):
            self.env['aw.design.hardware'].create({
                'product_id': self.product.id, 'qty': 1})

    def test_the_spec_set_is_offered_only_while_the_frame_follows_it(self):
        self.design.frame_hardware_from_spec()  # may be empty, must not raise
        self._save_frame([{'product_id': self.product.id, 'qty': 1}])
        with self.assertRaises(UserError):
            self.design.frame_hardware_from_spec()

    def test_a_copy_of_the_window_keeps_the_frames_rows(self):
        self._save_frame([{'product_id': self.product.id, 'qty': 3}])
        copy = self.design.copy_position()
        self.assertNotEqual(copy, self.design)
        self.assertEqual(copy.frame_hardware_ids.product_id, self.product)
        self.assertNotEqual(copy.frame_hardware_ids, self.design.frame_hardware_ids)

    def test_every_finish_has_a_drawing_colour(self):
        # On a fresh database the seed ran before the finishes were imported,
        # so run it again the way an upgrade on a filled one would.
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.finish_drawing_colours_seeded', '')
        attribute = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        attribute.value_ids.filtered(lambda v: v.name == 'Natural').html_color = False
        self.env['product.attribute']._seed_finish_drawing_colours()
        for value in attribute.value_ids:
            self.assertTrue(value.html_color, value.name)
        # and a colour somebody chose is never touched
        chosen = attribute.value_ids[:1]
        chosen.html_color = '#123456'
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.finish_drawing_colours_seeded', '')
        self.env['product.attribute']._seed_finish_drawing_colours()
        self.assertEqual(chosen.html_color, '#123456')
