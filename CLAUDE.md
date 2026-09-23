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
- `odoo/addons/aw_fenestration_core/` — master data for the aluminum windows
  business: `aw.window.kind`, `aw.window.type`, `aw.window.series`,
  `aw.profile.section`, `aw.hardware.set`, `aw.glass.spec`,
  `aw.window.template`. See below.
- `odoo/addons/aw_fenestration_design/` — per-quote design geometry
  (`aw.design` → row → leaf), depends on `aw_fenestration_core` + `sale`.
  See below.

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

## aw_fenestration_core

Master data only — no quoting, no geometry, no stock.lot length tracking.
Chatter (`mail.thread` + `mail.activity.mixin`, `tracking=True` on names and
key relations) on all 6 top-level models; the `.line` models (profile
section lines, hardware set lines) don't get their own chatter, they're
edited inline on the parent.

Three-layer master-data hierarchy: `aw.window.kind` (leaf-type rule set:
Sliding, Hinged/Casement, Fixed only, Tilt & Turn) → `aw.window.type` (broad
category: Sliding Window, Fix Window, Curtain Wall Fix Window, Open-able
Window, Tilt & Turn Window, Door — `kind_id` optional here, e.g. Door has
none) → `aw.window.series` (specific product family: Box Series, Collar Box,
Round Series, GSL Slim, Hinged/Casement, Curtain Wall — `window_type_id`
required, `kind_id` is a `related`+`store` passthrough of
`window_type_id.kind_id`, not set directly). `aw.window.series` is what
`aw.profile.section`/`aw.hardware.set`/`aw.window.template`'s
`window_type_id` field actually points at (comodel `aw.window.series`,
field name unchanged from before the Type layer existed — don't be misled
by the field name into thinking it points at `aw.window.type`).

Seeded via `data/window_kind_data.xml`, `data/window_type_data.xml`, then
`data/product_category_data.xml` (product category tree + the 6 Window
Series, which reference Type records from the file before it — that load
order matters) and `data/chawla_attributes_data.xml` +
`data/chawla_profiles_data.xml` (the Chawla pricelist import — regenerate
both from the melt CSV with `scripts/rebuild_melt_and_import.py`, never
hand-edit them).

**`hooks.py`'s `post_init_hook` creates records without an `ir.model.data`
entry** (the "Box Series - Standard" `aw.profile.section` and the 5 product
variants it needs). That means:
- Module uninstall does **not** clean these up automatically — only
  XML-declared records get deleted on uninstall.
- `aw.profile.section.window_type_id` and `aw.profile.section.line.product_id`
  are both `ondelete='restrict'`, so this leftover section blocks deletion
  of the Window Series and product variants it references.
- **A straight uninstall will fail.** Before uninstalling, delete the
  "Box Series - Standard" Profile Section by hand first (cascades to its
  5 lines) — then uninstall, then reinstall. `post_init_hook` is
  idempotent and recreates it identically on reinstall.

This module has been uninstall/reinstalled rather than live-migrated
multiple times now (Kind field-type change, then the Type-layer insertion
above) — this is still test data, so that's the deliberate choice each
time rather than writing migration scripts, which is why the sequence
above keeps mattering.

**View/data load-order chains that broke a real install before** — two
concrete Odoo-19 behaviors, not lazy: `%(xmlid)d` inside a `type="xml"`
field is resolved *eagerly* during `convert_xml_import`, and `ref="..."`
on a scalar field the same way. Both require the target to already exist
in `ir.model.data` at that exact point in the manifest's `data` list, not
just somewhere earlier. Current chains: `window_kind_data.xml` →
`window_type_data.xml` → `product_category_data.xml` (Series refs Type
and Kind); `window_series_views.xml` → `window_type_views.xml` (Type's
stat button refs `action_aw_window_series`) → `window_kind_views.xml`
(Kind's stat button refs `action_aw_window_type`). Adding a
`%(xmlid)d`/cross-file `ref=` anywhere else in this module means adding
to (or verifying against) this chain, not assuming render-time
resolution — see `odoo/tools/convert.py`'s `_tag_record`/`_eval_xml`, not
`ir_ui_view.py`'s `resolve_external_ids` (that one's for dev-mode
re-reads, a different and later mechanism).

## aw_fenestration_design

Data model only, deliberately — `aw.design.action_explode()` is a stub that
raises `NotImplementedError`. The explosion engine, manufacturability
checks, the coupler action, and the visual canvas are separate follow-on
work, not in this module. `aw.design` (top-level, chatter, `active`) →
`aw.design.row` → `aw.design.leaf` (both plain child models, no chatter,
matching the `.line`-model convention) → `aw.design.bom.line` (explosion
output, never hand-entered).

`aw.design.window_series_id`/`template_id` point at `aw.window.series`/
`aw.window.template`; `finish_id`/`thickness_id` are `product.attribute.value`
records domained by `ref()` to `aw_fenestration_core.aw_attribute_finish`/
`aw_attribute_thickness` (not name-string matching — a renamed attribute
would silently break that instead of erroring).

New group: `group_fenestration_sales` ("Fenestration / Sales"), separate
from core's `group_fenestration_manager` — quote-level Design access and
master-BOM-data access are two different grants. `security.xml` extends
`aw_fenestration_core.group_fenestration_manager`'s `implied_ids` by its
full external ID (cross-module record extension — confirmed genuine core
Odoo practice, not a workaround: `purchase/security/purchase_security.xml`
does the identical thing to `base.group_user`).

Caught two real bugs before this ever reached a live install, both repeats
of mistakes already made and fixed in `aw_fenestration_core` — worth
knowing the pattern, since it'll happen again: a stat button using
`type="object"` with a `%(xmlid)d` action reference (needs `type="action"`),
and an action record defined *after* the view that references it via
`%(xmlid)d` in the same file (that substitution resolves eagerly at parse
time — see the load-order note above).

## XML comment check

`scripts/check_xml_comments.py` rejects `--` inside `<!-- -->` comments —
illegal XML, breaks well-formedness, and has broken a deploy from this repo
twice already (both times in autogenerated `aw_fenestration_core` data files).
Wired as a pre-commit hook in `.githooks/pre-commit`, but git only runs hooks
from `.git/hooks` by default, which isn't tracked — enable it once per clone:

```
git config core.hooksPath .githooks
```

Until that's run, check manually before committing XML: `python
scripts/check_xml_comments.py`.
