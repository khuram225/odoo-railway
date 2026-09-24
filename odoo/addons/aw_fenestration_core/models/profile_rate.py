# -*- coding: utf-8 -*-
"""Profile rates (spec 8, Phase 6a).

Append-only by design: a new price list adds rows with a later
`date_from`, and nothing is ever updated in place. That is what lets a
quote from March still cost at March's rates when someone reopens it in
June -- the lookup asks for the newest rate that was in force on the
quote's own order date, not for "the current price".
"""
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Set while _recompute_date_to writes its results, so the write override
# does not turn one recompute into an endless chain of them.
SYNC_CONTEXT = 'aw_rate_date_to_sync'


def resolve_chain(entries):
    """Work out each version's end date from a chain of versions.

    `entries` is [(date_from, date_end_or_None), ...] sorted by
    date_from; returns [(date_to_or_False, closed_by_successor), ...] in
    the same order.

    Deliberately free of Odoo imports, like formula.py and
    layout_rules.py, so scripts/check_rate_chain.py can exercise the
    REAL implementation rather than a reimplementation that would share
    none of its bugs.

    Two rules worth stating:
    - A version ends the day before the next one STARTS, so there is
      never a gap and never an overlap.
    - Its own end date wins only when it falls earlier. That is what
      separates "superseded" (a newer price replaced it) from "expired"
      (someone retired it and nothing took over) -- and only the second
      should make a design report a missing rate.
    """
    result = []
    for index, (date_from, date_end) in enumerate(entries):
        # Strictly later, so two rows sharing a date_from cannot close
        # each other and land a date_to before their own date_from.
        successor_from = next(
            (other_from for other_from, _other_end in entries[index + 1:]
             if other_from > date_from), None)
        chain_end = (successor_from - timedelta(days=1)
                     if successor_from else None)

        if chain_end and (not date_end or chain_end <= date_end):
            result.append((chain_end, True))
        elif date_end:
            result.append((date_end, False))
        else:
            result.append((False, False))
    return result


