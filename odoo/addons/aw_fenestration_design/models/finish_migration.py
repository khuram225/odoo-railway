# -*- coding: utf-8 -*-
"""Phase 7e, the design half: every design takes its spec's finish.

Lives HERE and not in `aw_fenestration_core` beside the rest of the 7e
migration, and the reason is worth stating because getting it wrong broke
a deploy: `aw.design` is defined in THIS module, which depends on core.
An `_inherit = 'aw.design'` inside core fails at registry load with
"Model 'aw.design' does not exist in registry" -- and the container still
starts, so the deploy reports success while every single request 500s.

A module may only extend a model defined in itself or in something it
depends on. `scripts/check_cross_module_inherit.py` enforces that now.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

FINISH_PARAM = 'aw_fenestration.finish_moved_to_designs'


class AwDesign(models.Model):
    _inherit = 'aw.design'

    @api.model
    def _migrate_finish_to_designs(self):
        """Give every design the finish its own spec lines carried.

        Read in SQL off the gone column, and the MOST COMMON value wins
        where a spec's lines disagree -- they never should, since the
        finish was required on every line and seeded uniformly, but a
        hand-edited spec could have two. The majority is the one most of
        the BOM was already costed at, so it is the choice that moves
        the fewest prices.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(FINISH_PARAM):
            return False
        param.set_param(FINISH_PARAM, '1')

        line_model = self.env['aw.profile.section.line']
        if not line_model._column_exists('aw_profile_section_line',
                                         'finish_id'):
            return False

        # spec -> the finish most of its lines used.
        self.env.cr.execute("""
            SELECT spec_id, finish_id, count(*) AS n
              FROM aw_profile_section_line
             WHERE spec_id IS NOT NULL AND finish_id IS NOT NULL
          GROUP BY spec_id, finish_id
          ORDER BY spec_id, n DESC
        """)
        by_spec = {}
        for spec_id, finish_id, _count in self.env.cr.fetchall():
            by_spec.setdefault(spec_id, finish_id)

        natural = self.env.ref(
            'aw_fenestration_core.aw_attr_val_finish_natural',
            raise_if_not_found=False)
        moved = defaulted = 0
        for design in self.with_context(active_test=False).search([]):
            if design.finish_id:
                continue
            wanted = by_spec.get(design.template_id.id)
            if wanted:
                design.finish_id = wanted
                moved += 1
            elif natural:
                design.finish_id = natural
                defaulted += 1
        _logger.info(
            "aw_fenestration_core phase 7e: %s design(s) took their spec's "
            "finish, %s fell back to Natural", moved, defaulted)
        return True
