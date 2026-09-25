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
  frame (17 seeded rows: Outer Frame/Palay/Palay Bead/Fixed Bead ×
  Top/Bottom/Sides, Mesh - All Sides, Divider Vertical/Horizontal,
  Interlock, Meeting Stile). Replaces the old fixed
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
- ~~`leaf_type_ids`~~ is now mapped — see the seeding note below.
  `product_category_id` on the 8 Series is still **unset**: no category
  mapping was given for them. Set that once it's confirmed.
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

**Seed data that must not fight the UI.** The 8 Series' starting
`leaf_type_ids` come from `DEFAULT_LEAF_TYPES` in
`models/window_series.py`, applied by `_seed_default_leaf_types()` via a
`<function>` in `data/window_series_data.xml`. That method **fills only
a Series that has none** — deliberately, and this is the pattern to
copy for any other editable seeded field. The first attempt was a plain
record-based data file asserting the full mapping, which re-applied on
every upgrade and would have silently reverted UI edits, defeating the
point of leaf types being data-driven. Note the block is updatable, not
`noupdate="1"`: `convert.py`'s `_tag_function` skips a function inside a
noupdate block unless the module is being *installed*
(`self.noupdate and self.mode != 'init'`), so a Series added to the
mapping later would never reach existing databases. Running on every
upgrade is harmless given the guard. Consequence worth knowing:
clearing a Series' leaf types to none is not a stable state, since
"empty" is the signal for "never configured" — archive the Series
instead.

