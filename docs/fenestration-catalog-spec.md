# Fenestration Design Catalog — Gap Analysis & Implementation Spec

Status: agreed plan, decisions taken without client (Moazzam) input — every
such decision is marked **[revisit]** and is designed to be changeable in data,
not code.

Modules: `aw_fenestration_core` (master data), `aw_fenestration_design`
(designs, configurator, BOM). Odoo 19 Community.

---

## 0. Principles (apply to every phase)

1. **Data, not code.** Every list a user might want to extend (families,
   design types, leaf types, positions, mesh types, infill types, grid
   patterns, formulas) is a table editable in the UI. Seed data is applied
   once ("fill only if empty"), never re-imposed on upgrade.
2. **mm is the stored unit.** Display follows the global length-unit setting.
3. **One geometry, many views.** The design's rows/leaves tree is the single
   source; drawing, BOM, cut list, shop drawing and quote PDF are all derived
   from it.
4. **No stored fields on core models read on every request** (res.company,
   res.users). Settings go in `ir.config_parameter`.
5. **Deploy, then Upgrade.** Every phase ends with the Upgrade + a named
   browser test.

---

## 1. Gap analysis

| Requirement | Exists today | Gap → Phase |
|---|---|---|
| Family → design type | `aw.layout.family`, codes, pictures, library strip | ✅ P2 |
| Parameters W×H, series, glass, finish, thickness | `aw.design` | — |
| Panel type & opening hand | `aw.leaf.type` (7), hinge side, in/out, slide dir | — |
| Arbitrary splits (vent over sash, transom over one panel) | Nested subdivision (`parent_leaf_id`), depth 3, floating toolbar | ✅ P1 |
| Panel identification | `panel_no`, reading order, recursive, drawn as badges | ✅ P1 |
| French casement / double T&T (sashes meet, no mullion) | `junction_after`, validity rules, drawn distinctly | ✅ P1 |
| Opening symbol convention | Standard triangle (apex = hinge) + legend | ✅ P1 |
| Sliding 2–12 panels, tracks, roles | Sliding builder, `track_no`, validation rules | ✅ P2 |
| Twin sash (glass + mesh on same opening) | `mesh_type_id` on the panel, TWN-* presets | ✅ P3 |
| Pleated / roller mesh | `aw.mesh.type`, 7 seeded | ✅ P3 |
| Louvre, fan, AC cutout, solid panel | `aw.infill.type`, drawn per kind | ✅ P3 |
| Georgian bars | `aw.grid.pattern`, rows x cols per panel | ✅ P3 |
| Different glass per panel (e.g. frosted bottom) | `glass_spec_id` on the panel, 7 specs seeded | ✅ P3 |
| Profile BOM formulas, cut angles | Positions + Profile Sections (product only) | Scope/edge on positions, formulas on lines → **P4** |
| Hardware quantities & conditions (hinge count, T&T gear size, gaskets per m) | Hardware Set lines (product, qty, leaf type) | Qty/condition formulas, scope → **P4** |
| Glass / mesh cut sizes | Placeholder in prototype | Deduction formulas per Series → **P4** |
| Explosion engine | Stub | **P4** |
| Manufacturability checks, coupler | Prototype only | **P4** |
| Save layout as preset, remaining entry points | Both done; configurator is the default entry point | ✅ P2 |
| Duplicate position | Quote tab and configurator | ✅ P2 |
| Shop drawing, quote PDF with elevations | Live SVG only | SVG snapshot + reports → **P5** |
| Cut list, bar nesting, offcuts | Prototype algorithm | **P6** |
| Pricing cascade, rate versions | Prototype only | **P6** |
| Length-lot stock, stock-constrained cutting | `aluminum_inventory` (separate) | **P6** |

---

## 2. Decisions taken without client input **[revisit]**

