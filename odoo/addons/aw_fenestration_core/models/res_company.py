# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    aw_length_uom = fields.Selection([
        ('ftin', 'Feet + Inches'),
        ('in', 'Inches'),
        ('mm', 'Millimetres'),
    ], string='Fenestration Length Unit', default='ftin', required=True,
        help="How lengths are entered and displayed throughout Fenestration "
             "Design. Millimetres remain the stored source of truth "
             "regardless of this setting -- changing it only changes what "
             "you type into and see on screen.")
