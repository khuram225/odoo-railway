# -*- coding: utf-8 -*-
"""The words and the small prices around a sheet of glass.

OPTIONS are the plain editable lists a glass build-up picks from: spacer
type, spacer colour, gas, and the standard gap widths. The starting values
are only defaults, to be replaced by the supplier's own words.

EXTRAS are what is not a sheet: a spacer (per running ft), gas (per unit),
a protector film (per sqft), and later services and Georgian bars. Typed
once per item, with an effective date and an optional vendor, because the
supplier has not given prices yet and the numbers are few. If this grows it
moves to rate lists, like sheets and profiles.
"""
from odoo import api, fields, models

DEFAULT_OPTIONS = [
    ('spacer_type', ['Aluminium', 'Warm edge']),
    ('gap_mm', ['6', '9', '12', '16', '20']),
    ('spacer_colour', ['Silver', 'Black', 'White']),
    ('gas', ['Air', 'Argon']),
]


class AwGlassOption(models.Model):
    _name = 'aw.glass.option'
    _description = 'Glass Option'
    _order = 'kind, sequence, id'

    kind = fields.Selection([
        ('spacer_type', 'Spacer type'),
        ('gap_mm', 'Gap width (mm)'),
        ('spacer_colour', 'Spacer colour'),
        ('gas', 'Gas'),
    ], required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.model
    def _seed_glass_options(self):
        """The starting lists, fill-only: a list that already has any
        value (the user's own words) is left exactly as it is."""
        made = 0
        for kind, names in DEFAULT_OPTIONS:
            if self.with_context(active_test=False).search_count(
                    [('kind', '=', kind)]):
                continue
            for index, name in enumerate(names, start=1):
                self.create({'kind': kind, 'name': name,
                             'sequence': index * 10})
                made += 1
        return made


class AwGlassExtra(models.Model):
    _name = 'aw.glass.extra'
    _description = 'Glass Extra'
    _order = 'kind, name, date_from desc, id desc'

    name = fields.Char(
        required=True,
        help="The item: a spacer type (Aluminium), a gas (Argon), a "
             "protector film, a service. Spelled as in the lists.")
    kind = fields.Selection([
        ('spacer', 'Spacer'),
        ('gas', 'Gas'),
        ('protector_film', 'Protector film'),
        ('service', 'Service'),
        ('bar', 'Georgian bar'),
    ], required=True, index=True)
    unit = fields.Selection([
        ('per_sqft', 'per sqft'),
        ('per_ft', 'per running ft'),
        ('per_unit', 'per unit'),
    ], required=True, default='per_sqft')
    rate = fields.Float(digits='Product Price')
    date_from = fields.Date(
        string='Effective from', required=True,
        default=fields.Date.context_today)
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor',
        help="Empty means every vendor.")
    active = fields.Boolean(default=True)

    @api.model
    def _rate_for(self, kind, name, on_date, vendor=None):
        """The extra in force on `on_date` for this item: the vendor's own
        row when it has one, else the row for every vendor, newest start
        first. Nothing when there is none."""
        if not (kind and name and on_date):
            return self.browse()
        key = (name or '').strip().lower()
        rows = self.search([
            ('kind', '=', kind), ('date_from', '<=', on_date),
            ('vendor_id', 'in', [vendor.id if vendor else False, False]),
        ], order='date_from desc, id desc').filtered(
            lambda r: (r.name or '').strip().lower() == key)
        own = rows.filtered(lambda r: vendor and r.vendor_id == vendor)
        return (own or rows)[:1]