| Question | Decision | Why it's safe |
|---|---|---|
| French casement: mullion or not? | Support both via junction type; French preset defaults to **meeting** | Changeable per junction in the configurator |
| T&T + fixed combos | Seed both TT-FIX-L and TT-FIX-R | Presets are archivable |
| Double pleated opening to the sides | Seed as a mesh type | Archivable |
| Vent sash | Nested split + small hopper/awning panel; seed one preset | Uses existing features |
| Solid infill, AC cutout | Seed as infill types | Archivable |
| Opening symbol | **Triangle apex points to the hinge side, view from inside**; IN/OUT tag for swing; printed as a legend on every drawing | One convention everywhere; legend removes ambiguity |
| Deductions, sash limits | Placeholder values, clearly marked, editable per Series / section line | Real values come from supplier/shop data |
| Track numbering and where mesh sits | **Track 1 is innermost, counting outwards; mesh takes the outermost track** | Only a convention; if a system puts mesh on the inside it becomes a Series setting, not a code change. See 4.2. |

---

## 3. Phase 1 — Geometry completeness  ✅ COMPLETE

### 3.1 Nested subdivision ✅
`aw.design.row.parent_leaf_id`; container leaves; recursive save, drawing,
rescale, presets, thumbnails; depth limit 3; floating toolbar
(split V / split H / remove / in-out / hinge side / slide dir).

### 3.2 Panel numbers ✅
`aw.design.leaf.panel_no`, reading order, recursive; circles in drawing,
selected = filled; mesh panels "M<n>".

### 3.3 Junction type ✅
- `aw.design.leaf.junction_after`: `mullion` | `meeting` | `interlock`
  — the boundary between this leaf and the next leaf in the same row.
  Empty on the last leaf of a row.
- Default when a layout is created or edited:
  - slider next to slider → `interlock`
  - two opening sashes (casement / tilt & turn) with opposite hinge sides,
    meeting each other → `meeting`
  - anything else → `mullion`
- Horizontal boundaries (between rows / sub-rows) are always transoms.
- Configurator: clicking a vertical divider selects it; toolbar shows
  Mullion / Meeting / Interlock. Dragging still resizes.
- Drawing: mullion = solid bar; meeting = two thin lines with no bar;
  interlock = the two sash edges overlapping slightly.
- Presets / `layout_json` carry `junction_after`.
- Seed two new Profile Positions: **Interlock**, **Meeting Stile**
  (used in P4 for BOM).

### 3.4 Opening symbols + legend ✅
- Side-hung / casement: two dashed lines from the handle-side corners
  meeting at the midpoint of the hinge side (apex = hinge).
- Top-hung (awning): apex at top edge midpoint. Bottom-hung (hopper): apex
  at bottom.
- Tilt & turn: both triangles (side hinge + bottom tilt).
- Slider: arrow in slide direction (as now), plus track tag "T1/T2…" once
  P2 exists.
- IN / OUT tag as now.
- Legend under the drawing: "View from inside · triangle points to hinge".

**P1 test:** Casement Single Glaze → select a casement panel → split it
vertically → set the left sub-panel hinge **left** and the right one hinge
**right** → the boundary between them shows as *meeting*, both triangles
point outward to their hinges → change it to *mullion* → save → reopen.

(The original wording tested this via a "French preset". There isn't one
in Phase 1: the prototype's `frenchDoor` seeds as **Casement + Fixed +
Casement** (`OPN-CFC`), whose centre panel is fixed, so both its
boundaries are correctly mullions. `OPN-FRN`, the true L+R pair that
defaults to *meeting*, arrives with the preset codes in **4.6 / Phase 2**.
Splitting a panel exercises the same default rule without it.)

---

## 4. Phase 2 — Catalog structure  ✅ COMPLETE

### 4.1 Families ✅
New `aw.layout.family`: `name`, `code`, `sequence`, `active`,
`kind` = `layout` | `mesh` | `infill`.
- `layout` families: clicking an item replaces the design layout.
- `mesh` / `infill` families: clicking an item applies it to the **selected
  panel** (P3). This mirrors EvA's library, where designs and add-ons live
  in the same panel.

Seed:

