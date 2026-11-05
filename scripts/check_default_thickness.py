#!/usr/bin/env python3
"""The thickness a component added to a window starts with.

Runs the REAL rule, `default_thickness` out of
aw_fenestration_core/models/thickness.py (Odoo-free for exactly this),
because the bug it guards was an empty thickness reaching a profile with
several: "HD-3 GROOVE offers no '' thickness, only 1.6MM, 2MM". The cases
are ones whose answer can be read off by hand.
"""
import importlib.util
import sys
from pathlib import Path

MODULE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
          / 'aw_fenestration_core' / 'models' / 'thickness.py')
spec = importlib.util.spec_from_file_location('aw_thickness', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
rule = mod.default_thickness

CASES = [
    # (available, used, preferred, expected, why)
    (['1.6MM'], [], '', '1.6MM', 'one thickness is not a choice'),
    (['1.6MM', '2MM'], [], '', '1.6MM', 'several, none used: the lowest'),
    (['2MM', '1.6MM'], [], '', '1.6MM', 'the order offered does not matter'),
    (['1.6MM', '2MM'], ['2MM'], '', '2MM', 'what the window already uses'),
    (['1.6MM', '2MM'], ['3MM', '2MM'], '', '2MM', 'a used one it is not sold in is skipped'),
    (['1.6MM', '2MM'], ['2MM'], '1.6MM', '1.6MM', 'the position\'s own thickness first'),
    (['1.6MM', '2MM'], [], '3MM', '1.6MM', 'a preference it is not sold in is ignored'),
    (['1.2MM', '1.5MM', '1.6MM', '2MM', '3MM'], [], '', '1.2MM', 'numeric, not alphabetical'),
    (['10MM', '2MM'], [], '', '2MM', '2 is lower than 10'),
    (['Normal', '2MM'], [], '', '2MM', 'a named grade sorts after a number'),
    (['Standard'], [], '', 'Standard', 'a named grade on its own'),
    ([], ['2MM'], '', '', 'nothing offered: nothing to pick, and no error'),
]

failed = 0
for available, used, preferred, expected, why in CASES:
    got = rule(available, used, preferred)
    ok = got == expected
    failed += not ok
    print(('  ok   ' if ok else '  FAIL ') + why + ('' if ok else ' (got %r, want %r)' % (got, expected)))
# the failing case from the report, by name
got = rule(['1.6MM', '2MM'], [], '')
assert got, "the result must never be empty while the profile offers any"
if failed:
    print('%d FAILED' % failed)
    sys.exit(1)
print('default thickness: all %d cases pass' % len(CASES))
