# -*- coding: utf-8 -*-
"""Supplies `start_at` to the piece sticker sheet.

A report model exists purely so the default lives in PYTHON. The
wizard passes `data={'start_at': n}`, which
`ir_actions_report._get_rendering_context` merges straight into the
template's namespace -- but the plain Print menu passes no data at all,
and a QWeb expression naming a variable that is not there raises. There
is no "is it defined" test in QWeb, so the two paths are evened out
here instead.
"""
from odoo import api, models


class ReportCutLabels(models.AbstractModel):
    _name = 'report.aw_fenestration_design.report_cut_labels'
    _description = 'Piece Stickers (precut sheet)'

    @api.model
    def _get_report_values(self, docids, data=None):
        start_at = (data or {}).get('start_at') or 1
        return {
            'doc_ids': docids,
            'doc_model': 'aw.cut.plan',
            'docs': self.env['aw.cut.plan'].browse(docids),
            'start_at': start_at,
        }