| Code | Name | Kind |
|---|---|---|
| OPN | Openable Designs | layout |
| TT | Tilt & Turn Designs | layout |
| TWN | Twin Sash Designs | layout |
| SLD | Sliding Designs | layout |
| CW | Stick Curtain Wall Designs | layout |
| MSH | Add-on Mesh | mesh |
| PLT | Pleated & Pull-down Mesh | mesh |
| ADD | Add-ons | infill |

`aw.layout.preset`: add `code` (unique), `family_id` (replaces the text
`category`; migrate existing values by name, unknown → "Other" layout
family). Library groups by family, sorted by `sequence`.

**As built** — two things the table above doesn't say:
- `OTH` / **Other** / `layout` is seeded as well. The table omits it, but
  the migration rule sends unknown categories there, so it has to exist.
- `category` is **kept on the preset**, not dropped. It is what the
  families were migrated from, and the library falls back to it so a
  database part-way through the migration still groups sensibly. It is
  hidden on the form except in developer mode.

### 4.2 Sliding builder ✅
- `aw.design.leaf.track_no` (Integer, sliders and sliding mesh).
- Configurator button **Sliding builder** (only when the Series allows
  Slider): panels 2–12, tracks 2/3/4, optional mesh track, per panel role
  (Fixed / Sliding) and slide direction. Suggested default pattern per
  count, editable before applying.
- Generates one row: equal widths, `track_no` assigned, junctions per 3.3.
- Validation: adjacent sliding panels must be on different tracks; a fixed
  panel sits on the outer track; mesh track must be the outermost.
- **Save as preset** from the builder result.

**Track convention [revisit]** — the two rules above conflict whenever a
layout has both a fixed panel and a mesh sash, since they can't both own
"the outermost". As built:

| | |
|---|---|
| Track 1 | **innermost**, counting outwards |
| Glass panels | tracks 1..`tracks` |
| Fixed panel | the outermost **glass** track, i.e. `tracks` |
| Mesh sash | `tracks + 1`, outside all of them |

This is a convention, not a constraint of the data: `track_no` is a plain
integer and any numbering fits. If a system puts mesh on the *inside*,
this becomes a per-Series setting rather than a code change.

### 4.3 Save current layout as preset (Stage D) ✅
Configurator action: name, code, family, optional series → writes
`layout_json` (incl. nesting, junctions, tracks). Presets become authored
visually; JSON editor stays for admins.

### 4.4 Remaining entry points (Stage D) ✅
Add Position → configurator directly; quote Fenestration tab rows → open
configurator; raw form kept for admins.

### 4.5 Duplicate position ✅
Action on the quote tab and in the configurator: copies a design with its
full layout to a new position (new sale line, next free position ref).

### 4.6 Seed presets (codes) ✅

| Code | Family | Layout | Series |
|---|---|---|---|
| OPN-FIX | OPN | 1 fixed | Fix series |
| OPN-SHL / OPN-SHR | OPN | 1 casement, hinge L / R | Casement series |
| OPN-TOP | OPN | 1 awning (hinge top, out) | Casement series |
| OPN-BTM | OPN | 1 hopper (hinge bottom, in) | Casement series |
| OPN-FRN | OPN | 2 casements L+R, `meeting` | Casement series |
| OPN-FXC | OPN | fixed + casement | Casement series |
| OPN-VNT | OPN | fixed with top awning vent (nested) | Casement series |
| TT-SGL-L / TT-SGL-R | TT | 1 tilt & turn | Tilt & Turn |
| TT-DBL | TT | 2 T&T, `meeting` | Tilt & Turn |
| TT-FIX-L / TT-FIX-R | TT | T&T + fixed | Tilt & Turn |
| SLD-2P2T | SLD | S S, 2 tracks | Sliding series |
| SLD-2P2T-F | SLD | F S, 2 tracks | Sliding series |
| SLD-3P2T | SLD | S F S, 2 tracks | Sliding series |
| SLD-3P3T | SLD | S S S, 3 tracks | Sliding series |
| SLD-4P2T | SLD | F S S F, 2 tracks | Sliding series |
| SLD-4P4T | SLD | S S S S, 4 tracks | Sliding series |
| SLD-2P2T-M | SLD | S S + mesh track | Sliding series |
| CW-3FX / CW-VNT | CW | 3-tier fixed / curtain wall + vent | Curtain Wall Fix |

