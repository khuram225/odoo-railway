# -*- coding: utf-8 -*-
"""A copy takes its source's drawing (Make copies, Duplicate position), says so when
its size later differs, the quotation leaves such a picture out, and a hand-run
backfill gives older copies a drawing."""
import base64
import io
import os

from odoo.addons.aw_fenestration_design.models import drawing_mark
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged

DATA = os.path.join(os.path.dirname(__file__), 'data')
SCHEDULE = 'aw_fenestration_design.report_elevation_schedule'
SHEET_ORDER = 'aw_fenestration_design.report_elevation_sheet_order'
QUOTATION = 'sale.report_saleorder'
SIZE_NOTE = 'Drawing from the source window: size differs'
LAYOUT_NOTE = 'Drawing from the source window: layout differs'
OWN_NOTE = 'Drawing out of date'


def png_b64():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (60, 40), (30, 90, 160)).save(out, 'PNG')
    return base64.b64encode(out.getvalue())


def svg_text():
    with open(os.path.join(DATA, 'elevation_W21_two_casements.svg'),
              encoding='utf-8') as handle:
        return handle.read()


@tagged('post_install', '-at_install')
class TestCopyDrawing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.family, cls.series = seeded_family_series(env)
        cls.leaf_type = cls.series.leaf_type_ids[0].id
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create(
                {'name': 'Copy drawing customer'}).id,
            'aw_default_series_id': cls.series.id})
        cls.source = cls._window(cls.order, 'Source', 1219.2, 2159.0, 2)
        cls._draw(cls.source)

    @classmethod
    def _window(cls, order, location, width, height, panels):
        design = order._create_fenestration_position(
            cls.series, family=cls.family, location=location)
        design.write({'width_mm': width, 'height_mm': height})
        leaf = {'width_mm': width / panels, 'leaf_type_id': cls.leaf_type}
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': height,
                      'leaves': [dict(leaf) for _ in range(panels)]}]})
        return design

    @classmethod
    def _draw(cls, design):
        """What the configurator stores when the window is saved."""
        design.write({'elevation_svg': svg_text(),
                      'elevation_png': png_b64()})
        design.elevation_hash = design._layout_fingerprint()

    def _html(self, report, ids=None):
        return self.env['ir.actions.report']._render_qweb_html(
            report, ids or self.order.ids)[0].decode()

    # -- a copy takes the drawing ----------------------------------------------
    def test_a_copy_has_the_sources_drawing_and_it_is_current(self):
        copy = self.source.copy_position()
        self.assertTrue(copy.elevation_svg)
        self.assertTrue(copy.elevation_png)
        self.assertTrue(copy.elevation_is_current)
        self.assertEqual(copy.elevation_hash, self.source.elevation_hash)
        self.assertEqual(copy.elevation_date, self.source.elevation_date)
        self.assertEqual(copy._elevation_print_note(), '')

    def test_the_picture_is_stored_once(self):
        copy = self.source.copy_position()
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'aw.design'), ('res_field', '=', 'elevation_png'),
            ('res_id', 'in', (self.source.id, copy.id))])
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].checksum, attachments[1].checksum)
        if attachments[0].store_fname:       # a file store names it by content
            self.assertEqual(attachments[0].store_fname,
                             attachments[1].store_fname)

    def test_make_copies_gives_every_copy_a_drawing_that_prints(self):
        wizard = self.env['aw.design.copies.wizard'].create({
            'design_id': self.source.id, 'locations': 'Hall\nKitchen\nStudy'})
        wizard.action_make()
        copies = self.env['aw.design'].search([
            ('sale_order_id', '=', self.order.id),
            ('location', 'in', ('Hall', 'Kitchen', 'Study'))])
        self.assertEqual(len(copies), 3)
        for copy in copies:
            self.assertTrue(copy.elevation_is_current, copy.location)
            self.assertTrue(copy._elevation_print((60.0, 80.0), 6.0),
                            copy.location)
        html = self._html(SCHEDULE)
        self.assertNotIn('No drawing', html)
        self.assertNotIn(OWN_NOTE, html)

    def test_the_copy_is_marked_with_its_source(self):
        copy = self.source.copy_position()
        self.assertEqual(
            drawing_mark.read_mark(copy.elevation_svg),
            (self.source.name, drawing_mark.size_text(1219.2, 2159.0)))
        # the source's own drawing is not marked
        self.assertIsNone(drawing_mark.read_mark(self.source.elevation_svg))

    def test_a_copy_of_a_copy_names_the_original(self):
        first = self.source.copy_position()
        second = first.copy_position()
        self.assertEqual(drawing_mark.read_mark(second.elevation_svg)[0],
                         self.source.name)
        self.assertTrue(second.elevation_is_current)

    # -- never a wrong picture ---------------------------------------------------
    def test_a_stale_source_gives_its_copy_nothing(self):
        self.source.elevation_hash = 'taken from an older layout'
        copy = self.source.copy_position()
        self.assertFalse(copy.elevation_svg)
        self.assertFalse(copy.elevation_png)

    def test_a_source_with_no_drawing_gives_its_copy_nothing(self):
        bare = self._window(self.order, 'Bare', 1000.0, 1200.0, 1)
        self.assertFalse(bare.copy_position().elevation_svg)

    def test_a_layout_that_is_not_the_sources_is_not_given_its_picture(self):
        other = self._window(self.order, 'Wider', 1500.0, 2159.0, 2)
        self.assertFalse(other._copy_drawing_from(self.source))
        self.assertFalse(other.elevation_svg)

    def test_another_finish_is_not_given_the_picture(self):
        finish = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        spare = self.env['product.attribute.value'].create(
            {'name': 'ZT other finish', 'attribute_id': finish.id})
        twin = self._window(self.order, 'Twin', 1219.2, 2159.0, 2)
        self.assertEqual(twin._layout_fingerprint(), self.source.elevation_hash)
        twin.finish_id = spare
        self.assertFalse(twin._copy_drawing_from(self.source))
        self.assertFalse(twin.elevation_svg)

    # -- a copy whose size changes later ------------------------------------------
    def test_a_resized_copy_says_it_is_the_sources_picture(self):
        copy = self.source.copy_position()
        copy.width_mm = copy.width_mm + 100.0
        self.assertFalse(copy.elevation_is_current)
        self.assertEqual(copy._elevation_print_note(), SIZE_NOTE)
        self.assertIn(SIZE_NOTE, copy._elevation_warning())
        for report in (SCHEDULE, SHEET_ORDER):
            self.assertIn(SIZE_NOTE, self._html(report), report)

    def test_a_copy_with_a_changed_layout_says_layout_differs(self):
        copy = self.source.copy_position()
        panel = copy._all_panels()[:1]
        panel.write({'hinge_side': 'left' if panel.hinge_side != 'left'
                     else 'right'})
        self.assertFalse(copy.elevation_is_current)
        self.assertEqual(copy._elevation_print_note(), LAYOUT_NOTE)

    def test_the_quotation_leaves_out_a_copys_picture_that_no_longer_matches(self):
        copy = self.source.copy_position()
        before = self._html(QUOTATION)
        self.assertNotIn(SIZE_NOTE, before)
        copy.width_mm = copy.width_mm + 100.0
        after = self._html(QUOTATION)
        self.assertEqual(after.count('data:image/png;base64,'),
                         before.count('data:image/png;base64,') - 1)
        self.assertIn(SIZE_NOTE, after)

    def test_the_quotation_leaves_out_a_windows_own_stale_picture(self):
        before = self._html(QUOTATION)
        self.source.width_mm = self.source.width_mm + 100.0
        after = self._html(QUOTATION)
        self.assertEqual(after.count('data:image/png;base64,'),
                         before.count('data:image/png;base64,') - 1)
        self.assertIn(OWN_NOTE, after)

    def test_the_quotation_prints_a_current_picture_with_no_note(self):
        copy = self.source.copy_position()
        html = self._html(QUOTATION)
        self.assertNotIn(OWN_NOTE, html)
        self.assertNotIn(SIZE_NOTE, html)
        self.assertGreaterEqual(html.count('data:image/png;base64,'), 2)
        self.assertTrue(copy.elevation_is_current)

    def test_opening_and_saving_the_copy_clears_the_mark(self):
        copy = self.source.copy_position()
        copy.width_mm = copy.width_mm + 100.0
        copy._store_elevation({'svg': svg_text(), 'png': png_b64()})
        self.assertIsNone(drawing_mark.read_mark(copy.elevation_svg))
        self.assertTrue(copy.elevation_is_current)
        self.assertEqual(copy._elevation_print_note(), '')

    def test_a_window_that_drew_itself_keeps_the_old_wording(self):
        self.source.width_mm = self.source.width_mm + 100.0
        self.assertEqual(self.source._elevation_print_note(), OWN_NOTE)

    def test_no_drawing_at_all_has_no_note(self):
        bare = self._window(self.order, 'Bare', 1000.0, 1200.0, 1)
        self.assertEqual(bare._elevation_print_note(), '')

    # -- the one-time backfill ------------------------------------------------------
    def test_the_backfill_finds_and_fills_older_copies(self):
        # made before copies took the drawing: same quote, finish and layout
        old = self._window(self.order, 'Old copy', 1219.2, 2159.0, 2)
        elsewhere = self._window(
            self.env['sale.order'].create({
                'partner_id': self.order.partner_id.id,
                'aw_default_series_id': self.series.id}),
            'Other quote', 1219.2, 2159.0, 2)
        wider = self._window(self.order, 'Wider', 1500.0, 2159.0, 2)
        Design = self.env['aw.design']
        found = {d.id: s for q, d, s in Design._aw_twin_drawing_report()
                 if d.sale_order_id == self.order or d == elsewhere}
        self.assertEqual(set(found), {old.id})
        self.assertEqual(found[old.id], self.source)
        # counting wrote nothing
        self.assertFalse(old.elevation_svg)
        Design._aw_twin_drawing_report(apply=True)
        self.assertTrue(old.elevation_is_current)
        self.assertEqual(drawing_mark.read_mark(old.elevation_svg)[0],
                         self.source.name)
        self.assertFalse(elsewhere.elevation_svg)
        self.assertFalse(wider.elevation_svg)
        # and a second run has nothing left to do for it
        again = [d for q, d, s in Design._aw_twin_drawing_report()
                 if d == old]
        self.assertFalse(again)

    def test_the_backfill_count_says_why_a_window_is_skipped(self):
        Design = self.env['aw.design']
        finish = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        spare = self.env['product.attribute.value'].create(
            {'name': 'ZT skip finish', 'attribute_id': finish.id})
        fills = self._window(self.order, 'Fills', 1219.2, 2159.0, 2)
        other_finish = self._window(self.order, 'Other finish', 1219.2, 2159.0, 2)
        other_finish.finish_id = spare
        wider = self._window(self.order, 'Wider', 1500.0, 2159.0, 2)
        stale = self._window(self.order, 'Stale source', 900.0, 1200.0, 1)
        self._draw(stale)
        stale_twin = self._window(self.order, 'Stale twin', 900.0, 1200.0, 1)
        stale.width_mm = 950.0          # its drawing is now out of date
        lonely_order = self.env['sale.order'].create({
            'partner_id': self.order.partner_id.id,
            'aw_default_series_id': self.series.id})
        lonely = self._window(lonely_order, 'Lonely', 1000.0, 1000.0, 1)
        skipped = Design._aw_twin_drawing_skips()
        where = {d.id: reason for reason, rows in skipped.items()
                 for _q, d in rows}
        self.assertNotIn(fills.id, where)       # it is filled, not skipped
        self.assertEqual(where[other_finish.id], 'finish_differs')
        self.assertEqual(where[wider.id], 'size_or_layout_differs')
        self.assertEqual(where[stale_twin.id], 'source_not_current')
        self.assertEqual(where[lonely.id], 'no_twin')
        # each window is in one group only, and counting wrote nothing
        listed = [d.id for rows in skipped.values() for _q, d in rows]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertFalse(fills.elevation_svg)
        self.assertFalse(lonely.elevation_svg)

    # -- the quote's drawing check ----------------------------------------------------
    def test_each_window_has_one_drawing_state(self):
        copy = self.source.copy_position()
        bare = self._window(self.order, 'Bare', 1000.0, 1200.0, 1)
        stale = self._window(self.order, 'Stale', 1100.0, 1200.0, 1)
        self._draw(stale)
        stale.width_mm = 1300.0
        resized = self.source.copy_position()
        resized.width_mm = resized.width_mm + 50.0
        self.assertEqual(self.source._elevation_state(), 'ok')
        self.assertEqual(copy._elevation_state(), 'ok')
        self.assertEqual(bare._elevation_state(), 'none')
        self.assertEqual(stale._elevation_state(), 'stale')
        self.assertEqual(resized._elevation_state(), 'copy')

    def test_a_quote_with_current_drawings_has_no_warning(self):
        self.source.copy_position()
        self.order.invalidate_recordset()
        self.assertEqual(self.order.aw_drawing_issue_count, 0)
        self.assertFalse(self.order.aw_drawing_issue_html)

    def test_the_quote_lists_the_windows_that_would_print_a_grey_note(self):
        bare = self._window(self.order, 'Hall', 1000.0, 1200.0, 1)
        stale = self._window(self.order, 'Study', 1100.0, 1200.0, 1)
        self._draw(stale)
        stale.width_mm = 1300.0
        resized = self.source.copy_position()
        resized.write({'width_mm': resized.width_mm + 50.0,
                       'location': 'Garage'})
        fine = self.source.copy_position()
        self.order.invalidate_recordset()
        self.assertEqual(self.order.aw_drawing_issue_count, 3)
        html = str(self.order.aw_drawing_issue_html)
        self.assertIn('3 window(s) have no current drawing.', html)
        self.assertIn('%s (Hall): no drawing yet' % bare.name, html)
        self.assertIn('%s (Study): drawing out of date' % stale.name, html)
        self.assertIn('%s (Garage): %s' % (resized.name, SIZE_NOTE), html)
        self.assertNotIn(fine.name + ' (', html)

    def test_the_warning_is_for_a_quotation_still_being_made(self):
        self._window(self.order, 'Hall', 1000.0, 1200.0, 1)
        self.order.invalidate_recordset()
        self.assertEqual(self.order.aw_drawing_issue_count, 1)
        self.order.write({'state': 'sale'})
        self.order.invalidate_recordset()
        self.assertEqual(self.order.aw_drawing_issue_count, 0)

    def test_an_archived_window_is_not_counted(self):
        bare = self._window(self.order, 'Hall', 1000.0, 1200.0, 1)
        bare.active = False
        self.order.invalidate_recordset()
        self.assertEqual(self.order.aw_drawing_issue_count, 0)

    def test_the_names_are_escaped(self):
        bare = self._window(self.order, 'Hall', 1000.0, 1200.0, 1)
        bare.name = '<b>W1</b>'
        self.order.invalidate_recordset()
        html = str(self.order.aw_drawing_issue_html)
        self.assertNotIn('<b>W1</b>', html)
        self.assertIn('&lt;b&gt;W1&lt;/b&gt;', html)

    def test_the_quotation_form_shows_the_warning(self):
        arch = self.env['sale.order'].get_view(
            self.env.ref('sale.view_order_form').id)['arch']
        self.assertIn('aw_drawing_issue_html', arch)
