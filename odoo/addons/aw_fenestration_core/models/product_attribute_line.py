# -*- coding: utf-8 -*-
from odoo import api, models


class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    @api.model_create_multi
    def create(self, vals_list):
        """One line per attribute per template.

        Odoo reuses an ARCHIVED line for the same attribute but not an
        active one, so a data file or import that adds lines with `(0, 0,
        ...)` commands added a second line every time it ran: five
        profiles ended up with five Thickness and five Finish lines after
        four reinstalls. Here an active line for the same template and
        attribute takes the new values instead of a new line being made.
        """
        records = self.browse()
        for vals in vals_list:
            existing = self.browse()
            if vals.get('product_tmpl_id') and vals.get('attribute_id'):
                existing = self.search([
                    ('product_tmpl_id', '=', vals['product_tmpl_id']),
                    ('attribute_id', '=', vals['attribute_id']),
                    ('active', '=', True)], limit=1)
            if existing:
                ids = set()
                for command in vals.get('value_ids') or []:
                    if command[0] == 6:
                        ids.update(command[2])
                    elif command[0] == 4:
                        ids.add(command[1])
                new = ids - set(existing.value_ids.ids)
                if new:
                    existing.write({'value_ids': [(4, i) for i in new]})
                records |= existing
            else:
                records |= super().create([vals])
        return records
