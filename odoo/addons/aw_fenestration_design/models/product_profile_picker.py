# -*- coding: utf-8 -*-
"""Picking a profile on a purchase line: one variant, not the grid.

purchase_product_matrix opens its "Choose Product Variants" grid whenever
get_single_product_variant() answers nothing, which is every template with
dynamic attributes -- all 694 profiles, 674 of which have no variant yet. The
grid is for ordering a spread of variants; a profile line is one variant, so a
profile answers with its first existing variant, making the default one if
there is none. The variant column of the line picks another.
"""
from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def get_single_product_variant(self):
        result = super().get_single_product_variant()
        if result.get('product_id') or not self.aw_is_profile:
            return result
        variant = self.product_variant_ids[:1] \
            or self.sudo()._create_first_product_variant()
        if not variant:
            return result
        return dict(result, product_id=variant.id,
                    product_name=variant.display_name)
