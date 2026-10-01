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

2. The design half of this -- giving every design the finish its spec
   lines carried -- lives in `aw_fenestration_design`, in
   `models/finish_migration.py` there. It CANNOT live here: `aw.design`
   is defined in that module, which depends on this one, so an
   `_inherit = 'aw.design'` in core fails at registry load with "Model
   'aw.design' does not exist in registry" and takes every request down
   with it. That is not a style point; it is what broke a deploy.

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
