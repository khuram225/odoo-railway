# -*- coding: utf-8 -*-
"""Glass suggested per panel (Lake City schedule).

[revisit: the two thresholds and the wet-room words are read off the
Lake City schedule; the client is to confirm them.]

The rule, in order, for one panel:

1. the window's Location has a word STARTING WITH one of the wet-room
   words in Settings (BATH, POWDER, TOILET, WC, WASHROOM by default; any
   case, so BATH matches Bathroom and GF-BATH) -> Frosted;
2. the pane is at least the larger threshold (default 7 m2) -> 8+8+8;
3. at least the smaller one (default 4.5 m2) -> 6+10+8;
4. otherwise nothing: the panel follows the window's own glass.

The larger threshold is tested first. Tested the other way round, every
pane over 7 m2 would already have matched 4.5 and 8+8+8 could never be
suggested.

It only ever FILLS: a panel with glass chosen by hand is skipped, and a
panel whose glass was itself a suggestion is re-worked when its size or
the window's location changes. Only windows made after the feature
arrived take part (suggest_glass), and only in a double-glazed family,
because the four types are sealed units.
"""
import re

from odoo import api, models

from .glass_recipes import recipe_for_spec

WET_WORDS = 'aw_fenestration.glass_wet_words'
DEFAULT_WET_WORDS = 'BATH, POWDER, TOILET, WC, WASHROOM'
THRESHOLD_1 = 'aw_fenestration.glass_threshold_1_m2'
THRESHOLD_2 = 'aw_fenestration.glass_threshold_2_m2'
DEFAULT_THRESHOLD_1 = 4.5
DEFAULT_THRESHOLD_2 = 7.0

# The Lake City schedule, by the names glass_recipes.py knows them by.
CLEAR_6_10_8 = '6+10+8 Clear Tempered'
CLEAR_8_8_8 = '8+8+8 Clear Tempered'
FROSTED = '6+10+6 Frosted Tempered'


class AwDesign(models.Model):
    _inherit = 'aw.design'

    @api.model
    def _glass_thresholds(self):
        param = self.env['ir.config_parameter'].sudo()

        def read(key, default):
            # get_param() answers False for a key never saved, and a
            # Settings page saved with the box empty stores 0. float(False)
            # is 0.0, and a threshold of 0 m2 suggested the heaviest glass
            # (8+8+8) for EVERY panel on a database whose Settings had not
            # been saved. Neither is a usable limit: use the default.
            try:
                value = float(param.get_param(key) or 0.0)
            except ValueError:
                return default
            return value if value > 0.0 else default

        return (read(THRESHOLD_1, DEFAULT_THRESHOLD_1),
                read(THRESHOLD_2, DEFAULT_THRESHOLD_2))

    @api.model
    def _wet_room(self, location):
        """Does a Location word start with a wet-room word?"""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            WET_WORDS) or DEFAULT_WET_WORDS
        keywords = [w.strip().lower() for w in re.split(r'[,;]', raw)
                    if w.strip()]
        words = re.findall(r'[a-z0-9]+', (location or '').lower())
        return any(word.startswith(k) for word in words for k in keywords)

    def _suggested_glass_for(self, leaf):
        """The name of the stack the rule suggests for one panel, or ''."""
        self.ensure_one()
        if self._wet_room(self.location):
            return FROSTED
        area_m2 = (leaf.width_mm or 0.0) * (leaf.row_id.height_mm or 0.0) / 1e6
        small, large = self._glass_thresholds()
        if area_m2 >= large:
            return CLEAR_8_8_8
        if area_m2 >= small:
            return CLEAR_6_10_8
        return ''

    def _suggest_glass(self):
        """Fill the glass of panels that have none; see the module note."""
        for design in self:
            if not (design.suggest_glass
                    and design.family_id.glazing == 'double'):
                continue
            Part = self.env['aw.glass.part']
            default = Part._signature(design._glass_stack_dicts())
            for leaf in design._all_panels():
                if leaf.leaf_type_id.code == 'MESH' or (
                        leaf.infill_type_id
                        and not leaf.infill_type_id.uses_glass):
                    continue
                if leaf.glass_chosen or (
                        leaf.glass_part_ids and not leaf.glass_suggested):
                    continue          # chosen by hand: never replaced
                pick = design._suggested_glass_for(leaf)
                items = []
                if pick:
                    recipe = recipe_for_spec(pick, priced=True)
                    items = [dict(design._recipe_dict(p), migrated=False,
                                  rate_manual=False)
                             for p in (recipe or [])]
                if items and Part._signature(items) != default:
                    values = {'glass_part_ids': [(5, 0, 0)]
                              + Part._commands_from(items),
                              'glass_suggested': True}
                else:
                    # Nothing to suggest (or it equals the window's own
                    # glass): a previous suggestion is withdrawn, and the
                    # panel follows the window's stack again.
                    values = {'glass_part_ids': [(5, 0, 0)],
                              'glass_suggested': False}
                leaf.write(values)
