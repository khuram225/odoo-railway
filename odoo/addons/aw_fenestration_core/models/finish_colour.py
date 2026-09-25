# -*- coding: utf-8 -*-
"""Make Finish a colour attribute, once.

Verified against odoo-src before choosing this:

- `product.attribute.display_type` really does offer `('color', 'Color')`
  (product/models/product_attribute.py).
- The **sale order product configurator** renders it as real swatches:
  `sale.ptav_color` sets `background-color: ptav.html_color`, marks the
  chosen one `active`, and falls back to a `transparent` class when
  `html_color` is empty (sale/static/src/js/product_template_attribute_
  line/product_template_attribute_line.xml).
- The **backend** shows `html_color` as an editable `widget="color"`
  field on the attribute's values, not as a swatch on the product form.
  There, values appear as tags coloured by the separate INTEGER `color`
  index -- which is why both are set.

The integer index is a coarse 12-entry palette (No color, Red, Orange,
Yellow, Cyan, Purple, Almond, Teal, Blue, Raspberry, Green, Violet --
web/static/src/core/colorlist/colorlist.js), so the mapping below is
the nearest sensible match and nothing more. `html_color` is the
accurate one.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

SEEDED_PARAM = 'aw_fenestration.finish_colours_seeded'

# value name -> (html_color, tag colour index)
FINISH_COLOURS = {
    'Natural': ('#B8BCC0', 0),              # light grey: No color
    'H23 PC RAL': ('#F2F2F2', 0),           # near white: No color
    'Brown PC Sahara': ('#6E4A2E', 6),      # Almond, the only brown
    'Black Multi SS Dull': ('#1E1E1E', 8),  # Blue, the darkest offered
    'Designer': ('#9C6B3E', 2),             # tan -> Orange
    'C-Shine': ('#D9C79E', 3),              # champagne -> Yellow
}


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    @api.model
    def _seed_finish_colours(self):
        """Fill-only-if-empty, once per database.

        The display type is set unconditionally the first time and then
        left alone: switching Finish back to a dropdown is a legitimate
        choice, and re-imposing 'color' on every upgrade would undo it
        silently -- the same trap the leaf-type seed was rewritten to
        avoid.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SEEDED_PARAM):
            return 0

        attribute = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish',
            raise_if_not_found=False)
        if not attribute:
            return 0
        if attribute.display_type != 'color':
            attribute.display_type = 'color'

        filled = 0
        for value in attribute.value_ids:
            colours = FINISH_COLOURS.get(value.name)
            if not colours:
                continue
            html_colour, index = colours
            values = {}
            if not value.html_color:
                values['html_color'] = html_colour
            # 0 is "No color", i.e. unset, so it is safe to treat as
            # empty; a value someone has already coloured is not touched.
            if not value.color:
                values['color'] = index
            if values:
                value.write(values)
                filled += 1

        param.set_param(SEEDED_PARAM, '1')
        _logger.info(
            "aw_fenestration_core: Finish is now a colour attribute; "
            "%s value(s) given a colour.", filled)
        return filled
