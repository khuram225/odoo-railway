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
import time
from urllib.parse import urlencode

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .cut_algorithm import (
    MM_PER_FOOT, evaluate, pack_into_stock, scenario_by_key, solve,
)

PARAM_STOCK = 'aw_fenestration.stock_lengths_ft'
PARAM_KERF = 'aw_fenestration.kerf_mm'
PARAM_OFFCUT = 'aw_fenestration.offcut_min_mm'
PARAM_TRIM = 'aw_fenestration.start_trim_mm'
PARAM_MARGIN = 'aw_fenestration.safety_margin_mm'
PARAM_BUDGET = 'aw_fenestration.solve_budget_s'

# Precut label sheet. Defined in models/res_config_settings.py, which
# also owns the A4 sheet constants.
from .res_config_settings import SHEET_H, SHEET_W  # noqa: E402

LABEL_P = 'aw_fenestration.label_'

DEFAULT_STOCK = '14,16,18'
DEFAULT_KERF = 5.0
DEFAULT_OFFCUT = 400.0
# Start trim defaults to 0 on purpose: nobody has measured what the saw
# wastes squaring a bar end here, and an invented figure would shorten
# every bar in the shop silently. 25 mm safety margin is the agreed one.
DEFAULT_TRIM = 0.0
DEFAULT_MARGIN = 25.0
# Per profile group. The 31-window DG-26 job solves in about 9 s, so 20
# gives real jobs room while stopping a pathological one from holding a
# request open.
DEFAULT_BUDGET = 20.0


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
        ('confirmed', 'Final'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True)
    # Final = the bars were bought for this batch (a button for now; with
    # purchasing it will follow the PO). A Final batch is locked.
    bought_on = fields.Datetime(readonly=True, copy=False)
    bought_by = fields.Many2one('res.users', readonly=True, copy=False)
    # Stock = what earlier Final batches of the quote left on their bars (an
    # offcut above the minimum setting). Planning uses it before it buys a
    # bar. A Final batch must have been planned from stock, unless a manager
    # ticks Plan without stock and says why.
    plan_without_stock = fields.Boolean(copy=False)
    no_stock_reason = fields.Text(copy=False)
    stock_planned = fields.Boolean(readonly=True, copy=False)
    stock_bars_used = fields.Integer(compute='_compute_stock_bars_used')
    # A batch is a cutting plan: the windows ticked when it was made. A
    # window is in ONE active (not cancelled) batch only, and moves only
    # while the batch is Draft.
    batch_no = fields.Integer(readonly=True, copy=False)
    design_ids = fields.Many2many(
        'aw.design', 'aw_cut_plan_design_rel', 'plan_id', 'design_id',
        string='Windows')
    window_count = fields.Integer(compute='_compute_window_count')

    # The settings AS USED, not as they are now. A kerf changed next
    # month must not silently restate what the shop was told to cut.
    stock_lengths_ft = fields.Char(readonly=True)
    profile_vendor_id = fields.Many2one(
        'res.partner', string='Profile vendor', readonly=True)
    solve_budget_s = fields.Float(readonly=True)
    kerf_mm = fields.Float(readonly=True)
    offcut_min_mm = fields.Float(readonly=True)
    start_trim_mm = fields.Float(readonly=True)
    safety_margin_mm = fields.Float(readonly=True)
    max_piece_mm = fields.Float(
        readonly=True, string='Longest cuttable piece',
        help="Longest bar less start trim, safety margin and one saw "
             "cut. Nothing longer can be made: pieces are never joined.")

    # How good the answer is, stated rather than implied. "Optimal"
    # means the integer solution matched the LP lower bound, not that
    # the optimiser is pleased with itself.
    optimality = fields.Selection([
        ('optimal', 'Proven optimal'),
        ('gap', 'Near optimal'),
        ('greedy', 'Approximate (no solver)'),
    ], readonly=True)
    optimality_note = fields.Char(readonly=True)

    bom_fingerprint = fields.Char(readonly=True)
    is_current = fields.Boolean(compute='_compute_is_current')

    group_ids = fields.One2many('aw.cut.plan.group', 'plan_id', string='Profiles')
    oversize_note = fields.Text(readonly=True)
    blocked_note = fields.Text(readonly=True)

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
            plan.name = _("Batch %(no)s — %(order)s",
                          no=plan.batch_no or 1,
                          order=plan.sale_order_id.name or '')

    def _compute_stock_bars_used(self):
        for plan in self:
            plan.stock_bars_used = len(
                plan.group_ids.bar_ids.filtered('from_bar_id'))

    def _stock_for(self, product):
        """The offcuts of earlier Final batches of this quote that this
        batch may use for `product`: returnable (above the minimum), and not
        already taken by another active batch (a Draft one has reserved it)."""
        self.ensure_one()
        Bar = self.env['aw.cut.plan.bar']
        if self.plan_without_stock:
            return Bar
        others = self.search([
            ('sale_order_id', '=', self.sale_order_id.id),
            ('id', '!=', self.id), ('state', '=', 'confirmed')])
        bars = others.group_ids.filtered(
            lambda g: g.product_id == product).bar_ids.filtered(
            lambda b: b.is_returnable and b.remainder_mm > 0)
        taken = Bar.search([
            ('from_bar_id', 'in', bars.ids),
            ('group_id.plan_id', '!=', self.id),
            ('group_id.plan_id.state', '!=', 'cancel')]).from_bar_id
        return (bars - taken).sorted('id')

    @api.depends('design_ids')
    def _compute_window_count(self):
        for plan in self:
            plan.window_count = len(plan.design_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('batch_no') and vals.get('sale_order_id'):
                last = self.with_context(active_test=False).search(
                    [('sale_order_id', '=', vals['sale_order_id'])],
                    order='batch_no desc', limit=1)
                vals['batch_no'] = (last.batch_no or 0) + 1
        return super().create(vals_list)

    def write(self, vals):
        if (vals.get('plan_without_stock') or vals.get('no_stock_reason')) \
                and not self.env.user.has_group(
                    'aw_fenestration_core.group_fenestration_manager'):
            raise UserError(_(
                "Only a Fenestration manager can plan without stock."))
        if 'design_ids' in vals and not self.env.context.get(
                'aw_batch_backfill'):
            locked = self.filtered(lambda p: p.state != 'draft')
            if locked:
                raise UserError(_(
                    "Windows can only move while the batch is Draft."))
        return super().write(vals)

    @api.constrains('design_ids', 'state')
    def _check_windows(self):
        for plan in self.filtered(lambda p: p.state != 'cancel'):
            foreign = plan.design_ids.filtered(
                lambda d: d.sale_order_id != plan.sale_order_id)
            if foreign:
                raise ValidationError(_(
                    "%s is not a window of this quote.",
                    ', '.join(foreign.mapped('display_name'))))
            clash = self.search([
                ('id', '!=', plan.id), ('state', '!=', 'cancel'),
                ('design_ids', 'in', plan.design_ids.ids)])
            if clash:
                shared = clash.mapped('design_ids') & plan.design_ids
                raise ValidationError(_(
                    "%(windows)s already in %(batch)s. A window is in one "
                    "batch only; take it out of that batch first (while "
                    "it is Draft).",
                    windows=', '.join(shared.mapped('display_name')),
                    batch=', '.join(clash.mapped('name'))))

    def _ensure_draft(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_(
                    "%(batch)s is %(state)s: the bars are bought, so it "
                    "cannot change.", batch=plan.name,
                    state=dict(self._fields['state'].selection)[
                        plan.state].lower()))

    def action_mark_bought(self):
        """The bars of this batch were bought: it becomes Final and is
        locked. Only an up-to-date batch where every piece is on a bar and
        every profile was planned can be bought, so what was bought is what
        the shop cuts."""
        self.ensure_one()
        self._ensure_draft()
        if not self.group_ids:
            raise UserError(_("Nothing is planned in this batch yet."))
        if not self.is_current:
            raise UserError(_(
                "This batch is out of date. Regenerate it before marking "
                "the bars bought."))
        if self.oversize_note or self.blocked_note:
            raise UserError(_(
                "Some pieces are not on a bar, or a profile was not "
                "planned (see the notes on the batch). Fix that first."))
        if self.plan_without_stock:
            if not (self.no_stock_reason or '').strip():
                raise UserError(_(
                    "This batch is planned without stock: say why before "
                    "marking the bars bought."))
        elif not self.stock_planned:
            raise UserError(_(
                "Re-plan this batch from stock before marking the bars "
                "bought."))
        self.write({'state': 'confirmed',
                    'bought_on': fields.Datetime.now(),
                    'bought_by': self.env.user.id})
        self.sale_order_id.message_post(body=_(
            "%(who)s marked the bars bought for %(batch)s: %(bars)s bars, "
            "%(feet).0f ft.", who=self.env.user.name, batch=self.name,
            bars=self.bar_count, feet=self.feet_bought))
        return True

    def _ensure_nothing_uses_my_offcuts(self):
        """A batch whose offcuts another active batch is cutting from cannot
        be reopened: its bars would change under that batch."""
        self.ensure_one()
        users = self.env['aw.cut.plan.bar'].search([
            ('from_bar_id', 'in', self.group_ids.bar_ids.ids),
            ('group_id.plan_id.state', '!=', 'cancel')]).group_id.plan_id
        if users:
            raise UserError(_(
                "%(users)s cuts from the offcuts of this batch. Cancel or "
                "reopen that batch first.",
                users=', '.join(users.mapped('name'))))

    def action_reopen_batch(self):
        """Ask why, then (aw.cut.reopen.wizard) turn a Final batch back to
        Draft. Fenestration managers only, checked again by the wizard."""
        self.ensure_one()
        if not self.env.user.has_group(
                'aw_fenestration_core.group_fenestration_manager'):
            raise UserError(_("Only a Fenestration manager can reopen a batch."))
        if self.state != 'confirmed':
            raise UserError(_("Only a Final batch can be reopened."))
        self._ensure_nothing_uses_my_offcuts()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reopen batch"),
            'res_model': 'aw.cut.reopen.wizard',
            'view_mode': 'form',
            'views': [(self.env.ref(
                'aw_fenestration_design.view_aw_cut_reopen_wizard_form'
            ).id, 'form')],
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def action_cancel_batch(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_("Only a Draft batch can be cancelled."))
            plan.state = 'cancel'
            plan.sale_order_id.message_post(body=_(
                "%(who)s cancelled %(batch)s; its %(count)s window(s) are "
                "free for another batch.", who=self.env.user.name,
                batch=plan.name, count=len(plan.design_ids)))
        return True

    def action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'aw.cut.plan',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
        }

    @api.model
    def _backfill_batches(self):
        """Once: every plan made before batches existed gets the windows of
        its quote (that is what it was planned from), and a batch number in
        the order the plans were made. Never run again: a batch emptied by
        hand must stay empty."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param('aw_fenestration.batches_backfilled'):
            return 0
        plans = self.with_context(active_test=False).search(
            [], order='sale_order_id, id')
        counter, done = {}, 0
        for plan in plans:
            order = plan.sale_order_id
            counter[order.id] = counter.get(order.id, 0) + 1
            values = {}
            if not plan.batch_no:
                values['batch_no'] = counter[order.id]
            if not plan.design_ids and plan.state != 'cancel':
                taken = self.search([
                    ('sale_order_id', '=', order.id),
                    ('state', '!=', 'cancel'), ('id', '!=', plan.id)
                ]).design_ids
                values['design_ids'] = [
                    (6, 0, (order.aw_design_ids - taken).ids)]
            if values:
                plan.with_context(aw_batch_backfill=True).write(values)
                done += 1
        param.set_param('aw_fenestration.batches_backfilled', '1')
        return done


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
            structure = (plan.design_ids
                         or plan.sale_order_id.aw_design_ids)[:1].price_structure_id
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
    def _settings(self, vendor=None, strict=False, template=None):
        """The planning settings. Bar lengths are the VENDOR's when it has
        any listed (aw.vendor.bar.length), else the global list. Only
        ACTIVE lengths count, and for a profile TEMPLATE its own rows win
        over the vendor-wide ones. strict=True (generating a plan) stops for a
        vendor whose lengths are all switched off; the fingerprint and the
        piece limit do not stop, they fall back to the global list."""
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
        lengths = (self.env['aw.vendor.bar.length']._lengths_for(vendor, strict, template)
                   or lengths)

        def number(key, fallback):
            try:
                return float(param.get_param(key, fallback))
            except (TypeError, ValueError):
                return fallback

        return {
            'stock_ft': sorted(lengths),
            'kerf': number(PARAM_KERF, DEFAULT_KERF),
            'offcut_min': number(PARAM_OFFCUT, DEFAULT_OFFCUT),
            'start_trim': number(PARAM_TRIM, DEFAULT_TRIM),
            'safety_margin': number(PARAM_MARGIN, DEFAULT_MARGIN),
            'budget': number(PARAM_BUDGET, DEFAULT_BUDGET),
        }

    # ------------------------------------------------------------------
    # what the plan was built from
    # ------------------------------------------------------------------
    def _profile_lines(self):
        """Every profile BOM line of the windows in THIS batch.

        Quantities already include each design's qty -- the explosion
        multiplies by it -- so this must NOT multiply again.
        """
        self.ensure_one()
        designs = self.design_ids
        # A piece cut on site has no length and no place on a bar.
        return designs.mapped('bom_line_ids').filtered(
            lambda line: line.kind == 'profile' and not line.cut_on_site)

    def _live_fingerprint(self):
        self.ensure_one()
        settings = self._settings(self.sale_order_id.aw_profile_vendor_id)
        payload = {
            'settings': [settings['stock_ft'], settings['kerf'],
                         settings['offcut_min'], settings['start_trim'],
                         settings['safety_margin']],
            'lines': sorted(
                [line.product_id.id, round(line.length_mm or 0.0, 3),
                 line.cut_angle or '', line.qty or 0, line.label or '']
                for line in self._profile_lines()),
        }
        # Only the profiles whose lengths differ from the vendor's, so a
        # quote with no per-profile rows keeps the fingerprint it had.
        vendor = self.sale_order_id.aw_profile_vendor_id
        by_profile = {}
        for template in self._profile_lines().mapped(
                'product_id.product_tmpl_id'):
            lengths = self._settings(vendor, template=template)['stock_ft']
            if lengths != settings['stock_ft']:
                by_profile[str(template.id)] = lengths
        if by_profile:
            payload['by_profile'] = by_profile
        # A partial batch goes stale when its windows change. A batch that
        # holds every window keeps the fingerprint it had before batches.
        if self.design_ids != self.sale_order_id.aw_design_ids:
            payload['windows'] = sorted(self.design_ids.ids)
        blob = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------
    def action_generate(self):
        self._ensure_draft()
        for plan in self:
            plan._generate()
        return True

    def _generate(self):
        self.ensure_one()
        vendor = self.sale_order_id.aw_profile_vendor_id
        settings = self._settings(vendor)

        # Overrides are the estimator's decision, not the algorithm's --
        # keep them across a regeneration.
        overrides = {
            group.product_id.id: group.override_key
            for group in self.group_ids if group.override_key}
        # Everything already solved, by product, so an unchanged group
        # can be left exactly as it is.
        existing = {group.product_id.id: group for group in self.group_ids}

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
                    'ref': line.piece_ref or '',
                    'angle': line.cut_angle or '45',
                    'bom_line_id': line.id,
                    'seq': index,
                })

        if not pooled:
            self._settings(vendor, strict=True)     # nothing to plan, but
            # a vendor with every bar length switched off still stops here
        oversize_notes = []
        blocked = []
        planned = 0
        methods, gap_feet, all_proven = set(), 0.0, True
        reused = 0
        for product_id, entry in pooled.items():
            product = entry['product']
            # Each profile group plans with ITS lengths: the profile's own
            # rows, else the vendor's, else the global list. A profile whose
            # own rows are all off stops alone; the others still plan.
            try:
                group_settings = self._settings(
                    vendor, strict=True, template=product.product_tmpl_id)
            except UserError as error:
                if str(error) not in blocked:
                    blocked.append(str(error))
                continue
            stock_mm = [ft * MM_PER_FOOT for ft in group_settings['stock_ft']]
            rate, rate_date = self._rate_for_product(product)
            stock = self._stock_for(product)
            fingerprint = self._group_fingerprint(
                entry['pieces'], group_settings, rate,
                stock=[(bar.id, round(bar.remainder_mm, 2)) for bar in stock])
            stock_bars, to_buy = pack_into_stock(
                entry['pieces'],
                [(bar.id, bar.remainder_mm) for bar in stock],
                kerf=settings['kerf'], start_trim=settings['start_trim'])

            # Nothing about this profile moved, so re-solving it would
            # spend the budget to arrive back where it already is.
            previous = existing.pop(product_id, None)
            if (previous and previous.piece_fingerprint == fingerprint
                    and previous.bar_ids):
                reused += 1
                planned += 1
                previous.rate_date = rate_date or False
                methods.add(previous.solve_method or 'exact')
                gap_feet += previous.gap_feet or 0.0
                all_proven = all_proven and previous.proven_optimal
                continue

            if to_buy:
                result = evaluate(
                    to_buy, stock_mm, kerf=settings['kerf'],
                    offcut_min=settings['offcut_min'], rate_per_ft=rate,
                    start_trim=settings['start_trim'],
                    safety_margin=settings['safety_margin'],
                    time_budget=settings['budget'])
            else:          # every piece found an offcut: nothing to buy
                result = {'scenarios': [], 'oversize': [],
                          'chosen_key': None, 'method': 'stock',
                          'proven_optimal': True, 'gap_feet': 0.0}

            if previous:
                previous.unlink()
            group = self.env['aw.cut.plan.group'].create({
                'plan_id': self.id,
                'product_id': product.id,
                'rate_per_ft': rate,
                'rate_date': rate_date or False,
                'piece_fingerprint': fingerprint,
                'chosen_key': result['chosen_key'] or '',
                'override_key': overrides.get(product_id, ''),
                'solve_method': result.get('method') or 'none',
                'gap_feet': result.get('gap_feet') or 0.0,
                'proven_optimal': bool(result.get('proven_optimal')),
            })
            planned += 1
            methods.add(result.get('method') or 'none')
            gap_feet += result.get('gap_feet') or 0.0
            all_proven = all_proven and bool(result.get('proven_optimal'))

            group._store_scenarios(result)
            group._apply_choice(result, settings['offcut_min'])
            group._add_stock_bars(stock_bars, settings['offcut_min'])

            for piece in result['oversize']:
                oversize_notes.append(_(
                    "%(label)s on %(product)s is %(len)s mm, longer than "
                    "any bar can cut. Pieces are never joined, so this "
                    "position must be resized — it is NOT in the bars "
                    "below.",
                    label=piece['label'] or '?',
                    product=product.display_name,
                    len=round(piece['length'])))

        if blocked and not planned:
            raise UserError('\n'.join(blocked))

        # Whatever is left in `existing` is a profile the BOM no longer
        # uses (or one that was just blocked).
        for stale in existing.values():
            stale.unlink()

        if 'greedy' in methods:
            optimality = 'greedy'
            optimality_note = _(
                "No LP solver on this server, so the bars were packed "
                "greedily. The result is valid but not proven cheapest.")
        elif all_proven:
            optimality = 'optimal'
            optimality_note = _("Proven optimal: no cheaper set of bars "
                                "exists for these pieces.")
        else:
            optimality = 'gap'
            optimality_note = _(
                "Within %.2f ft of optimal.") % gap_feet

        self.write({
            'date': fields.Datetime.now(),
            'profile_vendor_id': vendor.id or False,
            'stock_lengths_ft': ','.join(
                '%g' % ft for ft in settings['stock_ft']),
            'kerf_mm': settings['kerf'],
            'offcut_min_mm': settings['offcut_min'],
            'start_trim_mm': settings['start_trim'],
            'safety_margin_mm': settings['safety_margin'],
            'solve_budget_s': settings['budget'],
            'max_piece_mm': self.env['aw.design']._max_piece_mm(
                self.sale_order_id.aw_profile_vendor_id),
            'optimality': optimality,
            'optimality_note': optimality_note,
            'bom_fingerprint': self._live_fingerprint(),
            'stock_planned': not self.plan_without_stock,
            'oversize_note': '\n'.join(oversize_notes),
            'blocked_note': '\n'.join(blocked),
        })

    @api.model
    def _group_fingerprint(self, pieces, settings, rate, stock=None):
        """What would change this group's answer, and nothing else.

        Lengths and angles because they are the problem; the saw and bar
        settings because they change the packing; the rate because it
        decides which option is cheapest. Labels and references are
        deliberately excluded -- renaming a piece does not change how it
        nests, and re-solving for that would throw away a good plan.
        """
        payload = {
            'pieces': sorted(
                (round(piece['length'], 2), piece.get('angle') or '45')
                for piece in pieces),
            'settings': [settings['stock_ft'], settings['kerf'],
                         settings['offcut_min'], settings['start_trim'],
                         settings['safety_margin']],
            'rate': round(rate, 6),
        }
        if stock:                      # the offcuts on offer change the answer
            payload['stock'] = sorted(stock)
        blob = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()

    def _rate_for_product(self, product):
        """(per-foot rate, its effective date) for a variant, on the
        quote's order date and at the order's profile vendor.

        Same lookup the costing uses -- including the cost-field stand-in
        when the vendor has no rate -- so a bar-feet cost and a BOM cost
        can never disagree about the price of the same profile.
        """
        self.ensure_one()
        design = self.sale_order_id.aw_design_ids[:1]
        on_date = design._costing_date() if design \
            else fields.Date.context_today(self)
        vendor = design._costing_vendor() if design \
            else self.env['aw.profile.rate']._legacy_vendor()
        template = product.product_tmpl_id
        thickness = finish = self.env['product.attribute.value']
        for value in product.product_template_variant_value_ids:
            attribute = value.attribute_id.name
            if attribute == 'Thickness':
                thickness = value.product_attribute_value_id
            elif attribute == 'Finish':
                finish = value.product_attribute_value_id
        rate = self.env['aw.profile.rate']._rate_for(
            template, thickness, finish, on_date, vendor)
        if rate:
            return rate.price, rate.date_from
        return product.standard_price or 0.0, False

    def action_print_cutting_sheet(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cutting_sheet'
        ).report_action(self)

    def action_print_labels(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cut_labels'
        ).report_action(self)

    def action_print_thermal_labels(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_cut_labels_thermal'
        ).report_action(self)

    # Error correction M, as specified: ~15% of the symbol can be lost
    # and still read, which is the realistic ask for a sticker on an
    # aluminium section in a workshop. Odoo's default is L (~7%).
    QR_ERROR_LEVEL = 'M'

    @api.model
    def _qr_src(self, payload):
        """The barcode controller URL for a QR of `payload`.

        Built here rather than in the template because QWeb cannot
        url-encode, and both are needed: the payload carries "/" and
        "|", and `barLevel` only reaches the controller as a query
        parameter -- the `/report/barcode/QR/<value>` path form accepts
        no options at all, so it would silently stay at level L.
        """
        # urlencode from the stdlib, not werkzeug.urls.url_encode:
        # werkzeug removed that helper and Odoo only still imports it
        # through a compatibility shim, which is not something a module
        # should depend on.
        return '/report/barcode/?' + urlencode({
            'barcode_type': 'QR',
            'value': payload,
            'barLevel': self.QR_ERROR_LEVEL,
        })

    def _sticker_qr(self, cut, product, thickness, finish, design,
                    bar_no, bar_total, cut_no):
        """The sticker's QR payload: bare values, pipe separated.

        It replaces "<quote>|<piece ref>", two values with nothing
        saying what they were. The fields are in a fixed order --
        piece ref, where it goes, profile, length and angles, window,
        order, then bar and cut -- and only the last carries keys,
        because "1/13 CUT 1" is the one part that is meaningless
        without them.

        Every character costs QR modules and the modules have to
        survive a thermal sticker, so the keys came off and the site
        address went to the window label, where there is room for it.
        Empty parts are dropped rather than printed as " |  | ", so a
        piece with no location spends nothing saying nothing.
        """
        profile = ' '.join(part for part in (
            product.product_tmpl_id.name or '', thickness, finish) if part)
        length = ' '.join(part for part in (
            cut.length_label or '', cut.cut_angle or '') if part)
        window = ' '.join(part for part in (
            design.name or '', design.location or '') if part)
        parts = [
            cut.piece_ref or '',
            cut.label or '',
            profile,
            length,
            window,
            self.sale_order_id.name or '',
            'BAR %s/%s CUT %s' % (bar_no, bar_total, cut_no),
        ]
        return ' | '.join(part for part in parts if part)

    # ------------------------------------------------------------------
    # precut label sheet
    # ------------------------------------------------------------------
    def _label_layout(self):
        """The sheet's geometry, from settings."""
        param = self.env['ir.config_parameter'].sudo()

        def number(key, default):
            try:
                return float(param.get_param(LABEL_P + key, default))
            except (TypeError, ValueError):
                return default

        def count(key, default):
            try:
                return max(1, int(float(param.get_param(LABEL_P + key,
                                                        default))))
            except (TypeError, ValueError):
                return default

        return {
            'w': number('w', 70.0), 'h': number('h', 29.7),
            'across': count('across', 3), 'down': count('down', 10),
            'top': number('top', 0.0), 'left': number('left', 0.0),
            'gap_x': number('gap_x', 0.0), 'gap_y': number('gap_y', 0.0),
            'offset_x': number('offset_x', 0.0),
            'offset_y': number('offset_y', 0.0),
            'safe': number('safe', 4.0),
        }

    def _sticker_pages(self, start_at=1):
        """Stickers placed on the precut grid, one list per sheet.

        The arithmetic is here and not in the template because it is
        arithmetic: a cell's position, and how much of the safe padding
        each of its four sides needs. QWeb would make it unreadable and
        untestable.

        `start_at` is 1-based and lets a part-used sheet be reused: the
        first N-1 cells are left empty and the run continues from there.
        """
        self.ensure_one()
        rows = self._sticker_rows()
        layout = self._label_layout()
        across, down = layout['across'], layout['down']
        per_sheet = across * down

        # Clamped, because a start beyond the sheet would silently
        # print nothing at all.
        start = min(max(int(start_at or 1), 1), per_sheet)
        queue = [None] * (start - 1) + rows

        pages = []
        for offset in range(0, len(queue), per_sheet):
            cells = []
            for slot, row in enumerate(queue[offset:offset + per_sheet]):
                if row is None:
                    continue        # a used-up label on a reused sheet
                column, line = slot % across, slot // across
                x = (layout['left'] + column * (layout['w'] + layout['gap_x'])
                     + layout['offset_x'])
                y = (layout['top'] + line * (layout['h'] + layout['gap_y'])
                     + layout['offset_y'])
                # Padding only where the label meets the SHEET edge, so
                # an inner label keeps the full width of its stock.
                pad_left = max(0.0, layout['safe'] - x)
                pad_top = max(0.0, layout['safe'] - y)
                pad_right = max(
                    0.0, layout['safe'] - (SHEET_W - (x + layout['w'])))
                pad_bottom = max(
                    0.0, layout['safe'] - (SHEET_H - (y + layout['h'])))
                # The QR is square and fills the height actually left
                # after this cell's own padding, so an edge label gets a
                # slightly smaller one rather than an overflowing one.
                usable_h = max(0.0, layout['h'] - pad_top - pad_bottom)
                usable_w = max(0.0, layout['w'] - pad_left - pad_right)
                # Never wider than half the label: the text needs room,
                # and a pathological setting should shrink the QR rather
                # than push the text out of the cell.
                qr_mm = min(usable_h, usable_w / 2.0)
                cells.append({
                    'row': row,
                    'box': ('position:absolute; left:%.2fmm; top:%.2fmm; '
                            'width:%.2fmm; height:%.2fmm; overflow:hidden;'
                            % (x, y, layout['w'], layout['h'])),
                    'inner': ('height:100%%; padding:%.2fmm %.2fmm %.2fmm '
                              '%.2fmm;' % (pad_top, pad_right, pad_bottom,
                                           pad_left)),
                    'qr_size': '%.2fmm' % qr_mm,
                    # Capped so the text block cannot be the thing that
                    # makes the sticker taller than its cell.
                    'text_box': 'max-height:%.2fmm;' % usable_h,
                    'ref_size': '%.2fmm' % min(4.2, usable_h / 6.0),
                    'small': '%.2fmm' % min(2.3, usable_h / 11.0),
                })
            pages.append(cells)
        return pages or [[]]

    def _sticker_rows(self):
        """Every cut, in cutting order: group, bar, then cut.

        One flat list rather than nested loops in the template, because
        a sticker sheet has to flow continuously across pages and both
        formats need exactly the same rows in exactly the same order.
        """
        self.ensure_one()
        rows = []
        for group in self.group_ids:
            product = group.product_id
            thickness = finish = finish_label = ''
            for value in product.product_template_variant_value_ids:
                if value.attribute_id.name == 'Thickness':
                    thickness = value.name
                elif value.attribute_id.name == 'Finish':
                    finish = value.name
                    finish_label = value.product_attribute_value_id.aw_label(
                        self.sale_order_id.aw_profile_vendor_id)
            for bar_index, bar in enumerate(group.bar_ids, start=1):
                for cut_index, cut in enumerate(bar.cut_ids, start=1):
                    design = cut.bom_line_id.design_id
                    payload = self._sticker_qr(
                        cut, product, thickness, finish, design,
                        bar_index, len(group.bar_ids), cut_index)
                    rows.append({
                        'ref': cut.piece_ref or '—',
                        'role': cut.label or '',
                        'profile': product.product_tmpl_id.name or '',
                        'thickness': thickness,
                        'finish': finish_label or finish,
                        'length': cut.length_label,
                        'length_mm': cut.length_mm,
                        'angle': cut.cut_angle or '',
                        'position': design.name or '',
                        'location': design.location or '',
                        'quote': self.sale_order_id.name or '',
                        'bar_no': bar_index,
                        'bar_total': len(group.bar_ids),
                        'cut_no': cut_index,
                        'stock': bar.stock_label,
                        'qr': payload,
                        'qr_src': self._qr_src(payload),
                    })
        return rows


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
    rate_date = fields.Date(
        string='Rate of',
        help="The effective date of the rate above, so a cost can be "
             "traced to the list it came from. Empty when no rate "
             "was found.")

    piece_fingerprint = fields.Char(
        readonly=True,
        help="Digest of this group's pieces and the settings they were "
             "solved with. A regeneration re-solves only the groups "
             "whose digest moved.")
    chosen_key = fields.Char(
        readonly=True, help="What the algorithm picked.")
    override_key = fields.Char(
        readonly=True, help="What the estimator picked instead.")
    is_overridden = fields.Boolean(compute='_compute_is_overridden')
    active_key = fields.Char(compute='_compute_is_overridden')

    scenario_ids = fields.One2many(
        'aw.cut.plan.scenario', 'group_id', string='Options')
    bar_ids = fields.One2many('aw.cut.plan.bar', 'group_id', string='Bars')

    solve_method = fields.Char(readonly=True)
    gap_feet = fields.Float(readonly=True)
    proven_optimal = fields.Boolean(readonly=True)

    piece_count = fields.Integer(readonly=True)
    bar_count = fields.Integer(readonly=True)
    # NOT 'Bars': bar_ids above is already called that, and this is
    # the MIX ('3 x 16 ft, 2 x 14 ft') rather than the bars
    # themselves.
    bars_summary = fields.Char(
        readonly=True, string='Bar mix',
        help="How many bars of each stock length this option buys.")
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

    def _pieces(self):
        """This group's pieces, exactly as the plan builds them."""
        self.ensure_one()
        pieces = []
        # Pieces already on an offcut from stock are not solved again.
        on_stock = {}
        for cut in self.bar_ids.filtered('from_bar_id').cut_ids:
            key = cut.bom_line_id.id
            on_stock[key] = on_stock.get(key, 0) + 1
        for line in self.plan_id._profile_lines():
            if line.product_id != self.product_id:
                continue
            skip = on_stock.get(line.id, 0)
            for index in range(skip, max(1, line.qty or 1)):
                pieces.append({
                    'length': round(line.length_mm or 0.0, 2),
                    'label': line.label or '',
                    'ref': line.piece_ref or '',
                    'angle': line.cut_angle or '45',
                    'bom_line_id': line.id,
                    'seq': index,
                })
        return pieces

    def _evaluate(self):
        """Re-run every option for this group."""
        self.ensure_one()
        settings = self.plan_id._settings(
            self.plan_id.sale_order_id.aw_profile_vendor_id, strict=True,
            template=self.product_id.product_tmpl_id)
        stock_mm = [ft * MM_PER_FOOT for ft in settings['stock_ft']]
        return evaluate(self._pieces(), stock_mm, kerf=settings['kerf'],
                        offcut_min=settings['offcut_min'],
                        rate_per_ft=self.rate_per_ft,
                        start_trim=settings['start_trim'],
                        safety_margin=settings['safety_margin'],
                        time_budget=settings['budget']), settings

    def _solve_option(self, key):
        """Solve ONE option with the whole budget.

        When the estimator picks an option the plan only half-solved --
        "only 16 ft in the yard today" -- they are going to cut from it,
        so it deserves the full budget rather than the quarter it got
        while four options shared one. Generating the plan spends the
        budget finding the best CHOICE; this spends it on the choice
        actually made.
        """
        self.ensure_one()
        settings = self.plan_id._settings(
            self.plan_id.sale_order_id.aw_profile_vendor_id, strict=True,
            template=self.product_id.product_tmpl_id)
        stock_mm = [ft * MM_PER_FOOT for ft in settings['stock_ft']]
        if key and key != 'mixed':
            wanted = [value for value in stock_mm
                      if abs(value / MM_PER_FOOT - float(key)) < 1e-6]
        else:
            wanted = stock_mm
        result = solve(
            self._pieces(), wanted or stock_mm, kerf=settings['kerf'],
            start_trim=settings['start_trim'],
            safety_margin=settings['safety_margin'],
            offcut_min=settings['offcut_min'],
            rate_per_ft=self.rate_per_ft,
            deadline=time.monotonic() + settings['budget'])
        return result, settings

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
                'proven_optimal': bool(scenario.get('proven_optimal')),
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
        return self._apply_scenario(
            scenario_by_key(result, self.active_key), offcut_min)

    def _apply_scenario(self, scenario, offcut_min):
        """Write the bars and totals for one solved option."""
        self.ensure_one()
        # Bars bought are replaced; offcuts taken from stock stay.
        self.bar_ids.filtered(lambda b: not b.from_bar_id).unlink()
        stock_cuts = len(self.bar_ids.cut_ids)
        if not scenario:
            self.write({'piece_count': stock_cuts, 'bar_count': 0,
                        'bars_summary': '', 'feet_bought': 0, 'feet_used': 0,
                        'yield_pct': 0, 'cost': 0})
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
                    'piece_ref': piece.get('ref') or '',
                    'length_mm': piece['length'],
                    'cut_angle': piece.get('angle') or '',
                })
        self.write({
            'piece_count': stock_cuts + sum(
                len(bar['cuts']) for bar in scenario['bars']),
            'bar_count': scenario['bar_count'],
            'bars_summary': self._summarise_bars(scenario['bars_by_length']),
            'feet_bought': scenario['feet_bought'],
            'feet_used': scenario['feet_used'],
            'yield_pct': scenario['yield_pct'],
            'cost': scenario['cost'],
        })

    def _add_stock_bars(self, stock_bars, offcut_min):
        """Record the offcuts from earlier batches that took pieces: a bar
        per offcut, pointing at the bar it came from, not counted as bought."""
        self.ensure_one()
        added = 0
        for bar in stock_bars:
            record = self.env['aw.cut.plan.bar'].create({
                'group_id': self.id,
                'sequence': 5,
                'from_bar_id': bar['from_id'],
                'stock_mm': bar['stock_mm'],
                'remainder_mm': bar['remainder'],
                'is_returnable': bar['remainder'] >= offcut_min,
            })
            for position, piece in enumerate(
                    sorted(bar['cuts'], key=lambda c: -c['length'])):
                self.env['aw.cut.plan.cut'].create({
                    'bar_id': record.id,
                    'sequence': (position + 1) * 10,
                    'bom_line_id': piece.get('bom_line_id') or False,
                    'label': piece.get('label') or '',
                    'piece_ref': piece.get('ref') or '',
                    'length_mm': piece['length'],
                    'cut_angle': piece.get('angle') or '',
                })
                added += 1
        if added:
            self.piece_count = (self.piece_count or 0) + added
        return added

    def action_clear_override(self):
        self.plan_id._ensure_draft()
        for group in self:
            group.override_key = ''
            result, settings = group._solve_option(group.chosen_key)
            group._apply_scenario(result, settings['offcut_min'])
            group.write({
                'solve_method': result.get('method') or 'none',
                'gap_feet': result.get('gap_feet') or 0.0,
                'proven_optimal': bool(result.get('proven_optimal')),
            })
            scenario = group.scenario_ids.filtered(
                lambda s: s.key == group.chosen_key)
            if scenario:
                scenario[:1]._absorb(result)
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
    proven_optimal = fields.Boolean(
        readonly=True,
        help="False means this option ran out of solver budget, not "
             "that it is genuinely this expensive. The chosen option is "
             "solved first, so it is the one most likely to be proven.")

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
        self.group_id.plan_id._ensure_draft()
        if not self.feasible:
            raise UserError(_(
                "That option cannot hold every piece in this profile, so "
                "it is not a choice: %s", self.blocked_note or ''))
        group = self.group_id
        # Recorded as an override only when it differs from what the
        # algorithm chose, so "overridden" means what it says.
        group.override_key = (
            '' if self.key == group.chosen_key else self.key)
        # Solved fresh with the FULL budget. The bars are only ever
        # stored for the option in force, so switching has to solve
        # anyway -- and this is the plan they will cut from, so it gets
        # the whole budget rather than the share it had while four
        # options competed.
        result, settings = group._solve_option(self.key)
        group._apply_scenario(result, settings['offcut_min'])
        self._absorb(result)
        group.write({
            'solve_method': result.get('method') or 'none',
            'gap_feet': result.get('gap_feet') or 0.0,
            'proven_optimal': bool(result.get('proven_optimal')),
        })
        return True

    def _absorb(self, result):
        """Update this row from a fresh solve of the same option, so the
        table stops showing the half-solved figures."""
        self.ensure_one()
        self.write({
            'bar_count': result['bar_count'],
            'bars_summary': self.group_id._summarise_bars(
                result['bars_by_length']),
            'feet_bought': result['feet_bought'],
            'feet_used': result['feet_used'],
            'waste_feet': result['waste_feet'],
            'yield_pct': result['yield_pct'],
            'cost': result['cost'],
            'proven_optimal': bool(result.get('proven_optimal')),
        })


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
    # An offcut an earlier batch left, used by this one instead of a new bar.
    from_bar_id = fields.Many2one(
        'aw.cut.plan.bar', string='Offcut of', ondelete='set null',
        index=True)
    source_label = fields.Char(compute='_compute_source_label')

    def _compute_source_label(self):
        for bar in self:
            source = bar.from_bar_id
            bar.source_label = _(
                "%(batch)s, bar %(no)s (%(mm)s mm left)",
                batch=source.group_id.plan_id.name,
                no=source.sequence // 10 or 1,
                mm=round(source.remainder_mm)) if source else ''

    @api.depends('stock_mm', 'remainder_mm')
    def _compute_labels(self):
        design = self.env['aw.design']
        for bar in self:
            bar.stock_label = '%g ft' % round(
                bar.stock_mm / MM_PER_FOOT, 2) if bar.stock_mm else ''
            # Soot style: these labels end up on the stickers and the
            # cutting sheet, which the workshop reads.
            bar.remainder_label = design._render_length(
                bar.remainder_mm, style='soot')


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
    label = fields.Char(help="e.g. 'P2 Palay - Top'.")
    piece_ref = fields.Char(
        string='Ref', index=True,
        help="The piece's stable reference, e.g. D1.3. Set by the "
             "design, not by this plan, so re-optimising never "
             "renumbers it.")
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
            cut.length_label = design._render_length(
                cut.length_mm, style='soot')
