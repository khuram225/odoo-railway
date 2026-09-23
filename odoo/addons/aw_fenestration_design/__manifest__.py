# -*- coding: utf-8 -*-
{
    'name': 'Fenestration Design',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Window/door design geometry — row/leaf grid, tied to Sale Order lines',
    'description': """
Fenestration Design
====================
Depends on aw_fenestration_core (Window Series, Leaf Type, Profile Position,
Profile Section, Hardware Set, Glass Spec) and Sale.

This module holds the DATA MODEL layer only, ported from the JS prototype's
row/leaf grid shape:

  aw.design            = one prototype QUOTE.designs[] entry, tied to a
                          real sale.order.line so pricing/discount/tax/PDF
                          all come from Odoo's own Sale flow rather than a
                          parallel quote document
  aw.design.row         = d.rows[]  — a horizontal band, has a height
  aw.design.leaf        = row.leaves[] — one opening within a row, has a
                          width and a leaf_type_id (Many2one to
                          aw_fenestration_core's aw.leaf.type -- dynamic,
                          not a hardcoded Selection)
  aw.design.bom.line    = explode()'s OUTPUT — profile pieces, one row per
                          cut length. Populated by the explosion engine,
                          not hand-entered. That engine is NOT part of this
                          module yet — see action_explode() below, which is
                          deliberately a stub. Checks, the coupler action,
                          and the visual canvas are separate follow-on work
                          too, in that order, per the agreed build sequence.
    """,
    'author': 'Khurram',
    'website': 'https://mycrewvault.com',
    'license': 'LGPL-3',
    'depends': ['aw_fenestration_core', 'sale'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/product_data.xml',
        'views/design_views.xml',
        'views/layout_preset_views.xml',
        'views/design_position_wizard_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
}
