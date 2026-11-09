# -*- coding: utf-8 -*-
"""A vendor's "Last prices" button: how many last purchase prices it has, and
the list filtered to them. Nothing is stored on res.partner."""
from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    aw_lpp_count = fields.Integer(
        string='Last prices', compute='_compute_aw_lpp_count')

    def _compute_aw_lpp_count(self):
        counts = {}
        if self.ids:
            counts = {
                group.id: count for group, count in self.env[
                    'aw.profile.lpp']._read_group(
                        [('vendor_id', 'in', self.ids)], ['vendor_id'],
                        ['__count'])}
        for partner in self:
            partner.aw_lpp_count = counts.get(partner.id, 0)

    def action_open_lpp(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Last prices - %s", self.display_name),
            'res_model': 'aw.profile.lpp',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('vendor_id', '=', self.id)],
            'context': {'search_default_group_profile': 1},
        }
