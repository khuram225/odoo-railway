# -*- coding: utf-8 -*-
"""The details beside an elevation drawing: the Area row, the Georgian bars
line, glass that is not chosen, and a block exactly as tall as the frame."""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged

SCHEDULE = 'aw_fenestration_design.report_elevation_schedule'
SHEET = 'aw_fenestration_design.report_elevation_sheet'


@tagged('post_install', '-at_install')
class TestElevationDetails(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Details customer'}).id,
            'aw_default_series_id': series.id})
        leaf_type = series.leaf_type_ids[0].id

        def window(location, width, height, panels):
            design = cls.order._create_fenestration_position(
                series, family=family, location=location)
            design.write({'width_mm': width, 'height_mm': height})
            leaf = {'width_mm': width / panels, 'leaf_type_id': leaf_type}
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': height,
                          'leaves': [dict(leaf) for _ in range(panels)]}]})
            return design

        cls.bars = window('Hall', 2590.8, 2514.6, 3)
        cls.plain = window('Study', 1219.2, 2159.0, 2)
        cls.pattern = env['aw.grid.pattern'].create(
            {'name': 'Georgian bars, rectangular', 'code': 'ZT-GEO',
             'kind': 'rect'})
        cls.bars._all_panels().write({
            'grid_pattern_id': cls.pattern.id, 'grid_rows': 4,
            'grid_cols': 2})

    def _rows(self, design, with_finish=False):
        return dict(design._elevation_detail_rows(with_finish))

    # -- the Area row ---------------------------------------------------------
    def test_the_area_row_has_two_decimals_in_both_units(self):
        self.assertEqual(self._rows(self.plain)['Area'],
                         '28.33 sqft · 2.63 sqm')
        self.assertEqual(self._rows(self.bars)['Area'],
                         '70.13 sqft · 6.51 sqm')

    def test_width_and_height_are_one_row_in_inches_and_millimetres(self):
        self.assertEqual(self._rows(self.plain)['W x H'],
                         '48 x 85 in (1219.2 x 2159.0 mm)')

    # -- the Georgian bars line ------------------------------------------------
    def test_panels_with_the_same_bars_are_one_line(self):
        self.assertEqual(self.bars._schedule_georgian_lines(),
                         ['P1, P2, P3: Georgian bars, rectangular, 4 x 2'])

    def test_a_different_spec_is_its_own_group(self):
        panels = self.bars._all_panels().sorted(lambda l: l.panel_no)
        panels[1].write({'grid_rows': 2, 'grid_cols': 2})
        self.assertEqual(self.bars._schedule_georgian_lines(), [
            'P1, P3: Georgian bars, rectangular, 4 x 2',
            'P2: Georgian bars, rectangular, 2 x 2'])

    def test_a_window_without_bars_has_no_georgian_row(self):
        self.assertEqual(self.plain._schedule_georgian_lines(), [])
        self.assertNotIn('Georgian bars', self._rows(self.plain))

    def test_the_row_is_on_the_sheet_and_the_schedule(self):
        for report in (SCHEDULE, SHEET):
            html = self.env['ir.actions.report']._render_qweb_html(
                report, self.order.ids if report == SCHEDULE
                else self.bars.ids)[0].decode()
            self.assertIn('<strong>Georgian bars</strong>', html)
            self.assertIn('P1, P2, P3: rectangular, 4 x 2', html)

    # -- glass that is not chosen ----------------------------------------------
    def test_no_glass_product_says_not_chosen(self):
        self.assertEqual(self._rows(self.plain)['Glass'], 'not chosen')

    # -- the block is as tall as the frame -------------------------------------
    def test_the_rows_add_up_to_the_height_of_the_frame(self):
        for design in (self.bars, self.plain):
            block = design._elevation_details(
                12.5, 80.0, 10.0, 40.0)
            self.assertEqual(block['top_mm'], 12.5)
            self.assertEqual(block['height_mm'], 80.0)
            self.assertAlmostEqual(
                sum(r['height_mm'] for r in block['rows']), 80.0, places=6)

    def test_a_row_with_more_lines_gets_more_room(self):
        block = self.bars._elevation_details(0.0, 80.0, 10.0, 30.0)
        rows = {r['label']: r for r in block['rows']}
        self.assertGreater(rows['W x H']['height_mm'],
                           rows['Qty']['height_mm'])

    def test_a_drawing_that_cannot_be_read_gets_no_fixed_heights(self):
        block = self.plain._elevation_details(None, None, 10.0, 40.0)
        self.assertEqual(block['top_mm'], 0.0)
        self.assertTrue(all(r['height_mm'] is None for r in block['rows']))

    def test_the_sheet_adds_the_finish_row(self):
        self.assertIn('Finish', self._rows(self.plain, with_finish=True))
        self.assertNotIn('Finish', self._rows(self.plain))

    # -- six to a page -----------------------------------------------------------
    def test_the_layout_fits_two_rows_of_cells_on_the_page(self):
        layout = self.order._aw_schedule_layout()
        used = layout['header_h'] + 2 * layout['cell_h']
        self.assertLess(used, 194.0 / 0.851)

    # -- Checks ------------------------------------------------------------------
    def _bar_notes(self, design):
        design.action_explode()
        return design.check_line_ids.filtered(
            lambda c: 'Georgian bars have no cost' in c.message)

    def test_bars_with_no_cost_are_an_info_line_in_checks(self):
        notes = self._bar_notes(self.bars)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes.level, 'info')
        self.assertIn('P1, P2, P3', notes.message)

    def test_no_bars_no_note(self):
        self.assertFalse(self._bar_notes(self.plain))

    def test_a_pattern_with_a_priced_line_has_no_note(self):
        product = self.env['product.product'].create(
            {'name': 'ZT bar profile'})
        self.env['aw.grid.pattern.line'].create({
            'grid_pattern_id': self.pattern.id, 'product_id': product.id,
            'qty_formula': '1'})
        self.assertFalse(self._bar_notes(self.bars))
