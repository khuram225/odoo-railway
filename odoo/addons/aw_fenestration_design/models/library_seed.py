# -*- coding: utf-8 -*-
"""The Layout Library's Shapes and Designs (Part 2, revised).

Replaces the mechanism-based library (Openable / Sliding / Tilt & Turn /
Twin Sash / Curtain Wall). Grouping by mechanism is a fact about the
panels, not a way anybody shops for a starting point: an estimator
looking at a 3-across opening with a top light wants to find "top light
over 3 across", and does not care that the panels happen to be casements.

So the library is now **Shapes** (geometry, every panel Fixed) and
**Designs** (named layouts the shop actually builds, with their panel
types). The old presets are ARCHIVED rather than deleted -- a design
quoted from one still names it, and `active=False` keeps that readable
while taking it out of the library.

Seeded by name, fill-only-if-absent, for the reason this repo has hit
three times now: these are user-editable records, and an xmlid cannot
see one the client made by hand. A preset that already exists under the
same name is adopted and left exactly as it is.
"""
import json
import logging

from odoo import api, models

from .library_data import DESIGNS, RETIRED_PREFIXES, SHAPES

_logger = logging.getLogger(__name__)

SEEDED_PARAM = 'aw_fenestration.layout_library_seeded'
RETIRED_PARAM = 'aw_fenestration.old_presets_retired'


class AwLayoutPreset(models.Model):
    _inherit = 'aw.layout.preset'

    @api.model
    def _seed_layout_library(self):
        """Seed the Shapes and Designs, once, by NAME.

        Both lists are left with no family_ids and no series_ids: a
        shape fits anywhere its (all-Fixed) panels fit, and the
        client's designs have not been assigned to systems yet. The
        leaf-type backstop in _allowed_for_series still keeps a
        casement design off a Fix-only system.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SEEDED_PARAM):
            return False

        created = []
        for kind, entries in (('shape', SHAPES), ('design', DESIGNS)):
            for name, code, sequence, rows in entries:
                # =ilike is an exact match that ignores case, so a
                # preset the client typed as "2 Across" is adopted
                # rather than duplicated.
                if self.with_context(active_test=False).search_count(
                        [('name', '=ilike', name)]):
                    continue
                self.create({
                    'name': name,
                    'code': code,
                    'kind': kind,
                    'sequence': sequence,
                    'layout_json': json.dumps({'rows': rows}),
                })
                created.append(code)
        param.set_param(SEEDED_PARAM, '1')
        _logger.info(
            "aw_fenestration_design: seeded %s layout library entr(ies)%s",
            len(created), (': %s' % ', '.join(created)) if created else '')
        return bool(created)

    @api.model
    def _retire_mechanism_presets(self):
        """Archive the mechanism-based presets, once.

        ARCHIVED, never deleted: a design quoted from one still carries
        its name, and unlinking would either fail on the reference or
        lose the only record of what the quote was started from.
        active=False takes it out of the library and leaves it
        readable, which is the whole difference.

        One-shot by parameter rather than fill-only-if-empty, because
        `active` is a Boolean: False is both "archived by this" and
        "archived by hand", so re-running could never tell whether
        somebody had deliberately brought one back.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(RETIRED_PARAM):
            return False
        presets = self.search([])
        retired = presets.filtered(
            lambda p: (p.code or '').startswith(RETIRED_PREFIXES))
        if retired:
            retired.write({'active': False})
        param.set_param(RETIRED_PARAM, '1')
        _logger.info(
            "aw_fenestration_design: archived %s mechanism-based preset(s)",
            len(retired))
        return bool(retired)

    @api.model
    def _retire_layout_families(self):
        """Archive the old library families.

        They grouped presets by mechanism and the library does not group
        that way any more. The MODEL stays -- aw.layout.family is still
        what `family_id` points at on every existing preset, and that
        link is the only record of the old grouping -- but the records
        come out of the picture and the menu is gone.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(RETIRED_PARAM + '_families'):
            return False
        families = self.env['aw.layout.family'].search([])
        if families:
            families.write({'active': False})
        param.set_param(RETIRED_PARAM + '_families', '1')
        _logger.info(
            "aw_fenestration_design: archived %s layout family record(s)",
            len(families))
        return bool(families)

    @api.model
    def _classify_existing_presets(self):
        """Give every pre-existing preset a kind, once.

        `kind` defaults to 'design', which is right for anything named
        and typed, and _init_column writes that default onto every
        existing row. This only has to correct the ones that are really
        shapes: all-Fixed layouts, which is exactly the test the Shape
        constraint applies.
        """
        param = self.env['ir.config_parameter'].sudo()
        key = SEEDED_PARAM + '_classified'
        if param.get_param(key):
            return False
        moved = 0
        for preset in self.with_context(active_test=False).search([]):
            if preset.kind == 'shape':
                continue
            if preset._leaf_type_codes() <= {'FIXED'}:
                preset.kind = 'shape'
                moved += 1
        param.set_param(key, '1')
        _logger.info(
            "aw_fenestration_design: classified %s existing preset(s) as "
            "Shapes", moved)
        return bool(moved)