Twin sash (TWN-*) presets come in P3, since they need mesh attachments —
"Twin Sash" means glass + mesh on one opening and is reserved for them.
The prototype's `frenchDoor` was seeded under that name by mistake and is
now **Casement + Fixed + Casement** (`OPN-CFC`).

**Three codes exist that this table doesn't list**, because presets
existed before it did and redefining them would have changed what a
saved design refers to:

| Code | Layout | Why |
|---|---|---|
| OPN-CFC | casement + fixed + casement | The renamed `frenchDoor`. Distinct from OPN-FRN, which is the L+R pair with no fixed panel between. |
| OPN-HOF | hopper over fixed | Pre-dates the table. `OPN-BTM` in the table is a *single* hopper, seeded separately, so this one needed its own code rather than taking OPN-BTM's. |
| OPN-2A1B | 2-across / 1 below | Pre-dates the table; the table has no equivalent. |

Seed "fill only if empty", as with leaf types. `aw.layout.preset.code`
already exists (added with the OPN-CFC correction); this table fills in
the rest.

**P2 test:** Double Glaze Sliding → Sliding builder → 4 panels, 2 tracks,
F S S F → apply → tracks and interlocks shown → save as preset → it appears
in the library → Duplicate position → copy is identical.

---

## 4b. For client review

Decisions taken to keep moving, all changeable in data rather than code.
Each needs Moazzam's confirmation. **Keep this list current** — add to it
whenever something is decided without him.

| # | Item | What was decided | If he disagrees |
|---|---|---|---|
| 1 | Library family strip | Tiles at the top of the library filter *and* scroll to a family; "All" clears. Only families with a preset available for the current Series get a tile. | Pure UI; change the strip. |
| 2 | Sliding track convention | Track 1 innermost; a fixed panel takes the outermost **glass** track; a mesh sash sits outside all of them at `tracks + 1`. Resolves 4.2's own contradiction. | `track_no` is a plain integer — becomes a per-Series setting. |
| 3 | Opening symbol | Triangle with its apex at the hinge, viewed from inside, plus an IN/OUT tag and a printed legend. | Drawing only; swap the glyph. |
| 4 | French casement | Two sashes hinged away from each other default to a **meeting** junction, no mullion. Any junction is overridable per boundary. | Change the default in `_default_junction`. |
| 5 | Mullion width | Drawn 60mm wide. A placeholder until profile section sizes exist (6.2). | Comes from the profile then. |
| 6 | Preset codes | `OPN-CFC`, `OPN-HOF`, `OPN-2A1B` exist outside 4.6's table, because they pre-date it and renaming them would change what saved designs refer to. | Rename only with a migration. |
| 7 | "Other" family | Seeded, though 4.1's table omits it, because 4.1's migration rule needs somewhere to put unknown categories. | Archive it once nothing lands there. |
| 8 | Starter glass list | Seven specs seeded (5mm clear, 6/8/10/12mm toughened, 6mm frosted, 24mm DGU) so Glass Specs can exist at all. `weight_kg_m2` = 2.5 x glass thickness; the DGU counts its two panes only, not the air gap. | Add, rename or archive freely. |
| 9 | Glass prices **[revisit]** | Every seeded glass product has a cost of **0**, marked "price to be set from the supplier list" on the product itself. Inventing rates would put fiction into a quote the moment pricing lands. | Enter the real per-m² rates; nothing else depends on the placeholder. |
| 10 | Deduction formulas **[revisit]** | Every seeded length and deduction formula (6.2, 6.4) is a plausible round number, not a shop-measured one: frame = `W`/`H`, palay = `PW - 10`, fixed glass = `PW - 60`, sash glass = `PW - 80`, mesh = `PW - 10`. | All editable per position and per Series; no code change. |
| 11 | Panel limits | `max_panel_w/h/kg` all seeded at **0**, which means "not checked", so nobody gets a warning based on an invented limit. | Enter the real ones per Series. |

