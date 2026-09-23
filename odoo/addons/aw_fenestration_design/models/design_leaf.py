# -*- coding: utf-8 -*-
from odoo import fields, models

LEAF_TYPE_SELECTION = [
    ('fixed', 'Fixed'),
    ('slider', 'Slider'),
    ('casement', 'Casement'),
    ('awning', 'Awning (top-hung)'),
    ('hopper', 'Hopper (bottom-hung)'),
    ('mesh', 'Mesh'),
    ('tiltturn', 'Tilt & Turn'),
]


class AwDesignLeaf(models.Model):
    """Direct port of the prototype's row.leaves[] entries. leaf_type
    now includes 'tiltturn' — the 7th leaf type added when Window Kind
    grew a 4th kind for the Tilt & Turn Window type. Legality (which
    leaf types a given row's design.window_series_id actually allows) is
    NOT enforced at this layer — that's a check against
    window_series_id.window_type_id.kind_id.allow_* , which belongs in
    the checks/validation step, not baked into this bare data model.

    Direction fields are all optional and only meaningful for some leaf
    types (hinge_side/swing for casement/awning/hopper/tiltturn,
    slide_dir for slider) — same as the prototype's PT[type].dir lookup,
    just not literally ported as a lookup table here since Python can
    branch on leaf_type directly wherever this matters.
    """
    _name = 'aw.design.leaf'
    _description = 'Fenestration Design Leaf'
    _order = 'sequence, id'

    row_id = fields.Many2one('aw.design.row', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    width_mm = fields.Float(string='Width (mm)', required=True)
    is_auto = fields.Boolean(
        string='Automatic',
        help="Same mechanism as aw.design.row.is_auto, one level down: "
             "exactly one leaf per row should absorb the remainder so "
             "the row's leaf widths always sum to the design's overall "
             "Width. Not enforced at this layer yet.")

    leaf_type = fields.Selection(LEAF_TYPE_SELECTION, required=True, default='fixed')

    hinge_side = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
        ('top', 'Top'), ('bottom', 'Bottom'),
    ], help="Casement/Awning/Hopper/Tilt & Turn only.")
    swing = fields.Selection([
        ('in', 'In'), ('out', 'Out'),
    ], help="Casement/Awning/Hopper/Tilt & Turn only.")
    slide_dir = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
    ], help="Slider only.")
