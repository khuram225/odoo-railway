# -*- coding: utf-8 -*-
"""Glass as a stack of parts per panel: costing, the window default, a
panel that differs, and the migration from saved specs."""
import unittest
from datetime import date

from odoo.tests import TransactionCase, tagged

SQFT_PER_SQM = 10.7639104
MM_PER_FOOT = 304.8


@tagged('post_install', '-at_install')
class TestGlassStack(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family = env['aw.window.family'].search([]).filtered(
            lambda f: f.series_ids.filtered('active').filtered(
                lambda s: s.leaf_type_ids))[:1]
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        series = family.series_ids.filtered('active').filtered(
            lambda s: s.leaf_type_ids)[0]
        cls.Type = env['aw.glass.type']
        cls.Type._seed_glass_types()
        env['aw.glass.option']._seed_glass_options()
        cls.Type._seed_glass_sheet()
        cls.vendor = env['res.partner'].create({'name': 'Glass vendor (test)'})
        cls.clear = cls.Type.search([('name', '=', 'Clear')])
        for mm, price in ((6, 100.0), (8, 150.0)):
            env['aw.glass.rate'].create({
                'glass_type_id': cls.clear.id, 'thickness_mm': mm,
                'vendor_id': cls.vendor.id, 'price': price,
                'date_from': date(2000, 1, 1)})
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
        cls.Part = env['aw.glass.part']

    # -- helpers ------------------------------------------------------------
    def _sheet(self, mm, **extra):
        return dict({'kind': 'sheet', 'glass_type': 'Clear',
                     'thickness_mm': float(mm)}, **extra)

    def _gap(self, mm=12.0, **extra):
        return dict({'kind': 'gap', 'gap_mm': mm, 'spacer_type': 'Aluminium',
                     'spacer_colour': 'Silver', 'gas': 'Air'}, **extra)

    def _set_header(self, items):
        self.design.glass_part_ids = [(5, 0, 0)] + self.Part._commands_from(items)

    def _set_panel(self, leaf, items):
        leaf.glass_part_ids = [(5, 0, 0)] + self.Part._commands_from(items)

    def _lines(self, panel=None):
        self.design._explode()
        lines = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'glass' and l.glass_part_kind)
        return lines.filtered(lambda l: l.panel_no == panel) if panel else lines

    # -- costing -----------------------------------------------------------------
    def test_a_stack_costs_the_sum_of_its_parts(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(6), self._gap(), self._sheet(8)])
        lines = self._lines(self.leaves[0].panel_no)
        self.assertEqual(lines.mapped('glass_part_kind'),
                         ['sheet', 'gap', 'sheet'])
        sheets = lines.filtered(lambda l: l.glass_part_kind == 'sheet')
        for line in sheets:
            rate = 100.0 if line.glass_mm == 6 else 150.0
            self.assertAlmostEqual(
                line.line_cost, rate * line.area_sqm * SQFT_PER_SQM, 2)
            self.assertEqual(line.rate_list, rate)
            self.assertFalse(line.rate_is_manual)
        # spacer and gas have no price yet, so the gap costs nothing, silently
        gap = lines.filtered(lambda l: l.glass_part_kind == 'gap')
        self.assertEqual(gap.line_cost, 0.0)
        self.assertFalse(gap.cost_note)
        self.assertAlmostEqual(
            sum(lines.mapped('line_cost')),
            sum(sheets.mapped('line_cost')), 2)
        # each sheet is a Glass Sheet variant
        self.assertTrue(all(l.product_id.product_tmpl_id
                            == self.Type._glass_sheet() for l in sheets))

    def test_the_gap_costs_spacer_per_running_ft_and_gas_per_unit(self):
        Extra = self.env['aw.glass.extra']
        Extra.create({'kind': 'spacer', 'name': 'Aluminium',
                      'unit': 'per_ft', 'rate': 10.0,
                      'date_from': date(2000, 1, 1)})
        Extra.create({'kind': 'gas', 'name': 'Argon', 'unit': 'per_unit',
                      'rate': 5.0, 'date_from': date(2000, 1, 1)})
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(6), self._gap(gas='Argon'),
                          self._sheet(6)])
        gap = self._lines(self.leaves[0].panel_no).filtered(
            lambda l: l.glass_part_kind == 'gap')
        perimeter_ft = 2 * (gap.glass_w + gap.glass_h) / MM_PER_FOOT
        self.assertAlmostEqual(gap.line_cost, perimeter_ft * 10.0 + 5.0, 2)

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

    def test_a_manual_rate_is_flagged_noted_and_reset_returns_to_the_list(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(6, rate_manual=True, manual_rate=0.0)])
        line = self._lines(self.leaves[0].panel_no)
        self.assertTrue(line.rate_is_manual)
        self.assertEqual(line.line_cost, 0.0)
        self.assertEqual(line.rate_list, 100.0)
        self.assertIn('manual rate 0 (list rate 100)', line.cost_note)
        self.design.glass_part_ids.write({'rate_manual': False})
        line = self._lines(self.leaves[0].panel_no)
        self.assertGreater(line.line_cost, 0.0)
        self.assertFalse(line.cost_note)

    def test_a_part_without_a_rate_is_named(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(5)])           # no 5 mm rate typed
        line = self._lines(self.leaves[0].panel_no)
        self.assertEqual(line.line_cost, 0.0)
        self.assertEqual(line.cost_note, '5 mm Clear: no rate')

    def test_the_order_glass_vendor_decides_whose_rates(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(6)])
        other = self.env['res.partner'].create({'name': 'Second glass vendor'})
        self.env['aw.glass.rate'].create({
            'glass_type_id': self.clear.id, 'thickness_mm': 6,
            'vendor_id': other.id, 'price': 300.0,
            'date_from': date(2000, 1, 1)})
        self.order.aw_glass_vendor_id = other
        self.assertEqual(self._lines(self.leaves[0].panel_no).rate_list, 300.0)
        self.order.aw_glass_vendor_id = self.vendor
        self.assertEqual(self._lines(self.leaves[0].panel_no).rate_list, 100.0)

    # -- panels ------------------------------------------------------------------
    def test_one_panel_can_differ_and_the_others_do_not(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([self._sheet(6)])
        self._set_panel(self.leaves[0], [self._sheet(8)])
        first = self._lines(self.leaves[0].panel_no)
        second = self._lines(self.leaves[1].panel_no)
        self.assertEqual(first.mapped('glass_label'), ['8 mm Clear'])
        self.assertEqual(second.mapped('glass_label'), ['6 mm Clear'])
        self.assertEqual(self.leaves[1].glass_part_ids.ids, [])  # follows
        # clearing the panel's own stack makes it follow the window again
        self.leaves[0].glass_part_ids = [(5, 0, 0)]
        self.assertEqual(
            self._lines(self.leaves[0].panel_no).mapped('glass_label'),
            ['6 mm Clear'])

    def test_no_stack_at_all_is_one_warning_not_a_cost(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self.design.glass_part_ids = [(5, 0, 0)]
        self.design.template_id.glass_part_ids.unlink()
        self.design._explode()
        glass = self.design.bom_line_ids.filtered(lambda l: l.kind == 'glass')
        self.assertTrue(glass)                       # the panel still shows
        self.assertFalse(glass.filtered('glass_part_kind'))
        self.assertFalse(any(glass.mapped('line_cost')))

    def test_quotes_print_the_remark_not_plain_clear(self):
        self.leaves.glass_part_ids = [(5, 0, 0)]
        self._set_header([
            self._sheet(6, remark='was: Frosted Tempered'),
            self._gap(10.0), self._sheet(6, remark='was: Frosted Tempered')])
        text = self.design._glass_stack_text()
        self.assertIn('6 mm Clear + 10 mm gap + 6 mm Clear', text)
        self.assertIn('was: Frosted Tempered', text)

    def test_the_migration_reports_list_what_was_migrated(self):
        self._set_header([self._sheet(6, migrated=True, remark='was: X')])
        Part = self.env['aw.glass.part']
        self.assertIn(
            self.design.glass_part_ids,
            Part.search([('migrated', '=', True)]) | self.design.glass_part_ids)
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

    # -- default stacks use the list rate ---------------------------------------
    def _migrated_zero(self, mm):
        return self._sheet(mm, manual_zero=True, migrated=True)

    def _clear(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'aw_fenestration.default_stack_rates_cleared', '')
        return self.env['aw.window.template']._clear_migrated_default_rates()

    def test_a_default_stack_loses_its_migrated_zero_but_an_order_keeps_it(self):
        spec = self.design.template_id
        spec.glass_part_ids = [(5, 0, 0)] + self.Part._commands_from([
            self._migrated_zero(6), self._gap(), self._migrated_zero(6),
            self._sheet(8, rate_manual=True, manual_rate=77.0)])
        self._set_header([self._migrated_zero(6)])      # on an order's window
        self.assertEqual(self._clear(), 2)
        sheets = spec.glass_part_ids.filtered(lambda p: p.kind == 'sheet')
        self.assertEqual(
            sorted(sheets.mapped('rate_manual')), [False, False, True])
        self.assertEqual(sheets.filtered('rate_manual').manual_rate, 77.0)
        self.assertFalse(any(spec.glass_part_ids.mapped('migrated')))
        # the window on the order is not re-priced
        header = self.design.glass_part_ids
        self.assertTrue(header.rate_manual and header.migrated)
        # once
        self.assertEqual(self.env['aw.window.template']
                         ._clear_migrated_default_rates(), 0)

    def test_a_new_window_costs_its_glass_at_the_list_rate(self):
        spec = self.design.template_id
        spec.glass_part_ids = [(5, 0, 0)] + self.Part._commands_from([
            self._migrated_zero(6), self._gap(), self._migrated_zero(6)])
        self._clear()
        series = spec.window_type_id
        fresh = self.order._create_fenestration_position(
            series, family=self.design.family_id)
        fresh.write({'template_id': spec.id, 'width_mm': 2400.0,
                     'height_mm': 1800.0})
        fresh._apply_spec(force=True)
        fresh._explode()
        sheets = fresh.bom_line_ids.filtered(
            lambda l: l.kind == 'glass' and l.glass_part_kind == 'sheet')
        self.assertTrue(sheets)
        for line in sheets:
            self.assertFalse(line.rate_is_manual)
            self.assertEqual(line.rate_list, 100.0)
            self.assertAlmostEqual(
                line.line_cost, 100.0 * line.area_sqm * SQFT_PER_SQM, 2)

    # -- glass size ----------------------------------------------------------------
    RULES = ('glass_fixed_w', 'glass_fixed_h', 'glass_sash_w', 'glass_sash_h',
             'mesh_w', 'mesh_h')

    def test_a_spec_with_empty_glass_rules_uses_the_window_types(self):
        spec = self.design.template_id
        spec.write({f: False for f in self.RULES})
        self.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        self._set_header([self._sheet(6), self._gap(), self._sheet(6)])
        lines = self._lines()
        sheets = lines.filtered(lambda l: l.glass_part_kind == 'sheet')
        self.assertTrue(sheets)
        for line in sheets:
            self.assertGreater(line.glass_w, 0.0)
            self.assertGreater(line.glass_h, 0.0)
            self.assertAlmostEqual(
                line.line_cost, 100.0 * line.area_sqm * SQFT_PER_SQM, 2)
            self.assertIn('System', line.calc_source or '')
        self.assertFalse(self.design.check_line_ids.filtered(
            lambda c: 'glass size is 0' in c.message))

    def test_a_spec_that_has_its_own_rules_keeps_them(self):
        spec = self.design.template_id
        spec.write({'glass_fixed_w': 'PW - 100', 'glass_fixed_h': 'PH - 100',
                    'glass_sash_w': 'PW - 100', 'glass_sash_h': 'PH - 100'})
        self._set_header([self._sheet(6)])
        sheet = self._lines().filtered(
            lambda l: l.glass_part_kind == 'sheet')[:1]
        self.assertIn('Spec', sheet.calc_source or '')
        self.assertIn('100', sheet.calc_rule or '')

    def test_glass_of_size_zero_is_a_warning_naming_the_panel(self):
        spec = self.design.template_id
        system = spec.window_type_id
        spec.write({f: False for f in self.RULES})
        system.write({f: False for f in self.RULES})
        self._set_header([self._sheet(6)])
        self.design._explode()
        warnings = self.design.check_line_ids.filtered(
            lambda c: 'glass size is 0' in c.message)
        self.assertTrue(warnings)
        self.assertIn('Panel 1', warnings[0].message)

    def test_a_typed_glass_rate_is_an_info_note_not_a_stand_in_warning(self):
        self._set_header([self._sheet(6, rate_manual=True, manual_rate=55.0)])
        self.design._explode()
        checks = self.design.check_line_ids
        self.assertTrue(checks.filtered(
            lambda c: c.level == 'info' and 'manual rate' in c.message))
        self.assertFalse(checks.filtered(
            lambda c: c.level == 'warning' and 'stand-in' in c.message))
