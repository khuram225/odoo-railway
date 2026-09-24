# -*- coding: utf-8 -*-
"""Costing and price (spec 8, Phase 6b).

The rule that shapes everything here: **a quote must not silently
recost itself**. Costs are snapshotted onto each BOM line at explosion
time, and the rate lookup uses the QUOTE'S order date, not today. So
re-saving a March quote in June still prices it at March's rates, and
the only way the number moves is if someone changes the design.

Cost flows in one direction:

    BOM line unit costs
      + wastage per material kind
      + labour x area
      = cost
      x (1 + profit)
      = basic value
      -> price (or manual_rate x area, if one is set)

Margin is measured against that cost, and a design under the floor is
an error on the design and a refusal at quote confirmation -- the same
hook core uses for its own pre-confirmation checks.
"""
from odoo import _, api, fields, models

MIN_MARGIN_PARAM = 'aw_fenestration.min_margin_pct'
DEFAULT_MIN_MARGIN = 20.0
MM_PER_FOOT = 304.8


class AwDesignBomLine(models.Model):
    _inherit = 'aw.design.bom.line'

    line_cost = fields.Float(
        string='Cost', digits='Product Price',
        help="unit_cost x the quantity this line represents. Snapshot, "
             "like unit_cost.")
    rate_date = fields.Date(
        string='Rate Of',
        help="Effective date of the rate used, so an old quote can be "
             "explained without guessing which price list it came from.")
    cost_note = fields.Char(
        help="Why this line has no cost, when it has none.")


