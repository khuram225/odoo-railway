# -*- coding: utf-8 -*-
"""The bar lengths a vendor sells a profile in.

Cut planning used to take one list for the whole business
(aw_fenestration.stock_lengths_ft). Vendors differ, so a quote now plans with
the lengths of its profile vendor; a vendor with none listed falls back to
that global list, which is why this changes nothing until a row differs.

Its own model rather than a field on res.partner: a stored field on a core
model read on every request is what took the site down once (see CLAUDE.md).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

SEEDED_PARAM = 'aw_fenestration.vendor_bar_lengths_seeded'


class AwVendorBarLength(models.Model):
    _name = 'aw.vendor.bar.length'
    _description = 'Vendor Bar Length'
    _order = 'vendor_id, length_ft'

    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True,
        ondelete='cascade')
    length_ft = fields.Float(string='Bar length (ft)', required=True)

    @api.constrains('vendor_id', 'length_ft')
    def _check_length(self):
        for rec in self:
            if rec.length_ft <= 0:
                raise ValidationError(_("A bar length must be more than 0."))
            twin = self.search([('vendor_id', '=', rec.vendor_id.id),
                                ('id', '!=', rec.id)]).filtered(
                lambda o: abs(o.length_ft - rec.length_ft) < 1e-6)
            if twin:
                raise ValidationError(_(
                    "%(vendor)s already has a %(ft)g ft bar.",
                    vendor=rec.vendor_id.display_name, ft=rec.length_ft))

    @api.model
    def _lengths_for(self, vendor):
        """Sorted lengths in ft for this vendor; [] when none are listed."""
        if not vendor:
            return []
        return sorted(self.sudo().search(
            [('vendor_id', '=', vendor.id)]).mapped('length_ft'))

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
            if not self.search_count([('vendor_id', '=', vendor.id)]):
                self.create([{'vendor_id': vendor.id, 'length_ft': ft}
                             for ft in lengths])
        param.set_param(SEEDED_PARAM, '1')
        return True
