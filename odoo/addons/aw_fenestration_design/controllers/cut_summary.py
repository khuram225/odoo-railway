# -*- coding: utf-8 -*-
"""The cut summary download: /aw/cut_summary/<plan id> (a logged-in user who
can read the batch)."""
from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class AwCutSummary(http.Controller):

    @http.route('/aw/cut_summary/<int:plan_id>', type='http', auth='user')
    def cut_summary(self, plan_id, **kwargs):
        plan = request.env['aw.cut.plan'].browse(plan_id)
        try:
            plan.check_access('read')
            name, content = plan._cut_summary_file()
        except (AccessError, MissingError):
            return request.not_found()
        except UserError as error:
            return request.make_response(
                str(error), headers=[('Content-Type', 'text/plain')],
                status=400)
        return request.make_response(content, headers=[
            ('Content-Type', XLSX),
            ('Content-Length', len(content)),
            ('Content-Disposition', http.content_disposition(name)),
        ])
