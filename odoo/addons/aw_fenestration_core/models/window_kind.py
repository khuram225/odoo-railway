# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowKind(models.Model):
    """Originally replaced a hard-coded Selection field on what was then
    aw.window.type (now aw.window.type is the Type layer above
    aw.window.series, and Kind hangs off Type via Type.kind_id). Where
    'sliding'/'hinged'/'fixed' used to be a plain string with the leaf-
    type rule living only in JS/Python logic elsewhere, a Kind is a real
    record carrying which leaf types it allows — so adding a new Kind
    from the UI is meaningful (you tick what it supports) rather than a
    label the design engine has never heard of.

    These booleans track real mechanical opening methods: fixed / slider
    / casement / awning / hopper / mesh / tilt-turn. Tilt & Turn was
    added alongside the Type layer since it's mechanically distinct from
    Casement/Hopper (one sash, two opening modes via handle position) --
    a genuinely new leaf type, not a recombination of the existing six.
    """
    _name = 'aw.window.kind'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Kind (leaf-type rule set)'
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    allow_fixed = fields.Boolean(default=True, tracking=True,
        help="Fixed (non-operable, glazed) leaf.")
    allow_slider = fields.Boolean(tracking=True,
        help="Sliding leaf — implies Interlock is a meaningful role "
             "when 2+ sliders share a row.")
    allow_casement = fields.Boolean(tracking=True,
        help="Side-hinged operable leaf.")
    allow_awning = fields.Boolean(tracking=True,
        help="Top-hinged operable leaf.")
    allow_hopper = fields.Boolean(tracking=True,
        help="Bottom-hinged operable leaf.")
    allow_mesh = fields.Boolean(default=True, tracking=True,
        help="Insect mesh leaf — allowed alongside either sliding or "
             "hinged systems.")
    allow_tiltturn = fields.Boolean(tracking=True, help="One sash, "
        "either full casement swing or top-tilt, selected by handle "
        "position — mechanically distinct from Casement/Hopper.")

    window_type_ids = fields.One2many(
        'aw.window.type', 'kind_id', string='Window Types using this Kind')
    window_type_count = fields.Integer(compute='_compute_window_type_count')

    def _compute_window_type_count(self):
        for rec in self:
            rec.window_type_count = len(rec.window_type_ids)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Window Kind code must be unique.'),
    ]
