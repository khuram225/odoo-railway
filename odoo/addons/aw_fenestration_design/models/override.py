# -*- coding: utf-8 -*-
"""Per-window changes to a Specification (phase 7c).

A Spec says what a window is normally made of. This says what THIS
window does differently -- a heavier mullion on one wide opening, a
different handle on the one that faces the street -- without editing
the spec and changing every other quote that uses it.

Two rules make the whole thing work:

- An override REPLACES one row of the spec and is keyed by that row's
  identity, not by its product. For a profile that identity is the
  PROFILE POSITION (Outer Frame - Top, Lock Bar), so changing the spec
  underneath still leaves the override pointing at the right slot; for
  hardware it is the hardware set LINE, because a set can legitimately
  carry two lines for the same product with different conditions.
- A profile override stores a TEMPLATE plus a thickness, never a
  variant. The design's own finish decides the variant, exactly as the
  spec's own lines do, so changing the window's colour moves the
  override with it instead of stranding it on last week's finish.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AwDesignOverride(models.Model):
    _name = 'aw.design.override'
    _description = 'Fenestration Per-Window Change'
    _order = 'kind, id'

    design_id = fields.Many2one(
        'aw.design', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([
        ('profile', 'Profile'),
        ('hardware', 'Hardware'),
    ], required=True, default='profile')

    # -- what is being replaced ---------------------------------------
    position_id = fields.Many2one(
        'aw.profile.position', string='Profile Position',
        ondelete='cascade',
        help="Which profile of the spec this replaces.")
    hardware_line_id = fields.Many2one(
        'aw.hardware.set.line', string='Hardware Line',
        ondelete='cascade',
        help="Which hardware line of the spec this replaces.")

    # -- what it is replaced WITH -------------------------------------
    product_tmpl_id = fields.Many2one(
        'product.template', string='Profile',
        ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )])
    thickness_id = fields.Many2one(
        'product.attribute.value', string='Thickness',
        ondelete='restrict')
    product_id = fields.Many2one(
        'product.product', string='Hardware',
        ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_hardware').id,
        )])
    qty = fields.Float(default=1.0)

    note = fields.Char(
        help="Why this window is different. Shown on the shop drawing.")
    is_added = fields.Boolean(
        string='Added Component', default=False,
        help="This change ADDS a part the Specification does not have, "
             "rather than replacing one it does. Only a change flagged "
             "so produces a piece on its own: an ordinary change whose "
             "position the spec no longer carries (after a spec switch) "
             "stays dormant, exactly as before.")

    _sql_constraints = [
        ('profile_uniq', 'unique(design_id, position_id)',
         'One change per profile position, per window.'),
        ('hardware_uniq', 'unique(design_id, hardware_line_id)',
         'One change per hardware line, per window.'),
    ]

    @api.constrains('kind', 'position_id', 'hardware_line_id',
                    'product_tmpl_id', 'product_id')
    def _check_complete(self):
        """A half-filled override is worse than none at all.

        It would look like a deliberate change on the Spec tab while
        the explosion quietly fell back to the spec, so the window
        would be built to the spec and the quote would say otherwise.
        """
        for rec in self:
            if rec.kind == 'profile':
                if not rec.position_id:
                    raise ValidationError(_(
                        "A profile change has to say which position it "
                        "replaces."))
                if not rec.product_tmpl_id:
                    raise ValidationError(_(
                        "A profile change has to name a profile."))
            else:
                if not rec.hardware_line_id:
                    raise ValidationError(_(
                        "A hardware change has to say which line it "
                        "replaces."))
                if not rec.product_id:
                    raise ValidationError(_(
                        "A hardware change has to name a product."))

    def _profile_variant_for(self, design, finish=None):
        """The variant this override resolves to, in the design's finish.

        Same call the spec's own lines make, so a changed profile is
        costed and cut exactly like an unchanged one -- and a variant
        that does not exist yet is created rather than reported
        missing.
        """
        self.ensure_one()
        finish = finish or design.finish_id
        return self.env['aw.profile.section.line']._variant_for(
            self.product_tmpl_id, self.thickness_id, finish)

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Same trap as the section line: the thickness domain only
        restricts a NEW pick, so a value from the previous template
        survives and silently resolves to nothing."""
        for rec in self:
            rec.thickness_id = False

    @api.onchange('kind')
    def _onchange_kind(self):
        """Never leave the other half of the record filled in.

        A profile override still carrying a hardware product would
        pass its own constraint and then confuse every reader of the
        Spec tab.
        """
        for rec in self:
            if rec.kind == 'profile':
                rec.hardware_line_id = False
                rec.product_id = False
            else:
                rec.position_id = False
                rec.product_tmpl_id = False
                rec.thickness_id = False