Still open from section 2 and unchanged: T&T + fixed combos, double
pleated opening to the sides, vent sash shape, solid infill / AC cutout
as infill types, and the placeholder deductions and sash limits.

---

## 5. Phase 3 — Attachments  ✅ COMPLETE

### 5.1 Mesh types (attached to a panel) ✅
New `aw.mesh.type`: `name`, `code`, `family_id` (kind mesh), `mechanism`
= `fixed` | `hinged` | `pleated` | `roller`, `pull` = `left` | `right` |
`center` | `sides` | `vertical` | none, `active`,
`line_ids` → product + qty formula + condition formula (same line model as
hardware, see P4).

`aw.design.leaf`: `mesh_type_id` (optional), `mesh_hinge_side` (hinged
mesh; defaults to the panel's hinge side).

Seed: MSH-FIX, MSH-HNG, PLT-SGL-L, PLT-SGL-R, PLT-DBL-C, PLT-DBL-S,
PLT-ROL.

Note: a **Mesh leaf** (its own sliding panel on a mesh track) stays as a
leaf type for sliding systems. Attached mesh is for openable/fixed panels.

### 5.2 Infill types ✅
New `aw.infill.type`: `name`, `code`, `kind` = `glass` | `panel` |
`louvre` | `fan` | `ac`, `uses_glass` (bool), `active`, `line_ids`
(products/formulas).
`aw.design.leaf.infill_type_id` (default Glass).
Seed: ADD-GLS (Glass, default), ADD-INF (Solid panel), ADD-LOUV-F (Louvre
fixed), ADD-LOUV-A (Louvre adjustable), ADD-FAN (Exhaust fan), ADD-AC
(AC cutout).

### 5.3 Glass per panel ✅
`aw.design.leaf.glass_spec_id` — optional override; empty = the design's
glass. `aw.glass.spec.weight_kg_m2` (for checks, P4).

### 5.4 Georgian bars ✅
New `aw.grid.pattern`: `name`, `code`, `kind` = `rect` (rows × cols) |
`perimeter`, bar product, `active`.
`aw.design.leaf`: `grid_pattern_id`, `grid_rows`, `grid_cols`.
Seed: ADD-GRID-R (rectangular), ADD-GRID-P (perimeter).

### 5.5 Configurator ✅
Library click on a mesh/infill item → applies to the selected panel.
Right panel: mesh, infill, glass, grid fields for the selected panel.
Drawing: mesh = hatch overlay + badge; infill symbols (panel shading,
louvre slats, fan circle, AC box); grid bars drawn over glass.

Twin sash presets now seeded: TWN-FIX, TWN-SHL, TWN-SHR, TWN-TOP, TWN-BTM
(Casement series, mesh MSH-HNG / MSH-FIX attached).

**P3 test:** casement panel → apply PLT-SGL-L → hatch + badge shown →
bottom panel of a nested split → infill Louvre → another panel → frosted
glass override → grid 2×3 → save → reopen.

---

## 6. Phase 4 — BOM rules and explosion engine

**As built, differing from the text below** (the text is the original
plan; these are the decisions taken while implementing it):

1. **The formula module lives in `aw_fenestration_core`**, not the design
   module, because `aw.profile.position` is in core and core cannot
   import from a module that depends on it. `models/formula.py` has no
   Odoo imports at all, so `scripts/check_formulas.py` can run the real
   grammar against every seeded formula rather than a copy of it.
2a. **Palay Bead is seeded by NAME, not as `<record>`s.** Declaring them
   as records made duplicates of three positions the client had already
   created by hand — an xmlid cannot see a user-made record.
   `_seed_palay_bead_positions()` adopts a position of that name
   (case-insensitively) or creates one, and reconciles the duplicates:
   whichever record the Profile Section lines already point at survives,
   any lines on the loser are re-pointed first, and the seed xmlid is
   moved onto the survivor. **Any future seed into an open-ended,
   user-editable table should match on name for the same reason.**

2. **`Palay Bead - Top/Bottom/Sides` are seeded**, scope `panel_opening`,
   with the same deductions as Fixed Bead, and are the only positions
   flagged `is_required = False`: some sash profiles have the glazing
   channel built in, so a section with no Palay Bead line is normal.
   Every other position is required, and a design that *needs* one
   whose Profile Section has no line for it gets a warning naming both
   and why — "'Profile 1' has no 'Interlock' line (1 interlock junction
   in this design)". Without that, a structural profile missing from a
   section would drop out of the cut list silently, since the
   missing-product check only fires on a line that already exists.
   `is_required` defaults to **True**, so a position added later warns
   until someone decides it is optional.
