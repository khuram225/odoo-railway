# -*- coding: utf-8 -*-
"""Rule-based cut list: lengths from formulas in inches and soot, edits
that survive a recompute, lines cut on site.

The acceptance case is a two-sash window with a divider, 72 in x 72 in,
built from a template whose rules read the way the workshop says them:
H - inch(1.5), OW + soot(3), H - inch(2).

OW = (W - frame deduction - dividers x divider body) / panels
   = (1828.8 - 76.2 - 38.1) / 2 = 857.25 mm, so a rail is
   857.25 + 3 soot = 866.775 mm.

Panel quantities are written per PANEL ('2' for the stiles of one sash),
because a panel line is evaluated once for every panel in the layout:
two sashes make four stiles.
"""
import unittest

from odoo.addons.aw_fenestration_core.models.units import to_display, to_mm
from odoo.tests import TransactionCase, tagged

INCH = 25.4


@tagged('post_install', '-at_install')
class TestUnits(TransactionCase):
    """The helper alone; needs no data."""

    def test_to_mm(self):
        self.assertEqual(to_mm("33-6"), 857.25)          # dash is soot
        self.assertAlmostEqual(to_mm("72"), 1828.8, places=2)
        self.assertAlmostEqual(to_mm("34 1/8"), 866.78, places=2)
        self.assertAlmostEqual(to_mm("34⅛"), 866.78, places=2)
        self.assertAlmostEqual(to_mm("3s"), 9.53, places=2)
        self.assertAlmostEqual(to_mm("+3s"), 9.53, places=2)
        self.assertAlmostEqual(to_mm("-1 1/2"), -38.1, places=2)
        self.assertEqual(to_mm("1829mm"), 1829.0)

    def test_to_display(self):
        self.assertEqual(to_display(866.8), "34⅛")
        self.assertEqual(to_display(1790.7), "70½")
        self.assertEqual(to_display(857.25), "33¾")


