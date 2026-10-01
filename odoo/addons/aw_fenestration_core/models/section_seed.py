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

RE-13 is the LOCK BAR, confirmed in Phase 7d. It was listed without a
position originally and deliberately left unplaced rather than guessed;
now that the client has said where it goes, it is seeded like the rest.

**The thickness has to come from the product, not from a preference.**
This section originally seeded every line with 'Normal', and the price
list sells all six RE- profiles only in 'Std' -> 'Standard'. Thickness
is a Dynamic-creation attribute, so a value the template does not carry
makes no variant at all: every profile line read "No product", nothing
resolved a rate, and the design priced at zero. _seed_thickness_for()
now takes the product's own thickness when it has exactly one, and says
so when there is a real choice rather than guessing.
_fix_dg_openable_thickness() is the one-shot that corrects the sections
already created.
"""
import logging

from odoo import api, models

from .thickness import choose_thickness

_logger = logging.getLogger(__name__)

SECTION_NAME = 'Double Glaze – Openable – Profile 1'
# What the section is called once the RE thicknesses are corrected.
# "Profile 1" was the client's own heading for the breakdown; the set
# is the thing worth naming now that we know what is in it.
SECTION_NAME_FIXED = 'Double Glaze – Openable – RE set'
SECTION_SERIES_XMLID = 'window_series_casement_dg'
SEEDED_PARAM = 'aw_fenestration.section_dg_openable_seeded'
THICKNESS_FIX_PARAM = 'aw_fenestration.section_dg_openable_thickness_fixed'

# position xmlid -> (default profile, [alternate profiles])
#
# ONE line per position since the phase 7d entry clean-up. The dividers
# used to be two lines distinguished by sequence and named 'Economy' /
# 'Heavy duty'; RE-3 is an ALTERNATE of RE-1 now, which is the same
# choice expressed as what it is -- a different profile in the same
# slot. No span rating is seeded on either: none has been given, and an
# invented one would raise warnings nobody asked for. [revisit]
SECTION_LINES = {
    'pos_frame_top': ('RE-8', []),
    'pos_frame_bottom': ('RE-8', []),
    'pos_frame_sides': ('RE-8', []),
    'pos_divider_vertical': ('RE-1', ['RE-3']),
    'pos_divider_horizontal': ('RE-1', ['RE-3']),
    'pos_palay_top': ('RE-15', []),
    'pos_palay_bottom': ('RE-15', []),
    'pos_palay_sides': ('RE-15', []),
    'pos_palay_bead_top': ('RE-10', []),
    'pos_palay_bead_bottom': ('RE-10', []),
    'pos_palay_bead_sides': ('RE-10', []),
    # Phase 7d. One piece, on the lock side of an opening panel.
    'pos_lock_bar': ('RE-13', []),
}

# The specification seeded over that section (phase 7c). "Spec" is the
# user-facing word for aw.window.template throughout.
SPEC_NAME = 'Double Glaze – Openable – RE spec'
SPEC_GLASS_XMLID = 'glass_spec_dgu_24'
SPEC_SEEDED_PARAM = 'aw_fenestration.spec_dg_openable_seeded'


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
    def _seed_thickness_for(self, template, preferred):
        """The thickness to seed on a line for `template`.

        Returns (value, warning). Seeding a thickness the product is
        not sold in resolves to no variant at all, silently -- this
        whole section shipped asking six RE- profiles for 'Normal'
        when the price list sells every one of them only in 'Std', so
        every profile line read "No product" and nothing could be
        costed.

        The DECISION is `thickness.choose_thickness`, kept Odoo-free so
        `scripts/check_section_seed.py` can run the real rule against
        the real seed data. This method only maps records to names and
        back: a check that reimplemented the rule would agree with
        itself for ever, and the rule disagreeing with the data is
        exactly the bug.
        """
        # This file runs before chawla_attributes_data.xml in the
        # manifest, so on a FRESH install the attribute does not exist
        # yet. Neither caller can reach here in that state (there are no
        # profiles and no section either), but a bare env.ref would be
        # one reordering away from breaking the install.
        attribute = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness',
            raise_if_not_found=False)
        if not (template and attribute):
            return preferred, ''
        options = self.env['aw.profile.section.line']._template_values(
            template, attribute)
        by_name = {value.name: value for value in options}
        chosen, problem = choose_thickness(
            preferred.name if preferred else '', sorted(by_name))
        return (by_name.get(chosen, preferred),
                '%s %s' % (template.name, problem) if problem else '')

    @api.model
    def _fix_dg_openable_thickness(self):
        """One-shot: point the seeded RE lines at a thickness that exists.

        Scoped deliberately -- it only touches lines still carrying the
        seeded 'Normal', and only renames a section still carrying the
        seeded name, so a section somebody has since corrected or
        renamed by hand is left exactly as they left it. Writing
        thickness_id recomputes product_id, which resolves (and creates)
        the right variant and pulls its cost from the rate.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(THICKNESS_FIX_PARAM):
            return False
        param.set_param(THICKNESS_FIX_PARAM, '1')

        sections = self.with_context(active_test=False).search(
            [('name', '=', SECTION_NAME)])
        if not sections:
            return False
        normal = self.env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_normal',
            raise_if_not_found=False)

        changed, warnings = 0, []
        for section in sections:
            for line in section.line_ids:
                if normal and line.thickness_id != normal:
                    continue          # already corrected by hand
                value, warning = self._seed_thickness_for(
                    line.product_tmpl_id, normal)
                if warning:
                    warnings.append(warning)
                if value and value != line.thickness_id:
                    line.thickness_id = value
                    changed += 1
            section.name = SECTION_NAME_FIXED
        _logger.info(
            "aw_fenestration_core: corrected the thickness on %s line(s) "
            "of '%s', now '%s'", changed, SECTION_NAME, SECTION_NAME_FIXED)
        if warnings:
            _logger.warning(
                "aw_fenestration_core: left alone -- %s", '; '.join(warnings))
        return True

    @api.model
    def _sections_by_seed_name(self):
        """The seeded section, under either spelling it has had."""
        return self.with_context(active_test=False).search(
            [('name', 'in', (SECTION_NAME, SECTION_NAME_FIXED))])

    @api.model
    def _seed_lock_bar_line(self):
        """Add the Lock Bar line to the seeded RE set, once.

        Has to look in TWO places, and that is the whole subtlety.
        Phase 7d re-points a section's lines onto its Specification and
        leaves the section empty, so "does this section already have a
        lock bar line?" answers NO on every upgrade after the
        migration -- and this would add a second one, to a section
        nothing reads, for ever. It therefore asks the spec as well,
        and writes wherever the lines actually live.

        Still fill-only-if-absent rather than parameter-guarded: a lock
        bar somebody has already chosen must never be replaced, and
        that is a stronger guarantee than "ran once".
        """
        position = self.env.ref(
            'aw_fenestration_core.pos_lock_bar', raise_if_not_found=False)
        if not position:
            return False
        Spec = self.env['aw.window.template'].with_context(
            active_test=False)
        added = []
        for section in self._sections_by_seed_name():
            specs = Spec.search([('profile_section_id', '=', section.id)])
            existing = (section.line_ids | specs.profile_line_ids).filtered(
                lambda l, p=position: l.position_id == p)
            if existing:
                continue
            template = self._find_profile_template('RE-13')
            if not template:
                _logger.warning(
                    "aw_fenestration_core: no RE-13 to seed as the lock "
                    "bar of '%s'", section.name)
                continue
            thickness, warning = self._seed_thickness_for(
                template,
                self.env.ref(
                    'aw_fenestration_core.aw_attr_val_thickness_standard',
                    raise_if_not_found=False))
            if warning:
                _logger.warning("aw_fenestration_core: %s", warning)
            # The finish the rest of the set already uses, rather than a
            # fresh guess -- the design overrides it anyway, but a line
            # whose finish disagrees with its neighbours looks like a
            # mistake on the form.
            siblings = specs.profile_line_ids or section.line_ids
            finish = siblings[:1].finish_id or self.env.ref(
                'aw_fenestration_core.aw_attr_val_finish_natural',
                raise_if_not_found=False)
            values = {
                'position_id': position.id,
                'product_tmpl_id': template.id,
                'thickness_id': thickness.id if thickness else False,
                'finish_id': finish.id if finish else False,
                'sequence': 150,
            }
            # Where the lines live now: the spec once migrated, the
            # section before that. Exactly one owner either way.
            for spec in specs or [None]:
                self.env['aw.profile.section.line'].create(dict(
                    values,
                    spec_id=spec.id if spec else False,
                    section_id=False if spec else section.id))
            added.append(section.name)
        if added:
            _logger.info(
                "aw_fenestration_core: seeded a Lock Bar line for %s",
                '; '.join(added))
        return bool(added)

    @api.model
    def _seed_dg_openable_spec(self):
        """The RE specification over the RE set, once.

        Seeded WITHOUT a hardware set, deliberately: no hardware list
        exists for this business yet, and a placeholder set would put
        zero hardware into every quote while looking configured. The
        field is optional for exactly this reason, and a design built
        to a spec with no hardware is warned about it once, by the
        checks. The system's own first hardware set is taken if one
        happens to exist, but nothing is invented.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SPEC_SEEDED_PARAM):
            return False

        series = self.env.ref(
            'aw_fenestration_core.%s' % SECTION_SERIES_XMLID,
            raise_if_not_found=False)
        section = self._sections_by_seed_name().filtered(
            lambda s, r=series: s.window_type_id == r)[:1]
        glass = self.env.ref(
            'aw_fenestration_core.%s' % SPEC_GLASS_XMLID,
            raise_if_not_found=False)
        if not (series and section and glass):
            return False

        Spec = self.env['aw.window.template']
        if Spec.with_context(active_test=False).search_count(
                [('name', '=', SPEC_NAME),
                 ('window_type_id', '=', series.id)]):
            param.set_param(SPEC_SEEDED_PARAM, '1')
            return False

        hardware = series.hardware_set_ids[:1]
        if not hardware:
            _logger.info(
                "aw_fenestration_core: '%s' seeded with no Hardware Set "
                "-- none exists yet. Designs built to it will warn that "
                "their hardware cost is missing.", SPEC_NAME)

        Spec.create({
            'name': SPEC_NAME,
            'window_type_id': series.id,
            'profile_section_id': section.id,
            'hardware_set_id': hardware.id if hardware else False,
            'glass_spec_id': glass.id,
            'is_default': not Spec.search_count([
                ('window_type_id', '=', series.id),
                ('is_default', '=', True)]),
            'notes': "Seeded in phase 7c: the RE set plus 24mm DGU.",
        })
        param.set_param(SPEC_SEEDED_PARAM, '1')
        return True

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
        # Either spelling counts as "already there": the section gets
        # renamed by _fix_dg_openable_thickness, and matching only the
        # original name would seed a second copy of it.
        if self.with_context(active_test=False).search_count(
                [('name', 'in', (SECTION_NAME, SECTION_NAME_FIXED)),
                 ('window_type_id', '=', series.id)]):
            param.set_param(SEEDED_PARAM, '1')
            return False

        thickness = self.env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_normal',
            raise_if_not_found=False)
        finish = self.env.ref(
            'aw_fenestration_core.aw_attr_val_finish_natural',
            raise_if_not_found=False)

        lines, missing, thickness_warnings = [], [], []
        sequence = 0
        for position_xmlid, (code, alternates) in SECTION_LINES.items():
            sequence += 10
            position = self.env.ref(
                'aw_fenestration_core.%s' % position_xmlid,
                raise_if_not_found=False)
            if not position:
                missing.append('position %s' % position_xmlid)
                continue
            template = self._find_profile_template(code)
            if not template:
                missing.append('%s (for %s)' % (code, position.name))
                continue
            # An alternate that is not in the price list is dropped and
            # reported, rather than making the whole line fail: the
            # default is what the window is built from, and a missing
            # alternate costs a choice, not a cut list.
            alternate_ids = []
            for other in alternates:
                found = self._find_profile_template(other)
                if found:
                    alternate_ids.append(found.id)
                else:
                    missing.append(
                        '%s (alternate for %s)' % (other, position.name))
            # The preferred thickness is a preference, not a fact
            # about this product -- see _seed_thickness_for.
            line_thickness, warning = self._seed_thickness_for(
                template, thickness)
            if warning:
                thickness_warnings.append(warning)
            lines.append((0, 0, {
                'position_id': position.id,
                'product_tmpl_id': template.id,
                'alternate_product_ids': [(6, 0, alternate_ids)],
                'thickness_id': (
                    line_thickness.id if line_thickness else False),
                'finish_id': finish.id if finish else False,
                'sequence': sequence,
            }))

        if lines:
            self.create({
                'name': SECTION_NAME,
                'window_type_id': series.id,
                'line_ids': lines,
                'notes': "Seeded from the client's Profile 1 breakdown. "
                         "RE-13 is the lock bar (phase 7d).",
            })
        if missing:
            _logger.warning(
                "aw_fenestration_core: '%s' seeded without %s",
                SECTION_NAME, '; '.join(missing))
        if thickness_warnings:
            _logger.warning(
                "aw_fenestration_core: '%s' kept the preferred thickness "
                "on a product that may not be sold in it -- %s",
                SECTION_NAME, '; '.join(thickness_warnings))
        param.set_param(SEEDED_PARAM, '1')
        return True
