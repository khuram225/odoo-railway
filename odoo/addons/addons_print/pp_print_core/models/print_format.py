from odoo import api, fields, models


class PrintFormat(models.Model):
    _name = "print.format"
    _description = "Standard format"
    _order = "code"

    code = fields.Char("Format", required=True)
    name = fields.Char("Description", required=True)
    width_in = fields.Float("Width (in)", digits=(8, 3), required=True)
    height_in = fields.Float("Height (in)", digits=(8, 3), required=True)
    orientation = fields.Selection([("portrait", "Portrait"), ("landscape", "Landscape"), ("square", "Square")],
                                   compute="_compute_orientation", store=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Format code must be unique.")

    @api.depends("width_in", "height_in")
    def _compute_orientation(self):
        for rec in self:
            rec.orientation = ("portrait" if rec.height_in > rec.width_in
                               else "landscape" if rec.width_in > rec.height_in else "square")
