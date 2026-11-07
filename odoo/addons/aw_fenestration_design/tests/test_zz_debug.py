# -*- coding: utf-8 -*-
"""TEMPORARY diagnostics: each probe fails on purpose so the values reach the
annotation. Never merged."""
from odoo.addons.aw_fenestration_design.tests import (
    test_chatter_glass_hardware as m_chatter,
    test_configurator_roundtrip as m_round,
    test_cut_rules as m_cut,
    test_glass_stack as m_glass)
from odoo.tests import tagged

TestChatterGlassHardware = m_chatter.TestChatterGlassHardware
TestConfiguratorRoundTrip = m_round.TestConfiguratorRoundTrip
TestCutRules = m_cut.TestCutRules
TestGlassStack = m_glass.TestGlassStack
del m_chatter, m_round, m_cut, m_glass

SQFT_PER_SQM = 10.7639


def _off(cls, base):
    for name in dir(base):
        if name.startswith('test_') and name not in cls.__dict__:
            setattr(cls, name, None)


def _line(l):
    return ('p%s' % l.panel_no, l.glass_label, 'rate=%s' % l.rate_list,
            'manual=%s' % l.rate_is_manual, 'sqm=%.4f' % l.area_sqm,
            'cost=%.2f' % l.line_cost, 'src=%s' % l.calc_source,
            'w=%s h=%s' % (l.glass_w, l.glass_h))


@tagged('post_install', '-at_install')
class ZGlass(TestGlassStack):

    def test_zz_u1_empty_rules(self):
        spec = self.design.template_id
        spec.write({f: False for f in self.RULES})
        self.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        self._set_header([self._sheet(6), self._gap(), self._sheet(6)])
        lines = self._lines()
        sheets = lines.filtered(lambda l: l.glass_part_kind == 'sheet')
        out = ['sheets=%s' % [_line(l) for l in sheets],
               'rates=%s' % [(r.glass_type_id.name, r.thickness_mm, r.price,
                              str(r.date_from)) for r in self.env['aw.glass.rate'].search([])],
               'vendor=%s order_vendor=%s' % (self.vendor, self.order.aw_glass_vendor_id),
               'header=%s' % [(p.kind, p.thickness_mm) for p in self.design.glass_part_ids],
               'panels=%s' % [(l.panel_no, [(p.kind, p.thickness_mm) for p in l.glass_part_ids])
                              for l in self.leaves]]
        self.fail(' || '.join(out))

    def test_zz_u2_typed_rate(self):
        self._set_header([self._sheet(6, rate_manual=True, manual_rate=55.0)])
        self.design._explode()
        out = ['checks=%s' % [(c.level, c.message) for c in self.design.check_line_ids]]
        self.fail(' || '.join(out))


_off(ZGlass, TestGlassStack)


@tagged('post_install', '-at_install')
class ZChatter(TestChatterGlassHardware):

    def test_zz_u3_chatter(self):
        out = []

        def window(data):
            data['header']['glass_stack'] = [
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0},
                {'kind': 'gap', 'gap_mm': 12.0, 'spacer_type': 'Aluminium',
                 'spacer_colour': 'Silver', 'gas': 'Air'},
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}]
        self._save(window)
        out.append('1:%s' % self._text(self._last())[:200])

        def panel(data):
            data['rows'][0]['leaves'][1]['glass_parts'] = [
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 8.0,
                 'rate_manual': True, 'manual_rate': 55.0}]
        self._save(panel)
        out.append('2:%s' % self._text(self._last())[:200])

        def change(data):
            part = data['rows'][0]['leaves'][1]['glass_parts'][0]
            part.update(thickness_mm=10.0, rate_manual=False, manual_rate=0.0)
        self._save(change)
        out.append('3:%s' % self._text(self._last())[:300])
        out.append('msgs=%s' % len(self.design.message_ids))
        out.append('panel2 parts now=%s' % [
            (p.thickness_mm, p.rate_manual) for p in
            self.design.row_ids.leaf_ids.sorted('panel_no')[1].glass_part_ids])
        self.fail(' || '.join(out))


_off(ZChatter, TestChatterGlassHardware)


@tagged('post_install', '-at_install')
class ZRound(TestConfiguratorRoundTrip):

    def test_zz_u4_clear(self):
        self.design.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])
        data = self.design.get_configurator_data()
        header = dict(data['header'], glass_stack=[])
        self.design.save_layout({'header': header, 'rows': data['rows']})
        out = ['after=%s' % [(p.kind, p.thickness_mm, p.glass_type_id.name)
                             for p in self.design.glass_part_ids],
               'spec glass=%s' % [(p.kind, p.thickness_mm)
                                  for p in self.design.template_id.glass_part_ids],
               'template=%s' % self.design.template_id.display_name]
        self.fail(' || '.join(out))

    def test_zz_u5_header(self):
        self.design.manual_rate = 123.45
        self.design.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])
        data = self.design.get_configurator_data()
        before = self._header_snapshot()
        self.design.save_layout({'header': data['header'], 'rows': data['rows']})
        after = self._header_snapshot()
        moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        self.fail('moved=%s' % moved)


_off(ZRound, TestConfiguratorRoundTrip)


@tagged('post_install', '-at_install')
class ZCut(TestCutRules):

    def test_zz_u6_precision(self):
        from odoo.addons.aw_fenestration_core.models.units import to_display, to_mm
        rail = self._pieces(self.p_rail)[0]
        rail.with_context(aw_bom_generating=True).write({
            'computed_length_mm': 1209.20, 'length_mm': 1209.20,
            'is_manual': False})
        out = ['typed=%s display=%s display(computed)=%s' % (
            to_mm('47-5'), to_display(to_mm('47-5')), to_display(1209.20))]
        rail.write({'length_mm': to_mm('47-5')})
        out.append('after typing: manual=%s length=%s computed=%s' % (
            rail.is_manual, rail.length_mm, rail.computed_length_mm))
        self.fail(' || '.join(out))


_off(ZCut, TestCutRules)
