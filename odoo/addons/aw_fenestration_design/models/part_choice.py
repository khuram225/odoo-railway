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
from odoo.exceptions import UserError, ValidationError

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

    def _sync_part_choices(self, reset=False, old_line_thickness=None):
        """Make sure every profile line of the spec has a choice row.

        New rows take the line's thickness. `reset` is a change of spec:
        the rows are rebuilt for the new lines, but a PICK is kept where
        the new profile still offers it. A pick is a thickness that
        differs from what the old line said (a thickness equal to it
        was only the mirrored default, and the new spec's own wins); a
        finish choice is always a pick. Positions the new spec does not
        have lose their rows. Returns the rows created.
        """
        self.ensure_one()
        old_line_thickness = old_line_thickness or {}
        kept = {}
        if reset:
            for choice in self.part_choice_ids:
                pos = choice.position_id.id
                thick = choice.thickness_id
                kept[pos] = {
                    'thickness': (thick if thick and thick.id
                                  != old_line_thickness.get(pos)
                                  else thick.browse()),
                    'finish': choice.finish_id,
                }
            self.part_choice_ids.unlink()
        Section = self.env['aw.profile.section.line']
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        have = set(self.part_choice_ids.position_id.ids)
        vals = []
        for line in self._spec_profile_lines():
            position = line.position_id
            if not position or position.id in have:
                continue
            have.add(position.id)
            old = kept.get(position.id, {})
            template = line.product_tmpl_id
            thickness = line.thickness_id
            pick = old.get('thickness')
            if pick and pick in Section._template_values(
                    template, thickness_attr):
                thickness = pick
            finish = old.get('finish')
            if finish and finish not in Section._template_values(
                    template, finish_attr):
                finish = finish.browse()
            vals.append({
                'design_id': self.id,
                'position_id': position.id,
                'thickness_id': thickness.id or False,
                'finish_id': finish.id if finish else False,
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

    def _profile_rows(self):
        """The profile lines the Spec tab lists: the spec's own, then the
        components added to this window."""
        self.ensure_one()
        return self._spec_profile_lines() | self._added_profile_lines()

    def _row_template(self, line):
        change = self._overrides_by_key()[0].get(line.position_id.id)
        return change.product_tmpl_id if change else line.product_tmpl_id

    def _row_thickness(self, line):
        """The thickness a row is cut in, an override's own included."""
        change = self._overrides_by_key()[0].get(line.position_id.id)
        if change:
            return change.thickness_id
        return self._line_thickness(line)

    def _thickness_options(self, template):
        return self.env['aw.profile.section.line']._template_values(
            template,
            self.env.ref('aw_fenestration_core.aw_attribute_thickness'))

    def _set_row_thickness(self, line, thickness):
        """Write one row's thickness where it actually lives: on the
        window's override when the row has one (the override resolves its
        own variant), otherwise on the row's choice."""
        change = self._overrides_by_key()[0].get(line.position_id.id)
        if change:
            change.thickness_id = thickness
            return
        self._choice_row(line.position_id).thickness_id = thickness

    def _choice_row(self, position):
        choice = self.part_choice_ids.filtered(
            lambda c: c.position_id == position)[:1]
        return choice or self.env['aw.design.part.choice'].create({
            'design_id': self.id, 'position_id': position.id})

    def set_part_choice(self, values):
        """One row's thickness and/or finish, from the Spec tab.

        Public RPC, so nothing is trusted: the position has to be one of
        THIS window's rows, the thickness one the row's profile is sold
        in, and the finish one of the Finish attribute's values. A
        falsy finish goes back to the window's own.
        """
        self.ensure_one()
        values = values or {}
        rows = self._profile_rows().filtered(
            lambda l: l.position_id.id == int(values.get('position_id') or 0))
        if not rows:
            raise UserError(_(
                "That profile position is not part of this window."))
        line = rows[:1]
        if 'thickness_id' in values:
            thickness = self.env['product.attribute.value'].browse(
                int(values['thickness_id'] or 0)).exists()
            if thickness and thickness not in self._thickness_options(
                    self._row_template(line)):
                raise UserError(_(
                    "%(profile)s is not sold in that thickness.",
                    profile=self._row_template(line).display_name))
            self._set_row_thickness(line, thickness)
        if 'finish_id' in values:
            finish = self.env['product.attribute.value'].browse(
                int(values['finish_id'] or 0)).exists()
            if finish and finish.id not in [
                    f['id'] for f in self._finish_options()]:
                raise UserError(_("That is not a finish."))
            self._choice_row(line.position_id).finish_id = finish
        self._explode()
        return self.get_configurator_data()

    def apply_thickness_all(self, thickness_id):
        """Give every row that offers this thickness that thickness.
        Rows whose profile is not sold in it are left as they are; rows
        already on another thickness are overwritten."""
        self.ensure_one()
        thickness = self.env['product.attribute.value'].browse(
            int(thickness_id or 0)).exists()
        if not thickness:
            raise UserError(_("Choose a thickness first."))
        for line in self._profile_rows():
            if thickness in self._thickness_options(self._row_template(line)):
                self._set_row_thickness(line, thickness)
        self._explode()
        return self.get_configurator_data()

    def _line_finish(self, line):
        """The finish a profile line is made in: its own choice, else the
        window's."""
        self.ensure_one()
        choice = self._choices_by_position().get(line.position_id.id)
        return (choice.finish_id if choice and choice.finish_id
                else self.finish_id)
