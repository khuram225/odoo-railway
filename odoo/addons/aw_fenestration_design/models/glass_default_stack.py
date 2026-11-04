# -*- coding: utf-8 -*-
"""A new window starts with its spec's default glass stack.

The seeded "Double Glaze - Openable" spec used to point at a saved glass
spec (24mm DGU). It gets a default STACK instead: a plain sealed unit,
6 + 12 + 6 Clear. Once, from the registry hook (it creates records of the
design module's own model, after every module has loaded), and only for a
spec that has no stack: a database that already had its stacks migrated, or
a user who removed the default, is left exactly as it is.
"""
import logging

from odoo import api, models

from odoo.addons.aw_fenestration_core.models.section_seed import SPEC_ID_PARAM

from .glass_recipes import DEFAULT_SEALED_UNIT

_logger = logging.getLogger(__name__)

SEEDED_PARAM = 'aw_fenestration.default_glass_stack_seeded'
CLEARED_PARAM = 'aw_fenestration.default_stack_rates_cleared'


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    def _register_hook(self):
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._seed_default_glass_stacks()
        except Exception:
            _logger.exception(
                "aw_fenestration_design: default glass stack seed failed")
        try:
            with self.env.cr.savepoint():
                self._clear_migrated_default_rates()
        except Exception:
            _logger.exception(
                "aw_fenestration_design: clearing migrated default rates "
                "failed")

    @api.model
    def _seed_default_glass_stacks(self):
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SEEDED_PARAM):
            return False
        spec_id = param.get_param(SPEC_ID_PARAM)
        if not spec_id:
            return False
        spec = self.with_context(active_test=False).browse(
            int(spec_id)).exists()
        param.set_param(SEEDED_PARAM, '1')
        if not spec or spec.glass_part_ids:
            return False
        Part = self.env['aw.glass.part']
        items = [self.env['aw.design']._recipe_dict(part)
                 for part in DEFAULT_SEALED_UNIT]
        spec.glass_part_ids = Part._commands_from(items)
        return True

    @api.model
    def _clear_migrated_default_rates(self):
        """A default stack is priced from the list, never from a typed 0.

        The migration from the saved glass specs gave every sheet that had
        no price of its own a manual rate of 0, flagged "migrated", so the
        migration would not change a quote. That is right for a panel on a
        quote, but a spec's default stack is what every NEW window copies,
        flags and all: a new window came out with glass at 0. Once, clear
        the manual 0 and the flag from every part that is not on a panel of
        a window on an order. A typed rate that is not 0 is somebody's
        decision and stays, and so does a part on an existing order's
        window, which must not re-price.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(CLEARED_PARAM):
            return 0
        Part = self.env['aw.glass.part'].with_context(active_test=False)
        parts = Part.search([
            ('rate_manual', '=', True), ('manual_rate', '=', 0.0),
            ('migrated', '=', True)])
        loose = parts.filtered(lambda p: p.template_id or not (
            (p.design_id or p.leaf_id.row_id.design_id).sale_order_line_id))
        loose.write({'rate_manual': False, 'migrated': False})
        param.set_param(CLEARED_PARAM, '1')
        _logger.info(
            "aw_fenestration_design: %s migrated manual rate(s) cleared "
            "from default stacks (%s kept on orders)",
            len(loose), len(parts) - len(loose))
        return len(loose)
