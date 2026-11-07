# -*- coding: utf-8 -*-
"""A mesh type's cloth: a product bought by the sqft.

The cost per ft2 is the product's cost, typed on the product page; the
product is never sold. One product per ACTIVE mesh type of a mechanism that
has a name below, made once from the registry hook (a product made during an
upgrade misses columns that purchase and sale add), by name: a product with
that name is adopted, a mesh type that already has one is never touched.
A type activated later is picked up at the next start.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CLOTH_LABELS = {
    'fixed': 'Fixed',
    'hinged': 'Hinged',
    'zigzag': 'Zig-zag',
    'roller': 'Roller',
}


class AwMeshType(models.Model):
    _inherit = 'aw.mesh.type'

    cloth_product_id = fields.Many2one(
        'product.product', string='Cloth product', ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_mesh_cloth').id,
        )],
        help="The cloth this mesh is cut from, priced per ft2 by the "
             "product's cost.")

    def _register_hook(self):
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._seed_cloth_products()
                self._move_cloth_lines()
        except Exception:
            _logger.exception("aw_fenestration_design: mesh cloth seed failed")

    @api.model
    def _seed_cloth_products(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_mesh_cloth',
            raise_if_not_found=False)
        if not category:
            return 0
        Product = self.env['product.product']
        uom = self.env.ref('uom.product_uom_square_foot',
                           raise_if_not_found=False)
        if uom and not uom.active:
            uom.active = True
        made = 0
        for mesh in self.search([('cloth_product_id', '=', False)]):
            label = CLOTH_LABELS.get(mesh.mechanism)
            if not label:
                continue
            name = 'Mesh cloth - %s' % label
            product = Product.search([('name', '=', name)], limit=1)
            if not product:
                values = {
                    'name': name, 'categ_id': category.id, 'type': 'consu',
                    'is_storable': False, 'sale_ok': False,
                    'purchase_ok': True, 'list_price': 0.0,
                }
                if uom:
                    values['uom_id'] = uom.id
                product = Product.create(values)
                made += 1
            mesh.cloth_product_id = product
        return made

    @api.model
    def _move_cloth_lines(self):
        """Move a mesh type's own cloth line onto that type's cloth product.

        Each type used to carry one line for the generic "Mesh cloth"
        product, quantity `OW * OH / 1000000` (the opening area, in m2).
        That IS the cloth, now priced by the sqft on the cloth product, so
        the line is pointed at it. The explosion skips a type line whose
        product is the type's own cloth (the sized line is the cloth), which
        is what keeps it to one cloth cost per panel.

        Fill-only and idempotent: only a line still on the generic product
        with exactly that formula moves, and only onto a type that HAS a
        cloth product. Anything else is left alone and counted, so a line
        that is not clearly the cloth is never guessed at. Nothing is
        deleted.
        """
        Line = self.env['aw.mesh.type.line']
        generic = self.env['product.product'].search([
            ('name', '=', 'Mesh cloth'),
            ('categ_id', '!=', self.env.ref(
                'aw_fenestration_core.product_category_mesh_cloth').id)])
        if not generic:
            return {'moved': 0, 'waiting': 0, 'unclear': 0}
        moved = waiting = unclear = 0
        for line in Line.with_context(active_test=False).search(
                [('product_id', 'in', generic.ids)]):
            formula = ''.join((line.qty_formula or '').split())
            if formula != 'OW*OH/1000000' or line.condition_formula:
                unclear += 1
                continue
            cloth = line.mesh_type_id.cloth_product_id
            if not cloth:
                waiting += 1        # a type with no cloth product yet
                continue
            line.product_id = cloth
            moved += 1
        # Logged at each start, but only when something moved or is waiting.
        if moved or waiting:
            _logger.info(
                "aw_fenestration_design: mesh cloth lines: %s moved to their "
                "type's cloth product, %s waiting for a cloth product, %s "
                "unclear and left alone", moved, waiting, unclear)
        return {'moved': moved, 'waiting': waiting, 'unclear': unclear}
