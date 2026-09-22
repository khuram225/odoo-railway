from odoo import fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    length_mm = fields.Integer(
        string='Length (mm)',
        help="Physical length of this lot's sticks, in millimeters.",
    )
    profile_source = fields.Selection(
        selection=[
            ('purchased', 'Purchased'),
            ('leftover_return', 'Leftover Return'),
        ],
        string='Profile Source',
        help="Where this lot came from: bought new, or returned as a leftover cut from a longer stick.",
    )
    parent_lot_id = fields.Many2one(
        'stock.lot',
        string='Cut From Lot',
        help="The original stick lot this leftover was cut from, if any.",
    )
