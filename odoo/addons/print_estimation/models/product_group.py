from odoo import api, fields, models

TEMPLATE_TYPES = [
    ("bound", "Bound book"),
    ("flat", "Flat sheet"),
    ("pad", "Pad / form set"),
    ("diecut", "Die-cut and made-up"),
    ("label", "Label (sticker stock)"),
    ("carton", "Carton"),
    ("bag", "Bag"),
    ("rigid", "Rigid box"),
]


class PrintProductGroup(models.Model):
    """L1 of the job taxonomy (e.g. Books and bound publications)."""
    _name = "print.product.group"
    _description = "Print product group (L1)"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    base_product_ids = fields.One2many("print.base.product", "group_id", string="Base products")
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "Product group code must be unique.")


class PrintBaseProduct(models.Model):
    """L2 of the job taxonomy. In DynamicsPrint terms the 'base product':
    the container of business rules (rules are added in a later step)."""
    _name = "print.base.product"
    _description = "Print base product (L2)"
    _order = "group_id, sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    group_id = fields.Many2one("print.product.group", string="Product group (L1)", required=True, ondelete="restrict")
    template_type = fields.Selection(TEMPLATE_TYPES, string="Estimating template", required=True, default="flat")
    description = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "Base product code must be unique.")

    @api.depends("name", "group_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.group_id.name} / {rec.name}" if rec.group_id else rec.name
