# -*- coding: utf-8 -*-
"""Retire the old flat glass: 11 saved specs and the 11 flat products.

A panel's glass is a stack now, so the saved specs and the flat glass
products they pointed at are dead data. This runs ONCE, from a data
function, in SQL where the model is already gone from the registry (the
model's class no longer exists when this runs):

1. VERIFY that nothing points at them: no design, panel or BOM line, no
   other reference to the products (a generic scan of every foreign key,
   so a table nobody remembered cannot be missed), and that every profile
   spec that had a default glass already has a default stack. If anything
   does, NOTHING is deleted, the findings are logged and kept in a
   parameter, and the next upgrade tries again. It never fails the upgrade.
2. Clear the profile specs' default-glass pointer and DROP the four
   `glass_spec_id` columns first. Odoo drops a removed field's column only
   at the end of the upgrade, and the restricting foreign keys on those
   columns would block deleting the specs until then.
3. Delete the specs, their chatter and external ids, then the 11 products
   (through the ORM, so their own messages and external ids go too), then
   the two categories only the old products used (DGU and Toughened).

Fenestration / Glass, the Glass Sheet product, the glass types and rates,
the stacks, the extras and the options are not touched.
"""
import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

DONE_PARAM = 'aw_fenestration.flat_glass_retired'
BLOCKED_PARAM = 'aw_fenestration.flat_glass_retire_blocked'

# Tables that may legitimately hold a row pointing at a product being
# deleted, because the delete handles them (cascade or set null).
EXPECTED_PRODUCT_REFERRERS = {
    'aw_glass_spec', 'product_product', 'product_taxes_rel',
    'product_supplier_taxes_rel', 'product_value',
}
POINTER_COLUMNS = (
    ('aw_window_template', 'glass_spec_id'),
    ('aw_design', 'glass_spec_id'),
    ('aw_design_leaf', 'glass_spec_id'),
    ('aw_design_bom_line', 'glass_spec_id'),
)
OLD_CATEGORIES = ('product_category_glass_dgu', 'product_category_glass_toughened')


