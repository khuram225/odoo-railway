# -*- coding: utf-8 -*-
"""TEMPORARY diagnostics: each test fails on purpose so the numbers reach the
annotation. Never merged."""
import os
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestZDebug(TransactionCase):

    def test_zz_glass(self):
        env = self.env
        Type = env['aw.glass.type']
        Type._seed_glass_types()
        Type._seed_glass_vendor()
        Type._seed_glass_sheet()
        vendor = Type._default_glass_vendor()
        path = os.path.join(os.path.dirname(__file__), 'data',
                            'ghani_glass_2026_07_01.txt')
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        rl = env['aw.vendor.rate.list'].create({
            'kind': 'glass', 'vendor_id': vendor.id,
            'date': date(2026, 7, 1), 'paste_text': text})
        rl.action_parse_paste()
        rl.action_apply()
        grey = Type.search([('name', '=', 'Grey')])
        out = ['vendor=%s' % vendor.display_name,
               'rates=%s' % env['aw.glass.rate'].search_count([]),
               'grey=%s colour=%s kind=%s' % (
                   grey, grey.colour_id.name, grey.kind_id.name),
               'twins=%s' % Type.search([
                   ('colour_id', '=', grey.colour_id.id),
                   ('kind_id', '=', grey.kind_id.id)]).mapped('name')]
        variant = grey._variant_for(6)
        out.append('variant=%s' % variant)
        if variant:
            key = variant._aw_glass_key()
            out.append('key=%s mm=%s' % (key[0].mapped('name'), key[1]))
            out.append('values=%s' % variant.product_template_variant_value_ids
                       .product_attribute_value_id.mapped(
                           lambda v: '%s:%s' % (v.attribute_id.name, v.name)))
            rate = env['aw.glass.rate']._rate_for(
                grey, 6, date.today(), vendor)
            out.append('rate_for_grey=%s today=%s' % (rate.price, date.today()))
            out.append('aw_glass_rate=%s' % variant.aw_glass_rate)
        self.fail(' || '.join(out))

    def test_zz_panel_opening(self):
        from odoo.addons.aw_fenestration_design.tests.test_cut_rules import (
            TestPanelOpening)
        design, fixed = TestPanelOpening._make(self, 144, 144)
        TestPanelOpening._row(self, design, 144, [48, 48, 48], fixed)
        design._renumber_panels()
        design._explode()
        out = ['template=%s' % design.template_id.name,
               'spec lines used=%s' % [
                   (l.position_id.name, l.is_used, l.product_tmpl_id.name)
                   for l in design.template_id.profile_line_ids
                   if 'PO' in (l.position_id.name or '')],
               'bom=%s' % [(l.kind, l.label, l.panel_no, l.length_mm)
                           for l in design.bom_line_ids],
               'checks=%s' % design.check_line_ids.mapped('message')]
        self.fail(' || '.join(out))

    def test_zz_seeds(self):
        env = self.env
        param = env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.premium_layout_seeded', False)
        param.set_param('aw_fenestration.chawla_layout_seeded', False)
        L = env['aw.vendor.layout']
        out = ['premium=%s' % L._seed_premium_layout(),
               'chawla=%s' % L._seed_chawla_layout(),
               'layouts=%s' % [(l.vendor_id.name, len(l.column_ids))
                               for l in L.search([])]]
        self.fail(' || '.join(out))
