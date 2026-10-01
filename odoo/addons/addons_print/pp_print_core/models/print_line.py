import math

from odoo import api, fields, models
from odoo.exceptions import UserError

from .engine import CUTS, cut_dims, fits, layout
from .res_config_settings import PARAM_GAP, PARAM_STRIP, print_param

SCRAP_METHODS = [
    ("wc", "Work centre: make-ready sheets + running %"),
    ("copies", "Extra copies"),
    ("sheets", "Extra paper sheets"),
]


class PrintEstimatePage(models.Model):
    """Print overview: the print fields and results of each page type line."""
    _inherit = "print.estimate.page"

    # ---------------------------------------------------------------- inputs
    press_id = fields.Many2one("print.workcenter", string="Base (press)",
                               domain="[('workcenter_type', 'in', ('offset', 'digital'))]",
                               help="Empty = Auto: the smallest press with enough colour units that fits.")
    imposition_id = fields.Many2one("print.imposition", string="Imposition", domain="[('category', '=', 'sheet')]",
                                    help="Empty = Auto: best fit calculated from the sheet and page sizes.")
    designs = fields.Integer("Designs", default=1, help="Sheet page types: number of different designs (each needs its own plates).")
    colours_front = fields.Integer("F", default=4)
    colours_back = fields.Integer("B", default=0)
    paper_parts = fields.Integer("Paperparts", default=0, help="Print sheets cut from one paper sheet; 0 = calculated.")
    workstyle = fields.Selection([("sheetwise", "Sheetwise"), ("turn", "Work and turn")], default="sheetwise", required=True)
    scrap_method = fields.Selection(SCRAP_METHODS, default="wc", required=True)
    scrap_value = fields.Float("Scrap value", help="Extra copies or extra paper sheets, depending on the method.")
    extra_plates = fields.Integer("Extra plates")
    version_plates = fields.Integer("Ver. plates")
    ink_use_pct = fields.Float("Ink use %", default=100.0)
    wash_ups = fields.Integer("Wash up")
    pms_no = fields.Char("PMS no.")
    primary_band = fields.Char("Primary band")
    secondary_band = fields.Char("Secondary band")
    print_remarks = fields.Text("Print remarks")

    # ---------------------------------------------------------------- results (written by _calculate)
    calc_ok = fields.Boolean(readonly=True, copy=False)
    calc_error = fields.Char(readonly=True, copy=False)
    calc_date = fields.Datetime("Calculated on", readonly=True, copy=False)
    press_used_id = fields.Many2one("print.workcenter", string="Press used", readonly=True, copy=False)
    end_width_in = fields.Float("End format W", digits=(8, 3), readonly=True, copy=False)
    end_height_in = fields.Float("End format H", digits=(8, 3), readonly=True, copy=False)
    spine_in = fields.Float("Spine (in)", digits=(8, 3), readonly=True, copy=False)
    paper_width_in = fields.Float("Paper format W", digits=(8, 3), readonly=True, copy=False)
    paper_height_in = fields.Float("Paper format H", digits=(8, 3), readonly=True, copy=False)
    print_width_in = fields.Float("Print format W", digits=(8, 3), readonly=True, copy=False)
    print_height_in = fields.Float("Print format H", digits=(8, 3), readonly=True, copy=False)
    parts_used = fields.Integer("Parts", readonly=True, copy=False)
    layout_text = fields.Char("Layout", readonly=True, copy=False)
    no_up = fields.Integer("No. up", readonly=True, copy=False)
    pages_per_sheet = fields.Integer("Pp./sht.", readonly=True, copy=False)
    sheets_per_copy = fields.Float("Sheet", digits=(10, 3), readonly=True, copy=False,
                                   help="Print sheets per copy (text: sections; sheet: designs).")
    passes = fields.Integer(readonly=True, copy=False)
    runs = fields.Integer("Make-readies", readonly=True, copy=False)
    print_net = fields.Float("Print net", digits=(12, 2), readonly=True, copy=False)
    print_total = fields.Float("Print total", digits=(12, 2), readonly=True, copy=False)
    scrap_qty = fields.Float("Scrap sheets", digits=(12, 2), readonly=True, copy=False)
    scrap_pct = fields.Float("Scrap %", digits=(6, 2), readonly=True, copy=False)
    impressions_per_run = fields.Float("Impressions per run", digits=(12, 0), readonly=True, copy=False)
    paper_sheets = fields.Float("Paper sheets", digits=(12, 2), readonly=True, copy=False)
    paper_kg = fields.Float("Kg", digits=(12, 2), readonly=True, copy=False)
    plates_calc = fields.Integer("Plates (calculated)", readonly=True, copy=False)
    plates_total = fields.Integer("Plates", readonly=True, copy=False)
    paper_cost_per_sheet = fields.Float("Paper cost / sheet", digits=(12, 4), readonly=True, copy=False)
    paper_cost = fields.Float("Paper cost", digits=(14, 2), readonly=True, copy=False)
    calc_log_ids = fields.One2many("print.estimate.page.log", "page_id", string="Calculation", readonly=True, copy=False)

    # ---------------------------------------------------------------- engine
    def _thickness_in(self):
        self.ensure_one()
        mic = self.material_id.print_caliper_micron
        return (mic or 0.0) / 25400.0

    def _choose_press(self, piece_w, piece_h, spine, max_colours):
        """Auto press: smallest offset press with enough colour units on which the piece fits.
        (Base-product rules replace this in a later step.)"""
        strip, gap = print_param(self.env, PARAM_STRIP, 0.2), print_param(self.env, PARAM_GAP, 0.0)
        presses = self.env["print.workcenter"].search(
            [("workcenter_type", "=", "offset"), ("status", "!=", "retired")])
        presses = presses.sorted(lambda w: (w.max_width_in * w.max_height_in, w.code))
        mat = self.material_id
        for wc in presses:
            if wc.colour_units < min(max_colours, 4):
                continue
            for parts in CUTS:
                pw, ph = cut_dims(mat.print_width_in, mat.print_height_in, parts)
                if not fits(pw, ph, wc.max_width_in, wc.max_height_in):
                    continue
                lay = layout(self.kind, pw, ph, piece_w, piece_h, spine, wc.gripper_in, strip, gap)
                if lay and lay["n"] > 0:
                    return wc
        return False

    def _calculate(self, spine):
        """Calculate one print line and store results plus a step-by-step log."""
        self.ensure_one()
        est = self.estimate_id
        log = []

        def step(name, how, result):
            log.append((name, how, result))

        def fail(msg):
            self._write_results({"calc_ok": False, "calc_error": msg}, log)

        mat = self.material_id
        run = est.run_qty
        pages = self.pages
        f, b = self.colours_front, self.colours_back
        max_c = max(f, b)
        if not mat:
            return fail("Choose a paper (Paper no.).")
        if not (mat.print_width_in and mat.print_height_in and mat.print_gsm):
            return fail(f"Material {mat.display_name} needs width, height and gsm.")
        if not (est.width_in and est.height_in):
            return fail("Set the format or W x H on the estimate.")

        # end format
        piece_w, piece_h = est.width_in, est.height_in
        if self.kind == "cover":
            step("End format (cover spread)",
                 f"2 x {est.width_in:g} + spine {spine:.3f} in (text pages / 2 x paper thickness)",
                 f"{2 * est.width_in + spine:.2f} x {piece_h:.2f} in")
        else:
            step("End format", "page size from the estimate" if self.kind == "text" else "piece size from the estimate",
                 f"{piece_w:.2f} x {piece_h:.2f} in")

        # press
        wc = self.press_id
        why = "set on the line"
        if not wc:
            wc = self._choose_press(piece_w, piece_h, spine, max_c)
            why = "Auto: smallest offset press with enough colour units that fits"
        if not wc:
            return fail("No press fits this line. Set Base (press) or check the work centres' sizes.")
        step("Base (press)", why, wc.display_name)
        digital = wc.workcenter_type == "digital"
        units = max(1, wc.colour_units or 1)

        # paper -> print format
        if self.paper_parts:
            parts = self.paper_parts
            if parts not in CUTS:
                return fail(f"Paperparts {parts} is not supported; use 1, 2, 3, 4, 6 or 8.")
            pw, ph = cut_dims(mat.print_width_in, mat.print_height_in, parts)
            if not fits(pw, ph, wc.max_width_in, wc.max_height_in):
                return fail(f"Paperparts {parts} gives {pw:.2f} x {ph:.2f} in, too big for {wc.name} "
                            f"(max {wc.max_width_in:g} x {wc.max_height_in:g}).")
            how = f"Paperparts {parts} set on the line"
        else:
            parts = next((p for p in CUTS if fits(*cut_dims(mat.print_width_in, mat.print_height_in, p),
                                                  wc.max_width_in, wc.max_height_in)), 0)
            if not parts:
                return fail(f"Paper {mat.print_width_in:g} x {mat.print_height_in:g} cannot be cut to fit {wc.name}.")
            pw, ph = cut_dims(mat.print_width_in, mat.print_height_in, parts)
            how = f"smallest cut of {mat.print_width_in:g} x {mat.print_height_in:g} that fits {wc.name} (max {wc.max_width_in:g} x {wc.max_height_in:g})"
        step("Paper format -> print format", how, f"{parts} part(s) of {pw:.2f} x {ph:.2f} in")

        # imposition
        imp = self.imposition_id
        strip, gap = print_param(self.env, PARAM_STRIP, 0.2), print_param(self.env, PARAM_GAP, 0.0)
        if imp:
            lay = layout(self.kind, pw, ph, piece_w, piece_h, spine, wc.gripper_in, strip, gap,
                         cols=imp.columns, rows=imp.rows, col_group=imp.column_group, row_group=imp.row_group,
                         orientation=imp.plate_orientation, grip_dir=imp.gripper_allowance, strip_pos=imp.color_strip)
            if not lay["fits"]:
                return fail(f"Imposition {imp.code} does not fit: needs {lay['need_w']:.2f} x {lay['need_h']:.2f} in, "
                            f"sheet allows {lay['avail_w']:.2f} x {lay['avail_h']:.2f} in.")
            lay_how = f"imposition {imp.code} ({imp.name}): {imp.columns} columns x {imp.rows} rows"
        else:
            lay = layout(self.kind, pw, ph, piece_w, piece_h, spine, wc.gripper_in, strip, gap)
            lay_how = f"Auto: best fit, {lay['cols']} across x {lay['rows']} high"
        lay_how += (f", {'upright' if lay['orientation'] == 'portrait' else 'turned'}; needs {lay['need_w']:.2f} x {lay['need_h']:.2f} in, "
                    f"available {lay['avail_w']:.2f} x {lay['avail_h']:.2f} in ({lay['other']:.2f} - {wc.gripper_in:g} gripper - {strip:g} colour strip)")
        n = lay["n"]
        if n < 1:
            return fail(f"{piece_w:.2f} x {piece_h:.2f} does not fit on {pw:.2f} x {ph:.2f}.")
        code = f"B {lay['cols']}B {lay['rows']}H {'steh' if lay['orientation'] == 'portrait' else 'lieg'} {lay['cols'] * lay['rows'] * 2}"
        match = imp or self.env["print.imposition"].search(
            [("category", "=", "sheet"), ("columns", "=", lay["cols"]), ("rows", "=", lay["rows"]),
             ("plate_orientation", "=", lay["orientation"]), ("gripper_allowance", "=", "across")], limit=1)

        # quantities
        if wc.perfecting:
            passes = math.ceil(max_c / units)
            pass_how = f"perfecting: {max_c} colours / {units} units"
        else:
            passes = (math.ceil(f / units) if f else 0) + (math.ceil(b / units) if b else 0)
            pass_how = f"front {f} / {units} units + back {b} / {units} units, rounded up"
        if self.kind == "text":
            if pages % 2:
                return fail("A text section needs an even number of pages.")
            pps = n
            pp_sheet = 2 * pps
            per_copy = pages / pp_sheet
            sides = math.ceil(pages / pps)
            fronts, backs = math.ceil(sides / 2), sides // 2
            step("Imposition (pages per side)", lay_how, str(pps))
            step("Pp./sht. and Sheet", f"{pps} x 2 sides = {pp_sheet} pages per print sheet; {pages} pages / {pp_sheet}",
                 f"{per_copy:.3f} print sheet(s) per copy, {sides} printed sides")
            if self.workstyle == "turn":
                plates = 0 if digital else fronts * max_c
                runs = fronts * math.ceil(max_c / units)
                plate_how = f"work and turn: {fronts} plate set(s) x {max_c} colours"
            else:
                plates = 0 if digital else fronts * f + backs * b
                runs = fronts * (math.ceil(f / units) if f else 0) + backs * (math.ceil(b / units) if b else 0)
                plate_how = f"{fronts} fronts x {f} + {backs} backs x {b} colours"
            net = run * per_copy
            no_up = 1
            step("Print net", f"{run:,} copies x {per_copy:.3f} sheets", f"{net:,.2f} sheets")
        else:
            no_up = n
            forms = max(1, self.designs)
            leaves = 1 if self.kind == "cover" else pages
            pp_sheet = no_up * (4 if self.kind == "cover" else (2 if b else 1))
            per_copy = leaves / no_up
            net = run * per_copy
            plates = 0 if digital else forms * (max_c if self.workstyle == "turn" else f + b)
            runs = forms * passes
            plate_how = f"{forms} design(s) x ({f} + {b}) colours" if self.workstyle != "turn" else f"{forms} design(s) x {max_c} colours (work and turn)"
            step("Imposition (No. up)", lay_how, str(no_up))
            step("Print net", (f"{run:,} copies / {no_up} up" if self.kind == "cover"
                               else f"{run:,} copies x {leaves} leaf/leaves / {no_up} up"), f"{net:,.2f} sheets")
        step("Passes", pass_how, str(passes))

        # scrap
        if self.scrap_method == "copies":
            total = per_copy * (run + self.scrap_value)
            scrap_how = f"{per_copy:.3f} sheets per copy x ({run:,} + {self.scrap_value:g} extra copies)"
        elif self.scrap_method == "sheets":
            total = net + self.scrap_value * parts
            scrap_how = f"{net:,.2f} + {self.scrap_value:g} extra paper sheets x {parts} parts"
        else:
            mr = runs * wc.makeready_sheets
            rw = net * wc.running_waste_pct / 100.0
            total = net + mr + rw
            scrap_how = (f"{net:,.2f} net + {runs} make-ready(s) x {wc.makeready_sheets:g} sheets + "
                         f"{wc.running_waste_pct:g}% running waste ({wc.name})")
        scrap = total - net
        scrap_pct = scrap / net * 100 if net else 0.0
        step("Print total (with scrap)", scrap_how, f"{total:,.2f} sheets ({scrap:,.2f} scrap, {scrap_pct:.1f}%)")

        paper_sheets = total / parts
        kg = paper_sheets * mat.print_kg_per_sheet_exact()
        step("Paper usage", f"{total:,.2f} print sheets / {parts} parts per paper sheet",
             f"{paper_sheets:,.2f} sheets of {mat.print_width_in:g} x {mat.print_height_in:g}")
        step("Kg", f"{paper_sheets:,.2f} x {mat.print_kg_per_sheet_exact():.6f} kg per sheet ({mat.print_weight_note})", f"{kg:,.2f} kg")

        plates_total = plates + self.extra_plates + self.version_plates
        step("Plates", ("digital press: no plates" if digital else plate_how)
             + f" + {self.extra_plates} extra + {self.version_plates} version plates", str(plates_total))

        imp_run = total / max(per_copy if self.kind == "text" else max(1, self.designs), 1e-9)
        step("Impressions per run", f"{total:,.2f} print sheets / {per_copy if self.kind == 'text' else max(1, self.designs):g} "
             f"({'positions' if self.kind == 'text' else 'designs'})", f"{imp_run:,.0f}")

        costs = mat.print_costs_on(est.date)
        cost = paper_sheets * costs["cost_per_sheet"]
        step("Paper cost", f"{paper_sheets:,.2f} sheets x {costs['cost_per_sheet']:.4f} ({costs['note']}; prices valid on {est.date})",
             f"{cost:,.2f}")

        self._write_results({
            "calc_ok": True, "calc_error": False, "press_used_id": wc.id,
            "end_width_in": 2 * est.width_in + spine if self.kind == "cover" else piece_w, "end_height_in": piece_h,
            "spine_in": spine if self.kind == "cover" else 0.0,
            "paper_width_in": mat.print_width_in, "paper_height_in": mat.print_height_in,
            "print_width_in": pw, "print_height_in": ph, "parts_used": parts,
            "layout_text": (f"{match.code} ({code})" if match else code),
            "no_up": no_up, "pages_per_sheet": pp_sheet, "sheets_per_copy": per_copy if self.kind == "text" else max(1, self.designs),
            "passes": passes, "runs": runs, "print_net": net, "print_total": total, "scrap_qty": scrap, "scrap_pct": scrap_pct,
            "impressions_per_run": imp_run, "paper_sheets": paper_sheets, "paper_kg": kg,
            "plates_calc": plates, "plates_total": plates_total,
            "paper_cost_per_sheet": costs["cost_per_sheet"], "paper_cost": cost,
        }, log)
        return True

    def _write_results(self, vals, log):
        vals = dict(vals)
        vals["calc_date"] = fields.Datetime.now()
        vals["calc_log_ids"] = [fields.Command.clear()] + [
            fields.Command.create({"sequence": i, "step": s, "how": h, "result": r}) for i, (s, h, r) in enumerate(log)]
        if not vals.get("calc_ok"):
            for name in ("press_used_id", "no_up", "pages_per_sheet", "sheets_per_copy", "passes", "runs", "print_net",
                         "print_total", "scrap_qty", "scrap_pct", "impressions_per_run", "paper_sheets", "paper_kg",
                         "plates_calc", "plates_total", "paper_cost_per_sheet", "paper_cost", "parts_used"):
                vals.setdefault(name, False)
        self.with_context(print_skip_calc=True).write(vals)

    def action_open_print_line(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "views": [(self.env.ref("pp_print_core.view_print_line_form").id, "form")],
            "target": "new", "name": f"{self.estimate_id.name} / {self.page_type_id.code}",
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "colours_back" not in vals and vals.get("page_type_id"):
                kind = self.env["print.page.type"].browse(vals["page_type_id"]).kind
                vals["colours_back"] = 4 if kind == "text" else 0
        recs = super().create(vals_list)
        if not self.env.context.get("print_skip_calc"):
            recs.mapped("estimate_id")._run_calculation()
        return recs

    @api.onchange("page_type_id")
    def _onchange_page_type_colours(self):
        if self.page_type_id.kind == "text" and not self.colours_back:
            self.colours_back = 4

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("print_skip_calc"):
            self.mapped("estimate_id")._run_calculation()
        return res

    @api.constrains("designs", "colours_front", "colours_back", "ink_use_pct", "extra_plates", "version_plates", "scrap_value")
    def _check_print_inputs(self):
        for rec in self:
            if rec.designs < 1:
                raise UserError(f"{rec.page_type_id.code}: designs must be at least 1.")
            if min(rec.colours_front, rec.colours_back, rec.extra_plates, rec.version_plates) < 0 or rec.scrap_value < 0:
                raise UserError(f"{rec.page_type_id.code}: colours, plates and scrap cannot be negative.")
            if rec.colours_front == 0 and rec.colours_back == 0 and rec.kind != "sheet":
                raise UserError(f"{rec.page_type_id.code}: at least one side must be printed.")


class PrintEstimatePageLog(models.Model):
    _name = "print.estimate.page.log"
    _description = "Print line calculation step"
    _order = "page_id, sequence"

    page_id = fields.Many2one("print.estimate.page", required=True, ondelete="cascade")
    sequence = fields.Integer()
    step = fields.Char(required=True)
    how = fields.Char("How it is calculated")
    result = fields.Char()


class PrintEstimate(models.Model):
    _inherit = "print.estimate"

    print_line_ids = fields.One2many("print.estimate.page", "estimate_id", string="Print overview")
    calc_warning = fields.Char(compute="_compute_calc_warning")
    total_paper_kg = fields.Float("Paper kg", compute="_compute_print_totals", digits=(12, 2))
    total_paper_cost = fields.Float("Paper cost", compute="_compute_print_totals", digits=(14, 2))
    total_plates = fields.Integer("Plates", compute="_compute_print_totals")

    @api.depends("page_ids.calc_ok", "page_ids.calc_error")
    def _compute_calc_warning(self):
        for rec in self:
            errs = [f"{p.page_type_id.code}: {p.calc_error}" for p in rec.page_ids if p.calc_error]
            rec.calc_warning = " | ".join(errs) if errs else False

    @api.depends("page_ids.paper_kg", "page_ids.paper_cost", "page_ids.plates_total")
    def _compute_print_totals(self):
        for rec in self:
            rec.total_paper_kg = sum(rec.page_ids.mapped("paper_kg"))
            rec.total_paper_cost = sum(rec.page_ids.mapped("paper_cost"))
            rec.total_plates = sum(rec.page_ids.mapped("plates_total"))

    def _spine_in(self):
        self.ensure_one()
        return sum(p.pages / 2 * p._thickness_in() for p in self.page_ids if p.kind == "text")

    def _run_calculation(self):
        for rec in self:
            spine = rec._spine_in()
            for line in rec.page_ids:
                line._calculate(spine)

    def action_calculate(self):
        self._run_calculation()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get("print_skip_calc"):
            recs._run_calculation()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("print_skip_calc"):
            self._run_calculation()
        return res
