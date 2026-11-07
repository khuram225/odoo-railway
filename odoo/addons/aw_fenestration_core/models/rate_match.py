# -*- coding: utf-8 -*-
"""Match a Review row to a product on the spot (3c of the template flow).

A row the vendor wrote a code for that we have no profile under shows in
Review as "Not written" with a Match button (Rates manager only). The dialog
shows both names, the vendor's code and our profile; it WARNS, never stops, when
our profile is not listed by this vendor under the row's series; and it has a
box "Remember this code for this vendor", unticked, which saves a vendor code
alias so the next list matches the same code by itself. Each remembered code is
logged on the list's chatter with the user and the date, listed in the Review
summary, and removable from the vendor's layout.

Matching changes what Confirm will write, so the review is rebuilt (and the
"I checked these price changes" tick is asked again).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

RATES_GROUP = 'aw_fenestration_core.group_rates_manager'


def profile_domain(env):
    return [('categ_id', 'child_of',
             env.ref('aw_fenestration_core.product_category_profiles').id)]


class AwVendorAliasLogged(models.Model):
    _inherit = 'aw.vendor.alias'
    _order = 'vendor_id, code_norm'

    code = fields.Char(
        string="Vendor's code", help="The code as the vendor wrote it.")
    rate_list_id = fields.Many2one(
        'aw.vendor.rate.list', string="Remembered on list",
        ondelete='set null', copy=False)
    added_by = fields.Many2one(
        'res.users', string="Added by", related='create_uid')
    added_on = fields.Datetime(string="Added on", related='create_date')


class AwVendorRateReviewMatch(models.Model):
    _inherit = 'aw.vendor.rate.review'

    can_match = fields.Boolean(readonly=True)

    def action_match_product(self):
        self.ensure_one()
        if not self.env.user.has_group(RATES_GROUP):
            raise UserError(_("Only a Rates manager can match a row."))
        return self.line_id.action_match_product()


class AwVendorRateListLineMatch(models.Model):
    _inherit = 'aw.vendor.rate.list.line'

    def action_match_product(self):
        """The one door to choosing a product for a row, from Review and from
        the grid alike."""
        self.ensure_one()
        if not self.env.user.has_group(RATES_GROUP):
            raise UserError(_("Only a Rates manager can match a row."))
        if self.list_id.state != 'draft' or self.list_id.kind != 'profile':
            raise UserError(_("Only a row of a draft profile list can be "
                              "matched to a product."))
        wizard = self.env['aw.vendor.rate.match.wizard'].create({
            'line_id': self.id})
        return {
            'type': 'ir.actions.act_window', 'name': _("Match to product"),
            'res_model': wizard._name, 'res_id': wizard.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new'}


class AwVendorRateListMatch(models.Model):
    _inherit = 'aw.vendor.rate.list'

    alias_ids = fields.One2many('aw.vendor.alias', 'rate_list_id')
    remembered_summary = fields.Char(compute='_compute_remembered_summary')

    @api.depends('alias_ids', 'alias_ids.product_tmpl_id')
    def _compute_remembered_summary(self):
        for rec in self:
            rec.remembered_summary = _(
                "Remembered for %(vendor)s on this list: %(codes)s. Remove "
                "any of them under Vendor Layouts.",
                vendor=rec.vendor_id.display_name,
                codes='; '.join(
                    '%s = %s (%s, %s)' % (
                        a.code or a.code_norm,
                        a.product_tmpl_id.default_code or
                        a.product_tmpl_id.display_name,
                        a.create_uid.name,
                        fields.Date.to_string(a.create_date))
                    for a in rec.alias_ids)) if rec.alias_ids else False


class AwVendorLayoutAliases(models.Model):
    _inherit = 'aw.vendor.layout'

    alias_count = fields.Integer(compute='_compute_alias_count')

    @api.depends('vendor_id')
    def _compute_alias_count(self):
        Alias = self.env['aw.vendor.alias']
        for rec in self:
            rec.alias_count = Alias.search_count(
                [('vendor_id', '=', rec.vendor_id.id)])

    def action_open_aliases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Remembered codes: %s", self.vendor_id.display_name),
            'res_model': 'aw.vendor.alias', 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('vendor_id', '=', self.vendor_id.id)],
            'context': {'default_vendor_id': self.vendor_id.id}}


class AwVendorRateMatchWizard(models.TransientModel):
    _name = 'aw.vendor.rate.match.wizard'
    _description = 'Match a rate list row to a product'

    line_id = fields.Many2one(
        'aw.vendor.rate.list.line', required=True, ondelete='cascade')
    vendor_code = fields.Char(related='line_id.code', string="Vendor's code")
    thickness = fields.Char(related='line_id.thickness_text')
    row_series = fields.Char(related='line_id.series',
                             string="Series on the row")
    product_tmpl_id = fields.Many2one(
        'product.template', string="Our profile",
        domain=lambda self: profile_domain(self.env))
    both_names = fields.Char(compute='_compute_both')
    remember = fields.Boolean(
        string="Remember this code for this vendor", default=False)
    series_warning = fields.Char(compute='_compute_warning')
    already = fields.Char(compute='_compute_warning')

    @api.depends('vendor_code', 'product_tmpl_id')
    def _compute_both(self):
        for wiz in self:
            product = wiz.product_tmpl_id
            wiz.both_names = _(
                "%(vendor)s's \"%(code)s\" = our %(product)s",
                vendor=wiz.line_id.list_id.vendor_id.display_name,
                code=wiz.vendor_code or '',
                product=product.display_name) if product else False

    @api.depends('product_tmpl_id', 'remember', 'line_id')
    def _compute_warning(self):
        Rate = self.env['aw.profile.rate']
        Alias = self.env['aw.vendor.alias']
        for wiz in self:
            wiz.series_warning = wiz.already = False
            line = wiz.line_id
            product = wiz.product_tmpl_id
            if not (line and product):
                continue
            vendor = line.list_id.vendor_id
            listed = {r.vendor_series.strip().upper() for r in Rate.search([
                ('vendor_id', '=', vendor.id),
                ('product_tmpl_id', '=', product.id)]) if r.vendor_series}
            series = (line.series or '').strip()
            if series and listed and series.upper() not in listed:
                wiz.series_warning = _(
                    "Check this is the right profile: %(vendor)s lists "
                    "%(product)s under %(listed)s, but this row says "
                    "%(series)s.", vendor=vendor.display_name,
                    product=product.display_name,
                    listed=', '.join(sorted(listed)), series=series)
            found = Alias.search([
                ('vendor_id', '=', vendor.id),
                ('code_norm', '=', line.code_norm),
                ('thickness_text', 'in', [False, ''])], limit=1)
            if found and wiz.remember and found.product_tmpl_id != product:
                wiz.already = _(
                    "%(code)s is already remembered as %(old)s; this replaces "
                    "it.", code=line.code, old=found.product_tmpl_id.display_name)

    def action_match(self):
        self.ensure_one()
        if not self.env.user.has_group(RATES_GROUP):
            raise UserError(_("Only a Rates manager can match a row."))
        if not self.product_tmpl_id:
            raise UserError(_("Pick our profile first."))
        line = self.line_id
        rate_list = line.list_id
        if rate_list.state != 'draft':
            raise UserError(_("This list is already applied."))
        product = self.product_tmpl_id
        # a match does not make the review on screen untrue by itself: it is
        # rebuilt below, so the reset that any edit of a row causes is skipped
        line.with_context(aw_auto_match=True).write({
            'product_tmpl_id': product.id, 'match_source': 'manual'})
        line._auto_match()           # the thickness, now the product is known
        line._refresh_need()
        today = fields.Date.to_string(fields.Date.context_today(self))
        who = self.env.user.name
        body = _("%(who)s matched %(vendor)s's \"%(code)s\" to %(product)s "
                 "on %(date)s.", who=who,
                 vendor=rate_list.vendor_id.display_name, code=line.code,
                 product=product.display_name, date=today)
        if self.remember:
            Alias = self.env['aw.vendor.alias']
            found = Alias.search([
                ('vendor_id', '=', rate_list.vendor_id.id),
                ('code_norm', '=', line.code_norm),
                ('thickness_text', 'in', [False, ''])], limit=1)
            values = {'product_tmpl_id': product.id, 'code': line.code,
                      'rate_list_id': rate_list.id}
            if found:
                found.write(values)
            else:
                Alias.create(dict(
                    values, vendor_id=rate_list.vendor_id.id,
                    code_norm=line.code_norm, thickness_text=False))
            body += ' ' + _("Remembered for this vendor: the same code is "
                            "matched to it on every later list.")
        else:
            body += ' ' + _("This list only; not remembered.")
        rate_list.message_post(body=body)
        message = _("Matched.")
        if rate_list.step == 'review':
            rate_list._store_review(rate_list._review_data())
            message = _("Matched. The review was rebuilt: check the price "
                        "changes again before Confirm.")
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("Matched"), 'type': 'success', 'sticky': False,
                'message': message,
                'next': {'type': 'ir.actions.act_window_close'}}}
