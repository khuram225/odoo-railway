# -*- coding: utf-8 -*-
"""Move Profile Section / Hardware Set lines onto their Specification
(phase 7d).

The hard requirement: **a design already quoted must come out of this
with the same BOM and the same price.** The BOM is costed from the
section lines themselves, so the way to guarantee that is to RE-POINT
the existing line records rather than copy them -- same ids, same
products, same thicknesses, same formulas, same `product_id` already
resolved. A copy would have been easier to write and would have
re-resolved every variant, which is exactly where a price moves.

Three cases, in this order:

1. A section used by exactly one spec: its lines are re-pointed. No new
   records, nothing recomputed.
2. A section shared by several specs: each spec gets a COPY, because
   one line cannot have two owners. The first spec still re-points, so
   at least one design keeps its original records.
3. A section used by NO spec: a spec is CREATED for it. This is not in
   the brief and it is not optional -- after this phase a design takes
   its profiles from its spec, so a system with sections but no spec
   would silently produce an empty BOM for every design built on it.
   Creating the spec preserves what those designs are made of.

Guarded by a parameter, and every step is idempotent anyway: a line
that already has a spec_id is skipped.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

MIGRATED_PARAM = 'aw_fenestration.spec_owns_lines_migrated'
DEDUCTIONS_PARAM = 'aw_fenestration.spec_deductions_migrated'

# Copied from the system onto each of its specs. Named rather than
# derived so adding a field to the system does not silently start
# migrating it.
DEDUCTION_FIELDS = (
    'glass_fixed_w', 'glass_fixed_h', 'glass_sash_w', 'glass_sash_h',
    'mesh_w', 'mesh_h', 'max_panel_w', 'max_panel_h', 'max_panel_kg',
)


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    # ------------------------------------------------------------------
    @api.model
    def _spec_for_orphan_section(self, section):
        """A spec for a section no spec points at.

        Named after the section, because that is the name the shop
        already knows the thing by, and marked default only when its
        system has no default yet.
        """
        system = section.window_type_id
        existing = self.with_context(active_test=False).search(
            [('name', '=', section.name),
             ('window_type_id', '=', system.id)], limit=1)
        if existing:
            return existing
        has_default = self.search_count([
            ('window_type_id', '=', system.id),
            ('is_default', '=', True),
        ])
        return self.create({
            'name': section.name,
            'window_type_id': system.id,
            'profile_section_id': section.id,
            'hardware_set_id': system.hardware_set_ids[:1].id or False,
            'glass_spec_id': (
                system.default_glass_spec_id.id
                or self.env['aw.glass.spec'].search([], limit=1).id
                or False),
            'is_default': not has_default,
            'notes': "Created by the phase 7d migration, so the designs "
                     "built on this Profile Section keep their BOM.",
        })

    @api.model
    def _migrate_lines_to_specs(self):
        """Re-point (or copy) every line onto a Specification."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(MIGRATED_PARAM):
            return False

        Section = self.env['aw.profile.section'].with_context(
            active_test=False)
        HardwareSet = self.env['aw.hardware.set'].with_context(
            active_test=False)
        specs = self.with_context(active_test=False).search([])

        created = []
        # Case 3 first, so every section has a spec before anything is
        # re-pointed -- otherwise a section processed early could be
        # left empty and then adopted by a spec created later.
        for section in Section.search([]):
            if not section.line_ids:
                continue
            if specs.filtered(lambda s, x=section: s.profile_section_id == x):
                continue
            spec = self._spec_for_orphan_section(section)
            created.append(spec.name)
            specs |= spec

        moved = copied = 0
        for section in Section.search([]):
            users = specs.filtered(
                lambda s, x=section: s.profile_section_id == x)
            lines = section.line_ids.filtered(lambda l: not l.spec_id)
            if not (users and lines):
                continue
            # The first spec keeps the ORIGINAL records, so the designs
            # built to it are costed from exactly what they were costed
            # from before.
            lines.write({'spec_id': users[0].id, 'section_id': False})
            moved += len(lines)
            for spec in users[1:]:
                for line in lines:
                    line.copy({'spec_id': spec.id, 'section_id': False})
                    copied += 1

        hw_moved = hw_copied = 0
        for hardware in HardwareSet.search([]):
            users = specs.filtered(
                lambda s, x=hardware: s.hardware_set_id == x)
            lines = hardware.line_ids.filtered(lambda l: not l.spec_id)
            if not (users and lines):
                continue
            lines.write({'spec_id': users[0].id, 'set_id': False})
            hw_moved += len(lines)
            for spec in users[1:]:
                for line in lines:
                    line.copy({'spec_id': spec.id, 'set_id': False})
                    hw_copied += 1

        param.set_param(MIGRATED_PARAM, '1')
        _logger.info(
            "aw_fenestration_core phase 7d: %s profile line(s) re-pointed "
            "and %s copied; %s hardware line(s) re-pointed and %s copied; "
            "%s specification(s) created for sections that had none%s",
            moved, copied, hw_moved, hw_copied, len(created),
            (' (%s)' % '; '.join(created)) if created else '')
        return True

    @api.model
    def _migrate_deductions_to_specs(self):
        """Copy each system's deductions and limits onto its specs.

        Unconditional per spec rather than fill-only-if-empty: the
        spec's fields carry Odoo defaults ('PW - 60' and friends), so
        "empty" cannot be told apart from "defaulted", and a spec left
        on the defaults while its system had tuned values would change
        a quoted size. One-shot by parameter instead.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(DEDUCTIONS_PARAM):
            return False
        updated = 0
        for spec in self.with_context(active_test=False).search([]):
            system = spec.window_type_id
            if not system:
                continue
            spec.write({
                name: system[name] for name in DEDUCTION_FIELDS
            })
            updated += 1
        param.set_param(DEDUCTIONS_PARAM, '1')
        _logger.info(
            "aw_fenestration_core phase 7d: deductions and limits copied "
            "onto %s specification(s)", updated)
        return True
