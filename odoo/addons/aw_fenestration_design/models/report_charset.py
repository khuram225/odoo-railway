# -*- coding: utf-8 -*-
"""Tell wkhtmltopdf which charset a body-only report is in.

A report that uses no external layout (the Elevation Schedule and Sheet) reaches
wkhtmltopdf as the BODY alone, with no <head> and no charset, and the engine then
reads the UTF-8 bytes as Latin-1: a "·" prints as "Â·", and so would an accented
customer name or a location like "Café". `Odoo._prepare_html` is where the bodies
are made, so a body that carries the marker class `o_aw_utf8` gets the declaration
in front. The report templates that DO have a layout have a charset already and are
left alone.
"""
from odoo import models

MARKER = 'o_aw_utf8'
CHARSET = '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _prepare_html(self, html, report_model=False):
        bodies, res_ids, header, footer, specific = super()._prepare_html(
            html, report_model=report_model)
        bodies = [self._aw_declare_charset(body) for body in bodies]
        return bodies, res_ids, header, footer, specific

    @staticmethod
    def _aw_declare_charset(body):
        """The body with a charset in front, when it is one of ours and has
        none."""
        if MARKER in body and 'charset' not in body[:2000].lower():
            return CHARSET + body
        return body
