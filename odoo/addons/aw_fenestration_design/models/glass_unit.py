# -*- coding: utf-8 -*-
"""One glass product per panel (G1).

A panel is glazed with ONE product: a finished unit defined in Inventory
(a sealed unit, toughened, frosted...) or a Glass Sheet variant. Which one:
the panel's own, else the window's default, else the profile spec's default.
The glass SIZE comes from the deduction rules and may be typed per panel
(flagged manual); the RATE is per sqft, and a rate typed on a panel stays a
manual override. The old build-up tables (`aw.glass.part`) are no longer
read by costing; G2 removes them.

The migration (`_migrate_glass_products`, once) turns a stack that was a
single sheet into its Glass Sheet variant and never invents a product for a
sealed unit or a protector: those panels are flagged `glass_choose` and
Checks says "choose a glass product".
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

MIGRATED_PARAM = 'aw_fenestration.glass_products_migrated'


def _glass_domain(records):
    category = records.env.ref(
        'aw_fenestration_core.product_category_glass',
        raise_if_not_found=False)
    return [('categ_id', 'child_of', category.id)] if category else [('id', '=', 0)]


class AwDesignLeaf(models.Model):
    _inherit = 'aw.design.leaf'

    glass_product_id = fields.Many2one(
        'product.product', string='Glass product', ondelete='restrict',
        domain=_glass_domain,
        help="This panel's own glass. Empty: it follows the window's.")
    glass_remark = fields.Char(
        string='Glass remark',
        help="Printed with the glass, e.g. 'was: Clear Tempered'.")
    glass_choose = fields.Boolean(
        string='Choose a glass product',
        help="This panel's glass was a sealed unit or a protector, which "
             "has no product yet: choose one. It does not follow the "
             "window until then.")
    glass_size_manual = fields.Boolean(
        string='Glass size typed',
        help="The glass size below was typed for this panel instead of "
             "coming from the deduction rules.")
    glass_w_mm = fields.Float(string='Glass width (mm)')
    glass_h_mm = fields.Float(string='Glass height (mm)')
    glass_rate_manual = fields.Boolean(string='Glass rate typed')
    glass_manual_rate = fields.Float(
        string='Glass rate / sqft', digits='Product Price')


    def _glass_rule_size(self):
        """(width, height) in mm of the glass the deduction rules gave this
        panel at the last explosion; (0, 0) while the size is typed or
        before there was one."""
        self.ensure_one()
        if self.glass_size_manual:
            return 0.0, 0.0
        design = self.row_id.design_id
        line = design.bom_line_ids.filtered(
            lambda l: l.kind == 'glass' and l.panel_no == self.panel_no)[:1]
        return (line.glass_w, line.glass_h) if line else (0.0, 0.0)


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    glass_product_id = fields.Many2one(
        'product.product', string='Default glass', ondelete='restrict',
        domain=_glass_domain,
        help="The glass a window of this spec starts with. A window or a "
             "panel can differ.")


class AwDesign(models.Model):
    _inherit = 'aw.design'

    glass_product_id = fields.Many2one(
        'product.product', string='Window glass', ondelete='restrict',
        domain=_glass_domain,
        help="The glass panels of this window follow. Empty: the spec's.")
    glass_remark = fields.Char(string='Glass remark')
    glass_choose = fields.Boolean(
        string='Choose a glass product',
        help="The window's glass was a sealed unit with no product yet.")

    # -- which product, what rate -------------------------------------------------
    def _glass_product_for(self, leaf=None):
        """The glass product of a panel (or of the window when no panel is
        given): its own, else the window's, else the spec's. Empty when it
        has to be chosen."""
        self.ensure_one()
        Product = self.env['product.product']
        if leaf is not None and leaf:
            if leaf.glass_product_id:
                return leaf.glass_product_id
            if leaf.glass_choose:
                return Product
        if self.glass_product_id:
            return self.glass_product_id
        if self.glass_choose:
            return Product
        return self.template_id.glass_product_id

    def _glass_remark_for(self, leaf=None):
        self.ensure_one()
        if leaf is not None and leaf and leaf.glass_product_id:
            return leaf.glass_remark or ''
        if self.glass_product_id:
            return self.glass_remark or ''
        return ''

    @api.model
    def _glass_unit_rate(self, product, on_date, vendor):
        """(rate per sqft, date, source) of a glass product: the NEWER of the
        glass vendor's list rate (a Glass Sheet variant has one) and the
        latest rate typed on the product; a tie goes to the typed one. A
        typed rate dated after the day costed is not yet in force. Nothing
        found: (0.0, False, '')."""
        candidates = []
        glass_type, mm = product._aw_glass_key()
        if glass_type and mm:
            rate = self.env['aw.glass.rate']._rate_for(
                glass_type, mm, on_date, vendor)
            if rate and rate.price:
                candidates.append((rate.date_from, 0, rate.price, 'list'))
        template = product.product_tmpl_id
        if template.aw_glass_latest_rate:
            dated = template.aw_glass_latest_rate_date
            if not dated or not on_date or dated <= on_date:
                candidates.append((
                    dated or fields.Date.to_date('1900-01-01'), 1,
                    template.aw_glass_latest_rate, 'latest'))
        if not candidates:
            return 0.0, False, ''
        date, _prio, price, source = max(candidates, key=lambda c: (c[0], c[1]))
        return price, date, source

    def _glass_products_payload(self):
        """The glass products a panel can be given, with the rate costing
        would use today (for display; the cost is always worked out on the
        server)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        vendor = self._glass_vendor()
        products = self.env['product.product'].search(
            _glass_domain(self), order='name')
        out = []
        for product in products:
            rate, date, source = self._glass_unit_rate(product, today, vendor)
            out.append({
                'id': product.id, 'name': product.display_name,
                'rate': rate, 'rate_date': date.isoformat() if date else '',
                'source': source})
        return out

    def _glass_product_named(self, name):
        Product = self.env['product.product']
        if not name:
            return Product
        return Product.search(
            _glass_domain(self) + [('name', '=ilike', name)], limit=1)

    # -- suggestions (Lake City schedule) ----------------------------------------------
    def _suggest_glass(self):
        """Fill the glass of panels that have none, by NAME: a rule's
        suggestion ('6+10+8 Clear Tempered') is used only when a glass
        product of that name exists in Inventory. Nothing is invented. The
        thresholds are untouched."""
        for design in self:
            if not (design.suggest_glass
                    and design.family_id.glazing == 'double'):
                continue
            default = design._glass_product_for(None)
            for leaf in design._all_panels():
                if leaf.leaf_type_id.code == 'MESH' or (
                        leaf.infill_type_id
                        and not leaf.infill_type_id.uses_glass):
                    continue
                if leaf.glass_chosen or (
                        leaf.glass_product_id and not leaf.glass_suggested):
                    continue          # chosen by hand: never replaced
                product = design._glass_product_named(
                    design._suggested_glass_for(leaf))
                if product and product != default:
                    leaf.write({
                        'glass_product_id': product.id, 'glass_choose': False,
                        'glass_suggested': True, 'glass_remark': False,
                        'glass_rate_manual': False, 'glass_manual_rate': 0.0})
                elif leaf.glass_product_id or leaf.glass_suggested:
                    # nothing to suggest: a previous suggestion is withdrawn
                    leaf.write({'glass_product_id': False,
                                'glass_suggested': False})

    # -- text on quotes and drawings ----------------------------------------------------
    def _glass_stack_text(self, leaf=None):
        """The glass as printed on a quote or a shop drawing: the product,
        with its remark ('was: Clear Tempered') so a frosted glass is never
        printed as plain Clear."""
        self.ensure_one()
        product = self._glass_product_for(leaf)
        text = product.display_name or ''
        remark = self._glass_remark_for(leaf)
        return '%s (%s)' % (text, remark) if text and remark else text

    # -- the glass section of Checks ------------------------------------------------------
    def _glass_choose_problems(self, exploded):
        """One warning per panel that takes glass and has no glass product,
        leading to the panel's glass."""
        problems = []
        seen = set()
        for values in exploded or []:
            if values.get('kind') == 'glass' and values.get('missing_glass'):
                panel = values.get('panel_no') or 0
                if panel in seen:
                    continue
                seen.add(panel)
                problems.append(('warning', _(
                    "Panel %(panel)s: choose a glass product. Its glass is "
                    "not in the price until one is chosen.", panel=panel),
                    self._target('glass', panel)))
        return problems

    # -- one-time migration ------------------------------------------------------------
    def _register_hook(self):
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._migrate_glass_products()
        except Exception:
            _logger.exception(
                "aw_fenestration_design: glass product migration failed")

    @api.model
    def _migrate_glass_products(self):
        """Once. A stack that was ONE sheet becomes its Glass Sheet variant
        (a variant that does not exist yet is not made here: the panel is
        flagged instead); a sealed unit or a protector gets no invented
        product and is flagged `glass_choose`. A typed rate and a remark
        move with the sheet. Nothing is deleted: the old rows stay until G2.
        Fill-only, so a rerun after a failure changes nothing it did."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(MIGRATED_PARAM):
            return {}
        Type = self.env['aw.glass.type']
        counts = {'specs': 0, 'windows': 0, 'panels': 0, 'flagged': 0}

        def variant_of(parts):
            """The product of a stack that is a single sheet, else empty."""
            if len(parts) != 1 or parts.kind != 'sheet' \
                    or not (parts.glass_type_id and parts.thickness_mm):
                return self.env['product.product']
            return Type.browse(parts.glass_type_id.id)._variant_for(
                parts.thickness_mm, create=False)

        for spec in self.env['aw.window.template'].with_context(
                active_test=False).search([('glass_part_ids', '!=', False)]):
            if spec.glass_product_id:
                continue
            product = variant_of(spec.glass_part_ids)
            if product:
                spec.glass_product_id = product
                counts['specs'] += 1

        for design in self.with_context(active_test=False).search([]):
            parts = design.glass_part_ids
            if parts and not design.glass_product_id and not design.glass_choose:
                product = variant_of(parts)
                if product:
                    design.write({'glass_product_id': product.id,
                                  'glass_remark': parts.remark or False})
                    counts['windows'] += 1
                else:
                    design.glass_choose = True
                    counts['flagged'] += 1
            for leaf in design._all_panels():
                parts = leaf.glass_part_ids
                if not parts or leaf.glass_product_id or leaf.glass_choose:
                    continue
                product = variant_of(parts)
                if product:
                    leaf.write({
                        'glass_product_id': product.id,
                        'glass_remark': parts.remark or False,
                        'glass_rate_manual': parts.rate_manual,
                        'glass_manual_rate': parts.manual_rate
                        if parts.rate_manual else 0.0})
                    counts['panels'] += 1
                else:
                    leaf.glass_choose = True
                    counts['flagged'] += 1
        param.set_param(MIGRATED_PARAM, '1')
        _logger.info(
            "aw_fenestration_design: glass products: %(specs)s spec(s), "
            "%(windows)s window(s), %(panels)s panel(s) moved to a product; "
            "%(flagged)s to choose.", counts)
        return counts
