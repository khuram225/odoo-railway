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
- Leaf Types: single source of truth for leaf mechanisms (Fixed, Slider,
  Casement, Awning, Hopper, Mesh, Tilt & Turn) -- used by Window Series
  (which it can host), Design Leaves (which type a leaf is), and Hardware
  Set lines (which type triggers a hardware item)
- Profile Positions: open-ended list of where a profile sits in the frame
  (Outer Frame/Palay/Bead x Top/Bottom/Sides, Mesh, Dividers) -- add a row,
  no schema change
- Window Series: the specific product family (Double Glaze Sliding, Single
  Glaze Fix, Curtain Wall Fix, Tilt & Turn Series, Casement Single/Double
  Glaze, etc.) -- the only classification layer; the earlier Window Kind/
  Window Type intermediate layers were dropped in the structure design
  consolidation
- Profile Sections: which profile product fills each position, for a given
  Window Series
- Hardware Sets: named bundles of hardware products (roller, lock, handle, hinge...) for a Window Series
- Glass Specs: named glass product references
- Window Templates: the assembly of one Profile Section + one Hardware Set + one Glass Spec
  for a Window Series — this is what a quote position ultimately points to.

Also seeds the product category tree used by Inventory:
Fenestration / Profiles / <per Window Series>, Fenestration / Hardware / <sub-groups>,
Fenestration / Glass / <sub-groups>.

This module intentionally holds master data only — no quoting, no geometry, no stock.lot
length tracking. Those live in downstream modules (aw_fenestration_design, aw_fenestration_quote,
aw_fenestration_stock) that depend on this one.
    """,
    'author': 'Khurram',
    'website': 'https://mycrewvault.com',
    'license': 'LGPL-3',
    'depends': ['product', 'stock', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/dynamic_seed_data.xml',
        'data/product_category_data.xml',
        'data/chawla_attributes_data.xml',
        'data/chawla_profiles_data.xml',
        'views/window_series_views.xml',
        'views/dynamic_views.xml',
        'views/profile_section_views.xml',
        'views/hardware_set_views.xml',
        'views/glass_spec_views.xml',
        'views/window_template_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}
