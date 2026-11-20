# -*- coding: utf-8 -*-
"""Download cut summary: the batch's cuts as an .xlsx (see cut_summary_xlsx).

Built from the plan's own cuts, so every piece traces to its BOM line, its
window and its bar. Nothing is stored: the file is made when the route is hit.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.aw_fenestration_core.models.units import to_display

from . import cut_summary_xlsx


class AwCutPlan(models.Model):
    _inherit = 'aw.cut.plan'

    def _cut_summary_data(self):
        """Plain values for cut_summary_xlsx.build_cut_summary."""
        self.ensure_one()
        vendor = self.sale_order_id.aw_profile_vendor_id
        states = dict(self._fields['state'].selection)
        cuts = []
        for group in self.group_ids:
            product = group.product_id
            template = product.product_tmpl_id
            thickness = finish = ''
            for value in product.product_template_attribute_value_ids:
                if value.attribute_id.name == 'Thickness':
                    thickness = value.name or ''
                elif value.attribute_id.name == 'Finish':
                    finish = value.product_attribute_value_id.aw_label(
                        vendor) or value.name or ''
            code = (product.default_code or template.default_code
                    or template.name or '')
            for bar_no, bar in enumerate(group.bar_ids, start=1):
                for cut in bar.cut_ids:
                    line = cut.bom_line_id
                    design = line.design_id
                    typed = bool(line.is_free_form or (
                        line.is_manual and abs(
                            (line.length_mm or 0.0)
                            - (line.computed_length_mm or 0.0)) > 0.05))
                    cuts.append({
                        'window': design.name or '-',
                        'location': design.location or '',
                        'panel': line.panel_no or 0,
                        'code': code,
                        'thickness': thickness,
                        'finish': finish,
                        'position': (line.template_line_id.position_id.name
                                     or cut.label or ''),
                        'length_text': to_display(cut.length_mm, 'soot'),
                        'length_mm': cut.length_mm or 0.0,
                        'angle': cut.cut_angle or '',
                        'bar_no': bar_no,
                        'typed': typed,
                        'block': group.id,
                    })
        return {
            'batch': _("Batch %s", self.batch_no or 1),
            'quote': self.sale_order_id.name or '',
            'date': fields.Date.to_string(fields.Date.context_today(self)),
            'state': states.get(self.state, self.state),
            'bars': self.bar_count,
            'feet': self.feet_bought,
            'stale': not self.is_current,
            'cuts': cuts,
        }

    def _cut_summary_file(self):
        """(file name, bytes). A batch with nothing planned is refused."""
        self.ensure_one()
        data = self._cut_summary_data()
        try:
            content = cut_summary_xlsx.build_cut_summary(data)
        except ValueError as error:
            raise UserError(str(error))
        except RuntimeError as error:
            raise UserError(str(error))
        name = cut_summary_xlsx.file_name(
            data['quote'], self.batch_no or 1, data['date'])
        return name, content

    def action_download_cut_summary(self):
        self.ensure_one()
        self._cut_summary_file()      # refuse an empty batch here, with a message
        return {
            'type': 'ir.actions.act_url',
            'url': '/aw/cut_summary/%s' % self.id,
            'target': 'self',
        }