@tagged('post_install', '-at_install')
class TestCutRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.series = env.ref('aw_fenestration_core.window_series_casement_dg',
                             raise_if_not_found=False)
        cls.casement = env['aw.leaf.type'].search(
            [('code', '=', 'CASEMENT')], limit=1)
        cls.glass = env['aw.glass.spec'].search([], limit=1)
        if not (cls.series and cls.casement and cls.glass):
            raise unittest.SkipTest(
                "Seed data for the cut-rules test is missing")
        profiles = env['product.template'].search(
            [('categ_id', 'child_of', env.ref(
                'aw_fenestration_core.product_category_profiles').id)])

        def profile(code):
            found = profiles.filtered(lambda p: p.default_code == code)[:1]
            return found or profiles[:1]

        def position(name, scope):
            return env['aw.profile.position'].create({
                'name': name, 'scope': scope, 'is_required': False})

        cls.p_frame_w = position('CR Frame W', 'frame')
        cls.p_frame_h = position('CR Frame H', 'frame')
        cls.p_divider = position('CR Divider', 'junction_mullion')
        cls.p_stile = position('CR Stile', 'panel_opening')
        cls.p_rail = position('CR Rail', 'panel_opening')
        cls.p_bead = position('CR Bead', 'panel_opening')

        def line(pos, code, length, qty, **extra):
            return (0, 0, dict({
                'position_id': pos.id,
                'product_tmpl_id': profile(code).id,
                'length_formula': length, 'qty_formula': qty,
            }, **extra))

        cls.template = env['aw.window.template'].create({
            'name': 'RE openable, 2 sash + divider',
            'window_type_id': cls.series.id,
            'glass_spec_id': cls.glass.id,
            'panel_count': 2, 'divider_count': 1,
            'frame_deduction_w_mm': 3 * INCH,
            'frame_deduction_h_mm': 3 * INCH,
            'divider_body_mm': 1.5 * INCH,
            'glass_sash_w': 'OW - inch(5.5)',
            'profile_line_ids': [
                line(cls.p_frame_w, 'RE-8', 'W', '2'),
                line(cls.p_frame_h, 'RE-8', 'H', '2'),
                line(cls.p_divider, 'RE-1', 'H - inch(2)', '1'),
                line(cls.p_stile, 'RE-15', 'H - inch(1.5)', '2'),
                line(cls.p_rail, 'RE-15', 'OW + soot(3)', '2'),
                line(cls.p_bead, 'RE-10', '', '4', cut_on_site=True),
            ],
        })
        cls.design = env['aw.design'].create({
            'name': 'CR1', 'qty': 1,
            'window_series_id': cls.series.id,
            'template_id': cls.template.id,
            'glass_spec_id': cls.glass.id,
            'width_mm': 72 * INCH, 'height_mm': 72 * INCH,
        })
        row = env['aw.design.row'].create({
            'design_id': cls.design.id, 'height_mm': 72 * INCH})
        for hinge in ('left', 'right'):
            env['aw.design.leaf'].create({
                'row_id': row.id, 'width_mm': 36 * INCH,
                'leaf_type_id': cls.casement.id, 'hinge_side': hinge,
                'swing': 'out'})
        cls.design._renumber_panels()
        cls.design._explode()

    def _pieces(self, position):
        return self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile' and position.name in (l.label or ''))

    def test_lengths_and_quantities(self):
        for position, length, count in (
                (self.p_frame_w, 1828.8, 2),
                (self.p_frame_h, 1828.8, 2),
                (self.p_divider, 1778.0, 1),
                (self.p_stile, 1790.7, 4),
                (self.p_rail, 866.775, 4)):
            pieces = self._pieces(position)
            self.assertEqual(sum(pieces.mapped('qty')), count, position.name)
            for piece in pieces:
                self.assertAlmostEqual(piece.length_mm, length, places=1,
                                       msg=position.name)

    def test_cut_on_site_has_pieces_and_no_length(self):
        beads = self._pieces(self.p_bead)
        self.assertEqual(sum(beads.mapped('qty')), 8)
        self.assertTrue(all(b.cut_on_site and not b.length_mm for b in beads))
        self.assertFalse(beads[0].length_text)

    def test_glass_uses_the_opening(self):
        glass = self.design.bom_line_ids.filtered(lambda l: l.kind == 'glass')
        self.assertTrue(glass)
        for piece in glass:
            self.assertAlmostEqual(
                piece.glass_w, 857.25 - 5.5 * INCH, places=1)

    def test_manual_edit_survives_recompute(self):
        design = self.design
        rails = self._pieces(self.p_rail)
        before = {l.piece_key: l.length_mm
                  for l in design.bom_line_ids if l.kind == 'profile'}
        rail = rails[0]
        key = rail.piece_key
        rail.length_mm = 870.0
        self.assertTrue(rail.is_manual)

        # A line added by hand, which a recompute must never touch.
        extra = self.env['aw.design.bom.line'].create({
            'design_id': design.id, 'kind': 'profile', 'label': 'extra',
            'length_mm': 500.0, 'qty': 1,
            'is_free_form': True, 'is_manual': True})

        design.action_recompute_cut_list()

        kept = design.bom_line_ids.filtered(lambda l: l.piece_key == key)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept.length_mm, 870.0)
        self.assertTrue(kept.is_manual)
        self.assertAlmostEqual(kept.computed_length_mm, 866.775, places=1)
        self.assertTrue(extra.exists())
        self.assertEqual(extra.length_mm, 500.0)
        for line in design.bom_line_ids.filtered(
                lambda l: l.kind == 'profile' and l.piece_key
                and l.piece_key != key):
            self.assertFalse(line.is_manual)
            self.assertAlmostEqual(
                line.length_mm, before[line.piece_key], places=2)

    def test_manual_line_without_a_piece_is_an_orphan(self):
        design = self.design
        rail = self._pieces(self.p_rail).filtered(
            lambda l: l.panel_no == 2)[0]
        rail.length_mm = 870.0
        design.row_ids.leaf_ids.filtered(lambda l: l.panel_no == 2).unlink()
        design.action_recompute_cut_list()
        orphans = design.bom_line_ids.filtered('is_orphan')
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans.length_mm, 870.0)
        self.assertTrue(orphans.is_manual)
        self.assertEqual(design.orphan_count, 1)
        # Lines that still have a piece are not orphans.
        self.assertFalse(design.bom_line_ids.filtered(
            lambda l: l.is_manual and not l.is_orphan))

    def test_resize_marks_the_cut_list_stale(self):
        self.design.write({'width_mm': 2000.0})
        self.assertTrue(self.design.cut_list_stale)
        self.design.action_recompute_cut_list()
        self.assertFalse(self.design.cut_list_stale)
