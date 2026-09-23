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
key relations) on the top-level models; the `.line` models (profile section
lines, hardware set lines) don't get their own chatter, they're edited
inline on the parent.

**Structure as of the "major consolidation" round** (this superseded an
earlier 3-layer Kind → Type → Series hierarchy — if you see references to
`aw.window.kind` or `aw.window.type` anywhere outside a historical
docstring/commit message, that's stale, both were deleted entirely):

- `aw.leaf.type` — single source of truth for leaf mechanisms (Fixed,
  Slider, Casement, Awning, Hopper, Mesh, Tilt & Turn — 7 seeded rows).
  Referenced by `aw.window.series.leaf_type_ids` (M2M, which this Series
  can host), `aw.design.leaf.leaf_type_id` (design module), and
  `aw.hardware.set.line.leaf_type_id` (blank = all leaves).
- `aw.profile.position` — open-ended list of where a profile sits in the
  frame (12 seeded rows: Outer Frame/Palay/Fixed Bead × Top/Bottom/Sides,
  Mesh - All Sides, Divider Vertical/Horizontal). Replaces the old fixed
  5-value `role` Selection (frame/sash/interlock/bead/mesh) on
  `aw.profile.section.line` — add a row, no schema change.
- `aw.window.series` — now the **only** classification layer (Double
  Glaze Sliding, Single Glaze Fix, Curtain Wall Fix, Tilt & Turn Series,
  Casement Single/Double Glaze, etc.). `leaf_type_ids` replaces the old
  Type/Kind chain directly.

`aw.profile.section`/`aw.hardware.set`/`aw.window.template`'s
`window_type_id` field still points at `aw.window.series` (comodel, field
name unchanged from the earlier Type-layer round — don't be misled by the
field name).

**Two known gaps, deliberately left unresolved rather than guessed** (see
the consolidation commit for the full reasoning):
- The 8 real Series seeded in `product_category_data.xml`
  (`window_series_dg_sliding` etc.) have `leaf_type_ids` and
  `product_category_id` left **unset** — no mapping table or category
  mapping was given for them. Set these once that's confirmed.
- The old 5 roles (frame/sash/interlock/bead/mesh) don't map 1:1 onto the
  12 seeded positions — `sash` and `interlock` have no equivalent at all
  among them. Because of this, the old `post_init_hook`/`hooks.py` that
  auto-seeded a "Box Series - Standard" Profile Section (frame/sash/
  interlock/bead/mesh → 5 specific Chawla products) was **removed
  entirely** rather than rewritten with a guessed position mapping. There
  is currently no post_init_hook and no auto-seeded Profile Section in
  this module — rebuild that manually once the sash/interlock → position
  question is settled (either map them onto existing positions or add new
  position rows for them). (What `post_init_hook` did by hand for those 5
  cases is now handled generally, for any of the 491 imported profiles —
  see `aw.profile.section.line` below.)
- `aw_fenestration_design`'s `aw.design.bom.line` still has its own
  separate `ROLE_SELECTION`/`role` field (frame/sash/interlock/bead/mesh)
  — not touched by this consolidation since it wasn't in scope and is
  currently dormant (explosion-engine output, nothing generates it yet).
  Same structural mismatch will need the same treatment once the
  explosion engine actually gets built.

Seeded via `data/dynamic_seed_data.xml` (Leaf Type + Profile Position, no
cross-references, safe to load early), then `data/product_category_data.xml`
(product category tree + the 8 Window Series) and
`data/chawla_attributes_data.xml` + `data/chawla_profiles_data.xml` (the
Chawla pricelist import — regenerate both from the melt CSV with
`scripts/rebuild_melt_and_import.py`, never hand-edit them).

**`aw.profile.section.line` resolves its own `product.product` variant
on demand.** Thickness/Finish are Dynamic-creation attributes on all 491
imported profile templates, so no variant exists for any of them until a
specific combination is requested — a general problem, not something
specific to any one profile. The line now has `product_tmpl_id` +
`thickness_id`/`finish_id` (domained to that template's own attribute
line values via computed `thickness_attribute_value_ids`/
`finish_attribute_value_ids` — a domain string can't call `.filtered()`
client-side, so those have to be real computed sibling fields, not an
inline expression) and a stored computed `product_id` that calls
`product.template._create_product_variant(combination)` — Odoo's own
get-or-create API, verified against `odoo-src`'s
`product_template.py` before use (`combination` must be a recordset of
`product.template.attribute.value`, the template-scoped wrapper around
`product.attribute.value` — not the same model, mapped via
`attribute_line_ids.product_template_value_ids.filtered(lambda v:
v.product_attribute_value_id == wanted)`). Changing `product_tmpl_id`
after `thickness_id`/`finish_id` are already set clears both via
`@api.onchange` — the domain only restricts new picks, it doesn't
retroactively invalidate an already-set value from the old template.

This module has been uninstall/reinstalled rather than live-migrated
multiple times now (Kind field-type change, the Type-layer insertion, and
now dropping Type/Kind again in favor of Leaf Type/Profile Position) — deliberate
each time, given this is still test data with nothing real built on top of it
yet.

**Load-order forward-references have broken a real install three separate
times in this repo** (twice in `aw_fenestration_core`, once in
`aw_fenestration_design`) — always the same root cause: `%(xmlid)d` inside a
`type="xml"` field, `ref="..."` on a scalar field, and **`parent="..."`/
`action="..."` on a `<menuitem>`** all resolve *eagerly* at XML-parse time
(`odoo/tools/convert.py`'s `_tag_record`/`_eval_xml`/`_tag_menuitem`, all
calling `self.id_get()`), not lazily at render time — despite
`ir_ui_view.py`'s `resolve_external_ids` existing as a *separate*, later,
dev-mode-only mechanism that made it look like this should be lazy. The
target external ID must already exist in `ir.model.data` at that exact
point in the manifest's `data` list. **`scripts/check_load_order.py`**
checks this automatically for every module (walks each manifest's `data`
list in order, flags any `ref=`/`%()d`/`parent=`/`action=` referencing an
undefined same-module id) — run it after touching any XML in this repo,
same habit as the comment checker. One concrete consequence: every menu in
this module is centralized in `views/menu_views.xml` (loaded last) rather
than inlined in each feature's own view file, specifically to sidestep this
class of bug.

## aw_fenestration_design

Data model only, deliberately — `aw.design.action_explode()` is a stub that
raises `NotImplementedError`. The explosion engine, manufacturability
checks, the coupler action, and the visual canvas are separate follow-on
work, not in this module. `aw.design` (top-level, chatter, `active`) →
`aw.design.row` → `aw.design.leaf` (both plain child models, no chatter,
matching the `.line`-model convention) → `aw.design.bom.line` (explosion
output, never hand-entered — still has its own dormant `role` Selection,
see the core module's gaps list above).

`aw.design.leaf.leaf_type_id` is a Many2one to `aw_fenestration_core`'s
`aw.leaf.type` (dynamic, not a hardcoded Selection, since the consolidation
round). The row form's nested leaf list pulls in `leaf_has_hinge_side`/
`leaf_has_slide_dir` as hidden (`column_invisible="1"`) related passthrough
fields specifically so the direction columns' own `column_invisible` can
reference them as plain sibling fields — no hardcoded leaf-type string list
in the view, and no `parent.` prefix (that was the original, real bug here;
see below).

`aw.design.window_series_id`/`template_id` point at `aw.window.series`/
`aw.window.template`; `finish_id`/`thickness_id` are `product.attribute.value`
records domained by `ref()` to `aw_fenestration_core.aw_attribute_finish`/
`aw_attribute_thickness` (not name-string matching — a renamed attribute
would silently break that instead of erroring).

`aw.design.width_mm`/`height_mm` are no longer directly editable — they're
`store=True` computes from `width_ft`+`width_in` / `height_ft`+`height_in`
(feet/inches, since that's how site measurements are actually taken; 1 ft =
304.8mm, 1 in = 25.4mm), kept as real stored fields so `area_sqm`/`area_sqft`'s
existing `@api.depends('width_mm', 'height_mm')` needed no changes. No
`default=` on the new ft/in fields, so upgrading an existing installed copy
of this module resets any existing design's width/height to 0 rather than
migrating it — there's no way to infer a sensible ft/in split from an old
mm value. Fine for test data; re-enter by hand after upgrading.

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

## Static checks

Two scripts, both wired into `.githooks/pre-commit` (git only runs hooks
from `.git/hooks` by default, which isn't tracked — enable once per clone):

- `scripts/check_xml_comments.py` rejects `--` inside `<!-- -->` comments —
  illegal XML, breaks well-formedness. Has broken a deploy from this repo
  twice, and been caught pre-commit at least three more times since
  (usually in a comment written to explain some *other* fix — worth
  double-checking any comment you add while fixing something else, not
  just autogenerated data files).
- `scripts/check_load_order.py` catches the eager-`ref=`/`%()d`/`parent=`
  forward-reference bug described above.

Enable the hook once per clone:

```
git config core.hooksPath .githooks
```

Until that's run, check manually before committing XML: `python
scripts/check_xml_comments.py && python scripts/check_load_order.py`.
