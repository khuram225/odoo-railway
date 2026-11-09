# -*- coding: utf-8 -*-
"""Receiving bars: one stock lot per profile variant and length, one receipt
per delivery.

A delivery is any mix of lengths. The person types bars per length; this
module turns that into the receipt Odoo already made for the purchase order:

* every row makes ONE stock lot (`length_mm` rounded to a whole mm, source
  "purchased") and a move line of bars x length in ft carrying it;
* bars that fit the open demand of an ordered line of that variant and length
  go on that line's move; bars beyond it (a length that was not ordered, or
  more of it) go on a NEW line "added at receipt", priced like the variant's
  line on the same order;
* the receipt is validated with the rest left in a backorder, so a partial
  delivery leaves the order open and the next delivery is a new receipt;
* what the added lines took is taken off the open demand of the variant's
  ordered lines, so a delivery of 244 ft in other lengths against 252 ft
  ordered leaves 8 ft to come, not 252.

The products are not lot-tracked yet, so Odoo's own availability ignores the
lots; they are recorded on the move line and the quant and are what the
tracking switch will use.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

FT_MM = 304.8
LARGE_ROW = 100


def length_mm(length_ft):
    """Whole millimetres: 14 ft = 4267, 16 ft = 4877, 18 ft = 5486."""
    return int(length_ft * FT_MM + 0.5)


def ft_status(ordered, received):
    """'complete', '8 ft short' or '12 ft over'."""
    delta = received - ordered
    if abs(delta) < 0.05:
        return _("complete")
    if delta < 0:
        return _("%(ft)g ft short", ft=round(-delta, 2))
    return _("%(ft)g ft over", ft=round(delta, 2))


class AwPoReceipt(models.Model):
    _name = 'aw.po.receipt'
    _description = 'Bars received on a purchase order'
    _order = 'count_date desc, id desc'
    _rec_name = 'picking_id'

    order_id = fields.Many2one(
        'purchase.order', string='Purchase order', required=True,
        index=True, ondelete='cascade')
    picking_id = fields.Many2one('stock.picking', string='Receipt')
    counted_by_id = fields.Many2one(
        'res.users', string='Counted by',
        default=lambda self: self.env.user)
    count_date = fields.Date(
        string='Date', default=fields.Date.context_today)
    line_ids = fields.One2many(
        'aw.po.receipt.line', 'receipt_id', string='Lines')
    total_ft = fields.Float(
        string='Feet', compute='_compute_total_ft', store=True)

    @api.depends('line_ids.feet')
    def _compute_total_ft(self):
        for receipt in self:
            receipt.total_ft = sum(receipt.line_ids.mapped('feet'))


class AwPoReceiptLine(models.Model):
    _name = 'aw.po.receipt.line'
    _description = 'Bars received, one row of a delivery'
    _order = 'receipt_id, id'

    receipt_id = fields.Many2one(
        'aw.po.receipt', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(related='receipt_id.order_id', store=True)
    product_id = fields.Many2one(
        'product.product', string='Profile', required=True)
    bar_length_ft = fields.Float(string='Bar length (ft)', required=True)
    bars = fields.Integer(string='Bars', required=True)
    feet = fields.Float(
        string='Feet', compute='_compute_feet', store=True)
    lot_id = fields.Many2one('stock.lot', string='Lot')
    po_line_id = fields.Many2one('purchase.order.line', string='PO line')
    added_at_receipt = fields.Boolean(string='Added at receipt')

    @api.depends('bars', 'bar_length_ft')
    def _compute_feet(self):
        for line in self:
            line.feet = line.bars * line.bar_length_ft


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    aw_receipt_ids = fields.One2many(
        'aw.po.receipt', 'order_id', string='Bar receipts')

    # -- what was ordered and what came ------------------------------------
    def _aw_variant_progress(self):
        """{product: {'ordered_ft', 'received_ft', 'lengths': {L: [ordered
        bars, received bars]}, 'line': first ordered line}} for the bars
        lines. Ordered leaves out the lines added at receipt; received counts
        every line, since the vendor's mix decides where the feet land."""
        self.ensure_one()
        foot = self.env['purchase.order.line']._aw_foot()
        progress = {}
        for line in self._aw_print_bar_lines():
            item = progress.setdefault(line.product_id, {
                'ordered_ft': 0.0, 'received_ft': 0.0, 'lengths': {},
                'line': line})
            length = round(line.aw_bar_length_ft, 4)
            slot = item['lengths'].setdefault(length, [0, 0])
            item['received_ft'] += line.product_uom_id._compute_quantity(
                line.qty_received, foot)
            if not line.aw_added_at_receipt:
                item['ordered_ft'] += line.product_uom_id._compute_quantity(
                    line.product_qty, foot)
                slot[0] += line.aw_bar_count
                if item['line'].aw_added_at_receipt:
                    item['line'] = line
        done = self.env['aw.po.receipt.line'].search(
            [('order_id', '=', self.id)])
        for row in done:
            item = progress.get(row.product_id)
            if item is not None:
                slot = item['lengths'].setdefault(
                    round(row.bar_length_ft, 4), [0, 0])
                slot[1] += row.bars
        return progress

    def _aw_progress_sorted(self, progress=None):
        progress = progress or self._aw_variant_progress()
        return sorted(
            progress.items(),
            key=lambda pair: self._aw_bar_line_key(pair[1]['line'])[:-1])

    def _aw_receive_lengths(self, product):
        """Every active length for this profile and vendor, plus the lengths
        already on the order."""
        template = product.product_tmpl_id
        lengths = set(self.env['aw.cut.plan']._settings(
            self.partner_id, strict=False, template=template)['stock_ft'])
        for line in self._aw_print_bar_lines():
            if line.product_id == product:
                lengths.add(round(line.aw_bar_length_ft, 4))
        return sorted(lengths)

    def action_receive_bars(self):
        """The receive screen, filled in: every ordered variant with a ready
        row for every active length."""
        self.ensure_one()
        if self.state != 'purchase':
            raise UserError(_("Confirm the order before receiving bars."))
        progress = self._aw_variant_progress()
        if not progress:
            raise UserError(_("This order has no bars lines."))
        commands, sequence = [], 0
        for product, item in self._aw_progress_sorted(progress):
            price = item['line'].price_unit
            for length in self._aw_receive_lengths(product):
                ordered, received = item['lengths'].get(length, [0, 0])
                sequence += 1
                commands.append((0, 0, {
                    'sequence': sequence, 'kind': 'length',
                    'product_id': product.id, 'bar_length_ft': length,
                    'ordered_bars': ordered, 'received_bars': received,
                    'ordered_ft': ordered * length,
                    'received_ft': received * length, 'price_ft': price}))
            sequence += 1
            commands.append((0, 0, {
                'sequence': sequence, 'kind': 'total',
                'product_id': product.id, 'ordered_ft': item['ordered_ft'],
                'received_ft': item['received_ft'], 'price_ft': price}))
        wizard = self.env['aw.po.receive.wizard'].create({
            'order_id': self.id, 'line_ids': commands})
        return {
            'type': 'ir.actions.act_window', 'name': _("Receive bars"),
            'res_model': 'aw.po.receive.wizard', 'res_id': wizard.id,
            'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'new'}

    # -- the receipt itself -------------------------------------------------
    def _aw_open_moves(self, line):
        return line.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')).sorted('id')

    def _aw_receipt_price(self, product):
        """Price per ft for a line added at receipt: the variant's own line
        on this order, else the last paid price, else the list rate."""
        own = self._aw_print_bar_lines().filtered(
            lambda l: l.product_id == product and l.price_unit)
        if own:
            line = own.sorted('id')[0]
            return line.price_unit, line.discount
        thickness, finish = self._aw_variant_values(product)
        price = self.env['purchase.order.line']._aw_start_price(
            product.product_tmpl_id, thickness, finish, self.partner_id,
            (self.date_order or fields.Datetime.now()).date(),
            self.currency_id)[0]
        return price or 0.0, 0.0

    def _aw_add_receipt_line(self, product, length, bars):
        price, discount = self._aw_receipt_price(product)
        foot = self.env['purchase.order.line']._aw_foot()
        line = self.env['purchase.order.line'].create({
            'order_id': self.id, 'product_id': product.id,
            'aw_bar_count': bars, 'aw_bar_length_ft': length,
            'product_qty': bars * length, 'product_uom_id': foot.id,
            'aw_added_at_receipt': True})
        values = {'price_unit': price, 'technical_price_unit': price}
        if discount:
            values['discount'] = discount
        line.write(values)
        self.message_post(
            body=_("Line added at receipt: %(product)s, %(bars)s bars of "
                   "%(ft)g ft at %(price).2f per ft.",
                   product=product.display_name, bars=bars, ft=length,
                   price=price),
            subtype_xmlid='mail.mt_note')
        return line

    def _aw_receive_bars(self, rows, counted_by=None, count_date=None):
        """Receive `rows` ([{'product_id', 'bar_length_ft', 'bars'}]) as one
        delivery; returns the aw.po.receipt."""
        self.ensure_one()
        if self.state != 'purchase':
            raise UserError(_("Confirm the order before receiving bars."))
        groups = {}
        for row in rows:
            bars = int(row.get('bars') or 0)
            length = round(float(row.get('bar_length_ft') or 0.0), 4)
            if bars < 0:
                raise UserError(_("Bars cannot be negative."))
            if not bars:
                continue
            if length <= 0 or not row.get('product_id'):
                raise UserError(_("Every row needs a profile and a length."))
            key = (row['product_id'], length)
            groups[key] = groups.get(key, 0) + bars
        if not groups:
            raise UserError(_("Nothing to receive: every row is 0."))

        Product = self.env['product.product']
        plan = []
        for (product_id, length), bars in sorted(groups.items()):
            product = Product.browse(product_id)
            if not product.product_tmpl_id.aw_is_profile:
                raise UserError(_("%s is not a profile.",
                                  product.display_name))
            remaining, takes = bars, []
            lines = self.order_line.filtered(
                lambda l: l.aw_is_bars and not l.aw_added_at_receipt
                and l.product_id == product
                and abs(l.aw_bar_length_ft - length) < 1e-6)
            for line in lines.sorted('id'):
                for move in self._aw_open_moves(line):
                    if remaining <= 0:
                        break
                    fits = int(move.product_uom_qty / length + 1e-6)
                    take = min(remaining, fits)
                    if take > 0:
                        takes.append((move, take, line))
                        remaining -= take
            plan.append({'product': product, 'length': length,
                         'bars': bars, 'takes': takes, 'over': remaining,
                         'added': self.env['purchase.order.line']})

        # what is beyond the open demand becomes a line of its own
        added_ft = {}
        for item in plan:
            if item['over'] > 0:
                line = self._aw_add_receipt_line(
                    item['product'], item['length'], item['over'])
                move = self._aw_open_moves(line)[:1]
                if not move:
                    raise UserError(_(
                        "Odoo made no receipt move for the added line of %s.",
                        item['product'].display_name))
                item['takes'].append((move, item['over'], line))
                item['added'] = line
                added_ft[item['product']] = added_ft.get(
                    item['product'], 0.0) + item['over'] * item['length']

        moves = self.env['stock.move']
        for item in plan:
            for move, _bars, _line in item['takes']:
                moves |= move
        pickings = moves.picking_id
        picking = pickings.sorted('id')[:1]
        for move in moves:
            if move.picking_id != picking:
                move.picking_id = picking
        picking = picking.with_context(skip_backorder=True)

        # the lots and the move lines
        for move in picking.move_ids:
            if move not in moves and move.state not in ('done', 'cancel'):
                move.move_line_ids.unlink()
                move.picked = False
        lots = {}
        for item in plan:
            product, length = item['product'], item['length']
            lot = self.env['stock.lot'].create({
                'name': "%s-%s-%gft" % (self.name, picking.name, length),
                'product_id': product.id, 'company_id': self.company_id.id,
                'length_mm': length_mm(length),
                'profile_source': 'purchased'})
            lots[(product.id, length)] = lot
        foot = self.env['purchase.order.line']._aw_foot()
        moved = {}
        for item in plan:
            lot = lots[(item['product'].id, item['length'])]
            for move, take, _line in item['takes']:
                moved.setdefault(move, []).append((take, item['length'], lot))
        for move, pieces in moved.items():
            move.move_line_ids.unlink()
            for take, length, lot in pieces:
                ft = take * length
                self.env['stock.move.line'].create({
                    'move_id': move.id, 'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'quantity': foot._compute_quantity(
                        ft, move.product_uom),
                    'lot_id': lot.id, 'picking_id': picking.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'picked': True})
            move.picked = True

        picking.button_validate()
        if picking.state != 'done':
            raise UserError(_("The receipt %s did not validate.",
                              picking.name))

        receipt = self.env['aw.po.receipt'].create({
            'order_id': self.id, 'picking_id': picking.id,
            'counted_by_id': (counted_by or self.env.user).id,
            'count_date': count_date or fields.Date.context_today(self),
            'line_ids': [(0, 0, {
                'product_id': item['product'].id,
                'bar_length_ft': item['length'], 'bars': item['bars'],
                'lot_id': lots[(item['product'].id, item['length'])].id,
                'po_line_id': (item['takes'][0][2].id
                               if item['takes'] else False),
                'added_at_receipt': bool(item['added'])})
                for item in plan]})
        self._aw_take_off_open_demand(added_ft)
        self._aw_post_receipt_note(receipt)
        return receipt

    def _aw_take_off_open_demand(self, added_ft):
        """Feet that arrived on added lines are feet of the variant: take
        them off what is still expected on its ordered lines."""
        for product, consume in added_ft.items():
            lines = self._aw_print_bar_lines().filtered(
                lambda l: l.product_id == product
                and not l.aw_added_at_receipt)
            cut_total = 0.0
            for line in lines.sorted('id'):
                for move in self._aw_open_moves(line):
                    if consume <= 1e-6:
                        break
                    cut = min(consume, move.product_uom_qty)
                    consume -= cut
                    cut_total += cut
                    if move.product_uom_qty - cut < 1e-6:
                        move._action_cancel()
                    else:
                        move.move_line_ids.unlink()
                        move.product_uom_qty -= cut
                        move._action_assign()
            if cut_total:
                self.message_post(
                    body=_("Still expected of %(product)s reduced by "
                           "%(ft)g ft: that much arrived in other lengths.",
                           product=product.display_name,
                           ft=round(cut_total, 2)),
                    subtype_xmlid='mail.mt_note')

    def _aw_post_receipt_note(self, receipt):
        """Ordered against received, per profile variant in feet and per
        length in bars."""
        self.ensure_one()
        from markupsafe import Markup, escape
        items = []
        for product, item in self._aw_progress_sorted():
            lengths = ', '.join(
                "%g ft: %s of %s bars" % (length, rec, ordr)
                for length, (ordr, rec) in sorted(item['lengths'].items())
                if ordr or rec)
            items.append(Markup('<li>%s: %s<br/>%s</li>') % (
                escape(product.display_name),
                escape(_("ordered %(o)g ft, received %(r)g ft, %(s)s",
                         o=round(item['ordered_ft'], 2),
                         r=round(item['received_ft'], 2),
                         s=ft_status(item['ordered_ft'],
                                     item['received_ft']))),
                escape(lengths)))
        body = Markup(
            '<p>%s</p><ul>%s</ul>') % (
            escape(_("Receipt %(picking)s, counted by %(who)s on %(date)s.",
                     picking=receipt.picking_id.name,
                     who=receipt.counted_by_id.name,
                     date=receipt.count_date)),
            Markup('').join(items))
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

