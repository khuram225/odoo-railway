# -*- coding: utf-8 -*-
"""Adding a component with a profile that has several thicknesses: the row
exists with a thickness and the window prices it. It used to raise
"offers no '' thickness" because an added position has no spec line to
take a thickness from."""
import unittest
from datetime import date

from odoo.tests import TransactionCase, tagged

from odoo.addons.aw_fenestration_core.models.thickness import thickness_mm
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)


@tagged('post_install', '-at_install')
class TestAddComponentThickness(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.template = env['product.template'].search(
            [('name', '=', 'HD-3 GROOVE')], limit=1)
        if not cls.template:
            raise unittest.SkipTest("HD-3 GROOVE is not in this database")
        attribute = env.ref('aw_fenestration_core.aw_attribute_thickness')
        cls.offered = env['aw.profile.section.line']._template_values(
            cls.template, attribute)
        if len(cls.offered) < 2:
            raise unittest.SkipTest("HD-3 GROOVE has one thickness here")
        family, series = seeded_family_series(env)
        if not family:
            raise unittest.SkipTest("No glazing family with a profile system")
        cls.order = env['sale.order'].create({
            'partner_id': env['res.partner'].create({'name': 'Thickness customer'}).id,
            'aw_default_series_id': series.id,
        })
        cls.design = cls.order._create_fenestration_position(series, family=family)
        cls.design.write({'width_mm': 2400.0, 'height_mm': 1800.0})
        leaf = {'width_mm': 2400.0, 'leaf_type_id': series.leaf_type_ids[0].id}
        cls.design.save_layout({
            'header': cls.design.get_configurator_data()['header'],
            'rows': [{'height_mm': 1800.0, 'leaves': [leaf]}]})
        # a frame position the spec does not have: an ADDED component
        cls.position = env['aw.profile.position'].create({
            'name': 'Test sill', 'scope': 'frame', 'edge': 'bottom',
            'default_length': 'PW', 'default_qty': '1',
        })
        cls.lowest = min(cls.offered, key=lambda v: (
            thickness_mm(v.name) is None, thickness_mm(v.name) or 0.0))
        for value in cls.offered:
            env['aw.profile.rate'].create({
                'product_tmpl_id': cls.template.id, 'thickness_id': value.id,
                'finish_id': cls.design.finish_id.id, 'price': 100.0,
                'vendor_id': cls.design._costing_vendor().id,
                'date_from': date(2000, 1, 1),
            })

    def _add(self, **extra):
        return self.design.set_override(dict({
            'kind': 'profile', 'position_id': self.position.id,
            'product_tmpl_id': self.template.id, 'added': True}, **extra))

    def test_a_two_thickness_profile_is_added_with_the_lowest_thickness(self):
        self._add()                                     # used to raise
        change = self.design.override_ids.filtered(
            lambda o: o.position_id == self.position)
        self.assertTrue(change.thickness_id)
        self.assertEqual(change.thickness_id, self.lowest)

    def test_the_window_prices_the_added_row(self):
        self._add()
        lines = self.design.bom_line_ids.filtered(
            lambda l: l.kind == 'profile'
            and l.product_id.product_tmpl_id == self.template)
        self.assertTrue(lines)
        self.assertTrue(all(l.product_id for l in lines))
        self.assertEqual(lines[0].unit_cost, 100.0)
        self.assertGreater(lines[0].line_cost, 0.0)

    def test_it_takes_the_thickness_the_window_already_uses(self):
        other = self.offered - self.lowest
        # the window's other lines use the higher thickness
        used = other[:1]
        self.assertEqual(
            self.env['aw.profile.section']._default_thickness_for(
                self.template, self.env['product.attribute.value'], used),
            used)

    def test_a_thickness_the_user_picked_is_kept(self):
        other = (self.offered - self.lowest)[:1]
        self._add(thickness_id=other.id)
        change = self.design.override_ids.filtered(
            lambda o: o.position_id == self.position)
        self.assertEqual(change.thickness_id, other)
