# -*- coding: utf-8 -*-
"""Phase 7e: glass off the system, finish off the spec lines.

**Every BOM and every price must be unchanged.** Three moves, each
reading the OLD column in SQL because the field it reads is gone from
the model while the column survives -- Odoo never drops a column it
stops using, which is what makes a migration like this possible at all.

1. `aw.window.series.default_glass_spec_id` is gone. Its value is copied
   onto the system's specs that have no glass of their own. A spec that
   already has one keeps it: the spec was always the more specific
   answer.

2. `aw.profile.section.line.finish_id` is gone; `aw.design.finish_id` is
   required. Every design takes the finish ITS OWN spec lines carried, so
   the variant each profile resolves to is the same record as before and
   the rate lookup lands on the same column. Today every seeded line is
   Natural, so in practice every design becomes Natural -- but reading it
   off the lines rather than assuming that is the difference between a
   migration that is correct and one that happens to be.

3. The seeded spec is renamed to its short name, "RE". Only if it still
   carries the name the seed gave it, so a spec renamed by hand is left
   alone.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

GLASS_PARAM = 'aw_fenestration.system_glass_moved_to_specs'
FINISH_PARAM = 'aw_fenestration.finish_moved_to_designs'
RENAME_PARAM = 'aw_fenestration.spec_short_name_applied'

# What the 7c seed called it, and what it is called now.
SEEDED_SPEC_NAME = 'Double Glaze – Openable – RE spec'
SHORT_SPEC_NAME = 'RE'


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    def _column_exists(self, table, column):
        self.env.cr.execute("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
        """, (table, column))
        return bool(self.env.cr.fetchone())

    @api.model
    def _migrate_system_glass_to_specs(self):
        """Copy each system's old Default Glass onto its specs."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(GLASS_PARAM):
            return False
        param.set_param(GLASS_PARAM, '1')
        if not self._column_exists('aw_window_series',
                                   'default_glass_spec_id'):
            return False

        self.env.cr.execute("""
            SELECT id, default_glass_spec_id FROM aw_window_series
             WHERE default_glass_spec_id IS NOT NULL
        """)
        filled = 0
        for system_id, glass_id in self.env.cr.fetchall():
            specs = self.with_context(active_test=False).search([
                ('window_type_id', '=', system_id),
                ('glass_spec_id', '=', False),
            ])
            if specs:
                specs.write({'glass_spec_id': glass_id})
                filled += len(specs)
        _logger.info(
            "aw_fenestration_core phase 7e: default glass copied onto %s "
            "specification(s)", filled)
        return True

    @api.model
    def _rename_seeded_spec(self):
        """'Double Glaze - Openable - RE spec' -> 'RE'."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(RENAME_PARAM):
            return False
        param.set_param(RENAME_PARAM, '1')
        specs = self.with_context(active_test=False).search(
            [('name', '=', SEEDED_SPEC_NAME)])
        if not specs:
            return False
        specs.write({'name': SHORT_SPEC_NAME})
        _logger.info(
            "aw_fenestration_core phase 7e: renamed %s specification(s) to "
            "'%s'", len(specs), SHORT_SPEC_NAME)
        return True


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
