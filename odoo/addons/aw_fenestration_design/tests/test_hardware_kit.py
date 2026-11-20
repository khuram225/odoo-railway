# -*- coding: utf-8 -*-
"""Hardware Sets saved from the configurator (aw.hardware.kit): a plain list
of products and quantities, copied onto a panel's rows, so a set that is
edited or deleted later changes nothing already on a window."""
import unittest

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestHardwareKit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        category = env.ref('aw_fenestration_core.product_category_hardware')
        cls.roller = env['product.product'].create({
            'name': 'Kit roller', 'categ_id': category.id,
            'standard_price': 50.0})
        cls.lock = env['product.product'].create({
            'name': 'Kit lock', 'categ_id': category.id,
            'standard_price': 20.0})
        cls.Kit = env['aw.hardware.kit']
        manager_group = env.ref('aw_fenestration_core.group_fenestration_manager')
        cls.manager = env['res.users'].create({
            'name': 'Kit manager', 'login': 'kit_manager',
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id, manager_group.id])],
        })
        cls.plain_user = env['res.users'].create({
            'name': 'Kit plain user', 'login': 'kit_plain',
            'group_ids': [(6, 0, [env.ref('base.group_user').id])],
        })

    def _rows(self):
        return [
            {'product_id': self.roller.id, 'qty': 2, 'rate_manual': True,
             'manual_rate': 70.0},
            {'product_id': self.lock.id, 'qty': 1, 'rate_manual': False,
             'manual_rate': 0.0},
            {'product_id': False, 'qty': 5},
        ]

    def _save(self, name='Casement set', with_rates=False, user=None, rows=None):
        return self.Kit.with_user(user or self.manager).create_from_rows(
            name, False, self._rows() if rows is None else rows, with_rates)

    def test_save_keeps_products_and_quantities_but_no_rate_by_default(self):
        kit = self._save()
        self.assertEqual([r['qty'] for r in kit['rows']], [2.0, 1.0])
        self.assertEqual(
            [r['product_id'] for r in kit['rows']],
            [self.roller.id, self.lock.id], "a row with no product is dropped")
        self.assertFalse(any(r['rate_manual'] for r in kit['rows']))
        self.assertFalse(any(r['manual_rate'] for r in kit['rows']))

    def test_save_rates_keeps_only_a_rate_that_was_typed(self):
        kit = self._save(name='Priced set', with_rates=True)
        first, second = kit['rows']
        self.assertTrue(first['rate_manual'])
        self.assertEqual(first['manual_rate'], 70.0)
        self.assertFalse(second['rate_manual'], "a row on the product's cost has no rate to save")
        self.assertEqual(second['manual_rate'], 0.0)
        self.assertEqual(second['list_rate'], 20.0)

    def test_the_panel_type_is_kept(self):
        leaf_type = self.env['aw.leaf.type'].search([], limit=1)
        kit = self.Kit.with_user(self.manager).create_from_rows(
            'Typed set', leaf_type.id, self._rows())
        self.assertEqual(kit['leaf_type_id'], leaf_type.id)

    def test_only_a_manager_can_save_but_everyone_can_read(self):
        with self.assertRaises(AccessError):
            self._save(name='Not allowed', user=self.plain_user)
        kit = self._save(name='Readable set')
        record = self.Kit.with_user(self.plain_user).browse(kit['id'])
        self.assertEqual(record.name, 'Readable set')
        with self.assertRaises(AccessError):
            record.write({'name': 'Renamed by a plain user'})
        with self.assertRaises(AccessError):
            record.unlink()
        names = [k['name'] for k in
                 self.Kit.with_user(self.plain_user)._configurator_payload()]
        self.assertIn('Readable set', names)

    def test_a_name_is_required_and_unique_ignoring_case(self):
        with self.assertRaises(UserError):
            self._save(name='   ')
        self._save(name='Unique set')
        with self.assertRaises(ValidationError):
            self._save(name='unique SET')

    def test_nothing_to_save_is_refused(self):
        with self.assertRaises(UserError):
            self._save(name='Empty set', rows=[{'product_id': False, 'qty': 1}])

    def test_the_configurator_gets_the_sets_and_the_right_to_edit(self):
        kit = self._save(name='Payload set')
        payload = self.Kit._configurator_payload()
        self.assertIn(kit['id'], [k['id'] for k in payload])
        self.assertTrue(self.Kit.with_user(self.manager)._can_edit())
        self.assertFalse(self.Kit.with_user(self.plain_user)._can_edit())
        self.Kit.browse(kit['id']).active = False
        self.assertNotIn(
            kit['id'], [k['id'] for k in self.Kit._configurator_payload()],
            "an archived set is not offered")

    def test_rows_on_a_window_do_not_follow_a_set_that_changes_or_goes(self):
        kit = self._save(name='Copied set')
        design_hw = self.env['aw.design.hardware']
        order = self.env['sale.order'].create({
            'partner_id': self.env['res.partner'].create({'name': 'Kit customer'}).id})
        family, series = seeded_family_series(self.env)
        if not family:
            raise unittest.SkipTest("No family with a system")
        design = order._create_fenestration_position(series, family=family)
        # what the configurator does on picking: copy the set's rows
        design.frame_hardware_ids = [(5, 0, 0)] + design_hw._commands_from(kit['rows'])
        rows = design.frame_hardware_ids
        self.assertEqual(len(rows), 2)
        record = self.Kit.browse(kit['id'])
        record.line_ids[0].qty = 9
        record.line_ids[1].unlink()
        self.assertEqual(sorted(rows.mapped('qty')), [1.0, 2.0])
        record.unlink()
        self.assertEqual(len(design.frame_hardware_ids), 2)
