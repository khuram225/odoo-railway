from odoo import api, fields, models

WORKCENTER_TYPES = [
    ("prepress", "Prepress"),
    ("ctp", "CTP / plate making"),
    ("offset", "Offset press"),
    ("digital", "Digital press"),
    ("guillotine", "Guillotine"),
    ("folder", "Folding machine"),
    ("laminator", "Laminator"),
    ("coater", "UV / varnish coater"),
    ("platen", "Platen (die, foil, emboss, crease)"),
    ("numbering", "Numbering / perforating"),
    ("binder", "Perfect binder"),
    ("stitcher", "Stitcher"),
    ("bench", "Hand work bench"),
    ("packing", "Packing"),
    ("other", "Other"),
]
SPEED_UNITS = [
    ("sheet", "Sheets per hour"),
    ("sqft", "Square feet per hour"),
    ("piece", "Pieces per hour"),
    ("copy", "Copies per hour"),
    ("plate", "Plates per hour"),
]
STATUS = [
    ("available", "Available"),
    ("running", "Running"),
    ("breakdown", "Breakdown"),
    ("maintenance", "Under maintenance"),
    ("retired", "Retired"),
]


class PrintWorkcenter(models.Model):
    _name = "print.workcenter"
    _description = "Work centre (machine or bench)"
    _inherit = ["mail.thread"]
    _order = "workcenter_type, code"

    code = fields.Char(required=True, tracking=True)
    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    workcenter_type = fields.Selection(WORKCENTER_TYPES, string="Type", required=True, tracking=True)
    status = fields.Selection(STATUS, default="available", required=True, tracking=True)
    cost_group_id = fields.Many2one("print.cost.group", string="Cost group", required=True)
    currency_id = fields.Many2one("res.currency", default=lambda s: s.env.company.currency_id, required=True)

    # Capability
    max_width_in = fields.Float("Max sheet width (in)", digits=(8, 2))
    max_height_in = fields.Float("Max sheet height (in)", digits=(8, 2))
    min_width_in = fields.Float("Min sheet width (in)", digits=(8, 2))
    min_height_in = fields.Float("Min sheet height (in)", digits=(8, 2))
    colour_units = fields.Integer("Colour units")
    perfecting = fields.Boolean("Perfecting (prints both sides in one pass)")
    gripper_in = fields.Float("Gripper margin (in)", digits=(6, 3))

    # Capacity and speed
    capacity_hours_day = fields.Float("Capacity hours per day", digits=(6, 2))
    speed_unit = fields.Selection(SPEED_UNITS, required=True, default="sheet")
    factor_group_id = fields.Many2one("print.factor.group", string="Speed factor group",
                                      help="Speed comes from this factor group (run length, grammage, ink use ...).")
    makeready_min = fields.Float("Make-ready minutes per run", digits=(8, 2))
    makeready_sheets = fields.Float("Make-ready sheets per run", digits=(8, 2))
    running_waste_pct = fields.Float("Running waste (%)", digits=(6, 3))

    # Crew and rates
    crew_ids = fields.One2many("print.workcenter.crew", "workcenter_id", string="Crew")
    rate_ids = fields.One2many("print.workcenter.rate", "workcenter_id", string="Rates")
    current_direct_rate_hr = fields.Monetary(compute="_compute_current", string="Machine direct / hour")
    current_indirect_rate_hr = fields.Monetary(compute="_compute_current", string="Machine indirect / hour")
    current_crew_rate_hr = fields.Monetary(compute="_compute_current", string="Crew / hour")
    current_total_rate_hr = fields.Monetary(compute="_compute_current", string="Total cost / hour")
    note = fields.Html()

    _code_uniq = models.Constraint("unique(code)", "Work centre code must be unique.")

    def rate_on(self, date=None):
        """Rate record effective on a date (latest 'valid from' on or before it)."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        return self.rate_ids.filtered(lambda r: r.date_from <= date).sorted("date_from", reverse=True)[:1]

    def crew_rate_on(self, date=None):
        self.ensure_one()
        return sum(c.count * c.role_id.rate_on(date) for c in self.crew_ids)

    def crew_headcount(self):
        self.ensure_one()
        return sum(self.crew_ids.mapped("count"))

    @api.depends("rate_ids.date_from", "rate_ids.direct_rate_hr", "rate_ids.indirect_rate_hr",
                 "crew_ids.count", "crew_ids.role_id.rate_ids.rate_hr", "crew_ids.role_id.rate_ids.date_from")
    def _compute_current(self):
        for rec in self:
            rate = rec.rate_on()
            rec.current_direct_rate_hr = rate.direct_rate_hr if rate else 0.0
            rec.current_indirect_rate_hr = rate.indirect_rate_hr if rate else 0.0
            rec.current_crew_rate_hr = rec.crew_rate_on()
            rec.current_total_rate_hr = rec.current_direct_rate_hr + rec.current_indirect_rate_hr + rec.current_crew_rate_hr


class PrintWorkcenterCrew(models.Model):
    _name = "print.workcenter.crew"
    _description = "Work centre crew"

    workcenter_id = fields.Many2one("print.workcenter", required=True, ondelete="cascade")
    role_id = fields.Many2one("print.labour.role", required=True, ondelete="restrict")
    count = fields.Float("Persons", default=1.0, digits=(6, 2))


class PrintWorkcenterRate(models.Model):
    """Effective-dated machine rates. Direct = power and running consumables; indirect = depreciation,
    maintenance, spares and space. Click rates apply to digital presses."""
    _name = "print.workcenter.rate"
    _description = "Work centre rate (effective-dated)"
    _order = "date_from desc"

    workcenter_id = fields.Many2one("print.workcenter", required=True, ondelete="cascade")
    date_from = fields.Date("Valid from", required=True, default=fields.Date.context_today)
    currency_id = fields.Many2one(related="workcenter_id.currency_id")
    direct_rate_hr = fields.Monetary("Machine direct / hour")
    indirect_rate_hr = fields.Monetary("Machine indirect / hour")
    click_rate_colour = fields.Monetary("Click, colour (per side)")
    click_rate_mono = fields.Monetary("Click, black (per side)")
    note = fields.Char()
