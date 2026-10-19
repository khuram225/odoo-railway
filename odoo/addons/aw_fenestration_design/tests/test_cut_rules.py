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
        self.assertEqual(to_mm("33-6"), 857.25)          # dash + number is soot
        self.assertAlmostEqual(to_mm("72"), 1828.8, places=2)
        self.assertAlmostEqual(to_mm("34.125"), 866.78, places=2)
        self.assertAlmostEqual(to_mm("34 1/8"), 866.78, places=2)
        self.assertAlmostEqual(to_mm("34-1/8"), 866.78, places=2)
        self.assertAlmostEqual(to_mm("33 5/16"), 846.14, places=2)
        self.assertAlmostEqual(to_mm("33-5/16"), 846.14, places=2)
        self.assertAlmostEqual(to_mm("33-6.5"), 858.84, places=2)
        self.assertAlmostEqual(to_mm("3s"), 9.53, places=2)
        self.assertAlmostEqual(to_mm("+3s"), 9.53, places=2)
        self.assertAlmostEqual(to_mm("-1 1/2"), -38.1, places=2)
        self.assertEqual(to_mm("1829mm"), 1829.0)

    def test_to_display(self):
        for mm, text in (
                (1828.8, "72"), (1790.7, "70 1/2"), (866.8, "34 1/8"),
                (846.1, "33 5/16"), (304.79999999999995, "12"),
                (600, "23 5/8"), (1200, "47 1/4"), (731, "28 3/4"),
                (-38.1, "-1 1/2"), (0, "0")):
            self.assertEqual(to_display(mm), text, mm)

    def test_to_display_soot_style(self):
        for mm, text in (
                (1209.2, "47-5"), (3647.6, "143-5"), (1179.2, "46-3.5"),
                (3617.6, "142-3.5"), (3657.6, "144"), (866.8, "34-1"),
                (857.25, "33-6"), (0, "0"), (12.7, "0-4")):
            self.assertEqual(to_display(mm, "soot"), text, mm)

    def test_round_trip(self):
        for style in ("fraction", "soot"):
            for mm in (1209.2, 1179.2, 866.8, 3657.6, 12.7, 731, 600):
                back = to_mm(to_display(mm, style))
                self.assertEqual(round(back / 25.4 * 16),
                                 round(mm / 25.4 * 16), (style, mm))


