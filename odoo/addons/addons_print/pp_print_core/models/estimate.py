from odoo import api, fields, models
from odoo.exceptions import UserError

from .material import MATERIAL_TYPES

STATES = [
    ("in_process", "In process"),
    ("quoted", "Quoted"),
    ("sales_order", "Sales order"),
    ("lost", "Lost"),
    ("cancelled", "Cancelled"),
]


class PrintEstimate(models.Model):
    """The estimate (DynamicsPrint 'Calculation' + 'Production / Overview')."""
    _name = "print.estimate"
    _description = "Print estimate"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "is_standard desc, name desc, version desc"
    _rec_names_search = ["name", "job_name", "partner_id.name"]

    # Identification
    name = fields.Char("Estimate no.", required=True, copy=False, readonly=True, default="New", tracking=True)
    version = fields.Integer(default=1, copy=False, readonly=True)
    job_name = fields.Char("Job name", required=True, tracking=True)
    is_standard = fields.Boolean("Standard", tracking=True,
                                 help="Standards are templates; new estimates can start from them.")
    state = fields.Selection(STATES, string="Estimate status", default="in_process", required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")

    # General
    base_product_id = fields.Many2one("print.base.product", string="Product", required=True, tracking=True)
    product_group_id = fields.Many2one(related="base_product_id.group_id", store=True, string="Product group")
    template_type = fields.Selection(related="base_product_id.template_type", store=True)
    ecolabel = fields.Boolean("Ecolabel")
    template_id = fields.Many2one("print.estimate", string="Template", domain="[('is_standard', '=', True)]",
                                  help="Standard estimate this one was started from.", copy=False)
    description = fields.Html("Description of the job")

    # Customer
    partner_id = fields.Many2one("res.partner", string="Customer", tracking=True)
    contact_id = fields.Many2one("res.partner", string="Contact",
                                 domain="[('parent_id', '=', partner_id), ('type', '=', 'contact')]")
    phone = fields.Char(compute="_compute_contact_info", string="Telephone")
    email = fields.Char(compute="_compute_contact_info", string="E-mail")
    website = fields.Char(compute="_compute_contact_info", string="Internet address")
    requisition = fields.Char("Requisition")
    customer_reference = fields.Char("Customer reference")
    author = fields.Char("Author")
    isbn = fields.Char("ISBN Nr. 1")
    estimator_id = fields.Many2one("res.users", string="Estimator", default=lambda s: s.env.user, tracking=True)
    sales_rep_id = fields.Many2one("res.users", string="Sales rep.", tracking=True)

    # Dates
    date = fields.Date("Calcdate", required=True, default=fields.Date.context_today, tracking=True,
                       help="Rates and prices valid on this date are used.")
    follow_up_date = fields.Date("Follow-up date")
    expiry_date = fields.Date("Expiry date")
    order_date = fields.Date("Order date")
    delivery_date = fields.Date("Delivery")

    # Production / Overview
    run_qty = fields.Integer("Run qty.", required=True, default=1000, tracking=True)
    run_qty_flag = fields.Boolean("Run qty. flag", help="Checkbox shown next to Run qty. in DynamicsPrint; meaning to confirm.")
    run_on_qty = fields.Integer("Qty - run on", default=1000,
                                help="Extra quantity used for the run-on columns in price setting.")
    format_id = fields.Many2one("print.format", string="Format")
    width_in = fields.Float("Width (in)", digits=(8, 3), compute="_compute_size", store=True, readonly=False)
    height_in = fields.Float("Height (in)", digits=(8, 3), compute="_compute_size", store=True, readonly=False)
    page_ids = fields.One2many("print.estimate.page", "estimate_id", string="Pagetypes", copy=True)
    pages_label = fields.Char("Pages", compute="_compute_pages_label", store=True)
    version_line_ids = fields.One2many("print.estimate.version", "estimate_id", string="Versions - Bind legs", copy=True)
    versions_total = fields.Integer(compute="_compute_versions_check")
    versions_warning = fields.Char(compute="_compute_versions_check")
    remarks = fields.Text("Remarks")

    # ---------------------------------------------------------------- computes
    @api.depends("partner_id", "contact_id")
    def _compute_contact_info(self):
        for rec in self:
            src = rec.contact_id or rec.partner_id
            rec.phone = src.phone if src else False
            rec.email = src.email if src else False
            rec.website = (rec.partner_id.website if rec.partner_id else False)

    @api.depends("format_id")
    def _compute_size(self):
        for rec in self:
            if rec.format_id:
                rec.width_in = rec.format_id.width_in
                rec.height_in = rec.format_id.height_in

    @api.depends("page_ids.pages", "page_ids.sequence")
    def _compute_pages_label(self):
        for rec in self:
            rec.pages_label = " + ".join(str(p.pages) for p in rec.page_ids.sorted("sequence")) or "0"

    @api.depends("version_line_ids.run_qty", "run_qty")
    def _compute_versions_check(self):
        for rec in self:
            total = sum(rec.version_line_ids.mapped("run_qty"))
            rec.versions_total = total
            rec.versions_warning = (
                f"Versions add up to {total:,} but run qty. is {rec.run_qty:,}."
                if rec.version_line_ids and total != rec.run_qty else False
            )

    @api.constrains("run_qty", "run_on_qty")
    def _check_qty(self):
        for rec in self:
            if rec.run_qty <= 0:
                raise UserError("Run qty. must be more than zero.")
            if rec.run_on_qty < 0:
                raise UserError("Qty - run on cannot be negative.")

    # ---------------------------------------------------------------- numbering
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                code = "print.estimate.standard" if vals.get("is_standard") else "print.estimate"
                vals["name"] = self.env["ir.sequence"].next_by_code(code) or "New"
        records = super().create(vals_list)
        for rec in records:
            if not rec.page_ids and rec.base_product_id.default_page_ids:
                rec.page_ids = rec._default_page_commands()
        return records

    def _default_page_commands(self):
        self.ensure_one()
        return [fields.Command.clear()] + [
            fields.Command.create({
                "sequence": line.sequence,
                "page_type_id": line.page_type_id.id,
                "pages": line.pages,
                "material_type": line.material_type,
                "material_id": line.material_id.id,
            }) for line in self.base_product_id.default_page_ids
        ]

    @api.onchange("base_product_id")
    def _onchange_base_product(self):
        if self.base_product_id and not self.page_ids:
            self.page_ids = self._default_page_commands()

    @api.onchange("partner_id")
    def _onchange_partner(self):
        if self.contact_id and self.contact_id.parent_id != self.partner_id:
            self.contact_id = False

    # ---------------------------------------------------------------- actions
    def _open(self, rec):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rec.id, "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def action_new_version(self):
        self.ensure_one()
        last = self.search([("name", "=", self.name)], order="version desc", limit=1)
        new = self.copy({"name": self.name, "version": last.version + 1, "state": "in_process"})
        new.message_post(body=f"Version {new.version} created from version {self.version}.")
        return self._open(new)

    def action_copy_estimate(self):
        self.ensure_one()
        new = self.copy({"job_name": f"{self.job_name} (copy)", "is_standard": False, "state": "in_process",
                         "date": fields.Date.context_today(self)})
        return self._open(new)

    def action_use_standard(self):
        """Start a new estimate from this standard."""
        self.ensure_one()
        if not self.is_standard:
            raise UserError("Only a standard can be used as a template.")
        new = self.copy({"is_standard": False, "state": "in_process", "template_id": self.id,
                         "date": fields.Date.context_today(self), "partner_id": False, "contact_id": False})
        return self._open(new)

    def action_save_as_standard(self):
        self.ensure_one()
        new = self.copy({"is_standard": True, "state": "in_process", "partner_id": False, "contact_id": False,
                         "job_name": self.job_name})
        return self._open(new)

    def action_set_quoted(self):
        self.write({"state": "quoted"})

    def action_set_lost(self):
        self.write({"state": "lost"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset(self):
        self.write({"state": "in_process"})

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", "New")
        return super().copy(default)


class PrintEstimatePage(models.Model):
    """A page type line of an estimate (DynamicsPrint Production / Overview / Pagetypes)."""
    _name = "print.estimate.page"
    _description = "Estimate page type"
    _order = "estimate_id, sequence, id"

    estimate_id = fields.Many2one("print.estimate", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    page_type_id = fields.Many2one("print.page.type", string="Page type", required=True, ondelete="restrict")
    kind = fields.Selection(related="page_type_id.kind", store=True)
    pages = fields.Integer("Pages", default=1,
                           help="Text: number of pages. Cover: 4. Sheet: leaves or pieces per copy.")
    material_type = fields.Selection(MATERIAL_TYPES, string="Material group")
    gsm_filter = fields.Float("Quality (gsm)", digits=(8, 1), help="Optional: limits the material list to this grammage.")
    material_id = fields.Many2one(
        "product.template", string="Paper no.",
        domain="[('print_is_sheet', '=', True), ('print_material_type', '=?', material_type), ('print_gsm', '=?', gsm_filter or False)]")
    material_desc = fields.Char(related="material_id.name", string="Paper description")
    manual_pricelist = fields.Boolean("Manual pricelist")

    @api.onchange("material_id")
    def _onchange_material(self):
        if self.material_id:
            self.material_type = self.material_id.print_material_type
            self.gsm_filter = self.material_id.print_gsm

    @api.constrains("pages")
    def _check_pages(self):
        for rec in self:
            if rec.pages <= 0:
                raise UserError(f"{rec.page_type_id.code}: pages must be more than zero.")
            if rec.kind == "text" and rec.pages % 2:
                raise UserError(f"{rec.page_type_id.code}: a text section needs an even number of pages.")


class PrintEstimateVersion(models.Model):
    """DynamicsPrint 'Versions - Bind legs' (shifts): e.g. English and Urdu editions of one job."""
    _name = "print.estimate.version"
    _description = "Estimate version (shift)"
    _order = "estimate_id, sequence, id"

    estimate_id = fields.Many2one("print.estimate", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    shift = fields.Char("Shifts/Ver", required=True)
    description = fields.Char()
    run_qty = fields.Integer("Run qty.")
    isbn = fields.Char("ISBN")
