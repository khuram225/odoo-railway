# -*- coding: utf-8 -*-
"""What the cost rule would do, before anything is switched on.

*Cost Rule Preview* re-costs every quote still being quoted (draft or sent)
twice in a savepoint that is always rolled back: once as today (the list
rate) and once with the cost rule (the newer of the list rate and the quote
vendor's last purchase price, within the maximum age). It lists, per window,
the cost as saved, the cost today, the cost with the rule and the
difference, and which pieces moved. It lists, per profile variant, the cost
field now against the cost the rule gives (what stock would be valued at),
the variants with cost 0 first. Nothing is written: not a cost, not a price,
not a BOM line.
"""
import logging
from contextlib import closing

from odoo import _, api, fields, models

from .cost_rule import money

_logger = logging.getLogger(__name__)


class AwCostPreviewWizard(models.TransientModel):
    _name = 'aw.cost.preview.wizard'
    _description = 'Cost rule preview'

    line_ids = fields.One2many(
        'aw.cost.preview.line', 'wizard_id', string='Windows', readonly=True)
    variant_ids = fields.One2many(
        'aw.cost.preview.variant', 'wizard_id', string='Variants',
        readonly=True)
    max_age_days = fields.Integer(string='Maximum age of a last price (days)',
                                  readonly=True)
    summary = fields.Char(readonly=True)

    @api.model
    def action_open(self):
        """Run the preview and show it."""
        wizard = self.create({})
        wizard._run()
        return {
            'type': 'ir.actions.act_window', 'name': _("Cost Rule Preview"),
            'res_model': self._name, 'res_id': wizard.id,
            'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'current'}

    # -- the windows still being quoted -----------------------------------
    def _recost(self, design, basis):
        """(cost, price, {variant id: (unit cost, note)}) of `design` costed
        again with `basis` ('list' or 'rule'), read inside a savepoint that
        is rolled back on the way out."""
        with closing(self.env.cr.savepoint()):
            design = design.with_context(aw_cost_basis=basis)
            design._explode()
            self.env.flush_all()
            pieces = {}
            for line in design.bom_line_ids.filtered(
                    lambda l: l.kind == 'profile' and l.product_id):
                pieces.setdefault(
                    line.product_id.id,
                    (line.unit_cost, line.cost_note or '',
                     line.product_id.display_name))
            return design.cost_total, design.price_total, pieces

    def _changes_text(self, today_pieces, rule_pieces):
        rows = []
        for variant_id, (unit, note, name) in rule_pieces.items():
            before = today_pieces.get(variant_id, (0.0, '', name))[0]
            if abs(unit - before) > 1e-9:
                rows.append("%s: %s -> %s (%s)" % (
                    name, money(before), money(unit), note or 'list'))
        return '\n'.join(sorted(rows))

    def _run(self):
        self.ensure_one()
        Line = self.env['aw.cost.preview.line']
        orders = self.env['sale.order'].sudo().search(
            [('state', 'in', ('draft', 'sent'))], order='id')
        total_now = total_rule = 0.0
        windows = 0
        for design in orders.aw_design_ids.sorted('id'):
            values = {
                'wizard_id': self.id, 'design_id': design.id,
                'order_name': design.sale_order_id.name,
                'saved_cost': design.cost_total,
                'saved_price': design.price_total}
            try:
                cost_now, price_now, today = self._recost(design, 'list')
                cost_rule, price_rule, rule = self._recost(design, 'rule')
            except Exception as error:      # one window never stops the rest
                _logger.exception("cost preview: %s", design.display_name)
                values['error'] = str(error)[:300]
            else:
                values.update({
                    'cost_now': cost_now, 'cost_rule': cost_rule,
                    'price_now': price_now, 'price_rule': price_rule,
                    'changes': self._changes_text(today, rule)})
                total_now += cost_now
                total_rule += cost_rule
                windows += 1
            Line.create(values)
        # the caches hold the rolled-back state's values: start clean
        self.env.invalidate_all()
        self._run_variants()
        self.write({
            'max_age_days': self.env['product.product']._aw_lpp_max_age_days(),
            'summary': _(
                "%(windows)s window(s) on %(orders)s quote(s): cost today "
                "%(now)s, with the rule %(rule)s, difference %(diff)s.",
                windows=windows, orders=len(orders), now=money(total_now),
                rule=money(total_rule), diff=money(total_rule - total_now))})

    # -- the cost field of every profile variant ------------------------------
    def _run_variants(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles')
        variants = self.env['product.product'].sudo().with_context(
            active_test=False).search(
            [('categ_id', 'child_of', category.id)])
        rows = []
        for variant in variants:
            result = variant._aw_current_cost()
            cost = variant.standard_price
            if result['kind'] == 'none' or \
                    abs(result['cost'] - cost) < 0.005:
                continue
            rows.append({
                'wizard_id': self.id, 'product_id': variant.id,
                'cost_field': cost, 'cost_rule': result['cost'],
                'source': result['text'], 'zero_cost': not cost})
        rows.sort(key=lambda r: (not r['zero_cost'],
                                 -abs(r['cost_rule'] - r['cost_field'])))
        self.env['aw.cost.preview.variant'].create(rows[:300])


class AwCostPreviewLine(models.TransientModel):
    _name = 'aw.cost.preview.line'
    _description = 'Cost rule preview, one window'
    _order = 'id'

    wizard_id = fields.Many2one(
        'aw.cost.preview.wizard', required=True, ondelete='cascade')
    design_id = fields.Many2one('aw.design', string='Window')
    order_name = fields.Char(string='Quote')
    saved_cost = fields.Float(string='Saved cost', digits='Product Price')
    saved_price = fields.Float(string='Saved price', digits='Product Price')
    cost_now = fields.Float(string='Cost today', digits='Product Price')
    cost_rule = fields.Float(string='Cost with the rule', digits='Product Price')
    price_now = fields.Float(string='Price today', digits='Product Price')
    price_rule = fields.Float(string='Price with the rule', digits='Product Price')
    difference = fields.Float(
        string='Cost difference', compute='_compute_difference',
        digits='Product Price')
    difference_pct = fields.Float(
        string='%', compute='_compute_difference', digits=(16, 1))
    changes = fields.Text(string='Pieces that move')
    error = fields.Char(string='Could not be re-costed')

    @api.depends('cost_now', 'cost_rule')
    def _compute_difference(self):
        for line in self:
            line.difference = line.cost_rule - line.cost_now
            line.difference_pct = (
                line.difference / line.cost_now * 100.0
                if line.cost_now else 0.0)


class AwCostPreviewVariant(models.TransientModel):
    _name = 'aw.cost.preview.variant'
    _description = 'Cost rule preview, one profile variant'
    _order = 'id'

    wizard_id = fields.Many2one(
        'aw.cost.preview.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Variant')
    cost_field = fields.Float(string='Cost field now', digits='Product Price')
    cost_rule = fields.Float(string='Cost by the rule', digits='Product Price')
    source = fields.Char(string='Where it comes from')
    zero_cost = fields.Boolean(string='Cost field is 0')
    difference = fields.Float(
        string='Difference', compute='_compute_difference',
        digits='Product Price')

    @api.depends('cost_field', 'cost_rule')
    def _compute_difference(self):
        for row in self:
            row.difference = row.cost_rule - row.cost_field
