# -*- coding: utf-8 -*-
"""Mesh for the RE series: a PLACEHOLDER mapping, until the workshop gives
the real mesh profile and bead codes.

  * Mesh > Frame (top, bottom, side) uses the profile the sliding series
    (GSL) already uses for its mesh panel frame.
  * Mesh > Bead uses RE-10, the same bead as the sash. PLACEHOLDER.
  * The cloth is deducted from the opening: OW - soot(2) by OH - soot(2).
  * Each Mesh Type gets a "Mesh cloth" product with cost 0, so the checks
    flag the missing cost instead of the cloth pricing at nothing quietly.

Fill-only and one-shot: nothing already configured is overwritten.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PARAM = 'aw_fenestration.re_mesh_placeholder_seeded'
FRAME_XMLIDS = ('pos_mesh_frame_top', 'pos_mesh_frame_bottom',
                'pos_mesh_frame_sides')
BEAD_XMLIDS = ('pos_mesh_bead_top', 'pos_mesh_bead_bottom',
               'pos_mesh_bead_sides')


class AwWindowTemplate(models.Model):
    _inherit = 'aw.window.template'

    @api.model
    def _seed_re_mesh(self):
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(PARAM):
            return {}
        report = {'frame': 0, 'bead': 0, 'deductions': 0, 'cloth': 0}

        def position(xmlid):
            return self.env.ref(
                'aw_fenestration_core.%s' % xmlid, raise_if_not_found=False)

        # The sliding series' mesh frame profile, if it has one.
        mesh_panel = position('pos_mesh_all')
        source = self.env['aw.profile.section.line'].search([
            ('position_id', '=', mesh_panel.id), ('is_used', '=', True),
            ('spec_id', '!=', False)], limit=1) if mesh_panel else None
        frame_product = source.product_tmpl_id if source else None
        bead_product = self.env['aw.profile.section']._find_profile_template(
            'RE-10')

        for spec in self.with_context(active_test=False).search(
                [('name', '=', 'RE')]):
            spec._sync_catalog_lines()
            for xmlid, product, key in (
                    [(x, frame_product, 'frame') for x in FRAME_XMLIDS]
                    + [(x, bead_product, 'bead') for x in BEAD_XMLIDS]):
                pos = position(xmlid)
                line = spec.profile_line_ids.filtered(
                    lambda l, p=pos: l.position_id == p)[:1]
                if not (pos and line and product) or line.is_used:
                    continue
                line.write({'is_used': True, 'product_tmpl_id': product.id})
                report[key] += 1
            for field, formula in (('mesh_w', 'OW - soot(2)'),
                                   ('mesh_h', 'OH - soot(2)')):
                if not spec[field]:
                    spec[field] = formula
                    report['deductions'] += 1

        cloth = self.env.ref('aw_fenestration_design.product_mesh_cloth',
                             raise_if_not_found=False)
        if cloth:
            variant = cloth.product_variant_id
            for mesh in self.env['aw.mesh.type'].with_context(
                    active_test=False).search([]):
                if not mesh.line_ids:
                    self.env['aw.mesh.type.line'].create({
                        'mesh_type_id': mesh.id,
                        'product_id': variant.id,
                        # Square metres of cloth for this panel.
                        'qty_formula': 'OW * OH / 1000000',
                    })
                    report['cloth'] += 1
        param.set_param(PARAM, '1')
        _logger.info("aw_fenestration_design: RE mesh placeholder: %s", report)
        return report
