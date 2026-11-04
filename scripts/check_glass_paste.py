#!/usr/bin/env python3
"""Runs the REAL glass price-list reader (models/glass_paste.py, which has
no Odoo imports) against the Ghani Glass Ltd list of 1 July 2026 and
checks the splitting rules: colours split on "/" and in brackets, "5mm/6mm"
becomes two rates, Ref. is a separate type, WC and CC are kept as written.
A wrong split writes a wrong price silently, so the counts are exact."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(
    ROOT, 'odoo/addons/aw_fenestration_core/models/glass_paste.py')
spec = importlib.util.spec_from_file_location('glass_paste', PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LIST = """Type\tThickness\tPrice
Clear\t2mm\t127.39
Clear\t3mm\t190.38
Clear\t4mm\t231.89
Clear\t5mm\t247.63
Clear\t6mm\t265.52
Clear\t8mm\t463.06
Clear\t10mm\t611.92
Clear\t12mm\t745.04
WC (Grn, Brw, Blue)\t5mm\t231.88
WC (Grn, Brw, Blue)\t6mm\t248.64
Green/Brown\t8mm\t948.13
Blue\t8mm\t971.78
Grey\t8mm\t1055.78
Brown\t12mm\t1458.66
Green/Blue\t12mm\t1508.85
Grey\t12mm\t1643.78
Green/Brown/Blue/Ford Blue\t4mm\t287.36
Green/Brown/Blue/Ford Blue\t5mm\t345.70
Green/Brown/Blue/Ford Blue\t6mm\t359.56
Ref. Green/Brown/Blue/Ford Blue\t4mm\t336.95
Ref. Green/Brown/Blue/Ford Blue\t5mm\t413.53
Ref. Green/Brown/Blue/Ford Blue\t6mm\t429.57
CC (Grn, Brw, Blue)\t5mm\t328.37
CC (Grn, Brw, Blue)\t6mm\t341.53
Grey\t4mm\t323.56
Grey\t5mm\t385.91
Grey\t6mm\t399.91
Ref. Grey\t4mm\t387.69
Ref. Grey\t5mm\t460.96
Ref. Grey\t6mm\t482.32
Ref. Clear\t6mm\t384.57
CC (Grey)\t5mm/6mm\t389.29
"""

fail = []


def check(ok, message):
    if not ok:
        fail.append(message)


rows = mod.parse_glass_paste(LIST)
by = {(r['type'], r['thickness_mm']): r['price'] for r in rows}
check(len(rows) == 61, 'expected 61 rates, got %s' % len(rows))
check(len(by) == len(rows), 'a (type, thickness) came out twice')
check(by.get(('Clear', 10.0)) == 611.92, 'Clear 10mm')
check(by.get(('WC Green', 5.0)) == 231.88 and by.get(('WC Blue', 6.0)) == 248.64,
      'WC colours not split / not kept as written')
check(by.get(('Green', 8.0)) == 948.13 and by.get(('Brown', 8.0)) == 948.13
      and by.get(('Blue', 8.0)) == 971.78, 'Green/Brown 8mm')
check(by.get(('Ford Blue', 4.0)) == 287.36, 'Ford Blue 4mm')
check(by.get(('Ref. Ford Blue', 6.0)) == 429.57, 'Ref. Ford Blue 6mm')
check(by.get(('CC Grey', 5.0)) == 389.29 and by.get(('CC Grey', 6.0)) == 389.29,
      'CC (Grey) 5mm/6mm should be two rates')
check(by.get(('CC Brown', 5.0)) == 328.37, 'CC Grn/Brw/Blue')
check(by.get(('Grey', 5.0)) == 385.91, 'plain Grey 5mm')
check(by.get(('Ref. Clear', 6.0)) == 384.57, 'Ref. Clear')
reflective = [r for r in rows if r['reflective']]
check(len(reflective) == 12 + 3 + 1, 'reflective rates: %s' % len(reflective))
check(all(r['type'].startswith('Ref. ') for r in reflective), 'Ref. naming')
check(mod.norm_type('Ref.Green') == mod.norm_type('ref. green'), 'norm_type')
check(mod.parse_thickness('5mm/6mm') == [5.0, 6.0], 'parse_thickness')
check(mod.parse_glass_paste('Heading only') == [], 'a heading is not a row')

# -- robustness: separators, whole-type comparison, nothing dropped quietly
NB = chr(0xa0)
mixed = ('Ref.' + NB + 'Grey' + NB + NB + '4mm ' + NB + '387.69\n'
         'Grey   4mm\t323.56\n')
rows2, skipped2 = mod.parse_glass_paste_report(mixed)
check(skipped2 == [], 'NBSP / space runs should separate the fields')
check({(r['type'], r['price']) for r in rows2}
      == {('Ref. Grey', 387.69), ('Grey', 323.56)},
      'Ref. Grey and Grey must stay two types: %s' % rows2)
check(mod.norm_type('Ref. Grey') != mod.norm_type('Grey'), 'whole-type compare')
rows3, skipped3 = mod.parse_glass_paste_report(
    'WC (Grn, Brw, Blue)\n5mm\t231.88\nGreen 4mm 287.36 336.95\n'
    'Clear 6mm 265.52\n')
check([r['type'] for r in rows3] == ['Clear'],
      'only the clean row is read: %s' % rows3)
check(len(skipped3) == 2 and '5mm' in skipped3[0] and '336.95' in skipped3[1],
      'unread lines must be handed back, headings (no digit) not: %s'
      % skipped3)
check(mod.split_row('Clear 6mm') is None, 'a row without a price is not a row')
check(mod.split_row('Clear 6 265.52') is None, 'a thickness needs mm')

# -- the REAL Ghani list as it was sent (flat lines, one rate each)
REAL = os.path.join(
    ROOT, 'odoo/addons/aw_fenestration_design/tests/data/'
          'ghani_glass_2026_07_01.txt')
with open(REAL, encoding='utf-8') as handle:
    real_rows, real_skipped = mod.parse_glass_paste_report(handle.read())
real = {(r['type'], r['thickness_mm']): r['price'] for r in real_rows}
check(len(real_rows) == 61 and len(real) == 61,
      'real list: %d rows, %d distinct' % (len(real_rows), len(real)))
check(real_skipped == [], 'real list: unread lines %s' % real_skipped)
for key, price in ((('Clear', 6.0), 265.52), (('Grey', 6.0), 399.91),
                   (('Ref. Grey', 6.0), 482.32), (('WC Green', 6.0), 248.64)):
    check(real.get(key) == price, 'real list %s: %s' % (key, real.get(key)))
check(len({r['type'] for r in real_rows}) == 19, 'real list: 19 types')

if fail:
    print('FAIL: glass price-list reader')
    for message in fail:
        print('  - ' + message)
    sys.exit(1)
print('Glass price list: %d rates from %d rows; colours, thicknesses, Ref., '
      'WC and CC split as written.' % (len(rows), 32))
