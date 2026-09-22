# odoo-railway

Odoo 19 Community, deployed on Railway. This is a **deployment repo**, not the
Odoo source: `odoo/Dockerfile` builds an Odoo image and copies `odoo/addons/`
to `/mnt/extra-addons` (the `addons_path` in `odoo/odoo.conf`). Custom modules
live under `odoo/addons/`.

A read-only reference clone of official Odoo 19.0 (`git clone --depth 1
--branch 19.0 https://github.com/odoo/odoo.git`) is kept as a sibling folder,
`../odoo-src`, for checking core model/view definitions before extending them.
It is not part of this repo.

## Custom modules

- `odoo/addons/hello_check/` — pipeline smoke-test module (depends on `base`
  only, no models/views). Confirms the addons path wiring works end to end.
- `odoo/addons/aluminum_inventory/` — first real business module, for an
  aluminum windows manufacturing operation. See below.

## aluminum_inventory

Extends `stock.lot` via `_inherit` (does not modify `stock/models/stock_lot.py`
or `stock/views/stock_lot_views.xml` directly). This is the **first extension
of `stock.lot`** in this codebase — if you're adding more fields to lots,
extend this module's `models/stock_lot.py` and the view xpath in
`views/stock_lot_views.xml` rather than creating a second inheriting module,
to avoid load-order/xpath-target conflicts.

Fields added to `stock.lot`:
- `length_mm` (Integer) — physical length of this lot's sticks, in mm.
- `profile_source` (Selection: `purchased` / `leftover_return`) — where the
  lot came from.
- `parent_lot_id` (Many2one → `stock.lot`, nullable) — for a leftover, the
  original stick lot it was cut from.

The view inherits `stock.view_production_lot_form` and adds a new "Aluminum
Profile" group via xpath (`group[@name='inventory_group']`, position
`after`). `parent_lot_id` is only shown when `profile_source ==
'leftover_return'`.

Confirmed against the Odoo 19.0 source (`../odoo-src/addons/stock/models/stock_lot.py`)
before adding these fields — no naming conflicts with core `stock.lot` fields.
