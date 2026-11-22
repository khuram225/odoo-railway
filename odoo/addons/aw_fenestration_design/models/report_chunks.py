# -*- coding: utf-8 -*-
"""Our reports are printed in groups, so the memory of a print does not grow with the
quote (see print_chunks.py for the why and the two shapes it cuts).

The pages are the same pages: every window still has its own footer and its own page
count ("Page 1 / 6" for each window sheet, as before), because a window is one body
and a body is never cut. What changes is that wkhtmltopdf is started once per group
and the PDFs are put together after. A body that is cut in parts (the cutting sheet)
counts its pages per part, and its footer says so: "Part 2 of 8, Page 3 / 12".
"""
import logging

from odoo import models
from odoo.tools.pdf import merge_pdf

from . import print_chunks

_logger = logging.getLogger(__name__)

PARAM = 'aw_fenestration.print_chunk'
OURS = 'aw_fenestration_design.'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _aw_print_per_run(self):
        """Weight a wkhtmltopdf run may hold (a window sheet weighs 1; a sticker
        page 2, a cutting-sheet bar 0.25); `aw_fenestration.print_chunk`
        changes it. 0 or less keeps one run."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM, str(print_chunks.DEFAULT_PER_RUN))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return print_chunks.DEFAULT_PER_RUN

    def _run_wkhtmltopdf(self, bodies, report_ref=False, header=None,
                         footer=None, landscape=False,
                         specific_paperformat_args=None,
                         set_viewport_size=False):
        report = self._get_report(report_ref) if report_ref else self
        per_run = self._aw_print_per_run()
        if per_run <= 0 or not (report.report_name or '').startswith(OURS):
            return super()._run_wkhtmltopdf(
                bodies, report_ref=report_ref, header=header, footer=footer,
                landscape=landscape,
                specific_paperformat_args=specific_paperformat_args,
                set_viewport_size=set_viewport_size)
        cut = print_chunks.was_cut(bodies)
        items = print_chunks.expand(list(bodies), per_run)
        groups = print_chunks.runs(items, per_run)
        if len(groups) <= 1:
            return super()._run_wkhtmltopdf(
                [body for _index, body, _w in items], report_ref=report_ref,
                header=header, footer=footer, landscape=landscape,
                specific_paperformat_args=specific_paperformat_args,
                set_viewport_size=set_viewport_size)
        _logger.info("%s: %d bodies printed in %d runs of up to %s",
                     report.report_name, len(items), len(groups), per_run)
        pdfs = []
        for number, group in enumerate(groups, 1):
            indexes = [index for index, _body, _w in group]
            run_footer = print_chunks.slice_children(
                footer, 'minimal_layout_report_footers', indexes)
            if cut:
                # a body cut in parts counts its pages per part
                run_footer = print_chunks.label_part(
                    run_footer, number, len(groups))
            pdfs.append(super()._run_wkhtmltopdf(
                [body for _index, body, _w in group], report_ref=report_ref,
                header=print_chunks.slice_children(
                    header, 'minimal_layout_report_headers', indexes),
                footer=run_footer,
                landscape=landscape,
                specific_paperformat_args=specific_paperformat_args,
                set_viewport_size=set_viewport_size))
        return merge_pdf(pdfs)
