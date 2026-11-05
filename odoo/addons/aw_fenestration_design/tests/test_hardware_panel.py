# -*- coding: utf-8 -*-
"""Hardware per panel: own rows replace the spec's per-panel lines, the
rate used defaults to the product's cost, and the warning is per panel and
only for a panel type that needs hardware."""
import unittest

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHardwarePerPanel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family = env['aw.window.family'].search([]).filtered(
            lambda f: f.series_ids.filtered('active').filtered(
                lambda s: len(s.leaf_type_ids) >= 2))[:1]
        if not family:
            raise unittest.SkipTest("No family with a system of two panel types")
        series = family.series_ids.filtered('active').filtered(
            lambda s: len(s.leaf_type_ids) >= 2)[0]
        cls.needs, cls.free = series.leaf_type_ids[:2]
        cls.needs.needs_hardware = True
        cls.free.needs_hardware = False
        cls.product = env['product.product'].create({
            'name': 'Test roller',
            'categ_id': env.ref('aw_fenestration_core.product_category_hardware').id,
            'standard_price': 50.0,
        })
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Hardware customer'}).id,
            'aw_default_series_id': series.id,
        })
        cls.design = cls.order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        cls.design.template_id.hardware_line_ids.unlink()
        a = {'width_mm': 1200.0, 'leaf_type_id': cls.needs.id}
        b = {'width_mm': 1200.0, 'leaf_type_id': cls.free.id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [a, b]}]})
        cls.leaf_a, cls.leaf_b = cls.design.row_ids.leaf_ids.sorted('panel_no')

    def _hardware_lines(self, leaf):
        self.design._explode()
        return self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'hardware' and l.panel_no == leaf.panel_no)

    def _row(self, qty=2, **extra):
        return dict({'product_id': self.product.id, 'qty': qty}, **extra)

    def _set(self, leaf, rows):
        leaf.hardware_ids = [(5, 0, 0)] + self.env[
            'aw.design.hardware']._commands_from(rows)

    def test_a_panels_own_rows_cost_qty_times_the_product_cost(self):
        self._set(self.leaf_a, [self._row(2)])
        line = self._hardware_lines(self.leaf_a)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.qty, 2)
        self.assertEqual(line.rate_list, 50.0)
        self.assertEqual(line.unit_cost, 50.0)
        self.assertAlmostEqual(line.line_cost, 100.0)
        self.assertFalse(line.rate_is_manual)

    def test_a_typed_rate_is_manual_noted_and_keeps_the_product_cost(self):
        self._set(self.leaf_a, [self._row(2, rate_manual=True, manual_rate=70.0)])
        line = self._hardware_lines(self.leaf_a)
        self.assertTrue(line.rate_is_manual)
        self.assertEqual(line.rate_list, 50.0)
        self.assertAlmostEqual(line.line_cost, 140.0)
        self.assertIn('manual rate', line.cost_note)

    def test_own_rows_replace_the_specs_lines_for_that_panel_only(self):
        spec = self.design.template_id
        other = self.env['product.product'].create({
            'name': 'Spec handle',
            'categ_id': self.env.ref('aw_fenestration_core.product_category_hardware').id,
            'standard_price': 10.0})
        self.env['aw.hardware.set.line'].create({
            'spec_id': spec.id, 'product_id': other.id, 'qty': 1.0,
            'qty_formula': '1', 'scope': 'panel'})
        self._set(self.leaf_a, [self._row(3)])
        self.design._explode()
        for_a = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'hardware' and l.panel_no == self.leaf_a.panel_no)
        for_b = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'hardware' and l.panel_no == self.leaf_b.panel_no)
        self.assertEqual(for_a.mapped('product_id'), self.product)
        self.assertEqual(for_b.mapped('product_id'), other)
        # no own rows: it follows the spec again
        self._set(self.leaf_a, [])
        self.assertEqual(
            self._hardware_lines(self.leaf_a).mapped('product_id'), other)

    def test_the_warning_is_per_panel_and_only_where_hardware_is_needed(self):
        self._set(self.leaf_a, [])
        self.design._explode()
        text = ' '.join(self.design.check_line_ids.mapped('message'))
        self.assertIn('Panel %s' % self.leaf_a.panel_no, text)
        self.assertIn('no hardware', text)
        self.assertNotIn('Panel %s (%s): no hardware' % (
            self.leaf_b.panel_no, self.free.display_name), text)
        self.assertNotIn('No hardware in this spec', text)
        self._set(self.leaf_a, [self._row(1)])
        self.design._explode()
        self.assertNotIn('Panel %s (%s): no hardware' % (
            self.leaf_a.panel_no, self.needs.display_name),
            ' '.join(self.design.check_line_ids.mapped('message')))

    def test_a_row_without_a_product_is_dropped(self):
        self._set(self.leaf_a, [{'qty': 1}, self._row(1)])
        self.assertEqual(len(self.leaf_a.hardware_ids), 1)

    def test_quick_create_makes_a_priceless_hardware_product_once(self):
        Hardware = self.env['aw.design.hardware']
        made = Hardware._create_product('  Quick latch ')
        product = self.env['product.product'].browse(made['id'])
        self.assertEqual(product.name, 'Quick latch')
        self.assertEqual(product.standard_price, 0.0)
        self.assertTrue(product.categ_id.parent_path.startswith(
            self.env.ref('aw_fenestration_core.product_category_hardware').parent_path))
        self.assertEqual(Hardware._create_product('quick latch')['id'], product.id)
        self.assertFalse(Hardware._create_product('   '))

    def test_the_specs_set_comes_as_calculated_rows_and_only_for_a_following_panel(self):
        spec = self.design.template_id
        self.env['aw.hardware.set.line'].create({
            'spec_id': spec.id, 'product_id': self.product.id, 'qty': 2.0,
            'qty_formula': '2', 'scope': 'panel'})
        self.design._explode()
        rows = self.design.hardware_from_spec(self.leaf_a.panel_no)
        self.assertEqual([(r['product_id'], r['qty']) for r in rows],
                         [(self.product.id, 2.0)])
        self._set(self.leaf_a, [self._row(1)])
        with self.assertRaises(UserError):
            self.design.hardware_from_spec(self.leaf_a.panel_no)

    def test_the_payload_round_trips_a_panels_hardware(self):
        self._set(self.leaf_a, [self._row(2, rate_manual=True, manual_rate=70.0)])
        data = self.design.get_configurator_data()
        leaf = data['rows'][0]['leaves'][0]
        self.assertEqual(leaf['hardware'][0]['qty'], 2.0)
        self.assertTrue(leaf['hardware'][0]['rate_manual'])
        self.assertIn(self.product.id, [p['id'] for p in data['hardware_products']])
        self.design.save_layout({'header': data['header'], 'rows': data['rows']})
        leaf_a = self.design.row_ids.leaf_ids.sorted('panel_no')[0]
        self.assertEqual(leaf_a.hardware_ids.manual_rate, 70.0)

    def test_fixed_and_mesh_start_without_the_flag_and_it_is_seeded_once(self):
        Type = self.env['aw.leaf.type']
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.needs_hardware_seeded', '')
        Type.search([('code', 'in', ('FIXED', 'MESH'))]).write(
            {'needs_hardware': True})
        Type._seed_needs_hardware()
        for t in Type.search([('code', 'in', ('FIXED', 'MESH'))]):
            self.assertFalse(t.needs_hardware)
        Type.search([('code', '=', 'FIXED')]).needs_hardware = True
        self.assertEqual(Type._seed_needs_hardware(), 0)       # once
        self.assertTrue(Type.search([('code', '=', 'FIXED')]).needs_hardware)

    def test_following_the_spec_then_saving_gives_the_per_panel_warning(self):
        """The Follow the spec button clears the panel's rows in the layout
        it sends; saving explodes again, so the warning must come back."""
        self._set(self.leaf_a, [self._row(1)])
        data = self.design.get_configurator_data()
        data['rows'][0]['leaves'][0]['hardware'] = []
        self.design.save_layout({'header': data['header'], 'rows': data['rows']})
        leaf = self.design.row_ids.leaf_ids.sorted('panel_no')[0]
        self.assertFalse(leaf.hardware_ids)
        text = ' '.join(self.design.check_line_ids.mapped('message'))
        self.assertIn('Panel %s (%s): no hardware' % (
            leaf.panel_no, self.needs.display_name), text)

    def test_a_typed_rate_is_an_info_note_not_a_warning(self):
        self._set(self.leaf_a, [self._row(2, rate_manual=True, manual_rate=70.0)])
        self.design._explode()
        infos = self.design.check_line_ids.filtered(lambda c: c.level == 'info')
        self.assertTrue(any('manual rate' in c.message and '70' in c.message
                            and '50' in c.message for c in infos))
        warnings = self.design.check_line_ids.filtered(
            lambda c: c.level == 'warning')
        self.assertFalse([c for c in warnings if 'manual rate' in c.message])
        self.assertFalse([c for c in warnings if 'stand-in' in c.message])
        self.assertEqual(self.design.check_warning_count,
                         len(warnings))

    # -- Checks as links ---------------------------------------------------------
    def _checks(self, text):
        return self.design.check_line_ids.filtered(lambda c: text in c.message)

    def test_the_no_hardware_warning_leads_to_the_panel_by_number(self):
        self._set(self.leaf_a, [])
        self.design._explode()
        check = self._checks('no hardware')[:1]
        self.assertEqual(check.target_kind, 'hardware')
        self.assertEqual(check.panel_no, self.leaf_a.panel_no)
        self.assertFalse(check.target_res_id)       # no row id to go stale

    def test_a_link_is_the_same_after_a_recompute(self):
        self._set(self.leaf_a, [])
        self.design._explode()
        before = [(c.target_kind, c.panel_no, c.target_key)
                  for c in self.design.check_line_ids]
        self.design.action_recompute_cut_list()
        after = [(c.target_kind, c.panel_no, c.target_key)
                 for c in self.design.check_line_ids]
        self.assertEqual(sorted(before), sorted(after))

    def test_glass_of_size_zero_leads_to_the_panels_glass(self):
        spec = self.design.template_id
        for record in (spec, spec.window_type_id):
            record.write({f: False for f in (
                'glass_fixed_w', 'glass_fixed_h', 'glass_sash_w',
                'glass_sash_h', 'mesh_w', 'mesh_h')})
        self._set(self.leaf_a, [self._row(1)])
        self.design._explode()
        check = self._checks('glass size is 0')[:1]
        self.assertEqual((check.target_kind, check.panel_no),
                         ('glass', self.leaf_a.panel_no))

    def test_a_no_cost_warning_names_and_opens_the_product(self):
        free = self.env['product.product'].create({
            'name': 'Free latch',
            'categ_id': self.env.ref('aw_fenestration_core.product_category_hardware').id,
            'standard_price': 0.0})
        self._set(self.leaf_a, [{'product_id': free.id, 'qty': 1}])
        self.design._explode()
        check = self._checks('Free latch has no cost price')[:1]
        self.assertTrue(check)
        self.assertEqual(
            (check.target_kind, check.target_model, check.target_res_id),
            ('record', 'product.product', free.id))

    def test_a_typed_rate_note_leads_to_the_panels_hardware(self):
        self._set(self.leaf_a, [self._row(1, rate_manual=True, manual_rate=70.0)])
        self.design._explode()
        check = self._checks('manual rate')[:1]
        self.assertEqual((check.level, check.target_kind, check.panel_no),
                         ('info', 'hardware', self.leaf_a.panel_no))

    def test_the_payload_carries_the_target(self):
        self._set(self.leaf_a, [])
        self.design._explode()
        checks = self.design.get_configurator_data()['checks']
        mine = [c for c in checks if 'no hardware' in c['message']]
        self.assertTrue(mine)
        for key in ('target_kind', 'panel_no', 'target_key', 'target_model',
                    'target_res_id'):
            self.assertIn(key, mine[0])
        self.assertEqual(mine[0]['target_kind'], 'hardware')
