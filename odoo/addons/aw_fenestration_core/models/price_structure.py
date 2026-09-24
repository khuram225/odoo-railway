# -*- coding: utf-8 -*-
"""The cost cascade (spec 8, Phase 6b).

Held as LINES rather than five fixed columns, following principle 0.1:
the next thing the shop wants added to a price -- delivery, a finishing
surcharge, a site allowance -- should be a new row, not a migration.
Each line's `kind` says how the engine uses it; the values themselves
are placeholders until the shop confirms them.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# kind -> (label, unit, default). Percentages apply to the matching
# material cost; the labour kinds are per square metre of the design.
STRUCTURE_DEFAULTS = (
    ('profile_wastage', 'Profile Wastage', 'percent', 8.0),
    ('glass_wastage', 'Glass Wastage', 'percent', 5.0),
    ('fabrication_labour', 'Fabrication Labour', 'per_sqm', 450.0),
    ('install_labour', 'Installation Labour', 'per_sqm', 250.0),
    ('profit', 'Profit', 'percent', 25.0),
)


class AwPriceStructure(models.Model):
    _name = 'aw.price.structure'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Price Structure'
    _order = 'is_default desc, name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string='Default', tracking=True,
        help="Used by any design that has not been given one of its own.")
    notes = fields.Text()
    line_ids = fields.One2many(
        'aw.price.structure.line', 'structure_id', string='Components')

    @api.constrains('is_default', 'active')
    def _check_single_default(self):
        """Exactly one default, or the price a design gets would depend
        on search order -- which is the kind of thing that produces two
        different quotes for the same window."""
        for structure in self:
            if not (structure.is_default and structure.active):
                continue
            other = self.search([
                ('is_default', '=', True), ('id', '!=', structure.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "'%s' is already the default Price Structure. Uncheck "
                    "it first.", other.display_name))

    @api.model
    def _default_structure(self):
        return self.search([('is_default', '=', True)], limit=1) \
            or self.search([], limit=1)

    def _values(self):
        """{kind: value} for the engine, with every kind present so a
        caller never has to guard a missing one."""
        # An empty recordset is a legitimate caller: a design with no
        # structure yet costs at zero markup rather than failing, and
        # the checks report the missing structure.
        values = {kind: 0.0 for kind, _label, _unit, _default in
                  STRUCTURE_DEFAULTS}
        for line in self.line_ids:
            values[line.kind] = line.value
        return values

    @api.model
    def _seed_default_structure(self):
        """One starter structure, once. Fill-only-if-empty like every
        other seed here: if any structure exists, the shop has taken
        this over and nothing is touched."""
        if self.search([], limit=1):
            return
        self.create({
            'name': 'Standard',
            'is_default': True,
            'notes': 'Placeholder values. Confirm each one with the shop '
                     'before quoting from them.',
            'line_ids': [(0, 0, {
                'sequence': (index + 1) * 10,
                'name': label,
                'kind': kind,
                'value': default,
                'show_on_quote': False,
            }) for index, (kind, label, _unit, default)
                in enumerate(STRUCTURE_DEFAULTS)],
        })


class AwPriceStructureLine(models.Model):
    _name = 'aw.price.structure.line'
    _description = 'Fenestration Price Structure Line'
    _order = 'sequence, id'

    structure_id = fields.Many2one(
        'aw.price.structure', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    kind = fields.Selection([
        (kind, label) for kind, label, _unit, _default in STRUCTURE_DEFAULTS
    ], required=True)
    value = fields.Float(required=True, digits='Product Price')
    unit = fields.Char(compute='_compute_unit', string='Unit')
    show_on_quote = fields.Boolean(
        help="Print this component as its own line on the customer's "
             "quote instead of folding it into the price.")

    @api.depends('kind')
    def _compute_unit(self):
        units = {kind: unit for kind, _label, unit, _default
                 in STRUCTURE_DEFAULTS}
        for line in self:
            line.unit = '%' if units.get(line.kind) == 'percent' else 'per m²'
