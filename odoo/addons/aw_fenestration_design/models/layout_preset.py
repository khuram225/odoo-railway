# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Starting Series assignment for the seeded presets, applied ONCE per
# preset by _seed_default_series(). Keyed by XML id on both sides so it
# doesn't depend on names, which are editable. Presets not listed here --
# including any created in the UI -- are left alone with no Series, i.e.
# offered everywhere their leaf types fit.
DEFAULT_PRESET_SERIES = {
    'layout_preset_casement': ('casement_sg', 'casement_dg'),
    'layout_preset_fix_casement': ('casement_sg', 'casement_dg'),
    'layout_preset_twin_sash': ('casement_sg', 'casement_dg'),
    'layout_preset_hopper_over_fixed': ('casement_sg', 'casement_dg'),
    'layout_preset_two_across_one_below': ('casement_sg', 'casement_dg'),
    'layout_preset_2track_2panel': ('dg_sliding', 'sg_sliding'),
    'layout_preset_2track_fix_slide': ('dg_sliding', 'sg_sliding'),
    'layout_preset_3track_mesh': ('dg_sliding', 'sg_sliding'),
    'layout_preset_fixed': ('dg_fix', 'sg_fix'),
    'layout_preset_stack3': ('curtain_wall_fix',),
    'layout_preset_curtain_wall_vent': ('curtain_wall_fix',),
}


