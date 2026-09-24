# -*- coding: utf-8 -*-
"""The cutting plan (spec 8, Phase 6c) -- quote stage, unlimited stock.

Pools every profile piece across all the positions on one quote, nests
them into stock bars, and shows what to buy and how to cut it. Stock is
assumed unlimited here; planning against real length lots and offcuts is
P6's stock mode and is not this.

The plan is a SNAPSHOT. It stores the settings it used and a fingerprint
of the BOM it was built from, so a design edited afterwards makes the
plan say "out of date" instead of quietly describing a window that no
longer exists.
"""
import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .cut_algorithm import MM_PER_FOOT, evaluate, scenario_by_key

PARAM_STOCK = 'aw_fenestration.stock_lengths_ft'
PARAM_KERF = 'aw_fenestration.kerf_mm'
PARAM_OFFCUT = 'aw_fenestration.offcut_min_mm'

DEFAULT_STOCK = '14,16,18'
DEFAULT_KERF = 5.0
DEFAULT_OFFCUT = 400.0


class AwCutPlan(models.Model):
    _name = 'aw.cut.plan'
    _description = 'Fenestration Cutting Plan'
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name')
    sale_order_id = fields.Many2one(
        'sale.order', required=True, ondelete='cascade', index=True)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], default='draft', required=True)

    # The settings AS USED, not as they are now. A kerf changed next
    # month must not silently restate what the shop was told to cut.
    stock_lengths_ft = fields.Char(readonly=True)
    kerf_mm = fields.Float(readonly=True)
    offcut_min_mm = fields.Float(readonly=True)

    bom_fingerprint = fields.Char(readonly=True)
    is_current = fields.Boolean(compute='_compute_is_current')

    group_ids = fields.One2many('aw.cut.plan.group', 'plan_id', string='Profiles')
    oversize_note = fields.Text(readonly=True)

    bar_count = fields.Integer(compute='_compute_totals', store=True)
    feet_bought = fields.Float(compute='_compute_totals', store=True)
    feet_used = fields.Float(compute='_compute_totals', store=True)
    yield_pct = fields.Float(compute='_compute_totals', store=True)
    cost_total = fields.Float(compute='_compute_totals', store=True)
    measured_wastage_pct = fields.Float(
        compute='_compute_totals', store=True,
        help="What this plan actually wastes. Compare it with the Price "
             "Structure's assumed profile wastage.")
    assumed_wastage_pct = fields.Float(compute='_compute_totals', store=True)
    currency_id = fields.Many2one(
        related='sale_order_id.currency_id', readonly=True)

    def _compute_name(self):
        for plan in self:
            plan.name = _("Cutting Plan — %s") % (
                plan.sale_order_id.name or '')

    @api.depends('group_ids.bar_count', 'group_ids.feet_bought',
                 'group_ids.feet_used', 'group_ids.cost')
    def _compute_totals(self):
        for plan in self:
            groups = plan.group_ids
            bought = sum(groups.mapped('feet_bought'))
            used = sum(groups.mapped('feet_used'))
            plan.bar_count = sum(groups.mapped('bar_count'))
            plan.feet_bought = bought
            plan.feet_used = used
            plan.yield_pct = (used / bought * 100.0) if bought else 0.0
            plan.cost_total = sum(groups.mapped('cost'))
            # Measured against what the pieces actually need, which is
            # the same base the Price Structure's percentage assumes.
            plan.measured_wastage_pct = (
                (bought - used) / used * 100.0) if used else 0.0
            structure = plan.sale_order_id.aw_design_ids[:1].price_structure_id
            plan.assumed_wastage_pct = structure._values()['profile_wastage']

    @api.depends('bom_fingerprint', 'sale_order_id')
    def _compute_is_current(self):
        for plan in self:
            plan.is_current = bool(plan.bom_fingerprint) and (
                plan.bom_fingerprint == plan._live_fingerprint())

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    @api.model
    def _settings(self):
        param = self.env['ir.config_parameter'].sudo()
        raw = param.get_param(PARAM_STOCK, DEFAULT_STOCK)
        lengths = []
        for token in (raw or '').split(','):
            token = token.strip()
            if not token:
                continue
            try:
                lengths.append(float(token))
            except ValueError:
                continue
        if not lengths:
            lengths = [float(v) for v in DEFAULT_STOCK.split(',')]

        def number(key, fallback):
            try:
                return float(param.get_param(key, fallback))
            except (TypeError, ValueError):
                return fallback

        return {
            'stock_ft': sorted(lengths),
            'kerf': number(PARAM_KERF, DEFAULT_KERF),
            'offcut_min': number(PARAM_OFFCUT, DEFAULT_OFFCUT),
        }

    # ------------------------------------------------------------------
    # what the plan was built from
    # ------------------------------------------------------------------
    def _profile_lines(self):
        """Every profile BOM line on this quote's positions.

        Quantities already include each design's qty -- the explosion
        multiplies by it -- so this must NOT multiply again.
        """
        self.ensure_one()
        designs = self.sale_order_id.aw_design_ids
        return designs.mapped('bom_line_ids').filtered(
            lambda line: line.kind == 'profile')

    def _live_fingerprint(self):
        self.ensure_one()
        settings = self._settings()
        payload = {
            'settings': [settings['stock_ft'], settings['kerf'],
                         settings['offcut_min']],
            'lines': sorted(
                [line.product_id.id, round(line.length_mm or 0.0, 3),
                 line.cut_angle or '', line.qty or 0, line.label or '']
                for line in self._profile_lines()),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------
    def action_generate(self):
        for plan in self:
            plan._generate()
        return True

    def _generate(self):
        self.ensure_one()
        settings = self._settings()
        stock_mm = [ft * MM_PER_FOOT for ft in settings['stock_ft']]

        # Overrides are the estimator's decision, not the algorithm's --
        # keep them across a regeneration.
        overrides = {
            group.product_id.id: group.override_key
            for group in self.group_ids if group.override_key}

        self.group_ids.unlink()

        pooled = {}
        for line in self._profile_lines():
            product = line.product_id
            if not product:
                continue          # reported by the design's own checks
            entry = pooled.setdefault(product.id, {
                'product': product, 'pieces': []})
            for index in range(max(1, line.qty or 1)):
                entry['pieces'].append({
                    'length': round(line.length_mm or 0.0, 2),
                    'label': line.label or '',
                    'angle': line.cut_angle or '',
                    'bom_line_id': line.id,
                    'seq': index,
                })

        oversize_notes = []
        for product_id, entry in pooled.items():
            product = entry['product']
            rate = self._rate_for_product(product)
            result = evaluate(
                entry['pieces'], stock_mm, kerf=settings['kerf'],
                offcut_min=settings['offcut_min'], rate_per_ft=rate)

            group = self.env['aw.cut.plan.group'].create({
                'plan_id': self.id,
                'product_id': product.id,
                'rate_per_ft': rate,
                'chosen_key': result['chosen_key'] or '',
                'override_key': overrides.get(product_id, ''),
            })
            group._store_scenarios(result)
            group._apply_choice(result, settings['offcut_min'])

            for piece in result['oversize']:
                oversize_notes.append(_(
                    "%(label)s on %(product)s is %(len)s mm, longer than "
                    "the longest stock bar. Split it with a coupler — it "
                    "is NOT in the bars below.",
                    label=piece['label'] or '?',
                    product=product.display_name,
                    len=round(piece['length'])))

        self.write({
            'date': fields.Datetime.now(),
            'stock_lengths_ft': ','.join(
                '%g' % ft for ft in settings['stock_ft']),
            'kerf_mm': settings['kerf'],
            'offcut_min_mm': settings['offcut_min'],
            'bom_fingerprint': self._live_fingerprint(),
            'oversize_note': '\n'.join(oversize_notes),
        })

    def _rate_for_product(self, product):
        """Per-foot rate for a variant, on the quote's order date.

        Same lookup the costing uses, so a bar-feet cost and a BOM cost
        can never disagree about the price of the same profile.
        """
        self.ensure_one()
        design = self.sale_order_id.aw_design_ids[:1]
        on_date = design._costing_date() if design \
            else fields.Date.context_today(self)
        template = product.product_tmpl_id
        thickness = finish = self.env['product.attribute.value']
        for value in product.product_template_variant_value_ids:
            attribute = value.attribute_id.name
            if attribute == 'Thickness':
                thickness = value.product_attribute_value_id
            elif attribute == 'Finish':
                finish = value.product_attribute_value_id
        rate = self.env['aw.profile.rate']._rate_for(
            template, thickness, finish, on_date)
        return rate.price if rate else 0.0

    def action_print_cutting_sheet(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cutting_sheet'
        ).report_action(self)

    def action_print_labels(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cut_labels'
        ).report_action(self)


class AwCutPlanGroup(models.Model):
    _name = 'aw.cut.plan.group'
    _description = 'Fenestration Cutting Plan Profile Group'
    _order = 'cost desc, id'

    plan_id = fields.Many2one(
        'aw.cut.plan', required=True, ondelete='cascade', index=True)
    # One group per profile VARIANT: template x thickness x finish is
    # exactly what a product.product is here, so the variant is the key
    # rather than three separate fields to keep in step.
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        string='Profile')
    rate_per_ft = fields.Float(string='Rate / ft')

    chosen_key = fields.Char(
        readonly=True, help="What the algorithm picked.")
    override_key = fields.Char(
        readonly=True, help="What the estimator picked instead.")
    is_overridden = fields.Boolean(compute='_compute_is_overridden')
    active_key = fields.Char(compute='_compute_is_overridden')

    scenario_ids = fields.One2many(
        'aw.cut.plan.scenario', 'group_id', string='Options')
    bar_ids = fields.One2many('aw.cut.plan.bar', 'group_id', string='Bars')

    piece_count = fields.Integer(readonly=True)
    bar_count = fields.Integer(readonly=True)
    bars_summary = fields.Char(readonly=True, string='Bars')
    feet_bought = fields.Float(readonly=True)
    feet_used = fields.Float(readonly=True)
    yield_pct = fields.Float(readonly=True, string='Yield %')
    cost = fields.Float(readonly=True)
    currency_id = fields.Many2one(
        related='plan_id.currency_id', readonly=True)

    @api.depends('override_key', 'chosen_key')
    def _compute_is_overridden(self):
        for group in self:
            group.is_overridden = bool(group.override_key)
            group.active_key = group.override_key or group.chosen_key

    def _evaluate(self):
        """Re-run the algorithm for this group alone."""
        self.ensure_one()
        plan = self.plan_id
        settings = plan._settings()
        stock_mm = [ft * MM_PER_FOOT for ft in settings['stock_ft']]
        pieces = []
        for line in plan._profile_lines():
            if line.product_id != self.product_id:
                continue
            for index in range(max(1, line.qty or 1)):
                pieces.append({
                    'length': round(line.length_mm or 0.0, 2),
                    'label': line.label or '',
                    'angle': line.cut_angle or '',
                    'bom_line_id': line.id,
                    'seq': index,
                })
        return evaluate(pieces, stock_mm, kerf=settings['kerf'],
                        offcut_min=settings['offcut_min'],
                        rate_per_ft=self.rate_per_ft), settings

    def _store_scenarios(self, result):
        self.ensure_one()
        self.scenario_ids.unlink()
        for index, scenario in enumerate(result['scenarios']):
            self.env['aw.cut.plan.scenario'].create({
                'group_id': self.id,
                'sequence': index * 10,
                'key': scenario['key'],
                'name': scenario['label'],
                'feasible': scenario['feasible'],
                'bar_count': scenario['bar_count'],
                'bars_summary': self._summarise_bars(
                    scenario['bars_by_length']),
                'feet_bought': scenario['feet_bought'],
                'feet_used': scenario['feet_used'],
                'waste_feet': scenario['waste_feet'],
                'yield_pct': scenario['yield_pct'],
                'cost': scenario['cost'],
                'blocked_note': (
                    _("No bar of this length can hold a %s mm piece.")
                    % round(scenario['blocked_by'][0])
                    if not scenario['feasible'] and scenario.get('blocked_by')
                    else ''),
            })

    @staticmethod
    def _summarise_bars(bars_by_length):
        if not bars_by_length:
            return ''
        return ', '.join(
            '%s x %g ft' % (count, round(stock_mm / MM_PER_FOOT, 2))
            for stock_mm, count in sorted(bars_by_length.items()))

    def _apply_choice(self, result, offcut_min):
        """Write the bars for whichever option is in force."""
        self.ensure_one()
        self.bar_ids.unlink()
        scenario = scenario_by_key(result, self.active_key)
        if not scenario:
            self.write({'piece_count': 0, 'bar_count': 0, 'bars_summary': '',
                        'feet_bought': 0, 'feet_used': 0, 'yield_pct': 0,
                        'cost': 0})
            return
        for index, bar in enumerate(scenario['bars']):
            record = self.env['aw.cut.plan.bar'].create({
                'group_id': self.id,
                'sequence': (index + 1) * 10,
                'stock_mm': bar['stock_mm'],
                'remainder_mm': bar['remainder'],
                'is_returnable': bar['remainder'] >= offcut_min,
            })
            # Longest cut first: it is how a mitre saw operator works
            # through a bar, and it keeps the offcut in one piece.
            ordered = sorted(bar['cuts'], key=lambda c: -c['length'])
            for position, piece in enumerate(ordered):
                self.env['aw.cut.plan.cut'].create({
                    'bar_id': record.id,
                    'sequence': (position + 1) * 10,
                    'bom_line_id': piece.get('bom_line_id') or False,
                    'label': piece.get('label') or '',
                    'length_mm': piece['length'],
                    'cut_angle': piece.get('angle') or '',
                })
        self.write({
            'piece_count': sum(len(bar['cuts']) for bar in scenario['bars']),
            'bar_count': scenario['bar_count'],
            'bars_summary': self._summarise_bars(scenario['bars_by_length']),
            'feet_bought': scenario['feet_bought'],
            'feet_used': scenario['feet_used'],
            'yield_pct': scenario['yield_pct'],
            'cost': scenario['cost'],
        })

    def action_clear_override(self):
        for group in self:
            group.override_key = ''
            result, settings = group._evaluate()
            group._apply_choice(result, settings['offcut_min'])
        return True


