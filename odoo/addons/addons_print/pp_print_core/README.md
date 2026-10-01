# Print Estimation

Step 1: module skeleton and master data. Step 2: the estimate (Calculation + Production overview). Step 3: print-line engine (Print overview).

Odoo 19 Community. Tested on Odoo 19: installs cleanly, all views render, 16 unit tests pass (`--test-tags=pp_print_core`).

## Install
1. Copy the `pp_print_core` folder into your custom addons folder in the repo (the one already on the addons path).
2. Commit and push; Railway redeploys.
3. In Odoo: Settings → activate developer mode → Apps → Update Apps List → search "Print Estimation" → Activate.
4. Settings → Users → give yourself **Print Production / Manager** (admin gets it automatically).

To update after changes: Apps → Print Estimation → Upgrade.

## What is in step 1 (all editable, nothing hard-coded)
Menu **Print Production → Configuration**:

| Menu | Model | Notes |
|---|---|---|
| Products → Product groups (L1) | print.product.group | 6 groups seeded from the costing-sheet analysis |
| Products → Base products (L2) | print.base.product | 23 seeded, each with an estimating template |
| Materials → Materials | product.template (+ print fields) | gsm, size in inches, thickness, pack; kg per sheet calculated; effective-dated prices per kg / sheet / pack / unit |
| Materials → Standard formats | print.format | inches |
| Production → Work centres | print.workcenter | type, status, capability, speed factor group, make-ready, crew, effective-dated machine rates |
| Production → Labour roles | print.labour.role | effective-dated hourly rates |
| Production → Factor groups | print.factor.group / print.factor | DynamicsPrint factor groups, config lines, diagram points and chart |
| Production → Imposition | print.imposition | DynamicsPrint imposition table, 12 seeded |
| Costing → Cost groups | print.cost.group | base groups with time and material markups |

Seed data is loaded with `noupdate`, so your edits survive upgrades. No rates or prices are seeded.

## Step 2: the estimate
Menu **Print Production → Estimates**:
- **Estimates**: opens on *My estimates, In process* (DynamicsPrint's default); remove the filters for all. Standards are green.
- **Standards**: templates. "Save as standard" on any estimate, "Use standard" to start a new one.
- Numbering from Settings → Technical → Sequences: `E01-` for estimates, `S01-` for standards (editable).
- Form tabs: **Production overview** (run qty., qty run on, format and W x H, ecolabel, template, Pagetypes, Versions - Bind legs, remarks), **General**, **Customer** (contact, phone, e-mail, external references, dates). History and activities are in the chatter.
- Buttons: Mark as quoted, New version (same number, version + 1), Copy estimate, Save as standard / Use standard, Lost, Cancel, Reset.
- Choosing a product fills its default page types (Configuration → Products → Base products → Default page types).
- Checks: text sections need even pages; versions must add up to run qty. (warning); run qty. > 0.
- Configuration → Products → Page types: Cover1, Text1, Part1 ... with their kind (text, cover, sheet).

## Step 3: print-line engine
- Estimate form, tab **Print overview**: one line per page type with Base (press), Imposition, colours F/B, results
  (press used, layout, sheets per copy, No. up, Pp./sht., passes, kg, print total, paper sheets, plates, paper cost).
  Empty Base / Imposition = Auto.
- Magnifier on a line: bottom panel (formats, print net/total, scrap method and value, plates, paper usage, colour comments,
  ink, wash-ups) and the step-by-step **Calculation** log.
- Results recalculate on every save; **Calculate** button forces it. Errors show in red with the reason.
- Print Production → Configuration → **Settings**: colour strip depth and gap between groups (stored as system parameters, no new columns on core tables).
- Upgrade note: text lines created before step 3 get 4/4 colours; open each old estimate and save or press Calculate.

## Rules followed in every step
- Every rate, price, speed, markup and allowance is a record, never a constant in code.
- Rates and prices are effective-dated; an estimate will use the rates valid on its date.
- Every calculated figure has a "how it is calculated" text next to it.
- Units: inches, kg; currency = company currency (set it to PKR).

## Formulas in this step
- Kg per sheet = W (in) x H (in) x 0.00064516 x gsm / 1000 (same basis as the costing sheet's W x H x gsm / 3100 / 500).
- Cost per sheet: per-kg price x kg per sheet; per-sheet price; or per-pack price / sheets per pack.
- Factor value: straight-line interpolation between diagram points, flat outside them; a factor group combines its lines by Min / Max / Average / Multiply.

## Version notes
Written for Odoo 19: `models.Constraint` instead of `_sql_constraints`, security groups under a `res.groups.privilege`, `<list>` views and `<chatter/>`.