**Seeding an open-ended, user-editable table must match on NAME, not
just xmlid.** `Palay Bead - Top/Bottom/Sides` were first declared as
plain `<record>`s in `dynamic_seed_data.xml`. The client had already
created positions with those exact names by hand, and an xmlid cannot
see a user-made record — so the upgrade made a second set of three, one
carrying the seeded rules and one carrying what the Profile Sections
actually pointed at. `_seed_palay_bead_positions()` replaces them:
it looks the position up by name (`=ilike`, so case differences do not
make a third one), adopts it or creates one, and writes the seed xmlid
onto it via `ir.model.data`. Where duplicates already exist it
reconciles them — **the record the section lines point at wins**, since
re-pointing a live line is the only step that could change a BOM, and
the loser's lines are moved before it is unlinked. Removing the
`<record>` tags is safe precisely because that block is `noupdate="1"`:
`_process_end` only clears rows with `COALESCE(noupdate, false) != true`
(verified in `odoo-src`'s `ir_model.py`), so the existing ir.model.data
rows survive having their `<record>` deleted.

**A Boolean cannot use that guard**, and `aw.profile.position.is_required`
is the case in point: False is both "someone unticked this" and "never
configured", so there is no empty state to test, and re-asserting the
list every upgrade would silently revert a UI edit — the exact trap the
leaf-type seed was rewritten to avoid. `_seed_required_flags()` instead
marks itself done with an `ir.config_parameter`
(`aw_fenestration.position_required_seeded`), which is the honest way to
get one-shot semantics for a Boolean. It names only the exceptions,
because the field defaults to True: a position added later is required
until someone says otherwise, the safe direction when the failure being
prevented is a structural profile silently missing from a cut list.

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
checks and the visual canvas are separate follow-on
work, not in this module. `aw.design` (top-level, chatter, `active`) →
`aw.design.row` → `aw.design.leaf` (both plain child models, no chatter,
matching the `.line`-model convention) → `aw.design.bom.line` (explosion
output, never hand-entered — still has its own dormant `role` Selection,
see the core module's gaps list above).

`aw.design.leaf.leaf_type_id` is a Many2one to `aw_fenestration_core`'s
`aw.leaf.type` (dynamic, not a hardcoded Selection, since the consolidation
round). The row form's nested leaf list pulls in `leaf_has_hinge_side`/
`leaf_has_slide_dir` as hidden (`column_invisible="1"`) related passthrough
fields specifically so the direction columns can reference them as plain
sibling fields — no hardcoded leaf-type string list in the view. Those
direction columns use **`invisible=`, not `column_invisible=`**: which
of them apply depends on each leaf's own `leaf_type_id`, so it's a
per-row decision. See the `column_invisible` lesson below.

`aw.design.window_series_id`/`template_id` point at `aw.window.series`/
`aw.window.template`; `finish_id`/`thickness_id` are `product.attribute.value`
records domained by `ref()` to `aw_fenestration_core.aw_attribute_finish`/
`aw_attribute_thickness` (not name-string matching — a renamed attribute
would silently break that instead of erroring).

**Configurable length unit, mm always the stored source of truth.**
`res.config.settings.aw_length_uom` (added by `aw_fenestration_core`,
Settings → Fenestration → Configuration → Settings) picks one of
`ftin`/`in`/`mm`, stored via `config_parameter='aw_fenestration.length_uom'`
— **deliberately not a field on `res.company`**, see the near-outage note
below. On `aw.design` (width+height), `aw.design.row` (height),
`aw.design.leaf` (width): `*_mm` is the real stored field;
`*_ft`+`*_in` and `*_inch_total` are compute+inverse pairs reading from
and writing back to it (1 ft = 304.8mm, 1 in = 25.4mm) — editing in any
unit recomputes the other two, since all three `@api.depends('*_mm')`.

**`*_mm` is deliberately NOT `required=True`** (it was, and that was a
bug). A required stored field can't coexist with entry through a
non-stored inverse: the NOT NULL constraint fires at INSERT, before the
inverse that would populate `*_mm` ever runs, so typing into the ft/in
pair on a *new* row/leaf/design fails with "Missing required value for
the field 'Width (mm)'". Add Position hits the same thing from the
other direction, creating the design before any dimension is known by
design. Zero means "not filled in yet", and the constraint lives where
it actually matters instead: `aw.design._check_dimensions_set()` is
called by `action_explode()` (no cut list from a zero-sized opening)
and, via `_incomplete_dimension_designs()`, by
`sale.order._confirmation_error_message()` — core's own
pre-confirmation hook, which `action_confirm` loops over and raises,
so this rides along with core's checks rather than wrapping
`action_confirm`.
Each model has a non-stored `length_uom` field: `aw.design`'s reads
`ir.config_parameter` directly (`@api.depends()` with no args — a real,
used-in-core pattern for a compute that depends on context rather than
other fields, confirmed in `odoo/addons/base/models/ir_model.py`);
`aw.design.row`/`aw.design.leaf` chain through their parent
(`design_id.length_uom` / `row_id.length_uom` — `related=` works fine
against a non-stored target, no need to duplicate the parameter read in
three places). Drives `invisible=`/`column_invisible=` so only the pair
matching the setting is shown for editing; `*_mm` itself stays **always
visible**, `readonly="length_uom != 'mm'"` rather than conditionally
hidden — editable only when that's the active setting, a read-only
reference otherwise. No `default=` on the ft/in/inch_total fields — there's
nothing to default, they're always derived from `*_mm`.

**Near-outage, worth internalizing:** the first version of this feature
put `aw_length_uom` directly on `res.company` (`related=` from there on
each model) and took the whole site down — every page 500'd, including
`/odoo` after login. Root cause, verified against `odoo-src` before
either building or fixing this: a plain container boot/restart **never**
runs the schema DDL that adds a new column — `Registry.new()`/
`load_modules()` both default `update_module=False`, and `init_models()`
(the actual `ALTER TABLE`) only runs when that's `True`, i.e. only for
`-i`/`-u` or clicking Install/Upgrade in the UI. The boot log's `Missing
not-null constraint on res.company.aw_length_uom` warning looked like
confirmation the column existed (that's what it means in every *other*
case in this history) but doesn't: `registry.check_null_constraints()`
only checks whether an *existing* column has the `NOT NULL` constraint
set — a genuinely **missing** column produces the exact same warning
text, no way to tell them apart from the log alone. `res.company` is
read with a full-column prefetch on essentially every request, so the
very first real page load after deploy (before anyone had clicked
Upgrade) hit `UndefinedColumn` and aborted its DB transaction, cascading
500s to everything downstream in that request. **Lesson: never add a
required (or otherwise request-path-critical) stored field to a core
model that's read on every request without either an immediate Upgrade
right after deploy, or — better, as used here — not touching that
model's schema at all.** `ir.config_parameter` via `config_parameter=`
on a `res.config.settings` field needs no schema change whatsoever, so
this whole failure class doesn't apply to it.

**Sale Order link (Step 1 of the quoting flow).** Every design prices
onto one `sale.order.line` whose product is a single generic seeded
product, `product_fenestration_position` ("Fenestration Position",
`consu`, not storable, list price 0, `noupdate="1"`) — the line's
*description* carries the real content (`"D1 — Drawing room — 8 ft 6 in
× 6 ft 0 in — Double Glaze Sliding"`, size rendered in the configured
length unit via `aw.design._format_length()`), not the product. The
Sale Order form gets a "Fenestration" notebook page listing
`aw_design_ids` plus an "Add Position" button (draft/sent only); the
order line list gets a row button back to its design.

**Add Position always has to settle the Window Series up front**, since
`aw.design.window_series_id` is required and the button opens the new
design's form immediately — the record must be creatable before the
user ever sees it. So: `sale.order.aw_default_series_id` (shown at the
top of the Fenestration tab) is used when set; when it isn't, the
button opens `aw.design.position.wizard`, which asks for the Series
(required) plus optional ref/location and offers "use as default for
this quote" (defaulting to checked, so it asks once per quote rather
than once per position). Both paths funnel into
`sale.order._create_fenestration_position()`. A design's own Series
stays freely editable afterwards. The wizard's form view is referenced
by `env.ref()` from Python at runtime, *not* by XML `ref=`, so it
carries none of the parse-time load-order constraints described above.

