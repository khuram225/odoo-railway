# -*- coding: utf-8 -*-
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class AwDesignPresetWizard(models.TransientModel):
    """Save the design you are looking at as a reusable preset (spec 4.3).

    Presets become authored visually: build the layout in the
    configurator, then name it. The JSON editor on the preset form stays
    for admins, but nobody has to start there.
    """
    _name = 'aw.design.preset.wizard'
    _description = 'Save Layout as Preset'

    design_id = fields.Many2one(
        'aw.design', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    code = fields.Char(
        help="Short stable code, e.g. OPN-FRN. Must be unique.")
    family_id = fields.Many2one(
        'aw.layout.family', string='Family', required=True,
        domain=[('kind', '=', 'layout')],
        default=lambda self: self.env.ref(
            'aw_fenestration_design.layout_family_oth',
            raise_if_not_found=False))
    series_ids = fields.Many2many(
        'aw.window.series', string='Window Series',
        help="Offer this preset only on these Series. Leave empty to "
             "offer it wherever its leaf types fit.")

    def action_save(self):
        self.ensure_one()
        design = self.design_id
        rows = design._layout_json_from_rows(design.row_ids)
        if not rows:
            raise UserError(_(
                "This design has no panels yet, so there is no layout to "
                "save."))
        preset = self.env['aw.layout.preset'].create({
            'name': self.name,
            'code': self.code or False,
            'family_id': self.family_id.id,
            # Kept in step with family_id so the library still groups
            # correctly on a database part-way through the migration.
            'category': self.family_id.name,
            'series_ids': [(6, 0, self.series_ids.ids)],
            'layout_json': json.dumps({'rows': rows}),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _("Layout Preset"),
            'res_model': 'aw.layout.preset',
            'res_id': preset.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }
