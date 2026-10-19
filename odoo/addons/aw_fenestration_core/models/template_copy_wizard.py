# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class AwWindowTemplateCopyWizard(models.TransientModel):
    """Start a new series from an existing one: a ONE-TIME copy of the
    mapping, with no live link afterwards."""
    _name = 'aw.window.template.copy.wizard'
    _description = 'Copy a series mapping'

    target_id = fields.Many2one(
        'aw.window.template', string='Series', required=True, readonly=True)
    source_id = fields.Many2one(
        'aw.window.template', string='Copy from', required=True,
        domain="[('id', '!=', target_id)]")

    def action_copy(self):
        self.ensure_one()
        target, source = self.target_id, self.source_id
        if target.profile_line_ids.filtered('is_used'):
            raise UserError(_(
                "'%s' already maps positions. Copying is only offered on "
                "an empty series, so nothing is overwritten.",
                target.display_name))
        Line = self.env['aw.profile.section.line']
        copied = 0
        for line in source.profile_line_ids.filtered('is_used'):
            values = {
                'is_used': True,
                'product_tmpl_id': line.product_tmpl_id.id,
                'alternate_product_ids': [(6, 0, line.alternate_product_ids.ids)],
                'thickness_id': line.thickness_id.id,
                'length_formula': line.length_formula,
                'length_formula_h': line.length_formula_h,
                'cut_angle': line.cut_angle,
                'qty_formula': line.qty_formula,
                'cut_on_site': line.cut_on_site,
                'is_optional': line.is_optional,
                'note': line.note,
                'sequence': line.sequence,
                'spec_section_id': line.spec_section_id.id,
            }
            mine = target.profile_line_ids.filtered(
                lambda l, p=line.position_id: l.position_id == p)[:1]
            if mine:
                mine.write(values)
            else:
                Line.create(dict(
                    values, spec_id=target.id,
                    position_id=line.position_id.id))
            copied += 1
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aw.window.template',
            'res_id': target.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
