# -*- coding: utf-8 -*-
"""One line per position per spec, counting USED lines only. Every catalog
position has an unused placeholder row on every spec; the rule used to count
it, so adding the line was refused as a duplicate of a row nobody could see,
while the Check said the spec had no line."""
import unittest

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOneLinePerPosition(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Line = env['aw.profile.section.line']
        cls.spec = env['aw.window.template'].search([], limit=1)
        cls.profile = cls.Line.search(
            [('product_tmpl_id', '!=', False)], limit=1).product_tmpl_id
        if not (cls.spec and cls.profile):
            raise unittest.SkipTest("No spec or profile in this database")
        cls.position = env['aw.profile.position'].create({
            'name': 'Test mesh frame', 'scope': 'mesh_attachment',
            'edge': 'top', 'default_length': 'PW', 'default_qty': '1'})
        cls.spec._sync_catalog_lines(cls.position)
        cls.row = cls.Line.search([
            ('spec_id', '=', cls.spec.id), ('position_id', '=', cls.position.id)])

    def _new(self, **extra):
        return self.Line.create(dict({
            'spec_id': self.spec.id, 'position_id': self.position.id,
            'product_tmpl_id': self.profile.id}, **extra))

    def test_the_placeholder_row_is_not_a_line(self):
        self.assertEqual(len(self.row), 1)
        self.assertFalse(self.row.is_used)
        self.assertNotIn(self.row, self.spec._live_profile_lines())

    def test_a_new_line_takes_over_the_placeholder_instead_of_clashing(self):
        line = self._new()
        self.assertEqual(line, self.row)            # same record, adopted
        self.assertTrue(line.is_used)
        self.assertEqual(line.product_tmpl_id, self.profile)
        self.assertEqual(self.Line.search_count([
            ('spec_id', '=', self.spec.id),
            ('position_id', '=', self.position.id)]), 1)

    def test_a_second_used_line_is_refused_and_the_error_names_the_first(self):
        first = self._new()
        with self.assertRaises(ValidationError) as caught:
            self.Line.create({
                'spec_id': self.spec.id, 'position_id': self.position.id,
                'product_tmpl_id': self.profile.id,
                'sequence': first.sequence + 1, 'is_used': True,
                'spec_section_id': first.spec_section_id.id,
                'cut_on_site': True})
        text = str(caught.exception)
        self.assertIn(self.position.display_name, text)
        self.assertIn(self.profile.display_name, text)
        self.assertIn('Profiles tab', text)

    def test_an_unused_duplicate_is_not_a_clash(self):
        self._new()
        extra = self.Line.create({
            'spec_id': self.spec.id, 'position_id': self.position.id,
            'is_used': False})
        self.assertFalse(extra.is_used)

    def test_the_rule_and_the_check_use_the_same_definition(self):
        self._new()
        design = self.env['aw.design'].search(
            [('template_id', '=', self.spec.id)], limit=1)
        if design:
            self.assertEqual(
                design._spec_profile_lines(), self.spec._live_profile_lines())
        self.assertIn(self.position, self.spec._live_profile_lines().position_id)
