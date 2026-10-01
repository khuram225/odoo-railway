from odoo import api, fields, models

from .material import MATERIAL_TYPES

PAGE_KINDS = [
    ("text", "Text (pages folded into sections)"),
    ("cover", "Cover (wraps the text)"),
    ("sheet", "Sheet / piece / part / blank"),
]


class PrintPageType(models.Model):
    """DynamicsPrint 'Page type' setup (Cover1, Text1, Insert1 ...)."""
    _name = "print.page.type"
    _description = "Page type"
    _order = "sequence, code"

    code = fields.Char("Page type", required=True)
    name = fields.Char("Description", required=True)
    kind = fields.Selection(PAGE_KINDS, required=True, default="text")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Page type must be unique.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.code or ""


class PrintBaseProductPage(models.Model):
    """Default page types of a base product (L2): copied onto a new estimate."""
    _name = "print.base.product.page"
    _description = "Base product default page type"
    _order = "sequence, id"

    base_product_id = fields.Many2one("print.base.product", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    page_type_id = fields.Many2one("print.page.type", required=True, ondelete="restrict")
    pages = fields.Integer("Pages / leaves", default=1)
    material_type = fields.Selection(MATERIAL_TYPES, string="Material group")
    material_id = fields.Many2one("product.template", string="Default material",
                                  domain="[('print_is_sheet', '=', True)]")


class PrintBaseProduct(models.Model):
    _inherit = "print.base.product"

    default_page_ids = fields.One2many("print.base.product.page", "base_product_id", string="Default page types")
