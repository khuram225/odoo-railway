# -*- coding: utf-8 -*-
"""A +/- adjustment on a piece: rule length + adjustment, after the rule,
following the window's size, under a typed absolute length, changing only its
own piece."""
from odoo.addons.aw_fenestration_design.tests.common import (
    first_thickness, seeded_family_series)
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPieceAdjust(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Adjust customer'}).id,
            'aw_default_series_id': series.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design = cls.order._create_fenestration_position(
            series, family=family, location='Hall')
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})

    # -- helpers -------------------------------------------------------------
    def _adjustable(self):
        return self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.piece_key
            and l.template_line_id and not l.cut_on_site
            and not l.is_free_form)

    def _lengths(self):
        return {l.piece_key: l.length_mm for l in self._adjustable()}

    def _line(self, key):
        return self.design.bom_line_ids.filtered(
            lambda l: l.piece_key == key)

    def _piece(self, panel_no=None):
        lines = self._adjustable()
        if panel_no is not None:
            lines = lines.filtered(lambda l: (l.panel_no or 0) == panel_no)
        self.assertTrue(lines, "the test window made no such piece")
        return lines[0].piece_key

    def _payload_piece(self, key):
        pieces = self.design.get_configurator_data()['pieces']
        return next(p for p in pieces if p['piece_key'] == key)

    # -- the rule -----------------------------------------------------------
    def test_no_adjustment_changes_nothing(self):
        for line in self._adjustable():
            self.assertAlmostEqual(line.length_mm, line.computed_length_mm)
        key = self._piece()
        piece = self._payload_piece(key)
        self.assertTrue(piece['adjustable'])
        self.assertIsNone(piece['adjust_mm'])
        self.assertAlmostEqual(piece['rule_length_mm'], piece['length_mm'])

    def test_final_length_is_the_rule_plus_the_adjustment(self):
        key = self._piece()
        before = self._line(key).length_mm
        self.design.set_piece_adjustment(key, 12.5)
        line = self._line(key)
        self.assertAlmostEqual(line.length_mm, before + 12.5)
        self.assertAlmostEqual(line.computed_length_mm, before + 12.5)
        self.assertFalse(line.is_manual)
        piece = self._payload_piece(key)
        self.assertAlmostEqual(piece['adjust_mm'], 12.5)
        self.assertAlmostEqual(piece['rule_length_mm'], before)
        self.design.set_piece_adjustment(key, -6.35)
        self.assertAlmostEqual(self._line(key).length_mm, before - 6.35)

    def test_an_adjustment_replaces_it_does_not_add(self):
        key = self._piece()
        before = self._line(key).length_mm
        self.design.set_piece_adjustment(key, 10.0)
        self.design.set_piece_adjustment(key, 4.0)
        self.assertAlmostEqual(self._line(key).length_mm, before + 4.0)
        self.assertEqual(len(self.design.piece_adjust_ids), 1)

    def test_a_typed_zero_is_the_pieces_own_adjustment(self):
        key = self._piece()
        before = self._line(key).length_mm
        self.design.set_piece_adjustment(key, 0.0)
        self.assertEqual(len(self.design.piece_adjust_ids), 1)
        self.assertAlmostEqual(self._line(key).length_mm, before)
        self.assertEqual(self._payload_piece(key)['adjust_mm'], 0.0)

    def test_reset_deletes_the_row_and_follows_the_default(self):
        key = self._piece()
        before = self._line(key).length_mm
        self.design.set_piece_adjustment(key, 25.0)
        self.design.reset_piece_adjustment(key)
        self.assertFalse(self.design.piece_adjust_ids)
        self.assertAlmostEqual(self._line(key).length_mm, before)
        self.assertIsNone(self._payload_piece(key)['adjust_mm'])
        # resetting a piece with none is harmless
        self.design.reset_piece_adjustment(key)

    def test_it_changes_its_own_piece_only(self):
        lengths = self._lengths()
        frame = self._piece(0)
        self.design.set_piece_adjustment(frame, 30.0)
        after = self._lengths()
        self.assertEqual(set(after), set(lengths))
        changed = {k for k in lengths
                   if abs(after[k] - lengths[k]) > 1e-6}
        self.assertEqual(changed, {frame})

    def test_it_follows_the_windows_size(self):
        key = self._piece(0)
        self.design.set_piece_adjustment(key, 10.0)
        rule_before = self._payload_piece(key)['rule_length_mm']
        self.design.write({'width_mm': 3000.0, 'height_mm': 2000.0})
        self.design._explode()
        piece = self._payload_piece(key)
        self.assertNotAlmostEqual(piece['rule_length_mm'], rule_before)
        self.assertAlmostEqual(piece['length_mm'],
                               piece['rule_length_mm'] + 10.0)
        self.assertAlmostEqual(piece['adjust_mm'], 10.0)

    # -- a typed absolute length wins ---------------------------------------
    def test_a_typed_length_wins_and_the_adjustment_stays(self):
        key = self._piece()
        self.design.set_piece_adjustment(key, 10.0)
        self.design.set_piece_length(self._line(key).id, 999.0)
        self.assertAlmostEqual(self._line(key).length_mm, 999.0)
        self.assertTrue(self._line(key).is_manual)
        self.design._explode()            # a recompute keeps the typed length
        self.assertAlmostEqual(self._line(key).length_mm, 999.0)
        self.assertEqual(len(self.design.piece_adjust_ids), 1)
        # "Use the rule" goes back to rule + adjustment, not to the bare rule
        rule = self._payload_piece(key)['rule_length_mm']
        self.design.use_piece_rule(self._line(key).id)
        line = self._line(key)
        self.assertFalse(line.is_manual)
        self.assertAlmostEqual(line.length_mm, rule + 10.0)

    def test_changing_the_adjustment_of_a_typed_piece_does_not_move_it(self):
        key = self._piece()
        self.design.set_piece_length(self._line(key).id, 777.0)
        self.design.set_piece_adjustment(key, 5.0)
        self.assertAlmostEqual(self._line(key).length_mm, 777.0)

    # -- refusals -----------------------------------------------------------
    def test_refusals(self):
        key = self._piece()
        with self.assertRaises(UserError):
            self.design.set_piece_adjustment('no|such|piece|1', 5.0)
        with self.assertRaises(UserError):
            self.design.set_piece_adjustment(key, 1500.0)      # a typo
        with self.assertRaises(UserError):
            self.design.set_piece_adjustment(key, float('nan'))
        with self.assertRaises(UserError):
            self.design.set_piece_adjustment(key, 'a lot')
        self.assertFalse(self.design.piece_adjust_ids)

    def test_it_cannot_make_a_piece_zero_long(self):
        # Its own small window, so there is always a piece well under the
        # 1 m limit: this test used to skip itself when the shared window
        # had none, and a skipped test proves nothing.
        env = self.env
        family, series = seeded_family_series(env)
        small = self.order._create_fenestration_position(
            series, family=family, location='Small')
        small.write({'width_mm': 600.0, 'height_mm': 600.0})
        leaf = {'width_mm': 300.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        small.save_layout({
            'header': small.get_configurator_data()['header'],
            'rows': [{'height_mm': 600.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})
        lines = small.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.piece_key
            and l.template_line_id and not l.cut_on_site
            and not l.is_free_form).sorted('length_mm')
        self.assertTrue(lines, "the small window made no piece")
        # Read now: setting an adjustment recomputes the window, which
        # replaces every BOM line, so `lines[0]` would be a deleted record.
        key, length = lines[0].piece_key, lines[0].length_mm
        self.assertGreater(length, 1.0)
        self.assertLess(length, 1000.0)
        with self.assertRaises(UserError):
            small.set_piece_adjustment(key, -length)
        # one millimetre short of the whole piece is allowed
        small.set_piece_adjustment(key, -(length - 1.0))
        after = small.bom_line_ids.filtered(lambda l: l.piece_key == key)
        self.assertAlmostEqual(after.length_mm, 1.0)

    def test_one_adjustment_per_piece(self):
        key = self._piece()
        self.design.set_piece_adjustment(key, 5.0)
        with self.assertRaises(ValidationError):
            self.env['aw.design.piece.adjust'].create({
                'design_id': self.design.id, 'piece_key': key,
                'adjust_mm': 1.0})

    # -- the rest of the system sees the final length ------------------------
    def test_the_cut_plan_goes_stale_and_plans_the_final_length(self):
        action = self.order.action_new_batch()
        self.env[action['res_model']].browse(action['res_id']).action_create()
        batch = self.order.aw_cut_plan_ids
        self.assertTrue(batch.is_current)
        key = self._piece()
        self.design.set_piece_adjustment(key, 20.0)
        self.assertFalse(batch.is_current)
        batch.action_generate()
        wanted = self._line(key).length_mm
        planned = batch.group_ids.bar_ids.cut_ids.filtered(
            lambda c: c.piece_ref == self._line(key).piece_ref)
        self.assertEqual(len(planned), 1)
        self.assertAlmostEqual(planned.length_mm, wanted, places=1)

    def test_the_change_is_noted_on_the_window(self):
        key = self._piece()
        self.design.set_piece_adjustment(key, 6.35)
        self.assertIn('adjusted piece', self.design.message_ids[0].body)
        self.design.reset_piece_adjustment(key)
        self.assertIn('reset the adjustment', self.design.message_ids[0].body)

    def test_a_copy_of_the_window_keeps_the_adjustments(self):
        key = self._piece()
        self.design.set_piece_adjustment(key, 8.0)
        copy = self.design.copy_position()
        self.assertEqual(copy.piece_adjust_ids.mapped('piece_key'), [key])
        self.assertAlmostEqual(copy.piece_adjust_ids.adjust_mm, 8.0)
        copy._explode()
        mine = self._line(key).length_mm
        theirs = copy.bom_line_ids.filtered(lambda l: l.piece_key == key)
        self.assertAlmostEqual(theirs.length_mm, mine)


@tagged('post_install', '-at_install')
class TestCopyAdjustments(TransactionCase):
    """Copy a panel's adjustments to another panel. Builds its OWN window: a
    spec with two profile lines of its own, on two Fixed panels, so the two
    panels share piece positions whatever the database holds (a database
    installed from scratch has no profile line on a panel at all)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        fixed = env['aw.leaf.type'].search([('code', '=', 'FIXED')], limit=1)
        profile = env['product.template'].search([
            ('categ_id', 'child_of', env.ref(
                'aw_fenestration_core.product_category_profiles').id)],
            limit=1)
        thickness = first_thickness(env, profile)
        positions = [env['aw.profile.position'].create({
            'name': name, 'scope': 'panel_fixed', 'is_required': False})
            for name in ('CA Rail', 'CA Stile')]
        spec = env['aw.window.template'].create({
            'name': 'CA spec', 'window_type_id': series.id,
            'profile_line_ids': [
                (0, 0, {'position_id': pos.id, 'product_tmpl_id': profile.id,
                        'thickness_id': thickness.id,
                        'length_formula': formula, 'qty_formula': '1'})
                for pos, formula in zip(positions, ('OW', 'OH'))]})
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Copy adjust customer'}).id,
            'aw_default_series_id': series.id})
        cls.design = order._create_fenestration_position(
            series, family=family, location='Hall')
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0,
                          'template_id': spec.id})
        leaf = {'width_mm': 1200.0, 'leaf_type_id': fixed.id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0,
                      'leaves': [dict(leaf), dict(leaf)]}]})

    def _pieces(self, panel):
        return self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and l.piece_key
            and (l.panel_no or 0) == panel and self.design._adjustable_line(
                l.piece_key))

    def _line(self, key):
        return self.design.bom_line_ids.filtered(
            lambda l: l.piece_key == key)

    def _payload_piece(self, key):
        pieces = self.design.get_configurator_data()['pieces']
        return next(p for p in pieces if p['piece_key'] == key)

    def _pair(self):
        """(piece key on panel 1, key of the piece in the same position on
        panel 2): the two panels have two such positions."""
        position = self.design._position_of_key
        second = {position(l.piece_key): l.piece_key for l in self._pieces(2)}
        pairs = [(l.piece_key, second[position(l.piece_key)])
                 for l in self._pieces(1) if position(l.piece_key) in second]
        self.assertEqual(len(pairs), 2, "the two panels share two positions")
        return pairs[0]

    def test_copy_takes_the_adjustment_to_the_piece_in_the_same_position(self):
        one, two = self._pair()
        before = self._line(two).length_mm
        self.design.set_piece_adjustment(one, 7.0)
        result = self.design.copy_piece_adjustments(1, 2)
        self.assertEqual(result['copied'], 1)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['refused'], 0)
        self.assertAlmostEqual(self._line(two).length_mm, before + 7.0)
        self.assertEqual(self._payload_piece(two)['adjust_mm'], 7.0)
        self.assertIn('copied the adjustments of panel 1',
                      self.design.message_ids[0].body)

    def test_copy_replaces_the_targets_own_and_leaves_its_other_pieces(self):
        one, two = self._pair()
        other = next(l.piece_key for l in self._pieces(2)
                     if l.piece_key != two)
        self.design.set_piece_adjustment(two, 20.0)
        self.design.set_piece_adjustment(one, 3.0)
        self.design.set_piece_adjustment(other, 5.0)
        self.design.copy_piece_adjustments(1, 2)
        adjustments = self.design._piece_adjustments()
        self.assertEqual(adjustments[two], 3.0)         # replaced
        self.assertEqual(adjustments[other], 5.0)       # left alone

    def test_copy_counts_what_has_no_piece_in_the_same_position(self):
        one, two = self._pair()
        self.design.set_piece_adjustment(one, 2.0)
        self.env['aw.design.piece.adjust'].create({
            'design_id': self.design.id, 'piece_key': '0|1|99|1',
            'adjust_mm': 4.0})
        result = self.design.copy_piece_adjustments(1, 2)
        self.assertEqual((result['copied'], result['skipped']), (1, 1))
        self.assertIn('skipped 1 (no piece in the same position)',
                      self.design.message_ids[0].body)

    def test_copy_with_nothing_to_copy_writes_nothing(self):
        before = len(self.design.message_ids)
        result = self.design.copy_piece_adjustments(1, 2)
        self.assertEqual(result['copied'], 0)
        self.assertFalse(self.design.piece_adjust_ids)
        self.assertEqual(len(self.design.message_ids), before)

    def test_copy_refuses_an_adjustment_that_cannot_hold_and_counts_it(self):
        one, two = self._pair()
        self.env['aw.design.piece.adjust'].create({
            'design_id': self.design.id, 'piece_key': one,
            'adjust_mm': -5000.0})
        result = self.design.copy_piece_adjustments(1, 2)
        self.assertEqual((result['copied'], result['refused']), (0, 1))
        self.assertNotIn(two, self.design._piece_adjustments())

    def test_copy_needs_another_panel(self):
        with self.assertRaises(UserError):
            self.design.copy_piece_adjustments(1, 1)
        with self.assertRaises(UserError):
            self.design.copy_piece_adjustments(0, 2)
