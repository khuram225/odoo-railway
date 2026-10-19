# -*- coding: utf-8 -*-
"""The position catalog: every spec has a row for every scoped position,
unused until mapped, and only used rows reach a window."""
import unittest

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPositionCatalog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.series = cls.env.ref(
            'aw_fenestration_core.window_series_casement_dg',
            raise_if_not_found=False)
        cls.glass = cls.env['aw.glass.spec'].search([], limit=1)
        if not (cls.series and cls.glass):
            raise unittest.SkipTest("Seed data is missing")
        cls.spec = cls.env['aw.window.template'].create({
            'name': 'CAT', 'window_type_id': cls.series.id,
            'glass_spec_id': cls.glass.id})
        cls.positions = cls.env['aw.profile.position'].search(
            [('scope', '!=', False)])

    def test_new_spec_gets_an_unused_row_per_position(self):
        lines = self.spec.profile_line_ids
        self.assertEqual(lines.position_id, self.positions)
        self.assertFalse(lines.filtered('is_used'))
        self.assertEqual(self.spec.profile_line_count, 0)

    def test_unused_rows_never_reach_a_window(self):
        design = self.env['aw.design'].new({
            'window_series_id': self.series.id,
            'template_id': self.spec.id})
        self.assertFalse(design._spec_profile_lines())

    def test_using_a_row_needs_a_profile_and_then_counts(self):
        line = self.spec.profile_line_ids[0]
        with self.assertRaises(ValidationError):
            line.is_used = True
        profile = self.env['product.template'].search([
            ('categ_id', 'child_of', self.env.ref(
                'aw_fenestration_core.product_category_profiles').id)],
            limit=1)
        line.write({'is_used': True, 'product_tmpl_id': profile.id})
        self.assertEqual(self.spec.profile_line_count, 1)

    def test_new_position_reaches_every_spec(self):
        position = self.env['aw.profile.position'].create({
            'name': 'CAT test position', 'scope': 'frame', 'edge': 'top',
            'default_length': 'W'})
        self.assertIn(position, self.spec.profile_line_ids.position_id)

    def test_names_are_unique_and_english(self):
        names = self.positions.mapped('name')
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse([n for n in names if 'palay' in n.lower()])

    def test_mesh_parts_exist_and_bead_is_optional(self):
        mesh = self.positions.filtered(lambda p: p.scope == 'mesh_attachment')
        self.assertEqual(len(mesh), 6)
        self.assertTrue(all(
            p.is_required for p in mesh if 'Frame' in p.name))
        self.assertFalse(any(
            p.is_required for p in mesh if 'Bead' in p.name))

    def test_copy_from_series_is_one_time_and_only_on_an_empty_series(self):
        source = self.env['aw.window.template'].search(
            [('id', '!=', self.spec.id)], limit=1)
        if not source.profile_line_ids.filtered('is_used'):
            raise unittest.SkipTest("No mapped series to copy from")
        self.env['aw.window.template.copy.wizard'].create({
            'target_id': self.spec.id, 'source_id': source.id}).action_copy()
        self.assertEqual(
            len(self.spec.profile_line_ids.filtered('is_used')),
            len(source.profile_line_ids.filtered('is_used')))
        with self.assertRaises(Exception):
            self.env['aw.window.template.copy.wizard'].create({
                'target_id': self.spec.id,
                'source_id': source.id}).action_copy()