class AwGlassType(models.Model):
    _inherit = 'aw.glass.type'

    @api.model
    def _retire_flat_glass(self):
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(DONE_PARAM):
            return False
        try:
            with self.env.cr.savepoint():
                return self._do_retire_flat_glass()
        except Exception:
            _logger.exception("aw_fenestration_core: flat glass retire failed")
            return False

    @api.model
    def _do_retire_flat_glass(self):
        cr = self.env.cr
        param = self.env['ir.config_parameter'].sudo()

        def exists(table):
            cr.execute("SELECT to_regclass(%s)", (table,))
            return cr.fetchone()[0] is not None

        def column(table, name):
            cr.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s", (table, name))
            return bool(cr.fetchone())

        def count(sql, args):
            cr.execute(sql, args)
            return cr.fetchone()[0]

        if not exists('aw_glass_spec'):
            param.set_param(DONE_PARAM, json.dumps({'note': 'no spec table'}))
            return False
        cr.execute("SELECT id, product_id FROM aw_glass_spec")
        rows = cr.fetchall()
        spec_ids = [r[0] for r in rows]
        variant_ids = [r[1] for r in rows if r[1]]
        template_ids = []
        if variant_ids:
            cr.execute(
                "SELECT DISTINCT product_tmpl_id FROM product_product "
                "WHERE id = ANY(%s)", (variant_ids,))
            template_ids = [r[0] for r in cr.fetchall()]

        # 1. verify ---------------------------------------------------------
        problems = {}
        for table, name in POINTER_COLUMNS[1:]:
            if exists(table) and column(table, name):
                n = count('SELECT count(*) FROM "%s" WHERE "%s" = ANY(%%s)'
                          % (table, name), (spec_ids,))
                if n:
                    problems['%s.%s' % (table, name)] = n
        if exists('aw_design_bom_line') and variant_ids:
            n = count('SELECT count(*) FROM aw_design_bom_line '
                      'WHERE product_id = ANY(%s)', (variant_ids,))
            if n:
                problems['aw_design_bom_line.product_id'] = n
        for target, ids in (('product_product', variant_ids),
                            ('product_template', template_ids)):
            if not ids:
                continue
            cr.execute("""
                SELECT c.conrelid::regclass::text, a.attname
                  FROM pg_constraint c
                  JOIN pg_attribute a ON a.attrelid = c.conrelid
                                     AND a.attnum = ANY(c.conkey)
                 WHERE c.contype = 'f' AND c.confrelid = %s::regclass""",
                (target,))
            for table, name in cr.fetchall():
                if table in EXPECTED_PRODUCT_REFERRERS:
                    continue
                n = count('SELECT count(*) FROM "%s" WHERE "%s" = ANY(%%s)'
                          % (table, name), (ids,))
                if n:
                    problems['%s.%s' % (table, name)] = n
        # every profile spec that had a default glass must already have a
        # default stack, or deleting the pointer loses its default.
        unstacked = []
        if exists('aw_window_template') and column(
                'aw_window_template', 'glass_spec_id'):
            cr.execute("""
                SELECT t.id FROM aw_window_template t
                 WHERE t.glass_spec_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM aw_glass_part p
                                    WHERE p.template_id = t.id)""")
            unstacked = [r[0] for r in cr.fetchall()]
            if unstacked:
                problems['profile specs without a default stack'] = unstacked
        if problems:
            param.set_param(BLOCKED_PARAM, json.dumps(problems))
            _logger.error(
                "aw_fenestration_core: old flat glass NOT removed, something "
                "still points at it: %s", problems)
            return False

        # 2. clear the pointers and drop their columns ------------------------
        report = {'specs': len(spec_ids), 'products': len(variant_ids),
                  'templates': len(template_ids)}
        if exists('aw_window_template') and column(
                'aw_window_template', 'glass_spec_id'):
            cr.execute("UPDATE aw_window_template SET glass_spec_id = NULL "
                       "WHERE glass_spec_id IS NOT NULL")
            report['spec_pointers_cleared'] = cr.rowcount
        for table, name in POINTER_COLUMNS:
            if exists(table) and column(table, name):
                cr.execute('ALTER TABLE "%s" DROP COLUMN "%s" CASCADE'
                           % (table, name))

        # 3. delete -----------------------------------------------------------
        if spec_ids:
            cr.execute("DELETE FROM mail_message WHERE model = 'aw.glass.spec' "
                       "AND res_id = ANY(%s)", (spec_ids,))
            cr.execute("DELETE FROM mail_followers WHERE res_model = "
                       "'aw.glass.spec' AND res_id = ANY(%s)", (spec_ids,))
            cr.execute("DELETE FROM ir_attachment WHERE res_model = "
                       "'aw.glass.spec' AND res_id = ANY(%s)", (spec_ids,))
        cr.execute("DELETE FROM ir_model_data WHERE model = 'aw.glass.spec'")
        cr.execute("DROP TABLE IF EXISTS aw_glass_spec CASCADE")
        templates = self.env['product.template'].with_context(
            active_test=False).browse(template_ids).exists()
        templates.unlink()
        report['products_deleted'] = len(templates)

        removed = []
        for name in OLD_CATEGORIES:
            category = self.env.ref('aw_fenestration_core.' + name,
                                    raise_if_not_found=False)
            if not category:
                continue
            busy = self.env['product.template'].with_context(
                active_test=False).search_count(
                    [('categ_id', 'child_of', category.id)])
            if busy or category.child_id:
                report.setdefault('categories_kept', []).append(category.complete_name)
                continue
            removed.append(category.complete_name)
            category.unlink()
        report['categories_deleted'] = removed
        param.set_param(DONE_PARAM, json.dumps(report))
        _logger.info("aw_fenestration_core: old flat glass removed: %s", report)
        return report
