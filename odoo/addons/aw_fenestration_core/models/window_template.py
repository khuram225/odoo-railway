# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AwWindowTemplate(models.Model):
    """A SPECIFICATION (spec 7c): one Profile Section + one Hardware Set
    + one Glass Spec, and optionally a default Finish, for one profile
    system. This is what a design starts from -- it is applied when the
    system is resolved and fills the three parts in one go, instead of
    each being picked separately and forgotten separately.

    The model name is `aw.window.template` and stays that way: renaming
    it would rewrite every stored reference and every xmlid for a label.
    Everything the user sees says "Specification" / "Spec".

    A system may have several (Standard / Heavy Duty / Economy). Exactly
    one of them can be the default, which is the one a new design gets.
    """
    _name = 'aw.window.template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Specification'
    _order = 'window_type_id, sequence, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        default=10,
        help="Order in the configurator's Spec dropdown. The default "
             "one is offered first regardless.")

    # Field name kept: renaming it would need a migration and break
    # every stored reference. Only the LABEL was ever wrong -- the
    # Window Type layer was folded into Series long ago.
    window_type_id = fields.Many2one(
        'aw.window.series', string='Series', required=True,
        ondelete='restrict', index=True, tracking=True)

    profile_section_id = fields.Many2one(
        'aw.profile.section', required=True, ondelete='restrict',
        domain="[('window_type_id', '=', window_type_id)]", tracking=True)
    # NOT required. No hardware list exists for this business yet, and
    # a required field would have forced either a placeholder set --
    # which puts zero hardware into every quote while looking
    # configured -- or no specification at all. Empty is honest, and
    # the design checks say so once per design rather than letting the
    # absence pass unmentioned.
    hardware_set_id = fields.Many2one(
        'aw.hardware.set', ondelete='restrict',
        domain="[('window_type_id', '=', window_type_id)]", tracking=True,
        help="Leave empty until a hardware list exists. A design built "
             "to this spec will warn that its hardware cost is missing.")
    glass_spec_id = fields.Many2one(
        'aw.glass.spec', required=True, ondelete='restrict', tracking=True)
    # Optional, unlike the three above: most systems are quoted in
    # whatever finish the job calls for, and a spec that insisted on one
    # would be re-picked on every design. Empty means "no opinion".
    finish_id = fields.Many2one(
        'product.attribute.value', string='Default Finish',
        ondelete='restrict', tracking=True,
        domain=lambda self: [(
            'attribute_id', '=',
            self.env.ref('aw_fenestration_core.aw_attribute_finish').id,
        )],
        help="Filled into a design that has no finish yet. Leave empty "
             "unless this system is genuinely always one colour.")

    is_default = fields.Boolean(
        string='Default', tracking=True,
        help="The spec a new design in this profile system starts from. "
             "One per system.")

    notes = fields.Text()

    _sql_constraints = [
        ('name_type_uniq', 'unique(name, window_type_id)',
         'A specification name must be unique per profile system.'),
    ]

    @api.constrains('is_default', 'window_type_id', 'active')
    def _check_one_default(self):
        """At most one default per system.

        Enforced in Python rather than by a unique index: the rule is
        "one row with is_default among the ACTIVE rows of a system",
        and a partial unique index on a Boolean would also have to
        carry `active`, which archiving then fights with.
        """
        for rec in self:
            if not (rec.is_default and rec.active):
                continue
            others = self.search([
                ('id', '!=', rec.id),
                ('window_type_id', '=', rec.window_type_id.id),
                ('is_default', '=', True),
            ])
            if others:
                raise ValidationError(_(
                    "'%(other)s' is already the default specification "
                    "for %(system)s. A system has one default; untick "
                    "that one first.",
                    other=others[0].display_name,
                    system=rec.window_type_id.display_name))

    @api.model
    def _default_for_system(self, system):
        """The spec a design in `system` should start from.

        The one marked default, else the first by sequence. Falling
        back rather than returning nothing is deliberate: a system with
        exactly one spec and nobody having ticked the box should still
        fill a design in.
        """
        if not system:
            return self.browse()
        specs = self.search([('window_type_id', '=', system.id)])
        return specs.filtered('is_default')[:1] or specs[:1]

    @api.constrains('window_type_id', 'profile_section_id', 'hardware_set_id')
    def _check_same_window_type(self):
        """The view domains steer the user correctly, but domains are only
        UI hints — imports, API calls and multi-record write bypass them.
        This is the real guard against pairing a sliding Profile Section
        with a hinged Hardware Set, etc."""
        for rec in self:
            if rec.profile_section_id.window_type_id != rec.window_type_id:
                raise ValidationError(
                    "Profile Section '%s' belongs to Series '%s', not "
                    "'%s'." % (rec.profile_section_id.name,
                               rec.profile_section_id.window_type_id.name,
                               rec.window_type_id.name))
            # `and` guards the empty case: an unset hardware set has
            # no window_type_id, which would otherwise read as a
            # mismatch and make the field required by the back door.
            if (rec.hardware_set_id
                    and rec.hardware_set_id.window_type_id
                    != rec.window_type_id):
                raise ValidationError(
                    "Hardware Set '%s' belongs to Series '%s', not "
                    "'%s'." % (rec.hardware_set_id.name,
                               rec.hardware_set_id.window_type_id.name,
                               rec.window_type_id.name))
