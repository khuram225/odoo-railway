# -*- coding: utf-8 -*-
"""Saved glass specs -> a stack on every panel, once.

Each window's header gets the stack of the spec it pointed at, each profile
spec gets the stack of its default glass, and every panel that takes glass
gets its OWN copy of its effective glass (its override, else the window's),
so a panel can be changed alone from the start. The old spec records and the
pointers to them stay as they were: nothing is deleted, and the stored
drawing fingerprints do not move.

A migration must not change a quote. Sheets of a spec with no price take a
manual rate of 0, flagged "migrated", so the old number is visible and
Reset shows the real list rate. The three specs that did have a price take
the list rate: it is the same number the old product carried, and the glass
area is now in sqft, which is why those panels rise, as agreed.

It runs from the registry hook, after every module has loaded, in a
savepoint, and is logged rather than raised. It sets its parameter only when
every window has been looked at, so a half-finished run is picked up again;
a window that already has a stack is never touched twice.
"""
import json
import logging

from odoo import api, models

from .glass_recipes import recipe_for_spec

_logger = logging.getLogger(__name__)

MIGRATED_PARAM = 'aw_fenestration.glass_stacks_migrated'


class AwDesign(models.Model):
    _inherit = 'aw.design'

    def _register_hook(self):
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._migrate_glass_stacks()
        except Exception:
            _logger.exception("aw_fenestration_design: glass stack migration failed")

    @api.model
    def _stack_items_for_spec(self, spec):
        """The canonical dicts for a saved spec, or None when its name is
        not one the recipes know (nothing is guessed)."""
        if not spec:
            return []
        recipe = recipe_for_spec(
            spec.name, priced=spec.product_id.standard_price > 0)
        if recipe is None:
            return None
        return [self._recipe_dict(part) for part in recipe]

    @api.model
    def _migrate_glass_stacks(self):
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(MIGRATED_PARAM):
            return False
        Part = self.env['aw.glass.part']
        report = {'templates': 0, 'windows': 0, 'panels': 0, 'unknown': [],
                  'cost_before': {}, 'panels_with_remark': 0}
        templates = self.env['aw.window.template'].with_context(
            active_test=False).search([('glass_spec_id', '!=', False)])
        for template in templates:
            if template.glass_part_ids:
                continue
            items = self._stack_items_for_spec(template.glass_spec_id)
            if items is None:
                report['unknown'].append(template.glass_spec_id.name)
                continue
            template.glass_part_ids = Part._commands_from(items)
            report['templates'] += 1

        designs = self.with_context(active_test=False).search([])
        for design in designs:
            if design._has_glass_stacks():
                continue
            header = self._stack_items_for_spec(design.glass_spec_id)
            if header is None:
                report['unknown'].append(design.glass_spec_id.name)
                header = []
            if header:
                design.glass_part_ids = Part._commands_from(header)
            for leaf in design._all_panels():
                if leaf.leaf_type_id.code == 'MESH' or (
                        leaf.infill_type_id
                        and not leaf.infill_type_id.uses_glass):
                    continue
                items = self._stack_items_for_spec(
                    leaf.glass_spec_id or design.glass_spec_id)
                if not items:
                    continue
                leaf.glass_part_ids = Part._commands_from(items)
                report['panels'] += 1
                if any(i.get('remark') for i in items):
                    report['panels_with_remark'] += 1
            report['windows'] += 1
        report['unknown'] = sorted(set(report['unknown']))
        param.set_param(MIGRATED_PARAM, json.dumps(report))
        _logger.info("aw_fenestration_design: glass stacks: %s", report)
        return report
