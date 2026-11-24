# -*- coding: utf-8 -*-
"""Size rules: a piece starts from the FINAL length of the piece before it.

One row per series and piece kind: where it starts from (window, frame,
divider, sash side) and an offset in mm. A row does nothing until
`starts_from` is set; with no rows every length is what the spec's formula
gives. Nothing is seeded. The chain itself is `size_chain.py` (Odoo-free).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .size_chain import (
    KIND_BY_GROUP, KIND_LABEL, KINDS, STARTS, allowed_starts, kind_for_group,
    resolve)

MM_PER_INCH = 25.4


class AwSizeRule(models.Model):
    _name = 'aw.size.rule'
    _description = 'Size rule'
    _order = 'series_id, id'

    series_id = fields.Many2one(
        'aw.window.series', required=True, ondelete='cascade', index=True)
    piece_kind = fields.Selection(KINDS, required=True)
    starts_from = fields.Selection(
        STARTS, help="Empty: the rule does nothing and the piece keeps the "
                     "length its spec formula gives.")
    offset_mm = fields.Float(
        string='Offset (mm)', help="Added to the length it starts from; "
                                   "negative makes the piece shorter.")
    offset_in = fields.Float(
        string='Offset (in)', compute='_compute_offset_in',
        inverse='_inverse_offset_in', digits=(16, 3))
    note = fields.Char()
    active = fields.Boolean(default=True)

    @api.depends('offset_mm')
    def _compute_offset_in(self):
        for rule in self:
            rule.offset_in = (rule.offset_mm or 0.0) / MM_PER_INCH

    def _inverse_offset_in(self):
        for rule in self:
            rule.offset_mm = (rule.offset_in or 0.0) * MM_PER_INCH

    @api.constrains('series_id', 'piece_kind')
    def _check_one_per_kind(self):
        for rule in self:
            if self.with_context(active_test=False).search_count([
                    ('series_id', '=', rule.series_id.id),
                    ('piece_kind', '=', rule.piece_kind),
                    ('id', '!=', rule.id)]):
                raise ValidationError(_(
                    "%(series)s already has a size rule for %(kind)s.",
                    series=rule.series_id.display_name,
                    kind=KIND_LABEL[rule.piece_kind]))

    @api.constrains('piece_kind', 'starts_from')
    def _check_starts_before(self):
        for rule in self:
            if rule.starts_from and rule.starts_from not in allowed_starts(
                    rule.piece_kind):
                raise ValidationError(_(
                    "A %(kind)s cannot start from %(start)s: a piece starts "
                    "from one that comes before it in the chain "
                    "(window, frame, divider, sash side).",
                    kind=KIND_LABEL[rule.piece_kind].lower(),
                    start=dict(STARTS)[rule.starts_from].lower()))


class AwDesign(models.Model):
    _inherit = 'aw.design'

    def _size_rules(self):
        """{kind: (starts_from, offset_mm)} of the FILLED rules of this
        window's series. The context key `aw_size_rules` replaces them, which
        is how the Setup page tries values before anything is saved."""
        self.ensure_one()
        override = self.env.context.get('aw_size_rules')
        if override is not None:
            return {kind: (value[0], value[1])
                    for kind, value in override.items()
                    if value and value[0]}
        rows = self.env['aw.size.rule'].search([
            ('series_id', '=', self.window_series_id.id),
            ('starts_from', '!=', False)])
        return {row.piece_kind: (row.starts_from, row.offset_mm)
                for row in rows}

    def _size_rule_pass(self, profiles, keys, adjustments, rules, multiplier):
        """Run the chain over the profile pieces of every unit.

        Returns ({(unit, index): result}, problems): the results of the
        pieces whose rule was applied, and Checks rows (level, text, target)
        for what the rules could not do. Every text starts "Size rule (...)".
        """
        self.ensure_one()
        Position = self.env['aw.profile.position']
        spec = self.template_id
        group_names = dict(Position._fields['part_group'].selection)
        applied, problems, said = {}, [], set()

        def say(level, text, target):
            if text not in said:
                said.add(text)
                problems.append((level, text, target))

        for unit in range(1, multiplier + 1):
            pieces = []
            for index, values in enumerate(profiles, start=1):
                position = Position.browse(values.get('position_id') or 0)
                kind = kind_for_group(position.part_group)
                if not kind and position:
                    say('warning', _(
                        "Size rule (position): '%(position)s' has the part "
                        "group '%(group)s', which is not tied to a size kind "
                        "(frame, divider, sash, bead, lock), so its pieces "
                        "never follow a size rule. Set its Part Group.",
                        position=position.name,
                        group=group_names.get(position.part_group) or _('none')),
                        self._record_target(position))
                key = keys[(unit, index)]
                shift = adjustments.get(key)
                if shift is None:
                    shift = self._adjust_default_mm(
                        values.get('template_line_id'))
                pieces.append({
                    'id': index, 'kind': kind,
                    'orient': values.get('_orient'),
                    'panel_no': values.get('panel_no') or 0,
                    'edge': values.get('_edge') or 0,
                    'length': values.get('length_mm') or 0.0,
                    'shift': shift,
                    'cut_on_site': bool(values.get('cut_on_site'))})
            results = resolve(pieces, rules, self.width_mm or 0.0,
                              self.height_mm or 0.0)
            for index, result in results.items():
                values = profiles[index - 1]
                kind = pieces[index - 1]['kind']
                target = self._target(
                    'piece', values.get('panel_no') or 0, keys[(unit, index)])
                if result['problem']:
                    say('warning', _(
                        "Size rule (%(kind)s): %(problem)s",
                        kind=KIND_LABEL[kind].lower(),
                        problem=result['problem']), target)
                if not result['applied']:
                    continue
                applied[(unit, index)] = result
                if kind == 'divider':
                    vertical = pieces[index - 1]['orient'] == 'v'
                    opening = ((self.height_mm or 0.0)
                               - (spec.frame_deduction_h_mm or 0.0)
                               if vertical else
                               (self.width_mm or 0.0)
                               - (spec.frame_deduction_w_mm or 0.0))
                    if opening > 0 and result['final'] >= opening:
                        say('warning', _(
                            "Size rule (divider): a %(way)s divider would be "
                            "%(length)s long, as long as or longer than the "
                            "frame opening (%(opening)s).",
                            way=_('vertical') if vertical else _('horizontal'),
                            length=self._format_length(result['final']),
                            opening=self._format_length(opening)), target)
        return applied, problems
