# -*- coding: utf-8 -*-
"""The bar lengths a vendor sells a profile in.

Cut planning used to take one list for the whole business
(aw.cut.plan stock_lengths_ft setting). Vendors differ, so a quote now plans
with the ACTIVE lengths of its profile vendor. A vendor with no rows at all
falls back to that global list, which is why this changes nothing until a row
differs; a vendor with rows but none active is a stop, not a fallback,
because switching every length off means "we cannot buy from them", not "use
the default".

A row may name a PROFILE (the product template); blank means every profile of
the vendor. For one profile and vendor: the profile's own active rows, else the
vendor-wide active rows, else (no vendor-wide rows at all) the global list. A
profile whose own rows are all off stops that profile only.

Its own model rather than a field on res.partner: a stored field on a core
model read on every request is what took the site down once (see CLAUDE.md).
Every change is written on the vendor's chatter with the user and the date.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SEEDED_PARAM = 'aw_fenestration.vendor_bar_lengths_seeded'


class AwVendorBarLength(models.Model):
    _name = 'aw.vendor.bar.length'
    _description = 'Vendor Bar Length'
    _order = 'vendor_id, length_ft'

    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True,
        ondelete='cascade')
    product_tmpl_id = fields.Many2one(
        'product.template', string='Set profile', index=True,
        ondelete='cascade',
        domain=lambda self: self._profile_domain(),
        help="Leave blank for every profile of this vendor.")
    profile_label = fields.Char(
        string='Profile', compute='_compute_profile_label')
    length_ft = fields.Float(string='Bar length (ft)', required=True)
    active = fields.Boolean(default=True)
    # Form only, never stored: "this length exists but is switched off".
    inactive_twin_note = fields.Char(
        compute='_compute_inactive_twin_note')
    switch_on_existing = fields.Boolean(
        string='Switch the existing one on instead', store=False)

    @api.model
    def _profile_domain(self):
        category = self.env.ref(
            'aw_fenestration_core.product_category_profiles',
            raise_if_not_found=False)
        return [('categ_id', 'child_of', category.id)] if category else []

    def _twins(self, vendor, template, length, exclude=None):
        """Rows (active or not) of the same vendor, profile and length."""
        rows = self.with_context(active_test=False).search([
            ('vendor_id', '=', vendor.id),
            ('product_tmpl_id', '=', template.id or False)])
        if exclude:
            rows -= exclude
        return rows.filtered(lambda o: abs(o.length_ft - length) < 1e-6)

    @api.depends('vendor_id', 'product_tmpl_id', 'length_ft', 'active')
    def _compute_inactive_twin_note(self):
        for rec in self:
            twin = rec._twins(
                rec.vendor_id, rec.product_tmpl_id, rec.length_ft,
                exclude=rec) if rec.vendor_id and rec.length_ft > 0 \
                else self.browse()
            off = twin.filtered(lambda o: not o.active)
            rec.inactive_twin_note = _(
                "A %(ft)g ft bar for %(profile)s exists but is switched "
                "off.", ft=rec.length_ft,
                profile=rec.product_tmpl_id.display_name or _(
                    "all profiles")) if off and not rec.id else False

    @api.depends('product_tmpl_id')
    def _compute_profile_label(self):
        for rec in self:
            rec.profile_label = (
                rec.product_tmpl_id.display_name or _("All profiles"))

    @api.constrains('vendor_id', 'product_tmpl_id', 'length_ft', 'active')
    def _check_length(self):
        for rec in self:
            if rec.length_ft <= 0:
                raise ValidationError(_("A bar length must be more than 0."))
            twin = self._twins(rec.vendor_id, rec.product_tmpl_id,
                               rec.length_ft, exclude=rec)
            if twin:
                profile = rec.product_tmpl_id.display_name or _(
                    "all profiles")
                if twin.filtered(lambda o: not o.active):
                    raise ValidationError(_(
                        "%(vendor)s already has a %(ft)g ft bar for "
                        "%(profile)s, and it is switched off. Switch it on "
                        "with its toggle in the Bar Lengths list, or tick "
                        "'Switch the existing one on instead' when adding.",
                        vendor=rec.vendor_id.display_name, ft=rec.length_ft,
                        profile=profile))
                raise ValidationError(_(
                    "%(vendor)s already has a %(ft)g ft bar for %(profile)s.",
                    vendor=rec.vendor_id.display_name, ft=rec.length_ft,
                    profile=profile))

    # -- who changed what, on the vendor's chatter -------------------------
    def _log(self, vendor, text):
        if self.env.context.get('aw_no_log'):
            return
        vendor.sudo().message_post(
            body=text, author_id=self.env.user.partner_id.id,
            subtype_xmlid='mail.mt_note')

    @api.model_create_multi
    def create(self, vals_list):
        # "Switch the existing one on instead": an identical switched-off row
        # is turned on rather than a second one refused or made.
        revived, fresh = self.browse(), []
        for vals in vals_list:
            vals = dict(vals)
            if vals.pop('switch_on_existing', False):
                twin = self._twins(
                    self.env['res.partner'].browse(vals.get('vendor_id')),
                    self.env['product.template'].browse(
                        vals.get('product_tmpl_id') or False),
                    vals.get('length_ft') or 0.0).filtered(
                    lambda o: not o.active)[:1]
                if twin:
                    twin.write({'active': True})
                    revived |= twin
                    continue
            fresh.append(vals)
        records = super().create(fresh) if fresh else self.browse()
        for rec in records:
            self._log(rec.vendor_id, _(
                "Bar length %(ft)g ft (%(profile)s) added by %(who)s on %(when)s.",
                ft=rec.length_ft, profile=rec.profile_label, who=self.env.user.name,
                when=fields.Datetime.now()))
        return records | revived

    def write(self, vals):
        before = {r.id: (r.length_ft, r.active) for r in self}
        result = super().write(vals)
        for rec in self:
            old_ft, old_active = before[rec.id]
            if old_active != rec.active:
                what = _("switched on") if rec.active else _("switched off")
            elif abs(old_ft - rec.length_ft) > 1e-9:
                what = _("changed from %(old)g ft", old=old_ft)
            else:
                continue
            self._log(rec.vendor_id, _(
                "Bar length %(ft)g ft (%(profile)s) %(what)s by %(who)s on %(when)s.",
                ft=rec.length_ft, profile=rec.profile_label, what=what, who=self.env.user.name,
                when=fields.Datetime.now()))
        return result

    def unlink(self):
        for rec in self:
            self._log(rec.vendor_id, _(
                "Bar length %(ft)g ft (%(profile)s) removed by %(who)s on %(when)s.",
                ft=rec.length_ft, profile=rec.profile_label, who=self.env.user.name,
                when=fields.Datetime.now()))
        return super().unlink()

    @api.model
    def _profile_templates(self, vendor):
        """The profiles this vendor has ACTIVE rows of their own for."""
        if not vendor:
            return self.env['product.template']
        return self.sudo().search([
            ('vendor_id', '=', vendor.id),
            ('product_tmpl_id', '!=', False)]).mapped('product_tmpl_id')

    @api.model
    def _lengths_for(self, vendor, strict=False, template=None):
        """Sorted ACTIVE lengths in ft for a vendor (and a profile template).

        [] means "use the global list": the vendor has no rows, or none that
        apply (only other profiles' rows). The profile's own active rows win;
        if all of them are off that profile is a stop when strict (UserError
        naming the profile), else it falls back to the vendor-wide rows. With
        vendor-wide rows all off: a stop when strict, else [].
        """
        if not vendor:
            return []
        rows = self.sudo().with_context(active_test=False).search(
            [('vendor_id', '=', vendor.id)])
        if not rows:
            return []
        if template:
            own = rows.filtered(lambda r: r.product_tmpl_id == template)
            if own:
                active = own.filtered('active')
                if active:
                    return sorted(active.mapped('length_ft'))
                if strict:
                    raise UserError(_(
                        "%(vendor)s has no active bar length for %(profile)s",
                        vendor=vendor.display_name,
                        profile=template.display_name))
        wide = rows.filtered(lambda r: not r.product_tmpl_id)
        if not wide:
            return []
        active = wide.filtered('active')
        if not active and strict:
            raise UserError(_(
                "%s has no active bar length.", vendor.display_name))
        return sorted(active.mapped('length_ft'))

    @api.model
    def _seed_vendor_bar_lengths(self):
        """Once: every vendor that has profile rates gets the current global
        list, so cut plans come out exactly as before. A vendor with no
        profile rates (glass, hardware) gets none. One-shot, by parameter:
        a vendor later left with no rows means "use the global list", and
        must not be refilled on the next upgrade."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(SEEDED_PARAM):
            return False
        lengths = self.env['aw.cut.plan']._settings()['stock_ft']
        vendors = self.env['aw.profile.rate'].with_context(
            active_test=False).search([('vendor_id', '!=', False)]).mapped(
            'vendor_id')
        for vendor in vendors:
            if not self.with_context(active_test=False).search_count(
                    [('vendor_id', '=', vendor.id)]):
                self.with_context(aw_no_log=True).create([
                    {'vendor_id': vendor.id, 'length_ft': ft}
                    for ft in lengths])
        param.set_param(SEEDED_PARAM, '1')
        return True
