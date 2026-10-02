# -*- coding: utf-8 -*-
"""Precut label sheet geometry, so a different sheet needs no code.

Deliberately in the DESIGN module rather than beside core's settings:
the label report lives here, and keeping these together means changing
the sheet is a Design upgrade and nothing else.

`config_parameter` throughout, which needs no schema change at all --
see the res.company near-outage in CLAUDE.md for why that matters.
"""
from odoo import fields, models

# A4, in mm. Not settings: the report's paperformat is A4, and a
# sheet of another paper size would need that changed too, which is
# not what "a different sheet" means here.
SHEET_W = 210.0
SHEET_H = 297.0

P = 'aw_fenestration.label_'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aw_label_w = fields.Float(
        string='Label Width (mm)', default=70.0,
        config_parameter=P + 'w')
    aw_label_h = fields.Float(
        string='Label Height (mm)', default=29.7,
        config_parameter=P + 'h')
    aw_label_across = fields.Integer(
        string='Labels Across', default=3,
        config_parameter=P + 'across')
    aw_label_down = fields.Integer(
        string='Labels Down', default=10,
        config_parameter=P + 'down')
    aw_label_top_mm = fields.Float(
        string='Sheet Top Margin (mm)', default=0.0,
        config_parameter=P + 'top')
    aw_label_left_mm = fields.Float(
        string='Sheet Left Margin (mm)', default=0.0,
        config_parameter=P + 'left')
    aw_label_gap_x_mm = fields.Float(
        string='Gap Across (mm)', default=0.0,
        config_parameter=P + 'gap_x')
    aw_label_gap_y_mm = fields.Float(
        string='Gap Down (mm)', default=0.0,
        config_parameter=P + 'gap_y')

    # Fine alignment. Every printer pulls the sheet slightly
    # differently, and the usual fix is to nudge the whole grid rather
    # than re-measure the stock.
    aw_label_offset_x_mm = fields.Float(
        string='Printer Offset X (mm)', default=0.0,
        config_parameter=P + 'offset_x',
        help="Shifts the whole grid right (negative = left). For "
             "correcting a printer that feeds slightly off-centre.")
    aw_label_offset_y_mm = fields.Float(
        string='Printer Offset Y (mm)', default=0.0,
        config_parameter=P + 'offset_y',
        help="Shifts the whole grid down (negative = up).")

    aw_label_safe_mm = fields.Float(
        string='Safe Inner Padding (mm)', default=4.0,
        config_parameter=P + 'safe',
        help="Keeps a sticker's CONTENT at least this far from the edge "
             "of the SHEET, so a label touching the paper edge is not "
             "clipped by the laser's unprintable border. Only the outer "
             "rows and columns are affected; inner labels are untouched.")
