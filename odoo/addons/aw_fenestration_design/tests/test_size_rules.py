# -*- coding: utf-8 -*-
"""Size rules (PR 3, part A): a piece starts from the final length of the
piece before it. Builds its OWN series, positions and spec (a database
installed from scratch has no profile lines on a panel), so nothing here
depends on what the catalogue holds, and nothing skips."""
from odoo.addons.aw_fenestration_design.models.family import (
    OPENING_LEAF_CODES)
from odoo.addons.aw_fenestration_design.tests.common import (
    first_thickness, seeded_family_series)
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

IN = 25.4


@tagged('post_install', '-at_install')
class TestSizeRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.family, _base = seeded_family_series(env)
        cls.opening = env['aw.leaf.type'].search(
            [('code', 'in', list(OPENING_LEAF_CODES))], limit=1)
        cls.fixed = env['aw.leaf.type'].search(
            [('code', '=', 'FIXED')], limit=1)
        assert cls.opening and cls.fixed, "the leaf types are seeded data"
        cls.series = env['aw.window.series'].create({
            'name': 'SZ series', 'family_id': cls.family.id,
            'leaf_type_ids': [(6, 0, (cls.opening | cls.fixed).ids)]})
        profile = env['product.template'].search([
            ('categ_id', 'child_of', env.ref(
                'aw_fenestration_core.product_category_profiles').id)],
            limit=1)
        thickness = first_thickness(env, profile)
        Position = env['aw.profile.position']

        def position(name, scope, group, edge=False):
            return Position.create({
                'name': name, 'scope': scope, 'part_group': group,
                'edge': edge, 'is_required': False})

        cls.p_top = position('SZ Frame top', 'frame', 'outer_frame', 'top')
        cls.p_side = position('SZ Frame side', 'frame', 'outer_frame',
                              'sides')
        cls.p_div = position('SZ Divider', 'junction_mullion', 'dividers')
        cls.p_sash = position('SZ Sash', 'panel_opening', 'sashes', 'sides')
        cls.p_bead = position('SZ Bead', 'panel_opening', 'beads', 'sides')

        def line(pos, formula):
            return (0, 0, {
                'position_id': pos.id, 'product_tmpl_id': profile.id,
                'thickness_id': thickness.id, 'length_formula': formula,
                'qty_formula': '1'})

        cls.spec = env['aw.window.template'].create({
            'name': 'SZ spec', 'window_type_id': cls.series.id,
            'is_default': True,
            'profile_line_ids': [
                line(cls.p_top, 'W'), line(cls.p_side, 'H'),
                line(cls.p_div, 'CH'), line(cls.p_sash, 'PH'),
                line(cls.p_bead, 'OH - 50')]})
        cls.design = cls._window(
            cls.series, [cls.opening, cls.fixed, cls.fixed])

    @classmethod
    def _window(cls, series, types, width=3000.0, height=1500.0):
        env = cls.env
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Size rule customer'}).id,
            'aw_default_series_id': series.id})
        design = order._create_fenestration_position(
            series, family=cls.family, location='Hall')
        design.write({'width_mm': width, 'height_mm': height,
                      'template_id': cls.spec.id})
        each = width / len(types)
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': height, 'leaves': [
                {'width_mm': each, 'leaf_type_id': t.id} for t in types]}]})
        return design

    # -- helpers -------------------------------------------------------------
    def _rule(self, kind, start, offset_mm, series=None):
        return self.env['aw.size.rule'].create({
            'series_id': (series or self.series).id, 'piece_kind': kind,
            'starts_from': start, 'offset_mm': offset_mm})

    def _lines(self, position, design=None):
        design = design or self.design
        return design.bom_line_ids.filtered(
            lambda l: l.template_line_id.position_id == position
        ).sorted('sequence')

    def _lengths(self, position, design=None):
        return [round(l.length_mm, 1) for l in self._lines(position, design)]

    def _recompute(self, design=None):
        (design or self.design)._explode()

    def _messages(self, design=None):
        return (design or self.design).check_line_ids.mapped('message')

    def _formula_lengths(self):
        return {p.name: self._lengths(p) for p in (
            self.p_top, self.p_side, self.p_div, self.p_sash, self.p_bead)}

    # -- nothing changes without rows ---------------------------------------
    def test_with_no_rows_every_length_is_what_the_formulas_give(self):
        # the window makes every piece the other tests lean on
        self.assertEqual(self._lengths(self.p_top), [3000.0])
        self.assertEqual(self._lengths(self.p_side), [1500.0, 1500.0])
        self.assertEqual(self._lengths(self.p_div), [1500.0, 1500.0])
        self.assertEqual(self._lengths(self.p_sash), [1500.0, 1500.0])
        self.assertEqual(self._lengths(self.p_bead), [1450.0, 1450.0])
        self.assertFalse(self.env['aw.size.rule'].search_count(
            [('series_id', '=', self.series.id)]))
        before = {l.piece_key: (l.length_mm, l.computed_length_mm,
                                l.calc_source)
                  for l in self.design.bom_line_ids if l.piece_key}
        self._recompute()
        after = {l.piece_key: (l.length_mm, l.computed_length_mm,
                               l.calc_source)
                 for l in self.design.bom_line_ids if l.piece_key}
        self.assertTrue(before)
        self.assertEqual(before, after)
        self.assertFalse([m for m in self._messages()
                          if m.startswith('Size rule')])

    def test_a_row_with_nothing_in_starts_from_does_nothing(self):
        before = self._formula_lengths()
        self._rule('divider', False, -50.8)
        self._recompute()
        self.assertEqual(self._formula_lengths(), before)

    # -- the chain ----------------------------------------------------------
    def test_divider_starts_from_the_frame(self):
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        self.assertEqual(self._lengths(self.p_div), [1449.2, 1449.2])
        line = self._lines(self.p_div)[0]
        self.assertEqual(line.calc_rule, 'Size rule')
        self.assertIn('divider: frame right side 59.06 in - 2 in',
                      line.calc_source)
        self.assertEqual(self._lengths(self.p_side), [1500.0, 1500.0])

    def test_only_the_filled_rows_use_the_chain(self):
        before = self._formula_lengths()
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        after = self._formula_lengths()
        self.assertNotEqual(after[self.p_div.name], before[self.p_div.name])
        for pos in (self.p_top, self.p_side, self.p_sash, self.p_bead):
            self.assertEqual(after[pos.name], before[pos.name])

    def test_sash_side_and_bead_follow_the_chain(self):
        self._rule('divider', 'frame', -2 * IN)
        self._rule('sash_side', 'divider', -1 * IN)
        self._rule('sash_bead', 'sash_side', -2 * IN)
        self._recompute()
        self.assertEqual(self._lengths(self.p_div), [1449.2, 1449.2])
        self.assertEqual(self._lengths(self.p_sash), [1423.8, 1423.8])
        self.assertEqual(self._lengths(self.p_bead), [1373.0, 1373.0])
        self.assertIn('sash bead: sash side',
                      self._lines(self.p_bead)[0].calc_source)

    def test_another_series_rule_does_not_reach_this_window(self):
        other = self.env['aw.window.series'].create({'name': 'SZ other'})
        self._rule('divider', 'frame', -2 * IN, series=other)
        before = self._formula_lengths()
        self._recompute()
        self.assertEqual(self._formula_lengths(), before)

    def test_a_start_that_is_not_in_the_window_falls_back_down_the_chain(self):
        single = self._window(self.series, [self.opening], width=1200.0)
        self._rule('sash_side', 'divider', -1 * IN)    # no divider in 1 panel
        self._recompute(single)
        self.assertEqual(self._lengths(self.p_sash, single),
                         [round(1500.0 - IN, 1)] * 2)
        self.assertIn('(no divider piece here)',
                      self._lines(self.p_sash, single)[0].calc_source)

    # -- adjustment and typed lengths ---------------------------------------
    def test_the_adjustment_stays_on_top_of_the_rule(self):
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        line = self._lines(self.p_div)[0]
        self.design.set_piece_adjustment(line.piece_key, 5.0)
        line = self._lines(self.p_div)[0]
        self.assertAlmostEqual(line.length_mm, 1454.2, places=1)
        self.assertAlmostEqual(
            self.design._rule_length(line), 1449.2, places=1)
        self.design.reset_piece_adjustment(line.piece_key)
        self.assertAlmostEqual(
            self._lines(self.p_div)[0].length_mm, 1449.2, places=1)

    def test_a_typed_length_wins_over_the_rule(self):
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        line = self._lines(self.p_div)[0]
        self.design.set_piece_length(line.id, 999.0)
        self.assertAlmostEqual(self._lines(self.p_div)[0].length_mm, 999.0)
        self._recompute()
        self.assertAlmostEqual(self._lines(self.p_div)[0].length_mm, 999.0)

    def test_a_frame_adjustment_moves_the_divider_but_a_typed_one_does_not(
            self):
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        frame = self._lines(self.p_side)[0]
        self.design.set_piece_adjustment(frame.piece_key, 10.0)
        self.assertEqual(self._lengths(self.p_div), [1459.2, 1459.2])
        self.design.reset_piece_adjustment(frame.piece_key)
        frame = self._lines(self.p_side)[0]
        self.design.set_piece_length(frame.id, 1200.0)
        self.assertAlmostEqual(self._lines(self.p_side)[0].length_mm, 1200.0)
        self.assertEqual(self._lengths(self.p_div), [1449.2, 1449.2])

    # -- the warnings -------------------------------------------------------
    def test_a_rule_that_gives_nothing_keeps_the_formula_and_says_so(self):
        self._rule('divider', 'frame', -5000.0)
        self._recompute()
        self.assertEqual(self._lengths(self.p_div), [1500.0, 1500.0])
        self.assertTrue([m for m in self._messages()
                         if m.startswith('Size rule (divider)')
                         and 'would be' in m])

    def test_a_divider_as_long_as_the_frame_opening_warns(self):
        rule = self._rule('divider', 'frame', 0.0)
        self._recompute()
        self.assertEqual(self._lengths(self.p_div), [1500.0, 1500.0])
        self.assertTrue([m for m in self._messages()
                         if m.startswith('Size rule (divider)')
                         and 'frame opening' in m])
        rule.offset_mm = -2 * IN
        self._recompute()
        self.assertFalse([m for m in self._messages()
                          if 'frame opening' in m])

    def test_a_position_with_no_size_kind_is_named_once_rules_exist(self):
        odd = self.env['aw.profile.position'].create({
            'name': 'SZ Odd', 'scope': 'frame', 'edge': 'top',
            'is_required': False})           # no part group
        first = self.spec.profile_line_ids[:1]
        self.spec.write({'profile_line_ids': [(0, 0, {
            'position_id': odd.id, 'product_tmpl_id': first.product_tmpl_id.id,
            'thickness_id': first.thickness_id.id,
            'length_formula': 'W', 'qty_formula': '1'})]})
        self._recompute()
        self.assertFalse([m for m in self._messages()
                          if m.startswith('Size rule (position)')])
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        said = [m for m in self._messages()
                if m.startswith('Size rule (position)')]
        self.assertEqual(len(said), 1)
        self.assertIn('SZ Odd', said[0])

    def test_interlock_and_fly_screen_positions_are_not_named(self):
        # "no size kind by design": interlock & meeting and fly screen
        first = self.spec.profile_line_ids[:1]
        for name, group in (('SZ Interlock', 'interlock_meeting'),
                            ('SZ Fly', 'fly_screen')):
            pos = self.env['aw.profile.position'].create({
                'name': name, 'scope': 'frame', 'edge': 'top',
                'part_group': group, 'is_required': False})
            self.spec.write({'profile_line_ids': [(0, 0, {
                'position_id': pos.id,
                'product_tmpl_id': first.product_tmpl_id.id,
                'thickness_id': first.thickness_id.id,
                'length_formula': 'W', 'qty_formula': '1'})]})
        self._rule('divider', 'frame', -2 * IN)
        self._recompute()
        self.assertFalse([m for m in self._messages()
                          if m.startswith('Size rule (position)')])

    # -- the model ----------------------------------------------------------
    def test_one_row_per_series_and_kind_and_a_start_before_the_piece(self):
        self._rule('divider', 'frame', 0.0)
        with self.assertRaises(ValidationError):
            self._rule('divider', 'window', 0.0)
        with self.assertRaises(ValidationError):
            self._rule('frame', 'divider', 0.0)

    # -- the Setup page -----------------------------------------------------
    def _wizard(self):
        wizard = self.env['aw.size.rule.setup'].create({
            'series_id': self.series.id,
            'sample_width_in': 3000.0 / IN, 'sample_height_in': 1500.0 / IN,
            'panels_across': 3, 'leaf_type_id': self.opening.id})
        wizard.action_load()
        return wizard

    def test_the_sample_shows_the_numbers_and_writes_nothing(self):
        orders = self.env['sale.order'].search_count([])
        designs = self.env['aw.design'].search_count([])
        wizard = self._wizard()
        self.assertEqual(len(wizard.line_ids), 5)
        wizard.line_ids.filtered(lambda l: l.kind == 'divider').write(
            {'starts_from': 'frame', 'offset_mm': -2 * IN})
        wizard.action_preview()
        divider = wizard.line_ids.filtered(lambda l: l.kind == 'divider')
        self.assertIn('1449.2 mm', divider.sample_text)
        self.assertIn('x 2', divider.sample_text)
        self.assertIn('frame', divider.sample_source)
        frame = wizard.line_ids.filtered(lambda l: l.kind == 'frame')
        self.assertIn('3000 mm', frame.sample_text)
        self.assertFalse(self.env['aw.size.rule'].search_count(
            [('series_id', '=', self.series.id)]))
        self.assertEqual(self.env['sale.order'].search_count([]), orders)
        self.assertEqual(self.env['aw.design'].search_count([]), designs)

    def test_saving_writes_only_the_filled_lines_and_clearing_removes(self):
        wizard = self._wizard()
        divider = wizard.line_ids.filtered(lambda l: l.kind == 'divider')
        divider.write({'starts_from': 'frame', 'offset_mm': -2 * IN})
        wizard.action_save()
        rules = self.env['aw.size.rule'].search(
            [('series_id', '=', self.series.id)])
        self.assertEqual(rules.mapped('piece_kind'), ['divider'])
        self.assertAlmostEqual(rules.offset_mm, -50.8)
        self.assertAlmostEqual(rules.offset_in, -2.0)
        divider.write({'starts_from': False})
        wizard.action_save()
        self.assertFalse(self.env['aw.size.rule'].search_count(
            [('series_id', '=', self.series.id)]))
