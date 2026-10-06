# -*- coding: utf-8 -*-
"""Glass suggested per panel (Lake City schedule).

[revisit: the two thresholds and the wet-room words are read off the
Lake City schedule; the client is to confirm them.]

The rule, in order, for one panel:

1. the window's Location names a wet room (BATH, POWDER, TOILET or WC,
   as whole words, any case) -> Frosted;
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

WET_ROOM = re.compile(r'\b(bath|powder|toilet|wc)\b', re.IGNORECASE)
THRESHOLD_1 = 'aw_fenestration.glass_threshold_1_m2'
THRESHOLD_2 = 'aw_fenestration.glass_threshold_2_m2'
DEFAULT_THRESHOLD_1 = 4.5
DEFAULT_THRESHOLD_2 = 7.0

CLEAR_6_10_8 = 'aw_fenestration_core.glass_spec_lc_6_10_8_clear'
CLEAR_8_8_8 = 'aw_fenestration_core.glass_spec_lc_8_8_8_clear'
FROSTED = 'aw_fenestration_core.glass_spec_lc_6_10_6_frosted'


class AwDesign(models.Model):
    _inherit = 'aw.design'

    @api.model
    def _glass_thresholds(self):
        param = self.env['ir.config_parameter'].sudo()

        def read(key, default):
            try:
                value = param.get_param(key)
                return float(value) if value not in (None, '') else default
            except ValueError:
                return default

        return (read(THRESHOLD_1, DEFAULT_THRESHOLD_1),
                read(THRESHOLD_2, DEFAULT_THRESHOLD_2))

    def _suggested_glass_for(self, leaf):
        """The glass the rule suggests for one panel, or empty."""
        self.ensure_one()
        Glass = self.env['aw.glass.spec']
        if WET_ROOM.search(self.location or ''):
            return self.env.ref(FROSTED, raise_if_not_found=False) or Glass
        area_m2 = (leaf.width_mm or 0.0) * (leaf.row_id.height_mm or 0.0) / 1e6
        small, large = self._glass_thresholds()
        if area_m2 >= large:
            return self.env.ref(CLEAR_8_8_8, raise_if_not_found=False) or Glass
        if area_m2 >= small:
            return self.env.ref(CLEAR_6_10_8, raise_if_not_found=False) or Glass
        return Glass

    def _suggest_glass(self):
        """Fill the glass of panels that have none; see the module note."""
        for design in self:
            if not (design.suggest_glass
                    and design.family_id.glazing == 'double'):
                continue
            default = design.glass_spec_id or design.template_id.glass_spec_id
            for leaf in design._all_panels():
                if leaf.leaf_type_id.code == 'MESH' or (
                        leaf.infill_type_id
                        and not leaf.infill_type_id.uses_glass):
                    continue
                if leaf.glass_spec_id and not leaf.glass_suggested:
                    continue          # chosen by hand: never replaced
                pick = design._suggested_glass_for(leaf)
                if pick and pick != default:
                    values = {'glass_spec_id': pick.id,
                              'glass_suggested': True}
                else:
                    # Nothing to suggest (or it equals the window's own
                    # glass): a previous suggestion is withdrawn.
                    values = {'glass_spec_id': False,
                              'glass_suggested': False}
                leaf.write(values)
