# Piped into `odoo shell` by scripts/rehearse.sh, on the REHEARSAL database
# (never production): explode every design again and compare its stored cost,
# price and BOM with the result. The transaction is rolled back at the end.
#
# Prints REHEARSAL lines; the last is "REHEARSAL designs different N".
env = globals()['env']        # put in scope by `odoo shell`
try:
    same = different = 0
    for design in env['aw.design'].with_context(active_test=False).search([]):
        def snapshot():
            return (round(design.cost_total, 2), round(design.price_total, 2),
                    sorted((l.kind, l.label or '', round(l.length_mm or 0, 2),
                            l.qty, l.product_id.id)
                           for l in design.bom_line_ids))
        before = snapshot()
        design._explode()
        after = snapshot()
        ok = before == after
        same += ok
        different += not ok
        print("REHEARSAL design %s cost/price %s -> %s, %s BOM lines -> %s: %s" % (
            design.display_name, before[:2], after[:2], len(before[2]),
            len(after[2]), "SAME" if ok else "DIFFERENT"))
    print("REHEARSAL designs same %s" % same)
    print("REHEARSAL designs different %s" % different)
finally:
    env.cr.rollback()
