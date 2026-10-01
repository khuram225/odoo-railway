from odoo import fields, models


class PrintCostGroup(models.Model):
    """DynamicsPrint 'base group' / estimate spec group (Prepress, Paper, Printing, Finishing ...).
    Recommended sales price = time cost x (1 + time markup) + material x (1 + material markup)."""
    _name = "print.cost.group"
    _description = "Cost group (base group)"
    _order = "sequence, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    time_markup_pct = fields.Float("Markup on time cost (%)", digits=(6, 2))
    material_markup_pct = fields.Float("Markup on material (%)", digits=(6, 2))

    _code_uniq = models.Constraint("unique(code)", "Cost group code must be unique.")
