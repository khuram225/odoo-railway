#!/usr/bin/env python3
"""Every glass rate maps to exactly one Glass Sheet variant.

Runs the REAL naming rules (models/glass_variants.py, no Odoo imports) on
the real Ghani list and checks that the 61 rates give 61 DIFFERENT
(colour, kind, thickness) combinations, that every glass type the list uses
has a colour and a kind, that the thickness is one the product carries, and
that the mapping can be turned back into the type and thickness it came
from. A rate that maps to nothing, or two rates that map to one variant,
would price a window from the wrong sheet without any error."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, 'odoo/addons/aw_fenestration_core/models')


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(MODELS, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


paste = load('glass_paste')
var = load('glass_variants')
FIXTURE = os.path.join(
    ROOT, 'odoo/addons/aw_fenestration_design/tests/data/'
          'ghani_glass_2026_07_01.txt')
with open(FIXTURE, encoding='utf-8') as handle:
    rows = paste.parse_glass_paste(handle.read())

fail = []
seen = {}
for row in rows:
    try:
        colour, kind = var.type_parts(row['type'])
    except ValueError as error:
        fail.append('%s %smm: %s' % (row['type'], row['thickness_mm'], error))
        continue
    mm = row['thickness_mm']
    if mm not in var.THICKNESSES_MM:
        fail.append('%s %smm: thickness not on the product' % (row['type'], mm))
    if var.type_name(colour, kind) != row['type']:
        fail.append('%s does not round-trip (%s, %s)' % (row['type'], colour, kind))
    key = (colour, kind, mm)
    if key in seen:
        fail.append('%s %smm and %s map to the SAME variant %s'
                    % (row['type'], mm, seen[key], key))
    seen[key] = '%s %smm' % (row['type'], mm)

if len(rows) != 61 or len(seen) != 61:
    fail.append('expected 61 rates -> 61 variants, got %d -> %d'
                % (len(rows), len(seen)))
for bad in ('Purple', 'WC', 'Ref. Pink', ''):
    try:
        var.type_parts(bad)
        fail.append('%r should not map to a variant' % bad)
    except ValueError:
        pass
if var.thickness_name(6) != '6 mm' or var.thickness_mm('6 mm') != 6.0:
    fail.append('thickness naming')

if fail:
    print('FAIL: glass rate -> variant mapping')
    for message in fail:
        print('  - ' + message)
    sys.exit(1)
print('Glass variants: %d rates map to %d different variants (%d types x '
      'thicknesses); every type has a colour and a kind.'
      % (len(rows), len(seen), len({r['type'] for r in rows})))
