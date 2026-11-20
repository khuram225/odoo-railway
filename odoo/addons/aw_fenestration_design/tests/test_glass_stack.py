# -*- coding: utf-8 -*-
"""Glass, one product per panel (G1): the product a panel is glazed with,
its rate (the newer of the vendor's list rate and the product's latest rate,
or one typed for the panel), the size from the deduction rules or typed, and
the migration from the old build-up. The old tables are still here (G2
removes them); what they keep is tested at the end."""
import unittest
from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

SQFT_PER_SQM = 10.7639104
MM_PER_FOOT = 304.8
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestGlassStack(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        cls.Type = env['aw.glass.type']
        cls.Type._seed_glass_types()
        env['aw.glass.option']._seed_glass_options()
        cls.Type._seed_glass_sheet()
        cls.vendor = env['res.partner'].create({'name': 'Glass vendor (test)'})
        cls.clear = cls.Type.search([('name', '=', 'Clear')])
        cls.category = env.ref('aw_fenestration_core.product_category_glass')
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Glass customer'}).id,
            'aw_default_series_id': series.id,
            'aw_glass_vendor_id': cls.vendor.id,
        })
        cls.design = cls.order._create_fenestration_position(
            series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        cls.leaves = cls.design.row_ids.leaf_ids.sorted('panel_no')
        cls.unit = cls._product('Unit 6+12+6', 400.0, date(2000, 1, 1))
        cls.other = cls._product('Unit 8+8+8', 600.0, date(2000, 1, 1))

    @classmethod
    def _product(cls, name, rate=0.0, rate_date=False):
        return cls.env['product.product'].create({
            'name': name, 'categ_id': cls.category.id, 'type': 'consu',
            'aw_glass_latest_rate': rate,
            'aw_glass_latest_rate_date': rate_date})

    def setUp(self):
        super().setUp()
        self.leaves.write({
            'glass_product_id': False, 'glass_choose': False,
            'glass_size_manual': False, 'glass_rate_manual': False,
            'glass_manual_rate': 0.0, 'glass_suggested': False,
            'glass_chosen': False})
        self.design.write({'glass_product_id': False, 'glass_choose': False})
        self.design.template_id.glass_product_id = False

    def _lines(self, panel=None):
        self.design._explode()
        lines = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'glass' and l.glass_part_kind == 'unit')
        return lines.filtered(lambda l: l.panel_no == panel) if panel else lines

    # -- which product -------------------------------------------------------------
    def test_a_panel_follows_the_window_which_follows_the_spec(self):
        spec = self.design.template_id
        spec.glass_product_id = self.unit
        self.assertEqual(self.design._glass_product_for(self.leaves[0]), self.unit)
        self.design.glass_product_id = self.other
        self.assertEqual(self.design._glass_product_for(self.leaves[0]), self.other)
        self.leaves[0].glass_product_id = self.unit
        self.assertEqual(self.design._glass_product_for(self.leaves[0]), self.unit)
        self.assertEqual(self.design._glass_product_for(self.leaves[1]), self.other)

    def test_a_panel_marked_to_choose_does_not_follow(self):
        self.design.glass_product_id = self.unit
        self.leaves[0].glass_choose = True
        self.assertFalse(self.design._glass_product_for(self.leaves[0]))
        self.assertEqual(self.design._glass_product_for(self.leaves[1]), self.unit)

    def test_one_panel_can_differ_and_the_others_do_not(self):
        self.design.glass_product_id = self.unit
        self.leaves[0].glass_product_id = self.other
        # read each line before the next explosion replaces the records
        lines = self._lines()
        by_panel = {l.panel_no: l.product_id for l in lines}
        self.assertEqual(len(lines), 2, "one glass line per panel")
        self.assertEqual(by_panel[self.leaves[0].panel_no], self.other)
        self.assertEqual(by_panel[self.leaves[1].panel_no], self.unit)

    def test_a_new_window_starts_from_the_spec_default(self):
        spec = self.design.template_id
        spec.glass_product_id = self.unit
        fresh = self.order._create_fenestration_position(
            spec.window_type_id, family=self.design.family_id)
        fresh.write({'template_id': spec.id, 'width_mm': 2400.0,
                     'height_mm': 1800.0})
        fresh._apply_spec(force=True)
        self.assertFalse(fresh.glass_product_id)
        self.assertEqual(fresh._glass_product_for(), self.unit)

    # -- rates ---------------------------------------------------------------------------
    def test_a_unit_costs_its_latest_rate_times_the_area(self):
        self.design.glass_product_id = self.unit
        line = self._lines(self.leaves[0].panel_no)
        self.assertEqual(line.rate_list, 400.0)
        self.assertFalse(line.rate_is_manual)
        self.assertAlmostEqual(
            line.line_cost, 400.0 * line.area_sqm * SQFT_PER_SQM, 2)
        self.assertGreater(line.line_cost, 0.0)

    def test_the_newer_of_the_list_rate_and_the_latest_rate_is_used(self):
        Rate = self.env['aw.glass.rate']
        Rate.create({'glass_type_id': self.clear.id, 'thickness_mm': 6,
                     'vendor_id': self.vendor.id, 'price': 300.0,
                     'date_from': date(2024, 1, 1)})
        product = self._product('Sheet-like unit', 450.0, date(2025, 1, 1))
        today = date(2026, 11, 1)
        with patch.object(type(product), '_aw_glass_key',
                          return_value=(self.clear, 6.0)):
            # the typed rate is newer
            self.assertEqual(
                self.design._glass_unit_rate(product, today, self.vendor),
                (450.0, date(2025, 1, 1), 'latest'))
            # the list rate is newer
            product.aw_glass_latest_rate_date = date(2023, 1, 1)
            self.assertEqual(
                self.design._glass_unit_rate(product, today, self.vendor),
                (300.0, date(2024, 1, 1), 'list'))
            # a tie goes to the typed one
            product.aw_glass_latest_rate_date = date(2024, 1, 1)
            self.assertEqual(
                self.design._glass_unit_rate(product, today, self.vendor)[2],
                'latest')
            # a typed rate dated after the day costed is not in force yet
            product.aw_glass_latest_rate_date = date(2027, 1, 1)
            self.assertEqual(
                self.design._glass_unit_rate(product, today, self.vendor)[2],
                'list')

    def test_no_rate_at_all_is_named_not_guessed(self):
        bare = self._product('Unpriced unit')
        self.design.glass_product_id = bare
        line = self._lines(self.leaves[0].panel_no)
        self.assertEqual(line.line_cost, 0.0)
        self.assertEqual(line.cost_note, 'Unpriced unit: no rate')

    def test_a_rate_typed_on_the_panel_is_manual_and_reset_returns_to_the_list(self):
        self.design.glass_product_id = self.unit
        self.leaves[0].write({'glass_rate_manual': True,
                              'glass_manual_rate': 0.0})
        line = self._lines(self.leaves[0].panel_no)
        self.assertTrue(line.rate_is_manual)
        self.assertEqual(line.line_cost, 0.0)
        self.assertEqual(line.rate_list, 400.0)
        self.assertIn('manual rate 0 (list rate 400)', line.cost_note)
        self.leaves[0].write({'glass_rate_manual': False})
        line = self._lines(self.leaves[0].panel_no)
        self.assertGreater(line.line_cost, 0.0)
        self.assertFalse(line.cost_note)

    def test_a_typed_glass_rate_is_an_info_note_not_a_stand_in_warning(self):
        self.design.glass_product_id = self.unit
        self.leaves[0].write({'glass_rate_manual': True,
                              'glass_manual_rate': 55.0})
        self.design._explode()
        checks = self.design.check_line_ids
        self.assertTrue(checks.filtered(
            lambda c: c.level == 'info' and 'manual rate' in c.message))
        self.assertFalse(checks.filtered(
            lambda c: c.level == 'warning' and 'stand-in' in c.message))

    def test_extras_prefer_the_vendors_own_row(self):
        Extra = self.env['aw.glass.extra']
        Extra.create({'kind': 'spacer', 'name': 'Warm edge', 'rate': 8.0,
                      'unit': 'per_ft', 'date_from': date(2000, 1, 1)})
        Extra.create({'kind': 'spacer', 'name': 'Warm edge', 'rate': 9.0,
                      'unit': 'per_ft', 'date_from': date(2000, 1, 1),
                      'vendor_id': self.vendor.id})
        today = date(2026, 11, 1)
        self.assertEqual(
            Extra._rate_for('spacer', 'warm EDGE', today, self.vendor).rate, 9.0)
        self.assertEqual(Extra._rate_for('spacer', 'Warm edge', today).rate, 8.0)
        self.assertFalse(Extra._rate_for('spacer', 'Warm edge', date(1999, 1, 1)))

    # -- choose a glass product -----------------------------------------------------
    def test_a_panel_with_no_product_is_one_warning_each_and_no_cost(self):
        self.design._explode()
        glass = self.design.bom_line_ids.filtered(lambda l: l.kind == 'glass')
        self.assertTrue(glass, "the panel still shows")
        self.assertFalse(any(glass.mapped('line_cost')))
        warnings = self.design.check_line_ids.filtered(
            lambda c: 'choose a glass product' in c.message)
        self.assertEqual(sorted(warnings.mapped('panel_no')), [1, 2])
        self.assertTrue(all(c.target_kind == 'glass' for c in warnings))
        self.assertTrue(all(c.level == 'warning' for c in warnings))

    def test_choosing_a_product_removes_the_warning(self):
        self.design.glass_product_id = self.unit
        self.design._explode()
        self.assertFalse(self.design.check_line_ids.filtered(
            lambda c: 'choose a glass product' in c.message))

    def test_quotes_print_the_product_and_its_remark(self):
        self.design.glass_product_id = self.unit
        self.design.glass_remark = 'was: Clear Tempered'
        text = self.design._glass_stack_text()
        self.assertIn('Unit 6+12+6', text)
        self.assertIn('was: Clear Tempered', text)
        self.leaves[0].glass_product_id = self.other
        self.assertNotIn('was:', self.design._glass_stack_text(self.leaves[0]))

    # -- the migration -------------------------------------------------------------------
    def _part(self, kind='sheet', mm=6.0, **extra):
        return dict({'kind': kind, 'glass_type': 'Clear', 'thickness_mm': mm,
                     'gap_mm': 12.0 if kind == 'gap' else 0.0}, **extra)

    def _migrate(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.glass_products_migrated', '')
        return self.env['aw.design']._migrate_glass_products()

    def test_a_single_sheet_becomes_its_variant_and_a_sealed_unit_is_left_to_choose(self):
        Part = self.env['aw.glass.part']
        variant = self.clear._variant_for(6.0)
        if not variant:
            self.skipTest("no Glass Sheet variant on this database")
        # panel 1: one sheet with a typed rate and a remark; panel 2: sealed
        self.leaves[0].glass_part_ids = Part._commands_from([
            self._part(rate_manual=True, manual_rate=70.0,
                       remark='was: Clear Tempered')])
        self.leaves[1].glass_part_ids = Part._commands_from([
            self._part(), self._part('gap'), self._part()])
        counts = self._migrate()
        self.assertEqual(self.leaves[0].glass_product_id, variant)
        self.assertTrue(self.leaves[0].glass_rate_manual)
        self.assertEqual(self.leaves[0].glass_manual_rate, 70.0)
        self.assertEqual(self.leaves[0].glass_remark, 'was: Clear Tempered')
        self.assertFalse(self.leaves[1].glass_product_id,
                         "no product is invented for a sealed unit")
        self.assertTrue(self.leaves[1].glass_choose)
        self.assertGreaterEqual(counts['flagged'], 1)
        # nothing is deleted
        self.assertTrue(self.leaves[1].glass_part_ids)

    def test_a_sealed_window_stack_flags_the_window_and_runs_once(self):
        Part = self.env['aw.glass.part']
        self.design.glass_part_ids = Part._commands_from([
            self._part(), self._part('gap'), self._part()])
        self._migrate()
        self.assertTrue(self.design.glass_choose)
        self.assertFalse(self.design.glass_product_id)
        self.design.glass_choose = False
        # once: a second run changes nothing
        self.assertEqual(self.env['aw.design']._migrate_glass_products(), {})
        self.assertFalse(self.design.glass_choose)

    # -- glass size ----------------------------------------------------------------------
    RULES = ('glass_fixed_w', 'glass_fixed_h', 'glass_sash_w', 'glass_sash_h',
             'mesh_w', 'mesh_h')

    def test_a_spec_with_empty_glass_rules_uses_the_window_types(self):
        spec = self.design.template_id
        spec.write({f: False for f in self.RULES})
        self.design.glass_product_id = self.unit
        lines = self._lines()
        self.assertTrue(lines)
        for line in lines:
            self.assertGreater(line.glass_w, 0.0)
            self.assertGreater(line.glass_h, 0.0)
            self.assertAlmostEqual(
                line.line_cost, 400.0 * line.area_sqm * SQFT_PER_SQM, 2)
            self.assertIn('System', line.calc_source or '')
        self.assertFalse(self.design.check_line_ids.filtered(
            lambda c: 'glass size is 0' in c.message))

    def test_a_spec_that_has_its_own_rules_keeps_them(self):
        spec = self.design.template_id
        spec.write({'glass_fixed_w': 'PW - 100', 'glass_fixed_h': 'PH - 100',
                    'glass_sash_w': 'PW - 100', 'glass_sash_h': 'PH - 100'})
        self.design.glass_product_id = self.unit
        line = self._lines()[:1]
        self.assertIn('Spec', line.calc_source or '')
        self.assertIn('100', line.calc_rule or '')

    def test_glass_of_size_zero_is_a_warning_naming_the_panel(self):
        spec = self.design.template_id
        system = spec.window_type_id
        spec.write({f: False for f in self.RULES})
        system.write({f: False for f in self.RULES})
        self.design.glass_product_id = self.unit
        self.design._explode()
        warnings = self.design.check_line_ids.filtered(
            lambda c: 'glass size is 0' in c.message)
        self.assertTrue(warnings)
        self.assertIn('Panel 1', warnings[0].message)

    def test_a_typed_size_replaces_the_rules_and_is_costed(self):
        self.design.glass_product_id = self.unit
        ruled = self._lines(self.leaves[0].panel_no)
        rule_w, rule_h = ruled.glass_w, ruled.glass_h
        self.assertEqual(self.leaves[0]._glass_rule_size(), (rule_w, rule_h))
        self.leaves[0].write({'glass_size_manual': True,
                              'glass_w_mm': 1000.0, 'glass_h_mm': 1500.0})
        line = self._lines(self.leaves[0].panel_no)
        self.assertEqual((line.glass_w, line.glass_h), (1000.0, 1500.0))
        self.assertEqual(line.calc_source, 'Typed on the panel')
        self.assertAlmostEqual(
            line.line_cost, 400.0 * 1.5 * SQFT_PER_SQM, 2)
        # the other panel keeps the rule
        other = self._lines(self.leaves[1].panel_no)
        self.assertEqual((other.glass_w, other.glass_h), (rule_w, rule_h))
        # a typed size of zero is not used
        self.leaves[0].glass_w_mm = 0.0
        line = self._lines(self.leaves[0].panel_no)
        self.assertEqual((line.glass_w, line.glass_h), (rule_w, rule_h))

    # -- the payload and the save -----------------------------------------------------
    def _save(self, edit):
        data = self.design.get_configurator_data()
        edit(data)
        self.design.save_layout({'header': data['header'], 'rows': data['rows']})

    def test_the_payload_carries_the_glass_and_a_save_keeps_it(self):
        data = self.design.get_configurator_data()
        self.assertIn(self.unit.id, [p['id'] for p in data['glass_products']])
        self.assertEqual(
            [p['rate'] for p in data['glass_products']
             if p['id'] == self.unit.id], [400.0])

        def edit(d):
            d['header']['glass_product_id'] = self.unit.id
            leaf = d['rows'][0]['leaves'][1]
            leaf['glass_product_id'] = self.other.id
            leaf['glass_size_manual'] = True
            leaf['glass_w_mm'] = 900.0
            leaf['glass_h_mm'] = 1400.0
            leaf['glass_rate_manual'] = True
            leaf['glass_manual_rate'] = 123.0
        self._save(edit)
        self.assertEqual(self.design.glass_product_id, self.unit)
        leaf = self.design.row_ids.leaf_ids.sorted('panel_no')[1]
        self.assertEqual(leaf.glass_product_id, self.other)
        self.assertEqual((leaf.glass_w_mm, leaf.glass_h_mm), (900.0, 1400.0))
        self.assertEqual(leaf.glass_manual_rate, 123.0)
        # saved back untouched: nothing moves
        self._save(lambda d: None)
        leaf = self.design.row_ids.leaf_ids.sorted('panel_no')[1]
        self.assertEqual(leaf.glass_product_id, self.other)
        self.assertTrue(leaf.glass_size_manual and leaf.glass_rate_manual)
        # a typed size or rate that is switched off is not kept
        def off(d):
            d['rows'][0]['leaves'][1]['glass_size_manual'] = False
            d['rows'][0]['leaves'][1]['glass_rate_manual'] = False
        self._save(off)
        leaf = self.design.row_ids.leaf_ids.sorted('panel_no')[1]
        self.assertEqual((leaf.glass_w_mm, leaf.glass_manual_rate), (0.0, 0.0))

    def test_a_copy_of_the_window_keeps_the_glass(self):
        self.design.write({'glass_product_id': self.unit.id,
                           'glass_remark': 'was: X'})
        copy = self.design.copy_position()
        self.assertEqual(copy.glass_product_id, self.unit)
        self.assertEqual(copy.glass_remark, 'was: X')

    def test_a_rule_suggestion_uses_a_product_of_that_name_and_invents_none(self):
        design = self.design
        design.suggest_glass = True
        design.family_id.glazing = 'double'
        design.location = 'Bathroom'
        design._suggest_glass()
        self.assertFalse(self.leaves.mapped('glass_product_id'),
                         "no product of the suggested name, so none is made")
        frosted = self._product('6+10+6 Frosted Tempered', 500.0, date(2000, 1, 1))
        design._suggest_glass()
        for leaf in self.leaves:
            self.assertEqual(leaf.glass_product_id, frosted)
            self.assertTrue(leaf.glass_suggested)
        # a hand-chosen panel is never replaced
        self.leaves[0].write({'glass_product_id': self.other.id,
                              'glass_suggested': False, 'glass_chosen': True})
        design._suggest_glass()
        self.assertEqual(self.leaves[0].glass_product_id, self.other)

    # -- what the old tables still keep (G2 removes them) -------------------------
    def _migrated_zero(self, mm):
        return self._part(mm=mm, manual_zero=True, migrated=True)

    def test_the_migration_reports_list_what_was_migrated(self):
        self.assertTrue(self.env.ref(
            'aw_fenestration_design.action_aw_glass_part_migrated'))
        self.assertTrue(self.env.ref(
            'aw_fenestration_design.action_aw_glass_part_remark'))

    def test_a_new_spec_starts_with_a_sealed_unit_stack(self):
        spec = self.env['aw.window.template'].search([], limit=1)
        if not spec:
            self.skipTest("no spec")
        Part = self.env['aw.glass.part']
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.default_glass_stack_seeded', '')
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.spec_dg_openable_id', str(spec.id))
        spec.glass_part_ids = [(5, 0, 0)]
        self.assertTrue(self.env['aw.window.template']._seed_default_glass_stacks())
        parts = spec.glass_part_ids.sorted('sequence')
        self.assertEqual(parts.mapped('kind'), ['sheet', 'gap', 'sheet'])
        self.assertEqual(parts[0].thickness_mm, 6.0)
        self.assertEqual(parts[1].gap_mm, 12.0)
        self.assertFalse(any(parts.mapped('migrated')))
        self.assertFalse(any(parts.mapped('rate_manual')))
        # once, and never over a stack somebody already has
        self.assertFalse(self.env['aw.window.template']._seed_default_glass_stacks())
        self.assertTrue(Part.search_count([('template_id', '=', spec.id)]) == 3)

    def test_changing_the_glass_clears_its_manual_rate(self):
        Part = self.env['aw.glass.part']
        self.design.glass_part_ids = [(5, 0, 0)] + Part._commands_from([
            self._part(rate_manual=True, manual_rate=55.0, migrated=True)])
        part = self.design.glass_part_ids
        part.write({'remark': 'x'})                      # not glass: kept
        self.assertTrue(part.rate_manual)
        part.write({'thickness_mm': 6.0})                # same value: kept
        self.assertTrue(part.rate_manual)
        part.write({'thickness_mm': 8.0})
        self.assertFalse(part.rate_manual or part.migrated)
        self.assertEqual(part.manual_rate, 0.0)
        part.write({'rate_manual': True, 'manual_rate': 66.0})
        part.write({'thickness_mm': 6.0, 'rate_manual': True, 'manual_rate': 70.0})
        self.assertTrue(part.rate_manual)
        self.assertEqual(part.manual_rate, 70.0)


@tagged('post_install', '-at_install')
class TestGlassThresholds(TransactionCase):
    """The suggestion limits fall back to the defaults when unset or empty."""

    def _thresholds(self):
        return self.env['aw.design']._glass_thresholds()

    def test_unset_and_empty_use_the_defaults(self):
        param = self.env['ir.config_parameter'].sudo()
        for key in ('aw_fenestration.glass_threshold_1_m2',
                    'aw_fenestration.glass_threshold_2_m2'):
            param.search([('key', '=', key)]).unlink()
        self.assertEqual(self._thresholds(), (4.5, 7.0))
        for key in ('aw_fenestration.glass_threshold_1_m2',
                    'aw_fenestration.glass_threshold_2_m2'):
            param.set_param(key, '0.0')
        self.assertEqual(self._thresholds(), (4.5, 7.0))

    def test_a_typed_limit_is_used(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.glass_threshold_1_m2', '3.0')
        param.set_param('aw_fenestration.glass_threshold_2_m2', '6.5')
        self.assertEqual(self._thresholds(), (3.0, 6.5))

    def test_a_small_panel_is_not_suggested_anything_by_default(self):
        param = self.env['ir.config_parameter'].sudo()
        for key in ('aw_fenestration.glass_threshold_1_m2',
                    'aw_fenestration.glass_threshold_2_m2'):
            param.search([('key', '=', key)]).unlink()
        design = self.env['aw.design'].new({})
        leaf = self.env['aw.design.leaf'].new({'width_mm': 1200.0})
        leaf.row_id = self.env['aw.design.row'].new({'height_mm': 1800.0})
        self.assertEqual(design._suggested_glass_for(leaf), '')
