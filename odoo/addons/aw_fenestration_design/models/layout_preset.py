# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    category = fields.Char(
        help="Groups the preset chips in the configurator, e.g. 'Basic', "
             "'Sliding', 'Stacked'. Free text -- add a category by typing "
             "one, no schema change.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
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
        """Presets are only offered when the design's Series can host
        every leaf type they'd create -- a Fix-only Series shouldn't be
        able to one-click its way to a casement."""
        allowed = set(series.leaf_type_ids.mapped('code'))
        return self.filtered(
            lambda p: p._leaf_type_codes() <= allowed)