class AwLayoutPreset(models.Model):
    """A reusable starting layout for a design — the row/leaf grid shape
    only, with no absolute sizes. Applying one to a design replaces its
    rows/leaves; the design's own overall width/height then divide up
    according to the relative weights stored here.

    layout_json shape:

        {"rows": [
            {"h": 1, "leaves": [
                {"w": 1, "type": "CASEMENT", "hinge": "left", "swing": "in"},
                {"w": 2, "type": "FIXED"}
            ]},
            {"h": 2, "leaves": [{"w": 1, "type": "FIXED"}]}
        ]}

    "h"/"w" are RELATIVE weights, not millimetres: a row with h=2 next to
    a row with h=1 takes two thirds of the design's height, whatever that
    height happens to be. That's what makes a preset reusable across
    positions of different sizes. "type" is aw.leaf.type.code. "hinge"/
    "swing"/"slide" are optional and only meaningful for leaf types whose
    has_hinge_side / has_slide_dir say so.
    """
    _name = 'aw.layout.preset'
    _description = 'Fenestration Layout Preset'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    # Stable identifier for a preset, independent of its (editable) name.
    # Spec 4.6 seeds the full set in Phase 2; only the presets corrected
    # by _apply_preset_corrections() carry one so far.
    code = fields.Char(
        help="Short stable code, e.g. OPN-CFC. Unlike the name, this is "
             "what other records and documents should refer to.")
    category = fields.Char(
        help="Groups the preset chips in the configurator, e.g. 'Basic', "
             "'Sliding', 'Stacked'. Free text -- add a category by typing "
             "one, no schema change.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    series_ids = fields.Many2many(
        'aw.window.series', string='Window Series',
        help="Offer this preset only on these Series. Leave empty to "
             "offer it on any Series whose leaf types it fits.")
    # A valid single-leaf starter, not an empty {"rows": []}: the
    # constraint below requires a non-empty rows list, so an empty
    # default would make "create preset, save" fail on its own default.
    layout_json = fields.Text(
        required=True,
        default='{"rows": [{"h": 1, "leaves": [{"w": 1, "type": "FIXED"}]}]}')

    @api.constrains('layout_json')
    def _check_layout_json(self):
        """Validated here rather than trusted, because this is a real
        system boundary: layout_json is hand-editable in the config form
        and a malformed one would otherwise only blow up later, inside
        the configurator, as an opaque client-side failure."""
        known_codes = set(
            self.env['aw.leaf.type'].search([]).mapped('code'))
        for preset in self:
            try:
                data = json.loads(preset.layout_json or '')
            except ValueError as exc:
                raise ValidationError(_(
                    "Layout of '%(name)s' is not valid JSON: %(error)s",
                    name=preset.name, error=exc))
            rows = data.get('rows') if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                raise ValidationError(_(
                    "Layout of '%s' needs a non-empty \"rows\" list.",
                    preset.name))
            for row in rows:
                leaves = row.get('leaves') if isinstance(row, dict) else None
                if not isinstance(leaves, list) or not leaves:
                    raise ValidationError(_(
                        "Every row in '%s' needs a non-empty \"leaves\" "
                        "list.", preset.name))
                for leaf in leaves:
                    code = leaf.get('type') if isinstance(leaf, dict) else None
                    if code not in known_codes:
                        raise ValidationError(_(
                            "Layout of '%(name)s' uses unknown leaf type "
                            "code %(code)r. Known codes: %(known)s",
                            name=preset.name, code=code,
                            known=', '.join(sorted(known_codes))))

    def _layout(self):
        self.ensure_one()
        return json.loads(self.layout_json)

    def _leaf_type_codes(self):
        """Every distinct leaf type code this preset would create."""
        self.ensure_one()
        return {
            leaf.get('type')
            for row in self._layout()['rows']
            for leaf in row['leaves']
        }

    def _allowed_for_series(self, series):
        """Two conditions, both required.

        series_ids, when set, is the explicit statement of intent: this
        preset belongs to these Series. Empty means "anywhere it fits".

        Leaf-type compatibility stays as the backstop -- a Fix-only
        Series shouldn't be able to one-click its way to a casement even
        if someone mis-assigns a Series. It is necessary but NOT
        sufficient on its own, which was the bug this fixes: every
        all-FIXED preset ("Fixed", "3-tier fixed stack") passed the leaf
        check on all 8 Series, so a curtain-wall layout was offered on
        sliding Series. Leaf types can't express category intent.
        """
        return self.filtered(
            lambda p: (not p.series_ids or series in p.series_ids)
            and p._leaf_type_codes() <= set(
                series.leaf_type_ids.mapped('code')))

    # One-off corrections to seeded presets, keyed by XML id:
    # (name it was seeded with, name it should have, code).
    PRESET_CORRECTIONS = {
        'layout_preset_twin_sash': (
            'Twin Sash: case+fix+case',
            'Casement + Fixed + Casement',
            'OPN-CFC',
        ),
    }

    @api.model
    def _apply_preset_corrections(self):
        """Fix names and fill codes on seeded presets, once.

        The seed file is noupdate="1", so editing a record there only
        affects fresh installs and would never reach a database where the
        preset already exists -- which is all of them.

        The guard here is "only if it still has the name it was seeded
        with", rather than the fill-only-if-empty used elsewhere, because
        a name is never empty. Same intent: a preset someone has renamed
        in the UI is left alone. The code is filled only when empty, since
        that one can use the usual rule.
        """
        for xmlid, (old_name, new_name, code) in self.PRESET_CORRECTIONS.items():
            preset = self.env.ref(
                'aw_fenestration_design.%s' % xmlid, raise_if_not_found=False)
            if not preset:
                continue
            values = {}
            if preset.name == old_name:
                values['name'] = new_name
            if not preset.code:
                values['code'] = code
            if values:
                preset.write(values)

    @api.model
    def _seed_default_series(self):
        """Assign each seeded preset its starting Series, once.

        Same shape, and same reasoning, as
        aw.window.series._seed_default_leaf_types(): a preset that
        already has Series is skipped, so an upgrade never overwrites a
        UI edit. Presets absent from the mapping -- anything created in
        the UI -- are never touched at all.

        Same caveat too: deliberately clearing a preset's Series back to
        "any Series" is not a stable state, because empty is exactly the
        signal this uses for "never assigned", so the next upgrade
        refills it. Archive the preset instead if it shouldn't be
        offered.
        """
        for preset_xmlid, series_keys in DEFAULT_PRESET_SERIES.items():
            preset = self.env.ref(
                'aw_fenestration_design.%s' % preset_xmlid,
                raise_if_not_found=False)
            if not preset or preset.series_ids:
                continue
            ids = []
            for key in series_keys:
                series = self.env.ref(
                    'aw_fenestration_core.window_series_%s' % key,
                    raise_if_not_found=False)
                if series:
                    ids.append(series.id)
            if ids:
                preset.series_ids = [(6, 0, ids)]