3. **Every seeded position got a scope**, so none are currently
   unscoped. The "position has no scope, ignored by BOM" warning is
   there for positions added by hand afterwards.
4. **`aw.design.thickness_id` is hidden**, not removed (`groups=
   "base.group_no_one"`). Thickness is per profile and comes from the
   section line; only finish is genuinely design-level, so nothing in the
   BOM reads a design thickness. Kept rather than dropped because
   removing it would lose whatever existing designs have stored.
5. **Hardware lines keep the plain `qty` alongside `qty_formula`.**
   `_seed_qty_formulas()` copies the number into the formula once,
   fill-only-if-empty, so existing Hardware Sets keep working untouched.
6. **`scope` was added to hardware lines only.** Mesh, infill and grid
   lines are inherently per-panel, so a scope selector there would offer
   two choices that cannot be right.
7. **A missing product is reported, not dropped.** `product_id`, `role`
   and `length_mm` on `aw.design.bom.line` are no longer required,
   specifically so an unconfigured position produces a visible warning
   line instead of silently vanishing from the BOM.

### 6.1 Formula language
`safe_eval` expressions, variables (all mm):

| Var | Meaning |
|---|---|
| `W`, `H` | design overall width / height |
| `PW`, `PH` | panel width / height |
| `CW`, `CH` | width / height of the container the panel sits in |
| `N` | panels in the row |
| `T` | tracks (sliding) |

Functions: `min`, `max`, `round`, `ceil`, `floor`. Invalid formulas are
rejected on save with a clear message.

### 6.2 Profile positions — where and how many
`aw.profile.position` gains:
- `scope`: `frame` (once per design) | `panel_opening` (casement, awning,
  hopper, T&T, slider) | `panel_fixed` | `panel_mesh` | `mesh_attachment` |
  `junction_mullion` | `junction_meeting` | `junction_interlock` | `transom`
- `edge`: `top` | `bottom` | `sides` | `all`
- `default_length` formula, `default_angle` (45 / 90), `default_qty`

Seed defaults (placeholders **[revisit]**):

| Position | Scope | Edge | Length | Angle |
|---|---|---|---|---|
| Outer Frame - Top / Bottom | frame | top / bottom | `W` | 45 |
| Outer Frame - Sides | frame | sides | `H` | 45 |
| Palay - Top / Bottom | panel_opening | top / bottom | `PW - 10` | 45 |
| Palay - Sides | panel_opening | sides | `PH - 10` | 45 |
| Palay Bead - * | panel_opening | per edge | `PW - 40` / `PH - 40` | 45 |
| Fixed Bead - * | panel_fixed | per edge | `PW - 40` / `PH - 40` | 45 |
| Mesh - All Sides | panel_mesh + mesh_attachment | all | `PW - 10` / `PH - 10` | 45 |
| Divider - Vertical | junction_mullion | — | `CH` | 90 |
| Divider - Horizontal | transom | — | `CW` | 90 |
| Interlock | junction_interlock | — | `PH - 10` | 90 |
| Meeting Stile | junction_meeting | — | `PH - 10` | 90 |

