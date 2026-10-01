from markupsafe import Markup

from odoo import api, fields, models

INPUT_VARIABLES = [
    ("print_total_per_run", "Print total per run (sheets)"),
    ("grammage", "Paper grammage (gsm)"),
    ("ink_use", "Ink use (%)"),
    ("colours", "Colours per pass"),
    ("no_up", "No. up"),
    ("sheet_area", "Print sheet area (sq in)"),
    ("units", "Units processed"),
    ("pages_bound", "Pages bound"),
]
CALC_METHODS = [
    ("min", "Min"),
    ("max", "Max"),
    ("average", "Average"),
    ("multiply", "Multiply"),
]


class PrintFactorGroup(models.Model):
    """DynamicsPrint factor group: combines several factors (e.g. speed by run length,
    by grammage, by ink use) into one value for a work centre."""
    _name = "print.factor.group"
    _description = "Factor group"
    _order = "code"

    code = fields.Char("Factor group id", required=True)
    name = fields.Char(required=True)
    calc_method = fields.Selection(CALC_METHODS, string="Calculation", required=True, default="min")
    factor_ids = fields.One2many("print.factor", "group_id", string="Config lines")
    workcenter_ids = fields.One2many("print.workcenter", "factor_group_id", string="Used by work centres")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Factor group id must be unique.")

    def evaluate(self, inputs):
        """Return (value, explanation) for a dict of input values keyed by INPUT_VARIABLES codes.
        Factors whose input is missing use their initial value; factors with no value are skipped."""
        self.ensure_one()
        labels = dict(INPUT_VARIABLES)
        results = []
        for factor in self.factor_ids:
            x = inputs.get(factor.input_variable)
            value = factor.value_at(x)
            if value is None:
                continue
            results.append((factor, x, value))
        if not results:
            return None, f"Factor group {self.code}: no usable config lines"
        values = [v for _, _, v in results]
        if self.calc_method == "max":
            total = max(values)
        elif self.calc_method == "average":
            total = sum(values) / len(values)
        elif self.calc_method == "multiply":
            total = 1.0
            for v in values:
                total *= v
        else:
            total = min(values)
        parts = "; ".join(
            f"{f.code} at {labels[f.input_variable]} {'n/a' if x is None else round(x, 2)} = {round(v, 2)}"
            for f, x, v in results
        )
        method = dict(CALC_METHODS)[self.calc_method]
        return total, f"Factor group {self.code} ({self.name}, {method}): {parts} -> {round(total, 2)}"


class PrintFactor(models.Model):
    """DynamicsPrint config line: one input variable mapped to an output by a diagram (points)."""
    _name = "print.factor"
    _description = "Factor (config line)"
    _order = "group_id, sequence, code"

    group_id = fields.Many2one("print.factor.group", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    code = fields.Char("Factor id", required=True)
    name = fields.Char(required=True)
    input_variable = fields.Selection(INPUT_VARIABLES, string="Input (reference field)", required=True)
    initial_value = fields.Float("Initial value", help="Output used when the input is not available.")
    use_initial = fields.Boolean("Use initial value when input is missing")
    point_ids = fields.One2many("print.factor.point", "factor_id", string="Diagram")
    diagram_svg = fields.Html(compute="_compute_diagram", sanitize=False, string="Diagram chart")

    def value_at(self, x):
        """Linear interpolation between diagram points; flat below the first and above the last point."""
        self.ensure_one()
        pts = sorted((p.input_value, p.output_value) for p in self.point_ids)
        if x is None:
            if self.use_initial:
                return self.initial_value
            return pts[0][1] if pts else None
        if not pts:
            return self.initial_value if self.use_initial else None
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]

    @api.depends("point_ids.input_value", "point_ids.output_value", "name")
    def _compute_diagram(self):
        for rec in self:
            pts = sorted((p.input_value, p.output_value) for p in rec.point_ids)
            if not pts:
                rec.diagram_svg = Markup("<p>No points yet.</p>")
                continue
            w, h, left, bottom, top, right = 520, 230, 60, 30, 20, 15
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, x1 = min(xs), max(xs)
            y1 = (max(ys) or 1) * 1.1

            def sx(x):
                return left + (0.5 if x1 == x0 else (x - x0) / (x1 - x0)) * (w - left - right)

            def sy(y):
                return h - bottom - (y / y1) * (h - bottom - top)

            grid = "".join(
                f'<line x1="{left}" y1="{sy(y1*k/4):.1f}" x2="{w-right}" y2="{sy(y1*k/4):.1f}" stroke="#ddd"/>'
                f'<text x="{left-4}" y="{sy(y1*k/4)+4:.1f}" font-size="10" text-anchor="end">{y1*k/4:,.0f}</text>'
                for k in range(5)
            )
            xl = "".join(f'<text x="{sx(x):.1f}" y="{h-bottom+14}" font-size="10" text-anchor="middle">{x:,.0f}</text>' for x, _ in pts)
            line = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
            dots = "".join(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5" fill="#1D63AE"/>' for x, y in pts)
            label = dict(INPUT_VARIABLES).get(rec.input_variable, "")
            rec.diagram_svg = Markup(
                f'<svg viewBox="0 0 {w} {h}" style="width:100%;max-width:{w}px" role="img" aria-label="{rec.name}">'
                f'<text x="{w/2}" y="14" font-size="12" font-weight="700" text-anchor="middle">{rec.name or ""}</text>'
                f'{grid}{xl}<polyline points="{line}" fill="none" stroke="#1D63AE" stroke-width="2"/>{dots}'
                f'<text x="{w/2}" y="{h-2}" font-size="10" text-anchor="middle" fill="#555">{label}</text></svg>'
            )


class PrintFactorPoint(models.Model):
    _name = "print.factor.point"
    _description = "Factor diagram point"
    _order = "input_value"

    factor_id = fields.Many2one("print.factor", required=True, ondelete="cascade")
    input_value = fields.Float("Input", required=True)
    output_value = fields.Float("Output", required=True)
