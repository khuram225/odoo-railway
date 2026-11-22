# -*- coding: utf-8 -*-
"""One details block for the sheet and the schedule, Design Ref order on every
report that lists windows, the header without the customer's name, and the
watermark (a switch per report, nothing without a logo, in every part of a cut
print)."""
import base64
import io
import re
from unittest import mock

from odoo.addons.aw_fenestration_design.models import print_chunks
from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.tools.pdf import PdfFileReader
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged

SCHEDULE = 'aw_fenestration_design.report_elevation_schedule'
SHEET_ORDER = 'aw_fenestration_design.report_elevation_sheet_order'
SHEET = 'aw_fenestration_design.report_elevation_sheet'
WINDOW_SHEETS = 'aw_fenestration_design.report_window_sheet_order_calc'
QUOTATION = 'sale.report_saleorder'


def pdf_with_text(pages, size=(842.0, 595.0)):
    """A PDF of `pages` pages, each with the text 'PAGE n' (what wkhtmltopdf gives
    back, as far as the watermark can tell)."""
    from reportlab.pdfgen import canvas
    packet = io.BytesIO()
    page = canvas.Canvas(packet, pagesize=size)
    for number in range(1, pages + 1):
        page.drawString(100, 300, 'PAGE %d' % number)
        page.showPage()
    page.save()
    return packet.getvalue()


def images_on(page):
    resources = page.get('/Resources')
    xobjects = resources.getObject().get('/XObject') if resources else None
    if not xobjects:
        return 0
    return sum(1 for ref in xobjects.getObject().values()
               if ref.getObject().get('/Subtype') == '/Image')


def logo_png():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGBA', (600, 300), (20, 40, 120, 255)).save(out, 'PNG')
    return base64.b64encode(out.getvalue())


@tagged('post_install', '-at_install')
class TestElevationWatermark(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        family, series = seeded_family_series(env)
        cls.partner = env['res.partner'].create({'name': 'Zebra Customer Ltd'})
        cls.order = env['sale.order'].create({
            'partner_id': cls.partner.id, 'aw_default_series_id': series.id})
        leaf_type = series.leaf_type_ids[0].id
        cls.refs = ['W1', 'W2', 'W3', 'W10', 'W11', 'W12']
        cls.designs = {}
        # made in a scrambled order, so the id order is not the natural order
        for ref in ['W11', 'W2', 'W12', 'W1', 'W10', 'W3']:
            design = cls.order._create_fenestration_position(
                series, family=family, location='Loc ' + ref)
            design.write({'name': ref, 'width_mm': 1000.0, 'height_mm': 1200.0})
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': 1200.0, 'leaves': [
                    {'width_mm': 1000.0, 'leaf_type_id': leaf_type}]}]})
            cls.designs[ref] = design
        cls.company = cls.order.company_id
        cls.company.logo = logo_png()
        cls.params = env['ir.config_parameter'].sudo()

    def setUp(self):
        super().setUp()
        from odoo.addons.aw_fenestration_design.models import watermark
        watermark._CACHE.clear()

    def _html(self, report, ids=None):
        return self.env['ir.actions.report']._render_qweb_html(
            report, ids or self.order.ids)[0].decode()

    # -- order ---------------------------------------------------------------
    def test_windows_come_in_design_ref_order(self):
        names = self.order._aw_elevation_designs().mapped('name')
        self.assertEqual(names, self.refs)

    def test_w1_w2_w3_w10_w11_w12_on_every_report(self):
        for report in (SCHEDULE, SHEET_ORDER, WINDOW_SHEETS):
            found = []
            for match in re.finditer(r'Loc (W\d+)', self._html(report)):
                if match.group(1) not in found:
                    found.append(match.group(1))
            self.assertEqual(found, self.refs, report)

    def test_a_ref_with_dots_and_a_ref_without_digits(self):
        self.designs['W3'].name = 'W1.1'
        self.designs['W12'].name = 'GF-BATH'
        names = self.order._aw_elevation_designs().mapped('name')
        self.assertEqual(names, ['W1', 'W1.1', 'W2', 'W10', 'W11', 'GF-BATH'])

    def test_ties_go_by_id(self):
        self.designs['W2'].name = 'W5'
        self.designs['W11'].name = 'W5'
        five = [d for d in self.order._aw_elevation_designs()
                if d.name == 'W5']
        self.assertEqual(five, sorted(five, key=lambda d: d.id))

    def test_the_quote_lines_keep_their_own_order(self):
        lines = self.order.order_line.sorted('sequence')
        self.assertEqual(
            [l.aw_design_ids.name for l in lines if l.aw_design_ids],
            ['W11', 'W2', 'W12', 'W1', 'W10', 'W3'])

    # -- one details block -----------------------------------------------------
    def test_the_sheet_and_the_schedule_print_the_same_rows(self):
        design = self.designs['W1']
        layout = self.order._aw_schedule_layout()
        sheet = design._sheet_cell()['details']['rows']
        cell = design._schedule_cell(layout)['details']['rows']
        self.assertEqual([(r['label'], r['text']) for r in sheet],
                         [(r['label'], r['text']) for r in cell])
        self.assertEqual(
            [r['label'] for r in sheet],
            ['Design Ref', 'Qty', 'Location', 'W', 'H', 'Area', 'Glass',
             'Finish'])

    def test_both_reports_call_the_one_template(self):
        for xmlid in ('aw_fenestration_design.report_elevation_sheet_document',
                      'aw_fenestration_design.report_elevation_schedule'):
            self.assertIn('report_elevation_details',
                          self.env.ref(xmlid).arch_db)

    # -- the header ------------------------------------------------------------
    def test_no_customer_name_on_the_elevation_reports(self):
        for report, ids in ((SCHEDULE, None), (SHEET_ORDER, None),
                            (SHEET, self.designs['W1'].ids)):
            self.assertNotIn('Zebra Customer', self._html(report, ids), report)

    def test_the_order_number_comes_before_the_date(self):
        html = self._html(SCHEDULE)
        date = self.order.date_order.strftime('%d %b %Y')
        # <span>S00003</span> &#183; <span data-oe-type="date" ...>22 Nov 2026</span>
        self.assertRegex(
            html, re.escape('<span>%s</span>' % self.order.name)
            + r'\s*(?:·|&#183;)\s*<span[^>]*>' + re.escape(date) + '</span>')

    # -- the watermark: stamped on the finished PDF, behind every page ----------
    def _print(self, report_name, bodies, pages_per_run=None):
        """Print `bodies` as `report_name` with wkhtmltopdf replaced by a recorder
        that returns a PDF of `pages_per_run` pages (one per body by default)."""
        calls = []

        def fake(report, given, **kwargs):
            calls.append(list(given))
            return pdf_with_text(pages_per_run or len(given))

        with mock.patch.object(IrActionsReport, '_run_wkhtmltopdf', fake):
            report = self.env['ir.actions.report']._get_report_from_name(
                report_name)
            pdf = report._run_wkhtmltopdf(bodies, report_ref=report.id)
        return calls, PdfFileReader(io.BytesIO(pdf), strict=False)

    def test_watermark_behind_every_page_of_the_three_reports(self):
        for report in ('aw_fenestration_design.report_elevation_sheet',
                       'aw_fenestration_design.report_elevation_sheet_order',
                       'aw_fenestration_design.report_elevation_schedule',
                       'sale.report_saleorder'):
            _calls, pdf = self._print(report, ['<p>x</p>'], pages_per_run=4)
            self.assertEqual(pdf.getNumPages(), 4, report)
            for number in range(4):
                page = pdf.getPage(number)
                self.assertEqual(images_on(page), 1, (report, number))
                # the page itself is still there, on top
                self.assertIn('PAGE %d' % (number + 1), page.extractText())

    def test_the_page_keeps_its_size(self):
        _calls, pdf = self._print(SCHEDULE, ['<p>x</p>'], pages_per_run=2)
        box = pdf.getPage(0).mediaBox
        self.assertAlmostEqual(float(box.getWidth()), 842.0, places=1)
        self.assertAlmostEqual(float(box.getHeight()), 595.0, places=1)

    def test_the_switch_per_report(self):
        reports = {'sheet': 'aw_fenestration_design.report_elevation_sheet_order',
                   'schedule': 'aw_fenestration_design.report_elevation_schedule',
                   'quotation': 'sale.report_saleorder'}
        for off in reports:
            self.params.set_param('aw_fenestration.watermark_%s' % off, 'off')
            for key, report in reports.items():
                _calls, pdf = self._print(report, ['<p>x</p>'], pages_per_run=2)
                self.assertEqual(images_on(pdf.getPage(0)),
                                 0 if key == off else 1, (off, key))
            self.params.set_param('aw_fenestration.watermark_%s' % off, 'on')

    def test_no_logo_no_watermark_and_no_error(self):
        self.company.logo = False
        for report in (SCHEDULE, SHEET_ORDER, QUOTATION):
            _calls, pdf = self._print(report, ['<p>x</p>'], pages_per_run=2)
            self.assertEqual(pdf.getNumPages(), 2)
            self.assertEqual(images_on(pdf.getPage(0)), 0, report)

    def test_a_logo_that_is_not_an_image_is_no_watermark_and_no_error(self):
        """Odoo will not store bytes that are not an image in the logo field, so
        the image step is made to fail or to give nothing, which is what a logo it
        cannot read does."""
        from odoo.addons.aw_fenestration_design.models import watermark_image
        from odoo.addons.aw_fenestration_design.models import watermark
        for outcome in ({'return_value': None}, {'side_effect': ValueError('x')}):
            watermark._CACHE.clear()
            with mock.patch.object(watermark_image, 'watermark', **outcome):
                _calls, pdf = self._print(
                    SCHEDULE, ['<p>x</p>'], pages_per_run=2)
            self.assertEqual(pdf.getNumPages(), 2)
            self.assertEqual(images_on(pdf.getPage(0)), 0)
        watermark._CACHE.clear()

    def test_stickers_cutting_sheet_and_cut_summary_are_not_watermarked(self):
        from odoo.addons.aw_fenestration_design.models import report_chunks
        for name in ('aw_fenestration_design.report_cut_labels',
                     'aw_fenestration_design.report_cut_labels_thermal',
                     'aw_fenestration_design.report_cutting_sheet',
                     'aw_fenestration_design.report_shop_drawing',
                     'aw_fenestration_design.report_window_sheet_order_calc'):
            self.assertNotIn(name, report_chunks.WATERMARKED)
        self.assertEqual(
            set(report_chunks.WATERMARKED.values()),
            {'sheet', 'schedule', 'quotation'})
        _calls, pdf = self._print(
            'aw_fenestration_design.report_cut_labels', ['<p>x</p>'],
            pages_per_run=3)
        self.assertEqual(images_on(pdf.getPage(0)), 0)

    def test_every_part_of_a_cut_print_is_stamped(self):
        """An order of many sheets is printed in parts, each its own wkhtmltopdf
        run, and put together before the watermark goes on: every page has it."""
        design = self.designs['W1']
        for _ in range(24):
            design.copy_position()
        report = self.env.ref(
            'aw_fenestration_design.action_report_aw_elevation_sheet_order')
        html = self.env['ir.actions.report']._render_qweb_html(
            SHEET_ORDER, self.order.ids)[0]
        bodies, _ids, _h, _f, _s = report._prepare_html(
            html, report_model='sale.order')
        calls, pdf = self._print(SHEET_ORDER, bodies)
        self.assertGreater(len(calls), 1)
        self.assertEqual(pdf.getNumPages(), len(calls))
        for number in range(pdf.getNumPages()):
            self.assertEqual(images_on(pdf.getPage(number)), 1, number)
