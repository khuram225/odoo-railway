# -*- coding: utf-8 -*-
from odoo import fields, models


class AwProfilePosition(models.Model):
    """Open-ended replacement for the old hardcoded 5-value role Selection
    (frame/sash/interlock/bead/mesh) on aw.profile.section.line. A real
    fabrication combination can need frame split by top/bottom/sides
    (different drainage profile on the sill than the head/jambs — the
    real detail that came out of the Double Glaze Sliding Profile 1
    breakdown), which a fixed 5-value list can't express. This table can
    grow by adding a row — no schema change, no code change — which is
    the actual point of making it dynamic rather than a longer hardcoded
    list.
    """
    _name = 'aw.profile.position'
    _description = 'Fenestration Profile Position'
    _order = 'sequence, name'

    name = fields.Char(required=True, help="e.g. 'Outer Frame - Top', "
        "'Palay - Bottom', 'Mesh - All Sides'.")
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Profile Position code must be unique.'),
    ]
