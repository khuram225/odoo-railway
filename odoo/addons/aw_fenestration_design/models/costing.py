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
SQFT_PER_SQM = 10.7639104



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

    def _fallback_vendor(self):
        """Who prices a profile the order's vendor has no rate for: the
        series' default vendor, and only when that is somebody else."""
        self.ensure_one()
        fallback = (self.template_id.default_vendor_id
                    or self.env['aw.profile.rate']._legacy_vendor())
        if fallback == self._costing_vendor():
            return self.env['res.partner']
        return fallback

    def _rate_with_fallback(self, template, thickness, finish, on_date):
        """(rate, level, used_fallback): the order vendor's rate, else the
        series' default vendor's. Nothing from either is no rate; the cost
        field of the variant is never consulted."""
        rates = self.env['aw.profile.rate']
        rate, level = rates._rate_lookup(
            template, thickness, finish, on_date, self._costing_vendor())
        if rate:
            return rate, level, False
        fallback = self._fallback_vendor()
        if fallback:
            rate, level = rates._rate_lookup(
                template, thickness, finish, on_date, fallback)
            if rate:
                return rate, level, True
        return rate, level, False

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

    def _missing_rate_info(self):
        """([text], {bom line ids}): see _missing_rate_entries."""
        self.ensure_one()
        entries = self._missing_rate_entries()
        return ([e[0] for e in entries],
                set().union(*[e[2] for e in entries]) if entries else set())

    def _missing_rate_entries(self):
        """[(text, profile template, {bom line ids})]: the profiles the
        costing vendor has no rate for, one entry per profile and
        thickness, naming the vendor whose rate stands in, or saying the
        price is incomplete. The same lookup the costing does, so this
        cannot disagree with the number. The template is where a Checks
        row leads."""
        self.ensure_one()
        on_date = self._costing_date()
        vendor = self._costing_vendor()
        fallback = self._fallback_vendor()
        entries, by_key = [], {}
        for line, template, thickness, finish in self._profile_rate_keys():
            rate, _level, used_fallback = self._rate_with_fallback(
                template, thickness, finish, on_date)
            if rate and not used_fallback:
                continue
            key = (template.id, thickness.id if thickness else 0)
            if key in by_key:
                by_key[key].add(line.id)
                continue
            line_ids = {line.id}
            by_key[key] = line_ids
            label = ' '.join(filter(None, [
                template.default_code or template.name,
                thickness.name if thickness else '']))
            if rate:
                entries.append((_(
                    "%(profile)s: no %(vendor)s rate, %(standin)s rate used",
                    profile=label, vendor=vendor.display_name or _('profile'),
                    standin=fallback.display_name),
                    template, line_ids))
            else:
                entries.append((_(
                    "%(profile)s: no %(vendor)s rate%(also)s, price "
                    "incomplete",
                    profile=label, vendor=vendor.display_name or _('profile'),
                    also=(_(" and no %s rate", fallback.display_name)
                          if fallback else '')),
                    template, line_ids))
        return entries

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

    def _glass_extra_problems(self):
        """A gap whose spacer, or whose gas (other than Air), has no rate in
        Glass Extras is costed at nothing, silently, by design: a missing
        price there is expected until the supplier gives one. This names
        each such panel and item so it can be seen. WARNING only: it
        changes no price. The link goes to the panel's glass; Checks links
        cannot open an action, so the text says where to add the rate.
        """
        self.ensure_one()
        Extra = self.env['aw.glass.extra']
        on_date = self._costing_date()
        vendor = self._glass_vendor()
        problems, seen = [], set()
        for line in self.bom_line_ids.filtered(
                lambda l: l.kind == 'glass' and l.glass_part_kind == 'gap'):
            panel = line.panel_no or 0
            spacer = (line.glass_spacer or '').strip()
            gas = (line.glass_gas or '').strip()
            key = ('spacer', panel, spacer.lower())
            if spacer and key not in seen and not Extra._rate_for(
                    'spacer', spacer, on_date, vendor):
                seen.add(key)
                problems.append(('warning', _(
                    "Panel %(panel)s: the gap's spacer '%(spacer)s' has no "
                    "rate, so the spacer is not in the price. Add it under "
                    "Rates, Glass Extras.", panel=panel, spacer=spacer),
                    self._target('glass', panel)))
            key = ('gas', panel, gas.lower())
            if gas and gas.lower() != 'air' and key not in seen \
                    and not Extra._rate_for('gas', gas, on_date, vendor):
                seen.add(key)
                problems.append(('warning', _(
                    "Panel %(panel)s: the gap's gas '%(gas)s' has no rate, so "
                    "the gas is not in the price. Add it under Rates, Glass "
                    "Extras.", panel=panel, gas=gas),
                    self._target('glass', panel)))
        return problems

    def _cost_glass_line(self, line, on_date):
        """(rate used, rate date, note) for one row of a panel's glass
        stack, and the line's cost.

        A sheet or a glass protector costs its dated vendor rate for the
        type and thickness times the glass area in sqft, unless a rate was
        typed for this panel (flagged manual). A film protector costs its
        extra per sqft. A gap costs the spacer per running ft round the
        glass plus the gas per unit; with no price typed yet for spacer or
        gas it costs nothing and says nothing, because a missing price
        there is expected until the supplier gives one.
        """
        Extra = self.env['aw.glass.extra']
        vendor = self._glass_vendor()
        label = line.glass_label or _('glass')
        qty = line.qty or 0
        kind = line.glass_part_kind
        if kind == 'gap':
            perimeter_ft = 2.0 * ((line.glass_w or 0.0)
                                  + (line.glass_h or 0.0)) / MM_PER_FOOT * qty
            spacer = Extra._rate_for(
                'spacer', line.glass_spacer, on_date, vendor)
            gas = Extra._rate_for('gas', line.glass_gas, on_date, vendor)
            line.rate_list = spacer.rate if spacer else 0.0
            line.line_cost = (
                perimeter_ft * (spacer.rate if spacer else 0.0)
                + (gas.rate if gas else 0.0) * qty)
            return (spacer.rate if spacer else 0.0,
                    spacer.date_from if spacer else False, '')
        area_sqft = (line.area_sqm or 0.0) * SQFT_PER_SQM
        rate_date = False
        if line.glass_extra_id:
            extra = Extra._rate_for(
                'protector_film', line.glass_extra_id.name, on_date, vendor)
            listed = extra.rate if extra else 0.0
            rate_date = extra.date_from if extra else False
        elif line.glass_type_id and line.glass_mm:
            rate = self.env['aw.glass.rate']._rate_for(
                line.glass_type_id, line.glass_mm, on_date, vendor)
            listed = rate.price if rate else 0.0
            rate_date = rate.date_from if rate else False
        else:
            line.rate_list = 0.0
            line.line_cost = 0.0
            return 0.0, False, _("%s: glass type or thickness not set", label)
        used = line.glass_manual_rate if line.rate_is_manual else listed
        line.rate_list = listed
        line.line_cost = used * area_sqft
        if line.rate_is_manual:
            note = _("%(label)s: manual rate %(used)g (list rate %(listed)g)",
                     label=label, used=used, listed=listed)
        elif not listed:
            note = _("%s: no rate", label)
        else:
            note = ''
        return used, rate_date, note

    def _cost_bom_lines(self):
        """Attach cost to every BOM line, after explosion.

        A line with no cost is left at zero and given a `cost_note`
        saying why, which the checks then report. Guessing a price would
        be worse than showing none: an invented number reaches a
        customer, a zero plus a warning does not.
        """
        self.ensure_one()
        on_date = self._costing_date()
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
                rate, level, used_fallback = self._rate_with_fallback(
                    template,
                    (self._line_thickness(source, template)
                     if source else False),
                    (self._line_finish(source) if source
                     else self.finish_id),
                    on_date)
                variant = line.product_id.display_name or template.display_name
                if rate:
                    unit_cost = rate.price
                    rate_date = rate.date_from
                    line.line_cost = (
                        (line.length_mm or 0.0) / MM_PER_FOOT
                        * rate.price * (line.qty or 0))
                    # A fallback is a rate for something else: never silent.
                    if used_fallback:
                        line.rate_is_standin = True
                        note = _(
                            "No %(vendor)s rate for %(variant)s: %(standin)s "
                            "rate used.",
                            vendor=vendor.display_name or _('profile'),
                            variant=variant,
                            standin=self._fallback_vendor().display_name)
                    elif level == 'thickness':
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
                    # No rate from the order's vendor or the series'
                    # default: nothing to cost with, and the line says so.
                    line.line_cost = 0.0
                    note = _(
                        "No %(vendor)s rate for %(variant)s on %(date)s: "
                        "price incomplete.",
                        vendor=vendor.display_name or _('profile'),
                        variant=variant, date=on_date)

            elif line.kind == 'glass':
                unit_cost, rate_date, note = self._cost_glass_line(
                    line, on_date)

            elif line.kind == 'mesh' and (line.glass_w or line.glass_h):
                # The SIZED cloth line (a mesh type's own lines, such as
                # the old generic "Mesh cloth" part, have no size and are
                # costed as parts below). Cloth: ft2 x the cloth product's cost per ft2, unless
                # a rate was typed for this panel. The piece count stays 1;
                # the quantity the cloth is bought by is its area. Roll
                # waste is NOT in this rate.
                listed = line.product_id.standard_price or 0.0
                name = line.product_id.display_name or line.label or _('mesh cloth')
                area_sqft = (line.area_sqm or 0.0) * SQFT_PER_SQM
                line.rate_list = listed
                if line.rate_is_manual:
                    unit_cost = line.manual_rate
                    note = _(
                        "%(name)s: manual rate %(used)g per sqft (product "
                        "cost %(listed)g)",
                        name=name, used=unit_cost, listed=listed)
                else:
                    unit_cost = listed
                    if not unit_cost:
                        note = _("%s has no cost per sqft", name)
                line.line_cost = unit_cost * area_sqft

            elif line.kind == 'hardware':
                # The product's cost unless a rate was typed for this
                # panel; the list rate is kept either way so the Cost
                # breakdown can show both.
                listed = line.product_id.standard_price or 0.0
                name = line.product_id.display_name or _('hardware')
                line.rate_list = listed
                if line.rate_is_manual:
                    unit_cost = line.manual_rate
                    note = _(
                        "%(name)s: manual rate %(used)g (product cost "
                        "%(listed)g)",
                        name=name, used=unit_cost, listed=listed)
                else:
                    unit_cost = listed
                    if not unit_cost:
                        note = _("%s has no cost price", name)
                line.line_cost = unit_cost * (line.qty or 0)

            else:
                unit_cost = line.product_id.standard_price or 0.0
                line.line_cost = unit_cost * (line.qty or 0)
                if not unit_cost:
                    note = _("%s has no cost price",
                             line.product_id.display_name or _('Product'))

            unit_cost, rate_date, note = self._take_frozen_cost(
                line, unit_cost, rate_date, note)
            line.unit_cost = unit_cost
            line.rate_date = rate_date
            line.cost_note = note

    # The structure's own values are NOT a dependency: changing a
    # wastage, labour or profit value re-prices the windows still being
    # quoted (cost_freeze.py asks for exactly those), never a window on a
    # confirmed order.
    @api.depends('bom_line_ids.line_cost', 'bom_line_ids.kind',
                 'bom_line_ids.cost_note', 'price_structure_id',
                 'area_sqm', 'area_sqft', 'manual_rate', 'qty')
    def _compute_pricing(self):
        for design in self:
            build = design._price_build_up()
            design.cost_total = build['cost']
            design.basic_value = build['basic']
            design.price_total = build['price']
            design.price_per_sqft = (
                build['price'] / build['total_sqft']
                if build['total_sqft'] else 0.0)
            design.margin_pct = (
                (build['price'] - build['cost']) / build['price'] * 100.0
                if build['price'] else 0.0)
            design.uncosted_line_count = build['uncosted']

    def _price_build_up(self):
        """The whole price of this position, line by line.

        THE one place the arithmetic lives: the stored cost and price
        (`_compute_pricing`) and the Pricing tab's "Price build-up" both
        read it, so what is shown cannot drift from what is charged.

        In order: each kind of material, its wastage where it has one
        (profile, glass, mesh CLOTH; hardware, infill and grid have none),
        then fabrication and installation labour per m2 of the window,
        which is COST; profit is a markup on cost; a manual rate per sqft
        replaces the calculated price.

        Everything is for the WHOLE position, not one window. The BOM lines
        already carry the design's qty (the explosion multiplies by it), so
        area and the manual rate are multiplied to match -- otherwise a qty
        of 4 would cost four windows and price one.
        """
        self.ensure_one()
        values = self.price_structure_id._values()
        profiles = glass = cloth = parts = hardware = infill_grid = 0.0
        feet = glass_sqft = cloth_sqft = 0.0
        uncosted = 0
        for line in self.bom_line_ids:
            # Only a line that carries NO cost is uncosted. A note on a
            # line that was costed anyway (a fallback rate, the cost field
            # standing in) is information, not a gap.
            if line.cost_note and not line.line_cost:
                uncosted += 1
            if line.kind == 'profile':
                profiles += line.line_cost
                feet += (line.length_mm or 0.0) * (line.qty or 0) / 304.8
            elif line.kind == 'glass':
                glass += line.line_cost
                if line.glass_part_kind in ('sheet', 'protector'):
                    glass_sqft += (line.area_sqm or 0.0) * SQFT_PER_SQM
            elif line.kind == 'mesh':
                if line.glass_w or line.glass_h:
                    cloth += line.line_cost         # the sized cloth
                    cloth_sqft += line.area_sqft or 0.0
                else:
                    parts += line.line_cost         # a mesh type's own part
            elif line.kind == 'hardware':
                hardware += line.line_cost
            else:
                infill_grid += line.line_cost

        units = max(1, self.qty or 1)
        total_sqm = (self.area_sqm or 0.0) * units
        total_sqft = (self.area_sqft or 0.0) * units

        rows = []

        def add(key, label, amount, kind, percent=None, rate=None,
                unit='', detail=''):
            rows.append({
                'key': key, 'label': label, 'amount': amount, 'kind': kind,
                'percent': percent, 'rate': rate, 'unit': unit,
                'detail': detail})

        def wastage(key, label, base, kind):
            percent = values[kind]
            add(key, label, base * percent / 100.0, 'add',
                percent=percent, unit='%')
            return base * percent / 100.0

        add('profiles', _('Profiles'), profiles, 'base',
            detail='%.2f ft' % feet if feet else '')
        material = profiles + wastage(
            'profile_wastage', _('Profile wastage'), profiles,
            'profile_wastage')
        add('glass', _('Glass'), glass, 'base',
            detail='%.2f sqft' % glass_sqft if glass_sqft else '')
        material += glass + wastage(
            'glass_wastage', _('Glass wastage'), glass, 'glass_wastage')
        add('mesh_cloth', _('Mesh cloth'), cloth, 'base',
            detail='%.2f sqft' % cloth_sqft if cloth_sqft else '')
        material += cloth + wastage(
            'mesh_wastage', _('Mesh wastage'), cloth, 'mesh_wastage')
        add('hardware', _('Hardware'), hardware, 'base')
        material += hardware
        if parts:
            add('mesh_parts', _('Mesh parts'), parts, 'base')
            material += parts
        add('infill_grid', _('Infill and grid'), infill_grid, 'base')
        material += infill_grid

        fabrication = values['fabrication_labour'] * total_sqm
        installation = values['install_labour'] * total_sqm
        area_detail = '%.2f m\u00b2' % total_sqm
        add('fabrication_labour', _('Fabrication labour'), fabrication,
            'labour', rate=values['fabrication_labour'], unit=_('per m\u00b2'),
            detail=area_detail)
        add('install_labour', _('Installation labour'), installation,
            'labour', rate=values['install_labour'], unit=_('per m\u00b2'),
            detail=area_detail)

        cost = material + fabrication + installation
        add('cost', _('Cost'), cost, 'subtotal')
        basic = cost * (1 + values['profit'] / 100.0)
        add('profit', _('Profit'), basic - cost, 'add',
            percent=values['profit'], unit='%')
        add('calculated_price', _('Calculated price'), basic, 'subtotal')

        # manual_rate is per sqft and has always overridden the calculated
        # price; it overrides the cascade's result, not the cost the
        # margin is measured against.
        if self.manual_rate:
            price = self.manual_rate * total_sqft
            add('manual_override', _('Manual rate'), price, 'override',
                rate=self.manual_rate, unit=_('per sqft'),
                detail='%.2f sqft' % total_sqft)
        else:
            price = basic
        add('price', _('Price'), price, 'total')

        return {
            'rows': rows, 'cost': cost, 'basic': basic, 'price': price,
            'total_sqft': total_sqft, 'total_sqm': total_sqm,
            'uncosted': uncosted,
        }

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
                'missing_rates': self._missing_rate_info()[0],
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
                    'mesh': values['mesh_wastage'],
                },
                'build_up': self._price_build_up()['rows'],
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
