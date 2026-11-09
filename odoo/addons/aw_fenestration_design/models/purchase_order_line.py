# -*- coding: utf-8 -*-
"""A profile bought as bars: a bar length and a number of bars.

The quantity of the line stays what Odoo reads everywhere (receipts, billing),
in ft, and is bars x length. The price is pinned: the standard price rule
re-prices a line whenever its quantity changes, and a price taken from the
vendor's profile rate on the day the order was made must not move because
somebody changed the number of bars.

A profile line typed by hand: the user picks the profile, the bar length is
filled in when the vendor sells that profile in exactly one length, and the
user types the number of bars. Until bars and length are both set the line
says so. Setting them puts the line in ft and, when it has no price, takes
the vendor's rate per ft.
"""
from odoo import _, api, fields, models
from odoo.tools import format_date
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    aw_bar_length_ft = fields.Float(string='Bar length (ft)', copy=False)
    aw_bar_count = fields.Integer(string='Bars', copy=False)
    aw_is_bars = fields.Boolean(compute='_compute_aw_bars')
    aw_is_profile = fields.Boolean(
        related='product_id.product_tmpl_id.aw_is_profile')
    aw_price_note = fields.Char(string='Price note', compute='_compute_aw_bars')

    @api.depends('aw_bar_count', 'aw_bar_length_ft', 'price_unit',
                 'product_id', 'order_id.partner_id', 'order_id.date_order')
    def _compute_aw_bars(self):
        for line in self:
            line.aw_is_bars = bool(
                line.aw_bar_count and line.aw_bar_length_ft)
            if line.aw_is_bars:
                line.aw_price_note = line._aw_price_note()
            elif line.product_id.product_tmpl_id.aw_is_profile:
                line.aw_price_note = _("Enter bars and bar length")
            else:
                line.aw_price_note = False

    @api.model
    def _aw_bar_qty(self, count, length):
        return float(count or 0) * float(length or 0.0)

    def _aw_foot(self):
        foot = self.env.ref('uom.product_uom_foot')
        if not foot.active:
            foot.sudo().active = True
        return foot

    @api.model
    def _aw_rate_for(self, template, thickness, finish, vendor, on_date):
        """The vendor's profile rate per ft on a date, or 0."""
        if not (template and vendor):
            return 0.0
        rate = self.env['aw.profile.rate']._rate_for(
            template, thickness, finish, on_date, vendor)
        return rate.price if rate else 0.0

    @api.model
    def _aw_start_price(self, template, thickness, finish, vendor, on_date,
                        currency=None):
        """(price per ft in the order's currency, 'lpp' | 'list' | None): a
        new line starts at the vendor's last purchase price when there is
        one, else at the list rate."""
        lpp = self.env['aw.profile.lpp']._last(
            vendor, template, thickness, finish)
        if lpp:
            price = lpp.price_ft
            if currency and currency != lpp.currency_id:
                price = lpp.currency_id._convert(
                    price, currency, self.env.company, on_date, round=False)
            return price, 'lpp'
        price = self._aw_rate_for(template, thickness, finish, vendor, on_date)
        return price, ('list' if price else None)

    def _aw_start_price_for_line(self):
        self.ensure_one()
        product = self.product_id
        thickness, finish = self.order_id._aw_variant_values(product)
        on_date = (self.order_id.date_order or fields.Datetime.now()).date()
        return self._aw_start_price(
            product.product_tmpl_id, thickness, finish,
            self.order_id.partner_id, on_date, self.order_id.currency_id)

    def _aw_last_price(self):
        """(price per ft in the order's currency, date, PO number) of the
        vendor's last purchase price for this line's variant, or None."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return None
        thickness, finish = self.order_id._aw_variant_values(product)
        lpp = self.env['aw.profile.lpp']._last(
            self.order_id.partner_id, product.product_tmpl_id, thickness,
            finish)
        # a line on the very order that made the row is not "last" news
        lpp = lpp.filtered(lambda r: r.po_line_id != self)
        if not lpp:
            return None
        price = lpp.price_ft
        currency = self.order_id.currency_id
        if currency and currency != lpp.currency_id:
            on_date = (self.order_id.date_order
                       or fields.Datetime.now()).date()
            price = lpp.currency_id._convert(
                price, currency, self.env.company, on_date, round=False)
        variant = ', '.join(p for p in (
            self.order_id._aw_finish_label(finish, self.order_id.partner_id)
            if finish else '', thickness.name or '') if p)
        return price, lpp.date, lpp.order_id.name or '', variant

    def _aw_vendor_rate(self):
        """The vendor's profile rate per ft on the order date, or 0."""
        self.ensure_one()
        product = self.product_id
        thickness, finish = self.order_id._aw_variant_values(product)
        on_date = (self.order_id.date_order or fields.Datetime.now()).date()
        return self._aw_rate_for(
            product.product_tmpl_id, thickness, finish,
            self.order_id.partner_id, on_date)

    def _aw_price_note(self):
        """'No price', or 'list R - +x.x%' when the price is not the list."""
        self.ensure_one()
        if not self.price_unit:
            return _("No price")
        notes = []
        rate = self._aw_vendor_rate()
        if rate and abs(self.price_unit - rate) > 0.005:
            notes.append(_("list %(rate).2f - %(pct)+.1f%%", rate=rate, pct=(
                self.price_unit - rate) / rate * 100.0))
        last = self._aw_last_price()
        if last and abs(self.price_unit - last[0]) > 0.005:
            notes.append(_(
                "last paid %(price).2f (%(variant)s) on %(date)s, %(order)s"
                " - %(pct)+.1f%%",
                price=last[0], variant=last[3],
                date=format_date(self.env, last[1], date_format='d MMM'),
                order=last[2], pct=(
                    self.price_unit - last[0]) / last[0] * 100.0))
        return ' | '.join(notes) or False

    @api.model
    def _aw_bars_text(self, count, length):
        return _("%(bars)d bars x %(ft)g ft = %(total)g ft", bars=count,
                 ft=length, total=self._aw_bar_qty(count, length))

    def _aw_line_text(self):
        """The line's description: the profile code, its finish and thickness,
        and a line 'N bars x L ft = F ft'. Built from the numbers, so it is
        never older than they are."""
        self.ensure_one()
        product = self.product_id
        thickness, finish = self.order_id._aw_variant_values(product)
        parts = [self.order_id._aw_finish_label(finish, self.order_id.partner_id)
                 if finish else '', thickness.name or '']
        head = product.product_tmpl_id.name
        detail = ', '.join(p for p in parts if p)
        if detail:
            head = "%s (%s)" % (head, detail)
        return "%s\n%s" % (head, self._aw_bars_text(
            self.aw_bar_count, self.aw_bar_length_ft))

    def _aw_sync_name(self):
        for line in self.filtered(lambda l: l.aw_bar_count
                                  and l.aw_bar_length_ft and l.product_id):
            text = line._aw_line_text()
            if line.name != text:
                super(PurchaseOrderLine, line).write({'name': text})

    @api.model
    def _aw_refresh_bars_names(self):
        """Upgrade step: lines made before the text was built from the
        numbers (and the ones edited since) get the right text. Idempotent."""
        lines = self.search([('aw_bar_count', '>', 0),
                             ('aw_bar_length_ft', '>', 0)])
        lines._aw_sync_name()
        return len(lines)

    def _aw_bar_values(self, count, length, price=None):
        """What a line holds once it is bars x length: the quantity, the unit
        in ft, and the price. An existing price is carried over to the new
        unit; a line with no price takes the vendor's rate per ft."""
        self.ensure_one()
        foot = self._aw_foot()
        values = {'product_qty': self._aw_bar_qty(count, length)}
        price = self.price_unit if price is None else price
        if self.product_uom_id and self.product_uom_id != foot and price:
            price = self.product_uom_id._compute_price(price, foot)
        if self.product_uom_id != foot:
            values['product_uom_id'] = foot.id
        if not price:
            price = self._aw_start_price_for_line()[0]
        if price != self.price_unit:
            values.update(price_unit=price, technical_price_unit=price)
        return values

    @api.onchange('aw_bar_count', 'aw_bar_length_ft')
    def _onchange_aw_bars(self):
        for line in self:
            if line.aw_bar_count and line.aw_bar_length_ft:
                for name, value in line._aw_bar_values(
                        line.aw_bar_count, line.aw_bar_length_ft).items():
                    line[name] = value
                line.name = line._aw_line_text()

    @api.onchange('product_id')
    def _onchange_aw_profile_length(self):
        """A profile the vendor sells in one length needs no length typed."""
        for line in self:
            template = line.product_id.product_tmpl_id
            if not template.aw_is_profile or line.aw_bar_length_ft:
                continue
            lengths = self.env['aw.vendor.bar.length']._lengths_for(
                line.order_id.partner_id, template=template)
            if len(lengths) == 1:
                line.aw_bar_length_ft = lengths[0]

    @api.constrains('aw_bar_count', 'aw_bar_length_ft', 'product_qty')
    def _check_aw_bars(self):
        for line in self:
            if line.aw_bar_count < 0 or line.aw_bar_length_ft < 0:
                raise ValidationError(_(
                    "Bars and bar length cannot be negative."))
            if not (line.aw_bar_count and line.aw_bar_length_ft):
                continue
            want = line._aw_bar_qty(line.aw_bar_count, line.aw_bar_length_ft)
            if line.product_uom_id == self.env.ref('uom.product_uom_foot') \
                    and abs(line.product_qty - want) > 1e-6:
                raise ValidationError(_(
                    "%(product)s: %(bars)s bars of %(ft)g ft is %(want)g ft, "
                    "not %(qty)g ft.", product=line.product_id.display_name,
                    bars=line.aw_bar_count, ft=line.aw_bar_length_ft,
                    want=want, qty=line.product_qty))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('aw_bar_count') and vals.get('aw_bar_length_ft'):
                vals['product_qty'] = self._aw_bar_qty(
                    vals['aw_bar_count'], vals['aw_bar_length_ft'])
        lines = super().create(vals_list)
        # a line typed by hand arrives in the product's unit, maybe unpriced
        for line in lines.filtered('aw_is_bars'):
            extra = line._aw_bar_values(
                line.aw_bar_count, line.aw_bar_length_ft)
            extra.pop('product_qty')
            if extra:
                line.write(extra)
        lines._aw_sync_name()
        return lines

    def write(self, vals):
        result = self._aw_write(vals)
        if {'aw_bar_count', 'aw_bar_length_ft', 'product_id'} & set(vals):
            self._aw_sync_name()
        return result

    def _aw_write(self, vals):
        if 'aw_bar_count' in vals or 'aw_bar_length_ft' in vals:
            for line in self:
                one = dict(vals)
                count = one.get('aw_bar_count', line.aw_bar_count)
                length = one.get('aw_bar_length_ft', line.aw_bar_length_ft)
                if count and length:
                    extra = line._aw_bar_values(
                        count, length, price=one.get('price_unit'))
                    for key, value in extra.items():
                        one.setdefault(key, value)
                    one['product_qty'] = extra['product_qty']
                super(PurchaseOrderLine, line).write(one)
            return True
        return super(PurchaseOrderLine, self).write(vals)

    def _compute_price_unit_and_date_planned_and_name(self):
        """A bars line keeps the price it was made with."""
        bars = self.filtered('aw_is_bars')
        return super(PurchaseOrderLine, self - bars)\
            ._compute_price_unit_and_date_planned_and_name()

    @api.depends('product_id', 'product_id.uom_id', 'product_id.uom_ids',
                 'product_id.seller_ids', 'product_id.seller_ids.product_uom_id',
                 'aw_bar_count')
    def _compute_allowed_uom_ids(self):
        super()._compute_allowed_uom_ids()
        foot = self.env.ref('uom.product_uom_foot', raise_if_not_found=False)
        if foot:
            for line in self.filtered('aw_bar_count'):
                line.allowed_uom_ids |= foot
