# -*- coding: utf-8 -*-
"""A confirmed order's cost does not move by itself.

Costs are snapshotted onto the BOM lines at explosion, at the rates of the
quote's date. Without more, exploding a window of a confirmed order again
(a re-save, Recompute, a changed spec) looks every rate up again, so a list
rate dated before the order and entered afterwards, or a changed cost on a
hardware part, would move a price the customer already has. The rule:

* re-exploding a window of a CONFIRMED order keeps the stored unit cost of
  every piece that still exists (same kind and product) and costs only the
  new pieces; a piece that is longer or shorter is the same unit cost over
  the new length;
* when nothing about the window changed (same pieces, area, quantity,
  manual rate and price structure) its cost and price are put back exactly
  as they were, even if a price structure value changed in between;
* the price structure's values no longer re-price windows on confirmed
  orders (only those still being quoted).

A cost typed for one panel (a manual rate) is a decision, not a lookup, and
is never frozen. Nothing here touches a draft or sent quote.
"""
from odoo import api, models

MM_PER_FOOT = 304.8
PRICING_FIELDS = ('cost_total', 'basic_value', 'price_total',
                  'price_per_sqft', 'margin_pct', 'uncosted_line_count')


class AwDesign(models.Model):
    _inherit = 'aw.design'

    def _is_frozen(self):
        order = self.sale_order_id
        return bool(order and order.state == 'sale')

    @staticmethod
    def _freeze_key(line):
        if line.product_id:
            return (line.kind, line.product_id.id)
        return (line.kind, 0, line.label or '')

    @staticmethod
    def _bom_signature(lines):
        return sorted(
            (l.kind, l.product_id.id, round(l.length_mm or 0.0, 1),
             l.qty or 0, l.panel_no or 0)
            for l in lines if not l.is_free_form)

    def _freeze_snapshot(self):
        """{key: stored unit cost, its date and its note} of the pieces that
        carry a looked-up cost."""
        self.ensure_one()
        snapshot = {}
        for line in self.bom_line_ids.sorted('sequence'):
            if line.is_free_form or line.rate_is_manual or not line.unit_cost:
                continue
            snapshot.setdefault(self._freeze_key(line), {
                'unit_cost': line.unit_cost, 'rate_date': line.rate_date,
                'cost_note': line.cost_note})
        return snapshot

    def _take_frozen_cost(self, line, unit_cost, rate_date, note):
        """The costing loop's hook: the stored unit cost for a piece that
        existed, scaling the line's cost to the (new) quantity."""
        frozen = self.env.context.get('aw_frozen_costs')
        if not frozen or line.rate_is_manual or line.is_free_form:
            return unit_cost, rate_date, note
        if line.kind == 'profile' and line.cut_on_site:
            return unit_cost, rate_date, note
        snap = frozen.get(self._freeze_key(line))
        if not snap:
            return unit_cost, rate_date, note
        old = snap['unit_cost']
        if unit_cost:
            if abs(unit_cost - old) > 1e-9:
                line.line_cost = line.line_cost * old / unit_cost
        elif line.kind == 'profile':
            line.line_cost = old * (line.length_mm or 0.0) / MM_PER_FOOT \
                * (line.qty or 0)
        elif line.kind in ('hardware', 'other'):
            line.line_cost = old * (line.qty or 0)
        else:
            return unit_cost, rate_date, note
        return old, snap['rate_date'], snap['cost_note']

    def _freeze_state(self):
        return {
            'signature': self._bom_signature(self.bom_line_ids),
            'inputs': (self.area_sqm, self.area_sqft, self.qty,
                       self.manual_rate, self.price_structure_id.id),
            'values': {name: self[name] for name in PRICING_FIELDS},
        }

    def _explode(self):
        self.ensure_one()
        if not (self._is_frozen() and self.bom_line_ids):
            return super()._explode()
        snapshot = self._freeze_snapshot()
        before = self._freeze_state()
        result = super(AwDesign, self.with_context(
            aw_frozen_costs=snapshot))._explode()
        self.env.flush_all()
        after = self._freeze_state()
        if (after['signature'] == before['signature']
                and after['inputs'] == before['inputs']):
            # nothing about the window changed: its price is what it was
            self.write(before['values'])
        return result


class AwPriceStructureLine(models.Model):
    _inherit = 'aw.price.structure.line'

    @api.model
    def _reprice_open_designs(self, structures):
        """Windows still being quoted (and not on any order) follow the
        structure; a window on a confirmed order does not."""
        if not structures:
            return
        designs = self.env['aw.design'].sudo().search([
            ('price_structure_id', 'in', structures.ids),
            '|', ('sale_order_id', '=', False),
            ('sale_order_id.state', 'in', ('draft', 'sent'))])
        for name in PRICING_FIELDS:
            self.env.add_to_compute(designs._fields[name], designs)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        self._reprice_open_designs(lines.structure_id)
        return lines

    def write(self, vals):
        result = super().write(vals)
        self._reprice_open_designs(self.structure_id)
        return result

    def unlink(self):
        structures = self.structure_id
        result = super().unlink()
        self._reprice_open_designs(structures)
        return result
