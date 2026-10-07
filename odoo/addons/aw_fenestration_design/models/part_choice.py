# -*- coding: utf-8 -*-
"""Per-window thickness and finish for each profile of the spec.

A Specification says WHICH profile goes in each position. How thick it is
and what colour it is are choices made for the window being quoted, so
they live here, one row per window and profile position, and never on
the spec.

This is the data model only. Until the Spec tab can edit them, every row
mirrors what the spec line says (thickness) or stays empty (finish ->
the window's own finish), so nothing about a BOM or a price changes. The
effective values are always resolved the same way:

    thickness: the choice, else the spec line's own, else the profile's
               only thickness when it is sold in exactly one;
    finish:    the choice, else the window's finish.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PARAM = 'aw_fenestration.part_choice_thickness_migrated'


class AwDesignPartChoice(models.Model):
    _name = 'aw.design.part.choice'
    _description = 'Fenestration Per-Window Thickness / Finish Choice'
    _order = 'design_id, position_id'

    design_id = fields.Many2one(
        'aw.design', required=True, ondelete='cascade', index=True)
    position_id = fields.Many2one(
        'aw.profile.position', required=True, ondelete='cascade',
        help="Which profile position of the spec this is for.")
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness',
        ondelete='restrict',
        help="Empty means the spec line's own thickness.")
    finish_id = fields.Many2one(
        'product.attribute.value', string='Finish', ondelete='restrict',
        help="Empty means the window's finish.")

    @api.constrains('design_id', 'position_id')
    def _check_one_per_position(self):
        # `_sql_constraints` is dead in Odoo 19, so this is in Python.
        for rec in self:
            if self.search_count([
                    ('design_id', '=', rec.design_id.id),
                    ('position_id', '=', rec.position_id.id)]) > 1:
                raise ValidationError(_(
                    "One thickness and finish choice per profile position "
                    "and window."))

    @api.model
    def _migrate_thickness_choices(self):
        """Give every existing window a choice per profile line holding
        the thickness the line has NOW, once.

        Nothing is priced differently afterwards: the effective thickness
        is the choice, and the choice is the line's own value. Windows
        that already have a choice for a position are left alone, so
        running it twice is harmless.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PARAM):
            return 0
        made = 0
        Design = self.env['aw.design'].with_context(active_test=False)
        for design in Design.search([]):
            made += len(design._sync_part_choices())
        param.set_param(PARAM, '1')
        return made


class AwDesign(models.Model):
    _inherit = 'aw.design'

    part_choice_ids = fields.One2many(
        'aw.design.part.choice', 'design_id', string='Part Choices',
        copy=True)

    def _choices_by_position(self):
        """This window's choices keyed by position id."""
        self.ensure_one()
        return {c.position_id.id: c for c in self.part_choice_ids}

    def _sync_part_choices(self, reset=False):
        """Make sure every profile line of the spec has a choice row.

        New rows take the line's thickness. `reset` drops the existing
        rows first, which is what a change of spec means while the lines
        still carry a thickness: the old rows mirrored the OLD spec.
        Returns the rows created.
        """
        self.ensure_one()
        if reset:
            self.part_choice_ids.unlink()
        have = set(self.part_choice_ids.position_id.ids)
        vals = []
        for line in self._spec_profile_lines():
            position = line.position_id
            if not position or position.id in have:
                continue
            have.add(position.id)
            vals.append({
                'design_id': self.id,
                'position_id': position.id,
                'thickness_id': line.thickness_id.id or False,
            })
        return self.env['aw.design.part.choice'].create(vals)

    def _line_thickness(self, line, product_tmpl=None):
        """The thickness a profile line is cut in, for THIS window."""
        self.ensure_one()
        choice = self._choices_by_position().get(line.position_id.id)
        if choice and choice.thickness_id:
            return choice.thickness_id
        if line.thickness_id:
            return line.thickness_id
        # A profile sold in exactly one thickness has nothing to choose.
        template = product_tmpl or line.product_tmpl_id
        options = self.env['aw.profile.section.line']._template_values(
            template, self.env.ref('aw_fenestration_core.aw_attribute_thickness'))
        return options if len(options) == 1 else options.browse()

    def _line_finish(self, line):
        """The finish a profile line is made in: its own choice, else the
        window's."""
        self.ensure_one()
        choice = self._choices_by_position().get(line.position_id.id)
        return (choice.finish_id if choice and choice.finish_id
                else self.finish_id)
