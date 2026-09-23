# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowType(models.Model):
    """The broad fenestration category a Series belongs to -- Sliding
    Window, Fix Window, Curtain Wall Fix Window, Open-able Window,
    Tilt & Turn Window, Door. Sits above aw.window.series: several Series
    (e.g. Box Series, Round Series, Collar Box Series) can share one Type.

    kind_id is intentionally NOT required -- Door doesn't have a leaf-type
    rule set yet, and forcing one here would mean picking an arbitrary
    Kind just to satisfy the field rather than leaving it genuinely unset.
    """
    _name = 'aw.window.type'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True)
    kind_id = fields.Many2one('aw.window.kind', tracking=True,
        ondelete='restrict',
        help="Leaf-type rule set this Type uses, where applicable. Left "
             "blank for Types like Door that don't have one yet.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    window_series_ids = fields.One2many(
        'aw.window.series', 'window_type_id', string='Series')
    window_series_count = fields.Integer(compute='_compute_window_series_count')

    def _compute_window_series_count(self):
        for rec in self:
            rec.window_series_count = len(rec.window_series_ids)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Window Type code must be unique.'),
    ]
