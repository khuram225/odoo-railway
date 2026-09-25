# -*- coding: utf-8 -*-
"""The generic position product, and its one-shot move to a Service.

Confirming a quote failed with "No rule has been found to replenish
'Fenestration Position' in 'Inter-warehouse transit'", once per line.

Two things combined. First, 'Fenestration Position' was `consu`, and
since Odoo 17 a consu product is Goods: confirming a sale runs
procurement for it and wants a delivery, whether or not it is storable.
Second, the destination that procurement asks for is
`partner_shipping_id.property_stock_customer` (sale_stock's
`_get_location_final`), and on this database that resolves to the
company's transit location -- see the report in the commit message.
There is no rule to replenish anything in transit, so it raised.

Until there is a real production and installation flow for windows,
a position is not a delivery. Making it a Service removes the
procurement entirely rather than papering over the location, which is
the honest shape for what it currently represents: work that is
quoted and invoiced, not goods that are shipped.

**[revisit]** once production/installation exists, when a position may
well become Goods again with a proper route.
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)

SERVICE_VALUES = {
    'type': 'service',
    # Invoice on ordered quantities: there is no delivery to measure
    # against, so "delivered" would never advance.
    'invoice_policy': 'order',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _migrate_position_product_to_service(self):
        """Turn the position product into a Service, once.

        Deliberately SKIPS rather than raises when it cannot act. This
        runs from a <function> during module upgrade, and an upgrade
        that dies because a product once moved stock would be a far
        worse failure than a product left as it is with a line in the
        log. "Refuse" here means "do not touch it", not "break the
        install".

        Idempotent on purpose: the client may well have changed this by
        hand to unblock their own testing, and finding it already done
        is a success, not a conflict.
        """
        product = self.env.ref(
            'aw_fenestration_design.product_fenestration_position',
            raise_if_not_found=False)
        if not product:
            return False

        if product.type == 'service':
            # Already a service, whether by this function on an earlier
            # upgrade or by hand. Make sure the invoice policy matches
            # and leave everything else alone.
            if product.invoice_policy != 'order':
                product.invoice_policy = 'order'
            return True

        moves = self.env['stock.move'].sudo().search_count([
            ('product_id', 'in', product.product_variant_ids.ids),
        ])
        if moves:
            _logger.warning(
                "aw_fenestration_design: '%s' still has %s stock move(s), "
                "so it was left as Goods. Changing it now would orphan "
                "those moves. Clear them first, then re-run "
                "_migrate_position_product_to_service().",
                product.display_name, moves)
            return False

        product.write(dict(SERVICE_VALUES))
        _logger.info(
            "aw_fenestration_design: '%s' is now a Service, invoiced on "
            "ordered quantities.", product.display_name)
        return True