class AwDesign(models.Model):
    _inherit = 'aw.design'

    price_structure_id = fields.Many2one(
        'aw.price.structure', string='Price Structure',
        compute='_compute_price_structure', store=True, readonly=False,
        ondelete='restrict',
        help="Empty falls back to the default structure.")

    cost_total = fields.Float(
        string='Cost', compute='_compute_pricing', store=True,
        digits='Product Price')
    basic_value = fields.Float(
        string='Basic Value', compute='_compute_pricing', store=True,
        digits='Product Price',
        help="Cost plus profit, before any manual override.")
    price_total = fields.Float(
        string='Price', compute='_compute_pricing', store=True,
        digits='Product Price')
    price_per_sqft = fields.Float(
        string='Price / sqft', compute='_compute_pricing', store=True,
        digits='Product Price')
    margin_pct = fields.Float(
        string='Margin %', compute='_compute_pricing', store=True)
    uncosted_line_count = fields.Integer(
        compute='_compute_pricing', store=True)
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_currency')

    def _compute_currency(self):
        for design in self:
            design.currency_id = design.env.company.currency_id

    @api.depends('window_series_id')
    def _compute_price_structure(self):
        for design in self:
            design.price_structure_id = (
                design.price_structure_id
                or self.env['aw.price.structure']._default_structure())

    # ------------------------------------------------------------------
    # cost snapshot, written by the explosion engine
    # ------------------------------------------------------------------
    def _costing_date(self):
        """The date the rates are looked up on.

        The quote's order date, so reopening and re-saving an old quote
        does not quietly reprice it. A design not yet on a quote has no
        such anchor and uses today.
        """
        self.ensure_one()
        order = self.sale_order_id
        if order and order.date_order:
            return fields.Date.to_date(order.date_order)
        return fields.Date.context_today(self)

    def _cost_bom_lines(self):
        """Attach cost to every BOM line, after explosion.

        A line with no cost is left at zero and given a `cost_note`
        saying why, which the checks then report. Guessing a price would
        be worse than showing none: an invented number reaches a
        customer, a zero plus a warning does not.
        """
        self.ensure_one()
        on_date = self._costing_date()
        rates = self.env['aw.profile.rate']
        section_lines = {
            line.product_id.id: line
            for line in self.profile_section_id.line_ids if line.product_id}

        for line in self.bom_line_ids:
            unit_cost, rate_date, note = 0.0, False, ''

            if line.kind == 'profile':
                source = section_lines.get(line.product_id.id)
                template = (source.product_tmpl_id if source
                            else line.product_id.product_tmpl_id)
                rate = rates._rate_for(
                    template,
                    source.thickness_id if source else False,
                    self.finish_id or (source.finish_id if source else False),
                    on_date)
                if rate:
                    unit_cost = rate.price
                    rate_date = rate.date_from
                    line.line_cost = (
                        (line.length_mm or 0.0) / MM_PER_FOOT
                        * rate.price * (line.qty or 0))
                else:
                    note = _("No rate for this profile on %s") % on_date
                    line.line_cost = 0.0

            elif line.kind == 'glass':
                unit_cost = line.product_id.standard_price or 0.0
                line.line_cost = unit_cost * (line.area_sqm or 0.0)
                if not unit_cost:
                    note = _("Glass product has no cost price")

            else:
                unit_cost = line.product_id.standard_price or 0.0
                line.line_cost = unit_cost * (line.qty or 0)
                if not unit_cost:
                    note = _("Product has no cost price")

            line.unit_cost = unit_cost
            line.rate_date = rate_date
            line.cost_note = note

    @api.depends('bom_line_ids.line_cost', 'bom_line_ids.kind',
                 'bom_line_ids.cost_note', 'price_structure_id.line_ids.value',
                 'area_sqm', 'area_sqft', 'manual_rate', 'qty')
    def _compute_pricing(self):
        for design in self:
            values = design.price_structure_id._values()
            profiles = glass = other = 0.0
            uncosted = 0
            for line in design.bom_line_ids:
                if line.cost_note:
                    uncosted += 1
                if line.kind == 'profile':
                    profiles += line.line_cost
                elif line.kind == 'glass':
                    glass += line.line_cost
                else:
                    other += line.line_cost

            # Everything below is for the WHOLE position, not one
            # window. The BOM lines already carry the design's qty (the
            # explosion multiplies by it), so area and the manual rate
            # have to be multiplied to match -- otherwise a qty of 4
            # would cost four windows and price one.
            units = max(1, design.qty or 1)
            total_sqm = (design.area_sqm or 0.0) * units
            total_sqft = (design.area_sqft or 0.0) * units

            material = (
                profiles * (1 + values['profile_wastage'] / 100.0)
                + glass * (1 + values['glass_wastage'] / 100.0)
                + other)
            labour = (values['fabrication_labour']
                      + values['install_labour']) * total_sqm
            cost = material + labour
            basic = cost * (1 + values['profit'] / 100.0)

            # manual_rate is per sqft and has always overridden the
            # calculated price; it overrides the cascade's result, not
            # the cost the margin is measured against.
            price = (design.manual_rate * total_sqft
                     if design.manual_rate else basic)

            design.cost_total = cost
            design.basic_value = basic
            design.price_total = price
            design.price_per_sqft = (
                price / total_sqft if total_sqft else 0.0)
            design.margin_pct = (
                (price - cost) / price * 100.0 if price else 0.0)
            design.uncosted_line_count = uncosted

    # ------------------------------------------------------------------
    # margin floor
    # ------------------------------------------------------------------
    @api.model
    def _min_margin_pct(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            MIN_MARGIN_PARAM)
        try:
            return float(raw) if raw not in (None, '') else DEFAULT_MIN_MARGIN
        except ValueError:
            return DEFAULT_MIN_MARGIN

    def _below_margin_floor(self):
        """Designs priced under the floor. Only ones that actually have
        a price: a design costing nothing yet is incomplete, not
        underpriced, and the uncosted-lines warning already covers it."""
        floor = self._min_margin_pct()
        return self.filtered(
            lambda d: d.price_total and d.cost_total
            and d.margin_pct < floor)

    def _pricing_payload(self):
        """The configurator's Pricing section. Internal only -- none of
        this goes near the customer PDF."""
        self.ensure_one()
        values = self.price_structure_id._values()
        # Both prices, always, so the panel can show what the manual rate
        # is being used INSTEAD OF. Showing only the one in force makes
        # the override impossible to judge.
        units = max(1, self.qty or 1)
        total_sqft = (self.area_sqft or 0.0) * units
        calculated = self.basic_value
        manual = self.manual_rate * total_sqft if self.manual_rate else 0.0

        def margin_of(price):
            return ((price - self.cost_total) / price * 100.0
                    if price else 0.0)

        return {
            'pricing': {
                'structure': self.price_structure_id.display_name or '',
                'currency': self.env.company.currency_id.symbol or '',
                'cost': self.cost_total,
                'basic_value': self.basic_value,
                'price': self.price_total,
                'price_per_sqft': self.price_per_sqft,
                'margin_pct': self.margin_pct,
                'min_margin_pct': self._min_margin_pct(),
                'manual_rate': self.manual_rate,
                'manual_in_use': bool(self.manual_rate),
                'calculated_price': calculated,
                'calculated_per_sqft': (
                    calculated / total_sqft if total_sqft else 0.0),
                'calculated_margin_pct': margin_of(calculated),
                'manual_price': manual,
                'manual_margin_pct': margin_of(manual),
                'uncosted': self.uncosted_line_count,
                'components': [
                    {'name': line.name,
                     'value': line.value,
                     'unit': line.unit}
                    for line in self.price_structure_id.line_ids
                ],
                'by_kind': [
                    {'kind': kind,
                     'cost': sum(
                         line.line_cost for line in self.bom_line_ids
                         if line.kind == kind)}
                    for kind in ('profile', 'glass', 'hardware', 'mesh',
                                 'infill', 'grid')
                ],
                'wastage': {
                    'profile': values['profile_wastage'],
                    'glass': values['glass_wastage'],
                },
            },
        }
