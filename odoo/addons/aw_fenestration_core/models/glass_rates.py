# -*- coding: utf-8 -*-
"""Glass types and the dated rate a glass supplier charges for them.

A sheet of glass is priced by TYPE (Clear, Green, Ref. Grey, WC Green...)
and THICKNESS in mm, per square foot, by a vendor from a start date, in
exactly the way a profile is priced: a new list adds rows with a later
date, nothing is edited in place, and each version ends the day before the
next starts. A glass spec has no price of its own.
"""
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .glass_paste import norm_type
from .profile_rate import SYNC_CONTEXT, resolve_chain

_logger = logging.getLogger(__name__)

GLASS_VENDOR = 'Ghani Glass Ltd'
# The types the first list uses. Seeded by name and never overwritten.
SEED_GLASS_TYPES = [
    ('Clear', False), ('Green', False), ('Brown', False), ('Blue', False),
    ('Ford Blue', False), ('Grey', False),
    ('WC Green', False), ('WC Brown', False), ('WC Blue', False),
    ('CC Green', False), ('CC Brown', False), ('CC Blue', False),
    ('CC Grey', False),
    ('Ref. Clear', True), ('Ref. Green', True), ('Ref. Brown', True),
    ('Ref. Blue', True), ('Ref. Ford Blue', True), ('Ref. Grey', True),
]


class AwGlassType(models.Model):
    _name = 'aw.glass.type'
    _description = 'Glass Type'
    _order = 'name'

    name = fields.Char(required=True)
    name_norm = fields.Char(compute='_compute_name_norm', store=True,
                            index=True)
    reflective = fields.Boolean(
        help="A reflective coating (written 'Ref.' on the price list).")
    active = fields.Boolean(default=True)

    @api.depends('name')
    def _compute_name_norm(self):
        for glass in self:
            glass.name_norm = norm_type(glass.name)

    @api.constrains('name')
    def _check_unique(self):
        for glass in self:
            clash = self.with_context(active_test=False).search([
                ('name_norm', '=', norm_type(glass.name)),
                ('id', '!=', glass.id)], limit=1)
            if clash:
                raise ValidationError(_(
                    "'%(name)s' is already a glass type.", name=clash.name))

    @api.model
    def _seed_glass_types(self):
        """The types and the supplier of the first glass list, fill-only
        by name: an existing type is never touched."""
        partner = self.env['res.partner'].with_context(active_test=False)
        if not partner.search([('name', '=ilike', GLASS_VENDOR)], limit=1):
            partner.create({'name': GLASS_VENDOR, 'is_company': True})
        made = 0
        for name, reflective in SEED_GLASS_TYPES:
            if not self.with_context(active_test=False).search(
                    [('name_norm', '=', norm_type(name))], limit=1):
                self.create({'name': name, 'reflective': reflective})
                made += 1
        return made


class AwGlassRate(models.Model):
    _name = 'aw.glass.rate'
    _description = 'Glass Rate'
    _order = 'glass_type_id, thickness_mm, date_from desc, id desc'

    glass_type_id = fields.Many2one(
        'aw.glass.type', string='Glass type', required=True,
        ondelete='restrict', index=True)
    thickness_mm = fields.Float(string='Thickness (mm)', required=True)
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True)
    price = fields.Float(
        string='PKR / sqft', digits='Product Price', required=True)
    date_from = fields.Date(
        string='Effective From', required=True, index=True,
        default=fields.Date.context_today)
    date_end = fields.Date(
        string='End Date',
        help="Set this to retire a rate on a known date. Empty means it "
             "runs until the next version replaces it.")
    date_to = fields.Date(string='Effective To', readonly=True, index=True)
    has_successor = fields.Boolean(readonly=True)
    status = fields.Selection([
        ('future', 'Future'), ('current', 'Current'),
        ('superseded', 'Superseded'), ('expired', 'Expired'),
    ], compute='_compute_status')
    source_note = fields.Char()
    rate_list_id = fields.Many2one(
        'aw.vendor.rate.list', string='Rate list', readonly=True,
        copy=False, index=True, ondelete='set null')
    active = fields.Boolean(default=True)

    @api.constrains('price')
    def _check_price(self):
        for rate in self:
            if rate.price < 0:
                raise ValidationError(_("A glass rate cannot be negative."))

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

    # -- validity chain: the same rule as profile rates ------------------
    def _chain_key(self):
        self.ensure_one()
        return (self.glass_type_id.id, round(self.thickness_mm, 3),
                self.vendor_id.id)

    @api.model
    def _recompute_date_to(self, keys):
        keys = {tuple(key) for key in keys}
        type_ids = {key[0] for key in keys if key[0]}
        if not type_ids:
            return 0
        rates = self.with_context(active_test=False).search(
            [('glass_type_id', 'in', list(type_ids))],
            order='date_from asc, id asc')
        chains = defaultdict(list)
        for rate in rates:
            key = rate._chain_key()
            if key in keys:
                chains[key].append(rate)
        pending = defaultdict(list)
        for chain in chains.values():
            resolved = resolve_chain(
                [(rate.date_from, rate.date_end) for rate in chain])
            for rate, (date_to, by_successor) in zip(chain, resolved):
                if (rate.date_to != date_to
                        or rate.has_successor != by_successor):
                    pending[(date_to, by_successor)].append(rate.id)
        for (date_to, by_successor), ids in pending.items():
            self.browse(ids).with_context(**{SYNC_CONTEXT: True}).write({
                'date_to': date_to, 'has_successor': by_successor})
        return sum(len(ids) for ids in pending.values())

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

    @api.model
    def _rate_for(self, glass_type, thickness_mm, on_date, vendor):
        """The rate in force on `on_date` from `vendor` for this type and
        thickness, else nothing: another vendor's rows, an expired price
        and a missing thickness are all 'no rate'."""
        if not (glass_type and thickness_mm and on_date and vendor):
            return self.browse()
        return self.search([
            ('glass_type_id', '=', glass_type.id),
            ('thickness_mm', '=', thickness_mm),
            ('vendor_id', '=', vendor.id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc, id desc', limit=1)
