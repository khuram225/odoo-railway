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