class AwProfileRate(models.Model):
    _name = 'aw.profile.rate'
    _description = 'Fenestration Profile Rate'
    _order = 'date_from desc, product_tmpl_id, id desc'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Profile', required=True,
        ondelete='cascade', index=True)
    # Nullable on purpose: some profiles have no thickness dimension at
    # all (the melt writes those with an empty thickness), and a rate
    # with no finish is the fallback for every finish.
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness', ondelete='restrict',
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_thickness').id,
        )])
    finish_id = fields.Many2one(
        'product.attribute.value', string='Finish', ondelete='restrict',
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_finish').id,
        )])

    price = fields.Float(
        string='Price / running ft', required=True,
        digits='Product Price',
        help="PKR per running foot, the vendor's own unit -- not a "
             "conversion. Stock lengths are 14/16/18 ft. Confirmed by "
             "the client; still to be had in writing from Chawla.")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    date_from = fields.Date(
        string='Effective From', required=True, index=True,
        default=fields.Date.context_today)
    date_end = fields.Date(
        string='End Date',
        help="Set this to retire a rate on a known date. Leave empty and "
             "the rate simply runs until the next version replaces it.")
    # A PLAIN stored field, written by _recompute_date_to -- not a
    # computed one. It depends on a SIBLING record (the next version of
    # the same rate), and @api.depends cannot express "recompute my
    # neighbour when I change": Odoo would recompute the record that
    # changed, never the one before it in the chain. So the recompute is
    # explicit, from create/write/unlink and the importer.
    date_to = fields.Date(
        string='Effective To', readonly=True, index=True,
        help="The earlier of the End Date and the day before the next "
             "version starts. Empty means open-ended.")
    has_successor = fields.Boolean(
        readonly=True,
        help="True when this rate was closed by a later version rather "
             "than by its own End Date. That is the whole difference "
             "between Superseded and Expired.")
    status = fields.Selection([
        ('future', 'Future'),
        ('current', 'Current'),
        ('superseded', 'Superseded'),
        ('expired', 'Expired'),
    ], compute='_compute_status')

    vendor_id = fields.Many2one('res.partner', string='Vendor', index=True)
    source_note = fields.Char(
        help="Which file this row came from, so a price can always be "
             "traced back to the list it was quoted on.")
    active = fields.Boolean(default=True)

    @api.constrains('price')
    def _check_price(self):
        for rate in self:
            if rate.price < 0:
                raise ValidationError(_("A profile rate cannot be negative."))

    @api.constrains('date_from', 'date_end')
    def _check_dates(self):
        for rate in self:
            if rate.date_end and rate.date_from \
                    and rate.date_end < rate.date_from:
                raise ValidationError(_(
                    "'%s' ends before it starts.", rate.display_name))

    # ------------------------------------------------------------------
    # validity chain
    # ------------------------------------------------------------------
    def _chain_key(self):
        """What makes two rates versions of the SAME price.

        Vendor is part of it: two suppliers quoting the same profile are
        two independent chains, and letting one close the other would
        silently retire a price nobody replaced.
        """
        self.ensure_one()
        return (self.product_tmpl_id.id, self.thickness_id.id,
                self.finish_id.id, self.vendor_id.id)

    @api.model
    def _recompute_date_to(self, keys):
        """Rebuild date_to for every rate in the given chains.

        Rebuilds each chain WHOLE rather than looking forward from the
        changed row. A back-dated import -- a list dated before one
        already loaded -- has to shorten the rate that previously ran
        through that period, which is a record EARLIER in the chain than
        anything being written. Only a full pass gets that right.
        """
        keys = {tuple(key) for key in keys}
        if not keys:
            return
        template_ids = {key[0] for key in keys if key[0]}
        if not template_ids:
            return
        rates = self.with_context(active_test=False).search(
            [('product_tmpl_id', 'in', list(template_ids))],
            order='date_from asc, id asc')

        chains = defaultdict(list)
        for rate in rates:
            key = rate._chain_key()
            if key in keys:
                chains[key].append(rate)

        for chain in chains.values():
            resolved = resolve_chain(
                [(rate.date_from, rate.date_end) for rate in chain])
            for rate, (date_to, by_successor) in zip(chain, resolved):
                if (rate.date_to != date_to
                        or rate.has_successor != by_successor):
                    rate.with_context(**{SYNC_CONTEXT: True}).write({
                        'date_to': date_to,
                        'has_successor': by_successor,
                    })

    def _keys_of(self):
        return {rate._chain_key() for rate in self}

    @api.model_create_multi
    def create(self, vals_list):
        rates = super().create(vals_list)
        rates._recompute_date_to(rates._keys_of())
        return rates

    def write(self, vals):
        if self.env.context.get(SYNC_CONTEXT):
            return super().write(vals)
        # Both sides: changing thickness, finish, vendor or date_from
        # moves a rate BETWEEN chains, and the one it left has to be
        # rebuilt too or it keeps a date_to set by a rate no longer in it.
        keys = self._keys_of()
        result = super().write(vals)
        keys |= self._keys_of()
        self._recompute_date_to(keys)
        return result

    def unlink(self):
        keys = self._keys_of()
        result = super().unlink()
        self._recompute_date_to(keys)
        return result

    def _compute_status(self):
        today = fields.Date.context_today(self)
        for rate in self:
            if rate.date_from and rate.date_from > today:
                rate.status = 'future'
            elif rate.date_to and rate.date_to < today:
                rate.status = ('superseded' if rate.has_successor
                               else 'expired')
            else:
                rate.status = 'current'

    @api.model
    def _rate_for(self, product_tmpl, thickness, finish, on_date):
        """The rate in force on `on_date`, most specific match first.

        Falls back from (thickness + finish) to thickness-only to
        template-only, because a vendor list often prices a profile the
        same in every finish and the melt records that as one row with
        no finish. Returns an empty recordset when nothing matches, and
        the caller reports that -- never a silent zero, which would put
        a free window on a quote.
        """
        if not product_tmpl or not on_date:
            return self.browse()
        # date_from <= on_date <= date_to, open-ended when date_to is
        # empty. A rate whose date_to has passed with no successor is
        # deliberately NOT matched: an expired price is not a price, and
        # the caller's "no rate" warning is the right outcome.
        base = [
            ('product_tmpl_id', '=', product_tmpl.id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ]
        attempts = [
            base + [('thickness_id', '=', thickness.id if thickness else False),
                    ('finish_id', '=', finish.id if finish else False)],
            base + [('thickness_id', '=', thickness.id if thickness else False),
                    ('finish_id', '=', False)],
            base + [('finish_id', '=', False), ('thickness_id', '=', False)],
        ]
        for domain in attempts:
            rate = self.search(
                domain, order='date_from desc, id desc', limit=1)
            if rate:
                return rate
        return self.browse()
