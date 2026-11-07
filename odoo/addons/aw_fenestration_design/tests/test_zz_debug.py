# -*- coding: utf-8 -*-
"""DO NOT MERGE. A probe: it fails on purpose so the values reach the annotation."""
from odoo.addons.aw_fenestration_design.tests.common import seeded_family_series
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class ZSuggest(TransactionCase):

    def test_zz_suggestion(self):
        env = self.env
        family, series = seeded_family_series(env)
        order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Probe'}).id,
            'aw_default_series_id': series.id})
        design = order._create_fenestration_position(series, family=family)
        design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        P = env['ir.config_parameter'].sudo()
        out = ['family=%s glazing=%s suggest_glass=%s location=%r' % (
            family.name, family.glazing, design.suggest_glass, design.location),
            'raw params: t1=%r t2=%r wet=%r' % (
                P.get_param('aw_fenestration.glass_threshold_1_m2'),
                P.get_param('aw_fenestration.glass_threshold_2_m2'),
                P.get_param('aw_fenestration.glass_wet_words')),
            'thresholds used=%s' % (design._glass_thresholds(),)]
        leaf = {'width_mm': 1200.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        design.save_layout({
            'header': design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [dict(leaf), dict(leaf)]}]})
        for l in design.row_ids.leaf_ids.sorted('panel_no'):
            area = (l.width_mm or 0) * (l.row_id.height_mm or 0) / 1e6
            out.append('panel %s w=%s h=%s area=%.3f suggested=%s chosen=%s pick=%r parts=%s' % (
                l.panel_no, l.width_mm, l.row_id.height_mm, area,
                l.glass_suggested, l.glass_chosen, design._suggested_glass_for(l),
                [(p.kind, p.thickness_mm, p.gap_mm) for p in l.glass_part_ids]))
        self.fail(' || '.join(out))
