# -*- coding: utf-8 -*-
"""The Setup page for size rules: a list per series, one line per piece kind,
and a sample window to try values on before anything is saved.

The sample is a scratch quote and window made inside a savepoint that is
always rolled back, exploded with the lines AS TYPED (context
`aw_size_rules`), so it shows what a real window would get and writes
nothing. Saving writes `aw.size.rule` rows for the lines that are filled and
removes the row of a line that was cleared.
"""
from contextlib import closing

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .family import OPENING_LEAF_CODES
from .size_chain import KIND_BY_GROUP, KIND_LABEL, KINDS, STARTS, allowed_starts

MM_PER_INCH = 25.4


class AwSizeRuleSetup(models.TransientModel):
    _name = 'aw.size.rule.setup'
    _description = 'Size rules setup'

    series_id = fields.Many2one('aw.window.series', required=True)
    line_ids = fields.One2many('aw.size.rule.setup.line', 'setup_id')
    series_leaf_type_ids = fields.Many2many(
        related='series_id.leaf_type_ids')
    sample_width_in = fields.Float(
        string='Sample width (in)', default=96.0, digits=(16, 2))
    sample_height_in = fields.Float(
        string='Sample height (in)', default=60.0, digits=(16, 2))
    panels_across = fields.Integer(string='Panels across', default=1)
    leaf_type_id = fields.Many2one(
        'aw.leaf.type', string='Panel type',
        help="What every panel of the sample window is.")
    warnings = fields.Text(readonly=True)
    sample_note = fields.Char(readonly=True)

    # -- loading -------------------------------------------------------------
    def _line_commands(self):
        """One line per piece kind, filled from the series' saved rules."""
        self.ensure_one()
        saved = {r.piece_kind: r for r in self.env['aw.size.rule'].search(
            [('series_id', '=', self.series_id.id)])}
        commands = [(5, 0, 0)]
        for kind, _label in KINDS:
            rule = saved.get(kind)
            commands.append((0, 0, {
                'kind': kind,
                'starts_from': rule.starts_from if rule else False,
                'offset_mm': rule.offset_mm if rule else 0.0,
                'note': rule.note if rule else False}))
        return commands

    def _default_leaf_type(self):
        types = self.series_id.leaf_type_ids
        return (types.filtered(lambda t: t.code in OPENING_LEAF_CODES)[:1]
                or types[:1])

    @api.onchange('series_id')
    def _onchange_series_id(self):
        if self.series_id:
            self.line_ids = self._line_commands()
            self.leaf_type_id = self._default_leaf_type()
        else:
            self.line_ids = [(5, 0, 0)]

    def action_load(self):
        """Fill the lines from the saved rules (for code and tests; the form
        does the same through the onchange)."""
        self.ensure_one()
        self.write({'line_ids': self._line_commands(),
                    'leaf_type_id': self._default_leaf_type().id})
        return True

    # -- the sample ---------------------------------------------------------
    def _typed_rules(self):
        rules = {}
        for line in self.line_ids:
            if line.starts_from:
                if line.starts_from not in allowed_starts(line.kind):
                    raise UserError(_(
                        "A %(kind)s cannot start from %(start)s: it starts "
                        "from a piece that comes before it (window, frame, "
                        "divider, sash side).",
                        kind=KIND_LABEL[line.kind].lower(),
                        start=dict(STARTS)[line.starts_from].lower()))
                rules[line.kind] = (line.starts_from, line.offset_mm)
        return rules

    def _sample(self, rules):
        """({kind: {'lengths', 'count', 'note'}}, [warnings]) of the sample
        window exploded with `rules`. Everything is rolled back."""
        self.ensure_one()
        series = self.series_id
        count = max(1, int(self.panels_across or 1))
        width = (self.sample_width_in or 0.0) * MM_PER_INCH
        height = (self.sample_height_in or 0.0) * MM_PER_INCH
        if width <= 0 or height <= 0:
            raise UserError(_("Give the sample a width and a height."))
        leaf_type = self.leaf_type_id or self._default_leaf_type()
        if not leaf_type:
            raise UserError(_("%s has no panel type to try.",
                              series.display_name))
        found, warnings = {}, []
        with closing(self.env.cr.savepoint()):
            order = self.env['sale.order'].sudo().create({
                'partner_id': self.env.company.partner_id.id,
                'aw_default_series_id': series.id})
            design = order._create_fenestration_position(
                series, location=_('Sample'))
            design.write({'width_mm': width, 'height_mm': height})
            leaf = {'width_mm': width / count, 'leaf_type_id': leaf_type.id}
            design = design.with_context(aw_size_rules=rules)
            design.save_layout({
                'header': design.get_configurator_data()['header'],
                'rows': [{'height_mm': height,
                          'leaves': [dict(leaf) for _i in range(count)]}]})
            self.env.flush_all()
            for bom in design.bom_line_ids.filtered(
                    lambda l: l.kind == 'profile' and l.template_line_id):
                kind = KIND_BY_GROUP.get(
                    bom.template_line_id.position_id.part_group)
                if not kind:
                    continue
                entry = found.setdefault(
                    kind, {'lengths': [], 'count': 0, 'note': ''})
                entry['count'] += 1
                entry['lengths'].append(round(bom.length_mm or 0.0, 1))
                if not entry['note'] and bom.calc_rule == _('Size rule'):
                    entry['note'] = bom.calc_source or ''
            warnings = [c.message for c in design.check_line_ids
                        if (c.message or '').startswith('Size rule')]
        self.env.invalidate_all()
        return found, warnings

    @staticmethod
    def _length_text(entry):
        if not entry or not entry['count']:
            return _("no such piece on the sample")
        seen = sorted(set(entry['lengths']), reverse=True)
        text = ' / '.join(
            "%s in (%s mm)" % (('%.2f' % (mm / MM_PER_INCH)).rstrip('0')
                               .rstrip('.'), ('%.1f' % mm).rstrip('0')
                               .rstrip('.')) for mm in seen)
        return "%s x %s" % (text, entry['count'])

    def action_preview(self):
        """Try the lines as typed on the sample window. Writes nothing."""
        self.ensure_one()
        found, warnings = self._sample(self._typed_rules())
        for line in self.line_ids:
            entry = found.get(line.kind)
            line.write({
                'sample_text': self._length_text(entry),
                'sample_source': (entry or {}).get('note') or '',
                'warning': ' '.join(
                    w for w in warnings
                    if w.startswith('Size rule (%s)' % KIND_LABEL[
                        line.kind].lower()))})
        self.write({
            'warnings': '\n'.join(warnings) or False,
            'sample_note': _(
                "%(w)s x %(h)s in, %(n)s panel(s) across, %(type)s. Nothing "
                "was saved.",
                w=self.sample_width_in, h=self.sample_height_in,
                n=max(1, self.panels_across or 1),
                type=(self.leaf_type_id or self._default_leaf_type()
                      ).display_name or '')})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window', 'name': _("Size Rules"),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'current'}

    # -- saving --------------------------------------------------------------
    def action_save(self):
        """Write a rule for every line that is filled; remove the rule of a
        line that was cleared."""
        self.ensure_one()
        rules = self._typed_rules()
        Rule = self.env['aw.size.rule'].with_context(active_test=False)
        saved = {r.piece_kind: r for r in Rule.search(
            [('series_id', '=', self.series_id.id)])}
        changes = []
        for line in self.line_ids:
            row = saved.get(line.kind)
            if line.kind in rules:
                values = {'starts_from': line.starts_from,
                          'offset_mm': line.offset_mm,
                          'note': line.note or False, 'active': True}
                if row:
                    if any(row[k] != v for k, v in values.items()):
                        row.write(values)
                        changes.append(line.kind)
                else:
                    Rule.create(dict(values, series_id=self.series_id.id,
                                     piece_kind=line.kind))
                    changes.append(line.kind)
            elif row:
                row.unlink()
                changes.append(line.kind)
        if changes:
            self.series_id.message_post(body=_(
                "%(who)s changed the size rules of: %(kinds)s. Windows pick "
                "a rule up the next time they are recomputed.",
                who=self.env.user.name,
                kinds=', '.join(KIND_LABEL[k] for k in changes)))
        return self._reopen()


class AwSizeRuleSetupLine(models.TransientModel):
    _name = 'aw.size.rule.setup.line'
    _description = 'Size rules setup line'
    _order = 'id'

    setup_id = fields.Many2one(
        'aw.size.rule.setup', required=True, ondelete='cascade')
    kind = fields.Selection(KINDS, string='Piece', required=True)
    starts_from = fields.Selection(STARTS, string='Starts from')
    offset_mm = fields.Float(string='Offset (mm)')
    offset_in = fields.Float(
        string='Offset (in)', compute='_compute_offset_in',
        inverse='_inverse_offset_in', digits=(16, 3))
    note = fields.Char()
    sample_text = fields.Char(string='Length on the sample', readonly=True)
    sample_source = fields.Char(string='Worked out from', readonly=True)
    warning = fields.Char(readonly=True)

    @api.depends('offset_mm')
    def _compute_offset_in(self):
        for line in self:
            line.offset_in = (line.offset_mm or 0.0) / MM_PER_INCH

    def _inverse_offset_in(self):
        for line in self:
            line.offset_mm = (line.offset_in or 0.0) * MM_PER_INCH
