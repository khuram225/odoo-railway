# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AwWindowSeries(models.Model):
    """Layout-preset count on the Series.

    This lives in aw_fenestration_design, not in core with the rest of
    the Series stat buttons, because aw.layout.preset is defined HERE:
    core doesn't depend on design, so it cannot reference the model.
    The form view is extended the same way, from this module.
    """
    _inherit = 'aw.window.series'

    layout_preset_count = fields.Integer(
        compute='_compute_layout_preset_count', string='Layout Presets')

    @api.depends('leaf_type_ids')
    def _compute_layout_preset_count(self):
        # Counts what would actually be OFFERED on this Series, i.e. the
        # same two-condition filter the configurator uses, not just
        # presets that name it. A preset with no Series is offered
        # everywhere its leaf types fit, and belongs in the count.
        presets = self.env['aw.layout.preset'].search([])
        for series in self:
            series.layout_preset_count = len(
                presets._allowed_for_series(series))

    def action_view_layout_presets(self):
        self.ensure_one()
        allowed = self.env['aw.layout.preset'].search(
            [])._allowed_for_series(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Layout Presets"),
            'res_model': 'aw.layout.preset',
            'view_mode': 'kanban,list,form',
            'views': [(False, 'kanban'), (False, 'list'), (False, 'form')],
            # A domain on ids rather than on series_ids: "offered here"
            # includes presets with no Series at all, which no simple
            # domain on that field can express.
            'domain': [('id', 'in', allowed.ids)],
            'context': {'default_series_ids': [(6, 0, [self.id])]},
        }
