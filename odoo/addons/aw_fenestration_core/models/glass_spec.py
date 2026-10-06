# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# The Lake City schedule: (xmlid suffix, name, overall mm, kg/m2). The
# weight is 2.5 kg/m2 per mm of GLASS, so the air gap counts for nothing:
# 6+10+6 is 12 mm of glass = 30, not 22 mm worth.
LAKE_CITY_GLASS = [
    ('lc_6_10_6_clear', '6+10+6 Clear Tempered', 22, 30),
    ('lc_6_10_8_clear', '6+10+8 Clear Tempered', 24, 35),
    ('lc_8_8_8_clear', '8+8+8 Clear Tempered', 24, 40),
    ('lc_6_10_6_frosted', '6+10+6 Frosted Tempered', 22, 30),
]
RE_SPEC_GLASS_PARAM = 'aw_fenestration.re_spec_glass_lake_city'


class AwGlassSpec(models.Model):
    """A named glass option, e.g. '8mm Clear Toughened' or '24mm DGU
    6+12+6', pointing at one glass product. Kept single-line by design —
    gaskets are Hardware Set lines, not part of the glass spec. If a real
    DGU build-up ever needs multiple priced components, extend this model
    with a line table then; don't build it speculatively now.
    """
    _name = 'aw.glass.spec'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Glass Specification'
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict', tracking=True,
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_glass').id,
        )])
    glazing = fields.Selection([
        ('single', 'Single glazed'),
        ('double', 'Double glazed'),
    ], default='single', tracking=True,
        help="Which glazing family may use this spec. A sealed unit is "
             "double; a single pane, however thick, is single.")
    thickness_mm = fields.Float(string='Thickness (mm)')
    weight_kg_m2 = fields.Float(
        string='Weight (kg/m²)',
        help="Used by the manufacturability checks in Phase 4, e.g. sash "
             "weight against the hardware's limit.")
    notes = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A glass spec name must be unique.'),
    ]

    @api.model
    def _seed_glazing(self):
        """Mark the sealed units double, once.

        Everything seeded is a single pane except the DGU, so the
        default already covers the rest; this only has to find the
        units. Matches on "DGU" in the name rather than on thickness,
        because a 24 mm single pane would be a strange thing to own but
        is not impossible, and thickness alone cannot tell them apart.
        """
        param = self.env['ir.config_parameter'].sudo()
        key = 'aw_fenestration.glass_glazing_seeded'
        if param.get_param(key):
            return 0
        marked = 0
        for spec in self.with_context(active_test=False).search([]):
            if spec.glazing == 'double':
                continue
            if 'DGU' in (spec.name or '').upper():
                spec.glazing = 'double'
                marked += 1
        param.set_param(key, '1')
        return marked

    @api.model
    def _lake_city_xmlid(self, suffix):
        return 'aw_fenestration_core.glass_spec_%s' % suffix

    @api.model
    def _seed_lake_city_glass(self):
        """Seed the four Lake City glass types, FILL-ONLY BY NAME.

        A glass spec of that name that already exists (made by hand, or
        by an earlier run) is adopted untouched and only given the seed
        xmlid, so later code can find it even after a rename. Nothing
        that exists is overwritten: prices, weights and names stay
        editable. Products sit under Fenestration / Glass / DGU, priced
        at zero and marked "price to be set" -- the same rule as the
        starter list: no invented prices in a quote.
        """
        category = self.env.ref(
            'aw_fenestration_core.product_category_glass_dgu',
            raise_if_not_found=False)
        uom = self.env.ref('uom.product_uom_square_meter',
                           raise_if_not_found=False)
        if not (category and uom):
            return 0
        Data = self.env['ir.model.data'].sudo()
        created = 0
        for suffix, name, thickness, weight in LAKE_CITY_GLASS:
            spec = self.with_context(active_test=False).search(
                [('name', '=', name)], limit=1)
            if not spec:
                product = self.env['product.product'].create({
                    'name': 'Glass %s' % name,
                    'type': 'consu',
                    'is_storable': True,
                    'categ_id': category.id,
                    'uom_id': uom.id,
                    'list_price': 0.0,
                    'standard_price': 0.0,
                    'description_sale':
                        'Price to be set from the supplier list.',
                })
                spec = self.create({
                    'name': name,
                    'product_id': product.id,
                    'glazing': 'double',
                    'thickness_mm': thickness,
                    'weight_kg_m2': weight,
                })
                created += 1
            xmlid = 'glass_spec_%s' % suffix
            if not Data.search_count([('module', '=', 'aw_fenestration_core'),
                                      ('name', '=', xmlid)]):
                Data.create({
                    'module': 'aw_fenestration_core', 'name': xmlid,
                    'model': self._name, 'res_id': spec.id,
                    'noupdate': True,
                })
        return created

    @api.model
    def _seed_re_spec_default_glass(self):
        """Point the RE spec's default glass at 6+10+6 Clear Tempered,
        ONCE.

        Only the SPEC's default changes. A design copies its glass when
        it is made (glass_spec_id is stored and recomputed only when
        the system changes), so existing windows keep what they have.
        Guarded by a parameter so a later choice in the UI is not
        reverted; set only once the spec and the glass both exist, so a
        database that gets the spec later still gets this.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(RE_SPEC_GLASS_PARAM):
            return False
        from .section_seed import SPEC_NAME
        glass = self.env.ref(self._lake_city_xmlid('lc_6_10_6_clear'),
                             raise_if_not_found=False)
        specs = self.env['aw.window.template'].with_context(
            active_test=False).search([('name', '=', SPEC_NAME)])
        if not (glass and specs):
            return False
        specs.write({'glass_spec_id': glass.id})
        param.set_param(RE_SPEC_GLASS_PARAM, '1')
        return True