`edge = all` generates 2 pieces of the width formula and 2 of the height
formula. `sides` generates 2.

`aw.profile.section.line` gains optional overrides: `length_formula`,
`cut_angle`, `qty_formula`. Empty = the position's default. Existing rule
kept: several lines on one position → lowest sequence is active, others are
alternates.

### 6.3 Hardware, mesh and infill lines
Common line fields: `product_id`, `qty_formula` (default `1`),
`condition_formula` (empty = always), scope (`design` | `panel` |
`junction`), leaf type filter (existing).
Examples: hinges `qty = 2 if PH <= 1200 else 3`; T&T gear chosen by
`condition PH <= 1400` vs `PH > 1400`; gasket per metre
`qty = 2*(PW+PH)/1000` with a metre UoM.

### 6.4 Series additions
`glass_fixed_w`, `glass_fixed_h`, `glass_sash_w`, `glass_sash_h`,
`mesh_w`, `mesh_h` (formulas; placeholders `PW - 60` etc. **[revisit]**);
limits `max_panel_w`, `max_panel_h`, `max_panel_kg`.

### 6.5 Explosion engine (`aw.design.action_explode`)
Walk frame → rows → leaves (recursive) → junctions → attachments.
Generate `aw.design.bom.line` with:
`kind` (profile / hardware / glass / mesh / infill / grid), product,
length, angle, qty × design qty, `panel_no`, label (`D1-P2 sash top`),
glass/mesh W×H and area. Run automatically on save; button stays for
re-run. Snapshot unit costs (pricing in P6).

### 6.6 Checks (panel in the configurator's right column)
Dimensions > 0; leaf types allowed by Series; panel size vs Series limits;
panel weight from glass `weight_kg_m2`; any profile piece longer than the
longest stock bar (18 ft) → error with **Split with coupler** action
(splits the design into two positions joined by a coupling mullion);
missing product on an active position → warning; a **required** position
the layout needs but the Profile Section has no line for → warning naming
the section, the position and the count that triggered it; no Profile
Section at all → one error rather than one warning per position.

**P4 test:** Double Glaze Sliding Profile 1, SLD-2P2T, 8 ft × 5 ft → explode
→ frame 4 pieces at 45°, 2 sashes × 4 palay pieces, 1 interlock, glass ×2
with deducted sizes, rollers/locks from the hardware set → hand-check two
lengths.

---

## 7. Phase 5 — Drawings and documents

- `aw.design.elevation_svg` (Text) — snapshot written by `save_layout()` from
  the configurator's rendered SVG, including numbers, symbols and legend.
- **Shop drawing PDF** per design: elevation, panel schedule (panel no,
  type, hinge/swing or track/direction, glass, mesh, infill, grid), profile
  cut list with angles and labels, hardware list.
- **Quote PDF**: extends the standard Sale PDF with each position's
  elevation thumbnail and spec lines.

---

## 8. Phase 6 — Cutting, pricing, stock

- **Cut list per sale order**: pool profile pieces by product variant
  (profile × thickness × finish); nest into stock bars 14 / 16 / 18 ft,
  mixed lengths allowed; kerf 5 mm; bars, cut sequence, angles, piece
  labels; offcuts ≥ 400 mm listed for return to stock. Settings (bar
  lengths, kerf, offcut minimum) in `ir.config_parameter`. Manual mitre saw
  output: group identical cuts, longest first, printable piece labels.
- **Pricing**: rates per product variant, effective-dated (native
  `product.supplierinfo` vs custom table — decide at P6), cost cascade
  (wastage, labour, margin), manual override, margin floor, price written
  to the sale order line.
- **Stock mode**: once length lots exist, plan cuts against actual lots and
  offcuts first, then new bars.

---

## 9. Later (noted, not scheduled)

Doors family (hinged/sliding doors, thresholds, door hardware); dual colour
(inside/outside); handle height per opening panel; sill / floor aperture
distance and survey checklist; coupled multi-frame assemblies beyond the
coupler split.
