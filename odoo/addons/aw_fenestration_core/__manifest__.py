# -*- coding: utf-8 -*-
{
    'name': 'Fenestration Core',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Master data for window/door types, profile sections, hardware sets, glass specs and templates',
    'description': """
Fenestration Core
=================
Foundation module for the aluminium windows & doors ERP.

Defines:
- Window Types (Box Series, Collar Box, Round Series, GSL Slim, Hinged/Casement, Curtain Wall)
- Profile Sections: which profile product fills each structural role (frame/sash/interlock/bead/mesh)
  for a given Window Type
- Hardware Sets: named bundles of hardware products (roller, lock, handle, hinge...) for a Window Type
- Glass Specs: named glass product references
- Window Templates: the assembly of one Profile Section + one Hardware Set + one Glass Spec
  for a Window Type — this is what a quote position ultimately points to.

Also seeds the product category tree used by Inventory:
Fenestration / Profiles / <per Window Type>, Fenestration / Hardware / <sub-groups>,
Fenestration / Glass / <sub-groups>.

This module intentionally holds master data only — no quoting, no geometry, no stock.lot
length tracking. Those live in downstream modules (aw_fenestration_design, aw_fenestration_quote,
aw_fenestration_stock) that depend on this one.
    """,
    'author': 'Khurram',
    'website': 'https://mycrewvault.com',
    'license': 'LGPL-3',
    'depends': ['product', 'stock'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/product_category_data.xml',
        'data/chawla_attributes_data.xml',
        'data/chawla_profiles_data.xml',
        'views/window_type_views.xml',
        'views/profile_section_views.xml',
        'views/hardware_set_views.xml',
        'views/glass_spec_views.xml',
        'views/window_template_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
