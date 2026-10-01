# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .formula import validate_formula


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

    # -- what this spec is made of (phase 7d) --------------------------
    # The spec OWNS its lines now. Profile Sections and Hardware Sets
    # were a layer between the system and the spec that nothing used
    # independently: every section belonged to one system and was
    # picked by one spec, so naming and maintaining it twice was all
    # cost. The old links are kept and hidden until they are dropped.
    profile_line_ids = fields.One2many(
        'aw.profile.section.line', 'spec_id', string='Profiles')
    hardware_line_ids = fields.One2many(
        'aw.hardware.set.line', 'spec_id', string='Hardware')

    profile_line_count = fields.Integer(compute='_compute_part_counts')
    hardware_line_count = fields.Integer(compute='_compute_part_counts')
    design_count = fields.Integer(
        compute='_compute_design_count', string='Used in')

    # -- 6.4 deductions and limits, moved off the system (phase 7d) ----
    # These describe how a PROFILE SYSTEM's glass sits in its sash, so
    # they belong with the profiles rather than with the system: two
    # specs of one system can legitimately use different beads and
    # therefore different deductions. Migrated by copying each system's
    # current values into every one of its specs, so nothing moves on
    # the upgrade.
    glass_fixed_w = fields.Char(string='Fixed Glass Width', default='PW - 60')
    glass_fixed_h = fields.Char(string='Fixed Glass Height', default='PH - 60')
    glass_sash_w = fields.Char(string='Sash Glass Width', default='PW - 80')
    glass_sash_h = fields.Char(string='Sash Glass Height', default='PH - 80')
    mesh_w = fields.Char(string='Mesh Width', default='PW - 10')
    mesh_h = fields.Char(string='Mesh Height', default='PH - 10')
    max_panel_w = fields.Float(
        string='Max Panel Width (mm)', help="0 means not checked.")
    max_panel_h = fields.Float(
        string='Max Panel Height (mm)', help="0 means not checked.")
    max_panel_kg = fields.Float(
        string='Max Panel Weight (kg)', help="0 means not checked.")

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

    @api.depends('profile_line_ids', 'hardware_line_ids')
    def _compute_part_counts(self):
        for rec in self:
            rec.profile_line_count = len(rec.profile_line_ids)
            rec.hardware_line_count = len(rec.hardware_line_ids)

    def _compute_design_count(self):
        """How many designs are built to this spec.

        Not stored and not depended on: a design count that went stale
        would be worse than one computed on open, and nothing here
        needs to trigger on it.
        """
        Design = self.env['aw.design'].with_context(active_test=False)
        for rec in self:
            rec.design_count = Design.search_count(
                [('template_id', '=', rec.id)]) if rec.id else 0

    @api.constrains('glass_fixed_w', 'glass_fixed_h', 'glass_sash_w',
                    'glass_sash_h', 'mesh_w', 'mesh_h')
    def _check_deduction_formulas(self):
        """Rejected on save, with the reason, rather than silently
        falling back to a default in the explosion later."""
        for rec in self:
            for value, label in (
                (rec.glass_fixed_w, _('Fixed Glass Width')),
                (rec.glass_fixed_h, _('Fixed Glass Height')),
                (rec.glass_sash_w, _('Sash Glass Width')),
                (rec.glass_sash_h, _('Sash Glass Height')),
                (rec.mesh_w, _('Mesh Width')),
                (rec.mesh_h, _('Mesh Height')),
            ):
                problem = validate_formula(value)
                if problem:
                    raise ValidationError(_(
                        "%(label)s on '%(name)s': %(problem)s",
                        label=label, name=rec.name, problem=problem))

    def action_duplicate_spec(self):
        """Copy this spec, its lines and its deductions.

        copy() carries the One2many lines because they are owned here
        now -- which is the point of the phase: a variant of a spec used
        to mean copying a Profile Section, a Hardware Set and the spec
        that pointed at both, and keeping three names in step.
        """
        self.ensure_one()
        new = self.copy({
            'name': _('%s (copy)', self.name),
            # Never two defaults for one system, and a copy is not the
            # thing a new design should silently start from.
            'is_default': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Specification'),
            'res_model': 'aw.window.template',
            'res_id': new.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def action_view_designs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Designs built to %s', self.display_name),
            'res_model': 'aw.design',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('template_id', '=', self.id)],
        }

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
