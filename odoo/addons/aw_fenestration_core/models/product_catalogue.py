# -*- coding: utf-8 -*-
"""Where a product sits in the Chawla printed catalogue.

Reference data, not master data: it tells a buyer which page to open
and what section they are looking at. Nothing computes from it, which
is why they are plain Chars -- `aw_section_dims` stays "100 x 30"
rather than becoming two Floats, because it is quoted from the
catalogue and is sometimes "154.14 x 63" and sometimes blank.
"""
from odoo import fields, models


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
