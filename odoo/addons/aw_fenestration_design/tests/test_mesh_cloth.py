# -*- coding: utf-8 -*-
"""Mesh cloth: a product per active mesh type, costed by the sqft."""
import unittest

from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_core.models.part_structure import (
    PART_LABELS, SCOPE_LABELS)


@tagged('post_install', '-at_install')
class TestMeshCloth(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Mesh = env['aw.mesh.type']
        cls.Mesh._seed_cloth_products()
        cls.zig = cls.Mesh.search([('mechanism', '=', 'zigzag')], limit=1)
        if not (cls.zig and cls.zig.cloth_product_id):
            raise unittest.SkipTest("No active zig-zag mesh type here")
        family = env['aw.window.family'].search([]).filtered(
            lambda f: f.series_ids.filtered('active').filtered(
                lambda s: s.leaf_type_ids))[:1]
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        series = family.series_ids.filtered('active').filtered(
            lambda s: s.leaf_type_ids)[0]
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Mesh customer'}).id,
            'aw_default_series_id': series.id,
        })
        cls.design = cls.order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 762.0, 'height_mm': 2438.0})
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 2438.0, 'leaves': [{
                'width_mm': 762.0, 'leaf_type_id': series.leaf_type_ids[0].id,
                'mesh_type_id': cls.zig.id}]}]})
        cls.leaf = cls.design.row_ids.leaf_ids[:1]
        cls.product = cls.zig.cloth_product_id
        # no deduction rules of the spec: the window type's (PW - 10, PH - 10)
        cls.design.template_id.write({'mesh_w': 'PW - 10', 'mesh_h': 'PH - 10'})

    def _line(self):
        self.design._explode()
        return self.design.bom_line_ids.filtered(lambda l: l.kind == 'mesh')[:1]

    # -- products ------------------------------------------------------------------
    def test_the_four_active_types_get_a_named_product_in_the_category(self):
        names = {
            m.mechanism: m.cloth_product_id.name
            for m in self.Mesh.search([('active', '=', True)])
            if m.cloth_product_id}
        for mechanism, label in (('fixed', 'Fixed'), ('hinged', 'Hinged'),
                                 ('zigzag', 'Zig-zag'), ('roller', 'Roller')):
            if mechanism in names:
                self.assertEqual(names[mechanism], 'Mesh cloth - %s' % label)
        product = self.product
        category = self.env.ref('aw_fenestration_core.product_category_mesh_cloth')
        self.assertTrue(product.categ_id.parent_path.startswith(category.parent_path))
        self.assertFalse(product.sale_ok)
        self.assertEqual(product.list_price, 0.0)
        self.assertTrue(product.product_tmpl_id.aw_is_mesh_cloth)

    def test_the_seed_never_overwrites_and_is_idempotent(self):
        other = self.env['product.product'].create({
            'name': 'My own cloth',
            'categ_id': self.env.ref('aw_fenestration_core.product_category_mesh_cloth').id})
        self.zig.cloth_product_id = other
        self.Mesh._seed_cloth_products()
        self.assertEqual(self.zig.cloth_product_id, other)
        self.assertEqual(self.Mesh._seed_cloth_products(), 0)

    def test_an_existing_product_of_the_name_is_adopted(self):
        self.zig.cloth_product_id = False
        before = self.product
        self.Mesh._seed_cloth_products()
        self.assertEqual(self.zig.cloth_product_id, before)

    def test_an_inactive_type_gets_no_product(self):
        pleated = self.Mesh.with_context(active_test=False).search(
            [('mechanism', '=', 'pleated')], limit=1)
        if not pleated:
            self.skipTest("no pleated type")
        pleated.write({'active': False, 'cloth_product_id': False})
        self.Mesh._seed_cloth_products()
        self.assertFalse(pleated.cloth_product_id)

    # -- cost -----------------------------------------------------------------------
    def test_a_752_by_2428_cloth_at_40_costs_786(self):
        self.product.standard_price = 40.0
        line = self._line()
        self.assertEqual((round(line.glass_w), round(line.glass_h)), (752, 2428))
        self.assertAlmostEqual(line.area_sqft, 19.654, 2)
        self.assertEqual(line.qty, 1)                   # the piece count
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.rate_list, 40.0)
        self.assertEqual(line.unit_cost, 40.0)
        self.assertAlmostEqual(line.line_cost, 786.0, delta=0.5)
        self.assertAlmostEqual(line.line_cost, 786.15, places=1)

    def test_no_rate_is_one_warning_naming_the_product_and_opening_it(self):
        self.product.standard_price = 0.0
        self._line()
        check = self.design.check_line_ids.filtered(
            lambda c: 'has no cost per sqft' in c.message)[:1]
        self.assertTrue(check)
        self.assertIn(self.product.display_name, check.message)
        self.assertEqual(
            (check.target_kind, check.target_model, check.target_res_id),
            ('record', 'product.product', self.product.id))

    def test_a_typed_rate_is_manual_noted_and_keeps_the_list_rate(self):
        self.product.standard_price = 40.0
        self.leaf.write({'mesh_rate_manual': True, 'mesh_manual_rate': 50.0})
        line = self._line()
        self.assertTrue(line.rate_is_manual)
        self.assertEqual(line.rate_list, 40.0)
        self.assertEqual(line.unit_cost, 50.0)
        self.assertAlmostEqual(line.line_cost, 50.0 * line.area_sqft, 2)
        info = self.design.check_line_ids.filtered(lambda c: c.level == 'info')
        self.assertTrue(any('manual rate' in c.message for c in info))
        self.assertFalse(self.design.check_line_ids.filtered(
            lambda c: c.level == 'warning' and 'manual rate' in c.message))

    def test_the_payload_carries_the_quantity_in_sqft_and_the_cloth_cost(self):
        self.product.standard_price = 40.0
        self._line()
        data = self.design.get_configurator_data()
        mesh = data['bom']['mesh'][0]
        self.assertAlmostEqual(mesh['area_sqft'], 19.654, 2)
        entry = [m for m in data['mesh_types'] if m['id'] == self.zig.id]
        if entry:
            self.assertEqual(entry[0]['cloth_cost'], 40.0)

    # -- labels ---------------------------------------------------------------------
    def test_the_labels_say_mesh_panel_and_cloth(self):
        self.assertEqual(SCOPE_LABELS['mesh'], 'Mesh panel')
        self.assertEqual(PART_LABELS['mesh_cloth'], 'Cloth')
        self.assertEqual(PART_LABELS['mesh_frame'], 'Frame')
        self.assertEqual(PART_LABELS['mesh_bead'], 'Bead')

    def test_a_mesh_types_own_parts_are_not_costed_as_cloth(self):
        self.product.standard_price = 40.0
        self.design._explode()
        parts = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'mesh' and not (l.glass_w or l.glass_h))
        for part in parts:
            self.assertEqual(part.area_sqft, 0.0)
            self.assertNotIn('per sqft', part.cost_note or '')

    # -- the old type lines --------------------------------------------------------
    def _generic_cloth(self):
        return self.env['product.product'].create({
            'name': 'Mesh cloth',
            'categ_id': self.env.ref('aw_fenestration_core.product_category_fenestration').id})

    def _type_line(self, product, formula='OW * OH / 1000000', **extra):
        return self.env['aw.mesh.type.line'].create(dict({
            'mesh_type_id': self.zig.id, 'product_id': product.id,
            'qty_formula': formula}, **extra))

    def test_a_zig_zag_panel_has_exactly_one_cloth_cost_line(self):
        self.product.standard_price = 40.0
        self._type_line(self.product)               # a type line for the cloth too
        self.design._explode()
        cloth = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'mesh' and l.product_id == self.product
            and l.panel_no == self.leaf.panel_no)
        self.assertEqual(len(cloth), 1)
        self.assertAlmostEqual(cloth.line_cost, 786.0, delta=0.5)
        self.assertEqual(
            len(self.design.bom_line_ids.filtered(
                lambda l: l.kind == 'mesh' and l.line_cost)), 1)

    def test_the_generic_cloth_line_moves_onto_the_types_cloth_product(self):
        line = self._type_line(self._generic_cloth())
        result = self.Mesh._move_cloth_lines()
        self.assertGreaterEqual(result['moved'], 1)
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(self.Mesh._move_cloth_lines()['moved'], 0)   # idempotent
        # and the panel still has one cloth cost
        self.design._explode()
        self.assertEqual(len(self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'mesh' and l.product_id == self.product
            and l.panel_no == self.leaf.panel_no)), 1)

    def test_a_line_that_is_not_clearly_the_cloth_is_left_and_counted(self):
        generic = self._generic_cloth()
        other = self._type_line(generic, formula='2 * OW / 1000')
        conditioned = self._type_line(generic, condition_formula='N > 1')
        result = self.Mesh._move_cloth_lines()
        self.assertGreaterEqual(result['unclear'], 2)
        self.assertEqual(other.product_id, generic)
        self.assertEqual(conditioned.product_id, generic)

    def test_a_type_with_no_cloth_product_keeps_its_line_as_a_part(self):
        pleated = self.Mesh.with_context(active_test=False).search(
            [('mechanism', '=', 'pleated')], limit=1)
        if not pleated:
            self.skipTest("no pleated type")
        pleated.write({'active': False, 'cloth_product_id': False})
        generic = self._generic_cloth()
        line = self.env['aw.mesh.type.line'].create({
            'mesh_type_id': pleated.id, 'product_id': generic.id,
            'qty_formula': 'OW * OH / 1000000'})
        result = self.Mesh._move_cloth_lines()
        self.assertGreaterEqual(result['waiting'], 1)
        self.assertEqual(line.product_id, generic)
