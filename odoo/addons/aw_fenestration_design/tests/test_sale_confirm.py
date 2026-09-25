# -*- coding: utf-8 -*-
"""Confirming a quote with fenestration positions must be boring.

The regression this exists for: confirming failed with "No rule has
been found to replenish 'Fenestration Position' in 'Inter-warehouse
transit'", once per line. The product was `consu`, which since Odoo 17
means Goods, so confirmation ran procurement and looked for a delivery
route to a location that has none.

A position is not a delivery until there is a production and
installation flow, so the product is a Service and confirmation should
produce no picking at all. Asserting "no pickings" rather than "no
exception" is deliberate: an exception is the symptom, a stray picking
is the cause, and a future change that reintroduces Goods would create
the picking long before anyone hit a location without a rule.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleConfirm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Fenestration Test Customer',
        })
        cls.series = cls.env['aw.window.series'].search([], limit=1)
        if not cls.series:
            cls.series = cls.env['aw.window.series'].create({
                'name': 'Confirm Test Series',
            })

    def _order_with_positions(self, count=2):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'aw_default_series_id': self.series.id,
        })
        for index in range(count):
            design = order._create_fenestration_position(
                self.series, name='D%s' % (index + 1))
            # Real dimensions: confirmation is blocked without them, and
            # a test that passed on zero-sized positions would not be
            # testing confirmation at all.
            design.write({'width_mm': 1200.0, 'height_mm': 1500.0})
        return order

    def test_position_product_is_a_service(self):
        product = self.env.ref(
            'aw_fenestration_design.product_fenestration_position')
        self.assertEqual(
            product.type, 'service',
            "The position product must be a Service: as Goods, confirming "
            "a quote runs procurement and asks for a delivery route.")
        self.assertEqual(
            product.invoice_policy, 'order',
            "There is no delivery to measure, so invoicing on delivered "
            "quantities would never advance.")

    def test_confirm_creates_no_pickings(self):
        order = self._order_with_positions()
        self.assertEqual(len(order.order_line), 2)

        order.action_confirm()

        self.assertEqual(order.state, 'sale')
        self.assertFalse(
            order.picking_ids,
            "Confirming fenestration positions created %s picking(s). A "
            "position is quoted work, not goods to ship."
            % len(order.picking_ids))
        moves = self.env['stock.move'].search([
            ('sale_line_id', 'in', order.order_line.ids),
        ])
        self.assertFalse(
            moves, "Confirmation generated stock moves for a Service.")

    def test_confirm_survives_a_transit_customer_location(self):
        """The exact shape that broke: a customer whose delivery location
        is the company's transit location.

        Odoo does this to itself -- stock.warehouse._update_partner_data
        rewrites property_stock_customer to the transit location for
        whichever partner is a warehouse's address. Selling to that
        partner then has nowhere to deliver to. A Service must not care.
        """
        transit = self.env.company.internal_transit_location_id
        if not transit:
            self.skipTest("No transit location on this company")
        self.partner.with_company(
            self.env.company).property_stock_customer = transit

        order = self._order_with_positions(count=1)
        order.action_confirm()

        self.assertEqual(order.state, 'sale')
        self.assertFalse(
            order.picking_ids,
            "A transit customer location still produced a picking.")
