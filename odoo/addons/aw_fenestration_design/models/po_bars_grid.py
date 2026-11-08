# -*- coding: utf-8 -*-
"""The bars grid on a purchase order: one profile, thickness x finish x length.

Replaces Odoo's variant grid for profiles. The dialog (static/src/po_bars_grid)
asks aw_bars_grid_data() for the thicknesses, finishes, lengths, the vendor's
rate per ft and the bars already on the order, and sends every cell back to
aw_bars_grid_apply(). A cell above 0 is one purchase line (variant + length,
priced at the vendor's rate per ft and pinned); a line that exists is updated,
never duplicated; a cell at 0 removes its line. Nothing is stored: the dialog
is a client component and these are plain methods.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

EDITABLE = ('draft', 'sent')


def _key(thickness_id, finish_id, length):
    return "%s|%s|%g" % (thickness_id, finish_id, length)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def action_add_profile_bars(self):
        """The button beside 'Add a product': opens the dialog."""
        order = self.env['purchase.order'].browse(
            self.env.context.get('order_id'))
        if not order:
            raise UserError(_("Save the order first."))
        return {
            'type': 'ir.actions.client', 'tag': 'aw_po_bars_grid',
            'params': {'order_id': order.id},
        }


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _aw_profile_domain(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles')
        return [('categ_id', 'child_of', category.id),
                ('purchase_ok', '=', True)]

    def aw_bars_grid_profiles(self, query=''):
        self.ensure_one()
        domain = self._aw_profile_domain()
        if query:
            domain.append(('name', 'ilike', query))
        return [{'id': t.id, 'name': t.display_name} for t in
                self.env['product.template'].search(
                    domain, limit=30, order='name')]

    def _aw_grid_template(self, template_id):
        template = self.env['product.template'].browse(template_id).exists()
        if not template or not template.aw_is_profile:
            raise UserError(_("Pick a profile."))
        return template

    def _aw_grid_values(self, template):
        """(thicknesses, finishes) of the template, as attribute values."""
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        lines = template.attribute_line_ids
        return (lines.filtered(
                    lambda l: l.attribute_id == thickness_attr).value_ids,
                lines.filtered(
                    lambda l: l.attribute_id == finish_attr).value_ids)

    def _aw_grid_lengths(self, template):
        """Active lengths: this profile's rows, the vendor's, else global."""
        return sorted(self.env['aw.cut.plan']._settings(
            self.partner_id, strict=True, template=template)['stock_ft'])

    def _aw_variant_values(self, product):
        thickness = finish = self.env['product.attribute.value']
        for value in product.product_template_variant_value_ids:
            name = value.attribute_id.name
            if name == 'Thickness':
                thickness = value.product_attribute_value_id
            elif name == 'Finish':
                finish = value.product_attribute_value_id
        return thickness, finish

    def aw_bars_grid_data(self, template_id):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Pick the vendor before adding a profile."))
        template = self._aw_grid_template(template_id)
        thicknesses, finishes = self._aw_grid_values(template)
        if not (thicknesses and finishes):
            raise UserError(_(
                "%s has no thickness or no finish to choose from.",
                template.display_name))
        lengths = self._aw_grid_lengths(template)
        Line = self.env['purchase.order.line']
        on_date = (self.date_order or fields.Datetime.now()).date()
        rates = {}
        for thickness in thicknesses:
            for finish in finishes:
                price = Line._aw_rate_for(
                    template, thickness, finish, self.partner_id, on_date)
                rates["%s|%s" % (thickness.id, finish.id)] = price or False
        cells = {}
        for line in self.order_line.filtered(
                lambda l: l.product_id.product_tmpl_id == template
                and l.aw_bar_count):
            thickness, finish = self._aw_variant_values(line.product_id)
            key = _key(thickness.id, finish.id, line.aw_bar_length_ft)
            cells[key] = cells.get(key, 0) + line.aw_bar_count
        return {
            'template': {'id': template.id, 'name': template.display_name},
            'vendor': self.partner_id.display_name,
            'editable': self.state in EDITABLE,
            'lengths': lengths,
            'thicknesses': [{'id': v.id, 'name': v.name} for v in thicknesses],
            'finishes': [{'id': v.id, 'name': v.aw_label(self.partner_id)}
                         for v in finishes],
            'cells': cells,
            'rates': rates,
            'currency': self.currency_id.symbol or '',
        }

    def aw_bars_grid_apply(self, template_id, cells):
        """cells: [{thickness_id, finish_id, length_ft, bars}] -- every cell
        of the grid. Whole numbers, 0 or more. Draft or sent orders only."""
        self.ensure_one()
        if self.state not in EDITABLE:
            raise UserError(_(
                "%s is confirmed. Bars cannot be changed from the grid; "
                "change the lines or make a new order.", self.name))
        template = self._aw_grid_template(template_id)
        thicknesses, finishes = self._aw_grid_values(template)
        lengths = self._aw_grid_lengths(template)
        Line = self.env['purchase.order.line']
        Variant = self.env['aw.profile.section.line']
        on_date = (self.date_order or fields.Datetime.now()).date()
        foot = Line._aw_foot()
        existing = self.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == template)
        wanted, to_remove = [], Line
        for cell in cells:
            bars = cell.get('bars') or 0
            if bars != int(bars) or bars < 0:
                raise UserError(_("Bars must be a whole number, 0 or more."))
            bars = int(bars)
            thickness = thicknesses.filtered(
                lambda v: v.id == cell.get('thickness_id'))
            finish = finishes.filtered(
                lambda v: v.id == cell.get('finish_id'))
            length = float(cell.get('length_ft') or 0)
            if not (thickness and finish) or not any(
                    abs(length - x) < 1e-6 for x in lengths):
                if bars:
                    raise UserError(_(
                        "%(product)s is not bought in %(ft)g ft bars here.",
                        product=template.display_name, ft=length))
                continue
            line = existing.filtered(
                lambda l: abs(l.aw_bar_length_ft - length) < 1e-6
                and self._aw_variant_values(l.product_id)
                == (thickness, finish))[:1]
            if bars:
                wanted.append((thickness, finish, length, bars, line))
            elif line:
                to_remove |= line
        for thickness, finish, length, bars, line in wanted:
            if line:
                if line.aw_bar_count != bars:
                    line.aw_bar_count = bars
                continue
            product = Variant._variant_for(template, thickness, finish)
            if not product:
                raise UserError(_(
                    "%(product)s cannot be made in %(thickness)s / "
                    "%(finish)s.", product=template.display_name,
                    thickness=thickness.name, finish=finish.name))
            price = Line._aw_rate_for(
                template, thickness, finish, self.partner_id, on_date) or 0.0
            Line.create({
                'order_id': self.id, 'product_id': product.id,
                'name': _("%(product)s: %(bars)s x %(ft)g ft bars",
                          product=product.display_name, bars=bars, ft=length),
                'aw_bar_length_ft': length, 'aw_bar_count': bars,
                'product_qty': bars * length, 'product_uom_id': foot.id,
                'price_unit': price, 'technical_price_unit': price,
                'date_planned': fields.Datetime.now(),
            })
        to_remove.unlink()
        return True
