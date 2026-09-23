# -*- coding: utf-8 -*-
from odoo import fields, models


class AwWindowKind(models.Model):
    """Replaces the old free Selection field on aw.window.type.kind.
    Where 'sliding'/'hinged'/'fixed' used to be a hard-coded string with
    the leaf-type rule living only in JS/Python logic elsewhere, a Kind
    is now a real record carrying which leaf types it allows — so adding
    a new Kind from the UI is meaningful (you tick what it supports)
    rather than a label the design engine has never heard of.

    These booleans mirror the prototype's PT (panel type) keys exactly:
    fixed / slider / casement / awning / hopper / mesh. That set is a
    closed list of real mechanical opening methods, not something new
    Kinds are expected to expand — a new Kind combines existing leaf
    types differently, it doesn't invent a 7th one.
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

    window_type_ids = fields.One2many(
        'aw.window.type', 'kind_id', string='Window Types using this Kind')
    window_type_count = fields.Integer(compute='_compute_window_type_count')

    def _compute_window_type_count(self):
        for rec in self:
            rec.window_type_count = len(rec.window_type_ids)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Window Kind code must be unique.'),
    ]
