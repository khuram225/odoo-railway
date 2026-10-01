# Print Production — domain context (addons_print)

Client: full-cycle print house, Heidelberg presses, in-house prepress (plate-making, imposition).
Order mix roughly 50/50: bound goods (notebooks, books) and boxes (cardboard, food boxes e.g. burger boxes).

## Tenancy
Print and aluminum serve different markets and never interact.

- Development: one Railway instance and database holding both.
- Implementation: print runs on its OWN Railway service and database, loading only
  `addons_print`. One image serves both; `addons_path` and `db_name` come from
  per-service environment variables (`ODOO_ADDONS_PATH`, `ODOO_DB_NAME`) -- see the
  repo CLAUDE.md's Deploy section for the table.

Shared codebase, isolated data AND isolated runtime. `pp_print_core` must never
depend on `aw_*`, `aluminum_*` or a shared `core_*` module: on the print service
those are not on the addons path at all, so such a dependency installs fine in
development and fails in implementation. `scripts/check_tenancy.py` enforces it.

## Architecture
- Odoo 19 Community. Native Sale / Purchase / Accounting (added when needed).
- Custom production engine. Do NOT extend Odoo MRP; work centres, routing and job tickets are our own models.
- Module `pp_print_core` depends only on base, mail, product (later sale, purchase, account,
  stock). Never on aw_*, aluminum_* or core_* -- enforced by scripts/check_tenancy.py.

## Rules (non-negotiable)
1. Nothing hard-coded: every rate, price, speed, markup, allowance and rule is a record editable in Odoo.
2. Rates and prices are effective-dated (`date_from`); an estimate uses the rates valid on its Calcdate.
3. Every calculated figure stores a human-readable "how it is calculated" text next to it.
4. Units: inches (dimensions), kg (weight), company currency PKR.
5. Each step ships with unit tests (`--test-tags=pp_print_core`); tests must pass on Odoo 19 before delivery.
6. Odoo 19 syntax: models.Constraint (not _sql_constraints), res.groups.privilege, <list>, <chatter/>, inline invisible.
7. Every ir.actions.act_window dict returned from Python or JS declares "views",
   e.g. [(False, "form")], not just view_mode.
8. Never add stored fields to shared core models (res.company, res.partner, res.users, product.template ...) in a
   normal step: deploy-before-upgrade breaks every page. Settings go to ir.config_parameter via
   res.config.settings(config_parameter=); per-record data goes on our own print.* models. (Step 1's product.template
   print_* fields are already deployed; any future change there is a planned, announced step.)

## Pre-commit hooks (all scan the whole repo; print code must pass every general one)
- check_python_names: no undefined names, no duplicate dict keys
- check_xml_comments: no "--" inside XML comments
- check_owl_names / check_owl_getters: OWL templates (if any) avoid reserved-word variables and JS globals; getters and methods must resolve
- check_act_window_views: every ir.actions.act_window dict returned from Python or JS declares "views"
- check_view_schemas: views validate against Odoo 19 RelaxNG (no expand=/string= on <group> in search views)
- check_inherited_xpaths: every xpath resolves against its parent arch
- check_view_buttons: every type="object" button names a real method on the model
- check_self_methods: every self._method() exists; every self.x = ... is a real field
- check_kanban_fields: no t-if/t-else/t-foreach/t-call directly on <field> in kanban; wrap in <t>
- check_load_order: no ref/parent/action/%(xmlid)d pointing at an xmlid defined later in the manifest order
  (finds manifests at any depth, so it covers addons_print/pp_print_core; reads "data" or 'data')
Aluminum-only hooks do not apply.

## Formulas in use
- Kg per sheet = W x H (in) x 0.00064516 x gsm / 1000 (same basis as the client's W x H x gsm / 3100 / 500).
- Cost per sheet: per-kg price x kg/sheet; per-sheet price; per-pack price / sheets per pack.
- Factor value: straight-line interpolation between diagram points, flat outside; factor group combines lines by Min / Max / Average / Multiply.

## Built so far (pp_print_core)
- Step 1 masters: product groups L1 (print.product.group), base products L2 (print.base.product, with estimating template),
  materials (product.template print_* fields + print.material.price), formats, work centres (print.workcenter: capability,
  status, factor group, make-ready, crew, dated rates), labour roles (dated rates), factor groups / config lines / diagram points,
  imposition table (DynamicsPrint codes), cost groups (time and material markups).
- Step 2 estimate: print.estimate (E01-/S01- sequences, versions, standards, statuses, customer, dates, run qty, run-on,
  format and W x H), print.estimate.page (page types with material), print.estimate.version (versions / bind legs),
  page type master, default page types per base product.
- Step 3 print-line engine on print.estimate.page (press, imposition, colours, designs, paperparts, workstyle, scrap method,
  extra/version plates, ink, colour comments); results and step log (print.estimate.page.log) written by _calculate() on
  every save; Print overview tab, line popup, Calculate button. Settings: pp_print_core.colour_strip_in, pp_print_core.gap_in
  (ir.config_parameter). Auto press = smallest offset press with enough colour units that fits (base-product rules replace
  it later).
  Print overview is display-only (computed print_line_ids); print settings are edited in the line dialog. Never put two
  writable One2many fields on the same inverse in one form.

## Next steps
4. Print general (prepress, finishing items, cutting), 5. binding and delivery, 6. costing (spec lines, cost points, margin cascade,
run-on), 7. client costing-sheet check, 8. price lists, 9. estimate to quotation / sale order; then job ticket, maintenance, labour time.

## Open decisions (resolve in Chat, then update here)
- Paper/board stock: trackable as sheets/units, weight and/or roll length, reams/packs with gsm + size as variants.
  Decide UoM categories and lot fields BEFORE stock products are created (when the stock dependency is added).
- Item coding structure: waiting for Rizwan's item master (raw materials, WIP, finished goods).
- Job ticket structure: bound goods vs boxes may need different routings.
- Machine rates, speeds, crews and markups: placeholders until the client confirms.

## Reference material
DynamicsPrint and Imp+ screen studies, the job taxonomy (Print_Job_Taxonomy_L1_L2.xlsx) and the client's
Costing Sheet _ HYEPL are in the claude.ai Project "Print Production - Odoo".
