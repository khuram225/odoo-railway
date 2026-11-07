# -*- coding: utf-8 -*-
"""Shared fixtures for the design tests.

A database installed from scratch has no Specification: the RE spec is seeded
by data functions that run BEFORE the Chawla profiles are imported, so they
find nothing to build it from (see CLAUDE.md, "Tests"). A design in such a
database has no spec and every reader of its parts fails. Production does
have the spec, so the tests that need one make it the way production did:
by running the same seed functions again, now that the profiles exist.
"""
from odoo.addons.aw_fenestration_core.models.section_seed import (
    SEEDED_PARAM, SPEC_SEEDED_PARAM)
from odoo.addons.aw_fenestration_core.models.spec_migration import (
    DEDUCTIONS_PARAM, MIGRATED_PARAM)

SERIES_XMLID = 'aw_fenestration_core.window_series_casement_dg'


def seeded_family_series(env):
    """(family, series) of the seeded RE spec, creating the spec if the
    database does not have it yet. Idempotent."""
    series = env.ref(SERIES_XMLID)
    Spec = env['aw.window.template']
    if not Spec.search_count([('window_type_id', '=', series.id)]):
        param = env['ir.config_parameter'].sudo()
        param.set_param(SEEDED_PARAM, False)
        param.set_param(SPEC_SEEDED_PARAM, False)
        env['aw.profile.section']._seed_dg_openable_section()
        env['aw.profile.section']._seed_dg_openable_spec()
        # production's spec got its lines (and the system's glass rules) from
        # these two migrations; without them the spec has no profiles at all
        param.set_param(MIGRATED_PARAM, False)
        param.set_param(DEDUCTIONS_PARAM, False)
        Spec._migrate_lines_to_specs()
        Spec._migrate_deductions_to_specs()
        param.set_param('aw_fenestration.default_glass_stack_seeded', False)
        Spec._seed_default_glass_stacks()
    family = env['aw.window.family'].search([]).filtered(
        lambda f: series in f.series_ids)[:1]
    return family, series


def first_thickness(env, template):
    """A Thickness value the profile template is sold in, so a spec line made
    for it resolves to a product (a dynamic attribute makes no variant for a
    value the template does not carry, and the piece is then skipped with
    'No thickness is chosen')."""
    attribute = env.ref('aw_fenestration_core.aw_attribute_thickness')
    line = template.attribute_line_ids.filtered(
        lambda l: l.attribute_id == attribute)[:1]
    return line.value_ids[:1]
