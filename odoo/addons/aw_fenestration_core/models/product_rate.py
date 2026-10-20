# -*- coding: utf-8 -*-
"""What a profile variant costs per foot, and the cost field it feeds.

The rate lives on `aw.profile.rate` and is looked up per
template + thickness + finish. A variant IS that combination, so it can
show its own rate without anyone joining the two by hand.

Computed and NOT stored on purpose: the rate in force changes with the
date and with every price-list import, and a stored copy would be
quietly wrong the morning after. `standard_price` is the stored one,
and it is only ever written deliberately -- by the import, by the
button, or when a variant is first created.
"""
import logging

from odoo import _, api, fields, models
from odoo.tools import float_compare

from .variant_codes import variant_reference

_logger = logging.getLogger(__name__)

# Profiles are stocked, costed and bought in FEET, the unit the vendor
# rates are quoted in, so a rate and a cost are the same number.


class ProductProduct(models.Model):
    _inherit = 'product.product'

    aw_rate_per_ft = fields.Float(
        string='Rate / ft', compute='_compute_aw_rate',
        digits='Product Price',
        help="The profile rate in force today for this exact "
             "thickness and finish. Zero means no rate covers it.")
    aw_rate_date = fields.Date(
        string='Rate Of', compute='_compute_aw_rate',
        help="Effective date of the rate above, so an unexpected cost "
             "can be traced to the list it came from.")
    aw_has_rate = fields.Boolean(compute='_compute_aw_rate')
    aw_rate_basis = fields.Char(
        string='Rate basis', compute='_compute_aw_rate',
        help="Which match the rate came from: this exact thickness and "
             "finish, the thickness in any finish, or the profile in any "
             "thickness and finish. Empty when there is no rate.")
    aw_thickness_name = fields.Char(
        string='Thickness', compute='_compute_aw_attribute_names')
    aw_finish_name = fields.Char(
        string='Finish', compute='_compute_aw_attribute_names')

    @api.depends('product_template_variant_value_ids')
    def _compute_aw_attribute_names(self):
        for variant in self:
            thickness = finish = ''
            for value in variant.product_template_variant_value_ids:
                if value.attribute_id.name == 'Thickness':
                    thickness = value.name
                elif value.attribute_id.name == 'Finish':
                    finish = value.name
            variant.aw_thickness_name = thickness
            variant.aw_finish_name = finish

    def _aw_fill_reference(self):
        """code-thickness-finish, only where empty and only when every
        value has an abbreviation in the table. True when it was set."""
        self.ensure_one()
        if self.default_code:
            return False
        thickness, finish = self._aw_attribute_values()
        reference, _missing = variant_reference(
            self.product_tmpl_id.name, thickness.name, finish.name)
        if not reference:
            return False
        self.default_code = reference
        return True

    @api.model_create_multi
    def create(self, vals_list):
        variants = super().create(vals_list)
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles',
            raise_if_not_found=False)
        if category and not self.pool._init:
            for variant in variants.filtered(
                    lambda v: v.categ_id.parent_path
                    and category.parent_path
                    and v.categ_id.parent_path.startswith(
                        category.parent_path)):
                variant._aw_fill_reference()
        return variants

    def _aw_attribute_values(self):
        """The plain attribute values behind this variant's combination.

        `product.template.attribute.value` is the template-scoped
        wrapper; `aw.profile.rate` stores the plain
        `product.attribute.value`, so the mapping has to be made here
        rather than comparing the two directly.
        """
        self.ensure_one()
        empty = self.env['product.attribute.value']
        thickness = finish = empty
        for value in self.product_template_variant_value_ids:
            name = value.attribute_id.name
            if name == 'Thickness':
                thickness = value.product_attribute_value_id
            elif name == 'Finish':
                finish = value.product_attribute_value_id
        return thickness, finish

    @api.depends('product_template_variant_value_ids', 'product_tmpl_id')
    def _compute_aw_rate(self):
        today = fields.Date.context_today(self)
        rates = self.env['aw.profile.rate']
        vendors = {}
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness',
            raise_if_not_found=False)
        for variant in self:
            thickness, finish = variant._aw_attribute_values()
            template = variant.product_tmpl_id
            # The series' default vendor: what the variant's own rate
            # fields (and its cost field) follow.
            if template.id not in vendors:
                vendors[template.id] = template._aw_default_vendor()
            # Costing's own rule for a profile with no thickness chosen:
            # one sold in exactly one thickness has nothing to choose, so
            # that is its thickness. A variant made without a thickness
            # value then finds the rate costing finds.
            if not thickness and thickness_attr:
                offered = self.env['aw.profile.section.line']._template_values(
                    template, thickness_attr)
                if len(offered) == 1:
                    thickness = offered
            # The same lookup costing uses, fallbacks included.
            rate, level = rates._rate_lookup(
                template, thickness, finish, today, vendors[template.id])
            variant.aw_rate_basis = {
                'exact': _('exact thickness and finish'),
                'thickness': _('thickness only, any finish'),
                'template': _('profile, any thickness and finish'),
            }.get(level, '')
            variant.aw_rate_per_ft = rate.price if rate else 0.0
            variant.aw_rate_date = rate.date_from if rate else False
            variant.aw_has_rate = bool(rate)
            variant.aw_cost_from_rate = rate.price if rate else 0.0

    # ------------------------------------------------------------------
    aw_cost_from_rate = fields.Float(
        string='Cost / ft from rate', compute='_compute_aw_rate',
        digits='Product Price',
        help="What the cost would be if written from the current rate. "
             "Shown even when the costing method forbids writing it.")
    aw_cost_sync_allowed = fields.Boolean(
        compute='_compute_aw_cost_sync_allowed')
    aw_cost_method = fields.Char(
        string='Costing Method', compute='_compute_aw_cost_sync_allowed')

    # NOT @api.depends('cost_method'): that field belongs to
    # stock_account, which this module does not depend on, and naming a
    # field that may not exist breaks the registry at load. See
    # _aw_cost_method().
    @api.depends('product_tmpl_id')
    def _compute_aw_cost_sync_allowed(self):
        """Only Standard Price costing owns standard_price.

        Under AVCO the field IS the running average that stock
        valuation maintains, and under FIFO it is a leftover that
        valuation ignores. Writing either from a supplier rate does not
        just put a wrong number on screen -- `_change_standard_price()`
        turns a change under AVCO into an inventory revaluation, so the
        stock ledger would move because a price list was imported.
        """
        for variant in self:
            method = variant.product_tmpl_id._aw_cost_method()
            variant.aw_cost_method = method
            variant.aw_cost_sync_allowed = method == 'standard'

    def _aw_sync_cost_from_rate(self):
        """Write standard_price from the rate, per foot.

        Returns (updated, blocked). Two things are deliberately never
        written:

        - a variant with NO rate is left alone rather than zeroed: a
          hand-entered cost is worth more than a zero this module is
          confident about;
        - a variant whose product is costed AVCO or FIFO is left alone
          whatever its rate, because there standard_price belongs to
          stock valuation.
        """
        updated = blocked = self.env['product.product']
        for variant in self:
            if not variant.aw_has_rate:
                continue
            if not variant.aw_cost_sync_allowed:
                blocked |= variant
                continue
            cost = variant.aw_rate_per_ft
            if float_compare(variant.standard_price, cost,
                             precision_digits=4) != 0:
                variant.standard_price = cost
                updated |= variant
        return updated, blocked

    def action_aw_update_costs_from_rates(self):
        """Cost from the current rate, for these variants."""
        variants = self
        updated, blocked = variants._aw_sync_cost_from_rate()

        if blocked:
            labels = {'average': 'AVCO', 'fifo': 'FIFO',
                      'standard': 'Standard Price'}
            methods = ', '.join(sorted({
                labels.get(variant.aw_cost_method, variant.aw_cost_method)
                for variant in blocked}))
            message = _(
                "Nothing written: %(count)s variant(s) are costed by "
                "%(methods)s, where stock valuation owns the Cost field. "
                "Writing it from a supplier rate would revalue your "
                "stock. The rate per foot is still shown for reference.",
                count=len(blocked), methods=methods)
            kind = 'warning'
        else:
            message = _(
                "%(done)s variant cost(s) updated from the current "
                "rates.", done=len(updated))
            kind = 'success' if updated else 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': kind,
                'message': message,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _aw_default_vendor(self):
        """The default vendor of the first series whose mapping uses this
        profile, else the vendor every rate belonged to before vendors
        (so a profile in no series still shows its rate)."""
        self.ensure_one()
        lines = self.env['aw.profile.section.line'].search([
            ('is_used', '=', True), ('spec_id', '!=', False),
            '|', ('product_tmpl_id', '=', self.id),
            ('alternate_product_ids', 'in', self.id)], order='spec_id')
        for line in lines:
            if line.spec_id.default_vendor_id:
                return line.spec_id.default_vendor_id
        return self.env['aw.profile.rate']._legacy_vendor()

    aw_current_rate_ids = fields.One2many(
        'aw.profile.rate', compute='_compute_aw_current_rate_ids',
        string='Current Rates')

    # No depends: this reads a whole other table on today's date, which
    # @api.depends cannot express. Same pattern as aw.design.length_uom
    # reading ir.config_parameter -- a compute whose input is context
    # rather than sibling fields.
    @api.depends()
    def _compute_aw_current_rate_ids(self):
        """Every rate in force today for this profile.

        Built from aw.profile.rate, NOT from the variants that happen to
        exist: the question a buyer asks is "what does Chawla price this
        profile at", and answering it from variants would silently omit
        every combination nobody has quoted yet. `variant_exists` says
        which ones have been used, rather than the table quietly
        dropping them.
        """
        today = fields.Date.context_today(self)
        rates = self.env['aw.profile.rate']
        for template in self:
            template.aw_current_rate_ids = rates.search([
                ('product_tmpl_id', '=', template.id),
                ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
            ], order='thickness_id, finish_id, date_from desc')

    aw_cost_sync_allowed = fields.Boolean(
        compute='_compute_aw_cost_sync_allowed',
        help="False when the costing method is AVCO or FIFO, where "
             "stock valuation owns the cost field.")
    aw_cost_method = fields.Char(
        string='Costing Method', compute='_compute_aw_cost_sync_allowed')

    def _aw_cost_method(self):
        """The costing method, safely.

        `cost_method` is defined by **stock_account**, which this module
        deliberately does not depend on -- pulling in stock valuation
        and its accounting just to read one selection would be a heavy
        price. Without that module there is no valuation to corrupt, so
        the cost field is ours to write and 'standard' is the honest
        answer.

        Checking `_fields` rather than try/except because a missing
        field is a normal configuration here, not an error.
        """
        self.ensure_one()
        if 'cost_method' not in self._fields:
            return 'standard'
        return self.cost_method or 'standard'

    # No depends on cost_method, for the reason above.
    @api.depends()
    def _compute_aw_cost_sync_allowed(self):
        for template in self:
            method = template._aw_cost_method()
            template.aw_cost_method = method
            template.aw_cost_sync_allowed = method == "standard"

    def action_aw_update_costs_from_rates(self):
        """Cost from the current rate, for this template's variants.

        Delegates to product.product so there is ONE implementation.
        The button also has to exist here because
        `product.product_normal_form_view` is a primary inherit of the
        product.template form on model product.product -- a button
        added to the template form lands on the variant form too, and
        the Upgrade refuses it if the method is missing there.
        """
        return self.mapped(
            'product_variant_ids').action_aw_update_costs_from_rates()

    # ------------------------------------------------------------------
    # one-shot data cleanup: duplicate attribute lines, unit, cost, refs
    # ------------------------------------------------------------------
    def _register_hook(self):
        """After every module has loaded; savepoint, and logged rather
        than raised, because this also runs on every ordinary start."""
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._aw_variant_data_cleanup()
        except Exception:
            _logger.exception("aw_fenestration_core: variant cleanup failed")

    def _aw_profile_templates(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles',
            raise_if_not_found=False)
        if not category:
            return self.browse()
        return self.with_context(active_test=False).search(
            [('categ_id', 'child_of', category.id)])

    @api.model
    def _aw_variant_data_cleanup(self):
        """Merge duplicate attribute lines, move profiles to feet, bring
        costs in line with the rates, fill internal references. Each step
        is its own one-shot parameter so a failure in one does not repeat
        or block the others."""
        param = self.env['ir.config_parameter'].sudo()
        report = {}
        if not param.get_param('aw_fenestration.attr_lines_merged'):
            report['merge'] = self._aw_merge_duplicate_attribute_lines()
            param.set_param('aw_fenestration.attr_lines_merged', '1')
        if not param.get_param('aw_fenestration.profiles_in_feet'):
            report['feet'] = self._aw_move_profiles_to_feet()
            param.set_param('aw_fenestration.profiles_in_feet', '1')
        if not param.get_param('aw_fenestration.profile_costs_synced_ft'):
            report['costs'] = self._aw_sync_all_profile_costs()
            param.set_param('aw_fenestration.profile_costs_synced_ft', '1')
        if not param.get_param('aw_fenestration.profile_costs_synced_fallback'):
            report['costs_fallback'] = self._aw_sync_all_profile_costs()
            param.set_param(
                'aw_fenestration.profile_costs_synced_fallback', '1')
        if not param.get_param('aw_fenestration.variant_refs_filled'):
            report['refs'] = self._aw_fill_variant_references()
            param.set_param('aw_fenestration.variant_refs_filled', '1')
        if report:
            param.set_param('aw_fenestration.variant_cleanup_report',
                            repr(report))
            _logger.info("aw_fenestration_core: variant cleanup: %s", report)
        return report

    @api.model
    def _aw_merge_duplicate_attribute_lines(self):
        """One line per attribute per template, variants untouched.

        The lowest-id line is kept. A variant that pointed at a surplus
        line's value now points at the kept line's matching value (it
        already did, in the cases seen, since variants were made against
        every duplicate), then the surplus lines go. Variant ids do not
        change, so rates, BOM lines and aliases keep their target.
        """
        cr = self.env.cr
        cr.execute("""
            SELECT product_tmpl_id, attribute_id, array_agg(id ORDER BY id)
              FROM product_template_attribute_line WHERE active
             GROUP BY 1, 2 HAVING count(*) > 1""")
        groups = cr.fetchall()
        Line = self.env['product.template.attribute.line']
        Variant = self.env['product.product'].with_context(active_test=False)
        removed = rewritten = 0
        templates = self.browse()
        for template_id, _attribute_id, ids in groups:
            keep, dups = ids[0], ids[1:]
            kept = Line.browse(keep)
            surplus = Line.browse(dups)
            # values the surplus lines had that the kept one lacks
            missing = surplus.value_ids - kept.value_ids
            if missing:
                kept.write({'value_ids': [(4, v.id) for v in missing]})
            self.env.flush_all()
            cr.execute("""
                INSERT INTO product_variant_combination
                       (product_product_id, product_template_attribute_value_id)
                SELECT c.product_product_id, k.id
                  FROM product_variant_combination c
                  JOIN product_template_attribute_value d
                    ON d.id = c.product_template_attribute_value_id
                  JOIN product_template_attribute_value k
                    ON k.attribute_line_id = %s
                   AND k.product_attribute_value_id = d.product_attribute_value_id
                 WHERE d.attribute_line_id = ANY(%s)
                ON CONFLICT DO NOTHING""", (keep, dups))
            cr.execute("""
                DELETE FROM product_variant_combination
                 WHERE product_template_attribute_value_id IN (
                       SELECT id FROM product_template_attribute_value
                        WHERE attribute_line_id = ANY(%s))""", (dups,))
            rewritten += cr.rowcount
            self.env.invalidate_all()
            variants = Variant.search([('product_tmpl_id', '=', template_id)])
            variants._compute_combination_indices()
            self.env.flush_all()
            surplus.unlink()
            removed += len(dups)
            templates |= self.browse(template_id)
        return {'groups': len(groups), 'lines_removed': removed,
                'combination_rows_removed': rewritten,
                'templates': templates.mapped('name')}

    @api.model
    def _aw_move_profiles_to_feet(self):
        """Profiles are bought and costed per running foot: the foot UoM
        (archived by default) is switched on and set on every profile.
        There is no purchase UoM on a product template in this version;
        that lives on a vendor pricelist line, which is not used here."""
        foot = self.env.ref('uom.product_uom_foot')
        if not foot.active:
            foot.sudo().active = True
        templates = self._aw_profile_templates().filtered(
            lambda t: t.uom_id != foot)
        if templates:
            templates.write({'uom_id': foot.id})
        return {'templates_moved': len(templates)}

    @api.model
    def _aw_sync_all_profile_costs(self):
        """Cost per foot = the series' default vendor's rate per foot, for
        every profile variant that exists and has a rate (fallbacks
        included, as in costing)."""
        variants = self._aw_profile_templates().product_variant_ids
        had_no_cost = variants.filtered(lambda v: not v.standard_price)
        variants.invalidate_recordset()
        updated, blocked = variants._aw_sync_cost_from_rate()
        no_rate = variants.filtered(lambda v: not v.aw_has_rate)
        return {'variants': len(variants), 'updated': len(updated),
                'blocked': len(blocked), 'without_rate': len(no_rate),
                'had_no_cost': len(had_no_cost),
                'now_costed': len(had_no_cost.filtered('standard_price')),
                'by_basis': {
                    basis: len(variants.filtered(
                        lambda v, b=basis: v.aw_rate_basis == b))
                    for basis in set(variants.mapped('aw_rate_basis'))}}

    @api.model
    def _aw_fill_variant_references(self):
        """code-thickness-finish where a variant has no reference."""
        done, unmapped = 0, {}
        variants = self._aw_profile_templates().product_variant_ids.filtered(
            lambda v: not v.default_code)
        for variant in variants:
            if variant._aw_fill_reference():
                done += 1
            else:
                thickness, finish = variant._aw_attribute_values()
                reference, missing = variant_reference(
                    variant.product_tmpl_id.name, thickness.name, finish.name)
                for name in missing:
                    unmapped[name] = unmapped.get(name, 0) + 1
        return {'filled': done, 'values_not_in_table': unmapped}
