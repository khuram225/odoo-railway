# -*- coding: utf-8 -*-
"""A window is one window; Make copies makes one per typed location."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMakeCopies(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Copies customer'}).id,
            'aw_default_series_id': series.id})
        cls.design = cls.order._create_fenestration_position(
            series, family=family, location='Original')
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})

    def _wizard(self, text, design=None):
        return self.env['aw.design.copies.wizard'].create({
            'design_id': (design or self.design).id, 'locations': text})

    # -- quantity is fixed at 1 ----------------------------------------------
    def test_a_new_window_cannot_have_a_quantity_above_one(self):
        with self.assertRaises(UserError):
            self.env['aw.design'].create({
                'name': 'Q2', 'qty': 2,
                'window_series_id': self.design.window_series_id.id})

    def test_the_quantity_cannot_be_raised_but_can_be_left_or_lowered(self):
        with self.assertRaises(UserError):
            self.design.write({'qty': 3})
        self.design.write({'qty': 1})            # every save writes it back

    def test_an_existing_window_with_more_than_one_is_left_alone(self):
        self.env.cr.execute(
            "UPDATE aw_design SET qty = 3 WHERE id = %s", (self.design.id,))
        self.design.invalidate_recordset(['qty'])
        self.assertEqual(self.design.qty, 3)
        self.design.write({'qty': 3})            # unchanged: allowed
        self.design.write({'location': 'Still fine'})
        self.assertEqual(self.design.qty, 3)
        self.design.write({'qty': 1})            # lowering is allowed
        with self.assertRaises(UserError):
            self.design.write({'qty': 2})

    # -- the dialog ----------------------------------------------------------
    def test_one_window_per_line_each_with_its_own_location(self):
        before = self.order.aw_design_ids
        self._wizard('Drawing room\n  Bedroom 1  \n\nBedroom 2\n').action_make()
        made = self.order.aw_design_ids - before
        self.assertEqual(sorted(made.mapped('location')),
                         ['Bedroom 1', 'Bedroom 2', 'Drawing room'])
        self.assertEqual(set(made.mapped('qty')), {1})
        self.assertEqual(len(set(made.mapped('name'))), 3)
        self.assertFalse(set(made.mapped('name')) & set(before.mapped('name')))
        # each on a quote line of its own, quantity 1
        lines = made.mapped('sale_order_line_id')
        self.assertEqual(len(lines), 3)
        self.assertEqual(set(lines.mapped('product_uom_qty')), {1.0})
        # the same layout as the source
        for copy in made:
            self.assertEqual(copy.width_mm, self.design.width_mm)
            self.assertEqual(len(copy.row_ids.leaf_ids),
                             len(self.design.row_ids.leaf_ids))

    def test_the_source_window_is_not_changed(self):
        location, name, qty = (self.design.location, self.design.name,
                               self.design.qty)
        rows = self.design.row_ids.ids
        self._wizard('A\nB').action_make()
        self.assertEqual((self.design.location, self.design.name,
                          self.design.qty), (location, name, qty))
        self.assertEqual(self.design.row_ids.ids, rows)

    def test_a_copy_of_an_older_window_is_one_window(self):
        self.env.cr.execute(
            "UPDATE aw_design SET qty = 3 WHERE id = %s", (self.design.id,))
        self.design.invalidate_recordset(['qty'])
        before = self.order.aw_design_ids
        self._wizard('Only one').action_make()
        copy = self.order.aw_design_ids - before
        self.assertEqual(copy.qty, 1)

    def test_it_is_logged_on_the_quote(self):
        self._wizard('Hall').action_make()
        self.assertIn('Hall', ' '.join(self.order.message_ids.mapped('body')))

    def test_nothing_to_make_is_refused(self):
        with self.assertRaises(UserError):
            self._wizard('  \n\n ').action_make()

    def test_too_many_at_once_is_refused(self):
        with self.assertRaises(UserError):
            self._wizard('\n'.join('L%s' % n for n in range(101))).action_make()

    def test_a_confirmed_quote_takes_no_more_windows(self):
        self.order.write({'state': 'sale'})
        with self.assertRaises(UserError):
            self._wizard('Late').action_make()

    def test_the_button_opens_the_dialog(self):
        action = self.design.action_make_copies()
        self.assertEqual(action['res_model'], 'aw.design.copies.wizard')
        self.assertEqual(action['context']['default_design_id'],
                         self.design.id)
