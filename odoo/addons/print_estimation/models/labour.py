from odoo import api, fields, models


class PrintLabourRole(models.Model):
    _name = "print.labour.role"
    _description = "Labour role"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    rate_ids = fields.One2many("print.labour.role.rate", "role_id", string="Hourly rates")
    currency_id = fields.Many2one("res.currency", default=lambda s: s.env.company.currency_id, required=True)
    current_rate_hr = fields.Monetary(compute="_compute_current_rate", string="Current rate / hour")

    _code_uniq = models.Constraint("unique(code)", "Role code must be unique.")

    def rate_on(self, date=None):
        """Hourly rate effective on a date: the latest rate whose 'valid from' is on or before it."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        rate = self.rate_ids.filtered(lambda r: r.date_from <= date).sorted("date_from", reverse=True)[:1]
        return rate.rate_hr if rate else 0.0

    @api.depends("rate_ids.date_from", "rate_ids.rate_hr")
    def _compute_current_rate(self):
        for rec in self:
            rec.current_rate_hr = rec.rate_on()


class PrintLabourRoleRate(models.Model):
    _name = "print.labour.role.rate"
    _description = "Labour role hourly rate (effective-dated)"
    _order = "date_from desc"

    role_id = fields.Many2one("print.labour.role", required=True, ondelete="cascade")
    date_from = fields.Date("Valid from", required=True, default=fields.Date.context_today)
    currency_id = fields.Many2one(related="role_id.currency_id")
    rate_hr = fields.Monetary("Rate / hour", required=True)
    note = fields.Char()
