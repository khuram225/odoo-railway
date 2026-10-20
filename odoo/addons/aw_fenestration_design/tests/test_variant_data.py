# -*- coding: utf-8 -*-
"""Variant data: one attribute line per attribute, references from a fixed
table, profiles costed per foot."""
from odoo.addons.aw_fenestration_core.models.variant_codes import (
    variant_reference)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVariantCodes(TransactionCase):

    def test_reference_is_code_thickness_finish(self):
        self.assertEqual(
            variant_reference('D-29', 'Normal', 'Natural'),
            ('D-29-NOR-NAT', []))
        self.assertEqual(
            variant_reference('GSL-03', '1.6MM', 'Brown PC Sahara'),
            ('GSL-03-16-SAH', []))

    def test_a_value_outside_the_table_gets_no_reference(self):
        self.assertEqual(
            variant_reference('X-1', '2.2MM', 'Natural'), ('', ['2.2MM']))

    def test_no_thickness_dimension_is_code_finish(self):
        self.assertEqual(
            variant_reference('Y-1', '', 'Designer'), ('Y-1-DSG', []))


@tagged('post_install', '-at_install')
class TestAttributeLines(TransactionCase):

    def test_a_second_line_for_the_same_attribute_is_merged(self):
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        first, second = finish_attr.value_ids[:2]
        template = self.env['product.template'].create({
            'name': 'LINE-GUARD',
            'attribute_line_ids': [
                (0, 0, {'attribute_id': finish_attr.id,
                        'value_ids': [(6, 0, first.ids)]}),
                (0, 0, {'attribute_id': finish_attr.id,
                        'value_ids': [(6, 0, second.ids)]}),
            ]})
        lines = template.attribute_line_ids.filtered(
            lambda l: l.attribute_id == finish_attr)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.value_ids, first | second)

    def test_repeating_the_same_command_adds_no_line(self):
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        values = finish_attr.value_ids[:2]
        template = self.env['product.template'].create({
            'name': 'LINE-REPEAT',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': finish_attr.id,
                'value_ids': [(6, 0, values.ids)]})]})
        template.write({'attribute_line_ids': [(0, 0, {
            'attribute_id': finish_attr.id,
            'value_ids': [(6, 0, values.ids)]})]})
        self.assertEqual(len(template.attribute_line_ids), 1)
