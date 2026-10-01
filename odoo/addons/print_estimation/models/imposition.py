from odoo import api, fields, models


class PrintImposition(models.Model):
    """DynamicsPrint imposition table. Codes like 'B 2B 2H lieg 8':
    B = across, H = high, steh = upright (portrait), lieg = turned (landscape), last number = pages on the sheet."""
    _name = "print.imposition"
    _description = "Imposition"
    _order = "code"

    code = fields.Char("Type", required=True)
    name = fields.Char("Description", required=True)
    category = fields.Selection([("sheet", "Sheet printing"), ("web", "Web printing")], required=True, default="sheet")
    columns = fields.Integer(required=True, default=1)
    column_group = fields.Integer("Column group", default=1)
    rows = fields.Integer(required=True, default=1)
    row_group = fields.Integer("Row group", default=1)
    gripper_allowance = fields.Selection([("across", "Across"), ("along", "Along")], default="across", required=True)
    plate_orientation = fields.Selection([("portrait", "Portrait"), ("landscape", "Landscape")], default="portrait", required=True)
    color_strip = fields.Selection([("edge", "Edge"), ("middle", "Middle"), ("none", "None")], default="edge", required=True)
    pages_per_side = fields.Integer(compute="_compute_pages", string="Pages / ups per side")
    pages_per_sheet = fields.Integer(compute="_compute_pages", string="Pages per sheet (both sides)")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Imposition type must be unique.")

    @api.depends("columns", "rows")
    def _compute_pages(self):
        for rec in self:
            rec.pages_per_side = rec.columns * rec.rows
            rec.pages_per_sheet = rec.columns * rec.rows * 2
