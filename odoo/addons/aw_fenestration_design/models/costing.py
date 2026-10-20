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
from contextlib import closing

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

    def _costing_vendor(self):
        """Whose rates this window's profiles are costed at: the order's
        profile vendor, else its series' default, else the vendor every
        rate belonged to before vendors existed."""
        self.ensure_one()
        return (self.sale_order_id.aw_profile_vendor_id
                or self.template_id.default_vendor_id
                or self.env['aw.profile.rate']._legacy_vendor())

    def _profile_rate_keys(self):
        """(line, template, thickness, finish) for each costed profile
        line: the same resolution the costing uses, in one place so the
        by-vendor comparison cannot disagree with it."""
        self.ensure_one()
        section_lines = {}
        for source in (self._spec_profile_lines()
                       | self._added_profile_lines()):
            for template in source._profile_choices():
                section_lines.setdefault(template.id, source)
        keys = []
        for line in self.bom_line_ids:
            if line.kind != 'profile' or line.cut_on_site:
                continue
            template = line.product_id.product_tmpl_id
            source = section_lines.get(template.id)
            keys.append((
                line, template,
                self._line_thickness(source, template) if source else False,
                self._line_finish(source) if source else self.finish_id))
        return keys

    def _profile_cost_by_vendor(self):
        """This window's profile cost at each vendor's rates in force,
        for comparison. Only vendors that have any rate; "n of m variants
        priced" says how complete each figure is, and "rates as of" the
        newest effective date it used."""
        self.ensure_one()
        on_date = self._costing_date()
        rates = self.env['aw.profile.rate']
        order_vendor = self._costing_vendor()
        keys = self._profile_rate_keys()
        out = []
        self.env.cr.execute(
            "SELECT DISTINCT vendor_id FROM aw_profile_rate "
            "WHERE vendor_id IS NOT NULL AND active")
        for (vendor_id,) in self.env.cr.fetchall():
            vendor = self.env['res.partner'].browse(vendor_id)
            total, as_of = 0.0, False
            variants, priced = set(), set()
            for line, template, thickness, finish in keys:
                variant = (template.id, thickness.id if thickness else 0,
                           finish.id if finish else 0)
                variants.add(variant)
                rate, _level = rates._rate_lookup(
                    template, thickness, finish, on_date, vendor)
                if not rate:
                    continue
                priced.add(variant)
                total += ((line.length_mm or 0.0) / MM_PER_FOOT
                          * rate.price * (line.qty or 0))
                if not as_of or rate.date_from > as_of:
                    as_of = rate.date_from
            out.append({
                'id': vendor.id,
                'name': vendor.display_name,
                'total': total,
                'priced': len(priced),
                'variants': len(variants),
                'as_of': as_of.isoformat() if as_of else '',
                'is_order_vendor': vendor == order_vendor,
            })
        return sorted(out, key=lambda v: (not v['is_order_vendor'], v['name']))

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
        vendor = self._costing_vendor()
        # Keyed by TEMPLATE, not by the line's variant: phase 7e took
        # the variant off the line, and keying by template also finally
        # covers a divider built from one of the line's ALTERNATES --
        # whose variant was never in this map, so its thickness fell
        # back to False and the rate was looked up loosely.
        section_lines = {}
        for source in (self._spec_profile_lines()
                       | self._added_profile_lines()):
            for template in source._profile_choices():
                section_lines.setdefault(template.id, source)

        for line in self.bom_line_ids:
            unit_cost, rate_date, note = 0.0, False, ''

            if line.kind == 'profile' and line.cut_on_site:
                # Nothing to measure, so nothing to cost here.
                line.line_cost = 0.0

            elif line.kind == 'profile':
                # The BOM line's own template is authoritative -- it is
                # the profile that will be cut, default or alternate. The
                # spec line only supplies the thickness.
                template = line.product_id.product_tmpl_id
                source = section_lines.get(template.id)
                # The line's own thickness and finish choice. With no
                # choice these are exactly what they were: the spec
                # line's thickness and the window's finish.
                # (A BOM line carries no position, so a template that is
                # in no spec line -- an override's -- keeps the window's
                # finish and the loose thickness it always had.)
                rate, level = rates._rate_lookup(
                    template,
                    (self._line_thickness(source, template)
                     if source else False),
                    (self._line_finish(source) if source
                     else self.finish_id),
                    on_date, vendor)
                variant = line.product_id.display_name or template.display_name
                if rate:
                    unit_cost = rate.price
                    rate_date = rate.date_from
                    line.line_cost = (
                        (line.length_mm or 0.0) / MM_PER_FOOT
                        * rate.price * (line.qty or 0))
                    # A fallback is a rate for something else: never silent.
                    if level == 'thickness':
                        note = _(
                            "%(vendor)s has no rate for this finish on "
                            "%(variant)s; its rate for the thickness in any "
                            "finish is used.",
                            vendor=vendor.display_name, variant=variant)
                    elif level == 'template':
                        note = _(
                            "%(vendor)s has no rate for this thickness or "
                            "finish on %(variant)s; its rate for the profile "
                            "in any thickness and finish is used.",
                            vendor=vendor.display_name, variant=variant)
                else:
                    # No rate from this vendor: the variant's cost field
                    # (per metre) stands in, and the check says so.
                    # Profiles are costed per foot, the rate's own unit.
                    per_ft = line.product_id.standard_price or 0.0
                    unit_cost = per_ft
                    line.line_cost = (
                        (line.length_mm or 0.0) / MM_PER_FOOT
                        * per_ft * (line.qty or 0))
                    note = (_(
                        "No %(vendor)s rate for %(variant)s on %(date)s; "
                        "the cost field is used.",
                        vendor=vendor.display_name or _('profile'),
                        variant=variant, date=on_date) if per_ft else _(
                        "No %(vendor)s rate for %(variant)s on %(date)s, "
                        "and no cost field either.",
                        vendor=vendor.display_name or _('profile'),
                        variant=variant, date=on_date))

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
                # Only a line that carries NO cost is uncosted. A note on a
                # line that was costed anyway (a fallback rate, the cost
                # field standing in) is information, not a gap.
                if line.cost_note and not line.line_cost:
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
        underpriced, and the uncosted-lines warning already covers it.

        Compared at 0.01%, the precision it is shown at: 19.996% is
        "20.00%", and a message saying "20.0% is below 20.0%" is a bug."""
        floor = round(self._min_margin_pct(), 2)
        return self.filtered(
            lambda d: d.price_total and d.cost_total
            and round(d.margin_pct, 2) < floor)

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
                'structure_id': self.price_structure_id.id,
                'structure_options': [
                    {'id': s.id, 'name': s.display_name}
                    for s in self.env['aw.price.structure'].search([])],
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
                'by_vendor': self._profile_cost_by_vendor(),
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

    def preview_pricing(self, manual_rate, finish_id=False,
                        structure_id=False):
        """The Pricing tab as it would read with `manual_rate` and, when
        given, a different `finish_id`, WITHOUT saving anything.

        A manual rate only swaps the override, so it is plain arithmetic
        over the stored cost. A finish changes every profile's variant
        and rate, so it is explode + cost inside a savepoint that is
        always rolled back (`closing` rolls back on exit, and the
        numbers are read out before it does). Works from the STORED
        layout: panels edited but not yet saved are not part of it."""
        self.ensure_one()
        finish_changed = bool(finish_id) and finish_id != self.finish_id.id
        structure_changed = (
            bool(structure_id) and structure_id != self.price_structure_id.id)
        if finish_changed or structure_changed:
            with closing(self.env.cr.savepoint()):
                changes = {}
                if finish_changed:
                    changes['finish_id'] = finish_id
                if structure_changed:
                    changes['price_structure_id'] = structure_id
                self.write(changes)
                if finish_changed:
                    self._explode()
                return self._preview_pricing_values(manual_rate)
        return self._preview_pricing_values(manual_rate)

    def _preview_pricing_values(self, manual_rate):
        self.ensure_one()
        manual_rate = float(manual_rate or 0.0)
        pricing = dict(self._pricing_payload()['pricing'])
        units = max(1, self.qty or 1)
        total_sqft = (self.area_sqft or 0.0) * units
        manual = manual_rate * total_sqft if manual_rate else 0.0
        price = manual if manual_rate else self.basic_value

        def margin_of(value):
            return ((value - self.cost_total) / value * 100.0
                    if value else 0.0)

        pricing.update({
            'manual_rate': manual_rate,
            'manual_in_use': bool(manual_rate),
            'price': price,
            'price_per_sqft': price / total_sqft if total_sqft else 0.0,
            'margin_pct': margin_of(price),
            'manual_price': manual,
            'manual_margin_pct': margin_of(manual),
        })
        return pricing
