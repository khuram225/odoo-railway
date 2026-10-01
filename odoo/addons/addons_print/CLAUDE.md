# Print Production — domain context (addons_print)

Client: full-cycle print house, Heidelberg presses, in-house prepress (plate-making, imposition).
Order mix roughly 50/50: bound goods (notebooks, books) and boxes (cardboard, food boxes e.g. burger boxes).

## Tenancy
For now one database holds both aluminum and print modules (decided: no second domain yet).
Later: own database `print` on print.mycrewvault.com (dbfilter = ^%d$). Shared codebase, isolated data.

## Architecture
- Odoo 19 Community. Native Sale / Purchase / Accounting (added when needed).
- Custom production engine. Do NOT extend Odoo MRP; work centres, routing and job tickets are our own models.
- Module `pp_print_core` depends only on base, mail, product (later sale, purchase, account, stock). Never on aw_*.

## Rules (non-negotiable)
1. Nothing hard-coded: every rate, price, speed, markup, allowance and rule is a record editable in Odoo.
2. Rates and prices are effective-dated (`date_from`); an estimate uses the rates valid on its Calcdate.
3. Every calculated figure stores a human-readable "how it is calculated" text next to it.
4. Units: inches (dimensions), kg (weight), company currency PKR.
5. Each step ships with unit tests (`--test-tags=pp_print_core`); tests must pass on Odoo 19 before delivery.
6. Odoo 19 syntax: models.Constraint (not _sql_constraints), res.groups.privilege, <list>, <chatter/>, inline invisible.

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

## Next steps
3. Print-line engine (Print overview): base press, colours, imposition, scrap, plates, paper sheets and kg, stored calculation log.
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
