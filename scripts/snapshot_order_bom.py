# -*- coding: utf-8 -*-
"""Snapshot one order's windows -- BOM, costs, price -- as JSON.

Run it through `odoo shell`, which provides `env`:

    odoo shell -c /etc/odoo/odoo.conf -d odoo < scripts/snapshot_order_bom.py

It RE-RUNS each window's explosion with whatever code is deployed, so
two snapshots (before and after a change to the explosion) can be
compared line by line. That means it does write -- BOM lines, costs,
variants -- but ONLY inside a transaction that is always rolled back,
here and again at the end, and `commit` is never called. Nothing it does
reaches the database.

    SNAP_ORDER=S00005     which order (default S00005)

Output is between SNAPSHOT_BEGIN and SNAPSHOT_END markers so it can be
cut out of the shell's startup noise.
"""
import json
import os

ORDER = os.environ.get('SNAP_ORDER') or 'S00005'

# `env` is provided by `odoo shell`; fetched by name so a linter that
# has never heard of the shell does not take it for an undefined name.
_shell_env = globals()['env']
env = _shell_env(context=dict(
    _shell_env.context, tracking_disable=True, mail_notrack=True))
cr = env.cr
cr.execute('SAVEPOINT snapshot_order_bom')


def num(value, digits=4):
    return round(value or 0.0, digits)


BOM_FIELDS = (
    'kind', 'label', 'panel_no', 'unit_no', 'piece_ref', 'length_mm',
    'cut_angle', 'qty', 'glass_w', 'glass_h', 'area_sqm', 'unit_cost',
    'line_cost', 'cost_note', 'is_changed')

out = {'order': ORDER, 'designs': [], 'checks': {}}
try:
    order = env['sale.order'].search([('name', '=', ORDER)], limit=1)
    if not order:
        raise SystemExit('No order named %s' % ORDER)
    designs = order.aw_design_ids.sorted(lambda d: d.id)
    for design in designs:
        design._explode()
        design.flush_recordset()
        bom_model = env['aw.design.bom.line']
        fields_here = [f for f in BOM_FIELDS if f in bom_model._fields]
        lines = []
        for line in design.bom_line_ids.sorted(lambda l: (l.sequence, l.id)):
            row = {}
            for field in fields_here:
                value = line[field]
                row[field] = num(value) if isinstance(value, float) else value
            row['product'] = line.product_id.display_name or ''
            row['glass_spec'] = line.glass_spec_id.display_name or ''
            lines.append(row)
        out['designs'].append({
            'name': design.name,
            'qty': design.qty,
            'size_mm': [num(design.width_mm), num(design.height_mm)],
            'spec': design.template_id.display_name or '',
            'system': design.window_series_id.display_name or '',
            'finish': design.finish_id.name or '',
            'price_total': num(design.price_total, 2),
            'cost_total': num(design.cost_total, 2),
            'basic_value': num(design.basic_value, 2),
            'bom': lines,
        })
        out['checks'][design.name] = sorted(
            (c.level, c.message) for c in design.check_line_ids)
finally:
    # Always. Nothing above is ever committed.
    cr.execute('ROLLBACK TO SAVEPOINT snapshot_order_bom')
    cr.rollback()

print('SNAPSHOT_BEGIN')
print(json.dumps(out, sort_keys=True, indent=1, default=str))
print('SNAPSHOT_END')