@tagged('post_install', '-at_install')
class TestPanelOpening(TransactionCase):
    """OW / OH per panel: each edge takes half the frame deduction on the
    window's outer edge and half the divider body anywhere else."""

    def _make(self, width_in, height_in):
        env = self.env
        series = env.ref('aw_fenestration_core.window_series_casement_dg',
                         raise_if_not_found=False)
        fixed = env['aw.leaf.type'].search([('code', '=', 'FIXED')], limit=1)
        glass = env['aw.glass.spec'].search([], limit=1)
        if not (series and fixed and glass):
            raise unittest.SkipTest("Seed data is missing")
        profile = env['product.template'].search([
            ('categ_id', 'child_of', env.ref(
                'aw_fenestration_core.product_category_profiles').id)],
            limit=1)
        pos_rail = env['aw.profile.position'].create({
            'name': 'PO Rail', 'scope': 'panel_opening',
            'is_required': False})
        pos_h = env['aw.profile.position'].create({
            'name': 'PO Height', 'scope': 'panel_opening',
            'is_required': False})
        template = env['aw.window.template'].create({
            'name': 'PO spec', 'window_type_id': series.id,
            'glass_spec_id': glass.id,
            'frame_deduction_w_mm': 3 * INCH,
            'frame_deduction_h_mm': 3 * INCH,
            'divider_body_mm': 1.5 * INCH,
            'profile_line_ids': [
                (0, 0, {'position_id': pos_rail.id,
                        'product_tmpl_id': profile.id,
                        'length_formula': 'OW + soot(3)',
                        'qty_formula': '1'}),
                (0, 0, {'position_id': pos_h.id,
                        'product_tmpl_id': profile.id,
                        'length_formula': 'OH', 'qty_formula': '1'}),
            ]})
        design = env['aw.design'].create({
            'name': 'PO', 'qty': 1, 'window_series_id': series.id,
            'template_id': template.id, 'glass_spec_id': glass.id,
            'width_mm': width_in * INCH, 'height_mm': height_in * INCH})
        return design, fixed

    def _row(self, design, height_in, widths_in, fixed, parent_leaf=None):
        row = self.env['aw.design.row'].create({
            'design_id': design.id, 'height_mm': height_in * INCH,
            'parent_leaf_id': parent_leaf.id if parent_leaf else False})
        return [self.env['aw.design.leaf'].create({
            'row_id': row.id, 'width_mm': w * INCH,
            'leaf_type_id': fixed.id}) for w in widths_in]

    def _explode(self, design):
        design._renumber_panels()
        design._explode()
        by_panel = {}
        for line in design.bom_line_ids.filtered(
                lambda l: l.kind == 'profile'):
            kind = 'rail' if 'PO Rail' in (line.label or '') else 'oh'
            by_panel.setdefault(line.panel_no, {})[kind] = line.length_mm
        return by_panel

    def _build(self, width_in, height_in, widths_in):
        design, fixed = self._make(width_in, height_in)
        self._row(design, height_in, widths_in, fixed)
        return self._explode(design)

    def test_three_equal_panels(self):
        got = self._build(144, 144, [48, 48, 48])
        self.assertAlmostEqual(got[1]['rail'], 1162.05 + 9.525, places=2)
        self.assertAlmostEqual(got[2]['rail'], 1181.10 + 9.525, places=2)
        self.assertAlmostEqual(got[3]['rail'], 1162.05 + 9.525, places=2)
        self.assertAlmostEqual(got[1]['rail'], 1171.575, places=2)

    def test_four_unequal_panels(self):
        got = self._build(126, 96, [16.25, 46.75, 46.75, 16.25])
        self.assertAlmostEqual(got[1]['rail'], 355.6 + 9.525, places=2)
        self.assertAlmostEqual(got[2]['rail'], 1149.35 + 9.525, places=2)
        self.assertAlmostEqual(got[3]['rail'], 1149.35 + 9.525, places=2)
        self.assertAlmostEqual(got[4]['rail'], 355.6 + 9.525, places=2)

    def test_nested_split_top_light_over_two_across(self):
        # One container filling the opening: a top light over two sashes.
        design, fixed = self._make(72, 96)
        container = self._row(design, 96, [72], fixed)[0]
        container.leaf_type_id = False
        top = self._row(design, 24, [72], fixed, container)[0]
        low = self._row(design, 72, [36, 36], fixed, container)
        got = self._explode(design)
        panel = {leaf.id: leaf.panel_no for leaf in (top, *low)}
        # Lower sashes: frame on the outside edge and the bottom, divider
        # on the inside edge and the top.
        for leaf in low:
            self.assertAlmostEqual(
                got[panel[leaf.id]]['rail'], 857.25 + 9.525, places=2)
            self.assertAlmostEqual(
                got[panel[leaf.id]]['oh'], (72 - 1.5 - 0.75) * INCH,
                places=2)
        # Top light: frame on top and both sides, divider at the bottom.
        self.assertAlmostEqual(
            got[panel[top.id]]['rail'], (72 - 3) * INCH + 9.525, places=2)
        self.assertAlmostEqual(
            got[panel[top.id]]['oh'], (24 - 1.5 - 0.75) * INCH, places=2)

    def test_single_row_height(self):
        got = self._build(72, 72, [36, 36])
        for panel in (1, 2):
            self.assertAlmostEqual(got[panel]['oh'], 1752.6, places=2)


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

    def test_two_equal_panels_opening_is_unchanged(self):
        for panel in (1, 2):
            rails = self._pieces(self.p_rail).filtered(
                lambda l: l.panel_no == panel)
            self.assertAlmostEqual(
                rails[0].length_mm, 857.25 + 3 * 3.175, places=2)

    def test_display_precision_entry_is_not_manual(self):
        rail = self._pieces(self.p_rail)[0]
        rail.with_context(aw_bom_generating=True).write({
            'computed_length_mm': 1209.20, 'length_mm': 1209.20,
            'is_manual': False})
        # What the client sends after the user types the displayed value.
        rail.write({'length_mm': to_mm('47-5')})
        self.assertFalse(rail.is_manual)
        self.assertEqual(rail.length_mm, 1209.20)
        # An already manual line typed back to the computed length is
        # computed again.
        rail.write({'length_mm': 1215.0})
        self.assertTrue(rail.is_manual)
        rail.write({'length_mm': to_mm('47-5')})
        self.assertFalse(rail.is_manual)
        self.assertEqual(rail.length_mm, 1209.20)
        # Product changed by hand: typing the length back keeps the flag.
        other = self.env['product.product'].search(
            [('id', '!=', rail.computed_product_id.id)], limit=1)
        rail.write({'product_id': other.id})
        self.assertTrue(rail.is_manual)
        rail.write({'length_mm': to_mm('47-5')})
        self.assertTrue(rail.is_manual)
        self.assertEqual(rail.length_mm, 1209.20)
        # A real edit beyond half a sixteenth still flags it.
        rail.write({'length_mm': 1211.0})
        self.assertTrue(rail.is_manual)
        self.assertEqual(rail.length_mm, 1211.0)

    def test_sale_line_description_reads_the_size(self):
        text = self.design._prepare_sale_line_description()
        self.assertIn('72 × 72 in', text)
        self.assertIn(self.template.full_name, text)

    def test_resize_marks_the_cut_list_stale(self):
        self.design.write({'width_mm': 2000.0})
        self.assertTrue(self.design.cut_list_stale)
        self.design.action_recompute_cut_list()
        self.assertFalse(self.design.cut_list_stale)
