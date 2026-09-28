# -*- coding: utf-8 -*-
"""The client's "Double Glaze - Openable - Profile 1" section (spec 9).

Seeded once, fill-only-if-empty. Two things worth knowing about the
product lookup:

- Names are matched EXACTLY. All six RE- profiles exist under their
  bare names in the price-list import; a prefix match would be actively
  wrong, because "RE-1" is a prefix of RE-10 through RE-16 and RE-127.
- The price list carries an "M.F" suffix on some profiles (RE-12 M.F),
  so an exact miss falls back to "<code> M.F" before giving up. None of
  the six need it today; the fallback is there because the next section
  the client sends may.

RE-13 is deliberately NOT placed: the client listed it without saying
where it goes. Guessing a position would put a real profile into a real
cut list. Marked [revisit] in the spec.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

SECTION_NAME = 'Double Glaze – Openable – Profile 1'
SECTION_SERIES_XMLID = 'window_series_casement_dg'
SEEDED_PARAM = 'aw_fenestration.section_dg_openable_seeded'

# position xmlid -> [(product name, sequence, option label, max span mm)]
SECTION_LINES = {
    'pos_frame_top': [('RE-8', 10, '', 0.0)],
    'pos_frame_bottom': [('RE-8', 10, '', 0.0)],
    'pos_frame_sides': [('RE-8', 10, '', 0.0)],
    # Two alternatives on each divider. Lowest sequence is the default,
    # which is the rule Profile Sections already used for alternates.
    # max_span_mm is left at 0 -- no span rating has been given, and an
    # invented one would raise warnings nobody asked for. [revisit]
    'pos_divider_vertical': [
        ('RE-1', 10, 'Economy', 0.0),
        ('RE-3', 20, 'Heavy duty', 0.0),
    ],
    'pos_divider_horizontal': [
        ('RE-1', 10, 'Economy', 0.0),
        ('RE-3', 20, 'Heavy duty', 0.0),
    ],
    'pos_palay_top': [('RE-15', 10, '', 0.0)],
    'pos_palay_bottom': [('RE-15', 10, '', 0.0)],
    'pos_palay_sides': [('RE-15', 10, '', 0.0)],
    'pos_palay_bead_top': [('RE-10', 10, '', 0.0)],
    'pos_palay_bead_bottom': [('RE-10', 10, '', 0.0)],
    'pos_palay_bead_sides': [('RE-10', 10, '', 0.0)],
}


class AwProfileSection(models.Model):
    _inherit = 'aw.profile.section'

    @api.model
    def _find_profile_template(self, code):
        """Exact name, then the price list's 'M.F' spelling.

        Never a prefix or ilike match: RE-1 would happily match RE-10,
        and a cut list built from the wrong profile is expensive and
        invisible.
        """
        Template = self.env['product.template']
        for candidate in (code, '%s M.F' % code):
            found = Template.with_context(active_test=False).search(
                [('name', '=', candidate)], limit=1)
            if found:
                return found
        return Template.browse()

    @api.model
    def _seed_dg_openable_section(self):
        """Create the section once, and report anything not found."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SEEDED_PARAM):
            return False

        series = self.env.ref(
            'aw_fenestration_core.%s' % SECTION_SERIES_XMLID,
            raise_if_not_found=False)
        if not series:
            return False
        if self.with_context(active_test=False).search_count(
                [('name', '=', SECTION_NAME),
                 ('window_type_id', '=', series.id)]):
            param.set_param(SEEDED_PARAM, '1')
            return False

        thickness = self.env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_normal',
            raise_if_not_found=False)
        finish = self.env.ref(
            'aw_fenestration_core.aw_attr_val_finish_natural',
            raise_if_not_found=False)

        lines, missing = [], []
        for position_xmlid, options in SECTION_LINES.items():
            position = self.env.ref(
                'aw_fenestration_core.%s' % position_xmlid,
                raise_if_not_found=False)
            if not position:
                missing.append('position %s' % position_xmlid)
                continue
            for code, sequence, label, max_span in options:
                template = self._find_profile_template(code)
                if not template:
                    missing.append('%s (for %s)' % (code, position.name))
                    continue
                lines.append((0, 0, {
                    'position_id': position.id,
                    'product_tmpl_id': template.id,
                    'thickness_id': thickness.id if thickness else False,
                    'finish_id': finish.id if finish else False,
                    'sequence': sequence,
                    'option_label': label,
                    'max_span_mm': max_span,
                }))

        if lines:
            self.create({
                'name': SECTION_NAME,
                'window_type_id': series.id,
                'line_ids': lines,
                'notes': "Seeded from the client's Profile 1 breakdown. "
                         "RE-13 was listed without a position and is "
                         "deliberately not placed.",
            })
        if missing:
            _logger.warning(
                "aw_fenestration_core: '%s' seeded without %s",
                SECTION_NAME, '; '.join(missing))
        param.set_param(SEEDED_PARAM, '1')
        return True
