# -*- coding: utf-8 -*-
"""Elevation drawings at print size, the Area row, and the QR codes that no
longer make wkhtmltopdf fetch (and spawn a thread for) every one of them."""
import base64
import os
import re

from odoo.addons.aw_fenestration_design.models import elevation_print
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged

DATA = os.path.join(os.path.dirname(__file__), 'data')
SCHEDULE = 'aw_fenestration_design.report_elevation_schedule'
WINDOW_SHEETS_CALC = 'aw_fenestration_design.report_window_sheet_order_calc'
WINDOW_SHEET_CALC = 'aw_fenestration_design.report_window_sheet_calc'


def stored(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as handle:
        return handle.read()


@tagged('post_install', '-at_install')
class TestElevationPrint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Elevation customer'}).id,
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

        cls.w21 = window('Bedroom', 1219.2, 2159.0, 2)
        cls.three = window('Front', 2590.8, 2514.6, 3)
        cls.w21.write({'elevation_svg': stored('elevation_W21_two_casements.svg')})
        cls.three.write({'elevation_svg': stored('elevation_W1_three_panels.svg')})

    def _html(self, report, ids=None):
        return self.env['ir.actions.report']._render_qweb_html(
            report, ids or self.order.ids)[0].decode()

    # -- the area -------------------------------------------------------------
    def test_w21_is_28_33_sqft_and_2_63_sqm(self):
        self.assertEqual(self.w21._schedule_area(), '28.33 sqft · 2.63 sqm')

    def test_a_window_with_three_panels(self):
        self.assertEqual(self.three._schedule_area(),
                         '70.13 sqft · 6.51 sqm')

    def test_the_area_is_in_the_window_sheet_header(self):
        self.assertEqual(dict(self.w21._sheet_header())['Area'],
                         '28.33 sqft · 2.63 sqm')

    def test_the_schedule_prints_the_area_row_under_h(self):
        html = self._html(SCHEDULE)
        self.assertIn('28.33 sqft · 2.63 sqm', html)
        self.assertIn('70.13 sqft · 6.51 sqm', html)
        self.assertLess(html.index('<strong>H</strong>'),
                        html.index('<strong>Area</strong>'))

    # -- the drawing at print size --------------------------------------------
    def test_the_stored_drawing_is_redrawn_at_print_size(self):
        for design in (self.w21, self.three):
            sheet = design._elevation_print((168.0, 150.0), 10.0)
            self.assertTrue(sheet['redrawn'])
            self.assertGreaterEqual(sheet['label_pt'], 10.0 - 0.05)
            self.assertTrue(sheet['src'].startswith('data:image/svg+xml;base64,'))
            schedule = design._elevation_print((86.0, 46.0), 6.0)
            self.assertGreaterEqual(schedule['label_pt'], 5.0)
            self.assertLessEqual(schedule['width_mm'], 86.01)
            self.assertLessEqual(schedule['height_mm'], 46.01)

    def test_the_label_size_is_the_size_on_the_page(self):
        out = self.w21._elevation_print((168.0, 150.0), 10.0)
        svg = base64.b64decode(out['src'].split(',', 1)[1]).decode()
        font = max(float(m) for m in re.findall(
            r'fill="#14181b"[^>]*font-size="([\d.]+)"', svg))
        width_mm = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
        view_w = float(re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+)', svg).group(1))
        points = font * (width_mm / view_w) / elevation_print.PT_MM
        self.assertGreaterEqual(points, 10.0 - 0.05)

    def test_no_stored_svg_means_no_vector_drawing(self):
        self.w21.write({'elevation_svg': False})
        self.assertFalse(self.w21._elevation_print((86.0, 46.0), 6.0))

    def test_an_unreadable_drawing_falls_back_and_never_stops_a_report(self):
        self.w21.write({'elevation_svg': '<svg><not closed'})
        self.assertFalse(self.w21._elevation_print((86.0, 46.0), 6.0))
        self.w21.write({'elevation_png': base64.b64encode(b'\x89PNG fake')})
        html = self._html(SCHEDULE)          # the PNG is printed instead
        self.assertIn('data:image/png;base64,', html)

    def test_the_schedule_uses_the_vector_drawing(self):
        html = self._html(SCHEDULE)
        self.assertEqual(html.count('data:image/svg+xml;base64,'), 2)

    def test_the_window_sheet_uses_the_vector_drawing(self):
        html = self._html(WINDOW_SHEET_CALC, self.three.ids)
        self.assertIn('data:image/svg+xml;base64,', html)

    # -- the QR codes: no fetch, no thread --------------------------------------
    def test_a_qr_is_an_image_not_a_url(self):
        src = self.env['aw.cut.plan']._qr_src('ORDER S00001 | WINDOW W1')
        self.assertTrue(src.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(src.split(',', 1)[1])[:4],
                         b'\x89PNG')

    def test_the_whole_quote_asks_wkhtmltopdf_to_fetch_nothing(self):
        """Each /report/barcode/ image was a request and a thread; 21 windows
        meant 25 threads and an address space past the worker's 1.25 GiB, so
        the print died with 'Thread creation error' (-11)."""
        html = self._html(WINDOW_SHEETS_CALC)
        self.assertNotIn('/report/barcode', html)
        # one QR per window, embedded (the company logo may add one more)
        self.assertGreaterEqual(html.count('data:image/png;base64,'),
                                len(self.order.aw_design_ids))
        one = self._html(WINDOW_SHEET_CALC, self.w21.ids)
        self.assertNotIn('/report/barcode', one)
