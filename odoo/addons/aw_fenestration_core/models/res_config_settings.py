# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aw_length_uom = fields.Selection(related='company_id.aw_length_uom',
        readonly=False, required=True)
