# -*- coding: utf-8 -*-
"""A report of ours is printed in groups and put together after, so the memory of a
print does not grow with the quote. wkhtmltopdf itself is replaced by a recorder (CI
has none): what is checked is what it is GIVEN and what comes back."""
import io
from unittest import mock

from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.aw_fenestration_design.models import print_chunks
from odoo.tests import TransactionCase, tagged
from odoo.tools.pdf import PdfFileReader, PdfFileWriter

WINDOW_SHEETS = 'aw_fenestration_design.action_report_aw_window_sheet_order_calc'


def pdf_of(pages):
    writer = PdfFileWriter()
    for _ in range(pages):
        writer.addBlankPage(100, 100)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def header_of(count):
    return ('<!DOCTYPE html><html><head></head><body>'
            '<div id="minimal_layout_report_headers">'
            + ''.join('<div class="header">H%d</div>' % i for i in range(count))
            + '</div></body></html>')


@tagged('post_install', '-at_install')
class TestPrintChunks(TransactionCase):

    def _print(self, xmlid, bodies, header=None, footer=None):
        calls = []

        def fake(report, given, **kwargs):
            calls.append({'bodies': list(given), **kwargs})
            return pdf_of(len(given))

        with mock.patch.object(IrActionsReport, '_run_wkhtmltopdf', fake):
            report = self.env.ref(xmlid)
            pdf = report._run_wkhtmltopdf(
                bodies, report_ref=xmlid, header=header, footer=footer)
        return calls, PdfFileReader(io.BytesIO(pdf)).getNumPages()

    def test_a_big_report_is_printed_in_groups_and_joined(self):
        bodies = ['<p>w%d</p>' % i for i in range(25)]
        calls, pages = self._print(WINDOW_SHEETS, bodies)
        self.assertEqual([len(c['bodies']) for c in calls], [10, 10, 5])
        self.assertEqual(pages, 25)
        self.assertEqual([b for c in calls for b in c['bodies']], bodies)

    def test_a_small_report_is_one_run(self):
        calls, pages = self._print(WINDOW_SHEETS, ['<p>a</p>', '<p>b</p>'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(pages, 2)

    def test_each_run_gets_the_header_of_its_own_windows(self):
        bodies = ['<p>w%d</p>' % i for i in range(23)]
        calls, _pages = self._print(
            WINDOW_SHEETS, bodies, header=header_of(23), footer=header_of(23)
            .replace('headers', 'footers'))
        for number, call in enumerate(calls):
            first = number * 10
            for n in range(len(call['bodies'])):
                self.assertIn('H%d' % (first + n), call['header'])
            self.assertEqual(call['header'].count('class="header"'),
                             len(call['bodies']))
            self.assertNotIn('H%d' % (first + 10), call['header'])

    def test_the_group_size_is_a_setting_and_zero_means_one_run(self):
        bodies = ['<p>w%d</p>' % i for i in range(25)]
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('aw_fenestration.print_chunk', '5')
        calls, pages = self._print(WINDOW_SHEETS, bodies)
        self.assertEqual(len(calls), 5)
        self.assertEqual(pages, 25)
        params.set_param('aw_fenestration.print_chunk', '0')
        calls, pages = self._print(WINDOW_SHEETS, bodies)
        self.assertEqual(len(calls), 1)
        self.assertEqual(pages, 25)

    def test_a_report_that_is_not_ours_is_left_alone(self):
        bodies = ['<p>w%d</p>' % i for i in range(25)]
        calls, _pages = self._print('sale.action_report_saleorder', bodies)
        self.assertEqual(len(calls), 1)

    def test_a_body_made_of_units_is_cut_between_them(self):
        unit = '<div style="%s">s</div>'
        body = ('<meta/><div class="article">' + ''.join(
            print_chunks.START + unit % (print_chunks.BREAK if i < 24 else '')
            for i in range(25)) + print_chunks.END + '</div>')
        calls, pages = self._print(
            'aw_fenestration_design.action_report_aw_elevation_sheet_order',
            [body])
        # one part per run: 10, 10 and 5 sheets
        self.assertEqual([c['bodies'][0].count('<div style=') for c in calls],
                         [10, 10, 5])
        self.assertEqual([len(c['bodies']) for c in calls], [1, 1, 1])
        self.assertEqual(pages, 3)
        for call in calls:
            for part in call['bodies']:
                self.assertNotIn('o_aw_split', part)
                self.assertTrue(part.startswith('<meta/><div class="article">'))

    def test_a_rendered_body_is_a_markup_and_is_not_escaped(self):
        """Odoo's bodies are Markup, which escapes any plain str added to it:
        the cut parts of the cutting sheet printed their own tags as text."""
        from markupsafe import Markup
        unit = '<table>%s</table>'
        body = Markup('<div class="article">' + ''.join(
            print_chunks.start_marker(0.25) + unit % i for i in range(90))
            + print_chunks.END + '</div>')
        calls, _pages = self._print(
            'aw_fenestration_design.action_report_aw_cutting_sheet', [body])
        for call in calls:
            self.assertNotIn('&lt;', call['bodies'][0])
            self.assertTrue(call['bodies'][0].startswith('<div class="article">'))
            self.assertIn('<table>', call['bodies'][0])

    def test_a_cut_body_is_printed_in_parts_that_say_which_part(self):
        unit = '<table>%s</table>'
        body = ('<div class="article">' + ''.join(
            print_chunks.start_marker(0.25) + unit % i for i in range(90))
            + print_chunks.END + '</div>')
        footer = ('<!DOCTYPE html><html><body>'
                  '<div id="minimal_layout_report_footers"><div class="footer">'
                  '<div>Page <span class="page"></span> / '
                  '<span class="topage"></span></div></div></div></body></html>')
        calls, pages = self._print(
            'aw_fenestration_design.action_report_aw_cutting_sheet', [body],
            footer=footer)
        self.assertEqual(len(calls), 3)
        for number, call in enumerate(calls, 1):
            self.assertIn('Part %d of 3, Page' % number, call['footer'])
        self.assertEqual(pages, 3)       # one part per run

    def test_window_sheets_keep_their_own_page_numbers(self):
        footer = ('<!DOCTYPE html><html><body>'
                  '<div id="minimal_layout_report_footers">%s</div></body></html>'
                  % ''.join('<div class="footer">Page <span class="page"></span>'
                            '</div>' for _ in range(25)))
        calls, _pages = self._print(
            WINDOW_SHEETS, ['<p>w%d</p>' % i for i in range(25)],
            footer=footer)
        for call in calls:
            self.assertNotIn('Part ', call['footer'])

    def test_the_elevation_sheets_and_cutting_sheet_mark_their_units_and_stickers_do_not(self):
        """Markers are in the templates, loaded the way the loader loads them. The
        stickers are NOT cut: the label format prints at 300 dpi, where one sticker
        sheet is not one paper page, so a cut would move labels."""
        for xmlid in ('aw_fenestration_design.report_elevation_sheet_order',
                      'aw_fenestration_design.report_cutting_sheet_document'):
            arch = self.env.ref(xmlid).arch_db
            self.assertIn('o_aw_split', arch)
            self.assertIn('o_aw_split_end', arch)
        stickers = self.env.ref(
            'aw_fenestration_design.report_cut_labels_document').arch_db
        self.assertNotIn('o_aw_split', stickers)