class AwCutPlanScenario(models.Model):
    _name = 'aw.cut.plan.scenario'
    _description = 'Fenestration Cutting Plan Option'
    _order = 'sequence, id'

    group_id = fields.Many2one(
        'aw.cut.plan.group', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    key = fields.Char(required=True)
    name = fields.Char(required=True, string='Option')
    feasible = fields.Boolean(default=True)
    blocked_note = fields.Char()

    bar_count = fields.Integer(string='Bars')
    bars_summary = fields.Char(string='By length')
    feet_bought = fields.Float(string='Feet bought')
    feet_used = fields.Float(string='Feet used')
    waste_feet = fields.Float(string='Waste (ft)')
    yield_pct = fields.Float(string='Yield %')
    cost = fields.Float()
    currency_id = fields.Many2one(
        related='group_id.currency_id', readonly=True)

    is_chosen = fields.Boolean(compute='_compute_is_chosen')

    @api.depends('key', 'group_id.override_key', 'group_id.chosen_key')
    def _compute_is_chosen(self):
        for scenario in self:
            scenario.is_chosen = scenario.key == scenario.group_id.active_key

    def action_use(self):
        """Estimator override: use this option instead."""
        self.ensure_one()
        if not self.feasible:
            raise UserError(_(
                "That option cannot hold every piece in this profile, so "
                "it is not a choice: %s", self.blocked_note or ''))
        group = self.group_id
        # Recorded as an override only when it differs from what the
        # algorithm chose, so "overridden" means what it says.
        group.override_key = (
            '' if self.key == group.chosen_key else self.key)
        result, settings = group._evaluate()
        group._apply_choice(result, settings['offcut_min'])
        return True


class AwCutPlanBar(models.Model):
    _name = 'aw.cut.plan.bar'
    _description = 'Fenestration Cutting Plan Bar'
    _order = 'sequence, id'

    group_id = fields.Many2one(
        'aw.cut.plan.group', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    stock_mm = fields.Float(string='Stock length (mm)')
    stock_label = fields.Char(compute='_compute_labels')
    remainder_mm = fields.Float(string='Remainder (mm)')
    remainder_label = fields.Char(compute='_compute_labels')
    is_returnable = fields.Boolean(
        string='Return to stock',
        help="The remainder is at least the minimum reusable offcut.")
    cut_ids = fields.One2many('aw.cut.plan.cut', 'bar_id', string='Cuts')

    @api.depends('stock_mm', 'remainder_mm')
    def _compute_labels(self):
        design = self.env['aw.design']
        for bar in self:
            bar.stock_label = '%g ft' % round(
                bar.stock_mm / MM_PER_FOOT, 2) if bar.stock_mm else ''
            bar.remainder_label = design._render_length(bar.remainder_mm)


class AwCutPlanCut(models.Model):
    _name = 'aw.cut.plan.cut'
    _description = 'Fenestration Cutting Plan Cut'
    _order = 'sequence, id'

    bar_id = fields.Many2one(
        'aw.cut.plan.bar', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    # set null, not cascade: re-exploding a design replaces its BOM
    # lines, and that must not silently delete cuts from a plan that has
    # already been printed. The plan goes "out of date" instead.
    bom_line_id = fields.Many2one(
        'aw.design.bom.line', ondelete='set null', index=True)
    label = fields.Char(help="e.g. 'D1-P2 sash top'.")
    length_mm = fields.Float(string='Length (mm)')
    length_label = fields.Char(compute='_compute_length_label')
    cut_angle = fields.Selection([
        ('45', '45°'),
        ('90', '90°'),
    ], string='Angle')

    @api.depends('length_mm')
    def _compute_length_label(self):
        design = self.env['aw.design']
        for cut in self:
            cut.length_label = design._render_length(cut.length_mm)
