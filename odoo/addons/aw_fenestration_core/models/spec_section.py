# -*- coding: utf-8 -*-
"""Sections of a specification, the way the client describes a window.

Frame (shared), then one section per panel type, then mesh add-ons, then
joints. A spec line belongs to one section, and the SECTION decides
which panels it applies to; the position stays generic (edge, default
length, angle). So one window can mix fixed, sliding, openable and mesh
panels, each built from its own section.

Sections are data: add your own (a Sill, say) from Configuration.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

APPLIES_TO = [
    ('frame', 'Frame (once per window)'),
    ('panel', 'Panel types'),
    ('addon', 'Add-ons'),
    ('joint', 'Joints'),
]

# (xmlid suffix, name, sequence, applies to, leaf type codes)
SEED = [
    ('frame', 'Frame', 10, 'frame', []),
    ('fixed', 'Fixed panel', 20, 'panel', ['FIXED']),
    ('sliding', 'Sliding panel', 30, 'panel', ['SLIDER']),
    ('openable', 'Openable panel', 40, 'panel',
     ['CASEMENT', 'AWNING', 'HOPPER', 'TILTTURN']),
    ('mesh_sliding', 'Mesh sliding panel', 50, 'panel', ['MESH']),
    ('mesh_addons', 'Mesh add-ons', 60, 'addon', []),
    ('joints', 'Joints', 70, 'joint', []),
]

JOINT_SCOPES = ('junction_mullion', 'junction_meeting',
                'junction_interlock', 'transom')

PARAM = 'aw_fenestration.line_sections_migrated'


class AwSpecSection(models.Model):
    _name = 'aw.spec.section'
    _description = 'Specification Section'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    applies_to = fields.Selection(
        APPLIES_TO, required=True, default='panel',
        help="What this section's lines apply to: the frame (once per "
             "window), certain panel types, add-ons fitted to a panel, "
             "or the joints between panels.")
    leaf_type_ids = fields.Many2many(
        'aw.leaf.type', string='Panel Types',
        help="For a panel section: the panel types it is built for. A "
             "panel type no section lists is built from whatever its "
             "positions' scope says, as before.")

    @api.model
    def _section_xmlid(self, suffix):
        return 'aw_fenestration_core.spec_section_%s' % suffix

    @api.model
    def _seed_spec_sections(self):
        """Seed the seven sections, FILL-ONLY.

        A section that already carries the seed xmlid is left exactly as
        it is, edits included. One a user made by hand with the same
        name is adopted (given the xmlid) rather than duplicated.
        """
        Data = self.env['ir.model.data'].sudo()
        LeafType = self.env['aw.leaf.type']
        created = 0
        for suffix, name, sequence, applies_to, codes in SEED:
            xmlid = 'spec_section_%s' % suffix
            if Data.search_count([('module', '=', 'aw_fenestration_core'),
                                  ('name', '=', xmlid)]):
                continue
            section = self.with_context(active_test=False).search(
                [('name', '=', name)], limit=1)
            if not section:
                section = self.create({
                    'name': name, 'sequence': sequence,
                    'applies_to': applies_to,
                    'leaf_type_ids': [(6, 0, LeafType.search(
                        [('code', 'in', codes)]).ids)],
                })
                created += 1
            Data.create({
                'module': 'aw_fenestration_core', 'name': xmlid,
                'model': self._name, 'res_id': section.id,
                'noupdate': True,
            })
        return created

    @api.model
    def _section_for(self, position, spec):
        """The section a spec line for this position belongs in, by its
        scope and the spec's system role -- or empty when nothing fits.

        A sash of a sliding spec is a Sliding panel part and a sash of an
        openable or tilt & turn spec an Openable panel part; the same
        position scope means different panels in different systems. Joint
        scopes stay in Joints: the explosion places those per joint, not
        per panel.
        """
        scope = position.scope
        role = spec.window_type_id.system_role

        def ref(suffix):
            return self.env.ref(self._section_xmlid(suffix),
                                raise_if_not_found=False) or self.browse()

        if scope == 'frame':
            return ref('frame')
        if scope == 'panel_fixed':
            return ref('fixed')
        if scope == 'panel_mesh':
            return ref('mesh_sliding')
        if scope == 'mesh_attachment':
            return ref('mesh_addons')
        if scope in JOINT_SCOPES:
            return ref('joints')
        if scope == 'panel_opening':
            if role == 'sliding':
                return ref('sliding')
            if role in ('openable', 'tiltturn'):
                return ref('openable')
        return self.browse()

    @api.model
    def _migrate_line_sections(self):
        """Give every existing spec line its section, ONCE.

        Nothing is re-priced: each line goes to the section that matches
        what its position's scope already did, and the explosion treats a
        line with no section exactly as before, so a line that fits no
        rule is listed in the log and left alone rather than guessed.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PARAM):
            return 0
        Line = self.env['aw.profile.section.line']
        lines = Line.with_context(active_test=False).search([
            ('spec_id', '!=', False), ('spec_section_id', '=', False)])
        assigned, left = 0, []
        for line in lines:
            section = self._section_for(line.position_id, line.spec_id)
            if section:
                line.spec_section_id = section
                assigned += 1
            else:
                left.append('%s / %s' % (
                    line.spec_id.display_name, line.position_id.display_name))
        if left:
            _logger.warning(
                "aw_fenestration_core: %s spec line(s) fit no section and "
                "were left without one: %s", len(left), '; '.join(left))
        param.set_param(PARAM, '1')
        return assigned
