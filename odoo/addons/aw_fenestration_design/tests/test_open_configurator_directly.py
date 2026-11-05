# -*- coding: utf-8 -*-
"""The Designs list opens the configurator; the form is the History page."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOpenConfiguratorDirectly(TransactionCase):

    def test_a_row_of_the_designs_list_opens_the_configurator(self):
        arch = self.env['aw.design'].get_view(view_type='list')['arch']
        self.assertIn('action="action_open_configurator"', arch)
        self.assertIn('type="object"', arch)
        self.assertTrue(hasattr(self.env['aw.design'], 'action_open_configurator'))

    def test_the_history_page_is_still_the_form(self):
        design = self.env['aw.design'].search([], limit=1)
        if not design:
            self.skipTest("no design")
        action = design.action_open_design()
        self.assertEqual(
            (action['res_model'], action['res_id'], action['view_mode']),
            ('aw.design', design.id, 'form'))

    def test_the_quote_line_opens_the_configurator(self):
        line = self.env['sale.order.line'].search(
            [('aw_design_ids', '!=', False)], limit=1)
        if not line:
            self.skipTest("no quote line with a window")
        action = line.action_open_configurator()
        self.assertEqual(action.get('type'), 'ir.actions.client')
