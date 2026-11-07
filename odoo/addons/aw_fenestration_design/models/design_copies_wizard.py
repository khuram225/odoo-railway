# -*- coding: utf-8 -*-
"""Make copies of a window: one window per line, each with its own location.

A window is one window (quantity 1). Where the quote needs several of the
same, the estimator types or pastes their locations, one per line, and this
makes one window for each: the same layout, glass, finish and changes as the
source, a quote line of its own, and the location written on that line. The
source window is not touched.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_COPIES = 100


class AwDesignCopiesWizard(models.TransientModel):
    _name = 'aw.design.copies.wizard'
    _description = 'Make Copies of a Window'

    design_id = fields.Many2one(
        'aw.design', string='Window', required=True, ondelete='cascade')
    locations = fields.Text(
        help="One location per line, typed or pasted. One window is made "
             "for each line; blank lines are ignored.")
    count = fields.Integer(compute='_compute_count')

    def _lines(self):
        self.ensure_one()
        return [line.strip() for line in (self.locations or '').splitlines()
                if line.strip()]

    @api.depends('locations')
    def _compute_count(self):
        for wizard in self:
            wizard.count = len(wizard._lines())

    def action_make(self):
        self.ensure_one()
        design = self.design_id
        order = design.sale_order_line_id.order_id
        if not order:
            raise UserError(_(
                "This window isn't on a quote yet, so there is no quote to "
                "make copies on."))
        if order.state not in ('draft', 'sent'):
            raise UserError(_(
                "Windows can only be added while the order is still a "
                "quotation."))
        locations = self._lines()
        if not locations:
            raise UserError(_("Type at least one location, one per line."))
        if len(locations) > MAX_COPIES:
            raise UserError(_(
                "%(count)s locations is more than %(max)s at once. Split "
                "them into smaller lists.", count=len(locations),
                max=MAX_COPIES))
        made = self.env['aw.design']
        for location in locations:
            copy = design.copy_position()
            copy.location = location
            if design.bom_line_ids:
                copy._explode()          # so the quote line carries a price
            made |= copy
        order.message_post(body=_(
            "%(who)s made %(count)s cop(ies) of %(window)s: %(names)s.",
            who=self.env.user.name, count=len(made),
            window=design.display_name,
            names=', '.join('%s (%s)' % (c.name, c.location) for c in made)))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Windows"),
            'res_model': 'aw.design',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', made.ids)],
        }
