# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AwWindowTemplate(models.Model):
    """The assembly: one Profile Section + one Hardware Set + one Glass Spec
    for a Window Type. This is what a quote position (in the downstream
    aw_fenestration_design/quote modules) points to as its starting default
    — matching the prototype's Template x Series = BOM idea, now with the
    hardware and glass legs added explicitly.

    A Window Type may have several Templates (Standard / Heavy Duty /
    Economy) — nothing here forces a 1:1.
    """
    _name = 'aw.window.template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Window Template'
    _order = 'window_type_id, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    active = fields.Boolean(default=True)

    window_type_id = fields.Many2one(
        'aw.window.type', required=True, ondelete='restrict', index=True,
        tracking=True)

    profile_section_id = fields.Many2one(
        'aw.profile.section', required=True, ondelete='restrict',
        domain="[('window_type_id', '=', window_type_id)]", tracking=True)
    hardware_set_id = fields.Many2one(
        'aw.hardware.set', required=True, ondelete='restrict',
        domain="[('window_type_id', '=', window_type_id)]", tracking=True)
    glass_spec_id = fields.Many2one(
        'aw.glass.spec', required=True, ondelete='restrict', tracking=True)

    notes = fields.Text()

    _sql_constraints = [
        ('name_type_uniq', 'unique(name, window_type_id)',
         'A template name must be unique per Window Type.'),
    ]

    @api.constrains('window_type_id', 'profile_section_id', 'hardware_set_id')
    def _check_same_window_type(self):
        """The view domains steer the user correctly, but domains are only
        UI hints — imports, API calls and multi-record write bypass them.
        This is the real guard against pairing a sliding Profile Section
        with a hinged Hardware Set, etc."""
        for rec in self:
            if rec.profile_section_id.window_type_id != rec.window_type_id:
                raise ValidationError(
                    "Profile Section '%s' belongs to Window Type '%s', not "
                    "'%s'." % (rec.profile_section_id.name,
                               rec.profile_section_id.window_type_id.name,
                               rec.window_type_id.name))
            if rec.hardware_set_id.window_type_id != rec.window_type_id:
                raise ValidationError(
                    "Hardware Set '%s' belongs to Window Type '%s', not "
                    "'%s'." % (rec.hardware_set_id.name,
                               rec.hardware_set_id.window_type_id.name,
                               rec.window_type_id.name))
