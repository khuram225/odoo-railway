# -*- coding: utf-8 -*-
"""Where a product sits in the Chawla printed catalogue.

Reference data, not master data: it tells a buyer which page to open
and what section they are looking at. Nothing computes from it, which
is why they are plain Chars -- `aw_section_dims` stays "100 x 30"
rather than becoming two Floats, because it is quoted from the
catalogue and is sometimes "154.14 x 63" and sometimes blank.
"""
from odoo import api, fields, models

from .thickness import implausible_thickness, norm_thickness


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    aw_catalogue_code = fields.Char(
        string='Catalogue Code', index=True,
        help="The code as printed in the catalogue, e.g. 'DC-30 (BA)'. "
             "Often differs in spacing and brackets from the product "
             "name, which is why it is kept separately.")
    aw_catalogue_category = fields.Char(string='Catalogue Section')
    aw_catalogue_page = fields.Integer(string='Catalogue Page')
    aw_section_dims = fields.Char(
        string='Section (mm)',
        help="Section dimensions as printed, e.g. '100 x 30'.")
    aw_catalogue_thickness = fields.Char(
        string='Catalogue Thickness',
        help="Thicknesses as printed. The product's real Thickness "
             "attribute is what the BOM and the rates use; this is the "
             "catalogue's own wording, kept for comparison.")

    def _aw_merge_catalogue_thickness(self):
        """Add the catalogue's thickness values to the Thickness line.

        UNION, never replacement: the price list and the catalogue
        disagree about which thicknesses a profile comes in, and the
        price list is the one that can actually be costed. Dropping a
        priced thickness because the catalogue omits it would silently
        remove a variant somebody may already have quoted.

        Returns {template: [names added]} so the caller can report it.
        """
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        cache = {
            value.name: value
            for value in self.env['product.attribute.value'].search(
                [('attribute_id', '=', thickness_attr.id)])}

        added, refused = {}, {}
        for template in self:
            raw = template.aw_catalogue_thickness or ''
            if not raw:
                continue
            # The two catalogue files punctuate differently: the
            # existing-products export separates with commas, the new
            # one with semicolons.
            wanted = self.env['product.attribute.value']
            for token in raw.replace(';', ',').split(','):
                canonical = norm_thickness(token)
                if not canonical:
                    continue
                if implausible_thickness(canonical):
                    refused.setdefault(template, []).append(canonical)
                    continue
                value = cache.get(canonical)
                if not value:
                    value = self.env['product.attribute.value'].create({
                        'name': canonical,
                        'attribute_id': thickness_attr.id,
                    })
                    cache[canonical] = value
                wanted |= value
            if not wanted:
                continue

            line = template.attribute_line_ids.filtered(
                lambda l: l.attribute_id == thickness_attr)
            if line:
                new = wanted - line.value_ids
                if new:
                    line.value_ids = [(4, value.id) for value in new]
                    added[template] = new.mapped('name')
            else:
                template.attribute_line_ids = [(0, 0, {
                    'attribute_id': thickness_attr.id,
                    'value_ids': [(6, 0, wanted.ids)],
                })]
                added[template] = wanted.mapped('name')
        return added, refused
