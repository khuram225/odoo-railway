# -*- coding: utf-8 -*-
"""The one-time removal of the old flat glass: 11 saved specs and 11 products.

The old table and pointer columns are rebuilt here in SQL, as they were on
production (the model is gone from the registry, so the ORM cannot make
them), and the real migration is run against them."""
import json

from odoo.tests import TransactionCase, tagged

POINTERS = ('aw_window_template', 'aw_design', 'aw_design_leaf',
            'aw_design_bom_line')


@tagged('post_install', '-at_install')
class TestRetireFlatGlass(TransactionCase):

    def setUp(self):
        super().setUp()
        env = self.env
        cr = env.cr
        self.param = env['ir.config_parameter'].sudo()
        self.param.set_param('aw_fenestration.flat_glass_retired', '')
        self.param.set_param('aw_fenestration.flat_glass_retire_blocked', '')
        cr.execute("""
            CREATE TABLE aw_glass_spec (
                id serial PRIMARY KEY, name varchar,
                product_id integer NOT NULL
                    REFERENCES product_product(id) ON DELETE RESTRICT)""")
        for table in POINTERS:
            cr.execute(
                'ALTER TABLE "%s" ADD COLUMN glass_spec_id integer '
                'REFERENCES aw_glass_spec(id) ON DELETE RESTRICT' % table)
        glass = env.ref('aw_fenestration_core.product_category_glass')
        self.templates = env['product.template'].create([
            {'name': 'Old flat glass %s' % n, 'categ_id': glass.id}
            for n in (1, 2)])
        self.spec_ids = []
        for template in self.templates:
            cr.execute(
                "INSERT INTO aw_glass_spec (name, product_id) "
                "VALUES (%s, %s) RETURNING id",
                (template.name, template.product_variant_id.id))
            self.spec_ids.append(cr.fetchone()[0])

    def _exists(self, table):
        self.env.cr.execute("SELECT to_regclass(%s)", (table,))
        return self.env.cr.fetchone()[0] is not None

    def _column(self, table, name):
        self.env.cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s", (table, name))
        return bool(self.env.cr.fetchone())

    def test_nothing_points_at_it_so_it_goes(self):
        ids = self.templates.ids
        report = self.env['aw.glass.type']._do_retire_flat_glass()
        self.assertEqual(report['specs'], 2)
        self.assertEqual(report['products_deleted'], 2)
        self.assertFalse(self.env['product.template'].browse(ids).exists())
        self.assertFalse(self._exists('aw_glass_spec'))
        for table in POINTERS:
            self.assertFalse(self._column(table, 'glass_spec_id'), table)
        done = json.loads(self.param.get_param('aw_fenestration.flat_glass_retired'))
        self.assertEqual(done['specs'], 2)
        # what stays
        self.assertTrue(self.env['aw.glass.type']._glass_sheet())
        self.assertTrue(self.env.ref(
            'aw_fenestration_core.product_category_glass'))
        # once: a second call does nothing
        self.assertFalse(self.env['aw.glass.type']._retire_flat_glass())

    def test_a_profile_spec_pointer_is_cleared_when_it_has_a_stack(self):
        template = self.env['aw.window.template'].search([], limit=1)
        if not template:
            self.skipTest("no profile spec in this database")
        template.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])
        self.env.cr.execute(
            "UPDATE aw_window_template SET glass_spec_id = %s WHERE id = %s",
            (self.spec_ids[0], template.id))
        report = self.env['aw.glass.type']._do_retire_flat_glass()
        self.assertEqual(report['spec_pointers_cleared'], 1)
        self.assertTrue(template.glass_part_ids)         # its stack stays

    def test_a_profile_spec_without_a_stack_blocks_everything(self):
        template = self.env['aw.window.template'].search([], limit=1)
        if not template:
            self.skipTest("no profile spec in this database")
        template.glass_part_ids.unlink()
        self.env.cr.execute(
            "UPDATE aw_window_template SET glass_spec_id = %s WHERE id = %s",
            (self.spec_ids[0], template.id))
        ids = self.templates.ids
        self.assertFalse(self.env['aw.glass.type']._do_retire_flat_glass())
        blocked = json.loads(self.param.get_param(
            'aw_fenestration.flat_glass_retire_blocked'))
        self.assertIn('profile specs without a default stack', blocked)
        # nothing was deleted or dropped
        self.assertEqual(len(self.env['product.template'].browse(ids).exists()), 2)
        self.assertTrue(self._exists('aw_glass_spec'))
        self.assertTrue(self._column('aw_design', 'glass_spec_id'))
        self.assertFalse(self.param.get_param('aw_fenestration.flat_glass_retired'))

    def test_any_other_reference_to_the_products_blocks_everything(self):
        order = self.env['sale.order'].create({
            'partner_id': self.env['res.partner'].create(
                {'name': 'Retire customer'}).id,
            'order_line': [(0, 0, {
                'product_id': self.templates[0].product_variant_id.id})]})
        self.assertTrue(order)
        ids = self.templates.ids
        self.assertFalse(self.env['aw.glass.type']._do_retire_flat_glass())
        blocked = json.loads(self.param.get_param(
            'aw_fenestration.flat_glass_retire_blocked'))
        self.assertIn('sale_order_line.product_id', blocked)
        self.assertEqual(len(self.env['product.template'].browse(ids).exists()), 2)

    def test_the_two_old_categories_go_only_when_empty(self):
        env = self.env
        parent = env.ref('aw_fenestration_core.product_category_glass')
        empty = env['product.category'].create(
            {'name': 'DGU (test)', 'parent_id': parent.id})
        busy = env['product.category'].create(
            {'name': 'Toughened (test)', 'parent_id': parent.id})
        env['product.template'].create(
            {'name': 'Something else', 'categ_id': busy.id})
        for name, record in (('product_category_glass_dgu', empty),
                             ('product_category_glass_toughened', busy)):
            env['ir.model.data'].create({
                'module': 'aw_fenestration_core', 'name': name,
                'model': 'product.category', 'res_id': record.id})
        report = env['aw.glass.type']._do_retire_flat_glass()
        self.assertEqual(report['categories_deleted'], ['Fenestration / Glass / DGU (test)'])
        self.assertEqual(report['categories_kept'], ['Fenestration / Glass / Toughened (test)'])
        self.assertFalse(empty.exists())
        self.assertTrue(busy.exists())
