# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    aw_is_mesh_cloth = fields.Boolean(
        compute='_compute_aw_is_mesh_cloth',
        help="In Fenestration / Mesh cloth: bought by the sqft and never "
             "sold, so there is no sales price on its form. Its cost, per "
             "ft2, is typed here.")

    @api.depends('categ_id')
    def _compute_aw_is_mesh_cloth(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_mesh_cloth',
            raise_if_not_found=False)
        for template in self:
            template.aw_is_mesh_cloth = bool(
                category and template.categ_id
                and (template.categ_id.parent_path or '').startswith(
                    category.parent_path or '\0'))