**The design → line sync lives in `create()`/`write()`, not an
onchange** — deliberately, and confirmed against core: a design is
edited on its own form, never embedded in the Sale Order form, so
there's no in-memory parent record an onchange could write back into.
`repair.repair.write()` → `_update_sale_order_line_price()` is the same
shape in core. Sync sets the description and `product_uom_qty`, and
sets `price_unit` **only** when `manual_rate` is set (otherwise Odoo's
own pricelist value is left alone — real pricing is Step 3).
`aw.design.unlink()` removes its line; the reverse needs no code, since
`sale_order_line_id` is `ondelete='cascade'`.

**Visual configurator** (`static/src/design_configurator/`, OWL client
action `aw_design_configurator`). Reads and writes the existing
design/row/leaf records — no new geometry model. Two server methods
carry it: `get_configurator_data()` (header, geometry, unit, the
Series' leaf types, allowed presets — one round trip) and
`save_layout(payload)` (replaces the whole grid plus header in a single
transaction, so a layout can't land half-rebuilt). `save_layout`
filters the header against an explicit allow-list — it's a public RPC,
and passing the dict to `write()` as-is would let a crafted call set
`sale_order_line_id` and re-point a design at another quote's line.

The SVG is a port of `docs/prototype/fenestration-quote-demo.html`'s
`draw()`/`leafGlyph()`/`drawDim()` (kept in-repo as the reference
spec), with one structural change: the prototype builds SVG nodes
imperatively via `createElementNS`, whereas the OWL version computes a
plain `scene` object and renders it declaratively, so it re-renders
reactively instead of being torn down and rebuilt. `frameFace` is a
drawing-only constant here — the prototype reads it from its `SERIES`
table, which is master data we don't port, and `aw.window.series` has
no equivalent field. **The scene returns `null` when width or height is
0**: designs legitimately start at 0×0 (see the `required=` note
above), and the prototype's scale factor would be `Infinity` there,
putting `NaN` into every coordinate.

**Which presets a Series is offered** is two conditions, both required:
`series_ids` (empty = any Series) states intent, and leaf-type
compatibility is the backstop so a Fix-only Series can't one-click its
way to a casement. Leaf types alone were not enough — every all-`FIXED`
preset passed on all 8 Series, so a curtain-wall layout showed up on
sliding Series. `series_ids` is seeded once per preset by
`_seed_default_series()`, the same fill-only-if-empty pattern as
`_seed_default_leaf_types()`, with the same caveat: clearing it back to
"any Series" isn't stable, archive instead. Note the two conditions can
contradict — a preset assigned to a Series whose leaf types it needs but
doesn't have is silently offered nowhere (see the `Hopper over Fixed`
note in the seeding commit).

`aw.layout.preset` seeds from the prototype's `ROWS`/`PRESET_CATS`/
`PRESETS`. All weights are 1 because the prototype's templates carry no
sizes at all — `normaliseRows()` splits equally — and equal weights
reproduce that while leaving unequal presets expressible. Its `kinds`
filtering is deliberately not ported: that keyed off the prototype's
series-kind concept, and presets are now filtered by whether the
design's Series can host every leaf type they need.

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
- `scripts/check_owl_names.py` rejects OWL template variables named
  `lt`/`gt`/`lte`/`gte`/`and`/`or` (owl.js's `WORD_REPLACEMENT` rewrites
  them into `<`/`>`/`<=`/`>=`/`&&`/`||` *before* parsing, so
  `t-as="lt"` compiles to `const key1 = <.id;`) or after one of its
  `RESERVED_WORDS` (`window`, `new`, `Math`, ...). Has already broken
  the configurator once. Nothing else catches it: the file is
  well-formed XML, it loads server-side without complaint, and it only
  fails in the browser when the component is first opened — which is
  exactly why it's worth a script rather than vigilance. Only scans
  `static/src` (server-side QWeb is a different compiler and is
  unaffected), and ignores names inside comments.

- `scripts/check_owl_getters.mjs` loads each OWL component's real class
  (stripping only the unresolvable imports and the registry call),
  builds it against a mocked state and reads every getter once. Catches
  **getter cycles**, which crash the component on open with `RangeError:
  Maximum call stack size exceeded` and are invisible to every other
  check — valid XML, valid JS, `node --check` clean. One shipped:
  `scene → unitsPerPixel → fitScale → scene`, from sizing the panel
  badges inside `scene`. Note *why* it runs the real class: the offline
  arithmetic tests that missed it were standalone reimplementations, so
  they exercised the maths but never the getters, and a cycle only
  exists between real getters. **The getters are enumerated off the
  class prototype, not listed by hand** — the list used to be manual,
  and had silently fallen twenty getters behind (26 of 46 checked), so a
  cycle in any of the other twenty would have shipped exactly the way
  the original one did. A second phase checks every method the
  template names actually exists on the component, and fires each
  bare-name `t-on-*` handler with a fake event. Worth knowing its limit:
  it does **not** catch a global called inside an inline arrow
  expression, because that expression is never compiled — the static
  rule in `check_owl_names.py` is what covers that.

**The configurator's drawing is deliberately two layers, and the order
is load-bearing**: `scene` is pure drawing units (frame, panels, divider
positions, dimension lines, viewBox — including its margins) and must
never read `unitsPerPixel`/`fitScale`/`zoom`/canvas size; `adornments`
holds everything sized in screen pixels (badge radius and font, divider
stroke and hit width) and is derived from `scene` afterwards. `fitScale`
reads `scene.vbW/vbH`, so anything `scene` reads back from it is a cycle.

  It also rejects **template expressions calling JS globals**
  (`parseInt`, `parseFloat`, `Number`, `String`, `Boolean`, `isNaN`,
  `JSON`, …). owl.js compiles every symbol outside its `RESERVED_WORDS`
  list into a lookup on the component context, so `parseInt(x)` becomes
  `ctx['parseInt'](x)` — undefined — and the handler dies with
  `TypeError: vNN is not a function` **only when the control is used**.
  Note `Math`, `Array`, `Object`, `Date`, `console` and `window` ARE
  reserved and work fine; flagging those would be a false positive.
  Do the conversion in a component method and let the template call
  only methods.

- `scripts/check_preset_layouts.py` runs every seeded `layout_json`
  through the **same validator the upgrade uses** — imported out of
  `models/layout_rules.py`, which is kept free of Odoo imports for
  exactly that reason — plus a self-test of the rules themselves. One
  upgrade has already died on this: `OPN-VNT` was the first seeded
  preset with a nested container, and the validation assumed every leaf
  carried a leaf type, so the install failed with `ParseError ... uses
  unknown leaf type code None`. **Every other check in this repo runs
  against the OWL component, i.e. client-side**, and the client already
  skipped containers — so nothing was watching the server-side data
  rule. When a rule exists on both sides, check the server one too.

- `scripts/check_act_window_views.py` requires every
  `ir.actions.act_window` dict — Python or JS — to declare `views`. The
  web client's `_preprocessAction` runs `action.views.map(...)`
  unguarded, so one without it dies with *"Cannot read properties of
  undefined (reading 'map')"* before the dialog opens. **The subtlety
  that makes this easy to miss:** an action returned from a *button*
  goes through `/web/dataset/call_button`, whose controller runs
  `clean_action()` → `generate_views()` and fills `views` in from
  `view_mode` — so the identical dict works from a button and crashes
  when the configurator fetches it with `orm.call()`, which goes
  through `call_kw` and does no such cleaning. That is exactly why
  "Save as preset" crashed while "Add Position" worked. Declare `views`
  and it is safe on both paths.

**Finish is a Color attribute, and where that actually shows.**
Verified in odoo-src before choosing it: `product.attribute.display_type`
offers `('color', 'Color')`; the **sale order product configurator**
renders it as real swatches (`sale.ptav_color` sets
`background-color: ptav.html_color`, marks the chosen one `active`, and
uses a `transparent` class when the colour is empty); the **backend**
shows `html_color` only as an editable `widget="color"` field on the
attribute's values — on the product form the values appear as tags
coloured by the separate INTEGER `color` index. That is why
`_seed_finish_colours()` sets both. The integer is a coarse 12-entry
palette (No color, Red, Orange, Yellow, Cyan, Purple, Almond, Teal,
Blue, Raspberry, Green, Violet — `web/.../colorlist/colorlist.js`), so
it is a nearest match and nothing more; `html_color` is the accurate
one. Seeded once, guarded by a parameter, because re-imposing the
display type every upgrade would silently undo a deliberate switch back
to a dropdown.

**`standard_price` is only ours under Standard Price costing.** Under
AVCO it IS the running average stock valuation maintains, and
`stock_account`'s `_change_standard_price()` turns a write into an
inventory revaluation -- so importing a price list would move the stock
ledger. Under FIFO it is a leftover valuation ignores. The sync
therefore writes only when the costing method is `standard`, reports
what it refused, and the stat button swaps to a disabled "Cost owned by
stock valuation" one. **`cost_method` is defined by `stock_account`,
which this module does NOT depend on**, so it is read through
`product.template._aw_cost_method()`, which checks `_fields` first and
answers `'standard'` when the field is absent -- no valuation module
means nothing to corrupt. Naming it in an `@api.depends` would break
the registry at load on a database without stock_account.

**Costs come from rates, never the other way round.**
`product.product.aw_rate_per_ft` / `aw_rate_date` are computed and NOT
stored: the rate in force changes with the date and with every import,
so a stored copy would be wrong the next morning. `standard_price` is
the stored one and is only written deliberately — by the price-list
import, by "Update costs from rates", or when
`aw.profile.section.line._variant_for()` first brings a variant into
existence. **A variant with no rate is left alone, never zeroed**: a
hand-entered cost is worth more than a zero this module is confident
about. Stock UoM is the metre, so cost = rate/ft x 3.280839895.

- `scripts/check_catalogue_import.py` dry-runs the catalogue import
  against the real zip without a database: every `existing_products.csv`
  row matches a product by exact name, no `new_products.csv` name
  collides, every referenced image is present, pages are numeric, and
  the thickness plausibility rule rejects exactly the three known-bad
  values. It uses the SAME `models/thickness.py` the wizard does, so it
  cannot drift from the real behaviour. The zip is vendor data and is
  gitignored, so this skips cleanly when absent.

  **`norm_thickness` lives in `aw_fenestration_core/models/thickness.py`
  and nowhere else.** `scripts/rebuild_melt_and_import.py` imports it
  from there (same pattern as `layout_rules.py` / `formula.py`) — it
  used to own the only copy, and the catalogue import needing the same
  rule is exactly how two copies start disagreeing and mis-keying
  attribute values against each other. The module also owns
  `THICKNESS_MAX_MM = 25`: two catalogue rows carry a length or a
  section dimension in the thickness column (`2300MM`, and `130MM; 50MM`
  on a row whose dimensions column is empty), and creating those as
  Thickness attribute values would put them in every thickness dropdown
  permanently. They are refused and reported instead.

  **WebP is stored verbatim.** Verified in `odoo-src/odoo/tools/image.py`:
  `ImageProcess.__init__` sets `self.image = False` for WebP after
  checking only its resolution, and `image_quality()` opens with
  `if not self.image: return self.source`. So `image_1920` keeps the
  bytes and no conversion is needed. The consequence is that
  `image_128` and friends are the same bytes rather than real
  thumbnails — harmless at ~4 KB each. **wkhtmltopdf cannot render
  WebP**, so if a product picture ever needs to appear on a PDF report,
  convert on import at that point.

- `scripts/check_rate_chain.py` exercises `resolve_chain()` from
  `aw_fenestration_core/models/profile_rate.py` — the function that
  decides when each version of a profile rate stops applying. Getting
  it wrong is expensive and silent: a rate closing a day late overlaps
  its successor and the lookup takes whichever sorts first; a day early
  leaves a gap where a quote has no price at all. Neither raises
  anything. `resolve_chain` is therefore kept free of Odoo imports (the
  same reason as `formula.py` and `layout_rules.py`) so the check runs
  the REAL function. Covers back-dated inserts, manual end dates either
  side of the successor, duplicate start dates, and chain continuity.
  **`date_to` is a plain stored field written explicitly, not an
  `@api.depends` compute** — it depends on a SIBLING record (the next
  version), and `@api.depends` cannot say "recompute my neighbour when
  I change"; Odoo would recompute the row that changed and never the
  one before it. `create`/`write`/`unlink` rebuild the affected chains
  whole, `write` collecting keys on BOTH sides because changing
  thickness/finish/vendor/date_from moves a rate between chains.
  **An upgrade does NOT rebuild existing chains**, which is easy to
  assume it would: `_init_column` writes the default and stops, and
  Odoo only schedules a recompute for a field that is both `compute`
  and `required` (`fields.py`'s `add_not_null`) — `date_to` is
  neither. `_backfill_date_to()` is the one-shot pass for rows imported
  before the field existed, guarded by
  `aw_fenestration.rate_date_to_backfilled`; that guard is about cost,
  not correctness, since the pass is idempotent. Writes are grouped by
  the VALUE being written rather than one per record — a second import
  of the Chawla list closes ~3473 rates at once and they nearly all
  share a date_to.

- `scripts/check_cut_plan.py` exercises the bar-nesting optimiser
  (`cut_algorithm.py`, kept Odoo-free for that purpose). **The LP/MIP
  needs `pulp==2.9.0`** — pinned in `odoo/Dockerfile`, because pulp 4.x
  is a rewrite with a different API and *no bundled solver*, so an
  unpinned install silently degrades the optimiser to its greedy
  fallback. The check prints which path it took, so a machine without
  pulp still passes but says so. Cases are ones whose true optimum can
  be shown by hand, including one where FFD needs three bars and the
  exact method proves two.

  **`AW_SKIP_SLOW_CHECKS=1` skips the 169 M1 case** for a quick local
  commit; it says so loudly, and the full suite still has to run before
  a deploy.

  **Plan generation is guarded three ways**, because the same solve that
  takes 9s here takes 28s across all four scenarios of a group: a
  per-group `piece_fingerprint` so a regeneration re-solves only what
  moved; a per-group time budget
  (`aw_fenestration.solve_budget_s`, default 20s) after which the best
  plan found is kept and reported as "within N ft" rather than proven;
  and the solve runs ONLY from Generate/Regenerate, never on design
  save. Opening a stale plan shows its banner and waits. The mixed
  scenario is solved FIRST so it gets the budget — it is almost always
  the chosen one, and the single-length options are alternatives.

  **Column generation is seeded with the greedy packing's patterns**,
  which is what makes the budget safe: the integer solve always has
  that answer to fall back on, so running out of time decides "proven"
  versus "within N ft" and never a nonsense total. Without the seeding,
  a 2 s budget on the DG-26 job returned 952/912/936/638 ft against
  greedy's 630/624/630/630 — every option worse than simply packing
  first-fit. `check_cut_plan.py` asserts each option's total is at most
  its own greedy total, at short budgets, and runs that assertion
  ALWAYS (the skip flag does not cover it). **Selecting an option
  re-solves that one option with the whole budget**, since it is the
  plan the shop will cut from.

- `scripts/check_owl_getters.mjs` stubs `window`, `document` and
  `getComputedStyle`. These are real browser globals the component
  legitimately uses (`window` is in OWL's RESERVED_WORDS); without the
  stubs the harness reports "window is not defined" for correct code,
  which is a fault in the harness rather than the component.

- `scripts/check_view_buttons.py` requires every
  `<button type="object" name="X">` in our views to name a method the
  model really has. **The obvious version of this check would miss the
  bug it was written for.** A stat button was added to
  product.template's form inside `//div[@name='button_box']`; the
  method exists on product.template, so "does the declaring view's
  model have it?" says yes — but `product.product_normal_form_view` is
  `mode="primary"` on **product.product** and inherits the
  product.template form, so the button propagated into the variant form
  and the Upgrade died with *"... is not a valid action on
  product.product"*. The rule is therefore: the method must exist on
  the declaring view's model **and on the model of every view that
  transitively inherits the view being patched**.

  It also follows `field[@name='x']` hops inside an `xpath` expr —
  without that it reports a false positive on every button inserted
  into an embedded list, because a button under
  `//field[@name='order_line']/list/...` belongs to sale.order.line,
  not sale.order. Python scanning is limited to `models/`, `wizard/`
  and `report/` of the dependency closure, which took it from 42 s to
  4.5 s. Needs `../odoo-src`; skips cleanly without it.

- `scripts/check_kanban_fields.py` rejects `t-if`/`t-elif`/`t-else`/
  `t-foreach`/`t-as`/`t-call` placed directly on a `<field>` inside a
  **kanban** arch. A kanban `<field>` is not markup: the web client
  turns it into a Field **component** and passes every attribute
  through as `attrs`, so `t-else=""` compiles to
  `attrs: {'t-else':, ...}` and the template dies with OwlError
  *"Unexpected token ','"* the moment anyone opens the view. Wrap the
  field instead — `<t t-else=""><field .../></t>`. Nothing else caught
  it: the XML is well-formed, load order is fine, and
  `check_view_schemas.py` can't help because **Odoo ships no RelaxNG
  for kanban** (it's validated by Python in core, which doesn't look at
  this). `t-att`/`t-attf` are deliberately allowed — they set an
  attribute value rather than controlling whether the element renders.

- `scripts/check_view_schemas.py` validates every standalone view arch
  against **Odoo's own RelaxNG schemas** (`../odoo-src/odoo/addons/base/
  rng/*.rng`), which is the same validation the Upgrade runs. It exists
  because that failure is near-undiagnosable from the server alone:
  the log gave the file, the line, `Invalid view ... definition` and
  literally `View error context: '-no context-'`, with no hint what was
  wrong. Running the schema locally printed the real cause in a second
  — `Invalid attribute expand for element group`. **`expand=` and
  `string=` are both gone from `<group>` in a v19 search view**
  (`common.rng` allows only colspan/rowspan/fill/height/width/name/
  color/invisible); both were valid in older Odoo, which is exactly how
  they get carried over. Core v19 search views use a bare `<group>`.
  Only the view types Odoo ships an RNG for are checked — form and
  kanban are validated by Python in core, not by a schema. Inherited
  views are skipped, since a fragment of xpath edits is not a whole
  arch and the schema rightly rejects it. Needs `lxml` and the
  `../odoo-src` clone; skips cleanly (exit 0) without either.

- `scripts/check_configurator_header.py` requires every field in
  `CONFIGURATOR_HEADER_FIELDS` (what `save_layout` may write) to appear
  in `get_configurator_data()`'s `header` (what the client is given).
  A field that is writable but not loaded is **destroyed by every
  save**: the client round-trips the header wholesale, so it sends back
  nothing for a key it never received, and `save_layout` writes the
  nothing. `manual_rate` was in exactly that state — a hand-entered
  price override wiped on every configurator save, silently, with no
  error and no control on screen to notice. One-directional on purpose:
  loaded-but-not-writable is fine (`window_series_name` is display
  only). The matching runtime test is
  `aw_fenestration_design/tests/test_configurator_roundtrip.py`, which
  loads a design, saves the payload back untouched and asserts the
  header did not move — it needs a database, so it runs under
  `odoo -u aw_fenestration_design --test-enable`, not in the hook.
  **`save_layout` also distinguishes absent/None ("not sent, leave it")
  from `False` ("clear it")** for `CONFIGURATOR_PROTECTED_HEADER`, since
  a hidden control sends nothing and that must not read as a clear.

- `scripts/check_configurator_payload.py` compares the keys
  `get_configurator_data()` returns (following `**self._method()`
  spreads) against every `state.data.<key>` the configurator reads. The
  mismatch it exists for: `_attachment_catalogue()` was spread into
  `get_series_context` but not into the loader, so mesh, infill, glass
  and grid were all undefined on open — headings with nothing under
  them, and "no Glass Specs exist yet" when seven existed. No OWL check
  can see it, because `this.state.data.mesh_types || []` is valid
  JavaScript that quietly yields an empty list; the mismatch only exists
  ACROSS the two files.

Enable the hook once per clone:

```
git config core.hooksPath .githooks
```

Until that's run, check manually before committing XML or JS: `python
scripts/check_xml_comments.py && python scripts/check_owl_names.py &&
node scripts/check_owl_getters.mjs && python
scripts/check_preset_layouts.py && python
scripts/check_act_window_views.py && python scripts/check_load_order.py`.

## Hard-won lessons

- The boot warning "Missing not-null constraint on X.y" does NOT prove
  column y exists — it fires for missing columns too.
- A normal deploy does not create columns for new fields; only
  Upgrade/-u does. Never add a stored field to a core model read on
  every request (res.company, res.users) — a single request before
  Upgrade takes the whole site down. Use ir.config_parameter for
  settings.
- A plain deploy also doesn't load XML (views, menus, data) — always
  Upgrade after deploying view changes.
- `column_invisible` in a list is evaluated **once for the whole list,
  against the parent record/context — never per row**. It therefore
  cannot reference the row's own fields: doing so raises OwlError
  "Name 'x' is not defined". Use `column_invisible="parent.x"` for a
  whole-column decision (requires `x` to be an active field on the
  parent form), and plain `invisible=` for anything that varies per
  row. `invisible=`, `readonly=` and `required=` on a list field *are*
  per-row and can use the row's own fields freely — which is why a list
  can legitimately carry a field used only by a per-row `readonly=`.
  A read-only list with no parent record to read (a top-level list
  view, or an embedded one whose parent lacks the field) can't switch
  columns at all — give it one preformatted column instead, the way
  `aw.design.size_display` handles unit switching.
