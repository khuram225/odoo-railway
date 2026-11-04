#!/usr/bin/env python3
"""The 11 saved glass specs, as stacks.

Runs the REAL recipe table (models/glass_recipes.py, no Odoo imports) on the
spec names that exist on production. A wrong gap width, a lost remark or a
sheet that is not 6 mm when the name says 6 would change what a quote says
about the glass, with no error anywhere."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(
    ROOT, 'odoo/addons/aw_fenestration_design/models/glass_recipes.py')
spec = importlib.util.spec_from_file_location('glass_recipes', PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

fail = []


def check(ok, message):
    if not ok:
        fail.append(message)


def shape(name, priced=False):
    parts = mod.recipe_for_spec(name, priced)
    return None if parts is None else [
        (p['kind'], p.get('thickness_mm', p.get('gap_mm')), p.get('remark', ''))
        for p in parts]


EXPECTED = {
    '5mm Clear': [('sheet', 5.0, '')],
    '6mm Clear Toughened': [('sheet', 6.0, 'was: Clear Toughened')],
    '6mm Frosted Toughened': [('sheet', 6.0, 'was: Frosted Toughened')],
    '8mm Clear Toughened': [('sheet', 8.0, 'was: Clear Toughened')],
    '10mm Clear Toughened': [('sheet', 10.0, 'was: Clear Toughened')],
    '12mm Clear Toughened': [('sheet', 12.0, 'was: Clear Toughened')],
    '24mm DGU (6 + 12 + 6)': [('sheet', 6.0, ''), ('gap', 12.0, ''),
                              ('sheet', 6.0, '')],
    '6+10+6 Clear Tempered': [('sheet', 6.0, 'was: Clear Tempered'),
                              ('gap', 10.0, ''),
                              ('sheet', 6.0, 'was: Clear Tempered')],
    '6+10+6 Frosted Tempered': [('sheet', 6.0, 'was: Frosted Tempered'),
                                ('gap', 10.0, ''),
                                ('sheet', 6.0, 'was: Frosted Tempered')],
    '6+10+8 Clear Tempered': [('sheet', 6.0, 'was: Clear Tempered'),
                              ('gap', 10.0, ''),
                              ('sheet', 8.0, 'was: Clear Tempered')],
    '8+8+8 Clear Tempered': [('sheet', 8.0, 'was: Clear Tempered'),
                             ('gap', 8.0, ''),
                             ('sheet', 8.0, 'was: Clear Tempered')],
}
for name, want in EXPECTED.items():
    got = shape(name)
    check(got == want, '%s: %s, expected %s' % (name, got, want))
check(len(EXPECTED) == 11, 'the 11 specs')
check(mod.recipe_for_spec('Mystery glass') is None, 'an unknown name is None')

unpriced = mod.recipe_for_spec('24mm DGU (6 + 12 + 6)', priced=False)
check(all(p['manual_zero'] for p in unpriced if p['kind'] == 'sheet'),
      'zero-priced sheets carry a manual 0')
priced = mod.recipe_for_spec('10mm Clear Toughened', priced=True)
check(not priced[0]['manual_zero'], 'a priced spec takes the list rate')
gap = [p for p in unpriced if p['kind'] == 'gap'][0]
check((gap['gas'], gap['spacer_type'], gap['spacer_colour']) ==
      ('Air', 'Aluminium', 'Silver') and gap['default_gap'],
      'a migrated gap is a flagged default: Air, Aluminium, Silver')

if fail:
    print('FAIL: glass spec recipes')
    for message in fail:
        print('  - ' + message)
    sys.exit(1)
print('Glass recipes: %d specs read as stacks; remarks, gaps and the manual 0 '
      'as agreed.' % len(EXPECTED))
