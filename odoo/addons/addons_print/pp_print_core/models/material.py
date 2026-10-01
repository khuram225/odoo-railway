from odoo import api, fields, models

# 1 square inch = 0.00064516 m2; gsm = g per m2; kg per sheet = W x H x 0.00064516 x gsm / 1000
SQIN_TO_M2 = 0.00064516

MATERIAL_TYPES = [
    ("paper", "Paper"),
    ("card", "Card"),
    ("board", "Board"),
    ("sticker", "Sticker stock"),
    ("ink", "Ink"),
    ("plate", "Plate"),
    ("film", "Lamination film"),
    ("foil", "Foil"),
    ("varnish", "Varnish / UV"),
    ("glue", "Glue"),
    ("binding", "Binding material (wire, spiral, thread)"),
    ("packing", "Packing material"),
    ("chemical", "Chemical"),
    ("other", "Other"),
]
SHEET_TYPES = ("paper", "card", "board", "sticker")
PRICE_BASIS = [
    ("kg", "Per kg"),
    ("sheet", "Per sheet"),
    ("pack", "Per pack"),
    ("unit", "Per unit"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    print_material_type = fields.Selection(MATERIAL_TYPES, string="Print material type")
    print_is_sheet = fields.Boolean(compute="_compute_print_is_sheet", store=True)
    print_gsm = fields.Float("Grammage (gsm)", digits=(8, 2))
    print_width_in = fields.Float("Sheet width (in)", digits=(8, 3))
    print_height_in = fields.Float("Sheet height (in)", digits=(8, 3))
    print_caliper_micron = fields.Float("Thickness (microns)", digits=(8, 1))
    print_grain = fields.Selection([("long", "Long grain"), ("short", "Short grain"), ("none", "Not specified")],
                                   string="Grain", default="none")
    print_finish = fields.Selection([("gloss", "Coated gloss"), ("matt", "Coated matt"), ("uncoated", "Uncoated"),
                                     ("other", "Other")], string="Finish")
    print_colour = fields.Char("Colour")
    print_mill = fields.Char("Mill / brand")
    print_pack_name = fields.Char("Pack name", help="e.g. Ream, Packet, Roll")
    print_units_per_pack = fields.Float("Sheets / units per pack", digits=(10, 2))

    print_sheet_area_sqin = fields.Float("Sheet area (sq in)", compute="_compute_print_weights", digits=(10, 3))
    print_kg_per_sheet = fields.Float("Kg per sheet", compute="_compute_print_weights", digits=(10, 6))
    print_kg_per_pack = fields.Float("Kg per pack", compute="_compute_print_weights", digits=(10, 4))
    print_weight_note = fields.Char("How the weight is calculated", compute="_compute_print_weights")

    print_price_ids = fields.One2many("print.material.price", "product_tmpl_id", string="Prices")
    print_currency_id = fields.Many2one("res.currency", default=lambda s: s.env.company.currency_id)
    print_current_basis = fields.Selection(PRICE_BASIS, compute="_compute_print_cost", string="Current price basis")
    print_current_price = fields.Monetary(compute="_compute_print_cost", currency_field="print_currency_id",
                                          string="Current price")
    print_cost_per_sheet = fields.Monetary(compute="_compute_print_cost", currency_field="print_currency_id",
                                           string="Cost per sheet")
    print_cost_per_kg = fields.Monetary(compute="_compute_print_cost", currency_field="print_currency_id",
                                        string="Cost per kg")
    print_cost_note = fields.Char("How the cost is calculated", compute="_compute_print_cost")

    @api.depends("print_material_type")
    def _compute_print_is_sheet(self):
        for rec in self:
            rec.print_is_sheet = rec.print_material_type in SHEET_TYPES

    @api.depends("print_width_in", "print_height_in", "print_gsm", "print_units_per_pack")
    def _compute_print_weights(self):
        for rec in self:
            area = (rec.print_width_in or 0.0) * (rec.print_height_in or 0.0)
            kg = area * SQIN_TO_M2 * (rec.print_gsm or 0.0) / 1000.0
            rec.print_sheet_area_sqin = area
            rec.print_kg_per_sheet = kg
            rec.print_kg_per_pack = kg * (rec.print_units_per_pack or 0.0)
            rec.print_weight_note = (
                f"{rec.print_width_in:g} x {rec.print_height_in:g} in x 0.00064516 m2/sq in x {rec.print_gsm:g} gsm "
                f"/ 1000 = {kg:.6f} kg per sheet" if area and rec.print_gsm else ""
            )

    def print_kg_per_sheet_exact(self):
        """Unrounded kg per sheet (the stored field is rounded for display)."""
        self.ensure_one()
        return (self.print_width_in or 0.0) * (self.print_height_in or 0.0) * SQIN_TO_M2 * (self.print_gsm or 0.0) / 1000.0

    def print_price_on(self, date=None):
        """Price record effective on a date (latest 'valid from' on or before it)."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        return self.print_price_ids.filtered(lambda p: p.date_from <= date).sorted("date_from", reverse=True)[:1]

    def print_costs_on(self, date=None):
        """Return dict(cost_per_sheet, cost_per_kg, basis, price, note) for a date."""
        self.ensure_one()
        price = self.print_price_on(date)
        kg = self.print_kg_per_sheet_exact()
        per_pack = self.print_units_per_pack
        res = {"basis": price.basis if price else False, "price": price.price if price else 0.0,
               "cost_per_sheet": 0.0, "cost_per_kg": 0.0, "note": "No price valid on this date"}
        if not price:
            return res
        p = price.price
        if price.basis == "kg":
            res.update(cost_per_kg=p, cost_per_sheet=p * kg,
                       note=f"Rs {p:g}/kg x {kg:.6f} kg = Rs {p * kg:.4f} per sheet")
        elif price.basis == "sheet":
            res.update(cost_per_sheet=p, cost_per_kg=(p / kg) if kg else 0.0,
                       note=f"Rs {p:g} per sheet" + (f" = Rs {p / kg:.2f}/kg" if kg else ""))
        elif price.basis == "pack":
            per_sheet = p / per_pack if per_pack else 0.0
            res.update(cost_per_sheet=per_sheet, cost_per_kg=(per_sheet / kg) if kg else 0.0,
                       note=(f"Rs {p:g} per pack / {per_pack:g} = Rs {per_sheet:.4f} per sheet" if per_pack
                             else "Set 'Sheets / units per pack' to convert the pack price"))
        else:
            res.update(cost_per_sheet=p, note=f"Rs {p:g} per unit")
        return res

    @api.depends("print_price_ids.date_from", "print_price_ids.price", "print_price_ids.basis",
                 "print_width_in", "print_height_in", "print_gsm", "print_units_per_pack")
    def _compute_print_cost(self):
        for rec in self:
            c = rec.print_costs_on()
            rec.print_current_basis = c["basis"]
            rec.print_current_price = c["price"]
            rec.print_cost_per_sheet = c["cost_per_sheet"]
            rec.print_cost_per_kg = c["cost_per_kg"]
            rec.print_cost_note = c["note"]


class PrintMaterialPrice(models.Model):
    _name = "print.material.price"
    _description = "Material price (effective-dated)"
    _order = "date_from desc"

    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    date_from = fields.Date("Valid from", required=True, default=fields.Date.context_today)
    basis = fields.Selection(PRICE_BASIS, required=True, default="kg")
    currency_id = fields.Many2one(related="product_tmpl_id.print_currency_id")
    price = fields.Monetary(required=True)
    partner_id = fields.Many2one("res.partner", string="Supplier")
    note = fields.Char()
